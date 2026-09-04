#!/home/ubuntu/.hermes/venv-fund/bin/python3
"""基金每日收盘数据Pipeline V2 - 全功能版
功能：
1. 拉取ETF行情（OHLC）→ 完整形态判断
2. 拉取基金净值 → 计算技术指标（MA/RSI/MACD）
3. 趋势判断 + 支撑压力位
4. 止损止盈预警
5. 每天复盘
6. 生成Market Snapshot
"""
import urllib.request, re, json, ssl, datetime, os, time
import pymysql

# 导入共享模块
import sys
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_holdings, get_fund_etf_map, get_fund_sectors

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

# 动态获取基金→ETF映射（从funds表）
_fund_etf_raw = get_fund_etf_map()
FUND_ETF_MAP = {code: {'etf': etf, 'name': ''} for code, etf in _fund_etf_raw.items()}

# 动态获取用户持仓（从trades表）
_holdings_raw = get_holdings()
POSITIONS = {}
for h in _holdings_raw:
    POSITIONS[h['fund_code']] = {
        'amount': h['total_amount'],
        'buy_nav': h.get('nav_price', 0),
        'buy_date': h['buy_date'].strftime('%Y-%m-%d') if hasattr(h['buy_date'], 'strftime') else str(h['buy_date']),
        'stop_loss': h.get('stop_loss', -8),
        'take_profit': h.get('take_profit', 10)
    }

# 动态获取关注基金列表（从数据库）
CODES = [h['fund_code'] for h in get_holdings()]

# 市场指数
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

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0'}

def http(url, headers=None, timeout=12):
    h = dict(UA)
    h.update(headers or {})
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

# ── 技术指标计算 ──
def calc_ma(prices, period):
    """计算移动平均线"""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calc_rsi(prices, period=14):
    """计算RSI指标"""
    if len(prices) < period + 1:
        return None
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    if len(gains) < period:
        return None
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 4)

def calc_ema(prices, period):
    """计算指数移动平均"""
    if len(prices) < period:
        return None
    
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    
    return ema

def calc_macd(prices, fast=12, slow=26, signal=9):
    """计算MACD指标"""
    if len(prices) < slow + signal:
        return None, None, None
    
    ema_fast = calc_ema(prices, fast)
    ema_slow = calc_ema(prices, slow)
    
    if ema_fast is None or ema_slow is None:
        return None, None, None
    
    macd_line = ema_fast - ema_slow
    
    # 计算信号线（需要历史MACD值）
    macd_values = []
    for i in range(slow + signal, len(prices) + 1):
        ef = calc_ema(prices[:i], fast)
        es = calc_ema(prices[:i], slow)
        if ef and es:
            macd_values.append(ef - es)
    
    if len(macd_values) < signal:
        return macd_line, None, None
    
    signal_line = calc_ema(macd_values, signal)
    histogram = macd_line - signal_line if signal_line else None
    
    return round(macd_line, 4), round(signal_line, 4) if signal_line else None, round(histogram, 4) if histogram else None

def detect_etf_pattern(open_p, high, low, close, prev_close):
    """用ETF OHLC判断完整形态"""
    if not all([open_p, high, low, close, prev_close]):
        return None
    
    try:
        open_p, high, low, close, prev_close = float(open_p), float(high), float(low), float(close), float(prev_close)
    except:
        return None
    
    if prev_close == 0:
        return None
    
    # 计算关键位置
    open_gap = (open_p - prev_close) / prev_close * 100  # 开盘缺口
    high_change = (high - prev_close) / prev_close * 100  # 最高涨幅
    low_change = (low - prev_close) / prev_close * 100  # 最低跌幅
    close_change = (close - prev_close) / prev_close * 100  # 收盘涨跌
    
    # 判断形态
    is_high_open = open_gap > 0.3  # 高开
    is_low_open = open_gap < -0.3  # 低开
    is_high_close = close_change > 0.3  # 收涨
    is_low_close = close_change < -0.3  # 收跌
    
    # 冲高回落：盘中冲高但收盘回落
    if high_change > 1 and close_change < high_change * 0.5:
        return '冲高回落'
    
    # 探底回升：盘中下跌但收盘拉回
    if low_change < -1 and close_change > low_change * 0.5:
        return '探底回升'
    
    # 高开高走
    if is_high_open and is_high_close:
        return '高开高走'
    
    # 高开低走
    if is_high_open and is_low_close:
        return '高开低走'
    
    # 低开高走
    if is_low_open and is_high_close:
        return '低开高走'
    
    # 低开低走
    if is_low_open and is_low_close:
        return '低开低走'
    
    # 大涨/大跌
    if close_change > 2:
        return '大涨'
    elif close_change < -2:
        return '大跌'
    
    return '横盘'

def detect_simple_pattern(daily_return):
    """场外基金简化形态判断（无OHLC时使用）"""
    if daily_return is None:
        return None
    
    try:
        daily_return = float(daily_return)
    except:
        return None
    
    if daily_return > 2:
        return '大涨'
    elif daily_return < -2:
        return '大跌'
    elif abs(daily_return) < 0.3:
        return '横盘'
    elif daily_return > 0:
        return '小涨'
    else:
        return '小跌'

def calc_trend(prices):
    """判断趋势"""
    if len(prices) < 20:
        return None
    
    ma5 = calc_ma(prices, 5)
    ma20 = calc_ma(prices, 20)
    ma60 = calc_ma(prices, 60) if len(prices) >= 60 else None
    
    current = prices[-1]
    
    # 上升趋势：价格在MA20上方，且MA5 > MA20
    if current > ma20 and ma5 > ma20:
        return '上升'
    
    # 下降趋势：价格在MA20下方，且MA5 < MA20
    if current < ma20 and ma5 < ma20:
        return '下降'
    
    return '震荡'

def calc_support_resistance(prices, period=20):
    """计算支撑位和压力位"""
    if len(prices) < period:
        return None, None
    
    recent = prices[-period:]
    support = min(recent)
    resistance = max(recent)
    
    return round(support, 4), round(resistance, 4)

