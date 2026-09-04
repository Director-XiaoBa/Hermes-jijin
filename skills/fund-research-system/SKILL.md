---
name: fund-research-system
description: 基金研究系统的数据基座——MySQL数据库(fund_research)、每日数据Pipeline V2、Market Snapshot生成、资金流向分析。Phase 1-5已全部落地（08-26）。触发：涉及基金数据库/数据入库/Pattern匹配/信号评估/交易记录入库/资金流向/技术指标时加载。
---

# 基金研究系统（数据基座）

## 概述

本skill是基金研究系统的**数据层**，与 `fund-swing-trading`（策略执行层）和 `fund-investment-analysis`（分析判断层）互补。

核心理念来自GPT参考文档的融合：
- **先积累数据，不追求预测** — 30-60个交易日数据积累后才做Pattern匹配
- **Snapshot替代全量分析** — 每天生成精炼快照，Hermes读快照而非原始API
- **信号源当待验证** — 老道不是老师，是待验证的信号源
- **结果反哺系统** — 交易结果回写，修正判断权重

## 数据库

**库名**：`fund_research`
**连接**：`mysql -u fund_admin -p'FundR2026!db' -h 127.0.0.1 fund_research`
**venv**：`~/.hermes/venv-fund/bin/python3`（含pymysql）

### 19张核心表

| 表名 | 存什么 | 写入频率 | 读取场景 |
|:--|:--|:--|:--|
| `funds` | 基金档案（代码/名称/经理/持仓/费率/规模/ETF映射/行业标签/观察列表） | 每周更新1次 | 分析前查基金信息 |
| `nav_daily` | 每日净值+技术指标（涨跌/连涨/回撤/位置/MA/RSI/MACD/趋势/支撑压力/ETF形态） | 每天15:30后 | 回测、Pattern匹配、技术分析 |
| `market_daily` | 每日大盘+行业+海外快照 | 每天15:30后 | Snapshot、趋势判断 |
| `events` | 结构化事件（时间/事件/行业/方向/强度/影响基金/T+N表现） | 有大事件时 | 历史类似事件检索 |
| `signals` | 信号源记录（老道/Hermes/你，每次信号+方向+后续T+N收益） | 每次有信号时 | 信号源胜率统计 |
| `trades` | 个人交易（买入/卖出/理由/持有天数/收益/最大浮盈浮亏） | 每次操作后 | 个人复盘、自我认知 |
| `ai_recommendations` | AI推荐记录（推荐日期/基金/方向/置信度/理由/验证结果） | 14:40确认后 | AI胜率统计、校正推荐 |
| `decisions` | 决策日志（基金/决策类型/日期/理由/信号源/市场状态/信心度） | 每次决策后 | 决策复盘、策略优化 |
| `strategy_backtest` | 策略回测记录（策略名/基金/区间/胜率/收益/回撤/夏普） | 手动/定期 | 策略验证、参数调优 |
| `sector_flow_daily` | 板块资金流向（主力/散户净流入，每日） | 每天15:30 | 资金趋势分析 |
| `sector_return_daily` | 板块资金流向排名（每日，新浪API净流入） | 每天15:30 | 板块轮动分析 |
| `north_flow_daily` | 北向资金（沪股通/深股通净流入） | 每天15:30 | 外资风向 |
| `margin_trading_daily` | 融资融券数据（融资余额/融券余额） | 每天15:30 | 杠杆资金方向（用资金流向近似） |
| `etf_flow_daily` | ETF申赎数据（份额变化） | 每天15:30 | 机构资金进出（用ETF行情近似） |
| `signal_resonance` | 信号共振记录（6个信号源综合判断） | 每天15:30 | 多指标共振分析 |
| `predictions` | AI预测记录（预测内容/依据/验证结果/教训） | 14:00写入，22:45验证 | 自进化：预测正确率统计 |
| `daily_predictions` | 每日基金预测（预测涨跌%/操作/实际结果/准确度） | 周日09:00写入5天，22:45验证当天 | 自进化：基金级别预测准确率 |
| `improvement_log` | 改进清单（教训类别/影响/措施/状态） | 15:50写入 | 自进化：错误模式识别 |
| `monthly_stats` | 月度统计（正确率/错误模式/规则更新） | 月底写入 | 自进化：量化改进效果 |
| `kol_tracking` | KOL跟踪（推荐/验证/可信度） | 有推荐时写入 | 三条学习线之一 |

### decisions 决策日志表

```sql
CREATE TABLE decisions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    decision_type ENUM('buy','sell','hold','watch') NOT NULL,
    decision_date DATE NOT NULL,
    reason TEXT COMMENT '决策依据',
    signal_source VARCHAR(50) COMMENT '信号来源：老道/AI/自主',
    market_state TEXT COMMENT '当时市场状态',
    confidence DECIMAL(3,2) COMMENT '信心度0-1',
    actual_outcome DECIMAL(8,4) COMMENT '实际结果',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fund_code (fund_code),
    INDEX idx_decision_date (decision_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='决策日志';
```

### strategy_backtest 策略回测表

```sql
CREATE TABLE strategy_backtest (
    id INT AUTO_INCREMENT PRIMARY KEY,
    strategy_name VARCHAR(50) NOT NULL,
    fund_code VARCHAR(10) NOT NULL,
    backtest_period VARCHAR(20) COMMENT '回测区间',
    total_trades INT COMMENT '总交易次数',
    win_rate DECIMAL(5,2) COMMENT '胜率%',
    avg_return DECIMAL(8,4) COMMENT '平均收益率%',
    max_drawdown DECIMAL(8,4) COMMENT '最大回撤%',
    sharpe_ratio DECIMAL(5,2) COMMENT '夏普比率',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_strategy_name (strategy_name),
    INDEX idx_fund_code (fund_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略回测记录';
```

### funds 表扩展字段（08-27新增）

```sql
ALTER TABLE funds ADD COLUMN etf_code VARCHAR(10) COMMENT '对应ETF代码';
ALTER TABLE funds ADD COLUMN sectors VARCHAR(200) COMMENT '行业标签，逗号分隔';
ALTER TABLE funds ADD COLUMN is_watchlist TINYINT DEFAULT 0 COMMENT '0=持仓 1=观察列表';
ALTER TABLE funds ADD COLUMN watchlist_reason TEXT COMMENT '观察理由';
ALTER TABLE funds ADD COLUMN watchlist_conditions TEXT COMMENT '进场条件JSON';
```

### nav_daily 关键字段

```sql
fund_code, trade_date, nav, daily_return,
return_3d, return_5d, return_10d, return_20d,  -- 近N日累计收益
high_20d, low_20d, drawdown_from_high,          -- 近20日高低点+回撤
consecutive_up, consecutive_down,               -- 连涨/连跌天数
price_pattern,                                  -- 价格行为形态
position_label,                                 -- 位置标签: "{low}-{high}" 格式（VARCHAR(30)）
-- V2新增技术指标：
etf_code, etf_open, etf_high, etf_low, etf_close, etf_pattern,  -- ETF OHLC+形态
ma5, ma10, ma20, ma60,                          -- 均线
rsi_6, rsi_12,                                  -- RSI指标
macd_line, signal_line, macd_histogram,         -- MACD
trend,                                          -- 趋势：上升/下降/震荡
support, resistance,                            -- 支撑压力位
data_source VARCHAR(20) DEFAULT 'fund_nav'       -- 数据来源: fund_nav=真实净值, etf_realtime=ETF估算
```

**data_source字段说明：**
- `fund_nav`：来自天天基金pingzhongdata的真实净值
- 15:05 Pipeline跳过无今日净值的基金（只写market_daily等ETF数据），不写入nav_daily
- 22:00 fund_nav_update.py拉取今日净值写入nav_daily（full模式）
- 22:30 fund_nav_update.py兜底补漏（fallback模式）+ fund_report.py出收益报告
- 查询时可直接 `SELECT * FROM nav_daily WHERE trade_date=CURDATE()` 获取当日数据

### market_daily 关键字段

```sql
trade_date, index_name, index_code,
close_price, daily_return, open_price, high, low, prev_close,
price_pattern                                   -- 价格行为形态
```

## Pipeline 脚本 V2（全功能版）

**路径**：`~/.hermes/scripts/fund_daily_pipeline_v2.py`
**运行**：`~/.hermes/venv-fund/bin/python3 ~/.hermes/scripts/fund_daily_pipeline_v2.py`
**时机**：每天15:05收盘后（写入market_daily/etf_flow_daily/sector_flow_daily，跳过nav_daily）

### 功能清单

| 功能 | 说明 | 价值 |
|:--|:--|:--|
| ETF行情拉取 | 7只基金有对应ETF，拿到OHLC数据 | ✅ 完整形态判断 |
| 完整形态判断 | 高开高走/高开低走/冲高回落等9种 | ✅ 精细分析 |
| 均线系统 | MA5/MA10/MA20/MA60 | ✅ 趋势判断 |
| RSI指标 | 6日/12日RSI | ✅ 超买超卖 |
| MACD指标 | MACD线/信号线/柱状图 | ✅ 金叉死叉 |
| 趋势判断 | 上升/下降/震荡 | ✅ 顺势而为 |
| 支撑压力位 | 近20日高低点 | ✅ 买卖参考 |
| 止损止盈预警 | 亏损>8%/盈利>10%提醒 | ✅ 风险控制 |
| 关键位置预警 | RSI超买超卖/形态组合信号 | ✅ 及时提醒 |

### 基金→ETF映射

| 联接基金 | 对应ETF | 能拿OHLC |
|:--|:--|:--|
| 017470 科创芯片C | 588200 科创芯片ETF | ✅ |
| 011036 稀土C | 516150 稀土ETF | ✅ |
| 018345 机器人C | 562500 机器人ETF | ✅ |
| 004433 有色金属C | 512400 有色金属ETF | ✅ |
| 012738 创新药C | 159992 创新药ETF | ✅ |
| 011613 科创50C | 588000 科创50ETF | ✅ |
| 012863 电池主题C | 561910 电池ETF | ✅ |
| 025209 半导体智选C | 512480 半导体ETF | ✅ |
| 025422 浦银数字经济C | 159638 数字经济ETF | ✅ |
| 017811 东方AI | 512480 半导体ETF | ✅（08-28新增映射） |
| 018123 数字经济C | — 无对应 | ❌ 已卖出08-28 |

**⚠️ 新增ETF映射时，必须同步更新FUND_ETF_MAP和ETF_MAP两处！**
- `FUND_ETF_MAP`：Pipeline主流程用（ETF行情获取+形态判断）
- `ETF_MAP`：Pipeline末尾"额外"ETF实时价格保存用（供15:50复盘）

### 流程（Pipeline V2 共13步）

```
[1/6] 拉取市场指数（新浪） → 8个指数的OHLC+涨跌+形态
[2/6] 拉取ETF行情（新浪） → 7只ETF的OHLC+形态
[3/6] 拉取基金净值（天天基金） → 11只基金的净值+计算所有技术指标
[4/6] 拉取行业板块（新浪资金流向） → 板块净流入TOP30（替代东财，避免限流）
[5/6] 写入MySQL（nav_daily + market_daily + sector_return_daily）
[6/6] 生成预警 + Market Snapshot
[7/7] 板块轮动分析
[8/8] 信号胜率统计
[9/9] 资金流向入库（sector_flow_daily + north_flow_daily）
[10/11] 融资融券+ETF申赎入库（margin_trading_daily + etf_flow_daily）
[11/11] 信号共振计算（signal_resonance，6信号源综合判断）
[额外] ETF实时价格保存（供15:50复盘使用）
[12/12] 持仓收益计算（C类手续费+到手金额）
[13/13] 新闻采集入库（东财7x24快讯 → events表，自动分类行业/方向/强度）
```

### 计算指标

#### 技术指标
- **均线**：MA5/MA10/MA20/MA60
- **RSI**：6日/12日RSI
- **MACD**：MACD线/信号线/柱状图
- **趋势**：上升/下降/震荡
- **支撑压力位**：近20日高低点

#### 形态判断（优先用ETF OHLC）
```
1. 拉取ETF实时行情（开盘价、最高价、最低价、收盘价）
2. 用ETF的OHLC判断形态：
   - 高开高走：开盘>昨收 且 收盘>开盘
   - 高开低走：开盘>昨收 且 收盘<开盘
   - 低开高走：开盘<昨收 且 收盘>开盘
   - 低开低走：开盘<昨收 且 收盘<开盘
   - 冲高回落：最高>昨收+1% 且 收盘<最高-0.5%
   - 探底回升：最低<昨收-1% 且 收盘>最低+0.5%
   - 大涨：涨幅>2%
   - 大跌：跌幅>2%
   - 横盘：涨跌幅<0.3%
3. 无ETF的基金用净值简化判断
```

### 预警规则

#### 止损止盈预警
- 亏损>8% → 🔴 止损预警
- 盈利>10% → 🟢 止盈预警

#### 关键位置预警
- RSI>70 → ⚠️ 超买预警
- RSI<30 → 💡 超卖预警
- 上升趋势+冲高回落 → ⚠️ 见顶预警
- 下降趋势+探底回升 → 💡 见底预警

### price_pattern 使用指南（场外基金）

**核心限制：** 天天基金pingzhongdata只返回净值，没有真正的OHLC数据。场外基金只能收盘按净值交易，盘中形态对操作无直接影响。

**场外基金的OHLC说明：**
- 开盘价 → 没有（只有净值=收盘价）
- 最高价 → 没有
- 最低价 → 没有
- 收盘价 = 净值 ✅

**当前简化判断逻辑：**
```python
if daily_return > 2%: 大涨
elif daily_return < -2%: 大跌
elif abs(daily_return) < 0.3%: 横盘
else: 小涨/小跌
```

#### 7种形态详解（场外基金适用版）

| 形态 | 定义 | 信号 | 对操作的影响 |
|:--|:--|:--|:--|
| **大涨（>2%）** | 当日涨幅超2% | 强势延续 | ⚠️ 追高风险大，等回调再买 |
| **大跌（<-2%）** | 当日跌幅超2% | 弱势 | 🤔 可能是机会，但要等企稳 |
| **冲高回落** | 盘中涨很多但收盘跌回 | 上方抛压重 | ⚠️ 警惕见顶，别追高 |
| **探底回升** | 盘中跌很多但收盘拉回 | 下方有支撑 | ✅ 关注见底信号 |
| **横盘（<0.3%）** | 涨跌幅极小 | 没方向 | ⏸️ 观望，等突破 |
| **小涨（0.3%~2%）** | 温和上涨 | 偏强 | 持有观察 |
| **小跌（-2%~-0.3%）** | 温和下跌 | 偏弱 | 持有观察 |

#### 位置+形态组合判断（买卖决策参考）

**这是核心：形态单独看意义有限，结合位置才有效。**

| 位置 | 形态 | 信号 | 操作建议 |
|:--|:--|:--|:--|
| **高位（>80%）** | 冲高回落/大跌 | 🔴 见顶信号 | 卖出/减仓 |
| **高位（>80%）** | 大涨 | 🟡 可能最后冲刺 | 准备止盈 |
| **低位（<20%）** | 探底回升/小涨 | 🟢 见底信号 | 关注买入 |
| **低位（<20%）** | 大跌 | 🟡 可能还没跌完 | 等企稳再买 |
| **中位（20%~80%）** | 大跌 | 🟡 可能是洗盘 | 等2天确认 |
| **中位（20%~80%）** | 大涨 | 🟡 可能是假突破 | 等回调确认 |
| **中位（20%~80%）** | 横盘 | ⏸️ 等方向 | 观望 |

