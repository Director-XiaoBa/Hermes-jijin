#!/home/ubuntu/.hermes/venv-fund/bin/python3
"""基金净值更新脚本（22:00主更新 + 22:30兜底）
只做一件事：拉取今日净值 → 计算技术指标 → 写入nav_daily。
不拉ETF行情、不拉板块、不出报告。
"""
import urllib.request, re, json, ssl, datetime, os, time, sys
import pymysql

sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_holdings, get_connection

DB_CONFIG = {
    'host': '127.0.0.1', 'port': 3306,
    'user': 'fund_admin', 'password': '<REDACTED>',
    'database': 'fund_research', 'charset': 'utf8mb4',
}

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0'}

def http(url, headers=None, timeout=12):
    h = dict(UA); h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout, context=ctx).read()

def grab(name, txt):
    m = re.search(name + r'\s*=\s*', txt)
    if not m: return None
    start = m.end(); depth = 0; i = start
    while i < len(txt):
        if txt[i] in '[{': depth += 1
        elif txt[i] in ']}':
            depth -= 1
            if depth == 0: break
        i += 1
    return txt[start:i+1]

def calc_ma(data, n):
    if len(data) < n: return None
    return sum(data[-n:]) / n

def calc_rsi(data, n):
    if len(data) < n + 1: return None
    gains, losses = [], []
    for i in range(-n, 0):
        diff = data[i] - data[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / n
    avg_loss = sum(losses) / n
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 4)

def calc_ema(data, n):
    if not data: return None
    k = 2 / (n + 1)
    ema = data[0]
    for v in data[1:]:
        ema = v * k + ema * (1 - k)
    return ema

def calc_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal: return None, None, None
    ema_fast = calc_ema(prices, fast)
    ema_slow = calc_ema(prices, slow)
    macd_line = ema_fast - ema_slow if ema_slow else 0
    macd_values = []
    k_fast = 2 / (fast + 1)
    k_slow = 2 / (slow + 1)
    ef = prices[0]; es = prices[0]
    for p in prices[1:]:
        ef = p * k_fast + ef * (1 - k_fast)
        es = p * k_slow + es * (1 - k_slow)
        macd_values.append(ef - es)
    if len(macd_values) < signal: return None, None, None
    signal_line = calc_ema(macd_values[-signal:], signal)
    histogram = macd_values[-1] - signal_line if signal_line else None
    return round(macd_values[-1], 4), round(signal_line, 4) if signal_line else None, round(histogram, 4) if histogram else None

def calc_trend(navs):
    if len(navs) < 20: return 'unknown'
    ma5 = sum(navs[-5:]) / 5
    ma10 = sum(navs[-10:]) / 10
    ma20 = sum(navs[-20:]) / 20
    if ma5 > ma10 > ma20: return 'up'
    elif ma5 < ma10 < ma20: return 'down'
    else: return 'sideways'

def calc_support_resistance(navs):
    if len(navs) < 20: return None, None
    recent = navs[-20:]
    return round(min(recent), 4), round(max(recent), 4)

def calc_return(arr, n):
    if len(arr) < n + 1: return None
    return round((arr[-1]['y'] / arr[-(n+1)]['y'] - 1) * 100, 4)

def calc_consecutive(arr):
    if len(arr) < 2: return 0, 0
    up = down = 0
    for x in reversed(arr):
        r = x.get('equityReturn', 0)
        if r > 0: up += 1
        else: break
    for x in reversed(arr):
        r = x.get('equityReturn', 0)
        if r < 0: down += 1
        else: break
    return up, down

def detect_simple_pattern(daily_ret):
    if daily_ret is None: return None
    if daily_ret >= 5: return '大阳线'
    elif daily_ret >= 2: return '中阳线'
    elif daily_ret > 0: return '小阳线'
    elif daily_ret > -2: return '小阴线'
    elif daily_ret > -5: return '中阴线'
    else: return '大阴线'


def fetch_nav_fallback(code):
    """备用数据源：天天基金FundMApi接口（支付宝同源）"""
    try:
        url = f"https://fundmobapi.eastmoney.com/FundMApi/FundBasicInformation.ashx?FCODE={code}&deviceid=appfund&plat=Iphone&product=EFund&Version=1"
        txt = http(url).decode('utf-8', 'ignore')
        data = json.loads(txt)
        d = data.get('Datas', {})
        if not d or not d.get('DWJZ'):
            return None
        nav = float(d['DWJZ'])
        daily_ret = float(d.get('RZDF', 0))
        trade_date = datetime.datetime.strptime(d['FSRQ'], '%Y-%m-%d').date()
        name = d.get('SHORTNAME', code)
        today = datetime.date.today()
        if trade_date != today:
            return None
        return {
            'fund_code': code,
            'fund_name': name,
            'trade_date': trade_date,
            'nav': nav,
            'daily_return': round(daily_ret, 4),
            'data_source': 'fund_api_fallback',
        }
    except Exception as e:
        print(f"  ⚠️ {code} 备用接口也失败: {e}")
        return None