def calc_return(arr, n):
    """计算近N日收益"""
    if not arr or len(arr) < n:
        return None
    val = 1.0
    for x in arr[-n:]:
        r = x.get('equityReturn') or 0
        val *= (1 + r / 100)
    return (val - 1) * 100

def calc_position_label(nav, high_20d, low_20d):
    """计算位置标签"""
    if not all([nav, high_20d, low_20d]) or high_20d == low_20d:
        return None
    pct = (nav - low_20d) / (high_20d - low_20d) * 100
    if pct > 80:
        return '高位'
    elif pct < 20:
        return '低位'
    else:
        return '中位'

def calc_consecutive(arr, key='equityReturn'):
    """计算连涨/连跌天数"""
    if not arr or len(arr) < 2:
        return 0, 0
    
    up = down = 0
    for x in reversed(arr):
        r = x.get(key) or 0
        if r > 0:
            if down > 0:
                break
            up += 1
        elif r < 0:
            if up > 0:
                break
            down += 1
        else:
            break
    return up, down

# ── 主流程 ──
today = datetime.date.today()
today_str = today.strftime('%Y-%m-%d')
print(f"[Pipeline V2] {today_str} 开始运行")
print("=" * 60)

out = []
db_rows_nav = []
db_rows_market = []
alerts = []  # 预警信息

# ── 1. 拉指数数据（新浪） ──
print("\n[1/6] 拉取市场指数...")
index_data = {}
try:
    codes_str = ','.join(MARKET_INDICES.values())
    raw = http(f"https://hq.sinajs.cn/list={codes_str}",
               {"Referer": "https://finance.sina.com.cn"}).decode('gbk', 'ignore')
    for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', raw):
        code, data = m.group(1), m.group(2)
        f = data.split(',')
        if len(f) < 6 or not f[0]:
            continue
        try:
            open_p = float(f[1]); prev_close = float(f[2]); current = float(f[3])
            high = float(f[4]); low = float(f[5])
            pct = (current / prev_close - 1) * 100 if prev_close else 0
            name = [k for k, v in MARKET_INDICES.items() if v == code]
            name = name[0] if name else code
            
            # 用指数数据判断形态
            pattern = detect_etf_pattern(open_p, high, low, current, prev_close)
            
            index_data[name] = {
                'code': code, 'name': name, 'close': current, 'open': open_p,
                'high': high, 'low': low, 'prev_close': prev_close, 
                'return': pct, 'pattern': pattern
            }
            db_rows_market.append({
                'trade_date': today, 'index_name': name, 'index_code': code,
                'close_price': current, 'daily_return': round(pct, 4),
                'open_price': open_p, 'high': high, 'low': low, 
                'prev_close': prev_close, 'price_pattern': pattern
            })
            print(f"  {name}: {current:.2f} ({pct:+.2f}%) {pattern}")
        except:
            pass
except Exception as e:
    print(f"  指数获取失败: {e}")

# ── 2. 拉ETF行情（腾讯API，新浪已封） ──
print("\n[2/6] 拉取ETF行情...")
etf_data = {}
etf_codes = list(set([v['etf'] for v in FUND_ETF_MAP.values()]))
# 转换为腾讯格式
etf_tencent_codes = []
for code in etf_codes:
    if code.startswith('5'):
        etf_tencent_codes.append(f'sh{code}')
    else:
        etf_tencent_codes.append(f'sz{code}')

try:
    codes_str = ','.join(etf_tencent_codes)
    raw = http(f"https://qt.gtimg.cn/q={codes_str}").decode('gbk', 'ignore')
    for m in re.finditer(r'v_(\w+)="([^"]*)"', raw):
        code, data = m.group(1), m.group(2)
        f = data.split('~')
        if len(f) < 10 or not f[3]:
            continue
        try:
            current = float(f[3]); prev_close = float(f[4]); open_p = float(f[5])
            high = float(f[33]) if f[33] else current
            low = float(f[34]) if f[34] else current
            pct = (current / prev_close - 1) * 100 if prev_close else 0
            
            # 去掉sh/sz前缀
            pure_code = code[2:]
            etf_data[pure_code] = {
                'open': open_p, 'high': high, 'low': low, 
                'close': current, 'prev_close': prev_close, 'return': pct
            }
            print(f"  {pure_code}: {current:.3f} ({pct:+.2f}%)")
        except:
            pass
except Exception as e:
    print(f"  ETF行情获取失败: {e}")

# ── 3. 拉基金净值+计算所有指标 ──
print("\n[3/6] 拉取基金净值并计算技术指标...")
fund_data = {}

