#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fund daily report for user's Alipay fund holdings.

动态从 trades 表读取持仓，自动计算总投入和收益。
T+1 逻辑：今天买入的基金不计算今日收益。
"""
from __future__ import annotations

import json
import math
import re
import sys
import urllib.request
import pymysql
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

# 导入共享模块
import os
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_connection, get_holdings as _common_get_holdings

# 数据库配置
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': '<REDACTED>',
    'database': 'fund_research',
    'charset': 'utf8mb4'
}

LEDGER = Path("/home/ubuntu/user_files/documents/投资持仓台账.md")
TZ = ZoneInfo("Asia/Shanghai")


def get_holdings() -> list[dict]:
    """从 fund_common 获取持仓，适配本脚本的key命名"""
    raw = _common_get_holdings()
    return [{
        'code': h['fund_code'],
        'name': h['fund_name'],
        'total_amount': h['total_amount'],
        'buy_date': h['buy_date'],
        'buy_nav': h.get('nav_price'),
        'stop_loss': h.get('stop_loss'),
        'take_profit': h.get('take_profit'),
        'notes': h.get('notes', []),
    } for h in raw]


def http(url, timeout=12):
    """发送HTTP请求"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://fund.eastmoney.com/"
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_fund_data(code: str) -> dict:
    """从东方财富获取基金数据（使用pingzhongdata接口）"""
    url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
    raw = http(url).decode("utf-8", "ignore")
    
    # 提取最新净值
    nav_match = re.search(r'Data_netWorthTrend\s*=\s*(\[.*?\]);', raw, re.DOTALL)
    if nav_match:
        nav_data = json.loads(nav_match.group(1))
        if nav_data:
            latest = nav_data[-1]
            nav_date = datetime.fromtimestamp(latest['x'] / 1000).strftime('%Y-%m-%d')
            nav_value = latest['y']
            nav_return = latest.get('equityReturn', 0)
        else:
            nav_date = "--"
            nav_value = None
            nav_return = None
    else:
        nav_date = "--"
        nav_value = None
        nav_return = None
    
    # 提取基金名称
    name_match = re.search(r'var fS_name\s*=\s*"([^"]+)"', raw)
    fund_name = name_match.group(1) if name_match else ""
    
    return {
        "code": code,
        "name": fund_name,
        "nav_date": nav_date,
        "nav_value": nav_value,
        "nav_return": nav_return,
    }