#### 买入时自动记录规则

当用户说"买了XXX"时，记录：
1. 买入当天的 `price_pattern`
2. 买入当天的 `position_label`
3. 后续追踪：买入点位是否合理

**示例：** 用户08-21买入017470
- 当天price_pattern = 横盘（+0.12%）
- 当天position_label = 中位
- 结论：中位横盘买入，中性信号，不算差

#### 每天复盘自动分析

10只基金的price_pattern + position_label组合，每天收盘后自动判断：
- 哪些在高位冲高回落 → 提醒风险
- 哪些在低位探底回升 → 提醒机会
- 哪些连跌3天+低位 → 可能超卖

### 关注基金列表（动态，以trades表为准）

**⚠️ 以下列表为快照（08-28），实际持仓以trades表`trade_status='持有'`为准。**

当前持有5只 + 观察3只：

| 代码 | 名称 | 领域 | 状态 |
|:--|:--|:--|:--|
| 017470 | 嘉实科创芯片C | 芯片/半导体 | 持有 |
| 017811 | 东方人工智能C | AI | 持有 |
| 011036 | 嘉实稀土产业C | 稀土 | 持有 |
| 025209 | 永赢半导体智选C | 半导体 | 持有（08-27买入） |
| 025422 | 浦银数字经济C | 数字经济/CPO | 持有（08-27买入） |
| 004433 | 南方有色金属C | 有色金属 | 观察 |
| 012738 | 广发创新药C | 创新药/CXO | 观察 |
| 011613 | 华夏科创50C | 科创50指数 | 观察 |

**已卖出：** 018345（08-28卖出）、018123（08-28卖出）、008586（与017811重叠）、017102（与025422重叠）

## Market Snapshot 格式

```markdown
# Market Snapshot YYYY-MM-DD

## 大盘概况
- 上证指数: XXXX (+X.XX%) 形态
- ...

## 行业板块TOP10
- 半导体: +X.X%
- ...

## 关注行业
（半导体/芯片/CPO/AI/机器人/创新药/稀土/有色金属/黄金）

## 关注基金
| 代码 | 名称 | 净值 | 今日 | 3日 | 5日 | 回撤 | 连涨/跌 | 位置 |
```

### Phase 10 ✅ 已完成（08-28）
**自进化闭环 + 三条学习线 + 宏观感知**

新增3个核心表：
- ✅ predictions表 — AI预测记录（预测→验证→教训）
- ✅ improvement_log表 — 结构化改进清单（类别/影响/措施/状态）
- ✅ monthly_stats表 — 月度统计（正确率/错误模式/规则更新）
- ✅ kol_tracking表 — KOL跟踪记录（推荐→验证→可信度）
- ✅ trades表新增analysis_scope字段 — JSON格式，记录买入时分析覆盖维度（催化剂/宏观/位置/时机）
- ✅ trades表新增user_reasoning字段 — 用户操作的判断依据

新增文件：
- ✅ `~/user_files/documents/宏观事件日历.md` — FOMC/CPI/财报/政策事件日历
- ✅ `~/.hermes/scripts/macro_calendar_update.py` — 自动从美联储官网拉取FOMC日期

**三条独立学习线：**

| 线 | 谁的 | 数据表 | 验证时机 |
|:--|:--|:--|:--|
| 我的预测 | AI | predictions + improvement_log | 15:50每日验证 |
| 用户操作 | 用户 | trades.user_reasoning | 15:50每日验证 |
| KOL跟踪 | 老道 | kol_tracking | 有推荐时验证 |

**自进化闭环：**
```
14:00预测 → 写入predictions（accuracy=pending）
15:50验证 → 更新predictions + 写入improvement_log
月底统计 → 读取predictions+improvement_log → 写入monthly_stats
月度调优 → 根据统计结果修改skill/prompt规则
下个月 → 执行新规则 → 重复
```

### 🔴 P0：predictions表缺少自动化验证（09-02发现）

**问题：** predictions表（14:00扫描写入）的验证列（actual_result/actual_direction/actual_return_pct/is_correct/verified_at）从未被任何cron job自动填充。只有daily_predictions表有22:45的验证cron job。

**根因：** Phase 10设计了predictions表的自进化闭环，但从未创建对应的验证cron job。22:45的'每日预测验证'任务只处理daily_predictions（按target_date=CURDATE()匹配NAV），不处理predictions表。

**验证逻辑（predictions表）：**
```python
# 按time_horizon计算可验证日期
from datetime import timedelta
if '1d' in time_horizon:
    verify_after = prediction_date + timedelta(days=1)
elif '3d' in time_horizon:
    verify_after = prediction_date + timedelta(days=3)
elif '5d' in time_horizon:
    verify_after = prediction_date + timedelta(days=5)

# 当前日期 >= verify_after 时可验证
# 验证依据：
# - direction类型：对比actual_direction与预测方向
# - event_impact类型：检查事件是否确实发生了预期影响
# - 范围预测：检查实际值是否在预测区间内
```

**验证结果统计（09-02手动验证37条后）：**
- 5d预测准确率100%（20/20）— 周度方向预测很准
- 1d预测准确率62.5%（10/16）— 日内预测偏差较大
- 3d预测准确率40%（4/10）— 最差，中期预测不可靠
- event_impact准确率83.3%（10/12）— 事件影响判断较强
- direction准确率73.3%（22/30）

**修复方案：** 需要创建专门的predictions验证cron job，或扩展现有22:45任务覆盖predictions表。

**宏观感知三层体系：**
```
Layer 1：日历预知（提前1-4周）→ ~/user_files/documents/宏观事件日历.md
Layer 2：快讯突发（实时）→ 东财7x24快讯
Layer 3：盘面反推（当天）→ 板块异常异动反推未知事件
```

**数据库查询：**
```sql
-- 预测正确率
SELECT accuracy, COUNT(*) FROM predictions WHERE accuracy != 'pending' GROUP BY accuracy;

-- 错误模式
SELECT category, COUNT(*) FROM improvement_log GROUP BY category ORDER BY COUNT(*) DESC;

-- 月度统计
SELECT * FROM monthly_stats ORDER BY month DESC;
```

## 与现有skill的关系

| 现有skill | 关系 |
|:--|:--|
| `fund-swing-trading` | **策略执行层**，规则不变。14:00扫描照常运行，但后续可读Snapshot替代部分实时拉取 |
| `fund-full-analysis` | **单基金深析**，流程不变。后续可从MySQL读基金档案，减少重复API调用 |
| `fund-strategy-backtesting` | **策略回测**，后续回测结果可入库积累 |
| `fund-investment-analysis` | **事件→持仓映射**，后续事件可入库，支持"类似事件后T+N"查询 |
| `fund-quarterly-report` | **季报抓取**，不变 |

## Phase 路线图

### Phase 1 ✅ 已完成（08-25）
- MySQL库+6张表（funds/nav_daily/market_daily/events/signals/trades）
- Pipeline脚本（nav_daily + market_daily入库 + Snapshot生成）
- 首次运行验证通过
- 08-26：回填10只基金63天历史净值（630条），trades表写入5条真实交易，signals表写入1条老道信号
- 基金列表从15只精简为10只（剔除重叠品种）

### Phase 2 ✅ 已完成（08-26）
- ✅ 老道每次发操作 → 写入 `signals` 表（08-21老道信号已入库）
- ✅ 用户每次买卖 → 写入 `trades` 表（5笔交易已入库）
- ✅ cron任务每天自动算信号T+N收益（Pipeline自动计算）

### Phase 3 ✅ 已完成（08-26）
- ✅ nav_daily已积累63天数据（08-26回填），满足30-60天门槛
- ✅ 完整形态判断（ETF OHLC → 9种形态）
- ✅ 技术指标（MA/RSI/MACD/趋势/支撑压力位）
- ✅ 集成到Pipeline V2

### Phase 4 ✅ 已完成（08-26）
- ✅ 交易结果自动回写trades表
- ✅ 板块轮动分析（领涨/领跌/关注板块）
- ✅ 信号胜率统计（各信号源准确率）
- ✅ 每月复盘报告（自动生成）
- ✅ 止损止盈预警（亏损>8%/盈利>10%）
- ✅ 关键位置预警（RSI超买超卖/形态组合）

### Phase 5 ✅ 已完成（08-26）
- ✅ 资金流向分析（主力/散户/北向）
- ✅ 14:00盘中推送资金流向
- ✅ 15:30资金流向历史入库
- ✅ 基金→行业板块映射
- ✅ 资金流向信号判断（主力吸筹/出货）
- ✅ 北向资金入库（东财datacenter API，pageSize>=20）

### Phase 6 ✅ 已完成（08-26）
- ✅ 信号共振分析（6个信号源：RSI/MACD/趋势/形态/位置/资金）
- ✅ 14:00扫描集成信号共振展示
- ✅ 15:30 Pipeline入库signal_resonance表
- ✅ 融资融券数据（用板块资金流向近似，展示时标注"板块资金情绪"）
- ✅ ETF申赎数据（用ETF行情近似，展示时标注"ETF资金动向"）
- ✅ 14:40尾盘确认（加script拉实时数据）
- ✅ 15:50收盘复盘（读15:30入库数据）
- ✅ AI推荐记录（14:40确认后写入ai_recommendations）
- ✅ 复盘逻辑修复（复盘上一个交易日，三方操作对比）
- ✅ 胜率统计（AI/老道/用户各自的准确率）
- ✅ 21:00最终净值更新（官方净值+持仓收益报告）
- ✅ C类基金手续费计算（7天内1.5%，7天后0%）
- ✅ 北向资金入库+14:00展示（东财datacenter API，pageSize>=20）
- ✅ 板块涨幅改用新浪API（替代东财push2，避免限流）
- ✅ 14:00扫描资金流向完整展示（7个模块：流入/流出/持仓信号/北向/共振/板块情绪/ETF动向）

### Phase 7 ✅ 已完成（08-26）
- ✅ 新闻采集入库（fund_event_collect.py集成到Pipeline）
- ✅ 东财7x24快讯自动分类（行业/事件类型/方向/强度）
- ✅ events表今日入库（50条/天）
- ✅ Pipeline从11步扩展到13步

### Phase 7.1 ✅ 已完成（08-27）
- ✅ 新闻分层过滤：50条→10-15条（只保留持仓/观察池/行业/市场大事相关）
- ✅ 去重逻辑：同标题不重复入库
- ✅ 重大事件（强度≥4）自动同步catalyst_analysis表
- ✅ 排除无关关键词（苹果/三星/LG/韩国央行等）
- ✅ FUND_ETF_MAP新增025209→512480、025422→159638
- ✅ 腾讯API替代新浪ETF行情（新浪08-27起被封）

### Phase 7.2 ✅ 已完成（08-27）
- ✅ 创建fund_common.py共享模块（单一数据源）
- ✅ 扩展funds表（etf_code, sectors, is_watchlist, watchlist_reason, watchlist_conditions）
- ✅ 创建decisions表（决策日志）
- ✅ 创建strategy_backtest表（回测记录）
- ✅ fund_daily_pipeline_v2.py：3处硬编码全部替换为从fund_common.py动态读取
- ✅ fund_scan_data.py：CODES和FUND_SECTOR_MAP替换为从fund_common.py动态读取
- ✅ fund_event_collect.py：HELD_FUNDS和WATCHLIST_FUNDS替换为从fund_common.py动态读取
- ✅ 修复pymysql Decimal类型JSON序列化问题
- ✅ 修复get_holdings()缺少nav_price字段导致除零错误
- ✅ 完整测试验证（fund_common.py/fund_report.py/fund_daily_pipeline_v2.py均通过）

### Phase 8 ✅ 已完成（08-27 深夜）
**系统架构升级：从"能用"到"好用+可靠"**

新增4个核心模块：
- ✅ fund_error_handler.py — 统一异常处理（重试3次+降级+日志记录+熔断器）
- ✅ fund_signal_engine.py — 信号评分引擎（5维度打分0-10分，7分以上才推送）
- ✅ fund_portfolio_tracker.py — 收益追踪（每日记录+最大回撤+夏普比率+胜率）
- ✅ fund_backtest.py — 策略回测引擎（历史胜率+盈亏比+连胜连亏）

数据库新增：
- ✅ portfolio_daily表（每日收益+风险指标）
- ✅ strategy_backtest表扩展（win_streak/lose_streak/avg_hold_days/profit_factor）

**定时任务新增：**
- ✅ 14:05 基金信号评分（fund_signal_task.py）
- ✅ 22:50 每日收益记录（fund_portfolio_task.py，no_agent模式）

文档：
- ✅ ~/.hermes/scripts/README.md（完整系统文档）

**信号评分算法：**
| 维度 | 权重 | 评分规则 |
|:--|:--:|:--|
| RSI位置 | 2分 | 超卖<30=2分，30-50=1分，>50=0分 |
| 趋势确认 | 2分 | 上升=2分，震荡=1分，下降=0分 |
| 形态确认 | 2分 | 探底回升=2分，横盘=1分，冲高回落=0分 |
| 位置标签 | 2分 | 底部=2分，中部=1分，顶部=0分 |
| 资金流向 | 2分 | 大幅流入>1亿=2分，小幅流入=1分，流出=0分 |

**系统评分：从75分升级到90分**

### Phase 9 ✅ 已完成（08-27 深夜修复）
**fund_report.py收益计算修正**

**问题：** fund_report.py使用错误公式计算总资产：
- 错误：资产 = 总投入 + 总投入 × 今日涨跌幅（只算今天，忽略历史）
- 正确：市值 = 各基金的（当前净值 / 买入净值 × 投入金额）

**修复内容：**
- ✅ fund_report.py：正确计算每只基金的市值（份额×净值）
- ✅ fund_report.py：今天买入的基金市值=投入金额（明天出净值）
- ✅ fund_report.py：get_holdings()添加nav_price字段
- ✅ fund_portfolio_tracker.py：正确处理今天买入的基金（T+1逻辑）

**验证结果：**
```
fund_report.py: 市值3765元 ✅
fund_portfolio_tracker.py: 总市值3765元 ✅
两者数据一致
```

**关键修正：**
| 基金 | 本金 | 市值计算 | 结果 |
|:--|:--|:--|:--|
| 017470 | 1000元 | 1000/2.8526×2.9202 | 1023.70元 ✅ |
| 025209 | 500元 | 今天买入，明天出净值 | 500元 ✅ |
| 025422 | 500元 | 今天买入，明天出净值 | 500元 ✅ |

**今日收益正确公式（最终版）：**
```
今日收益 = 今日市值 - 昨日市值
今日市值 = 份额 × 今日净值
昨日市值 = 份额 × 昨日净值
```

**错误公式（不要用）：**
```
❌ 今日收益 = 本金 × 今日涨跌幅%  （这只是今日涨跌的收益，不是真实收益）
❌ 总资产 = 总投入 + 总投入 × 今日涨跌幅%  （忽略了历史涨跌）
```

**验证：**
```
017470: 昨日市值981元 → 今日市值1024元 → 今日收益+43元 ✅
025209: 今天买入 → 明日出净值 → 今日收益=0 ✅
总计: 昨日3669元 → 今日3765元 → 今日收益+96元 ✅
```