for c in CODES:
    try:
        txt = http(f"https://fund.eastmoney.com/pingzhongdata/{c}.js").decode('utf-8', 'ignore')
        nm = re.search(r'fS_name\s*=\s*"([^"]+)"', txt)
        name = nm.group(1) if nm else c
        raw = grab('Data_netWorthTrend', txt)
        if not raw:
            continue
        arr = json.loads(raw)
        if len(arr) < 5:
            continue
        
        # 提取历史净值
        navs = [x.get('y', 0) for x in arr]
        returns = [x.get('equityReturn', 0) for x in arr]
        latest = arr[-1]
        nav = latest.get('y', 0)
        daily_ret = latest.get('equityReturn', 0)
        trade_date = datetime.datetime.fromtimestamp(latest['x'] / 1000).date()
        
        # 计算技术指标
        ma5 = calc_ma(navs, 5)
        ma10 = calc_ma(navs, 10)
        ma20 = calc_ma(navs, 20)
        ma60 = calc_ma(navs, 60)
        
        rsi_6 = calc_rsi(navs, 6)
        rsi_12 = calc_rsi(navs, 12)
        
        macd_line, signal_line, histogram = calc_macd(navs)
        
        # 趋势判断
        trend = calc_trend(navs)
        
        # 支撑压力位
        support, resistance = calc_support_resistance(navs)
        
        # 近N日收益
        ret_3d = calc_return(arr, 3)
        ret_5d = calc_return(arr, 5)
        ret_10d = calc_return(arr, 10)
        ret_20d = calc_return(arr, 20)
        
        # 近20日高低点
        recent_20 = navs[-20:] if len(navs) >= 20 else navs
        high_20d = max(recent_20)
        low_20d = min(recent_20)
        drawdown = (nav / high_20d - 1) * 100 if high_20d else 0
        
        # 连涨/连跌
        up, down = calc_consecutive(arr)
        
        # 位置标签
        position = calc_position_label(nav, high_20d, low_20d)
        
        # 场外基金简化形态
        simple_pattern = detect_simple_pattern(daily_ret)
        
        # ETF形态（如果有对应ETF）
        etf_pattern = None
        etf_info = None
        if c in FUND_ETF_MAP:
            etf_code = FUND_ETF_MAP[c]['etf']
            if etf_code in etf_data:
                etf_info = etf_data[etf_code]
                etf_pattern = detect_etf_pattern(
                    etf_info['open'], etf_info['high'], 
                    etf_info['low'], etf_info['close'], 
                    etf_info['prev_close']
                )
        
        # 优先使用ETF形态，否则用简化形态
        final_pattern = etf_pattern if etf_pattern else simple_pattern
        
        fund_data[c] = {
            'name': name, 'nav': nav, 'daily_return': daily_ret, 
            'trade_date': trade_date,
            'return_3d': ret_3d, 'return_5d': ret_5d, 
            'return_10d': ret_10d, 'return_20d': ret_20d,
            'high_20d': high_20d, 'low_20d': low_20d, 
            'drawdown': drawdown,
            'consecutive_up': up, 'consecutive_down': down, 
            'position': position,
            'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
            'rsi_6': rsi_6, 'rsi_12': rsi_12,
            'macd_line': macd_line, 'signal_line': signal_line, 
            'macd_histogram': histogram,
            'trend': trend, 'support': support, 'resistance': resistance,
            'etf_code': FUND_ETF_MAP.get(c, {}).get('etf'),
            'etf_open': etf_info['open'] if etf_info else None,
            'etf_high': etf_info['high'] if etf_info else None,
            'etf_low': etf_info['low'] if etf_info else None,
            'etf_close': etf_info['close'] if etf_info else None,
            'etf_pattern': etf_pattern,
            'price_pattern': final_pattern,
        }
        
        # 判断是否为今天数据
        today = datetime.date.today()
        is_today = (trade_date == today)

        # 如果不是今天数据，不写入nav_daily（等22:30真实净值）
        data_source = 'fund_nav'
        if not is_today:
            # 跳过，不写入今日nav_daily
            print(f"  ⏭️ {c} 无今日净值（{trade_date}），跳过写入，等22:30真实净值")
            continue

        # 构建数据库记录
        db_rows_nav.append({
            'fund_code': c, 'trade_date': trade_date, 'nav': nav,
            'daily_return': round(daily_ret, 4),
            'return_3d': round(ret_3d, 4) if ret_3d else None,
            'return_5d': round(ret_5d, 4) if ret_5d else None,
            'return_10d': round(ret_10d, 4) if ret_10d else None,
            'return_20d': round(ret_20d, 4) if ret_20d else None,
            'high_20d': high_20d, 'low_20d': low_20d,
            'drawdown_from_high': round(drawdown, 4),
            'consecutive_up': up, 'consecutive_down': down,
            'price_pattern': final_pattern, 'position_label': position,
            'etf_code': FUND_ETF_MAP.get(c, {}).get('etf'),
            'etf_open': etf_info['open'] if etf_info else None,
            'etf_high': etf_info['high'] if etf_info else None,
            'etf_low': etf_info['low'] if etf_info else None,
            'etf_close': etf_info['close'] if etf_info else None,
            'etf_pattern': etf_pattern,
            'ma5': round(ma5, 4) if ma5 else None,
            'ma10': round(ma10, 4) if ma10 else None,
            'ma20': round(ma20, 4) if ma20 else None,
            'ma60': round(ma60, 4) if ma60 else None,
            'rsi_6': round(rsi_6, 4) if rsi_6 else None,
            'rsi_12': round(rsi_12, 4) if rsi_12 else None,
            'macd_line': round(macd_line, 4) if macd_line else None,
            'signal_line': round(signal_line, 4) if signal_line else None,
            'macd_histogram': round(histogram, 4) if histogram else None,
            'trend': trend,
            'support': support,
            'resistance': resistance,
            'data_source': data_source,
        })
        
        # 打印摘要
        pattern_display = final_pattern or '-'
        trend_display = trend or '-'
        rsi_display = f"{rsi_6:.1f}" if rsi_6 else '-'
        print(f"  {c} {name[:8]}: {nav:.4f} ({daily_ret:+.2f}%) {pattern_display} {trend_display} RSI={rsi_display}")
        
    except Exception as e:
        print(f"  {c} 失败: {e}")

# ── 4. 拉板块涨幅（东财push2概念板块，按主力净流入排序） ──
print("\n[4/6] 拉取行业板块...")
sector_data = []
for attempt in range(3):
    try:
        raw = http("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk?page=1&num=30&sort=netamount&asc=0&fenlei=1",
                   {"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"}).decode('utf-8', 'ignore')
        items = json.loads(raw)
        if isinstance(items, list):
            for item in items:
                name = item.get("name", "")
                netflow = float(item.get("netamount", 0)) / 1e8 if item.get("netamount") else 0
                if name:
                    sector_data.append({'name': name, 'return': round(netflow, 2)})
        break
    except Exception:
        if attempt < 2:
            time.sleep(2)
        else:
            print(f"  板块榜失败: 重试3次后仍限流")

