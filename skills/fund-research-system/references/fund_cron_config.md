# 基金系统定时任务配置参考（09-04更新）

## 完整时间线（最终版 09-04）

```
14:00  盘中扫描 → fund_scan_data.py → 实时拉取 → 发现机会+给建议
14:05  信号评分 → fund_signal_task.py
14:20  黄金监控 → gold_monitor_v3.py
14:40  尾盘确认 → fund_scan_data.py --tail → 确认/取消14:00建议 → 记录推荐
15:05  ETF收盘入库 → fund_daily_pipeline_v2.py → 写market_daily/etf_flow_daily/sector_flow_daily/events
15:50  收盘复盘 → 复盘上一个交易日（读MySQL）
22:00  净值更新+归因+回填+报告 → fund_nav_update.py full + 归因+回填+报告 (agent)
22:30  兜底净值+报告 → fund_nav_update.py fallback → fund_report.py evening (agent)
22:45  每日预测验证 → daily_predictions对比 (agent)
22:50  每日收益记录 → fund_portfolio_task.py → portfolio_daily (no_agent)
```

## 基金核心任务（每日运行）

| 任务 | 时间 | 脚本 | AI分析 | 说明 |
|:--|:--|:--|:--|:--|
| 14:00扫描 | 14:00 | fund_scan_data.py | ✅ 有 | 实时数据+信号共振+操作建议 |
| 14:40确认 | 14:40 | fund_scan_data.py --tail | ✅ 有 | 确认/取消建议+记录推荐 |
| 15:05入库 | 15:05 | fund_daily_pipeline_v2.py | ❌ 无 | 收盘数据入库（净值跳过） |
| 15:50复盘 | 15:50 | 无 | ✅ 有 | 复盘上一个交易日 |
| 22:00净值+归因+回填 | 22:00 | fund_nav_update.py + 归因+回填 | ✅ 有 | 合并3个任务为1个 |
| 22:30兜底+报告 | 22:30 | fund_nav_update.py fallback | ✅ 有 | 22:00的retry |
| 22:45预测验证 | 22:45 | 无 | ✅ 有 | 验证周日预测 |
| 22:50收益记录 | 22:50 | fund_portfolio_task.py | ❌ 无 | no_agent，纯脚本 |

## 黄金任务

| 任务 | 时间 | 脚本 | 说明 |
|:--|:--|:--|:--|
| 金价播报 | 9:45 | gold_price_data.py | 每日金价 |
| 黄金监控 | 14:20 | gold_monitor_v3.py | 黄金信号 |

## 周度/月度任务

| 任务 | 时间 | 说明 |
|:--|:--|:--|
| 周度复盘 | 周六08:00 | 三条线统计 |
| 周度预测 | 周日09:00 | 下周一至周五预测 |
| 持仓周同步 | 周五16:10 | 持仓同步 |
| 月度复盘 | 每月28号14:00 | 月度复盘报告 |
| 月度策略 | 每月28号09:00 | 投资战略生成 |

## 晚间任务优化原则（09-04）

1. **画数据依赖图再合并**：读同一张表+做类似分析的任务可以合并
2. **纯脚本降级为no_agent**：self-contained Python不需要LLM推理
3. **兜底任务保持独立**：主任务的retry不合并
4. **验证合并效果**：手动cronjob run一次，检查输出质量
