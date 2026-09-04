#!/home/ubuntu/.hermes/venv-fund/bin/python3
"""基金每日收盘数据Pipeline：采集最终净值+市场数据 → 计算指标 → 写入MySQL → 生成Snapshot。
设计目标：15:30收盘后运行，总耗时<60秒。与fund_scan_data.py独立，不修改原有脚本。
"""
import urllib.request, re, json, ssl, datetime, os, time
import pymysql

# ── 配置 ──
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': 'FundR2026!db',
    'database': 'fund_research',
    'charset': 'utf8mb4',
}
SNAPSHOT_DIR = os.path.expanduser('~/user_files/documents')

# 关注基金列表（与fund_scan_data.py保持同步）
CODES = ['017811','012738','019919','017470','018345','011036','012863','017102',
         '008586','018301','004433','025833','011613','025422','025209']

# 关注的市场指数
MARKET_INDICES = {
    '上证指数': 'sh000001',
    '创业板': 'sz399006',
    '科创50': 'sh000688',
    '中证1000': 'sh000852',
    '沪深300': 'sh000300',
    '半导体ETF': 'sz159995',
    '科创芯片': 'sh000685',
    '黄金ETF': 'sh518880',
}

# 行业板块关注列表
FOCUS_INDUSTRIES = ['半导体', '芯片', 'CPO', 'AI', '机器人', '创新药', '稀土', '有色金属', '黄金']

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

def detect_price_pattern(open_p, high, low, close, prev_close):
    """根据OHLC判断价格行为形态"""
    if not all([open_p, high, low, close, prev_close]): return None
    try:
        open_p, high, low, close, prev_close = float(open_p), float(high), float(low), float(close), float(prev_close)
    except: return None
    
    if prev_close == 0: return None
    change_pct = (close - prev_close) / prev_close * 100
    high_change = (high - prev_close) / prev_close * 100
    open_gap = (open_p - prev_close) / prev_close * 100
    
    if high_change > 2 and change_pct < high_change * 0.5:
        return '冲高回落'
    low_change = (low - prev_close) / prev_close * 100
    if low_change < -2 and change_pct > low_change * 0.5:
        return '探底回升'
    
    is_high_open = open_gap > 0.3
    is_low_open = open_gap < -0.3
    
    if is_high_open and change_pct > 0.3: return '高开高走'
    elif is_high_open and change_pct < -0.3: return '高开低走'
    elif is_low_open and change_pct > 0.3: return '低开高走'
    elif is_low_open and change_pct < -0.3: return '低开低走'
    else: return '横盘'

def calc_consecutive(arr, key='equityReturn'):
    if not arr or len(arr) < 2: return 0, 0
    up = down = 0
    for x in reversed(arr):
        r = x.get(key) or 0
        if r > 0:
            if down > 0: break
            up += 1
        elif r < 0:
            if up > 0: break
            down += 1
        else: break
    return up, down

def calc_return(arr, n):
    if not arr or len(arr) < n: return None
    val = 1.0
    for x in arr[-n:]:
        r = x.get('equityReturn') or 0
        val *= (1 + r / 100)
    return (val - 1) * 100

def calc_position_label(nav, high_20d, low_20d):
    if not all([nav, high_20d, low_20d]) or high_20d == low_20d: return None
    pct = (nav - low_20d) / (high_20d - low_20d) * 100
    if pct > 80: return '高位'
    elif pct < 20: return '低位'
    else: return '中位'

# ── 主流程 ──
today = datetime.date.today()
today_str = today.strftime('%Y-%m-%d')
print(f"[Pipeline] {today_str} 开始运行")
out = []
db_rows_nav = []
db_rows_market = []

