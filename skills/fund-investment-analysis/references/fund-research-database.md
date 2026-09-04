# 基金研究数据库 Schema 参考

## 连接信息
- Host: 127.0.0.1:3306
- Database: fund_research
- User: fund_admin / FundR2026!db
- Venv: ~/.hermes/venv-fund/bin/python3

## 表结构（6张核心表）

### funds（基金档案）
```sql
CREATE TABLE funds (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(100), manager VARCHAR(50), fund_type VARCHAR(50),
    scale DECIMAL(10,2), fee_c DECIMAL(5,4), fee_mgmt DECIMAL(5,4),
    top_holdings TEXT, sector_exposure VARCHAR(200),
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### nav_daily（每日净值+指标）
```sql
CREATE TABLE nav_daily (
    id INT AUTO_INCREMENT PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL, trade_date DATE NOT NULL,
    nav DECIMAL(10,4), daily_return DECIMAL(8,4),
    return_3d/5d/10d/20d DECIMAL(8,4),
    high_20d/low_20d DECIMAL(10,4), drawdown_from_high DECIMAL(8,4),
    consecutive_up/down INT, price_pattern VARCHAR(20), position_label VARCHAR(10),
    UNIQUE KEY uk_fund_date (fund_code, trade_date)
);
```

### market_daily（每日市场快照）
```sql
CREATE TABLE market_daily (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE NOT NULL, index_name VARCHAR(50) NOT NULL,
    close_price/daily_return/open_price/high/low/prev_close DECIMAL,
    price_pattern VARCHAR(20),
    UNIQUE KEY uk_date_index (trade_date, index_name)
);
```

### events（结构化事件）
```sql
CREATE TABLE events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_time DATETIME, event_type VARCHAR(50), title VARCHAR(500),
    industry VARCHAR(100), direction VARCHAR(10), intensity TINYINT,
    duration VARCHAR(20), market_reaction/t1/t3/t5_return DECIMAL,
    source VARCHAR(100), verified TINYINT(1) DEFAULT 0
);
```

### signals（信号源记录）
```sql
CREATE TABLE signals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    signal_date DATE, source VARCHAR(50), fund_code VARCHAR(10),
    direction VARCHAR(20), nav_at_signal DECIMAL(10,4), reason TEXT,
    t1/t3/t5/t10_return DECIMAL(8,4), is_correct TINYINT(1)
);
```

### trades（个人交易记录）
```sql
CREATE TABLE trades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE, fund_code VARCHAR(10), direction VARCHAR(10),
    amount DECIMAL(10,2), nav_price DECIMAL(10,4), reason TEXT,
    actual_return/hold_days/net_return, trade_status VARCHAR(20) DEFAULT 'open'
);
```

## 脚本清单

| 脚本 | 用途 | 运行方式 |
|:--|:--|:--|
| `fund_daily_pipeline.py` | 每日采集+入库+Snapshot+T+N+Pattern+Event | cron 15:30 |
| `fund_signal_log.py` | 信号入库 | 手动 |
| `fund_trade_log.py` | 交易入库 | 手动 |
| `fund_tn_fill.py` | T+N收益自动补算 | pipeline调用 |
| `fund_pattern_match.py` | 形态匹配→历史相似→概率 | pipeline（≥30天） |
| `fund_event_collect.py` | 东财快讯→events表 | pipeline每天 |
| `fund_holdings_sync.py` | 前十大持仓入库 | cron每周五 |
| `fund_overseas_chain.py` | 海外传导链统计 | pipeline每周一 |
| `fund_feedback.py` | 月度复盘+权重建议 | cron每月28号 |

## Cron调度

| 时间 | 任务 | 频率 |
|:--|:--|:--|
| 14:00 | 盘中扫描 | 每天 |
| 14:40 | 尾盘确认 | 每天 |
| 15:20 | 复盘验证 | 每天 |
| 15:30 | Pipeline全量 | 每天 |
| 周五16:00 | 持仓同步 | 每周 |
| 28号10:00 | 月度复盘 | 每月 |

## Pipeline流程
15:30触发 → 采集指数/净值/板块 → 写MySQL → 生成Snapshot → T+N回填 → Pattern匹配 → Event采集 → 海外传导链(周一)

## 事件分类关键词
半导体:芯片/晶圆/光刻/中芯 | AI:大模型/算力/GPU/DeepSeek | CPO:光模块/中际旭创/新易盛 | 机器人:宇树/优必选 | 创新药:CRO/恒瑞/药明康德 | 稀土:出口管制/镓/锗 | 有色:铜/铝/锂 | 黄金:金价/央行购金/美联储

## 海外传导链
费城半导体→科创芯片/半导体ETF | 纳斯达克→创业板/科创50

## 关注基金
017811 012738 019919 017470 018345 011036 012863 017102 008586 018301 004433 025833 011613 025422 025209
