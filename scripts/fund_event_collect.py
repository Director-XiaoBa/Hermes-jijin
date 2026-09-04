#!/home/ubuntu/.hermes/venv-fund/bin/python3
"""Event自动采集：抓东财7x24快讯 → 筛选与持仓相关 → 写入events表。
优化版：只保留与持仓/观察池/行业相关的新闻，每天10-15条。
"""
import pymysql, datetime, json, urllib.request, re, ssl, time
import os, sys

# 导入共享模块
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_holdings, get_watchlist, get_fund_sectors

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

# ========== 分层配置 ==========

# ① 持仓基金（从数据库动态获取）
_holdings_raw = get_holdings()
HELD_FUNDS = {}
for h in _holdings_raw:
    code = h['fund_code']
    sectors = get_fund_sectors().get(code, [])
    HELD_FUNDS[code] = sectors if sectors else ['未知行业']

# ② 观察池基金（从数据库动态获取）
_watchlist_raw = get_watchlist()
WATCHLIST_FUNDS = {}
for w in _watchlist_raw:
    code = w['code']
    sectors = get_fund_sectors().get(code, [])
    WATCHLIST_FUNDS[code] = sectors if sectors else ['未知行业']

# ③ 关注行业（从持仓+观察池动态生成）
_all_sectors = set()
for sectors in HELD_FUNDS.values():
    _all_sectors.update(sectors)
for sectors in WATCHLIST_FUNDS.values():
    _all_sectors.update(sectors)
FOCUS_INDUSTRIES = list(_all_sectors) + ['黄金']  # 加上黄金

# ④ 市场大事关键词（无论行业都入库）
MARKET_MUST_KEYWORDS = [
    '美联储', '降息', '加息', '缩表', '关税', '贸易战', '制裁',
    '黑天鹅', '暴跌', '暴涨', '熔断', '战争', '冲突',
    '国务院', '发改委', '证监会', '央行',
]

# ========== 关键词映射 ==========

INDUSTRY_KEYWORDS = {
    '半导体': ['半导体', '芯片', '晶圆', '光刻', 'ASML', '中芯', '北方华创', '中微公司', '拓荆', '华海清科', '集成电路', '封装', '存储', 'HBM'],
    'AI': ['人工智能', 'AI', '大模型', '算力', 'GPU', '英伟达', 'NVIDIA', 'DeepSeek', 'ChatGPT', 'Transformer', '智能体', 'AIGC', '算力'],
    'CPO': ['CPO', '光模块', '光通信', '中际旭创', '新易盛', '天孚通信', 'Coherent', 'Lumentum'],
    '机器人': ['机器人', '人形机器人', '宇树', '优必选', '特斯拉机器人', 'Optimus', '具身智能'],
    '创新药': ['创新药', 'CRO', '医药', 'FDA', '临床试验', '恒瑞', '药明康德', '生物制品'],
    '稀土': ['稀土', '出口管制', '战略矿产', '镓', '锗', '商务部管制'],
    '有色金属': ['有色金属', '铜', '铝', '锂', '钴', '镍', '大宗商品', '矿产', '矿业'],
    '黄金': ['黄金', '金价', '避险', '央行购金', '降息'],
    '电池': ['电池', '锂电', '储能', '宁德时代', '比亚迪电池', '锂矿'],
    '电网': ['电网', '特高压', '电力', '十五五', '新能源', '光伏', '风电'],
    '数字经济': ['数字经济', '软件', '信息技术', '云计算', '大数据'],
}

EVENT_TYPE_KEYWORDS = {
    '政策': ['政策', '规划', '补贴', '关税', '管制', '发改委', '工信部', '国务院', '印发', '发布'],
    '财报': ['财报', '业绩', '营收', '利润', '季报', '年报', '中报', '净利'],
    '产业': ['订单', '产能', '出货', '量产', '投产', '签约', '扩产'],
    '地缘': ['战争', '冲突', '制裁', '关税', '贸易战', '地缘', '伊朗', '中东'],
    '突发': ['暴跌', '暴涨', '熔断', '黑天鹅', '突发', '紧急'],
}

# ========== 核心函数 ==========