**fund_portfolio_tracker.py夏普比率修复（08-27）：**
- 问题：数据不足时（只有1-2天），std_dev极小导致夏普比率计算出999.99
- 修复：当std_dev < 0.001时返回0
```python
if std_dev < 0.001:
    return 0
```

## 资金流向分析系统

### 双模式架构（核心设计）

**盘中14:00：实时展示，辅助当天决策**
**收盘15:30：历史入库，积累数据做分析**

```
14:00  实时拉取 → 展示资金信号 → 辅助14:00-14:30操作决策
   ↓
15:30  收盘拉取 → 写入数据库 → 积累历史数据
   ↓
积累30天后 → 趋势分析
积累60天后 → 信号验证
积累90天后 → 策略回测
```

**为什么这样设计：**
- 资金流向盘中就能拿到，14:00展示可以辅助当天操作
- 但盘中数据不入库，因为收盘后数据更完整
- 收盘后入库，积累历史数据，支持趋势分析和回测

### 新闻采集系统（Phase 7.1 优化版）

**数据源：** 东财7x24快讯API
**入库表：** events
**调用方式：** 15:30 Pipeline自动调用fund_event_collect.py
**优化目标：** 50条→10-15条，只保留与持仓/观察池/行业/市场大事相关的新闻

**分层过滤规则：**

| 层级 | 内容 | 入库条件 | 优先级 |
|:--|:--|:--|:--|
| ①持仓新闻 | 当前持仓基金相关 | 强度≥3 + 行业匹配 | 🔴高 |
| ②观察池新闻 | 观察列表里的基金 | 强度≥3 + 行业匹配 | 🟡中 |
| ③行业新闻 | 持仓行业重大事件 | 强度≥3 + 行业匹配 | 🟡中 |
| ④市场大事 | 美联储/政策/黑天鹅 | 强度≥4 或关键词匹配 | 🟢低 |

**排除关键词：** 苹果/三星/LG/韩国央行/日本央行（与持仓无关的市场大事）

**强度判断规则：**
- 强度4：政策/突发类事件
- 强度3：财报/产业类事件 + 关键词命中≥3
- 强度2：默认值

**重大事件自动同步：** 强度≥4的事件自动写入catalyst_analysis表

**典型输出：**
```
[Event采集] 2026-08-27
  今日快讯: 50条（总50条）
  入库: 16条 | 跳过: 34条（去重+无关）
  分类: 持仓4 | 观察池6 | 行业0 | 市场6
```

**行业关键词映射（扩展版12个行业）：**
```python
INDUSTRY_KEYWORDS = {
    '半导体': ['半导体', '芯片', '晶圆', '光刻', 'ASML', '中芯', '北方华创', '中微公司', '拓荆', '华海清科', '集成电路', '封装'],
    'AI': ['人工智能', 'AI', '大模型', '算力', 'GPU', '英伟达', 'NVIDIA', 'DeepSeek', 'ChatGPT', 'Transformer', '智能体', 'AIGC'],
    'CPO': ['CPO', '光模块', '光通信', '中际旭创', '新易盛', '天孚通信', 'Coherent', 'Lumentum'],
    '机器人': ['机器人', '人形机器人', '宇树', '优必选', '特斯拉机器人', 'Optimus', '具身智能'],
    '创新药': ['创新药', 'CRO', '医药', 'FDA', '临床试验', '恒瑞', '药明康德', '生物制品'],
    '稀土': ['稀土', '出口管制', '战略矿产', '镓', '锗', '商务部管制'],
    '有色金属': ['有色金属', '铜', '铝', '锂', '钴', '镍', '大宗商品', '矿产', '矿业'],
    '黄金': ['黄金', '金价', '避险', '央行购金', '美联储', '降息'],
    '电池': ['电池', '锂电', '储能', '宁德时代', '比亚迪电池', '锂矿'],
    '电网': ['电网', '特高压', '电力', '十五五', '新能源', '光伏', '风电'],
    '券商': ['券商', '证券', '牛市旗手', '金融'],
    '数字经济': ['数字经济', '软件', '信息技术', '云计算', '大数据'],
}
```

**方向判断优化（上下文感知）：**
```python
# 先检查利空上下文（避免"超预期加息"误判为利好）
bearish_context = ['加息', '收紧', '缩表', '上调利率', '超预期加息']
if any(kw in title for kw in bearish_context):
    direction = '利空'
else:
    # 再检查利好/利空关键词
    bullish_kw = ['利好', '上涨', '突破', '创新高', '超预期增长', '大涨', '涨停', '爆发', '领涨']
    bearish_kw = ['利空', '下跌', '暴跌', '跌停', '不及预期', '下滑', '风险', '预警', '蒸发']
```

**持仓相关性自动匹配：**
```python
FUND_INDUSTRY_MAP = {
    '017470': ['半导体', '芯片'],      '017811': ['AI', '人工智能'],
    '011036': ['有色金属', '稀土'],    '018345': ['机器人', '具身智能'],
    '018123': ['数字经济', '软件'],    '004433': ['有色金属'],
    '012738': ['创新药', '医药'],      '025422': ['数字经济', 'CPO'],
    '011613': ['半导体', '芯片'],      '025209': ['半导体', '芯片'],
    '012863': ['电池', '储能'],
}
```

**events表结构：**
```sql
events
  id, event_time, event_type, title, description,
  industry, direction, intensity, duration,
  related_funds, market_reaction,
  t1_return, t3_return, t5_return,
  similar_events, source, verified
```

**典型输出：**
```
[Event采集] 2026-08-26
  今日快讯: 50条（总50条）
  写入50条结构化事件
  行业分布: {'其他': 30, 'AI': 6, '电网': 4, '机器人': 4, '电池': 2}
  新闻入库: 50条
```

### 数据表

```sql
-- 板块资金流向（每日）
sector_flow_daily
  trade_date, sector_name, main_inflow, main_outflow, main_netflow,
  retail_inflow, retail_outflow, retail_netflow

-- 北向资金（每日）
north_flow_daily
  trade_date, sh_connect_netflow, sz_connect_netflow, total_netflow, is_inflow
```

### 数据来源

**新浪行业板块资金流向接口（已验证可用）：**
```
https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk?page=1&num=50&sort=netamount&asc=0&fenlei=2
```
- `fenlei=1` → 概念板块
- `fenlei=2` → 行业板块（用这个）
- 返回字段：name, netamount（净流入，单位元）, inamount, outamount

**注意：东财push2接口经常限流，已废弃。板块涨幅改用新浪资金流向净流入排名。**

### 基金→行业板块映射

```python
FUND_SECTOR_MAP = {
    '017470': ['电子', '半导体', '芯片'],
    '017811': ['计算机', '软件', '信息技术'],
    '011036': ['有色金属', '稀土', '金属'],
    '018345': ['机械', '设备', '仪器'],
    '018123': ['软件', '信息技术', '计算机'],
    '004433': ['有色金属', '金属', '矿采'],
    '012738': ['医药', '生物制品', '制药'],
    '025422': ['通信', '电子', '计算机'],
    '011613': ['电子', '计算机', '半导体'],
    '025209': ['电子', '半导体', '芯片'],
    '012863': ['电气机械', '电池', '新能源'],
}
```

### 资金信号判断规则

| 主力行为 | 信号 | 操作建议 |
|:--|:--|:--|
| 主力净流入 > 1亿 | 🟢 主力大幅流入 | 关注买入 |
| 主力净流入 > 0 | 🟢 主力流入 | 持有 |
| 主力净流入 < -1亿 | 🔴 主力大幅流出 | 考虑卖出 |
| 主力净流入 < 0 | ⚠️ 主力流出 | 观望 |

### 入库逻辑（15:30 Pipeline执行）

```python
# 在Pipeline V2末尾执行：
flow_url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk?page=1&num=50&sort=netamount&asc=0&fenlei=2"
flow_data = json.loads(flow_raw)

# 新建独立数据库连接（避免与主流程冲突）
flow_conn = pymysql.connect(**DB_CONFIG)
flow_cursor = flow_conn.cursor()

# 逐条写入
for item in flow_data:
    sector_name = item.get('name', '')
    netamount = float(item.get('netamount', 0)) / 100000000
    retail_netflow = -netamount  # 简化处理
    
    flow_cursor.execute(flow_sql, (today, sector_name, ...))

flow_conn.commit()
flow_conn.close()
```

**坑点：必须新建独立数据库连接，不能复用Pipeline主流程的cursor，否则会冲突。**

### 14:00盘中展示（fund_scan_data.py）

14:00的扫描脚本已集成**完整资金流向分析**，拉取实时数据并展示7个模块：

| 模块 | 数据源 | 说明 |
|:--|:--|:--|
| 💰 主力流入TOP5 | 新浪MoneyFlow | 板块主力资金净流入排名 |
| 💰 主力流出 | 新浪MoneyFlow | 板块主力资金净流出（无流出时显示"无板块净流出"） |
| 💰 持仓资金信号 | 新浪MoneyFlow | 11只基金对应板块的资金信号 |
| 🏦 北向资金 | 东财数据中心 | 沪深港通净流入+近期趋势（从MySQL读取） |
| 🎯 信号共振 | MySQL | 6维度信号综合判断（RSI/MACD/趋势/形态/位置/资金） |
| 📊 板块资金情绪 | 新浪MoneyFlow | TOP5板块资金流入/流出（近似融资融券） |
| 📈 ETF资金动向 | 新浪行情 | 7只ETF涨跌近似申赎方向 |

**资金流向输出格式：**
```
【主力流入TOP5】
  ✅ 有色金属冶炼和压: +68.6亿
  ✅ 计算机应用服务业: +66.3亿
  ...
【主力流出】无板块净流出
【你的持仓资金信号】
  017470 电子: 🟢 主力大幅流入 (+54.1亿)
  ...

【🏦 北向资金】
  最新: 2026-08-26 净流入 0.05亿 🟢 外资看多
  近期趋势:
    2026-08-26: +0.05亿 (流入)
    2026-08-25: -0.66亿 (流出)
```

**注意：** fund_scan_data.py的print语句必须在脚本最后一行，否则新增的代码不会输出。

### 后续应用场景

| 积累时间 | 能做什么 |
|:--|:--|
| 7天 | 看资金流向周趋势 |
| 30天 | 分析"连续流入N天后表现" |
| 60天 | 验证"主力流入+RSI超卖"胜率 |
| 90天 | 回测"跟着主力操作"策略 |

### 资金流向数据完整性

**用户问过：** "我们有全市场按投资者类型分（机构/主力/大户/散户）的数据吗？"

**结论：** 不需要。我们的**板块资金流向**更适合基金投资场景：
- 知道钱流入哪个板块 → 对应持仓基金
- 有色金属+68亿 → 011036稀土、004433有色金属受益
- 全市场按投资者类型分的（机构/主力/大户/散户）更适合看大盘情绪，选基金没用

**当前资金流向模块（14:00扫描展示7个）：**
1. 主力流入TOP5（板块）
2. 主力流出（板块）
3. 持仓资金信号（基金→板块映射）
4. 北向资金（东财datacenter）
5. 信号共振（6维度）
6. 板块资金情绪（近似融资融券）
7. ETF资金动向（近似申赎方向）

## Phase 2 实操：回填历史交易

当用户说"把我的持仓填进去"时，需要确认以下信息再写入：

### 确认清单（必须逐项确认）

| 字段 | 必填 | 说明 |
|:--|:--|:--|
| `fund_code` | ✅ | 基金代码（6位） |
| `trade_date` | ✅ | 买入日期（⚠️ 必须用 `date` 命令确认星期几，不要心算） |
| `direction` | ✅ | 买入=buy / 卖出=sell |
| `amount` | ✅ | 买入金额（元） |
| `nav_price` | ⚠️ 可选 | 买入净值（如有） |
| `signal_source` | ⚠️ 可选 | 信号来源：老道 / Hermes / 用户自主 |
| `reason` | ⚠️ 可选 | 买入理由 |

### 写入 trades 表的SQL模板

```sql
INSERT INTO trades (trade_date, fund_code, fund_name, direction, amount, nav_price, signal_source, reason, trade_status)
VALUES ('YYYY-MM-DD', 'XXXXXX', '基金名称', 'buy', 金额, 净值, '信号来源', '理由', 'open');
```

### 写入 signals 表（如果信号来自老道）

```sql
INSERT INTO signals (signal_date, source, fund_code, direction, confidence, nav_at_signal, reason)
VALUES ('YYYY-MM-DD', '老道', 'XXXXXX', 'buy', 0.7, 净值, '跟单理由');
```

### 回填流程

1. **确认日期**：用 `date` 命令验证交易日期是星期几（用户可能记错）
2. **拉取净值**：用 `fund_query.py nav XXXXXX` 或 pingzhongdata 获取买入日净值
3. **写入 trades**：执行INSERT
4. **写入 signals**（如有）：如果信号来自老道，同时写入signals表
5. **确认写入**：`SELECT * FROM trades ORDER BY id DESC LIMIT 5;`

### 批量回填历史净值

当需要一次性补充多天净值数据时，使用 `references/backfill_nav.py`：
```bash
~/.hermes/venv-fund/bin/python3 ~/.hermes/skills/personal/fund-research-system/references/backfill_nav.py 90
```
脚本会自动从funds表读取活跃基金列表，拉取最近N天净值，计算所有技术指标后写入nav_daily。

## 脚本清单

| 脚本 | 路径 | 功能 | 运行时间 |
|:--|:--|:--|:--|
| fund_common.py | ~/.hermes/scripts/ | 共享模块（单一数据源，所有脚本从这里读持仓/基金信息/ETF映射） | 被其他脚本import |
| fund_error_handler.py | ~/.hermes/scripts/ | 统一异常处理（重试/降级/日志/熔断器） | 被其他脚本import |
| fund_signal_engine.py | ~/.hermes/scripts/ | 信号评分引擎（5维度0-10分，7分以上推送） | 14:05定时任务 |
| fund_portfolio_tracker.py | ~/.hermes/scripts/ | 收益追踪（每日记录+回撤+夏普+胜率） | 22:35定时任务 |
| fund_backtest.py | ~/.hermes/scripts/ | 策略回测引擎（胜率/盈亏比/最大回撤） | 手动运行 |
| fund_signal_task.py | ~/.hermes/scripts/ | 信号评分定时任务包装 | 14:05 cron |
| fund_portfolio_task.py | ~/.hermes/scripts/ | 收益记录定时任务包装 | 22:50 cron（no_agent） |
| fund_daily_pipeline_v2.py | ~/.hermes/scripts/ | 每日Pipeline（全功能版，13步） | 15:05/22:30（ETF数据+板块+新闻） |
| fund_nav_update.py | ~/.hermes/scripts/ | 基金净值更新（full/fallback两种模式） | 22:00（full）/22:30（fallback兜底） |
| fund_backfill_sell_nav.py | ~/.hermes/scripts/ | 交易净值回填（actual_sell_nav/fee/hold_days） | 22:10（净值更新后自动回填） |
| fund_scan_data.py | ~/.hermes/scripts/ | 14:00盘中扫描+资金流向（7模块） | 14:00/14:40 |
| fund_event_collect.py | ~/.hermes/scripts/ | 新闻采集入库（东财7x24快讯→events表） | 15:30 Pipeline调用 |
| fund_signal_analysis.py | ~/.hermes/scripts/ | 信号共振分析（6信号源） | 手动/15:30 |
| fund_flow_analysis.py | ~/.hermes/scripts/ | 资金流向分析（独立） | 手动 |
| fund_sector_rotation.py | ~/.hermes/scripts/ | 板块轮动分析（独立） | 手动 |
| fund_signal_stats.py | ~/.hermes/scripts/ | 信号胜率统计（独立） | 手动 |
| fund_monthly_review.py | ~/.hermes/scripts/ | 每月复盘报告（独立） | 手动 |
| fund_daily_attribution.py | ~/.hermes/scripts/ | 涨跌归因分析（市场+持仓归因） | cron daily |

