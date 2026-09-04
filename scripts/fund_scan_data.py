#!/usr/bin/env python3
"""基金14:00方向扫描数据采集脚本：一次拉完所有数据，输出结构化摘要注入agent。
设计目标：总耗时 <60秒，任一数据源失败不影响其他。"""
import urllib.request, re, json, ssl, datetime
from datetime import date as _date
import os, sys

# 导入共享模块
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_holdings_for_scan, get_watchlist_codes, get_fund_sectors

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
UA = {'User-Agent':'Mozilla/5.0'}
out = []
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
out.append(f"[时间] {now}")

def http(url, headers=None, timeout=12):
    h = dict(UA); h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout, context=ctx).read()

# ---------- 1. 指数实时（新浪） ----------
try:
    raw = http("https://hq.sinajs.cn/list=sh000001,sz399006,sh000688,sh000852",
               {"Referer":"https://finance.sina.com.cn"}).decode('gbk','ignore')
    out.append("\n[指数实时]")
    for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', raw):
        f = m.group(2).split(',')
        if len(f) < 4 or not f[0]: continue
        try:
            pct = (float(f[3])/float(f[2])-1)*100
        except: pct = 0
        out.append(f"  {f[0]} {f[3]} ({pct:+.2f}%)")
except Exception as e:
    out.append(f"  [指数获取失败 {e}]")

# ---------- 2. 基金净值（天天基金，近8日+买入后累计） ----------
# 只获取持仓基金（不含观察列表），带买入日期用于T+1计算
holdings_scan = get_holdings_for_scan()

# 也读取今日卖出的基金（今天NAV still applies）
from fund_common import get_connection
import pymysql
_conn_sold = get_connection()
try:
    with _conn_sold.cursor(pymysql.cursors.DictCursor) as _cur:
        _cur.execute("""
            SELECT fund_code, fund_name, amount as total_amount, 
                   nav_price as buy_nav, trade_date as buy_date, 8 as days_held,
                   actual_sell_nav, actual_return
            FROM trades 
            WHERE trade_status = '已卖出' AND DATE(updated_at) >= DATE_SUB(CURDATE(), INTERVAL 1 DAY)
        """)
        for _s in _cur.fetchall():
            # 补充etf_code
            _etf = None
            _cur2 = _conn_sold.cursor()
            _cur2.execute("SELECT etf_code FROM funds WHERE code=%s", (_s['fund_code'],))
            _r = _cur2.fetchone()
            if _r: _etf = _r[0]
            _s['etf_code'] = _etf
            _s['is_sold_today'] = True
            _s['total_amount'] = float(_s['total_amount'])
            if _s.get('buy_nav'): _s['buy_nav'] = float(_s['buy_nav'])
            holdings_scan.append(_s)
finally:
    _conn_sold.close()

HOLDING_CODES = [h['fund_code'] for h in holdings_scan]
# 观察列表单独标注
watchlist_codes = get_watchlist_codes()

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

# ---------- ETF实时数据（提前拉取，供持仓计算使用） ----------
holdings_etf_map_pre = {h['fund_code']: h['etf_code'] for h in holdings_scan if h.get('etf_code')}
etf_estimates = {}
if holdings_etf_map_pre:
    etf_codes_pre = ",".join(f"sh{v}" if v.startswith("5") else f"sz{v}" for v in holdings_etf_map_pre.values())
    try:
        raw = http(f"https://hq.sinajs.cn/list={etf_codes_pre}",
                   {"Referer":"https://finance.sina.com.cn"}).decode("gbk","ignore")
        for m in re.finditer(r'var hq_str_(\w+)="([^"]*)', raw):
            code_full = m.group(1)
            code_num = code_full[2:]
            f = m.group(2).split(",")
            if len(f) < 4 or not f[0]: continue
            try:
                prev = float(f[2])
                curr = float(f[3])
                pct = (curr/prev - 1) * 100 if prev else 0
                # 找到对应的基金代码
                for fc, ec in holdings_etf_map_pre.items():
                    if ec == code_num:
                        etf_estimates[fc] = pct
            except: pass
    except: pass

out.append("\n[持仓基金结构化数据]")
# 使用预拉取的ETF估算数据

