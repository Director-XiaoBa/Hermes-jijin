#!/usr/bin/env python3
"""
基金每日涨跌归因分析
回答三个问题：大盘影响/板块影响/事件影响

用法：
    python3 fund_daily_attribution.py [日期]
    不传日期默认分析最近交易日
"""

import sys
import os
import json
import traceback
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pymysql
pymysql.install_as_MySQLdb()
from fund_common import get_connection


def get_latest_trade_date(conn, target_date=None):
    """获取最近的交易日"""
    cur = conn.cursor()
    if target_date:
        cur.execute("SELECT MAX(trade_date) FROM nav_daily WHERE trade_date <= %s", (target_date,))
    else:
        cur.execute("SELECT MAX(trade_date) FROM nav_daily")
    result = cur.fetchone()[0]
    cur.close()
    return result


def get_holdings_returns(conn, trade_date):
    """获取持仓基金当日涨跌"""
    cur = conn.cursor()
    # 聚合多条买入记录
    cur.execute("""
        SELECT n.fund_code, ANY_VALUE(t.fund_name) as fund_name, n.nav, n.daily_return,
               SUM(t.amount) as total_amount
        FROM nav_daily n
        JOIN trades t ON n.fund_code = t.fund_code
        WHERE n.trade_date = %s AND t.trade_status = '持有'
        GROUP BY n.fund_code, n.nav, n.daily_return
    """, (trade_date,))
    results = []
    for r in cur.fetchall():
        results.append({
            'fund_code': r[0],
            'fund_name': r[1][:12],
            'nav': float(r[2]) if r[2] else 0,
            'daily_return': float(r[3]) if r[3] else 0,
            'amount': float(r[4]) if r[4] else 0,
        })
    cur.close()
    return results


def get_index_returns(conn, trade_date):
    """获取指数当日涨跌"""
    cur = conn.cursor()
    cur.execute("""
        SELECT index_code, index_name, daily_return
        FROM market_daily
        WHERE trade_date = %s
    """, (trade_date,))
    results = {}
    for r in cur.fetchall():
        results[r[0]] = {'name': r[1], 'return': float(r[2]) if r[2] else 0}
    cur.close()
    return results


def get_sector_returns():
    """获取板块涨跌（从JSON缓存或实时拉取）"""
    try:
        with open('/tmp/fund_data/scan_summary.json') as f:
            data = json.load(f)
        sectors = data.get('sources', {}).get('sector_fund_flows', {}).get('data', {}).get('sectors', [])
        return {s['name']: s for s in sectors}
    except:
        return {}


def get_fund_sector_map(conn):
    """获取基金→板块映射"""
    cur = conn.cursor()
    cur.execute("SELECT fund_code, sector_name FROM fund_sector_map")
    result = {}
    for r in cur.fetchall():
        result[r[0]] = r[1] if r[1] else ''
    cur.close()
    return result


def match_sector(fund_code, sector_map, sector_returns):
    """匹配基金所属板块（模糊匹配）"""
    fund_sector = sector_map.get(fund_code, '')
    if not fund_sector:
        return None, 0

    # 精确匹配
    for sector_name, sector_data in sector_returns.items():
        if fund_sector == sector_name:
            return sector_name, sector_data.get('pct_change', 0)

    # 关键词映射（基金板块→新浪板块）
    keyword_map = {
        '芯片': ['电子器件', '电子信息'],
        '半导体': ['电子器件', '电子信息'],
        '电子': ['电子器件', '电子信息'],
        'AI': ['电子信息'],
        '算力': ['电子信息'],
        '机器人': ['机械行业'],
        '稀土': ['有色金属'],
        '消费': ['电子器件', '家电行业'],
        'CPO': ['电子信息'],
        '存储': ['电子器件'],
    }

    # 模糊匹配
    for kw, target_sectors in keyword_map.items():
        if kw in fund_sector:
            for target in target_sectors:
                if target in sector_returns:
                    return target, sector_returns[target].get('pct_change', 0)

    return None, 0


def get_related_events(conn, trade_date, fund_code):
    """获取与基金相关的当日事件"""
    cur = conn.cursor()
    cur.execute("""
        SELECT title, intensity, event_type
        FROM events
        WHERE DATE(event_time) = %s AND intensity >= 3
        ORDER BY intensity DESC
    """, (trade_date,))
    events = []
    for r in cur.fetchall():
        events.append({
            'title': r[0],
            'intensity': r[1],
            'type': r[2] if r[2] else '',
        })
    cur.close()
    return events


