#!/home/ubuntu/.hermes/venv-fund/bin/python3
"""基金持仓入库：抓取前十大持仓 → 持久化到funds表top_holdings字段。
设计目标：每周运行一次（或手动触发），避免频繁请求被限流。
"""
import pymysql, datetime, json, urllib.request, re, ssl, time

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

def fetch_holdings(fund_code):
    """抓取基金前十大持仓"""
    try:
        url = f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={fund_code}&topline=10"
        raw = http(url, {"Referer": "https://fundf10.eastmoney.com/"}).decode('utf-8', 'ignore')
        
        # 匹配表格行：序号|代码|名称|...|占净值比（兼容单双引号）
        holdings = []
        rows = re.findall(r"<td>(\d+)</td><td><a[^>]*>(\d+)</a></td><td class=['\"]tol['\"]><a[^>]*>([^<]+)</a></td>.*?<td class=['\"]tor['\"]>([\d.]+)%</td>", raw)
        
        for seq, code, name, weight in rows[:10]:
            holdings.append({
                'code': code,
                'name': name,
                'weight': float(weight),
            })
        
        return holdings
    except Exception as e:
        print(f"  {fund_code} 持仓抓取失败: {e}")
        return None

def sync_holdings():
    """同步所有关注基金的持仓"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    # 获取所有基金
    cursor.execute("SELECT code, name FROM funds")
    funds = cursor.fetchall()
    
    print(f"[持仓同步] {datetime.date.today()} | {len(funds)}只基金")
    
    updated = 0
    for f in funds:
        code = f['code']
        holdings = fetch_holdings(code)
        
        if holdings:
            # 保存为JSON
            holdings_json = json.dumps(holdings, ensure_ascii=False)
            
            # 提取行业暴露（从持仓名称推断）
            stock_names = [h['name'] for h in holdings]
            sector = infer_sector(stock_names, code)
            
            cursor.execute(
                "UPDATE funds SET top_holdings = %s, sector_exposure = %s, last_updated = NOW() WHERE code = %s",
                (holdings_json, sector, code)
            )
            updated += 1
            print(f"  {code} {f['name'][:10]}: {len(holdings)}只持仓 | {sector}")
        else:
            print(f"  {code}: 无持仓数据")
        
        time.sleep(1)  # 避免限流
    
    conn.commit()
    cursor.close(); conn.close()
    
    print(f"\n✅ 更新{updated}/{len(funds)}只基金持仓")

def infer_sector(stock_names, fund_code):
    """从持仓股票名推断行业"""
    sector_map = {
        '半导体': ['中芯', '北方华创', '中微公司', '拓荆', '华海清科', '海光', '寒武纪', '兆易创新', '韦尔股份', '澜起科技', '富创精密', '精测电子', '长川科技'],
        'AI算力': ['中际旭创', '新易盛', '天孚通信', '光迅科技', '工业富联', '沪电股份', '胜宏科技'],
        '机器人': ['汇川技术', '绿的谐波', '三花智控', '鸣志电器', '奥普特', '柏楚电子'],
        '创新药': ['恒瑞医药', '药明康德', '凯莱英', '泰格医药', '康龙化成'],
        '稀土': ['北方稀土', '中国稀土', '广晟有色', '盛和资源'],
        '有色金属': ['紫金矿业', '洛阳钼业', '中国铝业', '江西铜业', '天齐锂业', '赣锋锂业'],
        '电池': ['宁德时代', '比亚迪', '亿纬锂能', '国轩高科', '欣旺达'],
        '电网': ['国电南瑞', '许继电气', '思源电气', '特变电工'],
        '消费电子': ['立讯精密', '歌尔股份', '舜宇光学'],
    }
    
    # 基金代码→板块映射（从数据库动态获取）
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from fund_common import get_fund_sectors
        _db_sectors = get_fund_sectors()
        code_map = {code: sectors[0] if sectors else '' for code, sectors in _db_sectors.items()}
    except Exception:
        code_map = {}
    
    if fund_code in code_map:
        return code_map[fund_code]
    
    # 按持仓股票匹配
    for sector, keywords in sector_map.items():
        hits = sum(1 for kw in keywords if any(kw in sn for sn in stock_names))
        if hits >= 2:
            return sector
    
    return '其他'

if __name__ == '__main__':
    sync_holdings()
