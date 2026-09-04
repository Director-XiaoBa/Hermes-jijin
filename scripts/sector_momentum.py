#!/usr/bin/env python3
"""
板块动量计算 — 5维度指标计算
读取sector_flow_daily历史数据，计算动量指标和综合信号。

用法:
    python3 sector_momentum.py              # 计算今天的动量
    python3 sector_momentum.py 2026-09-04   # 指定日期
    python3 sector_momentum.py --backfill   # 回填最近10天
"""
import sys, os
from datetime import datetime, date, timedelta
from decimal import Decimal

import pymysql

DB_CONFIG = {
    'host': '127.0.0.1', 'port': 3306,
    'user': 'fund_admin', 'password': 'FundR2026!db',
    'database': 'fund_research', 'charset': 'utf8mb4'
}

def get_connection():
    return pymysql.connect(**DB_CONFIG)

def get_market_data(conn, target_date):
    """获取大盘数据（上证指数涨跌幅）"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT daily_return FROM market_daily 
        WHERE trade_date = %s AND index_name = '上证指数'
    """, (target_date,))
    row = cursor.fetchone()
    return float(row[0]) if row else 0.0

def get_sector_flow_history(conn, sector_name, days=10):
    """获取板块资金流向历史"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT trade_date, main_netflow, sector_name
        FROM sector_flow_daily 
        WHERE sector_name = %s 
        ORDER BY trade_date DESC LIMIT %s
    """, (sector_name, days))
    return cursor.fetchall()

def get_all_sectors_today(conn, target_date):
    """获取今天所有行业板块"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sector_name, main_netflow 
        FROM sector_flow_daily 
        WHERE trade_date = %s
        ORDER BY main_netflow DESC
    """, (target_date,))
    return cursor.fetchall()

def calc_consecutive_inflow(flows):
    """计算连续流入天数"""
    count = 0
    for f in flows:
        if float(f[1]) > 0:
            count += 1
        else:
            break
    return count

def calc_flow_direction(flows):
    """计算流向变化"""
    if len(flows) < 2:
        return 'stable', 0
    
    today = float(flows[0][1])
    yesterday = float(flows[1][1])
    
    if yesterday < 0 and today > 0:
        return 'turning_in', today - yesterday
    elif yesterday > 0 and today < 0:
        return 'turning_out', today - yesterday
    elif today > yesterday:
        return 'accelerating', today - yesterday
    elif today < yesterday:
        return 'decelerating', today - yesterday
    else:
        return 'stable', 0

def score_dimension_fund(flow_1d, flow_3d, flow_5d, flow_direction, consecutive_days):
    """资金维度打分（-2 ~ +2）"""
    score = 0
    
    # 流向变化（最重要）
    if flow_direction == 'turning_in':
        score += 2  # 拐点，强信号
    elif flow_direction == 'accelerating':
        score += 1  # 加速中
    elif flow_direction == 'turning_out':
        score -= 2  # 转流出，强负面
    elif flow_direction == 'decelerating':
        score -= 1  # 减速
    
    # 连续流入天数
    if consecutive_days >= 5:
        score -= 1  # 涨太多了
    elif 1 <= consecutive_days <= 3:
        score += 1  # 刚启动
    
    # 3日累计
    if flow_3d and flow_3d > 0:
        score += 0.5
    
    return max(-2, min(2, score))

def score_dimension_momentum(sector_return, relative_strength, rank_change):
    """动量维度打分（-2 ~ +2）"""
    score = 0
    
    # 相对强度
    if relative_strength > 2:
        score += 2
    elif relative_strength > 1:
        score += 1
    elif relative_strength < -2:
        score -= 2
    elif relative_strength < -1:
        score -= 1
    
    # 排名变化
    if rank_change and rank_change > 10:
        score += 1
    elif rank_change and rank_change > 5:
        score += 0.5
    elif rank_change and rank_change < -10:
        score -= 1
    
    return max(-2, min(2, score))

def score_dimension_volume(volume_ratio):
    """成交量维度打分（-2 ~ +2）"""
    if volume_ratio is None:
        return 0
    
    if volume_ratio > 2:
        return 1.5  # 明显放量
    elif volume_ratio > 1.5:
        return 1    # 放量
    elif volume_ratio > 1:
        return 0.5  # 温和放量
    elif volume_ratio < 0.5:
        return -1   # 严重缩量
    elif volume_ratio < 0.7:
        return -0.5 # 缩量
    else:
        return 0