# ── 5. 写入MySQL ──
print("\n[5/6] 写入MySQL...")
conn = None
try:
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # 写入nav_daily（包含所有新字段）
    sql_nav = """INSERT INTO nav_daily 
        (fund_code, trade_date, nav, daily_return, return_3d, return_5d, return_10d, return_20d,
         high_20d, low_20d, drawdown_from_high, consecutive_up, consecutive_down, 
         price_pattern, position_label,
         etf_code, etf_open, etf_high, etf_low, etf_close, etf_pattern,
         ma5, ma10, ma20, ma60, rsi_6, rsi_12,
         macd_line, signal_line, macd_histogram, trend, support, resistance, data_source)
        VALUES (%(fund_code)s, %(trade_date)s, %(nav)s, %(daily_return)s, %(return_3d)s, %(return_5d)s,
                %(return_10d)s, %(return_20d)s, %(high_20d)s, %(low_20d)s, %(drawdown_from_high)s,
                %(consecutive_up)s, %(consecutive_down)s, %(price_pattern)s, %(position_label)s,
                %(etf_code)s, %(etf_open)s, %(etf_high)s, %(etf_low)s, %(etf_close)s, %(etf_pattern)s,
                %(ma5)s, %(ma10)s, %(ma20)s, %(ma60)s, %(rsi_6)s, %(rsi_12)s,
                %(macd_line)s, %(signal_line)s, %(macd_histogram)s, %(trend)s, %(support)s, %(resistance)s, %(data_source)s)
        ON DUPLICATE KEY UPDATE
            nav=VALUES(nav), daily_return=VALUES(daily_return),
            return_3d=VALUES(return_3d), return_5d=VALUES(return_5d),
            return_10d=VALUES(return_10d), return_20d=VALUES(return_20d),
            high_20d=VALUES(high_20d), low_20d=VALUES(low_20d),
            drawdown_from_high=VALUES(drawdown_from_high), consecutive_up=VALUES(consecutive_up), consecutive_down=VALUES(consecutive_down),
            price_pattern=VALUES(price_pattern), position_label=VALUES(position_label),
            etf_code=VALUES(etf_code), etf_open=VALUES(etf_open), etf_high=VALUES(etf_high),
            etf_low=VALUES(etf_low), etf_close=VALUES(etf_close), etf_pattern=VALUES(etf_pattern),
            ma5=VALUES(ma5), ma10=VALUES(ma10), ma20=VALUES(ma20), ma60=VALUES(ma60),
            rsi_6=VALUES(rsi_6), rsi_12=VALUES(rsi_12),
            macd_line=VALUES(macd_line), signal_line=VALUES(signal_line), 
            macd_line=VALUES(macd_line), signal_line=VALUES(signal_line), 
            macd_histogram=VALUES(macd_histogram), trend=VALUES(trend),
            support=VALUES(support), resistance=VALUES(resistance),
            data_source=VALUES(data_source)"""
    
    cursor.executemany(sql_nav, db_rows_nav)
    print(f"  nav_daily: 写入{cursor.rowcount}条")
    
    # 写入market_daily
    sql_market = """INSERT INTO market_daily
        (trade_date, index_name, index_code, close_price, daily_return, 
         open_price, high, low, prev_close, price_pattern)
        VALUES (%(trade_date)s, %(index_name)s, %(index_code)s, %(close_price)s, %(daily_return)s,
                %(open_price)s, %(high)s, %(low)s, %(prev_close)s, %(price_pattern)s)
        ON DUPLICATE KEY UPDATE
            close_price=VALUES(close_price), daily_return=VALUES(daily_return),
            open_price=VALUES(open_price), high=VALUES(high), low=VALUES(low),
            prev_close=VALUES(prev_close), price_pattern=VALUES(price_pattern)"""
    
    cursor.executemany(sql_market, db_rows_market)
    print(f"  market_daily: 写入{cursor.rowcount}条")
    
    # 写入sector_return_daily（板块涨幅）
    if sector_data:
        sql_sector = """INSERT INTO sector_return_daily 
            (trade_date, sector_name, daily_return, rank_int)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                daily_return=VALUES(daily_return), rank_int=VALUES(rank_int)"""
        
        for i, s in enumerate(sector_data):
            cursor.execute(sql_sector, (today, s['name'], s['return'], i+1))
        print(f"  sector_return_daily: 写入{len(sector_data)}条")
    
    conn.commit()
    print("  MySQL写入完成 ✅")
except Exception as e:
    print(f"  MySQL写入失败: {e}")
    if conn:
        conn.rollback()
finally:
    if conn:
        conn.close()

# ── 6. 生成预警和复盘 ──
print("\n[6/6] 生成预警和复盘...")

# 止损止盈预警
for code, pos in POSITIONS.items():
    if code in fund_data:
        fd = fund_data[code]
        buy_nav = pos.get('buy_nav', 0)
        stop_loss = pos.get('stop_loss', -8) or -8  # 默认-8%
        take_profit = pos.get('take_profit', 10) or 10  # 默认10%
        if buy_nav and buy_nav > 0:
            buy_nav = float(buy_nav)  # 转换为float
            current_return = (fd['nav'] / buy_nav - 1) * 100
            
            if current_return <= stop_loss:
                alerts.append(f"🔴 止损预警：{fd['name']}({code}) 亏损{current_return:.1f}%，接近止损线{stop_loss}%")
            elif current_return >= take_profit:
                alerts.append(f"🟢 止盈预警：{fd['name']}({code}) 盈利{current_return:.1f}%，达到止盈线{take_profit}%")

# 关键位置预警
for code, fd in fund_data.items():
    if fd.get('rsi_6'):
        if fd['rsi_6'] > 70:
            alerts.append(f"⚠️ 超买预警：{fd['name']}({code}) RSI={fd['rsi_6']:.1f} > 70")
        elif fd['rsi_6'] < 30:
            alerts.append(f"💡 超卖预警：{fd['name']}({code}) RSI={fd['rsi_6']:.1f} < 30")
    
    if fd.get('trend') == '上升' and fd.get('price_pattern') == '冲高回落':
        alerts.append(f"⚠️ 见顶预警：{fd['name']}({code}) 上升趋势+冲高回落")
    
    if fd.get('trend') == '下降' and fd.get('price_pattern') in ['探底回升', '大涨']:
        alerts.append(f"💡 见底预警：{fd['name']}({code}) 下降趋势+探底回升")