**定时任务配置参考：** `references/fund_cron_config.md`

**持仓收益计算参考：** `references/portfolio_profit_calculation.md`

## 定时任务：fund_daily_pipeline_v2.py 和 fund_scan_data.py 由cron自动运行，其他脚本可手动执行。

**定时任务配置参考：** `references/fund_cron_config.md`
**Cron优化方法论：** `references/cron-optimization-methodology.md`

**财经新闻抓取：** 海外市场/财报新闻可用curl从国内财经网站抓取（华尔街见闻/第一财经/证券时报/21世纪经济报道）。详见 `references/financial_news_sources.md`。

### 信号共振分析系统（Phase 6）

#### 6个信号源

| 信号源 | 数据来源 | 买入条件 | 卖出条件 |
|:--|:--|:--|:--|
| **RSI** | nav_daily.rsi_6 | <30 超卖 | >70 超买 |
| **MACD** | nav_daily.macd_histogram + macd_line vs signal_line | histogram>0 且 MACD>信号线 | histogram<0 且 MACD<信号线 |
| **趋势** | nav_daily.trend | 上升（MA20>MA60） | 下降（MA20<MA60） |
| **形态** | nav_daily.price_pattern | 探底回升/大涨 | 冲高回落/大跌 |
| **位置** | nav_daily.position_label | 低位 | 高位 |
| **资金** | sector_flow_daily.main_netflow | 主力净流入>0 | 主力净流入<0 |

#### 共振判断规则

```
买入信号数 ≥ 4 → 🟢🟢 强烈买入
买入信号数 ≥ 3 → 🟢 买入
卖出信号数 ≥ 4 → 🔴🔴 强烈卖出
卖出信号数 ≥ 3 → 🔴 卖出
其他            → ⚪ 观望
```

#### 两步确认机制（14:00发现 + 14:40确认）

**这是核心工作流：发现机会 → 确认机会 → 才操作**

```
14:00: 侦察兵 — 发现机会，给出操作建议
       ↓
14:40: 确认官 — 验证形态没变坏，确认可以操作
       ↓
15:00: 收盘 — 按净值成交
```

**14:00做什么：**
- 拉取实时行情+资金流向+信号共振
- 给出操作建议（买/卖/观望）

**14:40做什么：**
- 检查14:00的建议
- 如果14:00说"不动"→ 静默结束，不推送
- 如果14:00说"买"→ 拉实时行情确认形态没变坏
  - 形态没坏 → ✅ 确认执行
  - 形态变坏 → ⚠️ 取消/调整
- 扫东财7x24快讯，确认没有突发利空

**铁律：** 能辅助当天操作的信号必须在14:00-14:40之间推送，不能收盘后才推。

### 使用场景

**用户问"现在能不能买某只基金"时：**
1. 查nav_daily获取最新技术指标
2. 查sector_flow_daily获取资金流向
3. 计算6个信号源
4. 给出共振判断和操作建议

**每天收盘复盘时：**
1. 对5只持仓基金运行信号共振
2. 识别买入/卖出机会
3. 生成操作建议

### fund_signal_analysis.py 使用

```bash
~/.hermes/venv-fund/bin/python3 ~/.hermes/scripts/fund_signal_analysis.py
```

输出：持仓信号共振分析报告，包含每只基金的6个信号源判断和最终建议。

## 用户偏好

### 先讲"为什么"，再做

用户希望在实施任何功能前，先理解**为什么要做这个**、**对我们有什么用**、**怎么用**。不要直接跳到"我来做"。

**示例对话模式：**
1. 用户问"资金流向是什么"
2. 解释概念 + 对我们的价值 + 使用场景
3. 用户说"OK开始做"
4. 才开始实现

### 做之前先讨论方案

用户明确说"做之前我们想想还有没有可以优化和改进的地方"。不要用户一说做就开始写代码，先一起讨论方案，达成共识再动手。

### 不要只做一半就停

当用户说"全部吧"或"都做"时，必须全部做完，不能只做第一个就说完成了。用户会追问"你实现了哪几点，还差哪些没做的"。

**正确做法：**
1. 列出所有要做的功能
2. 逐个实现
3. 每个功能都验证
4. 最后统一汇报"全部X个功能已完成"

### 数据展示 vs 数据入库

**用户核心观点：** "建了表就应该入库"、"不入库的数据没价值"

**正确做法：**
- 盘中实时展示 → 辅助当天决策
- 收盘历史入库 → 积累数据做分析
- 两者缺一不可

**错误做法：**
- 只展示不入库 → 数据用完就没了

### 收益展示格式（用户明确要求）

**用户原话：** "并不关心买入价和当前价，这些我看了没什么意义，我只关心钱和涨幅"

**22:30收益报告必须包含的字段：**

| 字段 | 说明 | 示例 |
|:--|:--|:--|
| 基金 | 名称 | 芯片C |
| 今日涨跌 | 百分比 | +1.63% |
| 今日盈亏 | 实际¥金额 | 赚¥16.3 |
| 累计盈亏 | 实际¥金额 | 亏¥19 |
| 盈亏率 | 百分比 | -1.9% |

**收益报告完整模板：**
```
📊 今日收益报告

【收益明细】
| 基金 | 今日涨跌 | 今日盈亏 | 累计盈亏 | 盈亏率 |
|:--|:--|:--|:--|:--|
| 芯片C | +1.63% | 赚¥16.3 | 亏¥19 | -1.9% |
| 东方AI | +2.38% | 赚¥11.9 | 赚¥12 | +2.4% |
| ...

【今日合计】赚¥36.8

【持仓总额】
- 总投入: ¥2700
- 当前市值: ¥2669

【持有收益】亏¥31（-1.15%）
```

**禁止展示：** 买入价、当前价 — 用户不关心这些中间数据。

**必须包含：** 今日合计、持仓总额（总投入+当前市值）、持有收益（金额+百分比）

### 数据验证：用户质疑时实时拉取对比

当用户说"感觉数据不对"时，立即从API实时拉取最新数据对比：
```python
# 实时拉取天天基金净值
url = f'https://fund.eastmoney.com/pingzhongdata/{code}.js'
# 对比数据库中的值
```
常见原因：天天基金净值是陆续发布的，15:30入库的可能是T-1数据，21:00会更新为T日数据。
## MySQL Schema Discovery Pattern（08-27教训）

**核心原则：不要假设列名，先DESCRIBE确认。**

本次session踩了多个列名假设错误的坑：

| 错误假设 | 实际列名 | 表 |
|:--|:--|:--|
| `netamount` | `main_netflow` | sector_flow_daily |
| `signal_type` | `direction` | signals |
| `net_amount` | `main_netflow` | sector_flow_daily |

**标准流程（每次修改表结构或写新SQL时）：**
```bash
# 1. 先DESCRIBE确认列名
mysql -h 127.0.0.1 -P 3306 -u fund_admin -p'FundR2026!db' fund_research -e "DESCRIBE table_name;"

# 2. 再写SQL
SELECT actual_column_name FROM table_name WHERE ...;
```

**不要猜测列名，每次都要验证。**

## Signal Threshold Tuning（08-27教训）

**初始部署时，信号阈值要设低一些，否则永远没有信号。**

本次session的信号评分系统：
- 5个维度，每个0-2分，满分10分
- 初始阈值设为7分 → 所有基金评分2-4分，永远没有信号
- 降到5分 → 仍然没有信号（市场震荡期）
- 降到3分 + 放宽条件 → 才有信号产生

**建议初始配置：**
```python
HIGH_SCORE_THRESHOLD = 5  # 不要设太高
# 买入条件：score >= 3 AND (rsi < 40 OR position == '底部')
# 卖出条件：score <= 3 AND (rsi > 70 OR position == '顶部')
```

**调试方法：**
```python
# 打印所有基金的评分，观察分布
for h in holdings:
    indicators = engine.get_indicators(h['fund_code'])
    score = engine.calculate_score(h['fund_code'], indicators)
    print(f"{h['fund_code']}: score={score}, rsi={indicators.get('rsi_6')}, position={indicators.get('position_label')}")
```

## Historical Data Backfill for Technical Indicators（08-27新增）

**问题：** nav_daily表中rsi_6、trend、price_pattern、position_label字段大部分为NULL，导致回测和信号评分无法正常工作。

**解决方案：** 批量计算历史数据的技术指标。

**脚本：** `~/.hermes/scripts/fund_calculate_indicators.py`

**使用方法：**
```bash
~/.hermes/venv-fund/bin/python3 ~/.hermes/scripts/fund_calculate_indicators.py
```

**计算逻辑：**
- RSI(6)：相对强弱指数
- 趋势：MA5 vs MA10判断上升/下降/震荡
- 形态：近5日涨跌幅判断大涨/小涨/横盘/小跌/大跌
- 位置：当前价格在20日高低点中的位置（0-100%）

**验证：**
```sql
SELECT fund_code, trade_date, rsi_6, trend, price_pattern, position_label
FROM nav_daily 
WHERE fund_code = '017470'
ORDER BY trade_date DESC
LIMIT 10;
```

## Cumulative Return Curve Visualization（08-27新增）

**脚本：** `~/.hermes/scripts/fund_curve_generator.py`

**功能：**
- 从portfolio_daily表读取每日收益数据
- 生成JSON数据文件
- 生成HTML交互式图表（使用Chart.js）

**使用方法：**
```bash
~/.hermes/venv-fund/bin/python3 ~/.hermes/scripts/fund_curve_generator.py
```

**输出文件：**
- `~/user_files/documents/portfolio_curve.json` — 数据文件
- `~/user_files/documents/portfolio_curve.html` — 交互式图表

**图表包含：**
- 总市值变化曲线
- 累计收益率曲线
- 摘要统计（总天数、起始市值、当前市值、累计收益率、最大回撤）

## Sharpe Ratio Edge Cases（08-27教训）

**问题：** 当数据不足（只有1-2天）时，标准差极小，导致夏普比率计算出异常大的值（如999.99）。

**解决方案：** 当标准差小于阈值时，返回0。
```python
def calculate_sharpe_ratio(self, daily_returns, risk_free_rate=2.0):
    if len(daily_returns) < 2:
        return 0
    
    avg_return = sum(daily_returns) / len(daily_returns)
    variance = sum((r - avg_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std_dev = math.sqrt(variance)
    
    # 标准差太小，无法计算有意义的夏普比率
    if std_dev < 0.001:
        return 0
    
    daily_risk_free = risk_free_rate / 252
    sharpe = (avg_return - daily_risk_free) / std_dev * math.sqrt(252)
    return round(max(-999.99, min(999.99, sharpe)), 2)
```

**同样需要限制范围的字段：**
- sharpe_ratio: DECIMAL(5,2)，范围-999.99~999.99
- win_rate: DECIMAL(5,2)
- profit_factor: DECIMAL(5,2)

## 关联参考文件

- `references/scan-script-t1-architecture.md` — 14:00扫描脚本T+1架构：持仓/观察分离、净值累计逻辑、Cron Prompt行为约束
- `references/portfolio-sync-pitfall-2026-08-27.md` — 持仓数据同步陷阱：硬编码vs动态读取、T+1确认逻辑、验证清单
- `references/fund-calculation-rules-2026-08-27.md` — 基金计算规则：T+1规则、市值计算公式、今日收益计算、夏普比率修复
- `references/prediction-verification-workflow.md` — 预测验证工作流：predictions表验证逻辑、准确率统计、cron job覆盖缺口
- `references/cron-optimization-methodology.md` — Cron任务优化方法论：数据依赖分析、合并/拆分决策标准、no_agent降级判断、jobs.json调试方法
- `~/user_files/documents/宏观事件日历.md` — 全球宏观事件日历（FOMC/CPI/财报/政策），14:00扫描时读取

## 已知坑点

### 🔴 P0：加权平均成本计算（09-03 新增）

当基金有多次买入记录时，**市值计算必须使用加权平均成本**，而不是最后一条记录的买入价：

```python
# ❌ 错误：使用最后一条记录的买入价
buy_nav = last_record.nav_price  # 如017470: 2.8242
shares = total_amount / buy_nav
current_value = current_nav * shares

# ✅ 正确：使用加权平均成本
avg_cost = sum(amount * nav_price) / sum(amount)  # 如017470: 2.8460
shares = total_amount / avg_cost
current_value = current_nav * shares
```

**案例**：017470分批买入（1000元@2.8526 + 300元@2.8242），使用最后买入价2.8242计算市值1278.55元，使用加权均价2.8460计算市值1268.74元，差异9.81元。

**修复**：fund_common.py的get_holdings()已改为计算加权平均成本：
```sql
SELECT 
    t.fund_code,
    SUM(amount) AS total_amount,
    SUM(amount * nav_price) / SUM(amount) as avg_cost
FROM trades t
WHERE direction = '买入' AND trade_status = '持有'
GROUP BY fund_code
```

**验证方法**：对比支付宝等第三方平台数据，差异大于1元的基金需要检查计算逻辑。

### 🔴 P0：统一HTTP请求（09-03 新增）

**问题**：7个脚本都有重复的http函数，修改需要改7个地方。

**解决方案**：在fund_common.py中添加统一的http_get()函数：

```python
# fund_common.py
import urllib.request
import ssl

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

UA = {'User-Agent': 'Mozilla/5.0'}

def http_get(url: str, headers: dict = None, timeout: int = 12) -> bytes:
    """统一的HTTP GET请求"""
    h = dict(UA)
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX).read()
```

**使用方式**：
```python
from fund_common import http_get
raw = http_get("https://qt.gtimg.cn/q=sh000001")
```

### 🔴 P0：数据库表清理（09-03 新增）

**删除的空表**：
- `dragon_tiger` - 龙虎榜（无数据，无脚本调用）
- `decisions` - 决策日志（无数据，无脚本调用）
- `event_calendar` - 事件日历（无数据，无脚本调用）

**剩余表**：25张（全部有数据）

### 🔴 P0：sync_portfolio.py同步机制（09-03 新增）

**问题**：用户操作后需要手动更新8处数据，容易遗漏。

**解决方案**：创建sync_portfolio.py同步脚本，用户操作后自动同步所有相关数据源。

**使用方式**：
```bash
# 买入操作
python3 sync_portfolio.py buy 025209 300 2.3535

# 卖出操作
python3 sync_portfolio.py sell 018123 200 1.9656

# 验证系统一致性
python3 sync_portfolio.py verify
```

**自动同步内容**：
- 更新trades表
- 自动生成台账md
- 检查events表
- 验证数据一致性

### 🔴 P0：完整性检查脚本（09-03 新增）

**脚本**：verify_system.py

**检查项**：
1. trades表 vs 台账md一致性
2. trades表 vs funds表一致性
3. nav_daily数据完整性
4. events表覆盖度
5. cron配置完整性
6. skill版本一致性

**使用方式**：
```bash
# 完整检查
python3 verify_system.py

# 只检查台账
python3 verify_system.py --check-ledger

# 只检查净值
python3 verify_system.py --check-nav
```

