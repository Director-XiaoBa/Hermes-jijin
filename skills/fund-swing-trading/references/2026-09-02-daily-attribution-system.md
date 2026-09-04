# 涨跌归因系统（2026-09-02 新增）

## 功能
每天自动回答三个问题：大盘影响/板块影响/事件影响

## 脚本
`fund_daily_attribution.py`（380行）

## 用法
```bash
python3 fund_daily_attribution.py [日期] --report
```

## 归因逻辑

### 1. 大盘影响
- 计算基金β系数（近20天相对于上证指数的协方差/方差）
- 大盘贡献 = 上证涨跌 × β
- 超额收益 = 基金涨跌 - 大盘贡献

### 2. 板块影响
- 基金→板块映射：从fund_sector_map表读取
- 板块→新浪板块名称映射：关键词匹配（芯片→电子器件，稀土→有色金属等）
- 板块贡献 = 板块涨跌 × 0.7（假设70%来自板块）

### 3. 事件影响
- 从events表读取当日强度≥3的事件
- 关键词匹配事件与基金的相关性
- 输出关联事件列表

## 板块名称映射表

| 基金板块 | 新浪板块 |
|:--|:--|
| 芯片/半导体/存储/CPO | 电子器件 |
| AI/算力 | 电子信息 |
| 机器人 | 机械行业 |
| 稀土 | 有色金属 |
| 消费电子 | 电子器件/家电行业 |

## MySQL表
daily_attribution（trade_date, fund_code, daily_return, beta, market_contribution, excess_return, sector_name, sector_return, conclusion）

## Cron集成
22:05自动运行（净值更新后）
