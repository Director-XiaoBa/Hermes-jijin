# 持仓收益计算实现（含C类基金手续费）

## 数据来源

### 用户持仓配置（硬编码在Pipeline中）
```python
POSITIONS = {
    '017470': {'name': '科创芯片C', 'buy_nav': 2.8526, 'amount': 1000, 'buy_date': '2026-08-21'},
    '017811': {'name': '东方AI', 'buy_nav': 3.2931, 'amount': 500, 'buy_date': '2026-08-25'},
    '011036': {'name': '稀土C', 'buy_nav': 1.2054, 'amount': 500, 'buy_date': '2026-08-21'},
    '018345': {'name': '机器人C', 'buy_nav': 1.1584, 'amount': 200, 'buy_date': '2026-08-21'},
    '018123': {'name': '数字经济C', 'buy_nav': 1.9648, 'amount': 500, 'buy_date': '2026-08-21'},
}
```

### 数据库查询
```sql
-- 获取最新净值
SELECT nav FROM nav_daily WHERE fund_code=%s ORDER BY trade_date DESC LIMIT 1
```

## 计算逻辑（含手续费）

```python
total_fee = 0
for fund_code, pos in POSITIONS.items():
    current_nav = query_latest_nav(fund_code)
    shares = pos['amount'] / pos['buy_nav']
    current_value = current_nav * shares
    profit = current_value - pos['amount']
    profit_rate = (current_nav / pos['buy_nav'] - 1) * 100
    
    # 计算持有天数和手续费
    buy_date = datetime.datetime.strptime(pos['buy_date'], '%Y-%m-%d').date()
    hold_days = (today - buy_date).days
    
    # C类基金手续费规则：7天内1.5%，7天后0%
    fee_rate = 1.5 if hold_days <= 7 else 0
    fee_amount = current_value * fee_rate / 100
    net_value = current_value - fee_amount
    
    total_invested += pos['amount']
    total_current += current_value
    total_fee += fee_amount

total_profit = total_current - total_invested
total_profit_rate = (total_current / total_invested - 1) * 100
actual_profit = total_profit - total_fee
actual_profit_rate = (total_current - total_fee - total_invested) / total_invested * 100
```

## C类基金手续费规则

| 持有天数 | 手续费率 | 说明 |
|:--|:--|:--|
| **≤7天** | **1.5%** | 惩罚性手续费（支付宝C类基金） |
| **>7天** | **0%** | C类基金无赎回费 |

**注意：** 买入当天不算，从买入次日开始计算。

## 输出文件

`~/user_files/documents/portfolio_profit.json`

## 推送模板

```
📊 今日收益报告（MM-DD）

【持仓收益明细】
| 基金 | 买入日期 | 持有天数 | 买入价 | 当前价 | 涨幅 | 当前市值 | 手续费 | 到手金额 |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| 芯片C | 08-21 | 5天 | 2.85 | 2.75 | -3.4% | ¥966 | -¥14.49 | ¥951 |
| AI | 08-25 | 1天 | 3.29 | 3.29 | 0% | ¥500 | -¥7.50 | ¥492 |
| ...

【总收益统计】
- 总投入: ¥X
- 当前市值: ¥X
- 总手续费: -¥X
- 总到手金额: ¥X
- 实际亏损: -¥X (X%)

【7天内卖出提醒】
⚠️ 017811 东方AI 仅持有1天，卖出需扣1.5%手续费
✅ 其他基金持有5天，还差2天免手续费
```

## 注意事项

1. 净值更新时间：基金官方净值在晚上8-9点更新，21:00 Pipeline能拿到当天净值
2. 持仓变动：用户买卖后需要更新POSITIONS配置
3. **C类基金手续费：** 7天内卖出扣1.5%，7天后卖出不扣
4. **到手金额 = 当前市值 - 手续费**
5. **实际盈亏 = 表面盈亏 - 手续费**