for h in holdings_scan:
    c = h['fund_code']
    buy_amt = h['total_amount']
    buy_date = h['buy_date']
    is_sold = h.get('is_sold_today', False)
    sold_tag = "|已卖出" if is_sold else ""
    if hasattr(buy_date, 'strftime'):
        buy_date_str = buy_date.strftime('%Y-%m-%d')
    else:
        buy_date_str = str(buy_date)
    # 持有天数 = 日历天数，买入次日开始算
    today_d = _date.today()
    bd = datetime.datetime.strptime(buy_date_str, '%Y-%m-%d').date()
    days_held = (today_d - bd).days
    try:
        txt = http(f"https://fund.eastmoney.com/pingzhongdata/{c}.js").decode('utf-8','ignore')
        nm = re.search(r'fS_name\s*=\s*"([^"]+)"', txt)
        name = nm.group(1)[:12] if nm else c
        raw = grab('Data_netWorthTrend', txt)
        # 获取今日ETF估算（无ETF时用NAV计算今日实际涨跌）
        etf_pct = etf_estimates.get(c)
        if etf_pct is None:
            # 无ETF：从NAV数据算今日实际涨跌
            try:
                _arr_all = json.loads(raw)
                if len(_arr_all) >= 2:
                    _today_nav = _arr_all[-1].get('y', 0)
                    _yesterday_nav = _arr_all[-2].get('y', 0)
                    if _yesterday_nav > 0:
                        etf_pct = (_today_nav / _yesterday_nav - 1) * 100
            except:
                pass
        etf_est_str = f"{etf_pct:+.2f}%" if etf_pct is not None else "—"
        etf_est_amt = buy_amt * etf_pct / 100 if etf_pct is not None else 0

        if not raw:
            out.append(f"  {c}|{name}|{buy_amt:.0f}|{buy_date_str}|{days_held}|—|{etf_est_str}|T+1无净值{sold_tag}")
            continue
        arr = json.loads(raw)[-30:]
        buy_ts = datetime.datetime.strptime(buy_date_str, '%Y-%m-%d').timestamp() * 1000
        # 次日零点（买入次日才算第一天持有）
        next_day_ts = buy_ts + 86400 * 1000
        # 买入次日及之后的NAV = 真正持有期间的净值
        post_buy = [x for x in arr if x['x'] >= next_day_ts]
        if len(post_buy) == 0:
            # T+1：尚无买入后的净值，用ETF估算
            cur_cum_pct = etf_pct or 0
            pre_fee_val = buy_amt * (1 + cur_cum_pct / 100)
            fee_rate = 0.0 if days_held >= 7 else 0.015
            fee_label = f"0%(满7天)" if days_held >= 7 else f"1.5%({days_held}天)"
            fee_amt = pre_fee_val * fee_rate
            cur_val = pre_fee_val - fee_amt
            cur_cum_amt = cur_val - buy_amt
            out.append(f"  {c}|{name}|{buy_amt:.0f}|{buy_date_str}|{days_held}|—|{etf_est_str}|{cur_cum_pct:+.2f}%|{fee_label}|{fee_amt:.1f}|{cur_val:.1f}|{etf_est_amt:.1f}|{cur_cum_amt:.1f}{sold_tag}")
        else:
            # 有持仓净值：从买入后第一天开始累计
            cum = 1.0
            for x in post_buy[1:]:
                r = x.get('equityReturn') or 0
                cum *= (1 + r/100)
            cum_pct = (cum - 1) * 100
            # 当前累计 = 昨日累计 + 今日估算
            cur_cum_pct = cum_pct + (etf_pct or 0)
            pre_fee_val = buy_amt * (1 + cur_cum_pct / 100)
            fee_rate = 0.0 if days_held >= 7 else 0.015
            fee_label = f"0%(满7天)" if days_held >= 7 else f"1.5%({days_held}天)"
            fee_amt = pre_fee_val * fee_rate
            cur_val = pre_fee_val - fee_amt
            cur_cum_amt = cur_val - buy_amt
            out.append(f"  {c}|{name}|{buy_amt:.0f}|{buy_date_str}|{days_held}|{cum_pct:+.2f}%|{etf_est_str}|{cur_cum_pct:+.2f}%|{fee_label}|{fee_amt:.1f}|{cur_val:.1f}|{etf_est_amt:.1f}|{cur_cum_amt:.1f}{sold_tag}")
    except Exception as e:
        out.append(f"  {c}|{name}|{buy_amt:.0f}|{buy_date_str}|{days_held}|—|—|—|—|—|—|—|错误{sold_tag}")