def fetch_nav(code):
    """拉取单只基金净值+技术指标，返回dict或None（无今日净值）"""
    try:
        txt = http(f"https://fund.eastmoney.com/pingzhongdata/{code}.js").decode('utf-8', 'ignore')
        nm = re.search(r'fS_name\s*=\s*"([^"]+)"', txt)
        name = nm.group(1) if nm else code
        raw = grab('Data_netWorthTrend', txt)
        if not raw: return None
        arr = json.loads(raw)
        if len(arr) < 5: return None

        navs = [x.get('y', 0) for x in arr]
        latest = arr[-1]
        nav = latest.get('y', 0)
        daily_ret = latest.get('equityReturn', 0)
        trade_date = datetime.datetime.fromtimestamp(latest['x'] / 1000).date()

        today = datetime.date.today()
        if trade_date != today:
            # 主接口没今日净值，尝试备用接口
            fb = fetch_nav_fallback(code)
            if fb:
                print(f"  ✅ {code} 主接口无今日数据，备用接口成功: {fb['nav']}")
                return fb
            return None  # 不是今日净值，跳过

        # 计算指标
        ma5 = calc_ma(navs, 5)
        ma10 = calc_ma(navs, 10)
        ma20 = calc_ma(navs, 20)
        ma60 = calc_ma(navs, 60)
        rsi_6 = calc_rsi(navs, 6)
        rsi_12 = calc_rsi(navs, 12)
        macd_line, signal_line, histogram = calc_macd(navs)
        trend = calc_trend(navs)
        support, resistance = calc_support_resistance(navs)
        ret_3d = calc_return(arr, 3)
        ret_5d = calc_return(arr, 5)
        ret_10d = calc_return(arr, 10)
        ret_20d = calc_return(arr, 20)
        recent_20 = navs[-20:] if len(navs) >= 20 else navs
        high_20d = max(recent_20)
        low_20d = min(recent_20)
        drawdown = (nav / high_20d - 1) * 100 if high_20d else 0
        up, down = calc_consecutive(arr)
        position = f"{low_20d:.4f}-{high_20d:.4f}"
        simple_pattern = detect_simple_pattern(daily_ret)

        return {
            'fund_code': code, 'fund_name': name, 'trade_date': trade_date,
            'nav': nav, 'daily_return': round(daily_ret, 4),
            'return_3d': round(ret_3d, 4) if ret_3d else None,
            'return_5d': round(ret_5d, 4) if ret_5d else None,
            'return_10d': round(ret_10d, 4) if ret_10d else None,
            'return_20d': round(ret_20d, 4) if ret_20d else None,
            'high_20d': high_20d, 'low_20d': low_20d,
            'drawdown_from_high': round(drawdown, 4),
            'consecutive_up': up, 'consecutive_down': down,
            'price_pattern': simple_pattern, 'position_label': position,
            'ma5': round(ma5, 4) if ma5 else None,
            'ma10': round(ma10, 4) if ma10 else None,
            'ma20': round(ma20, 4) if ma20 else None,
            'ma60': round(ma60, 4) if ma60 else None,
            'rsi_6': round(rsi_6, 4) if rsi_6 else None,
            'rsi_12': round(rsi_12, 4) if rsi_12 else None,
            'macd_line': round(macd_line, 4) if macd_line else None,
            'signal_line': round(signal_line, 4) if signal_line else None,
            'macd_histogram': round(histogram, 4) if histogram else None,
            'trend': trend, 'support': support, 'resistance': resistance,
            'data_source': 'fund_nav',
        }
    except Exception as e:
        print(f"  ❌ {code} 拉取失败: {e}")
        return None


