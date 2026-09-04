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

## 🔴 "昨日市值" 计算 Bug（08-29 发现）

**问题**：fund_report.py 计算"昨日市值"时，对**昨天买入**的基金算错。

**根因**：脚本查询 `SELECT nav FROM nav_daily WHERE trade_date < today_str`，对08-28的报告会取08-27的NAV。但025209/025422是08-27当天买入的，买入价=08-27 NAV，所以08-27市值应该=买入额=500。脚本却用08-26的NAV算出了507/519。

**正确逻辑**：
```python
if buy_date == yesterday_str:
    # 昨天买入，昨日市值=买入额
    market_value_yesterday = principal
else:
    # 更早买入，正常计算
    market_value_yesterday = nav_yesterday * shares
```

**验证铁律**：fund_report.py 生成后，至少抽查1-2只基金的"今日收益"是否与NAV变动匹配：
```python
shares = buy_amount / buy_nav
yesterday_value = shares * nav_yesterday
today_value = shares * nav_today
daily_profit = today_value - yesterday_value
# 对比报告中的数字
```

**实测错误案例（08-28报告）**：
| 基金 | 报告显示 | 正确值 | 错误原因 |
|:--|:--|:--|:--|
| 011036稀土C | +0.00 | -2.70 | NAV数据源问题 |
| 025209永赢半导体C | 昨日507 | 昨日500 | 用了08-26 NAV |
| 025422浦银数字经济C | 昨日519 | 昨日500 | 用了08-26 NAV |

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