# ── 生成Market Snapshot ──
print("\n生成Market Snapshot...")
snapshot_lines = [f"# Market Snapshot {today_str}\n"]

# 大盘概况
snapshot_lines.append("## 大盘概况\n")
for name in ['上证指数', '创业板', '科创50', '沪深300', '中证1000']:
    if name in index_data:
        d = index_data[name]
        snapshot_lines.append(f"- {name}: {d['close']:.2f} ({d['return']:+.2f}%) {d.get('pattern','')}")

# 行业板块TOP10
snapshot_lines.append("\n## 行业板块TOP10\n")
for s in sector_data[:10]:
    snapshot_lines.append(f"- {s['name']}: {s['return']:+.2f}%")

# 关注基金（完整版）
snapshot_lines.append("\n## 关注基金\n")
snapshot_lines.append("| 代码 | 名称 | 净值 | 今日 | 5日 | 位置 | 形态 | 趋势 | RSI6 | 支撑 | 压力 |")
snapshot_lines.append("|:--|:--|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|")

for c in CODES:
    if c in fund_data:
        fd = fund_data[c]
        r5 = f"{fd['return_5d']:+.1f}%" if fd['return_5d'] is not None else "-"
        rsi = f"{fd['rsi_6']:.0f}" if fd['rsi_6'] else "-"
        support = f"{fd['support']:.3f}" if fd['support'] else "-"
        resistance = f"{fd['resistance']:.3f}" if fd['resistance'] else "-"
        snapshot_lines.append(
            f"| {c} | {fd['name'][:8]} | {fd['nav']:.4f} | {fd['daily_return']:+.2f}% | {r5} | "
            f"{fd['position'] or '-'} | {fd['price_pattern'] or '-'} | {fd['trend'] or '-'} | {rsi} | {support} | {resistance} |"
        )

# 预警信息
if alerts:
    snapshot_lines.append("\n## ⚠️ 预警信息\n")
    for alert in alerts:
        snapshot_lines.append(f"- {alert}")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)
snapshot_path = os.path.join(SNAPSHOT_DIR, f'market_snapshot_{today.strftime("%Y%m%d")}.md')
with open(snapshot_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(snapshot_lines))
print(f"  Snapshot已生成: {snapshot_path}")

# ── 打印汇总 ──
print(f"\n{'=' * 60}")
print(f"Pipeline V2完成: {today_str}")
print(f"  基金: {len(db_rows_nav)}条 | 市场: {len(db_rows_market)}条 | 板块: {len(sector_data)}个")
print(f"  预警: {len(alerts)}条")
print(f"{'=' * 60}")

# 输出预警信息
if alerts:
    print("\n⚠️ 预警汇总:")
    for alert in alerts:
        print(f"  {alert}")

# ── 7. 板块轮动分析 ──
print("\n[7/7] 板块轮动分析...")
if sector_data:
    # 分类板块
    strong_up = [s for s in sector_data if s['return'] > 2][:5]
    strong_down = [s for s in sector_data if s['return'] < -2][:5]
    focus_industries = ['半导体', '芯片', 'CPO', 'AI', '机器人', '创新药', '稀土', '有色金属', '黄金', '电池']
    focus_sectors = [s for s in sector_data if any(fi in s['name'] for fi in focus_industries)]
    
    # 添加到Snapshot
    snapshot_lines.append("\n## 🔄 板块轮动分析\n")
    snapshot_lines.append("### 领涨板块TOP5\n")
    for s in strong_up:
        snapshot_lines.append(f"- 🔥 {s['name']}: {s['return']:+.2f}%")
    
    snapshot_lines.append("\n### 领跌板块TOP5\n")
    for s in strong_down:
        snapshot_lines.append(f"- 📉 {s['name']}: {s['return']:+.2f}%")
    
    snapshot_lines.append("\n### 关注板块表现\n")
    for s in focus_sectors:
        status = "🟢" if s['return'] > 0 else "🔴"
        snapshot_lines.append(f"- {status} {s['name']}: {s['return']:+.2f}%")
    
    print(f"  领涨: {', '.join([s['name'] for s in strong_up[:3]])}")
    print(f"  领跌: {', '.join([s['name'] for s in strong_down[:3]])}")

