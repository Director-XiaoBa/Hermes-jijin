# 天天基金（East Money）API 查询参考

查询 C 类场外联接基金数据的技术方案。用于替换人工搜索，实现自动化的基金代码/信息检索。

## 历史净值（lsjz API）— 最干净的 JSON 数据源

推荐用于查询基金近期走势。返回标准 JSON，含日期、单位净值、累计净值、日涨跌幅%，比 `pingzhongdata.js` 更易解析。

```bash
# 查最近20个交易日净值
curl -s "https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery&fundCode=011036&pageIndex=1&pageSize=20" \
  -H "Referer: https://fundf10.eastmoney.com/" | python3 -c "
import sys, json, re
data = sys.stdin.read()
m = re.search(r'jQuery\((.*)\)', data)
if m:
    j = json.loads(m.group(1))
    for item in j.get('Data', {}).get('LSJZList', []):
        print(f\"{item.get('FSRQ')}: NAV={item.get('DWJZ')}, CHG%={item.get('JZZZL')}\")
"
```

**重要参数**：必须带 `Referer` 请求头，否则被拦截。`pageSize` 最大支持 20 条/页。返回的 JSON 被 `jQuery(...)` 包裹，需要正则提取后解析。

返回字段：
- `FSRQ` — 日期（如 2026-07-22）
- `DWJZ` — 单位净值
- `LJJZ` — 累计净值
- `JZZZL` — 日涨跌幅百分比（如 4.26 表示涨 4.26%）

## 数据源

| 用途 | 接口 | 说明 |
|------|------|------|
| **全量基金代码表** | `https://fund.eastmoney.com/js/fundcode_search.js` | **JS 文件，包含所有基金**：`[code, pinyin_abbr, name, type, pinyin_full]` 结构，约 2.3M+ 行。可在 Python 中解析 JS 变量 `r` 为 JSON 数组后全量搜索。适合多关键词批量匹配和发现 API 搜索漏掉的基金。 |
| **基金搜索** | `https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key={关键词}` | 按基金名称/代码搜索，返回 JSON |
| **基金净值+规模+持仓** | `https://fund.eastmoney.com/pingzhongdata/{code}.js` | JS 变量文件，包含净值走势、规模变动、持有人结构、基金经理等 |
| **基金基本信息（含成立日）** | `https://fund.eastmoney.com/f10/jbgk_{code}.html` | HTML 页面，编码为 GBK，含成立日期、基金经理等 |
| **基金详情页（含跟踪指数）** | `https://fund.eastmoney.com/{code}.html` | HTML 页面，含跟踪标的、申赎状态等 |
| **实时估值** | `https://fundgz.1234567.com.cn/js/{code}.js` | 返回 JSONP 格式的当日估值净值，含 `fundcode`、`name`、`dwjz`（昨日净值）、`gsz`（实时估值）、`gszzl`（实时涨跌幅%） |

## 搜索查询

### 方案 A：FundSearch API（在线，适合精确搜索）

```bash
# 搜索"银行ETF联接 C"类基金
curl -s "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key=银行ETF联接+C" \
  -H "User-Agent: Mozilla/5.0" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data.get('Datas', []):
    info = item.get('FundBaseInfo', {})
    print(f\"{item['CODE']} | {item['NAME']} | {info.get('FTYPE','')} | {info.get('JJGS','')}\")
"
```

### 方案 B：fundcode_search.js 全量解析（离线，适合多关键词批量扫描）

用于需要跨多个关键词搜索、或 API 搜索可能遗漏的场景。下载一次后可在 Python 中做任意匹配。

```bash
# 下载全量基金代码表（约 2.3MB）
curl -s "https://fund.eastmoney.com/js/fundcode_search.js" \
  -H "User-Agent: Mozilla/5.0" \
  -o /tmp/fundcode_search.js

# 解析为 JSON 并用多关键词检索
python3 << 'EOF'
import json

# 读取 JS 文件并提取 JSON 数组
with open("/tmp/fundcode_search.js", "r", encoding="utf-8") as f:
    data = f.read()
    # JS 变量赋值: var r = [[...],[...],...];
    json_str = data.split("=", 1)[1].strip().rstrip(";")
    funds = json.loads(json_str)

# fundcode_search.js 的每行格式: [code, pinyin_abbr, name, fund_type, pinyin_full]
# 示例: ["005693","GFZZJGETFLJC","广发中证军工ETF联接C","指数型-股票","GUANGFAZHONGZHENGJUNGONGETFLIANJIEC"]

keywords = ["军工","国防","高端装备","商业航天","航天航空","高端制造"]
for f in funds:
    name = f[2]   # 基金中文名称
    ftype = f[3]  # 基金类型（如 "指数型-股票"）
    for kw in keywords:
        if kw in name:
            print(f"{f[0]}|{f[2]}|{f[3]}")
            break
EOF
```

**特点对比**：

