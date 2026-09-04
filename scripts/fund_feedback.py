#!/home/ubuntu/.hermes/venv-fund/bin/python3
"""Phase 4: 闭环反哺 — 月度统计+信号源评估+个人复盘。
用法：python3 fund_feedback.py [月份YYYY-MM]
  不传参数：统计当前月
  传月份：统计指定月

输出：
  1. 信号源胜率（老道/Hermes/新闻/技术 各自的T+3/T+5准确率）
  2. 个人交易复盘（胜率/盈亏比/最大回撤/板块偏好）
  3. 策略建议（哪些信号源值得加权、哪些板块擅长）
"""
import pymysql, datetime, sys, json
from collections import defaultdict

# 导入共享模块
import os
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_connection

def get_month_range(year, month):
    """获取月份的起止日期"""
    start = datetime.date(year, month, 1)
    if month == 12:
        end = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return start, end

def signal_source_analysis(conn, start, end):
    """信号源胜率分析"""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    cursor.execute("""
        SELECT source, COUNT(*) as total,
               SUM(CASE WHEN t3_return > 0 THEN 1 ELSE 0 END) as t3_up,
               SUM(CASE WHEN t5_return > 0 THEN 1 ELSE 0 END) as t5_up,
               AVG(t3_return) as avg_t3,
               AVG(t5_return) as avg_t5,
               AVG(t10_return) as avg_t10
        FROM signals
        WHERE signal_date BETWEEN %s AND %s
          AND t3_return IS NOT NULL
        GROUP BY source
        HAVING total >= 3
    """, (start, end))
    
    results = cursor.fetchall()
    cursor.close()
    return results

def signal_fund_detail(conn, start, end):
    """按基金×信号源的交叉统计"""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    cursor.execute("""
        SELECT s.source, s.fund_code, f.name as fund_name,
               COUNT(*) as total,
               AVG(s.t3_return) as avg_t3,
               AVG(s.t5_return) as avg_t5,
               SUM(CASE WHEN s.t3_return > 0 THEN 1 ELSE 0 END) as t3_up
        FROM signals s
        LEFT JOIN funds f ON s.fund_code = f.code
        WHERE s.signal_date BETWEEN %s AND %s
          AND s.t3_return IS NOT NULL
        GROUP BY s.source, s.fund_code
        HAVING total >= 2
        ORDER BY avg_t3 DESC
    """, (start, end))
    
    results = cursor.fetchall()
    cursor.close()
    return results

def trade_analysis(conn, start, end):
    """个人交易复盘"""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    # 基本统计
    cursor.execute("""
        SELECT COUNT(*) as total_trades,
               SUM(CASE WHEN actual_return > 0 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN actual_return < 0 THEN 1 ELSE 0 END) as losses,
               AVG(actual_return) as avg_return,
               AVG(net_return) as avg_net_return,
               MAX(actual_return) as max_win,
               MIN(actual_return) as max_loss,
               AVG(hold_days) as avg_hold_days
        FROM trades
        WHERE trade_date BETWEEN %s AND %s
          AND trade_status = 'closed'
          AND actual_return IS NOT NULL
    """, (start, end))
    
    basic = cursor.fetchone()
    
    # 按板块统计
    cursor.execute("""
        SELECT f.sector_exposure as sector,
               COUNT(*) as trades,
               AVG(t.actual_return) as avg_return,
               SUM(CASE WHEN t.actual_return > 0 THEN 1 ELSE 0 END) as wins
        FROM trades t
        LEFT JOIN funds f ON t.fund_code = f.code
        WHERE t.trade_date BETWEEN %s AND %s
          AND t.trade_status = 'closed'
          AND t.actual_return IS NOT NULL
        GROUP BY f.sector_exposure
        HAVING trades >= 2
        ORDER BY avg_return DESC
    """, (start, end))
    
    by_sector = cursor.fetchall()
    
    # 按信号来源统计
    cursor.execute("""
        SELECT t.signal_source,
               COUNT(*) as trades,
               AVG(t.actual_return) as avg_return,
               SUM(CASE WHEN t.actual_return > 0 THEN 1 ELSE 0 END) as wins
        FROM trades t
        WHERE t.trade_date BETWEEN %s AND %s
          AND t.trade_status = 'closed'
          AND t.actual_return IS NOT NULL
          AND t.signal_source IS NOT NULL
        GROUP BY t.signal_source
        ORDER BY avg_return DESC
    """, (start, end))
    
    by_signal = cursor.fetchall()
    
    # 持仓中的交易
    cursor.execute("""
        SELECT t.id, t.fund_code, t.fund_name, t.direction, t.amount, 
               t.nav_price, t.trade_date, f.sector_exposure
        FROM trades t
        LEFT JOIN funds f ON t.fund_code = f.code
        WHERE t.trade_status = 'open'
    """)
    
    open_trades = cursor.fetchall()
    
    cursor.close()
    return basic, by_sector, by_signal, open_trades