def fnum(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def signed(value: float, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "--"
    return f"{value:+.{digits}f}"


def build_report(mode: str) -> str:
    now = datetime.now(TZ)
    weekday = now.weekday()
    if weekday >= 5:
        return ""  # 周末不推

    today_str = now.strftime("%Y-%m-%d")
    
    # 从数据库动态读取持仓
    holdings = get_holdings()
    
    # 也读取今日卖出的基金（今天NAV still applies，需要显示）
    conn_sold = get_connection()
    try:
        with conn_sold.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT fund_code, fund_name, amount as total_amount, nav_price as buy_nav, 
                       trade_date, actual_sell_nav, actual_return, hold_days, fee, net_return
                FROM trades 
                WHERE trade_status = '已卖出' AND DATE(updated_at) = %s
            """, (today_str,))
            sold_today = cur.fetchall()
    finally:
        conn_sold.close()
    
    # 合并：持仓 + 今日卖出（统一显示）
    all_funds = list(holdings)
    for s in sold_today:
        # 转换为与holdings相同的格式
        all_funds.append({
            'code': s['fund_code'],
            'name': s['fund_name'][:8],
            'total_amount': float(s['total_amount']),
            'buy_nav': float(s['buy_nav']) if s.get('buy_nav') else None,
            'buy_date': str(s['trade_date']),
            'stop_loss': None,
            'take_profit': None,
            'is_sold_today': True,
            'sell_nav': float(s['actual_sell_nav']) if s.get('actual_sell_nav') else None,
            'sell_return': float(s['actual_return']) if s.get('actual_return') else None,
            'sell_fee': float(s['fee']) if s.get('fee') else 0,
            'sell_net_return': float(s['net_return']) if s.get('net_return') else None,
        })
    
    if not all_funds:
        return "📊 无持仓数据"
    
    # 获取每只基金的今日NAV（从nav_daily表，不用天天基金API）
    conn_nav = get_connection()
    try:
        with conn_nav.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT fund_code, nav FROM nav_daily WHERE trade_date = %s", (today_str,))
            today_navs = {row['fund_code']: float(row['nav']) for row in cur.fetchall()}
    finally:
        conn_nav.close()

    # 获取每只基金的实时数据
    rows = []
    for h in all_funds:
        try:
            code = h["code"]
            nav_val = today_navs.get(code)
            is_sold = h.get("is_sold_today", False)
            rows.append({
                **h,
                "ok": True,
                "nav_date": today_str if nav_val else None,
                "nav_value": nav_val,
                "nav_return": None,
                "buy_date": h.get("buy_date", ""),
                "is_sold_today": is_sold,
            })
        except Exception as e:
            rows.append({**h, "ok": False, "error": str(e)})
    
    # 计算总投入（持仓+今日卖出）
    total_principal = sum(h["total_amount"] for h in all_funds)
    held_names = " + ".join(f"{h['name'][:6]}{int(h['total_amount'])}元" for h in holdings)
    sold_names = " + ".join(f"{h['fund_name'][:6]}{int(h['total_amount'])}元" for h in sold_today) if sold_today else ""
    
    if mode == "intraday":
        title = f"📈 基金盘中估值｜{now.strftime('%m-%d %H:%M')}"
    else:
        title = f"📊 基金晚间日报｜{now.strftime('%m-%d %H:%M')}"
    
    desc_parts = [f"总本金{int(total_principal)}元"]
    if held_names:
        desc_parts.append(f"持仓: {held_names}")
    if sold_names:
        desc_parts.append(f"今日卖出: {sold_names}")
    desc = "｜".join(desc_parts)
    
    lines = [title, ""]
    lines.append(desc)
    lines.append("")
    
    ok_rows = [r for r in rows if r.get("ok")]
    
    # ── 持仓总览 ──
    if mode == "intraday":
        lines.append("**📋 实时估值（天天基金）**")
        lines.append("> ⚠️ 不同平台（天天基金/支付宝/养基宝）估值算法不同，结果可能有差异，以基金公司公布的官方净值为准")
    else:
        lines.append("**📋 确认净值**")
    lines.append("| 基金 | 本金 | 昨日市值 | 今日市值 | 今日收益 | 状态 |")
    lines.append("|---:|---:|---:|---:|---:|:---|")
    
    total_today = 0.0
    total_market_value = 0.0  # 总市值
    total_yesterday_value = 0.0  # 昨日总市值
    
    # 获取昨日日期
    from datetime import timedelta
    yesterday = now.date() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    for r in rows:
        if not r.get("ok"):
            lines.append(f"| ❌ {r['name'][:8]} | -- | -- | -- | 数据获取失败 | -- |")
            continue
        
        principal = r["total_amount"]
        buy_date = r["buy_date"]
        nav_value = r.get("nav_value")
        is_sold = r.get("is_sold_today", False)
        
        # T+1 逻辑：今天买入的不计算今日收益，市值=投入金额
        is_today_buy = (buy_date == today_str)
        
        if is_today_buy and not is_sold:
            # 今日买入，明天才出净值，市值=投入金额
            total_market_value += principal
            total_yesterday_value += principal
            lines.append(f"| {r['name'][:8]} | {int(principal)}元 | -- | -- | 明日出净值 | 🆕 新买入 |")
        else:
            # 非今日买入，计算今日收益 = 今日市值 - 昨日市值
            buy_nav = r.get("buy_nav", 0)
            if buy_nav and buy_nav > 0 and nav_value:
                buy_nav = float(buy_nav)  # 转换为float
                shares = principal / buy_nav
                
                # 今日市值
                market_value_today = nav_value * shares
                total_market_value += market_value_today
                
                # 获取昨日净值计算昨日市值
                # 从数据库获取昨日净值
                conn = pymysql.connect(**DB_CONFIG)
                try:
                    with conn.cursor(pymysql.cursors.DictCursor) as cur:
                        cur.execute("""
                            SELECT nav FROM nav_daily 
                            WHERE fund_code = %s AND trade_date < %s
                            ORDER BY trade_date DESC LIMIT 1
                        """, (r["code"], today_str))
                        yesterday_row = cur.fetchone()
                        
                        if yesterday_row:
                            nav_yesterday = float(yesterday_row['nav'])
                            market_value_yesterday = nav_yesterday * shares
                            total_yesterday_value += market_value_yesterday
                            profit_today = market_value_today - market_value_yesterday
                            total_today += profit_today
                            status = "📤已卖出" if is_sold else "✅ 持有"
                            lines.append(f"| {r['name'][:8]} | {int(principal)}元 | {market_value_yesterday:.0f}元 | {market_value_today:.0f}元 | {signed(profit_today)}元 | {status} |")
                        else:
                            # 无昨日净值，按投入金额计算
                            total_yesterday_value += principal
                            profit_today = market_value_today - principal
                            total_today += profit_today
                            lines.append(f"| {r['name'][:8]} | {int(principal)}元 | {int(principal)}元 | {market_value_today:.0f}元 | {signed(profit_today)}元 | ✅ 持有 |")
                finally:
                    conn.close()
            else:
                # 无法计算市值，按投入金额计算
                total_market_value += principal
                total_yesterday_value += principal
                lines.append(f"| {r['name'][:8]} | {int(principal)}元 | {int(principal)}元 | {int(principal)}元 | -- | ✅ 持有 |")
    
    total_profit = total_market_value - total_principal
    lines.append(f"| **总额** | **{int(total_principal)}元** | **{int(total_yesterday_value)}元** | **{int(total_market_value)}元** | **{signed(total_today)}元** | |")
    lines.append("")

    # ── 今日卖出记录 ──
    try:
        conn = get_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT fund_code, fund_name, amount, actual_sell_nav, actual_return, 
                       hold_days, fee, net_return, notes
                FROM trades 
                WHERE trade_status = '已卖出' 
                AND DATE(updated_at) = %s
            """, (today_str,))
            sold_today = cur.fetchall()
        conn.close()
    except Exception:
        sold_today = []

    if sold_today:
        lines.append("**📤 今日卖出**")
        lines.append("| 基金 | 本金 | 卖出净值 | 持有天数 | 手续费 | 收益 |")
        lines.append("|:--|:--|:--|:--|:--|:--|")
        for s in sold_today:
            amt = float(s.get('amount', 0))
            sell_nav = s.get('actual_sell_nav', '--')
            hold = s.get('hold_days', '--')
            fee_val = s.get('fee')
            net_ret = s.get('net_return')
            ret_pct = s.get('actual_return', 0)
            # 如果fee/net_return为空，用actual_return估算
            if net_ret is None and ret_pct is not None:
                net_ret = round(amt * float(ret_pct) / 100, 2)
            if fee_val is None:
                fee_val = 0
            net_ret = net_ret or 0
            sign = '+' if float(net_ret) >= 0 else ''
            lines.append(f"| {s['fund_name'][:8]} | {int(amt)}元 | {sell_nav} | {hold}天 | {fee_val} | {sign}{ret_pct}%/{sign}{net_ret}元 |")
        lines.append("")
    
    # ── 分析与建议 ──
    lines.append("**💡 分析与建议**")
    
    # 统计今日新买入
    new_buys = [r for r in rows if r.get("ok") and r["buy_date"] == today_str]
    old_holds = [r for r in rows if r.get("ok") and r["buy_date"] != today_str]
    
    if new_buys:
        new_names = "、".join(r["name"][:8] for r in new_buys)
        lines.append(f"- 🆕 今日新买入：{new_names}，明日出净值后开始计算收益。")
    
    if old_holds:
        # 计算旧持仓的平均涨跌
        valid_nav_return = [r["nav_return"] for r in old_holds if r.get("nav_return") is not None]
        if valid_nav_return:
            avg = sum(valid_nav_return) / len(valid_nav_return)
            if avg >= 3:
                lines.append("- 📈 旧持仓整体上涨，持有观望。")
            elif avg <= -3:
                lines.append("- 📉 旧持仓回调，观察是否触及止损线。")
            else:
                lines.append("- ➡️ 旧持仓小幅波动，持仓观望。")
    
    if mode == "intraday":
        summary = f"今日预估收益 **{signed(total_today)}元**，市值 {int(total_market_value)}元，累计盈亏 {signed(total_profit)}元。"
    else:
        summary = f"今日净值收益 **{signed(total_today)}元**，市值 {int(total_market_value)}元，累计盈亏 {signed(total_profit)}元。"
    
    lines.append(summary)
    
    return "\n".join(lines)


def save_report(report: str, mode: str) -> str:
    """保存报告到本地文件，推送失败也不丢数据"""
    import os
    report_dir = os.path.expanduser("~/user_files/documents")
    os.makedirs(report_dir, exist_ok=True)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    filename = f"fund_report_{mode}_{today}.md"
    filepath = os.path.join(report_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    return filepath


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "evening"
    if mode not in {"intraday", "evening"}:
        print("mode must be intraday or evening", file=sys.stderr)
        sys.exit(2)
    report = build_report(mode)
    # 同时保存到本地文件（推送失败也不丢数据）
    filepath = save_report(report, mode)
    print(report)
    print(f"\n📁 报告已保存: {filepath}")