# 观察列表净值（单独一行，标注为观察）

# 合计行数据（脚本预计算，agent直接展示）
total_buy = sum(h['total_amount'] for h in holdings_scan)
total_cur_val = sum(float(line.split('|')[10]) for line in out if line.startswith('  ') and '|错误' not in line and len(line.split('|')) >= 11)
total_etf_amt = sum(float(line.split('|')[11]) for line in out if line.startswith('  ') and '|错误' not in line and len(line.split('|')) >= 12)
total_cum_amt = sum(float(line.split('|')[12]) for line in out if line.startswith('  ') and '|错误' not in line and len(line.split('|')) >= 13)
total_fee = sum(float(line.split('|')[9]) for line in out if line.startswith('  ') and '|错误' not in line and len(line.split('|')) >= 10)
total_cum_pct = (total_cum_amt / total_buy * 100) if total_buy else 0
out.append(f"\n[合计] 买入总额:{total_buy:.0f}|当前总市值:{total_cur_val:.1f}|今日总盈亏:{total_etf_amt:.1f}|累计总盈亏:{total_cum_amt:.1f}/{total_cum_pct:+.2f}%|总手续费:{total_fee:.1f}")

if watchlist_codes:
    out.append("\n[观察列表净值(仅参考)]")
    for c in watchlist_codes:
        try:
            txt = http(f"https://fund.eastmoney.com/pingzhongdata/{c}.js").decode('utf-8','ignore')
            nm = re.search(r'fS_name\s*=\s*"([^"]+)"', txt)
            name = nm.group(1)[:12] if nm else c
            raw = grab('Data_netWorthTrend', txt)
            if not raw:
                out.append(f"  {c} {name}: 无净值")
                continue
            arr = json.loads(raw)[-3:]
            ds = [datetime.datetime.fromtimestamp(x['x']/1000).strftime('%m-%d') for x in arr]
            rs = [x.get('equityReturn') for x in arr]
            hist = " ".join(f"{d}:{r:+.1f}" for d, r in zip(ds, rs))
            out.append(f"  {c} {name} | {hist}")
        except Exception as e:
            out.append(f"  {c}: 失败 {e}")

# ---------- 3. 重仓股实时（新浪） ----------
STOCKS = "sh688256,sz300308,sz300502,sh688072,sh688012,sh688082,sz002008,sh688017,sz002472,sh601689,sz002050,sh688981,sh600111,sz300750"
try:
    raw = http(f"https://hq.sinajs.cn/list={STOCKS}",
               {"Referer":"https://finance.sina.com.cn"}).decode('gbk','ignore')
    out.append("\n[重仓股实时]")
    for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', raw):
        f = m.group(2).split(',')
        if len(f) < 4 or not f[0]: continue
        try: pct = (float(f[3])/float(f[2])-1)*100
        except: pct = 0
        out.append(f"  {f[0]} {f[3]} ({pct:+.2f}%)")
except Exception as e:
    out.append(f"  [重仓股失败 {e}]")

# ---------- 3.5 ETF实时+盘中估算 ----------
# 从持仓数据动态获取ETF映射（不再硬编码）
holdings_etf_map = {h['fund_code']: h['etf_code'] for h in holdings_scan if h.get('etf_code')}
# 反向映射：etf_code -> fund_code
etf_to_fund = {v: k for k, v in holdings_etf_map.items()}
# ETF代码列表
ETF_CODES = ",".join(f"sh{v}" if v.startswith("5") else f"sz{v}" for v in holdings_etf_map.values())
# ETF名称映射（从数据库或硬编码补充）
ETF_NAME_MAP = {"588200":"科创芯片", "562500":"机器人", "516150":"稀土", "159638":"数字经济", "512480":"半导体"}

