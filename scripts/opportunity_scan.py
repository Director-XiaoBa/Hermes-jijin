#!/usr/bin/env python3
"""
机会发现扫描 — 基于板块动量筛选TOP机会
读取sector_momentum_daily，筛选买入信号板块，匹配基金，生成报告。

用法:
    python3 opportunity_scan.py              # 扫描今天的机会
    python3 opportunity_scan.py 2026-09-04   # 指定日期
    python3 opportunity_scan.py --confirm    # 收盘确认模式（用收盘数据重算）
"""
import sys, os, json
from datetime import datetime, date

import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(os.path.expanduser("~"), ".hermes", "venv-fund", "bin", "python3")
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable

DB_CONFIG = {
    'host': '127.0.0.1', 'port': 3306,
    'user': 'fund_admin', 'password': 'FundR2026!db',
    'database': 'fund_research', 'charset': 'utf8mb4'
}

# 板块→基金映射（从fund_common.py复用）
SECTOR_FUND_MAP = {
    '互联网': ['017811', '025422'],
    '计算机': ['017811', '018123', '025422'],
    '软件': ['017811', '018123'],
    '信息技术': ['017811', '018123', '025422'],
    '电子': ['017470', '025209'],
    '半导体': ['017470', '025209'],
    '芯片': ['017470', '025209'],
    '通信': ['025422'],
    '机械': ['018345'],
    '设备': ['018345'],
    '机器人': ['018345'],
    '有色金属': ['011036'],
    '稀土': ['011036'],
}

FUND_NAMES = {
    '017811': '东方人工智能主题混合C',
    '017470': '嘉实上证科创板芯片ETF',
    '018345': '国泰中证机器人ETF联接C',
    '011036': '嘉实中证稀土产业ETF联接C',
    '025422': '天弘中证云计算与大数据ETF联接C',
    '025209': '永赢先锋半导体智选混合C',
    '018123': '华夏中证软件服务ETF联接C',
}

def get_connection():
    return pymysql.connect(**DB_CONFIG)

def match_funds(sector_name):
    """匹配板块→基金"""
    matched = []
    for keyword, fund_codes in SECTOR_FUND_MAP.items():
        if keyword in sector_name:
            for code in fund_codes:
                if code not in [m['code'] for m in matched]:
                    matched.append({
                        'code': code,
                        'name': FUND_NAMES.get(code, code),
                        'match_reason': f'匹配关键词: {keyword}'
                    })
    return matched

def get_fund_technicals(conn, fund_code):
    """获取基金技术指标"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nav, daily_return, rsi_12, macd_line, signal_line, 
               ma5, ma10, ma20, ma60
        FROM nav_daily 
        WHERE fund_code = %s 
        ORDER BY trade_date DESC LIMIT 1
    """, (fund_code,))
    row = cursor.fetchone()
    if row:
        return {
            'nav': float(row[0]),
            'daily_return': float(row[1]) if row[1] else 0,
            'rsi_12': float(row[2]) if row[2] else 50,
            'macd': float(row[3]) if row[3] else 0,
            'signal_line': float(row[4]) if row[4] else 0,
            'ma5': float(row[5]) if row[5] else 0,
            'ma10': float(row[6]) if row[6] else 0,
            'ma20': float(row[7]) if row[7] else 0,
            'ma60': float(row[8]) if row[8] else 0,
        }
    return None

def get_market_environment(conn, target_date):
    """获取大盘环境"""
    cursor = conn.cursor()
    
    # 上证指数
    cursor.execute("""
        SELECT daily_return FROM market_daily 
        WHERE trade_date = %s AND index_name = '上证指数'
    """, (target_date,))
    row = cursor.fetchone()
    sh_return = float(row[0]) if row else 0
    
    # 北向资金
    cursor.execute("""
        SELECT total_netflow FROM north_flow_daily 
        WHERE trade_date = %s
    """, (target_date,))
    row = cursor.fetchone()
    north_flow = float(row[0]) if row else 0
    
    # 判断环境
    if sh_return > 0.3 and north_flow > 0:
        env = '良好'
        env_score = 2
    elif sh_return > 0:
        env = '一般'
        env_score = 1
    elif sh_return > -0.3:
        env = '偏弱'
        env_score = 0
    else:
        env = '较差'
        env_score = -1
    
    return {
        'sh_return': sh_return,
        'north_flow': north_flow,
        'environment': env,
        'score': env_score
    }

