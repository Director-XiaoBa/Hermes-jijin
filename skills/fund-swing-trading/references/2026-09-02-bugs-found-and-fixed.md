# 深度检查发现的Bug及修复（2026-09-02）

## Bug 1：RSI计算断裂

**现象**：011036等基金从08-28起RSI=None，覆盖率从87%降到0%
**原因**：fund_nav_update.py只计算当天的RSI，历史批量插入的记录没有计算
**修复**：创建backfill_rsi.py回填脚本，一次性补全所有历史RSI/MA/MACD/趋势
**结果**：751/751条RSI完整（100%）

## Bug 2：同基金多条记录显示重复

**现象**：017470/017811/025209在14:00扫描中出现两行
**原因**：SQL查询没聚合多条买入记录，JOIN后产生笛卡尔积
**修复**：fund_common.py的get_holdings()改为SQL级聚合（GROUP BY + ANY_VALUE）
**关键SQL**：
```sql
SELECT n.fund_code, ANY_VALUE(t.fund_name), SUM(t.amount)
FROM nav_daily n JOIN trades t ON ...
GROUP BY n.fund_code, n.nav, n.daily_return
```

## Bug 3：预测验证率偏低

**现象**：60条预测只有9条已验证（15%）
**原因**：没有cron任务验证predictions表，验证字段刚加没回填
**修复**：手动验证37条历史预测，修复market_daily重复数据
**结果**：46/60已验证（76.7%），准确率73.9%

## Bug 4：MySQL strict mode GROUP BY

**现象**：`Expression #2 of SELECT list is not in GROUP BY clause`
**原因**：MySQL only_full_group_by模式要求所有非聚合列在GROUP BY中
**修复**：使用ANY_VALUE()包裹非聚合列，或在GROUP BY中包含所有列
**教训**：写SQL时注意MySQL strict mode，GROUP BY必须包含所有SELECT中的非聚合列

## 验证准确率统计

| 预测类型 | 准确率 |
|:--|:--|
| 事件影响 | 83.3%（最强） |
| 方向预测 | 73.3% |
| 入场时机 | 33.3%（最弱） |
| **综合** | **73.9%** |

| 时间维度 | 准确率 |
|:--|:--|
| 5天 | 100%（最强） |
| 1天 | 62.5% |
| 3天 | 40%（最弱） |