try:
    if ETF_CODES:
        raw = http(f"https://hq.sinajs.cn/list={ETF_CODES}",
                   {"Referer":"https://finance.sina.com.cn"}).decode("gbk","ignore")
        out.append("\n[ETF实时+盘中估算(持仓基金)]")
        etf_changes = {}
        for m in re.finditer(r'var hq_str_(\w+)="([^"]*)', raw):
            code_full = m.group(1)
            code_num = code_full[2:]  # remove sh/sz prefix
            f = m.group(2).split(",")
            if len(f) < 4 or not f[0]: continue
            try:
                prev = float(f[2])  # yesterday close
                curr = float(f[3])  # current price
                pct = (curr/prev - 1) * 100 if prev else 0
                name = ETF_NAME_MAP.get(code_num, code_num)
                etf_changes[code_num] = pct
                out.append(f"  {name}ETF({code_num}): {curr:.3f} ({pct:+.2f}%)")
            except: pass
        # 盘中估算持仓基金涨跌（按ETF分组避免重复）
        out.append("\n[盘中估算(基于ETF实时)]")
        etf_fund_groups = {}
        for fund_code, etf_code in holdings_etf_map.items():
            if etf_code not in etf_fund_groups:
                etf_fund_groups[etf_code] = []
            etf_fund_groups[etf_code].append(fund_code)
        for etf_code, fund_list in etf_fund_groups.items():
            if etf_code in etf_changes:
                pct = etf_changes[etf_code]
                label = "↑" if pct > 0 else "↓" if pct < 0 else "→"
                etf_name = ETF_NAME_MAP.get(etf_code, etf_code)
                codes_str = "/".join(fund_list)
                out.append(f"  {codes_str} 估算今日{label} {pct:+.2f}% (参考{etf_name}ETF)")
            else:
                codes_str = "/".join(fund_list)
                out.append(f"  {codes_str} 无对应ETF实时数据")
    else:
        out.append("\n[ETF估算: 持仓基金无ETF映射]")
except Exception as e:
    out.append(f"\n[ETF实时失败 {e}]")

# ---------- 4. 外围（美股+期货） ----------
try:
    raw = http("https://hq.sinajs.cn/list=gb_dji,gb_ixic,gb_inx,gb_sox,hf_NQ",
               {"Referer":"https://finance.sina.com.cn"}).decode('gbk','ignore')
    out.append("\n[外围]")
    for m in re.finditer(r'var hq_str_(gb_\w+|hf_\w+)="([^"]*)"', raw):
        code, data = m.group(1), m.group(2)
        f = data.split(',')
        if not f[0]: continue
        if code.startswith('gb_'):
            # 新浪gb格式: 名称,当前价,涨跌%,时间,涨跌额,今开,...
            pct = f[2] if len(f) > 2 else '?'
            out.append(f"  {f[0]} 收{f[1]} 涨跌{pct}%")
        else:
            # hf_NQ: 现价,..,昨收,今开
            try: pct = (float(f[0])/float(f[7])-1)*100 if len(f)>7 and f[7] else 0
            except: pct = 0
            out.append(f"  纳指期货 {f[0]} ({pct:+.2f}%)")
except Exception as e:
    out.append(f"  [外围失败 {e}]")

# ---------- 5. 科创50 MA20（新浪日K） ----------
try:
    raw = http("https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_k=/CN_MarketDataService.getKLineData?symbol=sh000688&scale=240&ma=no&datalen=25",
               {"Referer":"https://finance.sina.com.cn"}).decode('utf-8','ignore')
    m = re.search(r'\((\[.*\])\)', raw)
    if m:
        kl = json.loads(m.group(1))
        closes = [float(d['close']) for d in kl]
        ma20 = sum(closes[-20:])/20
        out.append(f"\n[大势开关] 科创50 MA20={ma20:.1f}")
except Exception as e:
    out.append(f"\n[MA20失败 {e}]")

# ---------- 6. 消息面（东财7x24快讯标题） ----------
try:
    raw = http("https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_724&column=345&order=1&needInteractData=0&page_index=1&page_size=20&req_trace=1&fields=code,showTime,title")
    d = json.loads(raw.decode('utf-8','ignore'))
    items = d.get('data',{}).get('list',[])
    out.append("\n[东财7x24快讯 近20条]")
    for it in items[:20]:
        out.append(f"  {it.get('showTime','')[11:16]} {it.get('title','')}")
except Exception as e:
    out.append(f"\n[快讯失败 {e}]")

