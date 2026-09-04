#!/usr/bin/env python3
"""
黄金监控系统 v3.0 - 正式版
数据源：华安黄金ETF联接C（000217）实际净值
"""
import urllib.request
import json
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.expanduser("~/user_files/documents/gold_monitor.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS gold_daily (
        date TEXT PRIMARY KEY,
        nav REAL,
        change_pct REAL,
        rsi_14 REAL,
        ma20 REAL,
        ma60 REAL,
        trend TEXT,
        signal_score INTEGER,
        signal_action TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn

def fetch_fund_nav(fund_code='000217', days=90):
    """获取基金净值数据（分页获取，确保足够MA60计算）"""
    all_navs = []
    page_size = 20  # API每页最多20条
    max_pages = (days // page_size) + 1  # 计算需要多少页
    
    for page in range(1, max_pages + 1):
        url = f'https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery&fundCode={fund_code}&pageIndex={page}&pageSize={page_size}'
        headers = {'Referer': 'https://fundf10.eastmoney.com/', 'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        try:
            raw = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='ignore')
            json_str = raw[raw.index('(') + 1:raw.rindex(')')]
            data = json.loads(json_str)
            if data.get('Data') and data['Data'].get('LSJZList'):
                navs = data['Data']['LSJZList']
                if not navs:
                    break
                for item in navs:
                    all_navs.append({
                        'date': item['FSRQ'],
                        'nav': float(item['DWJZ']),
                        'change': float(item['JZZZL']) if item['JZZZL'] else 0
                    })
            else:
                break
        except Exception as e:
            print(f"获取第{page}页数据失败: {e}")
            break
    
    return all_navs

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calculate_ma(closes, period):
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)

def analyze_gold():
    conn = init_db()
    
    print("=" * 70)
    print(f"📊 黄金每日监控报告 v3.0")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"📈 标的：华安黄金ETF联接C（000217）")
    print("=" * 70)
    
    # 获取净值数据
    navs = fetch_fund_nav('000217', 90)
    if not navs:
        print("❌ 无法获取净值数据")
        return
    
    # 反转为时间正序
    navs.reverse()
    
    dates = [n['date'] for n in navs]
    closes = [n['nav'] for n in navs]
    latest = closes[-1]
    latest_date = dates[-1]
    
    # 计算指标
    ma20 = calculate_ma(closes, 20)
    ma60 = calculate_ma(closes, 60)
    rsi = calculate_rsi(closes, 14)
    
    # 趋势判断
    if ma20 and ma60:
        uptrend = ma20 > ma60
        trend = "上升趋势 ✅" if uptrend else "下降趋势 ❌"
    else:
        uptrend = None
        trend = "数据不足"
    
    # 输出数据
    print(f"\n📈 最新净值")
    print(f"日期: {latest_date}")
    print(f"净值: {latest}")
    print(f"今日涨跌: {navs[-1]['change']:+.2f}%")
    
    print(f"\n📊 技术指标")
    if ma20:
        print(f"20日均线: {ma20}")
    if ma60:
        print(f"60日均线: {ma60}")
    if rsi:
        print(f"RSI(14): {rsi}")
    print(f"趋势判断: {trend}")
    
    # 信号判断
    print("\n" + "=" * 70)
    print("🎯 信号判断")
    print("=" * 70)
    
    score = 0
    signals = []
    
    # 条件1: MA20 > MA60
    if uptrend is True:
        score += 1
        signals.append("✅ MA20 > MA60（上升趋势）")
    elif uptrend is False:
        signals.append("❌ MA20 < MA60（下降趋势）")
    
    # 条件2: 价格在MA20附近
    if ma20 and latest < ma20 * 1.02:
        score += 1
        signals.append("✅ 价格在MA20附近（回调）")
    else:
        signals.append("❌ 价格偏离MA20较远")
    
    # 条件3: RSI从超卖回升
    if rsi and 40 < rsi < 60:
        score += 1
        signals.append(f"✅ RSI={rsi}（中性偏强）")
    elif rsi and rsi < 40:
        signals.append(f"⚠️ RSI={rsi}（超卖）")
    else:
        signals.append(f"❌ RSI={rsi}（超买）")
    
    for s in signals:
        print(s)
    
    print(f"\n📊 综合得分: {score}/3")
    
    # 操作建议
    print("\n" + "=" * 70)
    print("💡 操作建议")
    print("=" * 70)
    
    if score >= 3:
        print("🟢 强烈买入信号！")
        print("   建议：买入1000元")
        action = "强烈买入"
    elif score == 2:
        print("🟡 准备买入信号")
        print("   建议：可以挂单等待")
        action = "准备买入"
    elif score == 1:
        print("🔵 关注信号")
        print("   建议：暂不操作")
        action = "关注"
    else:
        print("🔴 观望信号")
        print("   建议：不买入")
        action = "观望"
    
    # 近5日走势
    print("\n" + "=" * 70)
    print("📅 近5日走势")
    print("=" * 70)
    for n in navs[-5:]:
        emoji = "🟢" if n['change'] > 0 else "🔴" if n['change'] < 0 else "⚪"
        print(f"{n['date']}: {n['nav']} ({n['change']:+.2f}%) {emoji}")
    
    # 保存到数据库
    try:
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO gold_daily 
            (date, nav, change_pct, rsi_14, ma20, ma60, trend, signal_score, signal_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (latest_date, latest, navs[-1]['change'], rsi, ma20, ma60, trend, score, action))
        conn.commit()
        print(f"\n✅ 数据已保存")
    except Exception as e:
        print(f"\n⚠️ 保存失败: {e}")
    
    conn.close()

if __name__ == "__main__":
    analyze_gold()