# ── 1. 拉指数数据（新浪） ──
print("  [1/4] 拉取市场指数...")
index_data = {}
try:
    codes_str = ','.join(MARKET_INDICES.values())
    raw = http(f"https://hq.sinajs.cn/list={codes_str}",
               {"Referer": "https://finance.sina.com.cn"}).decode('gbk', 'ignore')
    for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', raw):
        code, data = m.group(1), m.group(2)
        f = data.split(',')
        if len(f) < 6 or not f[0]: continue
        try:
            open_p = float(f[1]); prev_close = float(f[2]); current = float(f[3])
            high = float(f[4]); low = float(f[5])
            pct = (current / prev_close - 1) * 100 if prev_close else 0
            name = [k for k, v in MARKET_INDICES.items() if v == code]
            name = name[0] if name else code
            pattern = detect_price_pattern(open_p, high, low, current, prev_close)
            index_data[name] = {'code': code, 'name': name, 'close': current, 'open': open_p,
                'high': high, 'low': low, 'prev_close': prev_close, 'return': pct, 'pattern': pattern}
            db_rows_market.append({'trade_date': today, 'index_name': name, 'index_code': code,
                'close_price': current, 'daily_return': round(pct, 4), 'open_price': open_p,
                'high': high, 'low': low, 'prev_close': prev_close, 'price_pattern': pattern})
        except: pass
except Exception as e:
    print(f"  指数获取失败: {e}")

# ── 2. 拉基金净值+计算指标 ──
print("  [2/4] 拉取基金净值并计算指标...")
fund_data = {}
for c in CODES:
    try:
        txt = http(f"https://fund.eastmoney.com/pingzhongdata/{c}.js").decode('utf-8', 'ignore')
        nm = re.search(r'fS_name\s*=\s*"([^"]+)"', txt)
        name = nm.group(1) if nm else c
        raw = grab('Data_netWorthTrend', txt)
        if not raw: continue
        arr = json.loads(raw)
        if len(arr) < 5: continue
        latest = arr[-1]
        nav = latest.get('y', 0); daily_ret = latest.get('equityReturn', 0)
        trade_date = datetime.datetime.fromtimestamp(latest['x'] / 1000).date()
        ret_3d = calc_return(arr, 3); ret_5d = calc_return(arr, 5)
        ret_10d = calc_return(arr, 10); ret_20d = calc_return(arr, 20)
        recent_20 = arr[-20:] if len(arr) >= 20 else arr
        high_20d = max(x.get('y', 0) for x in recent_20)
        low_20d = min(x.get('y', 0) for x in recent_20)
        drawdown = (nav / high_20d - 1) * 100 if high_20d else 0
        up, down = calc_consecutive(arr)
        position = calc_position_label(nav, high_20d, low_20d)
        fund_data[c] = {'name': name, 'nav': nav, 'daily_return': daily_ret, 'trade_date': trade_date,
            'return_3d': ret_3d, 'return_5d': ret_5d, 'return_10d': ret_10d, 'return_20d': ret_20d,
            'high_20d': high_20d, 'low_20d': low_20d, 'drawdown': drawdown,
            'consecutive_up': up, 'consecutive_down': down, 'position': position}
        pattern = None
        if daily_ret > 2: pattern = '大涨'
        elif daily_ret < -2: pattern = '大跌'
        elif abs(daily_ret) < 0.3: pattern = '横盘'
        db_rows_nav.append({'fund_code': c, 'trade_date': trade_date, 'nav': nav,
            'daily_return': round(daily_ret, 4),
            'return_3d': round(ret_3d, 4) if ret_3d else None,
            'return_5d': round(ret_5d, 4) if ret_5d else None,
            'return_10d': round(ret_10d, 4) if ret_10d else None,
            'return_20d': round(ret_20d, 4) if ret_20d else None,
            'high_20d': high_20d, 'low_20d': low_20d,
            'drawdown_from_high': round(drawdown, 4),
            'consecutive_up': up, 'consecutive_down': down,
            'price_pattern': pattern, 'position_label': position})
        print(f"  {c} {name[:8]}: {nav:.4f} ({daily_ret:+.2f}%) 连涨{up}/连跌{down} {position or ''}")
    except Exception as e:
        print(f"  {c} 失败: {e}")

# ── 3. 拉板块涨幅（东财，带重试） ──
print("  [3/4] 拉取行业板块...")
sector_data = []
for attempt in range(3):
    try:
        raw = http("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=30&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f2,f3,f14",
                   {"Referer": "https://quote.eastmoney.com/"}).decode('utf-8', 'ignore')
        d = json.loads(raw)
        for it in d.get('data', {}).get('diff', [])[:30]:
            sector_data.append({'name': it.get('f14', ''), 'return': it.get('f3', 0)})
        break
    except Exception:
        if attempt < 2: time.sleep(2)
        else: print(f"  板块榜失败: 重试3次后仍限流")

