# 晚间定时任务优化（09-03）

## 问题背景
晚间22:00~22:50有5个cron任务密集执行，存在以下问题：
1. 任务间隔过短（22:00→22:05仅5分钟）
2. 失败处理缺失（22:00失败后22:30仍运行fallback模式）
3. 数据依赖不明确（22:45验证不检查数据完整性）

## 优化方案

### 1. 时间间隔优化
- **22:05→22:10**：归因分析延迟5分钟，确保与净值更新有10分钟间隔
- 所有任务间隔≥5分钟，避免iLink限流

### 2. 智能降级机制（22:30任务）
**原逻辑**：直接运行`fund_nav_update.py fallback`
**优化后**：先检查22:00是否成功，失败则运行full模式

```python
# 检查22:00是否成功
python3 -c "
import pymysql
conn = pymysql.connect(host='127.0.0.1', port=3306, user='fund_admin', 
                      password='FundR2026!db', database='fund_research', charset='utf8mb4')
with conn.cursor() as cur:
    cur.execute(\"SELECT COUNT(*) FROM nav_daily WHERE trade_date = CURDATE()\")
    count = cur.fetchone()[0]
    print(f'今日已更新{count}条净值')
conn.close()
"
# count=0 → 运行full模式
# count>0 → 运行fallback模式
```

### 3. 数据完整性检查（22:45任务）
**原逻辑**：直接验证预测
**优化后**：先检查nav_daily数据量 vs 持仓数量

```python
python3 -c "
import pymysql
conn = pymysql.connect(host='127.0.0.1', port=3306, user='fund_admin', 
                      password='FundR2026!db', database='fund_research', charset='utf8mb4')
with conn.cursor() as cur:
    cur.execute(\"SELECT COUNT(*) FROM nav_daily WHERE trade_date = CURDATE()\")
    count = cur.fetchone()[0]
    cur.execute(\"SELECT COUNT(*) FROM trades WHERE trade_status = '持有'\")
    holdings = cur.fetchone()[0]
    print(f'今日净值: {count}条, 持仓基金: {holdings}只')
conn.close()
"
# count < holdings → 验证结果可能不准确，需标注警告
```

## 优化前后对比

| 任务 | 优化前 | 优化后 | 改进 |
|------|--------|--------|------|
| 归因分析 | 22:05 | 22:10 | 间隔从5分钟增至10分钟 |
| 兜底+报告 | 直接fallback | 智能检查 | 失败时自动降级为full模式 |
| 预测验证 | 直接验证 | 数据完整性检查 | 不完整时标注警告 |

## 设计原则
1. **任务职责单一**：便于故障隔离
2. **不依赖前置任务成功**：但会检查数据完整性
3. **失败时降级运行**：不阻塞整个流程
4. **警告信息明确标注**：避免用户误解

## Cron任务执行记录（09-02）
```
22:00:18 → 22:01:04 (46秒) - 净值更新
22:05:18 → 22:05:42 (23秒) - 归因分析
22:30:19 → 22:32:49 (2.5分钟) - 兜底+报告
22:45:19 → 22:48:26 (3分钟) - 预测验证
22:50:19 → 22:50:27 (8秒) - 收益记录
```

所有任务均成功完成，无错误。