# 架构重构方法论（09-02 实战）

## 背景
系统从v2.2升级到v2.3，核心改动：37脚本→14个fund_脚本，33表→27表，19 cron→15个。

## 四步重构法

### Step 1：分析调用关系
```python
# 检查哪些脚本被cron调用
# 检查哪些脚本被其他脚本import
# 找出既没被cron调用也没被import的"死代码"
```

### Step 2：删除死代码
- 17个脚本被确认为死代码（既不在cron中也不被import）
- 安全删除，不影响任何功能
- 保留被import的模块（如fund_event_collect.py被fund_daily_pipeline_v2.py动态import）

### Step 3：合并重叠功能
- fund_signal_task.py + fund_signal_analysis.py + fund_signal_engine.py → 合并到fund_scan_data.py
- fund_portfolio_task.py + fund_portfolio_tracker.py → 合并到position_manager.py
- fund_flow_analysis.py + fund_sector_rotation.py → 删除（data_collector已覆盖）

### Step 4：更新所有引用
- Skill中的脚本引用
- Cron prompt中的脚本引用
- Memory中的版本号
- MySQL表引用

## 保留的核心架构（v2.3）

```
数据层 → fund_data_collector.py（8源并行→JSON+MySQL）
分析层 → fund_scan_data.py（读JSON→分析→出报告）
展示层 → 3个报告模板 + report_format_check.py
执行层 → position_manager.py + pre_trade_check.py
```

## 验证要点
1. 删除后检查所有剩余脚本语法
2. 检查Skill中所有脚本引用
3. 检查Cron中所有脚本引用
4. 实际运行核心脚本验证功能

## 关键教训
**重构不是重写，是"砍+合并+统一"。保留能用的，砍掉没用的，合并重复的，统一数据入口。**

## 重构后发现的3个Bug

### Bug1：RSI计算断裂
- **现象**：700/751条nav_daily记录RSI=None
- **根因**：fund_nav_update.py只计算当天指标，历史批量插入的记录没有计算
- **修复**：创建backfill_rsi.py回填脚本
- **详见**：`references/2026-09-02-rsi-backfill-pattern.md`

### Bug2：同基金多条记录
- **现象**：017470/017811/025209各有2条买入记录，14:00扫描显示重复行
- **根因**：fund_common.py的get_holdings()用Python聚合，保留了最早买入的NAV
- **修复**：改为SQL级聚合，取最新买入的NAV/止损/止盈
- **关键**：多条买入记录是正常行为（多次加仓），但显示时需要聚合

### Bug3：预测验证率低
- **现象**：60条预测只有9条已验证（15%）
- **根因**：没有cron任务验证predictions表，验证字段刚加没回填
- **修复**：手动验证37条历史预测，修复market_daily重复数据
- **结果**：验证率15%→76.7%，准确率73.9%

## MySQL GROUP BY strict mode陷阱

**多次遇到的错误：**
```
Expression #2 of SELECT list is not in GROUP BY clause
and contains nonaggregated column 'xxx' which is not 
functionally dependent on columns in GROUP BY clause
```

**原因**：MySQL strict mode要求所有非聚合列必须在GROUP BY中。

**解决方案：**
```sql
-- 错误
SELECT fund_code, fund_name, SUM(amount) FROM trades GROUP BY fund_code

-- 正确
SELECT fund_code, ANY_VALUE(fund_name), SUM(amount) FROM trades GROUP BY fund_code
```

**教训**：写新SQL查询时，要么用ANY_VALUE()包裹非聚合列，要么把所有非聚合列都加到GROUP BY中。