# ---------- 6.5 未来7天重大事件（从MySQL events表查询） ----------
try:
    import pymysql as _pymysql
    _conn_ev = _pymysql.connect(host='127.0.0.1', port=3306, user='fund_admin', password='<REDACTED>',
                                database='fund_research', charset='utf8mb4')
    _cur_ev = _conn_ev.cursor()
    _cur_ev.execute("""
        SELECT event_time, event_type, title, intensity, related_funds
        FROM events
        WHERE event_time BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 7 DAY)
          AND verified = 1
        ORDER BY event_time
    """)
    _ev_rows = _cur_ev.fetchall()
    _cur_ev.close()
    _conn_ev.close()

    if _ev_rows:
        out.append("\n[📅 未来7天重大事件]")
        for ev in _ev_rows:
            ev_date = ev[0].strftime('%m/%d') if ev[0] else '?'
            ev_type = ev[1] or ''
            ev_title = ev[2] or ''
            ev_intensity = ev[3] or 0
            ev_funds = ev[4] or ''
            stars = '⭐' * min(ev_intensity, 5)
            out.append(f"  {ev_date} [{ev_type}] {ev_title} {stars} → {ev_funds}")
    else:
        out.append("\n[📅 未来7天无重大事件记录]")
except Exception as e:
    out.append(f"\n[事件日历查询失败 {e}]")

# ---------- 7. 全市场板块涨幅榜TOP10（v1.3②强势跟踪名单数据源） ----------
try:
    ok = False
    for attempt in range(3):  # push2 盘中限流，重试3次（08-13实测偶发 Remote end closed）
        try:
            raw = http("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f2,f3,f14",
                       {"Referer":"https://quote.eastmoney.com/"}).decode('utf-8','ignore')
            d = json.loads(raw)
            out.append("\n[板块涨幅榜TOP10 (强势名单候选)]")
            for it in d.get('data',{}).get('diff',[])[:10]:
                out.append(f"  {it.get('f14','')}: {it.get('f3',0):+.2f}%")
            ok = True
            break
        except Exception:
            import time; time.sleep(1)
    if not ok:
        out.append("\n[板块榜失败 重试3次后仍限流]")
except Exception as e:
    out.append(f"\n[板块榜失败 {e}]")

