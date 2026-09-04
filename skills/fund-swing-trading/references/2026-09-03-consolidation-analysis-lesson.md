# 脚本合并分析方法论（09-03）

## 会话背景

用户问"是否还有架构升级空间"，我提议"减少脚本数量：合并一些相似功能的脚本"。用户问"效果会怎么样"，我诚实回答"收益有限"。用户说"那我们专门针对这一点再仔细检查一下"，我深入分析后发现**所有脚本功能不重叠，不需要合并**。

## 关键教训

**不要凭表面相似性提议合并，必须分析实际使用模式。**

我最初提议合并 fund_daily_pipeline_v2.py + fund_data_collector.py，理由是"两者都在采集数据"。但检查后发现：
- fund_daily_pipeline_v2.py：被15:05 cron任务使用，专注技术指标计算
- fund_data_collector.py：无直接cron任务，专注8源并行数据采集
- 功能不同，不重叠，不合并

## 分析方法

每次提议合并前，必须完成以下4步：

### 步骤1：检查cron任务使用情况
```bash
cronjob action=list
# 然后grep每个脚本名，看被哪些cron任务使用
grep -r "fund_xxx.py" ~/.hermes/cron/
```

### 步骤2：检查import依赖关系
```bash
# 检查脚本之间的导入关系
grep "from fund_\|import fund_" ~/.hermes/scripts/*.py
```

### 步骤3：检查功能差异
- 读脚本头部注释（功能说明）
- 读主函数（实际做什么）
- 对比输出（写入什么表/生成什么文件）

### 步骤4：评估合并影响
- 合并后cron任务是否需要修改？
- 合并后其他脚本的import是否需要修改？
- 合并后功能是否完整？

## 当前系统状态（09-03 验证后）

### 17个脚本，每个都有明确职责

| 脚本 | 职责 | cron任务 |
|------|------|----------|
| fund_common.py | 共享模块 | 无（被所有脚本导入） |
| fund_daily_pipeline_v2.py | 技术指标计算 | 15:05 |
| fund_data_collector.py | 8源并行采集 | 无（被其他脚本调用） |
| fund_nav_update.py | 净值更新 | 22:00 |
| fund_scan_data.py | 扫描数据采集 | 14:00/14:40 |
| fund_report.py | 报告生成 | 22:30 |
| fund_daily_attribution.py | 涨跌归因 | 22:10 |
| fund_feedback.py | 策略复盘 | 月度复盘 |
| fund_event_collect.py | 事件采集 | 被fund_daily_pipeline_v2.py调用 |
| fund_holdings_sync.py | 持仓同步 | 周五16:10 |
| fund_error_handler.py | 错误处理 | 无（被所有脚本导入） |
| fund_portfolio_task.py | 收益记录 | 22:50 |
| sync_portfolio.py | 同步工具 | 用户操作时 |
| verify_system.py | 完整性检查 | 手动/定时 |
| generate_ledger.py | 台账生成 | 被sync_portfolio.py调用 |
| generate_bill_report.py | 账单生成 | 每月15号 |
| system_monitor.py | 系统监控 | 手动/定时 |

### Cron任务关联验证

18个任务（16个启用，2个禁用），全部正确关联：

**日间任务**：
- 09:45 每日金价播报（gold_price_data.py）→ 无依赖
- 14:00 基金14点方向扫描（fund_scan_data.py）→ 无依赖
- 14:20 黄金每日监控（gold_monitor_v3.py）→ 无依赖
- 14:40 基金14:40尾盘确认（fund_scan_data.py）→ 依赖14:00
- 15:05 基金ETF收盘入库（fund_daily_pipeline_v2.py）→ 无依赖

**晚间任务**：
- 22:00 基金净值更新+分析（fund_nav_update.py）→ 无依赖
- 22:10 基金涨跌归因分析（fund_daily_attribution.py）→ 依赖22:00
- 22:30 基金兜底净值+完整报告（fund_report.py）→ 依赖22:00
- 22:45 每日预测验证（fund_signal_engine.py）→ 依赖22:00
- 22:50 每日收益记录（fund_portfolio_task.py）→ 依赖22:00

**周末/月度任务**：
- 周六08:00 基金周度复盘 → 无依赖
- 周日09:00 基金周度预测 → 无依赖
- 每月15号 每月账单报告（generate_bill_report.py）→ 无依赖
- 每月28号 月度投资战略生成 → 无依赖
- 每月28号 基金月度复盘报告（fund_feedback.py）→ 无依赖
- 周五16:10 基金持仓周同步（fund_holdings_sync.py）→ 无依赖

**已禁用任务**（2个）：
- 每月15号黄金定投提醒 → 已禁用
- paipai-每周架构检查 → 已禁用

## 结论

**当前系统架构已经很合理，不需要合并脚本。**

原因：
1. 每个脚本都有明确的职责
2. 功能不重叠
3. 使用场景明确
4. 依赖关系清晰

**如果强行合并**：
- 会增加脚本复杂度
- 会降低可维护性
- 会增加出错风险
- 收益有限（只是减少脚本数量）

## 验证命令

```bash
# 检查cron任务列表
cronjob action=list

# 检查脚本使用情况
grep -r "fund_xxx.py" ~/.hermes/cron/

# 检查import依赖
grep "from fund_\|import fund_" ~/.hermes/scripts/*.py

# 运行完整性检查
python3 ~/.hermes/scripts/verify_system.py

# 运行系统监控
python3 ~/.hermes/scripts/system_monitor.py
```