def classify_event(title):
    """根据标题自动分类事件"""
    # 匹配行业
    industry = None
    max_hits = 0
    for ind, keywords in INDUSTRY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in title)
        if hits > max_hits:
            max_hits = hits
            industry = ind
    
    # 匹配事件类型
    event_type = '其他'
    for etype, keywords in EVENT_TYPE_KEYWORDS.items():
        if any(kw in title for kw in keywords):
            event_type = etype
            break
    
    # 判断方向
    direction = '中性'
    bearish_context = ['加息', '收紧', '缩表', '上调利率', '超预期加息']
    if any(kw in title for kw in bearish_context):
        direction = '利空'
    else:
        bullish_kw = ['利好', '上涨', '突破', '创新高', '超预期增长', '大涨', '涨停', '爆发', '领涨']
        bearish_kw = ['利空', '下跌', '暴跌', '跌停', '不及预期', '下滑', '风险', '预警', '蒸发']
        if any(kw in title for kw in bullish_kw):
            direction = '利好'
        elif any(kw in title for kw in bearish_kw):
            direction = '利空'
    
    # 判断强度（1-5）
    intensity = 2
    if event_type in ['政策', '突发']:
        intensity = 4
    elif event_type in ['财报', '产业']:
        intensity = 3
    if max_hits >= 3:
        intensity = min(5, intensity + 1)
    
    # 判断持续性
    duration = '短期'
    if event_type == '政策':
        duration = '中期'
    elif event_type == '产业':
        duration = '中期'
    elif event_type == '突发':
        duration = '短期'
    
    return {
        'event_type': event_type,
        'industry': industry,
        'direction': direction,
        'intensity': intensity,
        'duration': duration,
    }


def is_relevant(title, classification):
    """判断新闻是否与持仓/观察池相关"""
    industry = classification['industry']
    intensity = classification['intensity']
    
    # ① 强度≥4的无论行业都入库（市场大事）
    if intensity >= 4:
        return True, 'market_event'
    
    # ② 与持仓行业相关（强度3以上）
    if industry and intensity >= 3:
        for fund_code, industries in HELD_FUNDS.items():
            if industry in industries:
                return True, 'held'
    
    # ③ 与观察池行业相关（强度3以上）
    if industry and intensity >= 3:
        for fund_code, industries in WATCHLIST_FUNDS.items():
            if industry in industries:
                return True, 'watchlist'
    
    # ④ 与关注行业相关（强度3以上）
    if industry and intensity >= 3 and industry in FOCUS_INDUSTRIES:
        return True, 'industry'
    
    # ⑤ 市场大事关键词（强度2以上）
    if intensity >= 2:
        for kw in MARKET_MUST_KEYWORDS:
            if kw in title:
                return True, 'market_event'
    
    return False, None


def collect_events():
    """抓取东财7x24快讯并入库"""
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    
    print(f"[Event采集] {today_str}")
    
    # 抓快讯
    try:
        raw = http("https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_724&column=345&order=1&needInteractData=0&page_index=1&page_size=50&req_trace=1&fields=code,showTime,title,summary")
        d = json.loads(raw.decode('utf-8', 'ignore'))
        items = d.get('data', {}).get('list', [])
    except Exception as e:
        print(f"  快讯抓取失败: {e}")
        return 0
    
    if not items:
        print("  无快讯数据")
        return 0
    
    # 过滤今天的快讯
    today_items = []
    for it in items:
        st = it.get('showTime', '')
        if today_str in st:
            today_items.append(it)
    
    print(f"  今日快讯: {len(today_items)}条（总{len(items)}条）")
    
    # 写入events表
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # 去重：获取今天已入库的标题
    cursor.execute("SELECT title FROM events WHERE DATE(event_time) = %s", (today,))
    existing_titles = set(row[0] for row in cursor.fetchall())
    
    inserted = 0
    skipped = 0
    relevance_stats = {'held': 0, 'watchlist': 0, 'industry': 0, 'market_event': 0}
    
    for it in today_items:
        title = it.get('title', '')
        if not title or len(title) < 5:
            continue
        
        # 去重
        if title in existing_titles:
            skipped += 1
            continue
        
        # 自动分类
        classification = classify_event(title)
        
        # 判断相关性
        is_rel, rel_type = is_relevant(title, classification)
        if not is_rel:
            skipped += 1
            continue
        
        # 解析时间
        st = it.get('showTime', '')
        try:
            event_time = datetime.datetime.strptime(st, '%Y-%m-%d %H:%M:%S')
        except:
            event_time = datetime.datetime.now().replace(hour=0, minute=0, second=0)
        
        # 获取相关基金
        related_funds = []
        if classification['industry']:
            for fund_code, industries in {**HELD_FUNDS, **WATCHLIST_FUNDS}.items():
                if classification['industry'] in industries:
                    related_funds.append(fund_code)
        
        sql = """INSERT INTO events (event_time, event_type, title, industry, direction, intensity, duration, related_funds, source, verified)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '东财7x24', 1)"""
        cursor.execute(sql, (
            event_time, classification['event_type'], title[:500],
            classification['industry'], classification['direction'],
            classification['intensity'], classification['duration'],
            json.dumps(related_funds, ensure_ascii=False) if related_funds else None
        ))
        inserted += 1
        relevance_stats[rel_type] = relevance_stats.get(rel_type, 0) + 1
    
    conn.commit()
    cursor.close(); conn.close()
    
    print(f"  入库: {inserted}条 | 跳过: {skipped}条（去重+无关）")
    print(f"  分类: 持仓{relevance_stats.get('held',0)} | 观察池{relevance_stats.get('watchlist',0)} | 行业{relevance_stats.get('industry',0)} | 市场{relevance_stats.get('market_event',0)}")
    
    # 重大事件自动写入catalyst_analysis
    if inserted > 0:
        _sync_to_catalyst(today)
    
    return inserted


