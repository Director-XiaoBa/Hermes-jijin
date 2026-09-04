#!/usr/bin/env python3
"""历史净值回填脚本 — 一次性拉取N天数据写入nav_daily。
用法：~/.hermes/venv-fund/bin/python3 backfill_nav.py [天数，默认90]
依赖：pymysql, urllib, json
"""
import pymysql, json, urllib.request, datetime, time, sys

DB_CONFIG = {
    'host': '127.0.0.1', 'port': 3306,
    'user': 'fund_admin', 'password': 'FundR2026!db',
    'database': 'fund_research', 'charset': 'utf8mb4',
}

# 从funds表动态读取，而非硬编码
def get_active_funds():
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT code, name FROM funds ORDER BY code")
    funds = cursor.fetchall()
    conn.close()
    return [f[0] for f in funds]

def fetch_nav_history(code, days=90):
    all_navs = []
    for page in range(1, 5):
        url = f'https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery&fundCode={code}&pageIndex={page}&pageSize=30'
        req = urllib.request.Request(url, headers={
            'Referer': 'https://fundf10.eastmoney.com/', 'User-Agent': 'Mozilla/5.0'
        })
        try:
            raw = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
            json_str = raw[raw.index('(') + 1:raw.rindex(')')]
            data = json.loads(json_str)
            items = data.get('Data', {}).get('LSJZList', [])
            if not items: break
            for item in items:
                all_navs.append((item['FSRQ'], float(item['DWJZ'])))
        except Exception as e:
            print(f"  {code} page {page} 失败: {e}")
            break
        time.sleep(0.3)
    all_navs.reverse()
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    return [(d, n) for d, n in all_navs if d >= cutoff]

def calc_metrics(navs):
    """计算所有技术指标（涨跌幅/连涨/位置标签等）"""
    if len(navs) < 2: return []
    results = []
    for i in range(len(navs)):
        date, nav = navs[i]
        daily_return = None
        if i > 0 and navs[i-1][1] > 0:
            daily_return = round((nav - navs[i-1][1]) / navs[i-1][1] * 100, 4)
        def calc_return(n):
            if i + 1 < n: return None
            start = navs[i - n + 1][1]
            return round((nav - start) / start * 100, 4) if start > 0 else None
        recent_20 = [n for _, n in navs[max(0, i-19):i+1]]
        high_20d = max(recent_20) if recent_20 else None
        low_20d = min(recent_20) if recent_20 else None
        drawdown = round((nav / high_20d - 1) * 100, 4) if high_20d and high_20d > 0 else None
        up = down = 0
        for j in range(i, max(0, i-10), -1):
            if j > 0:
                if navs[j][1] > navs[j-1][1]:
                    if down > 0: break
                    up += 1
                elif navs[j][1] < navs[j-1][1]:
                    if up > 0: break
                    down += 1
                else: break
        pos = None
        if high_20d and low_20d and high_20d > low_20d:
            pct = (nav - low_20d) / (high_20d - low_20d) * 100
            pos = '高位' if pct > 80 else '低位' if pct < 20 else '中位'
        pattern = None
        if daily_return is not None:
            if daily_return > 2: pattern = '大涨'
            elif daily_return < -2: pattern = '大跌'
            elif abs(daily_return) < 0.3: pattern = '横盘'
        results.append({
            'trade_date': date, 'nav': nav, 'daily_return': daily_return,
            'return_3d': calc_return(3), 'return_5d': calc_return(5),
            'return_10d': calc_return(10), 'return_20d': calc_return(20),
            'high_20d': high_20d, 'low_20d': low_20d, 'drawdown_from_high': drawdown,
            'consecutive_up': up, 'consecutive_down': down,
            'price_pattern': pattern, 'position_label': pos,
        })
    return results

if __name__ == '__main__':
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    codes = get_active_funds()
    print(f"回填 {len(codes)} 只基金最近 {days} 天净值...\n")
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    sql = """INSERT INTO nav_daily
        (fund_code, trade_date, nav, daily_return, return_3d, return_5d, return_10d, return_20d,
         high_20d, low_20d, drawdown_from_high, consecutive_up, consecutive_down, price_pattern, position_label)
        VALUES (%(fund_code)s, %(trade_date)s, %(nav)s, %(daily_return)s, %(return_3d)s, %(return_5d)s,
                %(return_10d)s, %(return_20d)s, %(high_20d)s, %(low_20d)s, %(drawdown_from_high)s,
                %(consecutive_up)s, %(consecutive_down)s, %(price_pattern)s, %(position_label)s)
        ON DUPLICATE KEY UPDATE
            nav=VALUES(nav), daily_return=VALUES(daily_return),
            return_3d=VALUES(return_3d), return_5d=VALUES(return_5d),
            return_10d=VALUES(return_10d), return_20d=VALUES(return_20d),
            high_20d=VALUES(high_20d), low_20d=VALUES(low_20d),
            drawdown_from_high=VALUES(drawdown_from_high),
            consecutive_up=VALUES(consecutive_up), consecutive_down=VALUES(consecutive_down),
            price_pattern=VALUES(price_pattern), position_label=VALUES(position_label)"""
    total = 0
    for code in codes:
        print(f"  {code}...", end=" ")
        navs = fetch_nav_history(code, days)
        if not navs: print("无数据"); continue
        metrics = calc_metrics(navs)
        for m in metrics: m['fund_code'] = code
        cursor.executemany(sql, metrics)
        total += len(metrics)
        print(f"✅ {len(navs)}天")
        time.sleep(0.5)
    conn.commit()
    conn.close()
    print(f"\n完成，共写入 {total} 条")
