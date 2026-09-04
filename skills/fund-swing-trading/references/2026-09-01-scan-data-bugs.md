# 14:00扫描数据源Bug记录（09-01）

## Bug1：资金流向方向反转（✅ 已修复）

### 问题
扫描显示"计算机+66.3亿、电子+54.1亿、无板块净流出"，实际东财数据是"电子净流出171亿、半导体-141.6亿"。

### 根因
fund_scan_data.py第8段使用新浪接口`MoneyFlow.ssl_bkzj_bk`，返回"行业板块"口径（计算机应用服务业等大类），与东财的"概念板块"口径（半导体/CPO/存储等细分）不同。新浪的净流入计算方式可能导致所有板块显示正值。

### 修复
换成东财push2接口：`https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:2+f:!50&fields=f12,f14,f62`

## Bug2：北向资金数据过时（⚠️ 今晚修复）

### 问题
扫描显示"2026-08-31净流入0.12亿，连续3日"，实际9/1全天净买入76.87亿，连续8日。

### 根因
脚本从MySQL north_flow_daily表读取，但数据只更新到8/31（15:05入库任务的数据）。

### 修复方案
15:05入库任务需加入今日北向数据写入，或在扫描脚本中加东财datacenter实时接口作为fallback。

## Bug3：没有events表查询（✅ 已修复）

### 问题
扫描完全没提9/2燧原申购、9/7摩尔线程解禁、9/9-11光博会、9/11-13算力大会、9/4特斯拉发布会。

### 根因
扫描脚本没有查询events表的逻辑。

### 修复
在fund_scan_data.py快讯段之后新增events表查询段（第6.5段），自动输出"未来7天重大事件"。

---

## 基础设施变更：搜索引擎替换（✅ 已完成 09-01）

### 问题
360搜索(so.com)返回0字节、百度返回验证码、DDGS依赖Google/Yahoo从国内服务器无法访问。

### 解决方案
Docker自建SearXNG（localhost:8888），配置中国搜索引擎（百度/搜狗/必应/夸克），禁用不通的西方引擎。

### 部署详情
```bash
# 容器
sudo docker run -d --name searxng --restart unless-stopped -p 8888:8080 searxng/searxng:latest

# 配置（~/searxng/searxng/settings.yml）
# 启用JSON格式 + 中国引擎 + 禁用Google/DuckDuckGo/Brave

# Hermes配置
# ~/.hermes/config.yaml: web.search_backend: searxng
# ~/.hermes/.env: SEARXNG_URL=http://localhost:8888
```

### 数据源优先级（更新后）
MySQL > 东财push2 > 东财快讯 > **SearXNG** > 老虎证券/雪球 > Bing英文兜底
