#!/usr/bin/env python3
"""
14:00报告数据填充 — 读取scan_summary.json，填充报告模板的数据部分
输出半成品报告到stdout（8/10章节已填好，催化剂分析+操作建议留空给LLM）

用法:
    python3 fund_report_data.py                    # 输出到stdout
    python3 fund_report_data.py > /tmp/report.md   # 输出到文件
"""
import json, sys, os
from datetime import datetime

SUMMARY_PATH = "/tmp/fund_data/scan_summary.json"

def load_summary():
    if not os.path.exists(SUMMARY_PATH):
        print("❌ scan_summary.json不存在，请先运行fund_scan_1400.py", file=sys.stderr)
        sys.exit(1)
    with open(SUMMARY_PATH) as f:
        return json.load(f)

def fmt_pct(v):
    """格式化百分比"""
    if v is None: return "—"
    return f"{v:+.2f}%"

def fmt_price(v):
    """格式化价格"""
    if v is None: return "—"
    return f"{v:.2f}"

def fmt_amount(v):
    """格式化金额（亿）"""
    if v is None: return "—"
    return f"{v:.2f}"

def build_section1_indices(data):
    """1. 大盘概况"""
    indices = data.get('indices_holdings', {}).get('data', {}).get('indices', [])
    lines = ["| 指数 | 点位 | 涨跌幅 |", "|:--|:--|:--|"]
    for idx in indices:
        lines.append(f"| {idx['name']} | {fmt_price(idx['price'])} | {fmt_pct(idx['pct'])} |")
    return "\n".join(lines)

def build_section2_holdings(data):
    """2. 持仓基金"""
    holdings = data.get('indices_holdings', {}).get('data', {}).get('holdings', [])
    if not holdings:
        return "当前空仓，无持仓基金。"
    lines = ["| 基金代码 | 基金名称 | 最新净值 | 今日涨跌 |", "|:--|:--|:--|:--|"]
    for h in holdings:
        lines.append(f"| {h.get('fund_code','')} | {h.get('fund_name','')} | {fmt_price(h.get('latest_nav'))} | {fmt_pct(h.get('today_pct'))} |")
    return "\n".join(lines)

def build_section3_stocks(data):
    """3. 重仓股实时"""
    stocks = data.get('indices_holdings', {}).get('data', {}).get('top_stocks', [])
    if not stocks:
        return "无重仓股数据。"
    lines = ["| 股票 | 现价 | 涨跌幅 |", "|:--|:--|:--|"]
    for s in stocks:
        lines.append(f"| {s['name']} | {fmt_price(s['price'])} | {fmt_pct(s['pct'])} |")
    return "\n".join(lines)

def build_section4_sectors(data):
    """4. 板块资金流向 TOP5"""
    top_inflow = data.get('sector_fund_flows', {}).get('data', {}).get('top_inflow', [])
    if not top_inflow:
        return "无板块数据。"
    lines = ["| 排名 | 板块 | 涨跌幅 | 成交额(亿) | 领涨股 |", "|:--|:--|:--|:--|:--|"]
    for i, s in enumerate(top_inflow[:5], 1):
        lines.append(f"| {i} | {s['name']} | {fmt_pct(s.get('pct_change'))} | {fmt_amount(s.get('amount_yi'))} | {s.get('leader','')} |")
    return "\n".join(lines)

def build_section5_global(data):
    """5. 外围环境"""
    gm = data.get('global_markets', {}).get('data', {})
    indices = gm.get('indices', [])
    futures = gm.get('futures', [])
    lines = ["### 美股", "| 指数 | 点位 | 涨跌幅 |", "|:--|:--|:--|"]
    for g in indices:
        lines.append(f"| {g['name']} | {fmt_price(g['price'])} | {fmt_pct(g['pct'])} |")
    if futures:
        lines.append("")
        lines.append("### 期货")
        lines.append("| 品种 | 最新 | 涨跌幅 |")
        lines.append("|:--|:--|:--|")
        for f in futures:
            lines.append(f"| {f['name']} | {fmt_price(f['price'])} | {fmt_pct(f['pct'])} |")
    return "\n".join(lines)

def build_section6_events(data):
    """6. 近期事件"""
    events = data.get('events', {}).get('data', {}).get('events', [])
    if not events:
        return "近期无重大事件。"
    lines = ["| 时间 | 事件 | 影响等级 |", "|:--|:--|:--|"]
    for e in events:
        intensity = "⭐" * min(e.get('intensity', 0), 5) if e.get('intensity') else "—"
        lines.append(f"| {e.get('time','')} | {e.get('title','')} | {intensity} |")
    return "\n".join(lines)