| 维度 | FundSearch API | fundcode_search.js |
|------|---------------|-------------------|
| 数据量 | 按关键词返回有限条（~20条） | **全部基金**（23万+条） |
| 搜索能力 | 模糊匹配，支持部分关键词 | 只能 Python 侧做子串/正则匹配 |
| 离线可用 | 否 | 是（下载后本地检索） |
| 字段信息 | 含基金类型、管理公司、成立日期等 | 含代码、名称、类型、拼音 |
| 适用场景 | 精确查找某只基金信息 | 跨赛道发现、多关键词批量扫描 |

### 搜索技巧

- 关键词尽量精确，如 `银行ETF联接 C`、`中证银行+C`、`银行指数C`
- 搜索港股指数的银行基金可用 `香港银行指数+C`
- 返回的 `Datas` 数组中可能有非基金条目（如股票代码），按 `CATEGORY: 700` 过滤基金

## 成立日期提取

```python
import urllib.request, re

code = "001595"
url = f"https://fund.eastmoney.com/f10/jbgk_{code}.html"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
html = urllib.request.urlopen(req).read()
text = html.decode('gbk', errors='ignore')

m = re.search(r'成立日期[：:]\s*(\d{4}-\d{2}-\d{2})', text)
if m:
    print(f"成立日期: {m.group(1)}")
```

## 跟踪指数提取

**推荐方式**：直接用浏览器访问 `https://fund.eastmoney.com/{code}.html`，在页面详情部分的"跟踪标的"行可见。

**终端提取**（从基金详情页 HTML）：

```bash
curl -s "https://fund.eastmoney.com/${CODE}.html" \
  -H "User-Agent: Mozilla/5.0" | grep -oP '跟踪标的[：:]\s*[^<|]+'
# 返回示例：跟踪标的：中证军工指数 | 年化跟踪误差：1.84%
```

**批量验证跟踪指数**（配合 fundcode_search.js 找到的候选基金列表）：

```bash
# 遍历候选代码列表，逐只查询跟踪指数
for code in 005693 002199 010364 012041; do
    echo "=== $code ==="
    curl -s "https://fund.eastmoney.com/${code}.html" \
      -H "User-Agent: Mozilla/5.0" | grep -oP '跟踪标的[：:]\s*[^<|]+'
    sleep 0.3  # 避免触发限流
done
```

> ⚠️ 基金名称含"军工"不一定跟踪军工指数，必须通过"跟踪标的"行确认。例如"鹏华空天军工指数(LOF)C"(010364) 跟踪的是**中证空天一体军工指数**，而非普通中证军工指数。

## 规模数据提取

从 pingzhongdata JS 文件中提取规模变动：

```python
import re

js_data = ...  # pingzhongdata/{code}.js 的内容

# 规模变动（最新规模 + 环比）
m = re.search(r'var Data_fluctuationScale\s*=\s*({.*?});', js_data, re.DOTALL)
if m:
    data = json.loads(m.group(1))

# 最新净值
m = re.search(r'var Data_netWorthTrend\s*=\s*\[({.*?})\s*,\s*{', js_data, re.DOTALL)
if m:
    first_nav = json.loads("[" + m.group(1) + "]")
```

## 高级解析：pingzhongdata.js 中的复杂数据结构

部分 JS 变量并非标准 `{key: [array]}` 格式，反复解析失败时参考以下模式：

### Data_fluctuationScale（规模变动）

```python
# ⚠️ series 是 {y, mom} 对象数组，不是 {y: [], mom: []}
# ❌ 错误：fs['series'][0]['y'][i]  → TypeError: 'float' object is not subscriptable
# ✅ 正确：
m = re.search(r'var Data_fluctuationScale\s*=\s*(\{.*?\})\s*;', js_data, re.DOTALL)
if m:
    fs = json.loads(m.group(1))
    for item in fs['series']:
        print(f"规模: {item['y']}亿, 环比: {item['mom']}")
```

### Data_assetAllocation（资产配置）

```python
# mixed types: '股票占净比'/现金/债券是数组, '净资产'有 type:"line"
m = re.search(r'var Data_assetAllocation\s*=\s*(\{.*?\})\s*;', js_data, re.DOTALL)
if m:
    aa = json.loads(m.group(1))
    cats = aa['categories']
    series = {s['name']: s['data'] for s in aa['series']}
    for i, c in enumerate(cats):
        stock = series['股票占净比'][i]
        net = series['净资产'][i]
```

### Data_holderStructure（持有人结构）

```python
# series 是命名字典数组: [{name, data}, ...]
m = re.search(r'var Data_holderStructure\s*=\s*(\{.*?\})\s*;', js_data, re.DOTALL)
if m:
    hs = json.loads(m.group(1))
    cats = hs['categories']
    shares = {s['name']: s['data'] for s in hs['series']}
    # 访问: shares['机构持有比例'][i], shares['个人持有比例'][i]
```

### Data_buySedemption（申购赎回）

