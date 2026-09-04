# 基金研究系统 — Code Review 请求

## 系统概览

这是一个**个人基金投资辅助系统**，运行在 CloudBase + MySQL 上，由 AI Agent (Hermes) 通过定时任务自动执行数据采集、分析、报告和验证。

**核心目标**：辅助用户做 A 股基金的短线交易决策（持有期 3-10 天），通过技术分析 + 事件驱动 + 预测验证的闭环，持续提升判断准确率。

**当前状态**：v5.1 架构，2026-09-03 全仓清仓（总亏损 ¥158，-2.93%），系统空仓待用户重新进场。

---

## 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    数据采集层                              │
│  fund_data_collector.py (8源并行)                         │
│  fund_event_collect.py (事件采集)                         │
│  fund_holdings_sync.py (持仓同步)                         │
└──────────────┬──────────────────────────────────────────┘
               │ 写入
               ▼
┌─────────────────────────────────────────────────────────┐
│                    数据存储层                              │
│  MySQL fund_research (26张表)                             │
│  核心表: nav_daily / trades / portfolio_daily             │
│  分析表: daily_predictions / signals / daily_attribution  │
│  辅助表: events / market_daily / sector_flow_daily        │
└──────────────┬──────────────────────────────────────────┘
               │ 读取
               ▼
┌─────────────────────────────────────────────────────────┐
│                    分析引擎层                              │
│  fund_nav_update.py (净值更新+技术指标)                    │
│  fund_scan_data.py (14:00盘中扫描)                        │
│  fund_daily_attribution.py (涨跌归因)                     │
│  fund_analysis_upgrade.py (分量分析)                      │
│  fund_comprehensive_analysis.py (综合分析)                │
└──────────────┬──────────────────────────────────────────┘
               │ 输出
               ▼