# ── 8. 信号胜率统计 ──
print("\n[8/8] 信号胜率统计...")
try:
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    # 统计信号表现
    cursor.execute("""
        SELECT source, 
               COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM signals
        GROUP BY source
    """)
    signal_stats = cursor.fetchall()
    
    # 统计交易表现
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN direction = '买入' THEN 1 ELSE 0 END) as buys,
            SUM(CASE WHEN direction = '卖出' THEN 1 ELSE 0 END) as sells
        FROM trades
    """)
    trade_stats = cursor.fetchone()
    
    conn.close()
    
    # 添加到Snapshot
    if signal_stats:
        snapshot_lines.append("\n## 📊 信号胜率统计\n")
        snapshot_lines.append("| 信号源 | 总数 | 正确 | 胜率 |")
        snapshot_lines.append("|:--|:--:|:--:|:--:|")
        for s in signal_stats:
            win_rate = (s['correct'] / s['total'] * 100) if s['total'] > 0 else 0
            snapshot_lines.append(f"| {s['source']} | {s['total']} | {s['correct']} | {win_rate:.1f}% |")
        
        print(f"  信号源: {len(signal_stats)}个")
    
    if trade_stats:
        snapshot_lines.append(f"\n**交易统计:** 买入{trade_stats['buys']}笔 / 卖出{trade_stats['sells']}笔")
        print(f"  交易: 买入{trade_stats['buys']}笔 / 卖出{trade_stats['sells']}笔")
        
except Exception as e:
    print(f"  统计失败: {e}")

# 重新写入Snapshot（包含所有新内容）
with open(snapshot_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(snapshot_lines))
print(f"\n  Snapshot已更新: {snapshot_path}")

# ── 9. 资金流向入库 ──
print("\n[9/9] 资金流向入库...")
flow_count = 0
north_count = 0

def fetch_with_retry(url, max_retries=3, delay=2):
    """带重试的HTTP请求"""
    for attempt in range(max_retries):
        try:
            raw = http(url, {"Referer": "https://finance.sina.com.cn/"}).decode('utf-8', 'ignore')
            if raw and '__ERROR' not in raw:
                return json.loads(raw)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
    return None

# 1. 板块资金流向（新浪API，东财push2已封）
try:
    flow_url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk?page=1&num=50&sort=netamount&asc=0&fenlei=1"
    flow_raw = fetch_with_retry(flow_url)
    
    if flow_raw:
        items = flow_raw if isinstance(flow_raw, list) else []
        
        flow_conn = pymysql.connect(**DB_CONFIG)
        flow_cursor = flow_conn.cursor()
        
        for item in items:
            try:
                sector_name = item.get('name', '')
                netamount = float(item.get('netamount', 0)) / 1e8 if item.get('netamount') else 0
                if not sector_name:
                    continue
                # 新浪API提供主力净流入和散户净流入
                main_netflow = float(item.get('mainnetamount', 0)) / 1e8 if item.get('mainnetamount') else netamount
                retail_netflow = float(item.get('retailnetamount', 0)) / 1e8 if item.get('retailnetamount') else 0
                
                flow_sql = """INSERT INTO sector_flow_daily 
                    (trade_date, sector_name, main_inflow, main_outflow, main_netflow,
                     retail_inflow, retail_outflow, retail_netflow)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        main_inflow=VALUES(main_inflow), main_outflow=VALUES(main_outflow),
                        main_netflow=VALUES(main_netflow), retail_inflow=VALUES(retail_inflow),
                        retail_outflow=VALUES(retail_outflow), retail_netflow=VALUES(retail_netflow)"""
                
                # Sina API没有inamount/outflow，用netflow计算
                inamount = max(0, main_netflow)
                outamount = max(0, -main_netflow)
                flow_cursor.execute(flow_sql, (
                    today, sector_name,
                    round(inamount, 2), round(outamount, 2), round(main_netflow, 2),
                    round(max(0, retail_netflow), 2), round(max(0, -retail_netflow), 2), round(retail_netflow, 2)
                ))
                flow_count += 1
            except:
                continue
        
        # 2. 北向资金（东财数据中心API）
        try:
            north_url = 'https://datacenter-web.eastmoney.com/api/data/v1/get?sortColumns=TRADE_DATE&sortTypes=-1&pageSize=20&pageNumber=1&reportName=RPT_MUTUAL_DEAL_HISTORY&columns=TRADE_DATE,MUTUAL_TYPE,NET_DEAL_AMT&source=WEB&client=WEB'
            north_raw = http(north_url, {"Referer": "https://data.eastmoney.com/"}).decode('utf-8', 'ignore')
            north_d = json.loads(north_raw)
            north_result = north_d.get('result', {})
            
            if north_result and north_result.get('data'):
                # 找北向合计（MUTUAL_TYPE=006）
                for item in north_result['data']:
                    if item.get('MUTUAL_TYPE') == '006':
                        net_amt_raw = item.get('NET_DEAL_AMT')
                        if net_amt_raw is None:
                            # 尝试其他字段
                            net_amt_raw = item.get('NET_BUY_AMT') or item.get('BUY_AMT', 0)
                        net_amt = float(net_amt_raw) / 10000 if net_amt_raw else 0  # 万→亿
                        is_inflow = 1 if net_amt > 0 else 0
                        
                        north_sql = """INSERT INTO north_flow_daily 
                            (trade_date, total_netflow, is_inflow)
                            VALUES (%s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                total_netflow=VALUES(total_netflow), is_inflow=VALUES(is_inflow)"""
                        flow_cursor.execute(north_sql, (today, round(net_amt, 2), is_inflow))
                        north_count = 1
                        break
        except Exception as e:
            pass
        
        flow_conn.commit()
        flow_conn.close()
    
    print(f"  板块资金流向: {flow_count}条入库")
    print(f"  北向资金: {north_count}条入库")
    
except Exception as e:
    print(f"  资金流向入库失败: {e}")

# ── 10. 融资融券+ETF申赎入库 ──
print("\n[10/11] 融资融券+ETF申赎入库...")
margin_count = 0
etf_count = 0

try:
    mf_conn = pymysql.connect(**DB_CONFIG)
    mf_cursor = mf_conn.cursor()
    
    # 融资融券（用板块资金流向近似，东财push2）
    try:
        margin_url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=30&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:2+f:!50&fields=f12,f14,f62"
        margin_raw = http(margin_url, {"Referer": "https://data.eastmoney.com/", "User-Agent": "Mozilla/5.0"}).decode('utf-8', 'ignore')
        margin_parsed = json.loads(margin_raw)
        margin_items = margin_parsed.get("data", {}).get("diff", [])
        
        for item in margin_items[:20]:
            try:
                name = item.get('f14', '')[:10]
                netamount = float(item.get('f62', 0)) / 1e8 if item.get('f62') else 0
                if not name:
                    continue
                
                margin_sql = """INSERT INTO margin_trading_daily 
                    (trade_date, fund_code, margin_buy, margin_repay, margin_balance, total_balance)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        margin_buy=VALUES(margin_buy), margin_repay=VALUES(margin_repay),
                        margin_balance=VALUES(margin_balance), total_balance=VALUES(total_balance)"""
                
                mf_cursor.execute(margin_sql, (today, name, round(inamount, 2), round(outamount, 2), round(netamount, 2), round(abs(netamount), 2)))
                margin_count += 1
            except:
                continue
    except:
        pass
    
    # ETF申赎（用ETF行情近似）
    etf_codes = list(get_fund_etf_map().values())
    for etf_code in etf_codes:
        try:
            prefix = 'sh' if etf_code.startswith('5') else 'sz'
            etf_url = f"https://hq.sinajs.cn/list={prefix}{etf_code}"
            etf_raw = http(etf_url, {"Referer": "https://finance.sina.com.cn/"}).decode('gbk', 'ignore')
            
            parts = etf_raw.split('="')[1].rstrip('"').split(',')
            if len(parts) > 5:
                name = parts[0]
                current = float(parts[3]) if parts[3] else 0
                prev_close = float(parts[2]) if parts[2] else 0
                change_pct = ((current / prev_close - 1) * 100) if prev_close else 0
                
                etf_sql = """INSERT INTO etf_flow_daily 
                    (trade_date, etf_code, etf_name, shares_change_pct)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        etf_name=VALUES(etf_name), shares_change_pct=VALUES(shares_change_pct)"""
                
                mf_cursor.execute(etf_sql, (today, etf_code, name, round(change_pct, 4)))
                etf_count += 1
        except:
            continue
    
    mf_conn.commit()
    mf_conn.close()
    
    print(f"  融资融券: {margin_count}条入库")
    print(f"  ETF申赎: {etf_count}条入库")
    
except Exception as e:
    print(f"  融资融券/ETF申赎入库失败: {e}")

# ── 11. 信号共振计算 ──
print("\n[11/11] 信号共振计算...")
resonance_count = 0

# 基金→板块映射
FUND_SECTOR_MAP = get_fund_sectors()

try:
    res_conn = pymysql.connect(**DB_CONFIG)
    res_cursor = res_conn.cursor()
    
    for fund_code in fund_data.keys():
        fd = fund_data[fund_code]
        
        buy = 0
        sell = 0
        signals = {}
        
        # 1. RSI信号
        rsi = float(fd.get('rsi_6', 50) or 50)
        if rsi < 30:
            signals['rsi'] = '买入'
            buy += 1
        elif rsi > 70:
            signals['rsi'] = '卖出'
            sell += 1
        else:
            signals['rsi'] = '中性'
        
        # 2. MACD信号
        macd_line = float(fd.get('macd_line', 0) or 0)
        signal_line_val = float(fd.get('signal_line', 0) or 0)
        histogram = float(fd.get('macd_histogram', 0) or 0)
        
        if histogram > 0 and macd_line > signal_line_val:
            signals['macd'] = '买入'
            buy += 1
        elif histogram < 0 and macd_line < signal_line_val:
            signals['macd'] = '卖出'
            sell += 1
        else:
            signals['macd'] = '中性'
        
        # 3. 形态信号
        pattern = fd.get('price_pattern', '')
        if pattern in ['探底回升', '大涨']:
            signals['pattern'] = '买入'
            buy += 1
        elif pattern in ['冲高回落', '大跌']:
            signals['pattern'] = '卖出'
            sell += 1
        else:
            signals['pattern'] = '中性'
        
        # 4. 趋势信号
        trend = fd.get('trend', '')
        if trend == '上升':
            signals['trend'] = '买入'
            buy += 1
        elif trend == '下降':
            signals['trend'] = '卖出'
            sell += 1
        else:
            signals['trend'] = '中性'
        
        # 5. 位置信号
        position = fd.get('position', '')
        if position == '低位':
            signals['position'] = '买入'
            buy += 1
        elif position == '高位':
            signals['position'] = '卖出'
            sell += 1
        else:
            signals['position'] = '中性'
        
        # 6. 资金流向信号
        flow_signal = '中性'
        for sector in FUND_SECTOR_MAP.get(fund_code, []):
            try:
                flow_sql = "SELECT main_netflow FROM sector_flow_daily WHERE trade_date=%s AND sector_name LIKE %s LIMIT 1"
                res_cursor.execute(flow_sql, (today, f"%{sector}%"))
                flow_row = res_cursor.fetchone()
                if flow_row:
                    main_flow = float(flow_row[0] or 0)
                    if main_flow > 0:
                        flow_signal = '买入'
                        buy += 1
                    elif main_flow < 0:
                        flow_signal = '卖出'
                        sell += 1
                    break
            except:
                pass
        signals['flow'] = flow_signal
        
        # 最终信号
        if buy >= 4:
            final_signal = '🟢🟢 强烈买入'
        elif buy >= 3:
            final_signal = '🟢 买入'
        elif sell >= 4:
            final_signal = '🔴🔴 强烈卖出'
        elif sell >= 3:
            final_signal = '🔴 卖出'
        else:
            final_signal = '⚪ 观望'
        
        # 入库
        try:
            res_sql = """INSERT INTO signal_resonance 
                (trade_date, fund_code, rsi_signal, macd_signal, pattern_signal, 
                 flow_signal, total_buy, total_sell, final_signal)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    rsi_signal=VALUES(rsi_signal), macd_signal=VALUES(macd_signal),
                    pattern_signal=VALUES(pattern_signal), flow_signal=VALUES(flow_signal),
                    total_buy=VALUES(total_buy), total_sell=VALUES(total_sell),
                    final_signal=VALUES(final_signal)"""
            
            res_cursor.execute(res_sql, (
                today, fund_code,
                signals.get('rsi', '中性'), signals.get('macd', '中性'),
                signals.get('pattern', '中性'), signals.get('flow', '中性'),
                buy, sell, final_signal
            ))
            resonance_count += 1
        except:
            continue
    
    res_conn.commit()
    res_conn.close()
    
    print(f"  信号共振: {resonance_count}条入库")
    
except Exception as e:
    print(f"  信号共振计算失败: {e}")

# ── 最终汇总 ──
print(f"\n{'=' * 60}")
print(f"Pipeline V2完成: {today_str}")
print(f"  基金: {len(db_rows_nav)}条 | 市场: {len(db_rows_market)}条 | 板块: {len(sector_data)}个")
print(f"  资金流向: {flow_count if 'flow_count' in dir() else 0}条")
print(f"  信号共振: {resonance_count}条")
print(f"  预警: {len(alerts)}条")
print(f"{'=' * 60}")

# ── 拉取ETF实时价格（腾讯API）──
print("\n[额外] 拉取ETF实时价格...")
etf_prices = {}

# 从数据库动态获取基金→ETF映射
ETF_MAP = get_fund_etf_map()

for fund_code, etf_code in ETF_MAP.items():
    if etf_code:
        try:
            prefix = 'sh' if etf_code.startswith('5') else 'sz'
            raw = http(f"https://qt.gtimg.cn/q={prefix}{etf_code}").decode('gbk','ignore')
            m = re.search(r'v_\w+="([^"]*)"', raw)
            if m:
                parts = m.group(1).split('~')
                if len(parts) >= 10:
                    current = float(parts[3])
                    prev = float(parts[4])
                    change = (current/prev-1)*100 if prev else 0
                    etf_prices[fund_code] = {
                        'etf_code': etf_code,
                        'price': current,
                        'change': round(change, 2)
                    }
                    print(f"  {fund_code} ETF:{etf_code} 价格:{current} 涨跌:{change:.2f}%")
        except Exception as e:
            print(f"  {fund_code} 拉取失败: {e}")

# 保存ETF价格到文件（供15:50复盘使用）
import json
etf_price_file = os.path.expanduser('~/user_files/documents/etf_prices.json')
with open(etf_price_file, 'w') as f:
    json.dump(etf_prices, f, ensure_ascii=False)
print(f"  ETF价格已保存到: {etf_price_file}")

# ── 持仓收益计算 ──
print("\n[12/12] 持仓收益计算...")
try:
    # 从数据库动态获取持仓
    _holdings_for_calc = get_holdings()
    POSITIONS = {}
    for h in _holdings_for_calc:
        POSITIONS[h['fund_code']] = {
            'name': h['fund_name'],
            'buy_nav': h.get('nav_price', 0),
            'amount': h['total_amount'],
            'buy_date': h['buy_date'].strftime('%Y-%m-%d') if hasattr(h['buy_date'], 'strftime') else str(h['buy_date'])
        }
    
    # 连接数据库获取最新净值
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    total_invested = 0
    total_fee = 0
    total_current = 0
    position_details = []
    
    for fund_code, pos in POSITIONS.items():
        # 获取最新净值
        cursor.execute("SELECT nav FROM nav_daily WHERE fund_code=%s ORDER BY trade_date DESC LIMIT 1", (fund_code,))
        row = cursor.fetchone()
        
        buy_nav = pos.get('buy_nav')
        if row and buy_nav and buy_nav > 0:
            buy_nav = float(buy_nav)  # 转换为float
            current_nav = float(row[0])
            shares = pos['amount'] / buy_nav
            current_value = current_nav * shares
            profit = current_value - pos['amount']
            profit_rate = (current_nav / buy_nav - 1) * 100
            
            # 计算持有天数和手续费
            buy_date = datetime.datetime.strptime(pos['buy_date'], '%Y-%m-%d').date()
            hold_days = (today - buy_date).days
            
            # C类基金手续费规则：7天内1.5%，7天后0%
            fee_rate = 1.5 if hold_days <= 7 else 0
            fee_amount = current_value * fee_rate / 100
            net_value = current_value - fee_amount
            
            total_invested += pos['amount']
            total_current += current_value
            total_fee += fee_amount
            
            position_details.append({
                'code': fund_code,
                'name': pos['name'],
                'buy_date': pos['buy_date'],
                'hold_days': hold_days,
                'buy_nav': pos['buy_nav'],
                'current_nav': current_nav,
                'amount': pos['amount'],
                'current_value': round(current_value, 0),
                'profit': round(profit, 0),
                'profit_rate': round(profit_rate, 2),
                'fee_rate': fee_rate,
                'fee_amount': round(fee_amount, 2),
                'net_value': round(net_value, 0)
            })
            
            print(f"  {pos['name']}: 持有{hold_days}天 手续费{fee_rate}% ¥{fee_amount:.2f} 到手¥{net_value:.0f}")
    
    # 总收益
    total_profit = total_current - total_invested
    if total_invested > 0:
        total_profit_rate = (total_current / total_invested - 1) * 100
    else:
        total_profit_rate = 0
    
    print(f"\n  总投入: ¥{total_invested}")
    print(f"  当前市值: ¥{total_current:.0f}")
    print(f"  总手续费: ¥{total_fee:.2f}")
    print(f"  总到手金额: ¥{total_current - total_fee:.0f}")
    if total_invested > 0:
        print(f"  实际盈亏: ¥{total_profit - total_fee:+.0f} ({(total_current - total_fee - total_invested) / total_invested * 100:+.2f}%)")
    else:
        print(f"  实际盈亏: ¥{total_profit - total_fee:+.0f}")
    
    # 保存到文件
    profit_data = {
        'date': today_str,
        'total_invested': float(total_invested),
        'total_current': round(float(total_current), 0),
        'total_profit': round(float(total_profit), 0),
        'total_profit_rate': round(float(total_profit_rate), 2),
        'positions': position_details
    }
    
    profit_file = os.path.expanduser('~/user_files/documents/portfolio_profit.json')
    with open(profit_file, 'w') as f:
        json.dump(profit_data, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n  收益数据已保存到: {profit_file}")
    
    conn.close()
    
except Exception as e:
    print(f"  持仓收益计算失败: {e}")

# ── 13. 新闻采集入库（东财7x24快讯） ──
print(f"\n[13/13] 新闻采集入库...")
try:
    # 导入并运行event采集脚本
    import importlib.util
    spec = importlib.util.spec_from_file_location("fund_event_collect", 
        os.path.expanduser("~/.hermes/scripts/fund_event_collect.py"))
    event_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(event_module)
    
    event_count = event_module.collect_events()
    print(f"  新闻入库: {event_count}条")
except Exception as e:
    print(f"  新闻采集失败: {e}")