```python
# 同上模式
m = re.search(r'var Data_buySedemption\s*=\s*(\{.*?\})\s*;', js_data, re.DOTALL)
if m:
    bs = json.loads(m.group(1))
    shares = {s['name']: s['data'] for s in bs['series']}
    # shares['期间申购'], shares['期间赎回'], shares['总份额']
```

### Data_performanceEvaluation（业绩评价评分）

```python
# 结构: {avr, categories[], dsc[], data[]}
m = re.search(r'var Data_performanceEvaluation\s*=\s*(\{.*?\})\s*;', js_data, re.DOTALL)
if m:
    pe = json.loads(m.group(1))
    print(f"总分: {pe['avr']}")
    for i, c in enumerate(pe['categories']):
        print(f"{c}: {pe['data'][i]}分 - {pe['dsc'][i]}")
```

### Data_currentFundManager（现任基金经理）

```python
# 数组，第0项是当前基金经理，含 power/experience/profit 三级评价
m = re.search(r'var Data_currentFundManager\s*=\s*(\[.*?\])\s*;', js_data, re.DOTALL)
if m:
    fm = json.loads(m.group(1))[0]
    print(f"经理: {fm['name']}, 从业: {fm['workTime']}, 管理: {fm['fundSize']}")
    print(f"综合: {fm['power']['avr']}")
    # profit 结构: {categories[], series: [{data: [{y: val}, ...]}]}
    profit_data = fm['profit']['series'][0]['data']
    print(f"任期收益: {profit_data[0]['y']}% vs 同类平均: {profit_data[1]['y']}%")
```

### 净值趋势中的大整数时间戳转换

```python
from datetime import datetime, timezone, timedelta
tz = timezone(timedelta(hours=8))

# pingzhongdata 的时间戳是毫秒级（13位）
def ts_to_date(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz).strftime('%Y-%m-%d')

# Data_netWorthTrend: [{"x": 1677686400000, "y": 1.0}, ...]
net_worth = json.loads(...)
latest_date = ts_to_date(net_worth[-1]['x'])
```

### 关键时间节点查找（近1年最高/最低/回撤）

```python
# 找近1年的高点/低点/回撤
net_worth = [...]  # 完整净值数组
yr_ago_idx = max(0, len(net_worth) - 365)
last_yr = net_worth[yr_ago_idx:]

peak = max(last_yr, key=lambda d: d['y'])
trough = min(last_yr, key=lambda d: d['y'])
drawdown = (net_worth[-1]['y'] / peak['y'] - 1) * 100

print(f"最高: {peak['y']:.4f} ({ts_to_date(peak['x'])})")
print(f"最低: {trough['y']:.4f} ({ts_to_date(trough['x'])})")
print(f"距高点回撤: {drawdown:.2f}%")
```

### 全量 JS 变量列表

```python
# 列出 pingzhongdata.js 中的所有 var 声明，辅助发现可用数据
for m in re.finditer(r'var\s+(\w+)\s*=', js_data):
    print(f"  var {m.group(1)}")
```

可用变量包括但不限于：`Data_netWorthTrend`, `Data_ACWorthTrend`, `Data_assetAllocation`, `Data_fluctuationScale`, `Data_holderStructure`, `Data_buySedemption`, `Data_performanceEvaluation`, `Data_currentFundManager`, `Data_fundSharesPositions`, `Data_hycc_list`, `jjcc_list`, `swithSameType`, `syl_1y`, `syl_6y`, `syl_3y`, `syl_1n`, `fS_name`, `fS_code`, `fund_sourceRate`, `fund_Rate`.

## 常用查询模式

### 查某个指数有哪些 C 类联接基金

```bash
KEYWORD="银行指数"
curl -s "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$KEYWORD'))")" \
  -H "User-Agent: Mozilla/5.0"
```

### 查单个基金详情

```bash
CODE="001595"
# 净值+规模信息
curl -s "https://fund.eastmoney.com/pingzhongdata/${CODE}.js" \
  -H "User-Agent: Mozilla/5.0" | grep -oP 'fS_name = "[^"]*"'
# 成立日期
curl -s "https://fund.eastmoney.com/f10/jbgk_${CODE}.html" \
  -H "User-Agent: Mozilla/5.0" | iconv -f gbk -t utf-8 2>/dev/null | grep -oP '成立日期[：:]\s*\d{4}-\d{2}-\d{2}'
```

## 注意事项

- 所有接口需要设置 `User-Agent` 请求头，否则可能被拦截
- `pingzhongdata` 返回的是 JS 变量赋值，不是标准 JSON，需要用正则提取
- `jbgk_` 页面编码为 **GBK**，需用 `gbk` 解码或 `iconv -f gbk -t utf-8` 转换
- 基金搜索接口返回的 `FTYPE` 为 `指数型-股票` 表示指数基金
- C 类基金名称末尾带 "C"（如 `天弘中证银行ETF联接C`），与 A 类共享同一个基金底层资产但收费方式不同
- 查询时需要适当加 `sleep 0.3~0.5` 避免触发 API 限流