def match_event_relevance(fund_code, events, sector_keywords):
    """判断事件与基金的相关性"""
    relevant = []
    for ev in events:
        title = ev['title']
        is_relevant = False
        for kw in sector_keywords.split(','):
            kw = kw.strip()
            if kw and kw in title:
                is_relevant = True
                break
        # 通用关键词匹配
        generic_keywords = ['大盘', 'A股', '科技', '半导体', 'AI', '芯片', '存储']
        for kw in generic_keywords:
            if kw in title and not is_relevant:
                is_relevant = True
                break
        if is_relevant:
            relevant.append(ev)
    return relevant


def calculate_beta(fund_code, conn, days=20):
    """计算基金相对于大盘的β系数"""
    cur = conn.cursor()
    # 获取基金近N天涨跌
    cur.execute("""
        SELECT daily_return FROM nav_daily 
        WHERE fund_code = %s 
        ORDER BY trade_date DESC LIMIT %s
    """, (fund_code, days))
    fund_returns = [float(r[0]) for r in cur.fetchall() if r[0]]

    # 获取大盘近N天涨跌
    cur.execute("""
        SELECT daily_return FROM market_daily 
        WHERE index_code = 'sh000001'
        ORDER BY trade_date DESC LIMIT %s
    """, (days,))
    index_returns = [float(r[0]) for r in cur.fetchall() if r[0]]

    cur.close()

    if len(fund_returns) < 5 or len(index_returns) < 5:
        return 1.0  # 默认β=1

    # 对齐天数
    min_len = min(len(fund_returns), len(index_returns))
    fr = fund_returns[:min_len]
    ir = index_returns[:min_len]

    # 简单β计算：cov(fund, index) / var(index)
    avg_f = sum(fr) / len(fr)
    avg_i = sum(ir) / len(ir)
    cov = sum((f - avg_f) * (i - avg_i) for f, i in zip(fr, ir)) / len(fr)
    var_i = sum((i - avg_i) ** 2 for i in ir) / len(ir)

    if var_i == 0:
        return 1.0

    beta = cov / var_i
    return round(max(0.1, min(3.0, beta)), 2)  # 限制在0.1-3.0之间


def generate_attribution(fund, index_returns, sector_returns, sector_map, events, conn):
    """生成单只基金的归因分析"""
    fund_code = fund['fund_code']
    fund_return = fund['daily_return']

    # 1. 大盘影响
    sh_return = index_returns.get('sh000001', {}).get('return', 0)
    cyb_return = index_returns.get('sz399006', {}).get('return', 0)
    beta = calculate_beta(fund_code, conn)
    market_contribution = round(sh_return * beta, 2)
    excess = round(fund_return - market_contribution, 2)

    # 2. 板块影响
    sector_name, sector_return = match_sector(fund_code, sector_map, sector_returns)
    sector_contribution = round(sector_return * 0.7, 2) if sector_return else 0  # 假设70%来自板块

    # 3. 事件影响
    sector_keywords = sector_map.get(fund_code, '')
    related_events = match_event_relevance(fund_code, events, sector_keywords)

    # 4. 生成结论
    if abs(excess) < 0.5:
        conclusion = "跟大盘走势，无独立行情"
    elif excess > 1:
        conclusion = "逆市上涨，有独立利好"
    elif excess < -1:
        conclusion = "跑输大盘，有个股/板块利空"
    else:
        conclusion = "小幅偏离大盘"

    if related_events:
        event_str = '、'.join([e['title'][:20] for e in related_events[:2]])
        conclusion += f"（关联事件：{event_str}）"

    return {
        'fund_code': fund_code,
        'fund_name': fund['fund_name'],
        'daily_return': fund_return,
        'amount': fund['amount'],
        'beta': beta,
        'market_contribution': market_contribution,
        'excess_return': excess,
        'sector_name': sector_name or '未匹配',
        'sector_return': sector_return,
        'sector_contribution': sector_contribution,
        'related_events': related_events,
        'conclusion': conclusion,
    }