### 🔴 P0：nav_daily.position_label字段长度不足（08-28教训）

**问题：** `position_label` 定义为 `VARCHAR(10)`，但实际格式是 `"{low_20d:.4f}-{high_20d:.4f}"`（如 `2403.6000-2853.4000`），长度可达20+字符，写入时 `DataError: Data too long for column 'position_label'`。

**根因：** 建表时低估了净值范围。基金净值从0.5到3000+不等，`{low}-{high}` 格式最坏情况约30字符。

**修复：**
```sql
ALTER TABLE nav_daily MODIFY COLUMN position_label VARCHAR(30);
```

**教训：** 任何存储计算结果的字段，设计时要用最坏情况估算长度，不要只看当前数据的典型值。

### 🔴 P0：T+1基金报告表格必须留空（08-28教训）

**问题：** 脚本已正确输出"T+1未出净值"，但agent生成报告表格时，仍从ETF估算区或自身知识补充了买入前的历史涨跌到"近8日涨跌"列。

**根因：** agent看到脚本输出中有基金代码+历史数据（来自其他基金或ETF区），就自动关联填入了T+1基金的表格行。

**修复：** 双重保险——
1. 脚本层：T+1基金不输出买入前历史涨跌（只输出"T+1未出净值"）
2. Prompt层：明确规则"T+1未出净值的基金，表格中近8日涨跌列必须留空或写—"

**详见：** `references/scan-script-t1-architecture.md`

### 🔴 P0：禁止硬编码持仓数据（08-27教训）— ✅ 已修复（08-27）

**用户原话：** "不是一个好系统"、"需要你检查一下，如有不对需重新设计"、"就应该跟着我们的数据库，实时嘛对不对"

**核心原则：** 所有脚本必须从 `trades` 表动态读取持仓，禁止在代码中写死基金代码、金额、止损止盈线等数据。

**系统性排查方法（08-27验证有效）：** 当用户要求"检查整个系统"时，必须执行：
```bash
# 1. 搜索所有硬编码的基金代码
grep -rn "017470\|017811\|011036\|018345\|018123" ~/.hermes/scripts/fund_*.py

# 2. 搜索所有硬编码的变量定义
grep -rn "CODES\s*=\|FUNDS\s*=\|HOLDINGS\s*=\|POSITIONS\s*=" ~/.hermes/scripts/fund_*.py

# 3. 逐个检查每个脚本的硬编码位置并替换
```

**✅ 已修复的脚本（08-27完成）：**
- ✅ fund_report.py — 从trades表动态读取（08-27下午修复）
- ✅ fund_daily_pipeline_v2.py — 3处硬编码全部替换为从fund_common.py读取
- ✅ fund_scan_data.py — CODES和FUND_SECTOR_MAP替换为从fund_common.py读取
- ✅ fund_event_collect.py — HELD_FUNDS和WATCHLIST_FUNDS替换为从fund_common.py读取

**解决方案：fund_common.py 共享模块**
```python
# ~/.hermes/scripts/fund_common.py
# 所有脚本统一使用这个模块获取数据

def get_holdings():
    """从trades表动态读取当前持仓"""
    # 返回: [{fund_code, fund_name, total_amount, buy_date, nav_price, stop_loss, take_profit}, ...]

def get_fund_etf_map():
    """从funds表动态读取ETF映射"""

def get_fund_sectors():
    """从funds表动态读取行业标签"""

def get_watchlist():
    """从funds表动态读取观察列表"""

def get_all_tracked_funds():
    """获取所有跟踪的基金代码（持仓+观察列表）"""

def add_fund(code, name, etf_code=None, sectors=None, is_watchlist=0):
    """添加新基金到funds表"""

def add_trade(fund_code, fund_name, direction, amount, ...):
    """添加交易记录到trades表"""

def add_decision(fund_code, decision_type, reason, ...):
    """记录决策日志"""
```

**使用方式：**
```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_holdings, get_fund_etf_map

# 动态获取
holdings = get_holdings()
etf_map = get_fund_etf_map()
```

**好处：** 用户买入/卖出后，所有脚本自动生效，无需手动改代码。

**关联参考：** `references/portfolio-sync-pitfall-2026-08-27.md`

### 🔴 P0：单一数据源架构（08-27教训）

**核心原则：** 所有脚本从一个共享模块（fund_common.py）读取数据，数据库是唯一真相来源。

**架构图：**
```
trades表（唯一数据源）
    ↓
fund_common.py（统一读取）
    ↓
┌─────────────────────────────────────────┐
│  fund_scan_data.py    → 信号扫描        │
│  fund_pipeline_v2.py  → 技术分析        │
│  fund_report.py       → 收益报告        │
│  fund_event_collect.py→ 事件收集        │
│  fund_signal_engine.py→ 信号评分        │
│  fund_portfolio_tracker.py → 收益追踪   │
└─────────────────────────────────────────┘
```

**好处：**
- 买入新基金只需在trades表加一条记录
- 所有脚本自动生效，无需改代码
- 数据一致，不会出现脚本间数据不同步

**添加新基金的标准流程：**
```sql
-- 1. 添加基金信息到funds表
INSERT INTO funds (code, name, etf_code, sectors, is_watchlist) 
VALUES ('025209', '永赢半导体智选C', '512480', '电子,半导体,芯片', 0);

-- 2. 记录交易到trades表
INSERT INTO trades (fund_code, fund_name, trade_date, direction, amount, 
                    nav_price, stop_loss, take_profit, trade_status)
VALUES ('025209', '永赢半导体智选C', '2026-08-27', '买入', 500, 
        2.42, -5, 7, '持有');
```

**完成！所有脚本自动生效，无需改代码。**

### 🔴 P0：新浪hq.sinajs.cn已封（08-27起）

**问题：** 新浪行情接口返回Forbidden，所有基金/指数/ETF实时数据无法获取。

**解决方案：** 改用腾讯股票API `https://qt.gtimg.cn/q=sh588200`，数据格式：
```
v_sh588200="1~科创芯片ETF嘉实~588200~1.203~1.148~1.160~..."
# 字段3=当前价, 字段4=昨收, 字段5=开盘, 字段33=最高, 字段34=最低
```

**注意：** 腾讯API返回的是`~`分隔，不是逗号分隔（新浪是逗号）。

### 🔴 P0：15:05无净值时不写入nav_daily（净值改由22:00独立脚本更新）

**问题：** 天天基金pingzhongdata返回的是T-1净值，15:05 Pipeline拿不到当天净值。

**当前方案（08-28重构）：**
- 15:05 Pipeline只写market_daily/etf_flow_daily/sector_flow_daily/events，跳过nav_daily
- 22:00 用 `fund_nav_update.py full` 独立拉取今日净值写入nav_daily
- 22:30 用 `fund_nav_update.py fallback` 兜底补漏（对22:00还没更新的基金再拉一次）
- **宏观事件日历**：`~/user_files/documents/宏观事件日历.md`，14:00扫描时读取预知未来7天事件
- **trades表analysis_scope字段**：JSON格式，记录买入时分析覆盖的4个维度（催化剂/宏观/位置/时机），事后复盘可用

```python
# 判断是否为今天数据
today = datetime.date.today()
is_today = (trade_date == today)

# 如果不是今天数据，跳过写入
if not is_today:
    print(f"  ⏭️ {c} 无今日净值（{trade_date}），跳过写入，等22:00真实净值")
    continue
```

**fund_nav_update.py 支持两种模式：**
- `full`=全量更新（22:00用）
- `fallback`=只更新缺净值的基金（22:30兜底用）

### 🔴 P0：北向资金API需要pageSize>=20

**问题：** 东财数据中心API（RPT_MUTUAL_DEAL_HISTORY）返回的MUTUAL_TYPE=006（北向合计）不在前3条，需要更多数据。

**解决方案：**
```python
# 东财数据中心北向资金
url = 'https://datacenter-web.eastmoney.com/api/data/v1/get?sortColumns=TRADE_DATE&sortTypes=-1&pageSize=20&pageNumber=1&reportName=RPT_MUTUAL_DEAL_HISTORY&columns=TRADE_DATE,MUTUAL_TYPE,NET_DEAL_AMT&source=WEB&client=WEB'
# MUTUAL_TYPE: 001=沪股通, 002=沪股通(?), 003=深股通, 004=深股通(?), 005=港股通(?), 006=北向合计
# NET_DEAL_AMT单位是万元，需除以10000转亿元
```

**坑点：** 前3条可能是005/003/001（None值），006在第4条以后。

### 🔴 P0：MySQL UPSERT返回rowcount=0不代表失败

**问题：** `executemany` with `ON DUPLICATE KEY UPDATE`，当更新的数据与现有数据完全相同时，rowcount返回0。

**验证：**
```python
# INSERT返回1，UPDATE相同数据返回0，UPDATE不同数据返回2
cursor.execute(sql, ('TEST', date, 1.0, 0.0))  # INSERT → rowcount=1
cursor.execute(sql, ('TEST', date, 1.0, 0.0))  # UPDATE相同 → rowcount=0
cursor.execute(sql, ('TEST', date, 2.0, 1.0))  # UPDATE不同 → rowcount=2
```

**结论：** Pipeline显示"nav_daily: 写入0条"可能是正常行为（数据已是最新），不是bug。

### 🔴 P0：fund_nav_update.py 备用接口返回缺字段导致写入崩溃（09-01教训）

**问题：** `fetch_nav_fallback` 只返回6个字段（fund_code/fund_name/trade_date/nav/daily_return/data_source），缺少全部技术指标字段（return_3d/ma5/rsi_6/trend等）。主接口失败走备用时，`executemany` 拿到不完整dict，报 `KeyError: 'return_3d'`，导致整批写入失败。

**根因：** 备用接口（FundMApi）只返回净值+涨跌幅，没有历史数据，无法计算技术指标。但SQL INSERT需要所有字段。

**修复：** 在写入数据库前，补全缺失字段为None：
```python
all_keys = ['return_3d','return_5d','return_10d','return_20d','high_20d','low_20d',
            'drawdown_from_high','consecutive_up','consecutive_down','price_pattern','position_label',
            'ma5','ma10','ma20','ma60','rsi_6','rsi_12','macd_line','signal_line','macd_histogram',
            'trend','support','resistance']
for r in results:
    for k in all_keys:
        r.setdefault(k, None)
```

**教训：** 任何多数据源拼接写入同一张表时，必须确保所有数据源的dict包含SQL需要的全部字段。备用接口通常只返回最基础数据，缺字段是常态。

### 🔴 P0：绝对不要心算星期几

**用户已3次纠正星期计算错误**（"为什么星期老是算错"），这是最严重的沟通摩擦。

- 08-21 我算成周四 → 实际是**周五**
- 08-25 我算成周一 → 实际是**周二**

**铁律：任何涉及日期/星期的判断，必须先执行：**
```bash
python3 -c "import datetime; print(datetime.date(2026,8,21).strftime('%A'))"
# 或
date  # 看当前日期
```
**不要用"今天是周三，往前推4天是周五"这种心算逻辑，每次都会错。**

### 🔴 P0：market_daily重复数据检测（09-02发现）

**问题：** Pipeline V2在08-28写入了与08-29完全相同的market_daily数据（8条记录），导致两天数据重复。

**根因：** Pipeline数据源在非交易日或数据延迟时，可能返回前一交易日数据并错误地标记为当天。

**检测方法：**
```sql
-- 查找重复数据
SELECT trade_date, index_code, close_price, daily_return
FROM market_daily 
WHERE trade_date IN ('2026-08-28', '2026-08-29')
ORDER BY trade_date, index_code;
-- 如果两天数据完全相同，说明有重复
```

**修复：** 删除重复记录（保留正确日期的那份）：
```sql
DELETE FROM market_daily WHERE trade_date = '2026-08-28';
```

**预防：** Pipeline写入market_daily时应先检查当天是否已有数据，有则跳过或用ON DUPLICATE KEY UPDATE。

### 🔴 P0：Pipeline内资金流向入库必须新建独立数据库连接

**问题：** Pipeline V2主流程已有conn/cursor，资金流向入库时复用会导致冲突或数据丢失。

**解决：** 新建独立连接，用完立即关闭。
```python
flow_conn = pymysql.connect(**DB_CONFIG)
flow_cursor = flow_conn.cursor()
# ... 执行SQL ...
flow_conn.commit()
flow_conn.close()
```

### 🔴 P0：交易净值回填闭环（09-03教训，09-04合并到22:00任务）

**问题：** 22:00净值更新只写nav_daily，不回填trades表的actual_sell_nav。导致用户清仓后，trades表的卖出净值全部为NULL，无法计算真实盈亏。

**根因：** 数据流缺少"净值更新→回填trades"的衔接环节。

**解决方案：** 创建fund_backfill_sell_nav.py脚本，**合并到22:00任务中**（09-04优化），不再单独跑22:10任务。

**回填内容：**
- actual_sell_nav：从nav_daily读取卖出日净值
- actual_return：(actual_sell_nav - buy_price) / buy_price * 100
- fee：C类基金持有<7天=1.5%，>=7天=0%
- hold_days：DATEDIFF(sell_date, trade_date)

**关键：必须用sell_date计算hold_days，不能用CURDATE()。** 因为历史交易的卖出日期不是今天。

**trades表新增sell_date字段：**
```sql
ALTER TABLE trades ADD COLUMN sell_date DATE NULL AFTER trade_date;
```

**完整晚间流程（09-04合并后）：**
```
22:00 净值更新+归因+回填+报告 → nav_daily + trades + 推送报告（合并3任务）
22:30 兜底净值+报告 → 补漏净值 + 收益报告（本地备份）
22:45 每日预测验证 → 对比周日预测vs实际NAV
22:50 收益记录 → portfolio_daily（no_agent脚本）
```

### 🔴 P0：建了表就必须入库

**用户核心观点：** "建了表就应该入库"、"不入库的数据没价值"

**错误做法：** 只展示不入库 → 数据用完就没了
**正确做法：** 盘中展示 + 收盘入库，两者缺一不可

### 🔴 P0：Cron Job no_agent=true + script 会用系统Python执行

**问题：** 当cron job配置`no_agent=true`且`script`字段有值时，cron runner会直接用系统Python执行脚本，而不是用脚本shebang指定的venv Python。导致`ModuleNotFoundError: No module named 'pymysql'`。

**验证：**
```bash
# 系统Python没有pymysql
python3 -c "import pymysql"  # ModuleNotFoundError

# venv Python有pymysql
~/.hermes/venv-fund/bin/python3 -c "import pymysql"  # OK
```

**解决方案（二选一）：**
1. **改为agent模式**（推荐）：`no_agent=false` + `script=null` + prompt中写执行命令
   ```json
   {
     "no_agent": false,
     "script": null,
     "prompt": "执行命令：~/.hermes/venv-fund/bin/python3 ~/.hermes/scripts/fund_daily_pipeline_v2.py"
   }
   ```
2. **保持no_agent=true但用wrapper脚本**：创建一个bash脚本先激活venv再执行Python脚本

**坑点：** 修改cron job的`no_agent`字段后，需要直接编辑`~/.hermes/cron/jobs.json`文件，cronjob update工具可能不会修改该字段。

### 🔴 P0：pip install到venv必须用uv（PEP 668限制）

**问题：** 本机Python 3.11启用了PEP 668（`--break-system-packages`），直接`pip install pymysql`会被拒绝。

