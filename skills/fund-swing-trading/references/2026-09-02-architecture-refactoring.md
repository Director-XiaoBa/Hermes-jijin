# 架构重构记录（2026-09-02）

## 重构前后对比

| 维度 | 重构前 | 重构后 | 变化 |
|:--|:--|:--|:--|
| 脚本数 | 37个fund_开头 | 14个fund_开头 | -23个 |
| MySQL表 | 33张 | 27张 | -6张 |
| Cron任务 | 19个 | 15个启用 | -4个 |

## 删除的脚本（16个）

### 确认死代码（从未被cron调用，从未被import）
- fund_monthly_review.py
- fund_curve_generator.py
- fund_signal_stats.py
- fund_tn_fill.py
- fund_signal_log.py
- fund_robot_watch.py
- fund_overseas_chain.py
- fund_backtest.py
- fund_trade_log.py
- fund_calculate_indicators.py
- fund_signal_analysis.py
- fund_pattern_match.py
- fund_sector_rotation.py
- fund_query.py
- fund_flow_analysis.py
- fund_backfill_portfolio.py

### 保留但标记
- fund_event_collect.py — 被fund_daily_pipeline_v2.py动态import，不可删除

## 删除的MySQL表（6张）

| 表名 | 原因 |
|:--|:--|
| kol_tracking | 0行，无脚本引用 |
| market_snapshot | 0行，无脚本引用 |
| monthly_stats | 0行，无脚本引用 |
| signal_stats | 0行，无脚本引用 |
| industry_trend_signals | 0行，无脚本引用 |
| industry_trend_positions | 0行，无脚本引用 |

## 删除的Cron任务（2个）

| 任务 | 原因 |
|:--|:--|
| 基金每日复盘（15:50） | 合并到22:30报告 |
| 月度策略调优（28号11:00） | 合并到月度复盘（28号14:00） |

## 保留的核心架构

```
数据层 → fund_data_collector.py（8源并行→JSON+MySQL）
分析层 → fund_scan_data.py（读JSON→分析→出报告）
展示层 → 3个报告模板 + report_format_check.py
执行层 → position_manager.py + pre_trade_check.py
```

## Skill引用修复

删除脚本后，skill中以下引用已更新：
- fund_query.py的bash命令 → 改为Python SQL查询示例
- fund_signal_analysis.py的历史教训引用 → 更新为通用描述
- fund_signal_log.py/fund_trade_log.py → 改为"trades表MySQL管理"

## 验证结果

- 40个.py文件全部语法通过
- 27张MySQL表结构正确
- 15个cron任务无引用已删除脚本
- 9个skill脚本引用全部有效