def score_dimension_market(market_return, north_flow):
    """大盘环境打分（-2 ~ +2）"""
    score = 0
    
    if market_return > 1:
        score += 2
    elif market_return > 0.3:
        score += 1
    elif market_return < -1:
        score -= 2
    elif market_return < -0.3:
        score -= 1
    
    if north_flow and north_flow > 0:
        score += 0.5
    elif north_flow and north_flow < 0:
        score -= 0.5
    
    return max(-2, min(2, score))

def calc_composite_score(fund_score, momentum_score, volume_score, catalyst_score, market_score):
    """计算综合得分"""
    # 权重
    weights = {
        'fund': 0.35,
        'momentum': 0.25,
        'volume': 0.15,
        'catalyst': 0.15,
        'market': 0.10
    }
    
    # 大盘环境一票否决
    if market_score <= -1.5:
        return -2, 'avoid', 0
    
    score = (
        fund_score * weights['fund'] +
        momentum_score * weights['momentum'] +
        volume_score * weights['volume'] +
        catalyst_score * weights['catalyst'] +
        market_score * weights['market']
    )
    
    # 信号等级
    if score >= 1.5:
        signal, position = 'strong_buy', 30
    elif score >= 0.8:
        signal, position = 'buy', 10
    elif score >= 0:
        signal, position = 'watch', 0
    else:
        signal, position = 'avoid', 0
    
    return round(score, 2), signal, position