**解决方案：** 用uv指定目标venv安装：
```bash
uv pip install --python ~/.hermes/venv-fund/bin/python pymysql
```
**不要用：** `pip install pymysql`（报错externally-managed-environment）或 `pip install --break-system-packages`（全局污染）。

### 🔴 P0：pymysql返回Decimal类型不能直接JSON序列化（08-27教训）

**问题：** pymysql从MySQL读取numeric/decimal字段时返回`decimal.Decimal`类型，`json.dump()`无法序列化。

**错误表现：** `TypeError: Object of type Decimal is not JSON serializable`

**解决方案：** 在JSON序列化前将Decimal转换为float：
```python
import json
from decimal import Decimal

# ❌ 错误：直接序列化
json.dump(data, f)  # Decimal is not JSON serializable

# ✅ 正确：转换为float
json.dump(data, f, default=str)  # 所有非标准类型转字符串

# 或者显式转换
data['amount'] = float(data['amount'])
json.dump(data, f)
```

**同样需要转换的场景：**
- `pos['buy_nav']` — pymysql返回Decimal
- `pos['amount']` — pymysql返回Decimal
- `total_invested` — SUM(amount)返回Decimal

**在计算中也要注意：**
```python
# ❌ 错误：float / Decimal 会报错
current_return = (fd['nav'] / pos['buy_nav'] - 1) * 100

# ✅ 正确：先转换为float
buy_nav = float(pos['buy_nav'])
current_return = (fd['nav'] / buy_nav - 1) * 100
```

### 🔴 P0：portfolio_daily表sharpe_ratio字段范围限制（08-27教训）

**问题：** sharpe_ratio字段定义为`DECIMAL(5,2)`，范围-999.99~999.99。当数据不足（如只有1天）时，计算出的sharpe可能超出范围。

**解决方案：** 计算后限制范围：
```python
sharpe = max(-999.99, min(999.99, sharpe))
```

**同样需要限制范围的字段：**
- `sharpe_ratio` — DECIMAL(5,2)
- `win_rate` — DECIMAL(5,2)
- `profit_factor` — DECIMAL(5,2)

### 🔴 P0：backtest_period字段长度限制（08-27教训）

**问题：** strategy_backtest表的backtest_period字段定义为`VARCHAR(20)`，但回测区间字符串"2025-01-01 ~ 2026-08-27"长度超过20。

**解决方案：** 扩展字段长度：
```sql
ALTER TABLE strategy_backtest MODIFY COLUMN backtest_period VARCHAR(50);
```

### 🔴 P0：SQL-level aggregation for one-to-many trades（09-02教训）

**问题：** 当同一基金有多笔买入记录时，Python-level aggregation（for循环分组）会取最早买入的 `nav_price`、`stop_loss`、`take_profit`、`buy_date`，而14:00扫描需要最新买入的这些值（用于T+1计算和风控）。

**根因：** 旧版 `get_holdings()` 用Python字典按fund_code分组，`holdings[code] = {...}` 在首次遇到时写入nav_price/stop_loss/take_profit，后续同基金的买入记录只累加amount，不更新这些字段。

**实际数据（09-02）：**
```
017470: 2笔买入 → 旧代码用2026-08-21的nav=2.8526，应为2026-09-01的nav=2.8242
017811: 2笔买入 → 旧代码用2026-08-25的nav=3.2931，应为2026-09-01的nav=3.2743
025209: 2笔买入 → 旧代码用2026-08-27的nav=2.4542，应为2026-09-02的nav=2.3535
```

**正确做法：SQL-level aggregation with subqueries**
```sql
SELECT
    t.fund_code,
    t.fund_name,
    latest.trade_date,        -- MAX(trade_date) per fund
    agg.total_amount,         -- SUM(amount) per fund
    t.nav_price,              -- from latest buy row
    t.stop_loss,              -- from latest buy row
    t.take_profit,            -- from latest buy row
    t.notes
FROM trades t
INNER JOIN (
    SELECT fund_code, SUM(amount) AS total_amount
    FROM trades
    WHERE direction = '买入' AND trade_status = '持有'
    GROUP BY fund_code
) agg ON t.fund_code = agg.fund_code
INNER JOIN (
    SELECT fund_code, MAX(trade_date) AS trade_date
    FROM trades
    WHERE direction = '买入' AND trade_status = '持有'
    GROUP BY fund_code
) latest ON t.fund_code = latest.fund_code
         AND t.trade_date = latest.trade_date
WHERE t.direction = '买入' AND t.trade_status = '持有'
ORDER BY t.trade_date
```

**为什么不用Python aggregation：**
- Python分组只能累加amount，无法"取最新行的其他列"
- Python分组需要多轮遍历，SQL一次查询完成
- SQL的MAX(trade_date) JOIN保证精确取到最新买入行的所有字段

**为什么不用窗口函数（ROW_NUMBER）：**
- MySQL5.7不支持窗口函数（ROW_NUMBER() OVER）
- 子查询+JOIN方式兼容MySQL5.7+

**教训：** 当需要"GROUP BY + 取最新行的非聚合列"时，用子查询JOIN，不要用Python循环分组。

### 🔴 P0：get_holdings()必须包含nav_price字段（08-27教训）

**问题：** fund_common.py的get_holdings()初始版本SQL查询没有包含nav_price字段，导致Pipeline计算持仓收益时buy_nav为None，触发除零错误。

**解决方案：** SQL查询必须包含nav_price：
```sql
SELECT fund_code, fund_name, trade_date, amount, nav_price,
       stop_loss, take_profit, notes
FROM trades 
WHERE direction = '买入' AND trade_status = '持有'
```

**验证方法：**
```python
holdings = get_holdings()
for h in holdings:
    assert h.get('nav_price') is not None, f"{h['fund_code']} nav_price is None"
```

### 🔴 P0：信号评分引擎数据格式不匹配（08-28教训）

**问题：** `fund_signal_engine.py` 的评分逻辑与 `fund_daily_pipeline_v2.py` 实际写入 nav_daily 的值不匹配，导致所有维度评分永远为0：

| 维度 | 信号引擎期望 | Pipeline实际写入 | 结果 |
|:--|:--|:--|:--|
| 趋势 | `下降`/`震荡`/`上升` | `down`/`sideways`/`up` | ❌ 趋势永远0分 |
| 形态 | `探底回升`/`横盘`/`冲高回落` | `中阴线`/`小阴线`/`小阳线` | ❌ 形态永远0分 |
| 位置 | `底部`/`中部`/`顶部` | `2.5488-3.0860`（low-high格式） | ❌ 位置永远0分 |

**根因：** Pipeline V2用ETF OHLC计算形态（中文K线名）+ 英文趋势标签，信号引擎假设的是简化版中文标签。

**修复：** 信号引擎必须同时支持中英文趋势名和完整K线形态名，位置标签需解析"low-high"格式。

```python
# 趋势：支持中英文
if trend in ('上升', 'up'): ...
elif trend in ('震荡', 'sideways'): ...

# 形态：支持完整K线名
if pattern in ('探底回升', '小阳线', '大涨', '低开高走'): ...
elif pattern in ('横盘', '小涨', '小跌', '小阴线', '中阴线', '中阳线'): ...

# 位置：解析"low-high"格式
def _parse_position(self, position: str) -> float:
    if position in ('底部', 'bottom'): return 10
    elif position in ('顶部', 'top'): return 90
    try:
        parts = position.split('-')
        if len(parts) == 2 and float(parts[1]) > float(parts[0]):
            return 50  # 默认中间位置
    except: pass
    return 50
```

**教训：** 新增评分/判断模块时，必须先 `SELECT DISTINCT` 确认数据库实际值格式，不能假设字段含义。

### 其他坑点

1. **pingzhongdata净值滞后1天**：返回的是上一个交易日数据（如周一运行返回周五净值），这是天天基金特性非bug
2. **venv路径**：脚本shebang指向`~/.hermes/venv-fund/bin/python3`，不要用系统python3（缺pymysql）
3. **UPSERT语义**：nav_daily和market_daily用`ON DUPLICATE KEY UPDATE`，同一天重复运行会覆盖更新而非插入新行。rowcount=0可能只是数据相同，不是失败
4. **交易记录确认流程**：用户说"买入"时，必须逐条确认日期+金额+信号源再写入数据库，不要假设。用户可能记错日期（如把周五记成周四）。

## 系统构建方法论

### 增量构建四步法（从本次session总结）

用户纠正了"一次性做完再检查"的思路，要求**建了就必须用**：

```
第一步：建表（schema）
  ↓
第二步：回填历史数据（让表有内容）
  ↓
第三步：新功能开发（加字段/加逻辑）
  ↓
第四步：入库验证（确保数据真的写进去了）
```

**关键原则：** 每一步完成后都要验证，不能假设"应该没问题"。用户说"不提醒都不知道"意味着agent应该主动自检。

### 🔴 完整实现四步法（用户纠正"造车但没用"）

**用户原话：** "那不等于造车了但没用吗，又让我提醒你"

**每次新增功能，必须完成以下4步，缺一不可：**

```
Step 1: 建表（CREATE TABLE）
  ↓ 验证：SHOW TABLES确认表存在
Step 2: 写脚本（Python脚本实现逻辑）
  ↓ 验证：手动运行脚本确认输出正确
Step 3: 集成到Pipeline（在pipeline中调用脚本/写入表）
  ↓ 验证：运行pipeline确认数据入库
Step 4: 配置定时任务（cron job，正确的时间+正确的脚本）
  ↓ 验证：cronjob list确认任务配置正确
```

**常见遗漏（本次session犯过的错误）：**
- ❌ 建了表但没入库 → 用户说"建了表就应该入库"
- ❌ 写了脚本但没集成到Pipeline → 脚本成了摆设
- ❌ 创建了cron job但时间放错 → 15:00收盘了推送信号没意义
- ❌ 创建了cron job但没关联script → 只有prompt没有实际执行
- ❌ 脚本中print语句位置错误 → 代码在print之后永远不会执行
- ❌ 承诺做P0/P1/P2三个功能，只做了P0就说完成了 → 用户必须追问"还差哪些"
- ❌ 承诺的P1/P2功能"下次再做"但从未继续 → 必须当场做完或明确说不做

### 🔴 输出模板必须完整展示所有模块

**用户原话：** "看回复好像没看到那些标题，是你浓缩成一句话了吗"

**问题：** AI收到脚本输出后，把资金流向、融资融券、ETF申赎、信号共振等模块浓缩成分析结论，用户看不到原始数据。

**正确做法：** prompt中必须明确要求"完整展示所有模块的原始数据，不要浓缩"。

**14:00/14:40输出模板（必须包含）：**
```
📊 盘中分析/尾盘确认

【大盘判断/实时指数】
...

【持仓信号共振】
| 基金 | RSI | 趋势 | 形态 | 位置 | 资金 | 信号 |
|:--|:--:|:--:|:--:|:--:|:--:|:--|

【资金流向】
- 主力流入TOP5：...
- 你的持仓资金信号：...

【融资融券情绪】
- TOP5板块融资净买入：...

【ETF申赎动向】
- 流入/流出情况：...

【操作建议/尾盘确认结果】
...

【风险提示】
...
```

**铁律：** 每个模块单独一个标题，展示原始数据，不要合并成一段话。

### 🔴 14:40必须配置script字段

**问题：** 14:40尾盘确认只配了prompt没配script，导致无法拉取实时数据。

**正确配置：**
```json
{
  "name": "基金14:40尾盘确认",
  "script": "fund_scan_data.py",
  "enabled_toolsets": ["terminal", "web"]
}
```

**14:00和14:40用同一个脚本**（fund_scan_data.py），脚本根据时间自动判断是否使用尾盘模式（--tail）。

### 🔴 P0：交易记录三步入库闭环

**用户原话：** "这个是你推荐的操作，记录了吗"

**每次用户操作（买/卖）后，必须完成三步，缺一不可：**

```
Step 1: 更新台账md（~/user_files/documents/投资持仓台账.md）
  ↓
Step 2: 写入trades表（MySQL fund_research.trades）
  ↓
Step 3: 写入ai_recommendations表（如果是AI推荐的操作）
```

**常见遗漏：**
- ❌ 只更新了台账，没写trades表 → 用户追问"入库了吗"
- ❌ 只写了trades表，没写ai_recommendations → AI推荐统计为空
- ❌ 三步都做了但没验证 → 实际没写进去

**验证方法：**
```sql
-- 检查trades表
SELECT * FROM trades WHERE trade_date = CURDATE();
-- 检查ai_recommendations表
SELECT * FROM ai_recommendations WHERE trade_date = CURDATE();
```

### 🔴 P0：自检铁律（用户明确要求）

**每次修改系统后，必须主动执行完整自检，不要等用户提醒。**

自检清单：
1. 数据库表结构是否完整
2. 新表是否有数据（不只是建了表）
3. Pipeline是否覆盖新功能（不只是写了脚本）
4. 14:00和15:30的数据流是否完整
5. 所有表的trade_date是否包含今天
6. 脚本是否都能正常运行
7. **每个承诺的功能是否都完成了**（不只是做了第一个就说完成了）
8. 定时任务是否关联了正确的脚本（不只是创建了任务）
9. 任务时间是否合理（交易信号不能收盘后才推）
10. **14:00/14:40的prompt是否要求完整展示所有模块**（不能浓缩成一句话）
11. **15:50复盘是否用ETF实时价格**（不能用昨天净值）
12. **三方操作是否都列出**（AI推荐、用户操作、老道推荐）
13. **nav_daily的data_source字段**：15:30是`etf_realtime`（临时），22:30后应为`fund_nav`（真实）
14. **trades表+ai_recommendations表**：今天有操作时必须都有记录
15. **FUND_ETF_MAP和ETF_MAP**：新增基金时两处都要更新

**用户原话：** "我不提醒都不知道，还得我自己去发现提醒你" — 这意味着agent必须主动检查，不能被动等待。

**用户原话：** "你实现了哪几点，还差哪些没做的" — 当你承诺做P0/P1/P2三个功能时，必须三个都做完，不能只做P0就说完成了。

**用户原话：** "看回复好像没看到那些标题，是你浓缩成一句话了吗" — 输出模板必须完整展示所有模块的原始数据。

### 🔴 完整实现四步法（用户纠正"造车但没用"）

**用户原话：** "那不等于造车了但没用吗，又让我提醒你"

**每次新增功能，必须完成以下4步，缺一不可：**

```
Step 1: 建表（CREATE TABLE）
  ↓ 验证：SHOW TABLES确认表存在
Step 2: 写脚本（Python脚本实现逻辑）
  ↓ 验证：手动运行脚本确认输出正确
Step 3: 集成到Pipeline（在pipeline中调用脚本/写入表）
  ↓ 验证：运行pipeline确认数据入库
Step 4: 配置定时任务（cron job，正确的时间+正确的脚本）
  ↓ 验证：cronjob list确认任务配置正确
```

**常见遗漏（本次session犯过的错误）：**
- ❌ 建了表但没入库 → 用户说"建了表就应该入库"
- ❌ 写了脚本但没集成到Pipeline → 脚本成了摆设
- ❌ 创建了cron job但时间放错 → 15:00收盘了推送信号没意义
- ❌ 创建了cron job但没关联script → 只有prompt没有实际执行
- ❌ 脚本中print语句位置错误 → 代码在print之后永远不会执行
- ❌ 承诺做P0/P1/P2三个功能，只做了P0就说完成了 → 用户必须追问"还差哪些"
- ❌ 承诺的P1/P2功能"下次再做"但从未继续 → 必须当场做完或明确说不做