def _sync_to_catalyst(today):
    """将强度≥4的事件同步到catalyst_analysis表"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # 找今天的强事件
    cursor.execute("""
        SELECT id, event_time, event_type, title, industry, direction, intensity, related_funds
        FROM events 
        WHERE DATE(event_time) = %s AND intensity >= 4
    """, (today,))
    strong_events = cursor.fetchall()
    
    if not strong_events:
        cursor.close(); conn.close()
        return
    
    # 检查catalyst_analysis今天是否已有
    cursor.execute("SELECT COUNT(*) FROM catalyst_analysis WHERE DATE(event_time) = %s", (today,))
    existing = cursor.fetchone()[0]
    
    if existing > 0:
        print(f"  catalyst_analysis今天已有{existing}条，跳过同步")
        cursor.close(); conn.close()
        return
    
    for ev in strong_events:
        ev_id, ev_time, ev_type, title, industry, direction, intensity, related_funds = ev
        
        # 匹配基金
        matched_funds = []
        if industry:
            for fund_code, industries in {**HELD_FUNDS, **WATCHLIST_FUNDS}.items():
                if industry in industries:
                    matched_funds.append({
                        'code': fund_code,
                        'name': fund_code,
                        'match': '完美' if fund_code in HELD_FUNDS else '间接',
                        'reason': f'{industry}方向',
                    })
        
        sql = """INSERT INTO catalyst_analysis 
                 (event_time, event_type, title, source, core_variable, industry_chain,
                  matched_funds, predicted_direction, confidence, created_at, updated_at)
                 VALUES (%s, %s, %s, '东财7x24', %s, %s, %s, %s, %s, NOW(), NOW())"""
        cursor.execute(sql, (
            ev_time, ev_type, title[:500],
            f'{industry}相关事件' if industry else '市场大事',
            industry or '全局',
            json.dumps(matched_funds, ensure_ascii=False) if matched_funds else None,
            direction,
            intensity * 20,  # 强度转信心分
        ))
    
    conn.commit()
    cursor.close(); conn.close()
    print(f"  同步{len(strong_events)}条强事件到catalyst_analysis")


def backfill_event_returns():
    """为已有事件补算T+N市场反应"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    cutoff = datetime.date.today() - datetime.timedelta(days=3)
    cursor.execute("""
        SELECT id, event_time, industry 
        FROM events 
        WHERE DATE(event_time) <= %s AND market_reaction IS NULL AND industry IS NOT NULL
        LIMIT 20
    """, (cutoff,))
    events = cursor.fetchall()
    
    if not events:
        cursor.close(); conn.close()
        return
    
    print(f"  回填{len(events)}条事件的市场反应...")
    
    # 从数据库动态构建 行业→基金代码 映射（sectors表是 基金代码→行业列表，需反转）
    industry_funds = {}
    for fc, sectors in get_fund_sectors().items():
        for s in sectors:
            if s not in industry_funds:
                industry_funds[s] = fc
    
    for ev in events:
        fund_code = industry_funds.get(ev['industry'])
        if not fund_code:
            continue
        
        ev_date = ev['event_time'].date() if isinstance(ev['event_time'], datetime.datetime) else ev['event_time']
        cursor.execute("""
            SELECT daily_return FROM nav_daily
            WHERE fund_code = %s AND trade_date > %s
            ORDER BY trade_date ASC LIMIT 1
        """, (fund_code, ev_date))
        t1_row = cursor.fetchone()
        
        if t1_row and t1_row['daily_return'] is not None:
            cursor.execute("UPDATE events SET market_reaction = %s WHERE id = %s",
                          (t1_row['daily_return'], ev['id']))
    
    conn.commit()
    cursor.close(); conn.close()


if __name__ == '__main__':
    collect_events()
    backfill_event_returns()
