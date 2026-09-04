# 14:00扫描报告格式规范（v1.9 08-28定稿）

## 架构原则：脚本预计算，agent只展示

所有持仓相关数值（当前市值、累计、手续费）由 `fund_scan_data.py` 预计算输出，agent不做任何数学运算，只负责格式化展示。

**原因**：agent计算容易出错（手续费费率用错、累计忘加今日估算、T+1误填历史数据），脚本计算可单元测试、可复现。

## 脚本输出格式

```
[持仓基金结构化数据]
  017470|嘉实上证科创板芯片ETF|1000|2026-08-21|7|+5.63%|-2.41%|+3.22%|0%(满7天)|0.0|1032.2|-24.1|32.2
  ...
[合计] 买入总额:3000|当前总市值:3007.5|今日总盈亏:-48.9|累计总盈亏:7.5/+0.25%|总手续费:22.3
```

字段顺序（`|`分隔）：
`code|name|buy_amt|buy_date|days_held|yesterday_cum|etf_est|cur_cum|fee_label|fee_amt|cur_val|etf_est_amt|cur_cum_amt`

- yesterday_cum: 买入次日起到昨天的累计涨跌%（不含今天）
- etf_est: 今日ETF估算涨跌%
- cur_cum: yesterday_cum + etf_est
- fee_label: `0%(满7天)` 或 `1.5%(N天)`
- fee_amt: 手续费金额
- cur_val: 当前市值（到手）= 买入额 × (1+cur_cum/100) - fee_amt
- etf_est_amt: 今日估算盈亏 = 买入额 × etf_est/100
- cur_cum_amt: 累计盈亏 = cur_val - 买入额

## 报告表格格式

| 基金 | 当前市值 | 今日估算 | 当前累计 | 手续费 | 信号 |
|:--|:--|:--|:--|:--|:--|
| 017470科创芯片C | ¥1032.2 | ↓-2.41%/-¥24.1 | ≈+3.22%/+¥32.2 | 0%(满7天)/-¥0 | ⚪观望 |
| **合计** | **¥3007.5** | **↓-¥48.9** | **≈+0.25%/+¥7.5** | **-¥22.3** | — |

显示规则：
- 今日估算：↑/↓取决于etf_est正负
- 当前累计：加≈前缀
- T+1基金：当前累计显示"待确认"
- 手续费：满7天显示 `0%(满7天)/-¥0`
- 合计行：直接引用脚本[合计]行，不要自己算

## T+1判断逻辑

用NAV数据判断，不用日期间隔。

- 过滤条件：`x['x'] >= 买入次日零点的时间戳`
- 过滤后为空 → T+1，用ETF估算
- 过滤后有数据 → 正常累计

**常见错误**：
- ❌ `>= 买入日期` → 买入当天NAV被计入，T+1误显示昨日累计
- ❌ `> 买入日期` → 正常基金丢失第一天NAV，累计偏低
- ✅ `>= 买入次日零点` → 正确区分

## ETF数据时序

ETF实时数据必须在持仓基金数据**之前**拉取（持仓计算需要ETF估算值）。

## 持有天数

日历天数 = 今天日期 - 买入日期。08-25买入→08-28 = 3天。买入当天不算持有。

## 手续费

C类基金：持有<7天=1.5%，≥7天=0%。费用=扣费前市值×费率。

---

# 晚间报告格式规范（fund_report.py，08-28更新）

## 核心原则

1. **今日卖出的基金必须显示**：3点前卖出的基金，今天NAV still applies，在主表格中显示并标注"📤已卖出"
2. **NAV数据源**：优先从 `nav_daily` 表读取（与养基宝/基金公司官方一致），不用天天基金API（可能有差异）
3. **市值计算**：当前市值 = 买入额 / 买入价 × 今日NAV

## 持仓市值计算公式

```python
shares = buy_amount / buy_nav  # 买入价来自trades表nav_price
current_value = shares * today_nav  # 今日NAV来自nav_daily表
profit = current_value - buy_amount
```

## 卖出基金处理

```python
# 查询今日卖出的基金
SELECT fund_code, fund_name, amount, nav_price, actual_sell_nav, actual_return
FROM trades 
WHERE trade_status = '已卖出' AND DATE(updated_at) = today_str

# 合并到持仓列表，统一显示
all_funds = holdings + sold_today
```

## ⚠️ trades表nav_price陷阱

trades表的 `nav_price` 字段记录的是买入时的NAV，但**可能不准**：
- 025209: nav_price=2.4200，实际08-27 NAV=2.4542 → 差异导致市值计算偏差
- 025422: nav_price=1.9900，实际08-27 NAV=2.0674 → 同上

**修复方法**：对比nav_daily中买入当天的NAV，用正确值更新trades表。
**预防**：新买入时务必从nav_daily获取正确的买入当天NAV写入trades表。

## 与养基宝对账

养基宝显示的市值 = 基金公司官方NAV × 份额。如果我们的计算与养基宝差异>1%，检查：
1. trades表nav_price是否正确
2. nav_daily中的NAV是否与基金公司官方一致
3. 份额计算精度（fund companies use more decimal places）