### 🔴 信号推送时间铁律

**用户原话：** "为什么放在3点啊，那时候都收盘了"

**交易相关信号必须在盘中推送：**

| 信号类型 | 正确时间 | 错误时间 |
|:--|:--|:--|
| 盘中扫描+资金流向+信号共振 | 14:00 | ❌ 15:00 |
| 操作建议 | 14:00-14:40 | ❌ 15:00后 |
| 尾盘确认（验证14:00建议） | 14:40 | ❌ 15:00后 |
| 历史数据入库 | 15:30 | ✅ 这个必须收盘后 |
| 收盘复盘（回顾**上一个交易日**） | 15:50 | ✅ 读15:30入库数据 |

**原则：** 能辅助当天操作的 → 盘中推送；纯历史积累的 → 收盘后入库

### 🔴 复盘逻辑：基金是T+1确认收益

**用户原话：** "如果今天操作不是得第二天收盘才能出结果吗，所以复盘应该是只能复盘上一个交易日的吧"

**核心逻辑：** 基金按净值成交，今天买入要看**明天收盘**才知道结果。

```
08-26 14:40 AI推荐买入017470
08-26 用户操作了（或没操作）
08-26 老道推荐了（或没推荐）
       ↓
08-27 15:50 复盘：验证08-26的操作，用08-27的ETF实时价格（80%准确）
08-27 20:30 最终验证：用08-27的官方净值（100%准确）
```

**15:50复盘内容（必须包含三方）：**

```
📊 08-26操作复盘（08-27 15:50推送）

【三方操作汇总】
| 来源 | 基金 | 操作 | 操作价 | 今日ETF收盘 | 涨跌 | 对/错 |
|:--|:--|:--|:--|:--|:--|:--|
| AI推荐 | 017470 | 买入 | 2.75 | 2.78 | +1.1% | ✅对 |
| 用户操作 | 017470 | 买入 | 2.85 | 2.78 | -2.5% | ❌错 |
| 老道推荐 | 无 | - | - | - | - | - |

【胜率统计】
| 来源 | 总数 | 正确 | 胜率 |
|:--|:--:|:--:|:--:|
| AI推荐 | 10 | 7 | 70% |
| 用户操作 | 8 | 5 | 62.5% |
| 老道推荐 | 5 | 3 | 60% |
```

**判断对错标准：**

| 推荐 | 收盘价 vs 推荐价 | 结果 |
|:--|:--|:--|
| 买入 | 收盘价 > 推荐价 | ✅ 对 |
| 买入 | 收盘价 < 推荐价 | ❌ 错 |
| 卖出 | 收盘价 < 推荐价 | ✅ 对 |
| 卖出 | 收盘价 > 推荐价 | ❌ 错 |
| 观望 | - | ⚪ 不评判 |

**铁律：** 用户和老道没跟你说就是没动，不要假设他们操作了。

### 🔴 15:50复盘用ETF实时价格（不用昨天净值）

**用户原话：** "这两个净值用昨天的拿来干嘛，如果是哪来当成今天的净值，那不太对啊"

**问题：** 15:30 Pipeline拉到的净值是昨天的（天天基金特性），用昨天净值验证今天的推荐没意义。

**解决方案：** 15:50复盘用**ETF实时价格**作为净值近似值（80%准确）。

**15:50复盘SQL：**
```bash
# 获取ETF实时价格作为净值近似值
~/.hermes/venv-fund/bin/python3 << 'EOF'
import urllib.request, json, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def http(url, headers=None, timeout=12):
    h = {'User-Agent': 'Mozilla/5.0'}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout, context=ctx).read()

FUND_ETF = {
    '017470': '588200', '017811': None, '011036': '516150',
    '018345': '562500', '018123': None,
}

for fund_code, etf_code in FUND_ETF.items():
    if etf_code:
        prefix = 'sh' if etf_code.startswith('5') else 'sz'
        raw = http(f"https://hq.sinajs.cn/list={prefix}{etf_code}", 
                  {"Referer":"https://finance.sina.com.cn"}).decode('gbk','ignore')
        parts = raw.split('="')[1].rstrip('"').split(',')
        if len(parts) >= 4:
            current = float(parts[3])
            prev = float(parts[2])
            change = (current/prev-1)*100 if prev else 0
            print(f"{fund_code} ETF:{etf_code} 当前价:{current} 涨跌:{change:.2f}%")
EOF
```

**20:30最终验证SQL：**
```sql
UPDATE ai_recommendations ar
JOIN nav_daily nd ON ar.fund_code = nd.fund_code 
AND nd.trade_date = DATE_ADD(ar.trade_date, INTERVAL 1 DAY)
SET ar.nav_after_1d = nd.nav,
    ar.return_1d = ROUND((nd.nav - ar.nav_at_recommend) / ar.nav_at_recommend * 100, 2),
    ar.is_correct = CASE 
        WHEN ar.direction = '买入' AND nd.nav > ar.nav_at_recommend THEN 1
        WHEN ar.direction = '卖出' AND nd.nav < ar.nav_at_recommend THEN 1
        WHEN ar.direction = '观望' THEN 1
        ELSE 0
    END
WHERE ar.trade_date = DATE_SUB(CURDATE(), INTERVAL 1 DAY);
```

### 完整时间线（09-04重构版）

```
14:00  盘中扫描 → 实时拉取 → 发现机会+给建议（不记录推荐）
14:05  信号评分 → fund_signal_task.py
14:20  黄金监控 → gold_monitor_v3.py
14:40  尾盘确认 → 实时拉取 → 确认/取消14:00建议 → 记录最终推荐到ai_recommendations
15:05  ETF收盘入库 → fund_daily_pipeline_v2.py → 写market_daily/etf_flow_daily/sector_flow_daily/events（净值跳过）
15:50  收盘复盘 → 复盘上一个交易日（读MySQL，不需要当天净值）
22:00  净值更新+归因+回填+报告 → fund_nav_update.py full + fund_daily_attribution.py + fund_backfill_sell_nav.py（合并3任务→1）
22:30  兜底净值+报告 → fund_nav_update.py fallback（补漏）→ fund_report.py evening（收益报告+本地备份）
22:45  每日预测验证 → 对比周日预测vs实际NAV（读daily_predictions）
22:50  收益记录 → fund_portfolio_task.py → 写portfolio_daily（no_agent=True，纯脚本）
```

**数据流向：**
```
14:00 拉实时 → 分析 → 给建议（不记录）
       ↓
14:40 拉实时 → 确认建议 → 记录最终推荐
       ↓
15:05 拉收盘 → 入库ETF/指数/板块/新闻（净值跳过）
       ↓
15:50 读MySQL → 复盘上一个交易日
       ↓
22:00 拉净值+归因+回填 → 写nav_daily+trades+报告（合并3任务）
       ↓
22:30 补漏净值 → 出收益报告（本地备份）
       ↓
22:50 收益记录 → 写portfolio_daily（no_agent脚本）
```

**注意：** 21:00改为22:30，因为不同基金公司发布净值时间不同，22:30能确保所有基金净值都已更新。22:10归因分析和回填已合并到22:00任务（09-04优化）。

### 🔴 P0：晚间Cron任务优化方法论（09-04沉淀）

**核心原则：先画数据依赖图，再决定合并/拆分。**

#### 分析步骤

1. **读每个任务的实际内容**（prompt + script），不要凭名字猜
2. **画数据依赖图**：哪个任务写哪张表、哪个任务读哪张表、谁依赖谁
3. **识别重叠**：多个任务读同一张表+做类似分析 → 可合并
4. **识别降级机会**：纯脚本任务（self-contained Python，不需要LLM推理）→ `no_agent=True`
5. **保留兜底任务**：主任务的 retry/fallback 不要合并，保持独立

#### 判断标准：该不该合并

| 信号 | 合并 | 保留独立 |
|:--|:--|:--|
| 两个任务读同一张表、做类似分析 | ✅ | |
| 一个任务是另一个的下游（A写表→B读同一张表） | ✅ 串行执行 | |
| 两个任务完全独立、无数据依赖 | | ✅ |
| 合并后单次任务过重（>3个步骤+LLM推理） | | ✅ 拆开 |
| 一个失败会影响另一个的判断 | | ✅ 隔离 |

#### 判断标准：该不该降级为 no_agent

| 条件 | 降级 | 保持 agent |
|:--|:--|:--|
| 脚本自包含（读DB→计算→写DB，无需LLM） | ✅ no_agent=True | |
| 需要LLM做判断/总结/推送 | | ✅ no_agent=False |
| 脚本只输出结构化数据，agent需要解读 | | ✅ 保持 agent |

#### 实际案例：晚间任务从6→4

优化前（6个任务，50分钟窗口）：
```
22:00 净值更新+分析 (agent)
22:10 归因分析 (agent) + 回填 (脚本)  ← 两个同时跑
22:30 兜底净值+报告 (agent)
22:45 预测验证 (agent)
22:50 收益记录 (agent)  ← 实际是纯脚本，浪费agent token
```

优化后（4个任务，45分钟窗口）：
```
22:00 净值更新+归因+回填+报告 (合并3→1, agent)  ← 归因和回填都读nav_daily
22:30 兜底净值+报告 (保留, agent)  ← 22:00的retry
22:45 预测验证 (保留, agent)  ← 独立逻辑
22:50 收益记录 (保留, 降级为no_agent)  ← 纯脚本，不需要LLM
```

**关键决策理由：**
- 归因分析和净值更新读同一张表（nav_daily），没有额外依赖，可合并
- 回填是净值更新的下游（nav_daily→trades），串行执行即可
- 收益记录脚本384行自包含，不需要LLM，降级为no_agent省token
- 22:30兜底必须保留，是22:00的保险
- 22:45预测验证逻辑独立（读daily_predictions），不合并

**验证方法：** 合并后手动 `cronjob run` 一次，检查输出质量不降级、耗时可接受。

### 持仓收益计算（22:30推送）

**🔴 P0：持仓数据必须从trades表动态读取（08-27教训）**

**问题：** fund_report.py曾使用硬编码持仓数据（017470¥1500/026211¥500/014855¥500=¥2500），与实际持仓完全不符。用户实际持仓¥3700（7只基金）。

**根因：** 脚本没有从trades表读取持仓，而是写死了旧数据。

**正确做法：** 持仓收益计算必须从`trades`表动态聚合：
```sql
-- 获取当前持仓（买入未卖出）
SELECT fund_code, SUM(amount) as total_invested
FROM trades 
WHERE direction = '买入'
GROUP BY fund_code;
```

**portfolio_profit.json 数据结构（正确版）：**
```json
{
  "date": "2026-08-27",
  "total_invested": 3700,
  "total_current": 3750,
  "total_profit": 50,
  "total_profit_rate": 1.35,
  "positions": [
    {
      "code": "017470",
      "name": "科创芯片C",
      "buy_date": "2026-08-21",
      "amount": 1000,
      "buy_nav": 2.8526,
      "current_nav": 2.9000,
      "current_value": 1016,
      "profit": 16,
      "profit_rate": 1.6,
      "holding_days": 6,
      "fee_rate": 1.5,
      "net_profit": 1.1
    }
  ]
}
```

### 🔴 P0：T+1确认逻辑（08-27教训）— 已修正两次

**问题：** 用户今天（08-27）买入025209和025422，报告却显示"+4.52%"收益——这是错误的。后来修正为"市值=投入金额"，但fund_report.py仍用错误公式。

**核心规则（基金基本规则，必须记住）：**

1. **今天3点前买入 → 明天才出净值 → 收益从明天开始算**
2. **今天买入的基金，市值 = 投入金额**（因为明天才有净值）
3. **明天出净值后，才能用公式计算真实市值**

**正确逻辑（最终版）：**
```python
from datetime import date

today = date.today()
buy_date = position['buy_date']  # 从trades表获取

is_today_buy = (buy_date == today)

if is_today_buy:
    # 今天买入，明天才出净值，市值=投入金额
    market_value = principal  # 500元
    profit = 0
    profit_rate = 0
else:
    # 非今天买入，用净值计算市值
    shares = principal / buy_nav
    market_value = current_nav * shares
    profit = market_value - principal
    profit_rate = (current_nav / buy_nav - 1) * 100
```

**正确的市值计算公式：**
```
市值 = 投入金额 / 买入净值 × 当前净值
盈亏 = 市值 - 投入金额
盈亏率 = (当前净值 / 买入净值 - 1) × 100%
```

**错误的公式（不要用）：**
```
❌ 资产 = 总投入 + 总投入 × 今日涨跌幅  （这只算了今天，忽略了历史涨跌）
❌ impact = principal * nav_return / 100  （这只是今日涨跌的收益，不是总盈亏）
```

**验证清单：**
- [ ] 持仓数据从trades表动态读取（不是硬编码）
- [ ] 今日买入的基金显示"明日出净值"（不是当天涨幅）
- [ ] 市值计算用"份额×净值"，不是"本金×涨跌幅"
- [ ] 总投入与trades表SUM(amount)一致
- [ ] 持有天数计算正确（含买入日）

**21:00推送模板：**
```
📊 今日收益报告

【基金涨幅】
| 基金 | 今日净值 | 涨幅 |
|:--|:--|:--|
| 017470 科创芯片C | 2.7547 | -0.36% |

【持仓盈亏】
| 基金 | 买入价 | 当前价 | 持仓金额 | 盈亏 | 盈亏率 |
|:--|:--|:--|:--|:--|:--|
| 017470 科创芯片C | 2.8526 | 2.7547 | ¥966 | -¥34 | -3.43% |

【总收益统计】
- 总投入: ¥2700
- 当前市值: ¥2633
- 总盈亏: -¥67 (-2.48%)
```

### 🔴 基金净值更新时间（关键认知）

**基金官方净值不是收盘就更新的！不同基金公司发布时间不同！**

| 数据 | 更新时间 | 15:30能拉到 | 14:40能拉到 |
|:--|:--|:--|:--|
| **基金官方净值** | 晚上8-10点（陆续发布） | ❌ 昨天的 | ❌ 昨天的 |
| **ETF实时价格** | 盘中实时 | ✅ 今天的 | ✅ 今天的 |

**实测发现（08-26）：**
- 018345机器人C、018123数字经济C：21:00已更新 ✅
- 017470芯片C、017811东方AI、011036稀土C：21:00还没更新 ❌
- 22:30再拉一次，基本都能更新

**所以：**
- 15:30 Pipeline拉到的净值是**昨天**的（天天基金pingzhongdata特性）
- 21:00 Pipeline可能还有部分基金没更新
- **22:00净值更新**是主更新（full模式），拉所有基金今日净值+归因+回填+报告
- **22:30兜底**是最终版本，确保所有基金净值都已更新（fallback模式补漏）
- 15:50复盘**不能用昨天净值验证今天的推荐**（没意义）
- 应该用**ETF实时价格**作为净值近似值（80%准确）
- 22:30用**官方净值**做最终验证（100%准确）

**15:50复盘用ETF价格的逻辑：**
```
08-26 14:40 推荐买入017470，ETF价格2.75
08-26 15:50 验证：ETF收盘价2.78 → 涨了+1.1% ✅（80%准确）
08-26 20:30 最终确认：官方净值2.78 → 涨了+1.1% ✅（100%准确）
```

### Pipeline任务架构（09-04重构）