def save_attribution(conn, trade_date, attributions):
    """保存归因结果到MySQL"""
    cur = conn.cursor()

    # 创建表（如果不存在）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_attribution (
            id INT AUTO_INCREMENT PRIMARY KEY,
            trade_date DATE NOT NULL,
            fund_code VARCHAR(10) NOT NULL,
            fund_name VARCHAR(50),
            daily_return DECIMAL(8,4),
            amount DECIMAL(10,2),
            beta DECIMAL(4,2),
            market_contribution DECIMAL(8,4),
            excess_return DECIMAL(8,4),
            sector_name VARCHAR(50),
            sector_return DECIMAL(8,4),
            sector_contribution DECIMAL(8,4),
            related_events TEXT,
            conclusion TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_date_fund (trade_date, fund_code)
        )
    """)
    conn.commit()

    for attr in attributions:
        events_json = json.dumps([e['title'][:50] for e in attr['related_events']], ensure_ascii=False)
        cur.execute("""
            INSERT INTO daily_attribution 
            (trade_date, fund_code, fund_name, daily_return, amount, beta,
             market_contribution, excess_return, sector_name, sector_return,
             sector_contribution, related_events, conclusion)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                daily_return=VALUES(daily_return),
                market_contribution=VALUES(market_contribution),
                excess_return=VALUES(excess_return),
                sector_name=VALUES(sector_name),
                conclusion=VALUES(conclusion)
        """, (
            trade_date, attr['fund_code'], attr['fund_name'],
            attr['daily_return'], attr['amount'], attr['beta'],
            attr['market_contribution'], attr['excess_return'],
            attr['sector_name'], attr['sector_return'],
            attr['sector_contribution'], events_json, attr['conclusion']
        ))

    conn.commit()
    cur.close()


def format_report(trade_date, attributions):
    """生成Markdown格式的归因报告"""
    lines = [f"📊 {trade_date} 涨跌归因报告\n"]

    for attr in attributions:
        emoji = "🔴" if attr['daily_return'] < -1 else "🟢" if attr['daily_return'] > 1 else "⚪"
        lines.append(f"{emoji} {attr['fund_code']} {attr['fund_name']} | 今日{attr['daily_return']:+.2f}% | 持仓¥{attr['amount']:.0f}")
        lines.append(f"  ├─ 大盘影响：{attr['market_contribution']:+.2f}%（β={attr['beta']}）")
        lines.append(f"  ├─ 板块影响：{attr['sector_name']} {attr['sector_return']:+.2f}% → 贡献{attr['sector_contribution']:+.2f}%")
        lines.append(f"  ├─ 超额收益：{attr['excess_return']:+.2f}%")
        lines.append(f"  └─ 结论：{attr['conclusion']}")
        lines.append("")

    # 汇总
    total_pnl = sum(a['daily_return'] * a['amount'] / 100 for a in attributions)
    total_amount = sum(a['amount'] for a in attributions)
    lines.append(f"💰 今日总盈亏：¥{total_pnl:+.2f}（总仓位¥{total_amount:.0f}）")

    return '\n'.join(lines)


def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description='基金每日涨跌归因分析')
    parser.add_argument('date', nargs='?', help='分析日期（YYYY-MM-DD），默认最近交易日')
    parser.add_argument('--report', action='store_true', help='输出Markdown报告')
    args = parser.parse_args()

    conn = get_connection()

    # 获取交易日
    trade_date = get_latest_trade_date(conn, args.date)
    if not trade_date:
        print("❌ 无交易日数据")
        return
    print(f"分析日期: {trade_date}")

    # 获取数据
    holdings = get_holdings_returns(conn, trade_date)
    index_returns = get_index_returns(conn, trade_date)
    sector_returns = get_sector_returns()
    sector_map = get_fund_sector_map(conn)
    events = get_related_events(conn, trade_date, None)

    print(f"持仓基金: {len(holdings)}只")
    print(f"指数数据: {len(index_returns)}个")
    print(f"板块数据: {len(sector_returns)}个")
    print(f"当日事件: {len(events)}条（强度≥3）")

    # 生成归因
    attributions = []
    for fund in holdings:
        attr = generate_attribution(fund, index_returns, sector_returns, sector_map, events, conn)
        attributions.append(attr)

    # 保存到MySQL
    save_attribution(conn, trade_date, attributions)
    print(f"\n✅ 归因结果已保存到daily_attribution表")

    # 输出报告
    if args.report:
        report = format_report(trade_date, attributions)
        print(f"\n{report}")

        # 保存到文件
        report_path = os.path.expanduser(f'~/user_files/documents/attribution_{trade_date}.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\n📄 报告已保存: {report_path}")

    conn.close()


if __name__ == '__main__':
    main()