def build_section9_sector_scan(data):
    """9. 全市场板块扫描"""
    scan = data.get('sector_scan', {}).get('data', {})
    top5 = scan.get('top5', [])
    bottom5 = scan.get('bottom5', [])
    lines = ["### 🔴 涨幅 TOP5", "| 排名 | 板块 | 涨幅 | 领涨股 |", "|:--|:--|:--|:--|"]
    for i, s in enumerate(top5[:5], 1):
        lines.append(f"| {i} | {s['name']} | {fmt_pct(s.get('pct'))} | {s.get('leader','')} |")
    lines.append("")
    lines.append("### 🟢 跌幅 TOP5")
    lines.append("| 排名 | 板块 | 跌幅 | 领跌股 |")
    lines.append("|:--|:--|:--|:--|")
    for i, s in enumerate(bottom5[:5], 1):
        lines.append(f"| {i} | {s['name']} | {fmt_pct(s.get('pct'))} | {s.get('leader','')} |")
    return "\n".join(lines)

def build_section10_signals(data):
    """10. 信号评分"""
    signals = data.get('signals', [])
    raw = data.get('signal_raw', '')
    if not signals:
        return "今日无高质量信号（≥7分）。"
    lines = ["| 基金 | 信号 | 评分 |", "|:--|:--|:--|"]
    for s in signals:
        lines.append(f"| {s.get('name','')} | {s.get('signal','')} | {s.get('score','')} |")
    return "\n".join(lines)

def build_news_summary(data):
    """快讯摘要（供LLM分析用）"""
    items = data.get('news', {}).get('data', {}).get('items', [])
    if not items:
        return "无快讯。"
    lines = []
    for n in items[:10]:
        lines.append(f"- [{n.get('time','')[-5:]}] {n.get('title','')}")
    return "\n".join(lines)

def build_holdings_detail(data):
    """持仓详情（供LLM检查用）"""
    holdings = data.get('indices_holdings', {}).get('data', {}).get('holdings', [])
    if not holdings:
        return "空仓。"
    lines = []
    for h in holdings:
        lines.append(f"- {h.get('fund_name','')}({h.get('fund_code','')}): 净值{fmt_price(h.get('latest_nav'))} 今日{fmt_pct(h.get('today_pct'))}")
    return "\n".join(lines)

def main():
    summary = load_summary()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    stats = summary.get('stats', {})
    data = summary.get('sources', {})

    # 组装半成品报告
    report = f"""📊 14:00市场扫描｜{now}
⚠️ 数据说明：基金净值为上一交易日收盘值，重仓股/ETF为今日实时
数据状态：{stats.get('ok',0)}/{stats.get('total',0)}源成功

---

## 1. 大盘概况
{build_section1_indices(data)}

---

## 2. 持仓基金
{build_section2_holdings(data)}

---

## 3. 重仓股实时
{build_section3_stocks(data)}

---

## 4. 板块资金流向 TOP5
{build_section4_sectors(data)}

---

## 5. 外围环境
{build_section5_global(data)}

---

## 6. 近期事件
{build_section6_events(data)}

---

## 7. 催化剂分析
{LLM_ANALYSIS_PLACEHOLDER}

---

## 8. 操作建议
{LLM_ANALYSIS_PLACEHOLDER}

---

## 9. 全市场板块扫描
{build_section9_sector_scan(data)}

---

## 10. 信号评分
{build_section10_signals(data)}

---

*报告生成时间：{now} | 数据来源：脚本自动填充*
"""

    # 同时输出供LLM分析的辅助数据
    llm_context = f"""## 供LLM分析的辅助数据

### 快讯摘要（最近10条）
{build_news_summary(data)}

### 持仓详情
{build_holdings_detail(data)}

### 事件列表
{build_section6_events(data)}

### 需要LLM完成的分析：
1. **催化剂分析**（第7章）：基于快讯+事件，分析当前市场的核心催化剂
2. **操作建议**（第8章）：基于以上所有数据，给出买入/卖出/持有的建议和理由

请输出以下格式的分析结果（不要输出其他章节的内容）：

## 7. 催化剂分析
[你的分析]

## 8. 操作建议
[你的建议]
"""

    # 保存半成品报告到文件（供assemble脚本读取）
    report_path = "/tmp/fund_data/report_data.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    # 输出到stdout
    print(report)

    # 同时写LLM分析辅助数据到文件
    llm_path = "/tmp/fund_data/llm_analysis_input.md"
    with open(llm_path, 'w', encoding='utf-8') as f:
        f.write(llm_context)
    print(f"\n[LLM分析辅助数据已写入: {llm_path}]", file=sys.stderr)

LLM_ANALYSIS_PLACEHOLDER = "⚠️ 待LLM分析填充"

if __name__ == "__main__":
    main()