def weight_suggestion(signal_results, trade_results):
    """根据历史表现给出信号权重建议"""
    suggestions = []
    
    if signal_results:
        for r in signal_results:
            source = r['source']
            t3_up_pct = (r['t3_up'] / r['total'] * 100) if r['total'] > 0 else 0
            avg_t3 = float(r['avg_t3'] or 0)
            
            if t3_up_pct >= 60 and avg_t3 > 0.5:
                suggestions.append(f"  ✅ {source}: T+3上涨{t3_up_pct:.0f}%，平均+{avg_t3:.2f}% → 建议权重15-20%")
            elif t3_up_pct >= 50:
                suggestions.append(f"  🟡 {source}: T+3上涨{t3_up_pct:.0f}%，平均{avg_t3:+.2f}% → 建议权重5-10%")
            else:
                suggestions.append(f"  ❌ {source}: T+3上涨{t3_up_pct:.0f}%，平均{avg_t3:+.2f}% → 建议权重0-5%")
    
    return suggestions

def format_monthly_report(year, month, signal_results, signal_detail, trade_basic, 
                          trade_by_sector, trade_by_signal, open_trades, suggestions):
    """格式化月度报告"""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"📊 基金研究系统月度复盘: {year}-{month:02d}")
    lines.append(f"{'='*60}")
    
    # 信号源分析
    lines.append(f"\n## 一、信号源胜率")
    if signal_results:
        lines.append(f"\n{'来源':>8} | {'样本':>4} | {'T+3涨':>8} | {'T+5涨':>8} | {'T+3均':>8} | {'T+5均':>8} | {'T+10均':>8}")
        lines.append(f"{'-'*8}-+-{'-'*4}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")
        for r in signal_results:
            t3_pct = r['t3_up'] / r['total'] * 100 if r['total'] else 0
            t5_pct = r['t5_up'] / r['total'] * 100 if r['total'] else 0
            lines.append(f"{r['source']:>8} | {r['total']:>4} | {t3_pct:>7.1f}% | {t5_pct:>7.1f}% "
                        f"| {float(r['avg_t3'] or 0):>+7.2f}% | {float(r['avg_t5'] or 0):>+7.2f}% "
                        f"| {float(r['avg_t10'] or 0):>+7.2f}%")
    else:
        lines.append("  本月无足够信号数据（需≥3条同源信号）")
    
    # 信号×基金交叉
    if signal_detail:
        lines.append(f"\n### 信号×基金交叉（按T+3收益排序）")
        lines.append(f"{'来源':>6} | {'基金':>8} | {'名称':>10} | {'次数':>4} | {'T+3均':>8} | {'T+3涨%':>8}")
        lines.append(f"{'-'*6}-+-{'-'*8}-+-{'-'*10}-+-{'-'*4}-+-{'-'*8}-+-{'-'*8}")
        for r in signal_detail[:10]:
            t3_pct = r['t3_up'] / r['total'] * 100 if r['total'] else 0
            lines.append(f"{r['source']:>6} | {r['fund_code']:>8} | {(r['fund_name'] or '')[:10]:>10} "
                        f"| {r['total']:>4} | {float(r['avg_t3'] or 0):>+7.2f}% | {t3_pct:>7.1f}%")
    
    # 交易复盘
    lines.append(f"\n## 二、个人交易复盘")
    if trade_basic and trade_basic['total_trades']:
        b = trade_basic
        total = b['total_trades']
        wins = b['wins'] or 0
        losses = b['losses'] or 0
        win_rate = wins / total * 100 if total else 0
        
        lines.append(f"\n  总交易: {total}笔 | 盈: {wins} | 亏: {losses} | 胜率: {win_rate:.1f}%")
        lines.append(f"  平均收益: {float(b['avg_return'] or 0):+.2f}% | 扣费后: {float(b['avg_net_return'] or 0):+.2f}%")
        lines.append(f"  最大盈利: {float(b['max_win'] or 0):+.2f}% | 最大亏损: {float(b['max_loss'] or 0):+.2f}%")
        lines.append(f"  平均持有: {float(b['avg_hold_days'] or 0):.1f}天")
        
        # 盈亏比
        avg_win = float(b['avg_return'] or 0) if wins > 0 else 0
        avg_loss = abs(float(b['avg_return'] or 0)) if losses > 0 else 1
        if avg_loss > 0:
            ratio = avg_win / avg_loss
            lines.append(f"  盈亏比: {ratio:.2f}:1")
    
    # 按板块
    if trade_by_sector:
        lines.append(f"\n### 按板块")
        lines.append(f"{'板块':>10} | {'笔数':>4} | {'胜率':>6} | {'平均收益':>8}")
        lines.append(f"{'-'*10}-+-{'-'*4}-+-{'-'*6}-+-{'-'*8}")
        for r in trade_by_sector:
            wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
            lines.append(f"{(r['sector'] or '未知'):>10} | {r['trades']:>4} | {wr:>5.1f}% | {float(r['avg_return'] or 0):>+7.2f}%")
    
    # 按信号来源
    if trade_by_signal:
        lines.append(f"\n### 按信号来源")
        lines.append(f"{'来源':>8} | {'笔数':>4} | {'胜率':>6} | {'平均收益':>8}")
        lines.append(f"{'-'*8}-+-{'-'*4}-+-{'-'*6}-+-{'-'*8}")
        for r in trade_by_signal:
            wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
            lines.append(f"{(r['signal_source'] or '未知'):>8} | {r['trades']:>4} | {wr:>5.1f}% | {float(r['avg_return'] or 0):>+7.2f}%")
    
    # 持仓
    if open_trades:
        lines.append(f"\n### 当前持仓")
        lines.append(f"{'基金':>8} | {'名称':>10} | {'金额':>6} | {'买入净值':>8} | {'板块':>8}")
        lines.append(f"{'-'*8}-+-{'-'*10}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}")
        for t in open_trades:
            lines.append(f"{t['fund_code']:>8} | {(t['fund_name'] or '')[:10]:>10} "
                        f"| ¥{float(t['amount'] or 0):>5.0f} | {float(t['nav_price'] or 0):>8.4f} "
                        f"| {(t['sector_exposure'] or '未知'):>8}")
    
    # 权重建议
    if suggestions:
        lines.append(f"\n## 三、信号权重建议")
        lines.append(f"  基于本月{year}-{month:02d}数据，建议下月信号权重:")
        for s in suggestions:
            lines.append(s)
    else:
        lines.append(f"\n## 三、信号权重建议")
        lines.append(f"  数据不足，暂不调整权重。继续积累。")
    
    # 总结
    lines.append(f"\n## 四、本月总结")
    if trade_basic and trade_basic['total_trades']:
        win_rate = (trade_basic['wins'] or 0) / trade_basic['total_trades'] * 100
        if win_rate >= 60:
            lines.append(f"  ✅ 本月胜率{win_rate:.0f}%，表现良好。继续保持纪律。")
        elif win_rate >= 45:
            lines.append(f"  🟡 本月胜率{win_rate:.0f}%，中等水平。检查是否有凭感觉操作的案例。")
        else:
            lines.append(f"  ❌ 本月胜率{win_rate:.0f}%，需要复盘。重点关注：止损是否执行？是否追高了？")
    else:
        lines.append(f"  本月交易数据不足，继续积累。")
    
    lines.append(f"\n{'='*60}")
    return '\n'.join(lines)

def main():
    # 确定统计月份
    if len(sys.argv) > 1:
        parts = sys.argv[1].split('-')
        year, month = int(parts[0]), int(parts[1])
    else:
        today = datetime.date.today()
        year, month = today.year, today.month
    
    start, end = get_month_range(year, month)
    
    conn = get_connection()
    
    # 信号源分析
    signal_results = signal_source_analysis(conn, start, end)
    signal_detail = signal_fund_detail(conn, start, end)
    
    # 交易分析
    trade_basic, trade_by_sector, trade_by_signal, open_trades = trade_analysis(conn, start, end)
    
    # 权重建议
    suggestions = weight_suggestion(signal_results, trade_basic)
    
    # 输出报告
    report = format_monthly_report(year, month, signal_results, signal_detail,
                                   trade_basic, trade_by_sector, trade_by_signal, 
                                   open_trades, suggestions)
    print(report)
    
    # 保存到文件
    report_path = f"/home/ubuntu/user_files/documents/fund_monthly_{year}{month:02d}.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n报告已保存: {report_path}")
    
    conn.close()

if __name__ == '__main__':
    main()