┌─────────────────────────────────────────────────────────┐
│                    报告 & 决策层                           │
│  fund_report.py (报告生成)                                │
│  fund_portfolio_task.py (收益记录)                        │
│  fund_feedback.py (月度复盘)                              │
│  daily_predictions (预测验证)                              │
└─────────────────────────────────────────────────────────┘
```

---

## 脚本清单 (scripts/)

| 脚本 | 行数 | 职责 | 调用方式 |
|------|------|------|---------|
| `fund_common.py` | 300+ | 共享模块：DB连接、get_holdings()、工具函数 | 被其他脚本 import |
| `fund_error_handler.py` | 150+ | 错误处理：retry、fallback、log_error 装饰器 | 被其他脚本 import |
| `fund_data_collector.py` | 700+ | 数据采集：8个数据源并行（新浪/东财/腾讯等） | Pipeline V2 调用 |
| `fund_nav_update.py` | 338 | 净值更新：拉取净值→计算MA/RSI/MACD→写入nav_daily | 22:00/22:30定时 |
| `fund_backfill_sell_nav.py` | 152 | 交易回填：nav_daily→trades的actual_sell_nav | 22:00合并执行 |
| `fund_daily_pipeline_v2.py` | 1200+ | Pipeline V2：完整的每日数据管道 | 15:05定时 |
| `fund_scan_data.py` | 700+ | 盘中扫描：14:00数据采集+信号生成+报告 | 14:00定时 |
| `fund_1400_enhanced.py` | 150+ | 增强扫描：14:00扫描的增强版 | 被14:00任务调用 |
| `fund_daily_attribution.py` | 394 | 涨跌归因：大盘/板块/事件三维度归因 | 22:00合并执行 |
| `fund_analysis_upgrade.py` | 230+ | 分量分析：持仓基金的分量化评估 | 10:00定时 |
| `fund_comprehensive_analysis.py` | 180+ | 综合分析：多维度综合评估报告 | 10:30定时 |
| `fund_report.py` | 400+ | 报告生成：14:00/22:30报告模板 | 定时任务调用 |
| `fund_portfolio_task.py` | 384 | 收益记录：计算市值/回撤/夏普→写portfolio_daily | 22:50定时 |
| `fund_holdings_sync.py` | 130+ | 持仓同步：同步用户实际持仓到trades表 | 周五16:10定时 |
| `fund_event_collect.py` | 400+ | 事件采集：东财快讯→结构化事件库 | 被Pipeline调用 |
| `fund_feedback.py` | 350+ | 月度复盘：生成月度投资复盘报告 | 每月28日定时 |

---

## 数据库Schema

详见 `schema.sql`。26张表，核心表说明：

### 核心数据流表

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `nav_daily` | 每日净值+技术指标 | fund_code, trade_date, nav, daily_return, rsi_6/12, ma20/60, trend, support, resistance |
| `trades` | 交易记录 | fund_code, direction(buy/sell), amount, nav_price, actual_sell_nav, actual_return, trade_status |
| `portfolio_daily` | 每日组合收益 | total_invested, total_value, profit_rate, max_drawdown, sharpe_ratio |

### 分析表

| 表名 | 用途 |
|------|------|
| `daily_predictions` | 每日预测（周日生成→每日验证） |
| `signals` | 交易信号记录 |
| `daily_attribution` | 每日涨跌归因 |
| `improvement_log` | 改进教训记录 |

### 辅助数据表

| 表名 | 用途 |
|------|------|
| `funds` | 基金基本信息 |
| `fund_sector_map` | 基金→板块映射 |
| `events` | 结构化事件库 |
| `market_daily` | 大盘/板块行情 |
| `etf_flow_daily` | ETF资金流 |
| `sector_flow_daily` | 板块资金流 |

---

## 定时任务 (cron-jobs.json)

当前共 **19个任务**，按时间排列：

### 工作日流程 (周一至周五)

| 时间 | 任务 | 类型 | 说明 |
|------|------|------|------|
| 09:45 | 每日金价播报 | agent+脚本 | 黄金价格播报 |
| 10:00 | 基金分量分析 | agent | 持仓分量化评估 |
| 10:30 | 基金综合分析 | agent | 多维度综合报告 |
| 14:00 | 基金方向扫描 | agent+脚本 | 盘中扫描+信号生成 |
| 14:20 | 黄金每日监控 | 脚本 | 黄金价格监控 |
| 14:40 | 尾盘确认 | agent+脚本 | 14:00信号的尾盘确认 |
| 15:05 | ETF收盘入库 | 脚本 | Pipeline V2入库存储 |
| 22:00 | 净值更新+分析 | agent | **核心任务**：净值更新→回填→归因→报告 |
| 22:30 | 兜底净值+报告 | agent | 22:00的retry+晚间报告 |
| 22:45 | 预测验证 | agent | 对比周日预测vs实际 |
| 22:50 | 收益记录 | 脚本 | 记录portfolio_daily |

### 周末任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 周六 08:00 | 周度复盘 | 三条线统计+预测验证 |
| 周日 09:00 | 周度预测 | 下周一至周五全预测 |

### 月度任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 每月15日 09:00 | 每月账单报告 | 个人记账 |
| 每月15日 10:00 | 黄金定投提醒 | 提醒定投 |
| 每月28日 09:00 | 月度投资战略 | 生成月度战略 |
| 每月28日 14:00 | 月度复盘报告 | 投资复盘 |

---

## 已知问题 & 历史教训

### 09-03 全仓清仓复盘

**总亏损 ¥158（-2.93%）**，其中手续费 ¥43 占 25%。

**三大系统脱离错误**：
1. **08-27 大阳线追涨** — 违反"大阳线日不追"铁律
2. **09-01 暴跌当天抄底** — 趋势未稳就进场
3. **09-02/03 下跌趋势补仓** — 越跌越买

**组合问题**：
- 8只全科技方向，零分散
- ¥200-300小仓位，手续费比例过高

### 系统层面问题

1. **数据源不稳定**：新浪/360/百度搜索被封，东财push2 API从云IP完全封禁
2. **预测准确率**：09-02预测准确率0%，预测系统需持续迭代
3. **AI过于被动**：用户反馈"你大多数都是观望，只有非常明显的信号才会给出建议，那样都晚了"

---

## 请 Review 的重点

### 1. 脚本冗余分析
- 哪些脚本功能重叠？能否合并？
- `fund_1400_enhanced.py` 和 `fund_scan_data.py` 的关系？
- `fund_analysis_upgrade.py` 和 `fund_comprehensive_analysis.py` 是否冗余？

### 2. 数据库Schema设计
- 表结构是否合理？有没有缺失的索引？
- 字段类型是否合适？（比如 decimal 精度）
- 26张表是否过多？能否精简？

### 3. 定时任务调度
- 19个任务是否过多？哪些可以合并？
- 时间窗口安排是否合理？
- 依赖关系是否正确？

### 4. 代码质量
- 错误处理是否完善？
- 有没有明显的性能瓶颈？
- 代码风格和可维护性如何？

### 5. 架构层面
- 整体架构是否合理？
- 有没有更好的技术选型建议？
- 对于个人投资辅助系统，这个复杂度是否必要？

### 6. 具体改进建议
- 请给出 Top 5 优先级最高的改进项
- 每个改进项给出具体方案和预期收益

---

## 文件结构

```
fund-system-review/
├── README.md              ← 本文件
├── schema.sql             ← 数据库26张表结构
├── cron-jobs.json         ← 19个定时任务配置（已脱敏）
├── scripts/               ← 16个核心脚本
│   ├── fund_common.py
│   ├── fund_error_handler.py
│   ├── fund_nav_update.py
│   ├── fund_backfill_sell_nav.py
│   ├── fund_daily_attribution.py
│   ├── fund_scan_data.py
│   ├── fund_1400_enhanced.py
│   ├── fund_report.py
│   ├── fund_portfolio_task.py
│   ├── fund_data_collector.py
│   ├── fund_daily_pipeline_v2.py
│   ├── fund_holdings_sync.py
│   ├── fund_event_collect.py
│   ├── fund_feedback.py
│   ├── fund_analysis_upgrade.py
│   └── fund_comprehensive_analysis.py
└── skills/                ← 相关Skill定义
    ├── fund-swing-trading/
    ├── fund-research-system/
    └── fund-investment-analysis/
```

## 技术栈

- **运行环境**：腾讯云 Ubuntu 22.04, 4核Xeon@2.5G
- **数据库**：MySQL 8.0 (fund_research)
- **AI Agent**：Hermes Agent (Nous Research)
- **定时调度**：Hermes Cron (内置)
- **数据源**：新浪/东财/腾讯/天天基金 等8个API
- **语言**：Python 3.11