def calculate_momentum(target_date):
    """计算指定日期的板块动量"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 获取大盘数据
    market_return = get_market_data(conn, target_date)
    
    # 获取北向资金
    cursor.execute("""
        SELECT total_netflow FROM north_flow_daily 
        WHERE trade_date = %s
    """, (target_date,))
    north_row = cursor.fetchone()
    north_flow = float(north_row[0]) if north_row else None
    
    # 获取所有行业板块
    sectors = get_all_sectors_today(conn, target_date)
    
    results = []
    for sector_name, flow_1d in sectors:
        flow_1d = float(flow_1d)
        
        # 获取历史数据
        history = get_sector_flow_history(conn, sector_name, 10)
        if len(history) < 2:
            continue
        
        # 计算指标
        flow_3d = sum(float(h[1]) for h in history[:3])
        flow_5d = sum(float(h[1]) for h in history[:5])
        flow_10d = sum(float(h[1]) for h in history[:10])
        
        flow_direction, flow_accel = calc_flow_direction(history)
        consecutive_days = calc_consecutive_inflow(history)
        
        # 排名（需要全量数据）
        all_flows = [(s[0], float(s[1])) for s in sectors]
        all_flows.sort(key=lambda x: x[1], reverse=True)
        rank_today = next((i+1 for i, (n, _) in enumerate(all_flows) if n == sector_name), None)
        
        # 昨日排名
        cursor.execute("""
            SELECT sector_name, main_netflow FROM sector_flow_daily 
            WHERE trade_date = (
                SELECT MAX(trade_date) FROM sector_flow_daily 
                WHERE trade_date < %s AND sector_name = %s
            ) AND sector_name = %s
        """, (target_date, sector_name, sector_name))
        yesterday_row = cursor.fetchone()
        
        rank_yesterday = None
        if yesterday_row:
            # 获取昨日所有板块排名
            prev_date = history[1][0] if len(history) > 1 else None
            if prev_date:
                cursor.execute("""
                    SELECT sector_name, main_netflow FROM sector_flow_daily 
                    WHERE trade_date = %s ORDER BY main_netflow DESC
                """, (prev_date,))
                prev_sectors = cursor.fetchall()
                rank_yesterday = next((i+1 for i, (n, _) in enumerate(prev_sectors) if n == sector_name), None)
        
        rank_change = None
        if rank_today and rank_yesterday:
            rank_change = rank_yesterday - rank_today  # 正=排名上升
        
        # 相对强度（简化：用资金流入排名变化近似）
        relative_strength = 0  # 需要板块涨跌幅数据，暂用0
        
        # 成交量（简化：用资金流入变化近似）
        volume_ratio = None
        if len(history) >= 5:
            avg_5d = sum(abs(float(h[1])) for h in history[:5]) / 5
            if avg_5d > 0:
                volume_ratio = abs(flow_1d) / avg_5d
        
        # 打分
        fund_score = score_dimension_fund(flow_1d, flow_3d, flow_5d, flow_direction, consecutive_days)
        momentum_score = score_dimension_momentum(0, relative_strength, rank_change)
        volume_score = score_dimension_volume(volume_ratio)
        catalyst_score = 0  # 暂无催化剂数据
        market_score = score_dimension_market(market_return, north_flow)
        
        total_score, signal_type, suggested_position = calc_composite_score(
            fund_score, momentum_score, volume_score, catalyst_score, market_score
        )
        
        # 存储
        try:
            cursor.execute("""
                INSERT INTO sector_momentum_daily
                (trade_date, sector_name, sector_type,
                 flow_1d, flow_3d, flow_5d, flow_10d, flow_accel, flow_direction,
                 consecutive_inflow_days,
                 rank_today, rank_yesterday, rank_change,
                 volume_today, volume_5d_avg, volume_ratio,
                 fund_score, momentum_score, volume_score, catalyst_score, market_score,
                 total_score, signal_type, suggested_position)
                VALUES (%s, %s, 'industry',
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    flow_1d=VALUES(flow_1d), flow_3d=VALUES(flow_3d),
                    flow_5d=VALUES(flow_5d), flow_10d=VALUES(flow_10d),
                    flow_accel=VALUES(flow_accel), flow_direction=VALUES(flow_direction),
                    consecutive_inflow_days=VALUES(consecutive_inflow_days),
                    rank_today=VALUES(rank_today), rank_yesterday=VALUES(rank_yesterday),
                    rank_change=VALUES(rank_change),
                    volume_ratio=VALUES(volume_ratio),
                    fund_score=VALUES(fund_score), momentum_score=VALUES(momentum_score),
                    volume_score=VALUES(volume_score), catalyst_score=VALUES(catalyst_score),
                    market_score=VALUES(market_score),
                    total_score=VALUES(total_score), signal_type=VALUES(signal_type),
                    suggested_position=VALUES(suggested_position)
            """, (
                target_date, sector_name,
                flow_1d, flow_3d, flow_5d, flow_10d, flow_accel, flow_direction,
                consecutive_days,
                rank_today, rank_yesterday, rank_change,
                abs(flow_1d), avg_5d if len(history) >= 5 else None, volume_ratio,
                fund_score, momentum_score, volume_score, catalyst_score, market_score,
                total_score, signal_type, suggested_position
            ))
        except Exception as e:
            print(f"  存储失败 {sector_name}: {e}")
        
        results.append({
            'name': sector_name,
            'flow_1d': flow_1d,
            'flow_3d': round(flow_3d, 2),
            'flow_direction': flow_direction,
            'consecutive_days': consecutive_days,
            'rank_today': rank_today,
            'rank_change': rank_change,
            'total_score': total_score,
            'signal': signal_type
        })
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return results

def main():
    if '--backfill' in sys.argv:
        # 回填最近10天
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT trade_date FROM sector_flow_daily ORDER BY trade_date DESC LIMIT 10")
        dates = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        
        for d in dates:
            print(f"\n计算 {d}...")
            results = calculate_momentum(d)
            signals = {}
            for r in results:
                sig = r['signal']
                signals[sig] = signals.get(sig, 0) + 1
            print(f"  完成: {len(results)}个板块, {signals}")
    else:
        # 计算今天（或指定日期）
        if len(sys.argv) > 1 and sys.argv[1] != '--backfill':
            target_date = sys.argv[1]
        else:
            target_date = date.today().isoformat()
        
        print(f"计算 {target_date} 板块动量...")
        results = calculate_momentum(target_date)
        
        # 输出TOP5
        results.sort(key=lambda x: x['total_score'], reverse=True)
        print(f"\nTOP5 板块:")
        for i, r in enumerate(results[:5], 1):
            rank_str = f"{r['rank_change']:+d}" if r['rank_change'] is not None else "?"
            print(f"  #{i} {r['name']}: 得分{r['total_score']:.2f} | "
                  f"1日{r['flow_1d']:+.1f}亿 3日{r['flow_3d']:+.1f}亿 | "
                  f"方向{r['flow_direction']} | 连续{r['consecutive_days']}天 | "
                  f"排名#{r['rank_today']}(变化{rank_str}) | "
                  f"信号: {r['signal']}")
        
        # 统计
        signals = {}
        for r in results:
            sig = r['signal']
            signals[sig] = signals.get(sig, 0) + 1
        print(f"\n信号统计: {signals}")

if __name__ == "__main__":
    main()
