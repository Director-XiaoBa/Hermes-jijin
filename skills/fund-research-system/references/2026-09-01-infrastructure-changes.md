# 09-01 基础设施变更记录

## 新增表：fund_sector_map（基金关联板块映射）

### 用途
每只基金关联一个板块指数，用于14:00扫描时输出"关联板块实时涨跌"（类似养基宝功能）。

### 表结构
```sql
CREATE TABLE fund_sector_map (
    id INT AUTO_INCREMENT PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    fund_name VARCHAR(50),
    sector_name VARCHAR(50),      -- 板块名称（如"科创芯片"）
    sector_index_code VARCHAR(20), -- 东财指数代码（如"1.588200"）
    sector_bk_code VARCHAR(20),   -- 板块代码（如"BK1036"）
    UNIQUE KEY uk_fund (fund_code)
);
```

### 当前数据
| fund_code | sector_name | sector_bk_code |
|:--|:--|:--|
| 017470 | 上证科创芯片 | BK1036 |
| 017811 | 半导体材料 | BK1325 |
| 011036 | 稀土产业 | BK0560 |
| 025209 | 存储芯片 | BK1137 |
| 025422 | CPO | BK1101 |
| 018301 | 国证消费电子 | BK0738 |
| 018345 | 中证机器人 | BK1408 |
| 018123 | 国产算力 | BK1325 |

## 数据源变更

### 资金流向：新浪MoneyFlow → 东财push2
- **旧接口**：`vip.stock.finance.sina.com.cn/.../MoneyFlow.ssl_bkzj_bk`（行业板块口径，方向常反转）
- **新接口**：`push2.eastmoney.com/api/qt/clist/get?fs=m:90+t:2+f:!50&fid=f62`（概念板块口径，准确）
- **影响脚本**：fund_scan_data.py（第8段）、fund_daily_pipeline_v2.py（3处）、fund_signal_analysis.py（1处）

### 搜索引擎：360/百度 → SearXNG
- **旧方案**：360搜索(so.com)/百度 — 自09-01起被封
- **新方案**：Docker SearXNG（localhost:8888），聚合百度/搜狗/必应
- **配置**：config.yaml `search_backend: searxng`，.env `SEARXNG_URL=http://localhost:8888`

### 事件日历：新增events表查询
- fund_scan_data.py第6.5段：查询MySQL events表未来7天事件
- 自动输出"📅 未来7天重大事件"模块

## 北向数据修复（待完成）
- **问题**：扫描从MySQL读北向数据，但数据只到8/31
- **方案**：15:05入库任务加入东财datacenter实时接口fallback