def main():
    """主函数：mode=fallback时只更新缺净值的基金"""
    mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')

    # 持仓基金 + 近7天卖出的基金（需要记录卖出净值）
    holdings = get_holdings()
    codes = [h['fund_code'] for h in holdings]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if codes:
                placeholders = ','.join(['%s'] * len(codes))
                cur.execute(f"""
                    SELECT DISTINCT fund_code FROM trades 
                    WHERE trade_status = '已卖出' AND sell_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                    AND fund_code NOT IN ({placeholders})
                """, codes)
            else:
                cur.execute("""
                    SELECT DISTINCT fund_code FROM trades 
                    WHERE trade_status = '已卖出' AND sell_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                """)
            for row in cur.fetchall():
                if row[0] not in codes:
                    codes.append(row[0])
    finally:
        conn.close()
    print(f"📋 待更新基金: {len(codes)}只 (模式: {mode})")

    # fallback模式：只更新今天还没净值的基金
    if mode == 'fallback':
        conn = pymysql.connect(**DB_CONFIG)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT fund_code FROM nav_daily WHERE trade_date = %s",
                    (today_str,)
                )
                has_nav = {r[0] for r in cur.fetchall()}
        finally:
            conn.close()
        before = len(codes)
        codes = [c for c in codes if c not in has_nav]
        print(f"  兜底模式: {before}只中{len(has_nav)}只已有净值，还需更新{len(codes)}只")
        if not codes:
            print("✅ 所有基金已有今日净值，无需兜底")
            return

    # 拉取净值
    results = []
    skipped = []
    for c in codes:
        time.sleep(0.3)  # 避免限流
        r = fetch_nav(c)
        if r:
            results.append(r)
            print(f"  ✅ {r['fund_name'][:8]} {r['nav']:.4f} ({r['daily_return']:+.2f}%)")
        else:
            skipped.append(c)

    if not results:
        print(f"⚠️ 无今日净值数据（可能净值还没更新）")
        return

    # 补全缺失字段（备用接口返回的dict缺少技术指标字段）
    all_keys = ['return_3d','return_5d','return_10d','return_20d','high_20d','low_20d',
                'drawdown_from_high','consecutive_up','consecutive_down','price_pattern','position_label',
                'ma5','ma10','ma20','ma60','rsi_6','rsi_12','macd_line','signal_line','macd_histogram',
                'trend','support','resistance']
    for r in results:
        for k in all_keys:
            r.setdefault(k, None)

    # 写入数据库
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            sql = """INSERT INTO nav_daily
                (fund_code, trade_date, nav, daily_return, return_3d, return_5d, return_10d, return_20d,
                 high_20d, low_20d, drawdown_from_high, consecutive_up, consecutive_down,
                 price_pattern, position_label,
                 ma5, ma10, ma20, ma60, rsi_6, rsi_12,
                 macd_line, signal_line, macd_histogram, trend, support, resistance, data_source)
                VALUES (%(fund_code)s, %(trade_date)s, %(nav)s, %(daily_return)s, %(return_3d)s, %(return_5d)s,
                        %(return_10d)s, %(return_20d)s, %(high_20d)s, %(low_20d)s, %(drawdown_from_high)s,
                        %(consecutive_up)s, %(consecutive_down)s, %(price_pattern)s, %(position_label)s,
                        %(ma5)s, %(ma10)s, %(ma20)s, %(ma60)s, %(rsi_6)s, %(rsi_12)s,
                        %(macd_line)s, %(signal_line)s, %(macd_histogram)s, %(trend)s, %(support)s, %(resistance)s, %(data_source)s)
                ON DUPLICATE KEY UPDATE
                    nav=VALUES(nav), daily_return=VALUES(daily_return),
                    return_3d=VALUES(return_3d), return_5d=VALUES(return_5d),
                    return_10d=VALUES(return_10d), return_20d=VALUES(return_20d),
                    high_20d=VALUES(high_20d), low_20d=VALUES(low_20d),
                    drawdown_from_high=VALUES(drawdown_from_high),
                    consecutive_up=VALUES(consecutive_up), consecutive_down=VALUES(consecutive_down),
                    price_pattern=VALUES(price_pattern), position_label=VALUES(position_label),
                    ma5=VALUES(ma5), ma10=VALUES(ma10), ma20=VALUES(ma20), ma60=VALUES(ma60),
                    rsi_6=VALUES(rsi_6), rsi_12=VALUES(rsi_12),
                    macd_line=VALUES(macd_line), signal_line=VALUES(signal_line),
                    macd_histogram=VALUES(macd_histogram), trend=VALUES(trend),
                    support=VALUES(support), resistance=VALUES(resistance),
                    data_source=VALUES(data_source)"""
            cur.executemany(sql, results)
            conn.commit()
            print(f"\n✅ nav_daily写入{len(results)}条，跳过{len(skipped)}只")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