# ---------- 8. 资金流向分析（实时，东财push2板块接口） ----------
try:
    import urllib.request as _urllib_req
    # 东财push2板块资金流向（概念板块，按主力净流入排序）
    _sector_url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:2+f:!50&fields=f12,f14,f62,f184"
    _req = _urllib_req.Request(_sector_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"})
    _raw = _urllib_req.urlopen(_req, timeout=10, context=ctx).read()
    _d = json.loads(_raw)
    _items = _d.get("data", {}).get("diff", [])

    sectors = []
    for item in _items:
        name = item.get("f14", "")
        netflow = item.get("f62", 0)  # 主力净流入（元）
        if netflow is not None and name:
            sectors.append({"name": name, "main_netflow": round(float(netflow) / 1e8, 2)})

    out.append("\n[💰 资金流向分析（东财板块口径）]")

    # 基金→行业板块映射
    all_sectors = get_fund_sectors()
    holding_codes_set = set(h['fund_code'] for h in holdings_scan)
    FUND_SECTOR_MAP = {k: v for k, v in all_sectors.items() if k in holding_codes_set}

    # 主力流入TOP5
    sorted_sectors = sorted(sectors, key=lambda x: x['main_netflow'], reverse=True)
    out.append("  【主力流入TOP5】")
    for s in sorted_sectors[:5]:
        if s['main_netflow'] > 0:
            out.append(f"    ✅ {s['name']}: +{s['main_netflow']:.1f}亿")

    # 主力流出TOP5
    outflow_sectors = [s for s in sorted_sectors if s['main_netflow'] < 0]
    if outflow_sectors:
        out.append("  【主力流出TOP5】")
        for s in outflow_sectors[:5]:
            out.append(f"    ⚠️ {s['name']}: {s['main_netflow']:.1f}亿")
    else:
        out.append("  【主力流出】无板块净流出")

    # 基金持仓资金信号
    out.append("  【你的持仓资金信号】")
    sector_map = {s['name']: s for s in sectors}

    for fund_code, sector_names in FUND_SECTOR_MAP.items():
        matched = None
        for s_name in sector_map.keys():
            for keyword in sector_names:
                if keyword in s_name or s_name in keyword:
                    matched = sector_map[s_name]
                    break
            if matched:
                break

        if matched:
            main = matched['main_netflow']
            if main > 1:
                signal = '🟢 主力大幅流入'
            elif main > 0:
                signal = '🟢 主力流入'
            elif main < -1:
                signal = '🔴 主力大幅流出'
            elif main < 0:
                signal = '⚠️ 主力流出'
            else:
                signal = '⚪ 平衡'
            out.append(f"    {fund_code} {sector_names[0]}: {signal} ({main:+.1f}亿)")
        else:
            out.append(f"    {fund_code} {sector_names[0]}: ⚪ 未匹配到板块")

except Exception as e:
    out.append(f"\n[资金流向分析失败 {e}]")

# ---------- 8.5 北向资金（东财数据中心） ----------
try:
    import pymysql
    conn = pymysql.connect(host='127.0.0.1', port=3306, user='fund_admin', password='<REDACTED>', database='fund_research', charset='utf8mb4')
    cursor = conn.cursor()
    
    cursor.execute("SELECT trade_date, total_netflow, is_inflow FROM north_flow_daily ORDER BY trade_date DESC LIMIT 1")
    row = cursor.fetchone()
    
    if row:
        out.append("\n[🏦 北向资金]")
        status = "流入" if row[2] else "流出"
        signal = "🟢 外资看多" if row[2] else "🔴 外资看空"
        out.append(f"  最新: {row[0]} 净{status} {abs(row[1]):.2f}亿 {signal}")
        
        # 查看最近3天趋势
        cursor.execute("SELECT trade_date, total_netflow, is_inflow FROM north_flow_daily ORDER BY trade_date DESC LIMIT 3")
        rows = cursor.fetchall()
        if len(rows) > 1:
            out.append("  近期趋势:")
            for r in rows:
                s = "流入" if r[2] else "流出"
                out.append(f"    {r[0]}: {r[1]:+.2f}亿 ({s})")
    
    conn.close()
except Exception as e:
    out.append(f"\n[北向资金获取失败]")


# ---------- 9. 信号共振分析 ----------
try:
    import pymysql
    
    DB_CONFIG = {
        'host': '127.0.0.1', 'port': 3306,
        'user': 'fund_admin', 'password': '<REDACTED>',
        'database': 'fund_research', 'charset': 'utf8mb4',
    }
    
    FUND_SECTOR = get_fund_sectors()
    
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    out.append("\n[🎯 信号共振分析]")
    out.append("| 基金 | RSI | 趋势 | 形态 | 位置 | 资金 | 信号 |")
    out.append("|:--|:--:|:--:|:--:|:--:|:--:|:--|")
    
    # 动态获取持仓基金列表
    from fund_common import get_holdings
    _holdings_for_scan = get_holdings()
    for h in _holdings_for_scan:
        fund_code = h['fund_code']
        fund_name = h['fund_name'][:6]
        cursor.execute("SELECT rsi_6, trend, price_pattern, position_label FROM nav_daily WHERE fund_code=%s ORDER BY trade_date DESC LIMIT 1", (fund_code,))
        row = cursor.fetchone()
        if not row: continue
        
        rsi, trend, pattern, position = float(row[0] or 50), row[1] or '', row[2] or '', row[3] or ''
        buy = sell = 0
        
        if rsi < 30: buy += 1
        elif rsi > 70: sell += 1
        if trend == '上升': buy += 1
        elif trend == '下降': sell += 1
        if pattern in ['探底回升','大涨']: buy += 1
        elif pattern in ['冲高回落','大跌']: sell += 1
        if position == '低位': buy += 1
        elif position == '高位': sell += 1
        
        # 资金流向
        flow_sig = '中性'
        for sector in FUND_SECTOR.get(fund_code, []):
            cursor.execute("SELECT main_netflow FROM sector_flow_daily WHERE trade_date=CURDATE() AND sector_name LIKE %s LIMIT 1", (f"%{sector}%",))
            fr = cursor.fetchone()
            if fr and fr[0]:
                mf = float(fr[0])
                if mf > 0: flow_sig = '买入'; buy += 1
                elif mf < 0: flow_sig = '卖出'; sell += 1
                break
        
        if buy >= 4: sig = '🟢🟢强烈买入'
        elif buy >= 3: sig = '🟢买入'
        elif sell >= 3: sig = '🔴卖出'
        else: sig = '⚪观望'
        
        out.append(f"| {fund_name} | {rsi:.0f} | {trend} | {pattern} | {position} | {flow_sig} | {buy}买/{sell}卖 {sig} |")
    
    conn.close()
except Exception as e:
    out.append(f"\n[信号共振失败 {e}]")

# ---------- 10. 融资融券情绪（板块资金流向近似） ----------
try:
    import pymysql
    conn = pymysql.connect(host='127.0.0.1', port=3306, user='fund_admin', password='<REDACTED>', database='fund_research', charset='utf8mb4')
    cursor = conn.cursor()
    
    cursor.execute("SELECT fund_code, margin_buy, margin_repay, margin_balance FROM margin_trading_daily WHERE trade_date=CURDATE() ORDER BY margin_balance DESC LIMIT 5")
    rows = cursor.fetchall()
    
    if rows:
        out.append("\n[📊 板块资金情绪 TOP5]（主力资金流向近似）")
        for r in rows:
            out.append(f"  {r[0]}: 流入{r[1]:.1f}亿 | 流出{r[2]:.1f}亿 | 净{r[3]:+.1f}亿")
    
    conn.close()
except Exception as e:
    out.append(f"\n[板块资金情绪获取失败]")

# ---------- 11. ETF资金动向（涨跌幅近似） ----------
try:
    conn = pymysql.connect(host='127.0.0.1', port=3306, user='fund_admin', password='<REDACTED>', database='fund_research', charset='utf8mb4')
    cursor = conn.cursor()
    
    cursor.execute("SELECT etf_code, etf_name, shares_change_pct FROM etf_flow_daily WHERE trade_date=CURDATE() ORDER BY shares_change_pct DESC")
    rows = cursor.fetchall()
    
    if rows:
        out.append("\n[📈 ETF资金动向]（涨跌幅近似申赎方向）")
        for r in rows:
            pct = float(r[2])
            if pct > 1:
                signal = "🟢 大幅流入"
            elif pct > 0:
                signal = "🟢 流入"
            elif pct < -1:
                signal = "🔴 大幅流出"
            elif pct < 0:
                signal = "🔴 流出"
            else:
                signal = "⚪ 平衡"
            out.append(f"  {r[1]}({r[0]}): {pct:+.2f}% {signal}")
    
    conn.close()
except Exception as e:
    out.append(f"\n[ETF资金动向获取失败]")
print("\n".join(out))

# ---------- 12. 尾盘确认专用数据（14:40调用）----------
import sys
if "--tail" in sys.argv:
    # 只输出尾盘确认需要的数据
    tail_out = []
    tail_out.append("[尾盘确认数据]")
    
    # 拉取实时指数
    try:
        raw = http("https://hq.sinajs.cn/list=sh000001,sz399006,sh000688",
                   {"Referer":"https://finance.sina.com.cn"}).decode('gbk','ignore')
        tail_out.append("【实时指数】")
        for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', raw):
            f = m.group(2).split(',')
            if len(f) >= 4 and f[0]:
                try:
                    pct = (float(f[3])/float(f[2])-1)*100
                    tail_out.append(f"  {f[0]}: {f[3]} ({pct:+.2f}%)")
                except: pass
    except: pass
    
    # 拉取重仓股实时
    try:
        raw = http("https://hq.sinajs.cn/list=sh688256,sz300308,sz300502,sh688072,sh688012",
                   {"Referer":"https://finance.sina.com.cn"}).decode('gbk','ignore')
        tail_out.append("【重仓股实时】")
        for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', raw):
            f = m.group(2).split(',')
            if len(f) >= 4 and f[0]:
                try:
                    pct = (float(f[3])/float(f[2])-1)*100
                    tail_out.append(f"  {f[0]}: {f[3]} ({pct:+.2f}%)")
                except: pass
    except: pass
    
    print("\n".join(tail_out))
    sys.exit(0)

# ---------- 自动检测是否为尾盘模式 ----------
import datetime
current_hour = datetime.datetime.now().hour
if current_hour >= 14 and "14:40" not in " ".join(sys.argv):
    # 14:40后自动进入尾盘模式
    sys.argv.append("--tail")

