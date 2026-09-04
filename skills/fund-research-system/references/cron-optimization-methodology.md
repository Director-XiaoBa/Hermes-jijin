# Cron任务优化方法论（09-04沉淀）

## 核心原则
**先画数据依赖图，再决定合并/拆分。不凭任务名字猜。**

## 分析步骤

1. **读每个任务的实际内容**（prompt + script），不要凭名字猜
2. **画数据依赖图**：哪个任务写哪张表、哪个任务读哪张表、谁依赖谁
3. **识别重叠**：多个任务读同一张表+做类似分析 → 可合并
4. **识别降级机会**：纯脚本任务（self-contained Python，不需要LLM推理）→ `no_agent=True`
5. **保留兜底任务**：主任务的 retry/fallback 不要合并，保持独立

## 判断标准：该不该合并

| 信号 | 合并 | 保留独立 |
|:--|:--|:--|
| 两个任务读同一张表、做类似分析 | ✅ | |
| 一个任务是另一个的下游（A写表→B读同一张表） | ✅ 串行执行 | |
| 两个任务完全独立、无数据依赖 | | ✅ |
| 合并后单次任务过重（>3个步骤+LLM推理） | | ✅ 拆开 |
| 一个失败会影响另一个的判断 | | ✅ 隔离 |

## 判断标准：该不该降级为 no_agent

| 条件 | 降级 | 保持 agent |
|:--|:--|:--|
| 脚本自包含（读DB→计算→写DB，无需LLM） | ✅ no_agent=True | |
| 需要LLM做判断/总结/推送 | | ✅ no_agent=False |
| 脚本只输出结构化数据，agent需要解读 | | ✅ 保持 agent |

## 调试方法
```bash
# 查看cron job完整配置（包括no_agent字段）
python3 -c "
import json
with open('/home/ubuntu/.hermes/cron/jobs.json') as f:
    data = json.load(f)
for j in data['jobs']:
    if j.get('name') == '目标任务名':
        print(json.dumps(j, ensure_ascii=False, indent=2))
"

# 修改no_agent字段（cronjob update工具不支持该字段）
python3 -c "
import json
path = '/home/ubuntu/.hermes/cron/jobs.json'
with open(path) as f:
    data = json.load(f)
for j in data['jobs']:
    if j.get('name') == '目标任务名':
        j['no_agent'] = True
with open(path, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
"
```

## 实际案例：晚间任务从6→4

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