| 时间 | 任务 | 脚本 | 写入表 | 说明 |
|:--|:--|:--|:--|:--|
| **15:05** | ETF收盘入库 | fund_daily_pipeline_v2.py | market_daily, etf_flow_daily, sector_flow_daily, events | 净值跳过（15:00收盘后净值还没出来） |
| **15:50** | 复盘上一交易日 | agent prompt（读MySQL） | 决策日志 | 不需要当天净值 |
| **22:00** | 净值更新+归因+回填+报告 | fund_nav_update.py + 归因+回填脚本 | nav_daily + trades | 合并3任务为1个（09-04优化） |
| **22:30** | 兜底+收益报告 | fund_nav_update.py fallback → fund_report.py evening | nav_daily（补漏）+ 本地文件 | 对没净值的基金再拉一次 |
| **22:50** | 每日收益记录 | fund_portfolio_task.py | portfolio_daily | no_agent模式，纯脚本 |

**fund_nav_update.py 支持两种模式：**
- `full`=全量更新（22:00用，拉所有跟踪基金的今日净值）
- `fallback`=只更新缺净值的基金（22:30兜底用，先查nav_daily今天已有哪些，只拉缺的）

**fund_report.py 同时保存到本地文件**（`~/user_files/documents/fund_report_evening_YYYY-MM-DD.md`），推送失败也不丢数据。

### C类基金手续费

| 持有天数 | 手续费率 | 说明 |
|:--|:--|:--|
| **≤7天** | **1.5%** | 惩罚性手续费（支付宝C类基金） |
| **>7天** | **0%** | C类基金无赎回费 |

**到手金额 = 当前市值 - 手续费**
**实际盈亏 = 表面盈亏 - 手续费**

**21:00推送模板：**
```
📊 今日收益报告

【持仓收益明细】
| 基金 | 买入日期 | 持有天数 | 买入价 | 当前价 | 涨幅 | 当前市值 | 手续费 | 到手金额 |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|

【总收益统计】
- 总投入: ¥X
- 当前市值: ¥X
- 总手续费: -¥X
- 总到手金额: ¥X
- 实际亏损: -¥X (X%)

【7天内卖出提醒】
⚠️ 017811 东方AI 仅持有1天，卖出需扣1.5%手续费
✅ 其他基金持有5天，还差2天免手续费
```

**15:30 Pipeline新增功能（ETF实时价格保存）：**
```python
# 拉取ETF实时价格并保存到文件
etf_prices = {}
ETF_MAP = {
    '017470': '588200', '017811': None, '011036': '516150',
    '018345': '562500', '018123': None,
}

for fund_code, etf_code in ETF_MAP.items():
    if etf_code:
        # 拉取ETF实时价格
        etf_prices[fund_code] = {'price': current, 'change': change}

# 保存到文件（供15:50复盘使用）
with open('~/user_files/documents/etf_prices.json', 'w') as f:
    json.dump(etf_prices, f)
```

**21:00任务配置：**
```json
{
  "name": "基金最终净值更新",
  "script": "fund_daily_pipeline_v2.py",
  "schedule": "0 21 * * 1-5"
}
```

**21:00任务新增功能（持仓收益计算）：**
- 读取trades表获取持仓信息
- 查询最新净值计算盈亏
- 保存到portfolio_profit.json
- 推送今日收益报告（涨幅+盈亏+总收益）

### 🔴 Python脚本print语句位置

**本次session犯过的错误：** 在脚本末尾添加新代码，但print语句在新代码之前，导致新代码永远不执行。

**正确做法：** print("\n".join(out)) 必须在脚本最后一行。

```python
# ❌ 错误：print在中间，后面的代码不会输出
out.append("数据1")
print("\n".join(out))  # 这里就输出了
out.append("数据2")    # 这行永远不输出

# ✅ 正确：print在最后
out.append("数据1")
out.append("数据2")
print("\n".join(out))  # 所有数据都会输出
```

### API接口选择策略

**新浪hq.sinajs.cn已封（08-27起），优先用腾讯API：**

| 数据 | 推荐接口 | 备用接口 |
|:--|:--|:--|
| 板块资金流向 | 新浪 MoneyFlow.ssl_bkzj_bk (fenlei=2) | — |
| 板块涨幅/净流入 | 新浪 MoneyFlow.ssl_bkzj_bk (fenlei=2) | 东财push2（限流严重） |
| 基金净值 | 天天基金 pingzhongdata | — |
| 指数行情 | 腾讯 qt.gtimg.cn | — |
| ETF实时行情 | 腾讯 qt.gtimg.cn | — |
| 北向资金 | 东财datacenter (pageSize>=20) | — |

**腾讯API格式：** `https://qt.gtimg.cn/q=sh588200`
- 返回：`v_sh588200="1~科创芯片ETF嘉实~588200~当前价~昨收~开盘~..."`
- 字段用`~`分隔，字段3=当前价，字段4=昨收，字段5=开盘，字段33=最高，字段34=最低
- 解析：`re.search(r'v_(\w+)="([^"]*)"', raw)` → `data.split('~')`

**限流处理：** 重试3次 + 间隔2秒，仍失败则跳过，不影响其他数据入库。

### 融资融券+ETF申赎数据来源

**融资融券：** 目前用板块资金流向近似（新浪接口fenlei=2），真实融资融券接口（东财datacenter）数据异常暂不可用。

**ETF申赎：** 目前用ETF行情（新浪hq.sinajs.cn）近似，真实ETF份额数据接口暂不可用。

**后续优化：** 找到可用的融资融券/ETF份额接口后替换近似方案。

### 融资融券+ETF申赎入库（15:30 Pipeline执行）

```python
# 融资融券（用板块资金流向近似）
margin_url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk?page=1&num=30&sort=netamount&asc=0&fenlei=2"
margin_data = json.loads(margin_raw)

for item in margin_data[:20]:
    name = item.get('name', '')[:10]
    inamount = float(item.get('inamount', 0)) / 100000000
    outamount = float(item.get('outamount', 0)) / 100000000
    netamount = float(item.get('netamount', 0)) / 100000000
    
    # 融资买入≈inamount，融资偿还≈outamount，净买入≈netamount
    cursor.execute(margin_sql, (today, name, round(inamount, 2), round(outamount, 2), round(netamount, 2), round(abs(netamount), 2)))

# ETF申赎（用ETF行情近似）
etf_codes = ['588200', '516150', '562500', '512400', '159992', '588000', '561910']
for etf_code in etf_codes:
    prefix = 'sh' if etf_code.startswith('5') else 'sz'
    etf_url = f"https://hq.sinajs.cn/list={prefix}{etf_code}"
    # 解析：份额变化≈当日涨跌幅（近似）
    cursor.execute(etf_sql, (today, etf_code, name, round(change_pct, 4)))
```

### 14:40尾盘确认数据拉取

14:40尾盘确认需要拉实时数据，通过`fund_scan_data.py --tail`参数实现：

```bash
~/.hermes/venv-fund/bin/python3 ~/.hermes/scripts/fund_scan_data.py --tail
```

脚本会输出：
- 实时指数（上证/创业板/科创50）
- 重仓股实时行情

**注意：** fund_scan_data.py中`--tail`参数的代码必须在print语句之前，否则不会执行。

### 🔴 AI推荐记录（14:40确认后自动写入）

**核心逻辑：** 14:00只是初步建议，14:40确认后才是最终推荐。只在14:40记录。

**ai_recommendations表结构：**

```sql
CREATE TABLE ai_recommendations (
    id INT PRIMARY KEY AUTO_INCREMENT,
    trade_date DATE NOT NULL,
    fund_code VARCHAR(10) NOT NULL,
    fund_name VARCHAR(50),
    direction VARCHAR(10),        -- 买入/卖出/观望
    confidence DECIMAL(5,2),      -- 置信度(0-100)
    reason TEXT,                  -- 推荐理由
    signal_sources JSON,          -- 信号源快照
    final_signal VARCHAR(20),     -- 最终信号
    nav_at_recommend DECIMAL(10,4),  -- 推荐时净值
    nav_after_1d DECIMAL(10,4),   -- 1日后净值
    nav_after_3d DECIMAL(10,4),   -- 3日后净值
    return_1d DECIMAL(8,4),       -- 1日收益率(%)
    is_correct BOOLEAN,           -- 判断对错
    UNIQUE KEY uk_date_fund (trade_date, fund_code)
);
```

**14:40确认后写入SQL：**

```sql
INSERT INTO ai_recommendations 
(trade_date, fund_code, fund_name, direction, confidence, reason, signal_sources, final_signal)
VALUES 
(CURDATE(), '017470', '科创芯片C', '买入', 80, 'RSI超卖+低位+资金流入', '{}', '🟢买入'),
(CURDATE(), '018123', '数字经济C', '买入', 75, 'RSI超卖+低位+资金流入', '{}', '🟢买入')
ON DUPLICATE KEY UPDATE
    direction = VALUES(direction),
    confidence = VALUES(confidence),
    reason = VALUES(reason),
    final_signal = VALUES(final_signal);
```

**15:50复盘时验证对错：**

```sql
UPDATE ai_recommendations ar
JOIN nav_daily nd ON ar.fund_code = nd.fund_code AND nd.trade_date = ar.trade_date
SET ar.nav_at_recommend = nd.nav,
    ar.is_correct = CASE 
        WHEN ar.direction = '买入' AND nd.daily_return > 0 THEN 1
        WHEN ar.direction = '卖出' AND nd.daily_return < 0 THEN 1
        WHEN ar.direction = '观望' THEN 1
        ELSE 0
    END
WHERE ar.trade_date = CURDATE();
```

**铁律：** 14:00不记录推荐，只在14:40确认后记录最终推荐。

### 数据完整性检查清单

每次Pipeline运行后，必须主动检查（不要等用户提醒）：
- [ ] nav_daily：新字段（MA/RSI/MACD等）是否有值（⚠️ 15:30拉到的是T-1数据，22:30才是今天的）
- [ ] sector_flow_daily：今日是否入库
- [ ] sector_return_daily：今日是否入库（新浪API，30条）
- [ ] north_flow_daily：今日是否入库（东财datacenter，1条）
- [ ] margin_trading_daily：今日是否入库
- [ ] etf_flow_daily：今日是否入库
- [ ] signal_resonance：今日是否入库
- [ ] events：今日是否入库（东财7x24快讯，50条/天）
- [ ] 定时任务：14:00/15:30任务是否配置正确且关联了正确脚本
- [ ] **trades表**：今天有操作时必须有记录
- [ ] **ai_recommendations表**：AI推荐操作后必须有记录
- [ ] **FUND_ETF_MAP**：新增基金时两处都要更新（FUND_ETF_MAP + ETF_MAP）

## 数据库审计（09-02）

**标准审计流程：** 每次大版本变更后执行一次schema审计，确认脚本与数据库一致。

```bash
# 1. 列出所有表
mysql -h 127.0.0.1 -P 3306 -u fund_admin -p'FundR2026!db' fund_research -e "SHOW TABLES;"

# 2. DESCRIBE关键表，与脚本INSERT/SELECT对比
mysql ... -e "DESCRIBE trades;"

# 3. 检查外键约束（本库无FK，但其他库可能有）
mysql ... -e "SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME 
FROM information_schema.KEY_COLUMN_USAGE 
WHERE TABLE_SCHEMA='fund_research' AND REFERENCED_TABLE_NAME IS NOT NULL;"

# 4. 搜索脚本引用（确认表有写入者）
grep -rn 'table_name' ~/.hermes/scripts/fund_*.py
```

**已知审计发现（09-02）：**
- ⚠️ `industry_trend_signals` 表已建但无脚本写入（0行，纯摆设）
- ⚠️ `industry_trend_positions` 表已建但无脚本写入（0行，纯摆设）
- ⚠️ 全库无外键约束（设计选择，非bug，允许孤儿数据）
- ✅ trades表与fund_common.py完全一致
- ✅ events表与fund_event_collect.py完全一致（event_time/intensity/related_funds均正确）
- ✅ 所有Pipeline表存在且列名正确
- ✅ monthly_strategy表存在且monthly_strategy.py正确写入

**详细审计报告：** 见 `references/database-audit-2026-09-02.md`

### 🔴 P0：建了表就必须有脚本写入（09-02教训）

**问题：** `industry_trend_signals` 和 `industry_trend_positions` 两张表已创建，schema正确，但没有任何Python脚本引用它们——0行数据，纯摆设。

**根因：** 建表时只完成了schema设计，未集成到Pipeline或任何脚本。违反了"完整实现四步法"的Step 2（写脚本）和Step 3（集成到Pipeline）。

**自检铁律（新增）：** 每次新建表后，必须确认：
1. ✅ 表存在（SHOW TABLES）
2. ✅ 至少有一个脚本INSERT/UPDATE该表（`grep -rn 'table_name' ~/.hermes/scripts/fund_*.py`）
3. ✅ 该脚本被Pipeline或cron调用
4. ✅ 首次运行后有数据（SELECT COUNT(*)）

**四步法补充：**
```
Step 1: 建表（CREATE TABLE）→ SHOW TABLES确认
Step 2: 写脚本 → grep确认脚本引用了新表名
Step 3: 集成到Pipeline → 运行pipeline确认数据入库
Step 4: 配置定时任务 → cronjob list确认
```

**与"建了表就必须入库"的区别：**
- "建了表就必须入库"：强调数据要进入数据库（不能只展示不入库）
- "建了表就必须有脚本写入"：强调表要有写入者（不能建了表但没脚本引用）

### 🔴 P0：涨跌归因脚本空仓时的报告内容（09-03教训）

**问题：** `fund_daily_attribution.py --report` 在空仓（所有持仓已卖出）时，输出"持仓基金: 0只"和"总盈亏：¥0.00（总仓位¥0）"，saved report只有2行，缺乏市场级归因内容。

**根因：** 脚本的归因逻辑只在有持仓时才生成分析。空仓时没有持仓→没有归因→报告为空。但市场数据（8个指数、板块涨跌、事件）已成功采集，完全可以生成市场级归因报告。

**解决方案（由agent手动补全）：**
1. 先运行脚本获取基础数据（指数/板块/事件）
2. 手动查询MySQL补充板块涨跌TOP10和重要事件
3. 组织成市场级归因报告（大盘走势+板块归因+事件归因+操作建议）

**数据库查询坑点：**
- `sector_return_daily` 涨跌幅列是 `daily_return`（不是 `pct_change`）
- `events` 表日期列是 `event_time`（不是 `event_date`），强度列是 `intensity`（不是 `strength`）
- `sector_return_daily` 当天数据可能延迟入库（最新数据可能是前一交易日）

**教训：** 空仓不等于无内容。市场级归因（大盘/板块/事件分析）对用户判断下一步操作有价值，不应因持仓为空而跳过。

## 重复skill说明

`fund-research-database` 与本skill内容高度重叠（都描述fund_research数据库）。建议后续合并，以本skill为准。

## 与fund-research-database的关系

`fund-research-database`是早期版本（6张表、旧Pipeline），本skill是完整版本（12+张表、Pipeline V2）。**以本skill为准**，fund-research-database可标记为废弃。

## 老道观点参考

用户会从"理财盘友圈"app获取老道（@趋势交易的老道）的观点。老道的观点是**待验证的信号源**，不是指令。

**老道观点格式：**
- 一句话结论
- 三个要点
- 操作建议

**与系统信号的关系：**
- 老道观点 + 系统信号共振 = 更可靠的判断
- 两者一致 → 高置信度
- 两者矛盾 → 需要谨慎