def generate_report(target_date, confirm_mode=False):
    """生成机会发现报告"""
    conn = get_connection()
    
    # 获取大盘环境
    market = get_market_environment(conn, target_date)
    
    # 获取动量数据
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sector_name, flow_1d, flow_3d, flow_5d, 
               flow_direction, consecutive_inflow_days,
               rank_today, rank_change, volume_ratio,
               fund_score, momentum_score, volume_score,
               total_score, signal_type, suggested_position
        FROM sector_momentum_daily 
        WHERE trade_date = %s 
        ORDER BY total_score DESC
    """, (target_date,))
    sectors = cursor.fetchall()
    
    # 筛选买入信号
    buy_sectors = []
    for s in sectors:
        (name, flow_1d, flow_3d, flow_5d, direction, consec_days,
         rank_today, rank_change, volume_ratio,
         fund_score, momentum_score, volume_score,
         total_score, signal_type, suggested_position) = s
        
        if signal_type in ('buy', 'strong_buy'):
            # 匹配基金
            funds = match_funds(name)
            
            # 获取基金技术指标
            for fund in funds:
                tech = get_fund_technicals(conn, fund['code'])
                fund['technicals'] = tech
            
            buy_sectors.append({
                'name': name,
                'flow_1d': float(flow_1d) if flow_1d else 0,
                'flow_3d': float(flow_3d) if flow_3d else 0,
                'flow_5d': float(flow_5d) if flow_5d else 0,
                'direction': direction,
                'consec_days': consec_days,
                'rank': rank_today,
                'rank_change': rank_change,
                'volume_ratio': float(volume_ratio) if volume_ratio else None,
                'scores': {
                    'fund': float(fund_score) if fund_score else 0,
                    'momentum': float(momentum_score) if momentum_score else 0,
                    'volume': float(volume_score) if volume_score else 0,
                },
                'total_score': float(total_score) if total_score else 0,
                'signal': signal_type,
                'position': suggested_position,
                'funds': funds
            })
    
    conn.close()
    
    # 生成报告
    mode_label = "收盘确认" if confirm_mode else "盘中扫描"
    report = f"📊 机会发现报告 {target_date}（{mode_label}）\n\n"
    
    # 大盘环境
    report += f"## 一、大盘环境：{market['environment']}\n"
    report += f"- 上证涨跌: {market['sh_return']:+.2f}%\n"
    report += f"- 北向资金: {market['north_flow']:+.2f}亿\n"
    if market['score'] <= -1:
        report += "⚠️ 大盘环境较差，建议观望\n"
    report += "\n"
    
    # TOP机会
    if buy_sectors:
        report += f"## 二、TOP机会板块（共{len(buy_sectors)}个）\n\n"
        for i, s in enumerate(buy_sectors[:5], 1):
            signal_icon = "🟢 强买入" if s['signal'] == 'strong_buy' else "🟡 买入"
            report += f"### {i}. {s['name']} — {signal_icon}\n"
            report += f"- 资金: 1日{s['flow_1d']:+.1f}亿, 3日{s['flow_3d']:+.1f}亿\n"
            report += f"- 方向: {s['direction']}, 连续流入{s['consec_days']}天\n"
            report += f"- 排名: #{s['rank']}"
            if s['rank_change'] is not None:
                report += f" (变化{s['rank_change']:+d})"
            report += "\n"
            report += f"- 得分: {s['total_score']:.2f} (资金{s['scores']['fund']:+.1f} 动量{s['scores']['momentum']:+.1f} 量{s['scores']['volume']:+.1f})\n"
            report += f"- 建议仓位: {s['position']}%\n"
            
            if s['funds']:
                report += "- 匹配基金:\n"
                for f in s['funds']:
                    tech = f.get('technicals')
                    if tech:
                        report += f"  - {f['code']} {f['name']}: 净值{tech['nav']:.4f}, RSI{tech['rsi_12']:.1f}, MACD{'↑' if tech['macd'] > tech['signal_line'] else '↓'}\n"
                    else:
                        report += f"  - {f['code']} {f['name']}\n"
            else:
                report += "- ⚠️ 暂无匹配基金\n"
            report += "\n"
    else:
        report += "## 二、今日无买入信号板块\n\n"
        # 显示TOP5观望板块
        watch_sectors = [s for s in sectors if s[13] == 'watch'][:5]
        if watch_sectors:
            report += "以下板块值得关注（待确认）：\n"
            for s in watch_sectors:
                report += f"- {s[0]}: 得分{s[12]:.2f}, 1日{s[1]:+.1f}亿, 方向{s[4]}\n"
    
    # 持仓检查
    report += "\n## 三、持仓止盈止损\n"
    report += "- 当前空仓，无需检查\n"
    
    return report

def main():
    confirm_mode = '--confirm' in sys.argv
    
    if len(sys.argv) > 1 and sys.argv[1] not in ('--confirm',):
        target_date = sys.argv[1]
    else:
        target_date = date.today().isoformat()
    
    report = generate_report(target_date, confirm_mode)
    print(report)

if __name__ == "__main__":
    main()
