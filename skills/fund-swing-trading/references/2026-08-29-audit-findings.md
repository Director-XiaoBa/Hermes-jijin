# 预测-验证-进化系统 审计发现（08-29）

## 已修复的问题

### 1. NAV验证时间错误（🔴高）
- **问题**：验证任务原定16:00，但NAV数据22:00才更新
- **修复**：改为22:45
- **教训**：验证任务必须在数据源更新后执行

### 2. 22:30时间冲突（🔴高）
- **问题**：兜底净值报告和预测验证都定在22:30
- **修复**：预测验证改为22:45
- **教训**：多个任务不能同时触发，需错开≥5分钟

### 3. daily_predictions表无唯一约束（🔴高）
- **问题**：可能重复写入同一基金同一天的预测
- **修复**：添加唯一索引（prediction_date, target_date, fund_code）

### 4. predictions表重复数据（🟡中）
- **问题**：存在重复预测记录
- **修复**：清理重复数据+添加唯一索引（prediction_date, prediction_type, target）

### 5. 每周认知进步表skill版本过旧（🟡中）
- **问题**：使用v1.5，其他任务用v1.7
- **修复**：更新到v1.7

## 数据流验证

```
周日09:00预测 → 写入daily_predictions+predictions
    ↓
周一至周五22:45验证 → 读取daily_predictions+nav_daily → 更新accuracy
    ↓
周六08:00复盘 → 读取daily_predictions+predictions → 统计准确率+调整策略
    ↓
写入strategy_evolution → 新会话继承
```

## 关键字段引用

| 表 | 验证字段 | 数据来源 |
|:--|:--|:--|
| daily_predictions | actual_nav | nav_daily.nav |
| daily_predictions | actual_change_pct | nav_daily.daily_return |
| daily_predictions | accuracy | 对比predicted vs actual |
| predictions | actual_result | 手动填写 |
| market_snapshot | sh_index | qt.gtimg.cn |
| market_snapshot | sentiment | 手动判断 |