# ── 4. 写入MySQL ──
print("  [4/4] 写入MySQL...")
conn = None
try:
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    sql_nav = """INSERT INTO nav_daily 
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
    cursor.executemany(sql_nav, db_rows_nav)
    print(f"  nav_daily: 写入{cursor.rowcount}条")
    sql_market = """INSERT INTO market_daily
        (trade_date, index_name, index_code, close_price, daily_return, open_price, high, low, prev_close, price_pattern)
        VALUES (%(trade_date)s, %(index_name)s, %(index_code)s, %(close_price)s, %(daily_return)s,
                %(open_price)s, %(high)s, %(low)s, %(prev_close)s, %(price_pattern)s)
        ON DUPLICATE KEY UPDATE
            close_price=VALUES(close_price), daily_return=VALUES(daily_return),
            open_price=VALUES(open_price), high=VALUES(high), low=VALUES(low),
            prev_close=VALUES(prev_close), price_pattern=VALUES(price_pattern)"""
    cursor.executemany(sql_market, db_rows_market)
    print(f"  market_daily: 写入{cursor.rowcount}条")
    conn.commit()
    print("  MySQL写入完成 ✅")
except Exception as e:
    print(f"  MySQL写入失败: {e}")
    if conn: conn.rollback()
finally:
    if conn: conn.close()

# ── 5. 生成Market Snapshot ──
print("  生成Market Snapshot...")
snapshot_lines = [f"# Market Snapshot {today_str}\n", "## 大盘概况\n"]
for name in ['上证指数', '创业板', '科创50', '沪深300', '中证1000']:
    if name in index_data:
        d = index_data[name]
        snapshot_lines.append(f"- {name}: {d['close']:.2f} ({d['return']:+.2f}%) {d.get('pattern','')}")
snapshot_lines.append("\n## 行业板块TOP10\n")
for s in sector_data[:10]:
    snapshot_lines.append(f"- {s['name']}: {s['return']:+.2f}%")
snapshot_lines.append("\n## 关注行业\n")
focus_found = [s for s in sector_data if any(fi in s['name'] for fi in FOCUS_INDUSTRIES)]
for s in focus_found[:15]:
    snapshot_lines.append(f"- {s['name']}: {s['return']:+.2f}%")
snapshot_lines.append("\n## 关注基金\n")
snapshot_lines.append("| 代码 | 名称 | 净值 | 今日 | 3日 | 5日 | 回撤 | 连涨/跌 | 位置 |")
snapshot_lines.append("|:--|:--|:--:|:--:|:--:|:--:|:--:|:--:|:--:|")
for c in CODES:
    if c in fund_data:
        fd = fund_data[c]
        up_down = f"{fd['consecutive_up']}↑" if fd['consecutive_up'] > 0 else f"{fd['consecutive_down']}↓" if fd['consecutive_down'] > 0 else "-"
        r3 = f"{fd['return_3d']:+.1f}%" if fd['return_3d'] is not None else "-"
        r5 = f"{fd['return_5d']:+.1f}%" if fd['return_5d'] is not None else "-"
        snapshot_lines.append(f"| {c} | {fd['name'][:8]} | {fd['nav']:.4f} | {fd['daily_return']:+.2f}% | {r3} | {r5} | {fd['drawdown']:+.1f}% | {up_down} | {fd['position'] or '-'} |")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
snapshot_path = os.path.join(SNAPSHOT_DIR, f'market_snapshot_{today.strftime("%Y%m%d")}.md')
with open(snapshot_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(snapshot_lines))
print(f"  Snapshot已生成: {snapshot_path}")
print(f"\n{'='*50}\nPipeline完成: {today_str}\n  基金: {len(db_rows_nav)}条 | 市场: {len(db_rows_market)}条 | 板块: {len(sector_data)}个\n{'='*50}")
