# 预测-验证-进化系统 配置清单（08-29 更新）

## Cron任务时间表

| 任务 | 时间 | Job ID | 依赖 |
|:--|:--|:--|:--|
| 基金周度预测 | 周日09:00 | 3c71324b8d6a | 无（独立） |
| 每日预测验证 | 周一至周五**22:45** | 0da21fde8a9c | 依赖22:00 NAV更新完成 |
| 基金周度复盘 | 周六08:00 | 8e4db68f7640 | 依赖本周验证数据 |

⚠️ **验证任务必须在22:45**：NAV数据22:00才更新，16:00时nav_daily没有当天数据。

## 周度预测Prompt日期锚定要求（08-31 教训）

周日预测任务（3c71324b8d6a）的prompt**必须包含以下日期锚定规则**，防止agent偏移日期范围：

```
**日期锚定规则**：
- prediction_date = 今天（周日）
- target_dates = 明天（周一）开始，连续5个交易日
- 例如：如果今天是09-06周日，则 target_dates = 09-07(周一), 09-08(周二), 09-09(周三), 09-10(周四), 09-11(周五)
- **必须用 `date` 命令验证每个target_date是星期几，确保是周一到周五**
```

**历史bug**：prompt写"下周一到周五"，agent将"下周"理解为从周二开始，遗漏了周一。已修复（08-31）。

## 数据库表约束

```sql
-- daily_predictions: 防重复预测
UNIQUE INDEX idx_fund_prediction (prediction_date, target_date, fund_code)

-- predictions: 防重复市场预测
UNIQUE INDEX idx_prediction_unique (prediction_date, prediction_type, target)

-- market_snapshot: 每天一条
UNIQUE INDEX idx_snapshot_date (snapshot_date)
```

## 晚间任务时间线（无冲突）

```
22:00  NAV更新 (fund_nav_update.py full)
  ↓ 30分钟
22:30  兜底净值+报告 (fund_nav_update.py fallback + fund_report.py)
  ↓ 15分钟
22:45  预测验证 (读daily_predictions+nav_daily)
  ↓ 5分钟
22:50  收益记录 (fund_portfolio_task.py → portfolio_daily)
```

## 关键字段映射

| 目标表 | 字段 | 数据来源 |
|:--|:--|:--|
| daily_predictions | actual_nav | nav_daily.nav |
| daily_predictions | actual_change_pct | nav_daily.daily_return |
| daily_predictions | accuracy | 对比predicted vs actual |
| predictions | actual_result | 手动填写 |
| market_snapshot | sh_index | qt.gtimg.cn |
| market_snapshot | sentiment | 手动判断(bullish/neutral/bearish) |

## 验证标准

- **correct**：方向正确，幅度误差<1%
- **partial**：方向正确但幅度偏差大
- **wrong**：完全相反
