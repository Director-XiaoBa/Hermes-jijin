# 基金计算规则（2026-08-27 修正）

## T+1 规则（核心规则）

**基金的基本规则：**
1. 今天3点前买入 → 明天才出净值 → 收益从明天开始算
2. 今天买入的基金，市值 = 投入金额（因为明天才有净值）
3. 明天出净值后，才能用公式计算真实市值

**正确逻辑：**
```python
from datetime import date

today = date.today()
buy_date = position['buy_date']  # 从trades表获取

is_today_buy = (buy_date == today)

if is_today_buy:
    # 今天买入，明天才出净值，市值=投入金额
    market_value = principal  # 500元
    profit = 0
    profit_rate = 0
else:
    # 非今天买入，用净值计算市值
    shares = principal / buy_nav
    market_value = current_nav * shares
    profit = market_value - principal
    profit_rate = (current_nav / buy_nav - 1) * 100
```

## 市值计算公式

**正确的公式：**
```
市值 = 投入金额 / 买入净值 × 当前净值
盈亏 = 市值 - 投入金额
盈亏率 = (当前净值 / 买入净值 - 1) × 100%
```

**错误的公式（不要用）：**
```
❌ 资产 = 总投入 + 总投入 × 今日涨跌幅  （这只算了今天，忽略了历史涨跌）
❌ impact = principal * nav_return / 100  （这只是今日涨跌的收益，不是总盈亏）
```

## 今日收益计算

**正确的公式：**
```
今日收益 = 今日市值 - 昨日市值
今日市值 = 份额 × 今日净值
昨日市值 = 份额 × 昨日净值
```

**错误的公式（不要用）：**
```
❌ 今日收益 = 本金 × 今日涨跌幅%  （这只是今日涨跌的收益，不是真实收益）
```

## 验证案例（2026-08-27）

### 017470 科创芯片C
- 买入日期：8月21日
- 买入净值：2.8526
- 投入金额：1000元
- 买入份额：1000 / 2.8526 = 350.57份
- 昨日净值（8月26日）：2.7995
- 今日净值（8月27日）：2.9202
- 昨日市值：350.57 × 2.7995 = 981.60元
- 今日市值：350.57 × 2.9202 = 1023.70元
- 今日收益：1023.70 - 981.60 = +42.10元 ✅

### 025209 永赢半导体智选C
- 买入日期：8月27日（今天）
- 买入净值：2.4200
- 投入金额：500元
- 明天（8月28日）才出净值
- 昨日市值：500元（投入金额）
- 今日市值：500元（投入金额）
- 今日收益：0元 ✅

## 夏普比率计算

**问题：** 数据不足时（只有1-2天），std_dev极小导致夏普比率计算出999.99

**解决方案：** 当std_dev < 0.001时返回0
```python
if std_dev < 0.001:
    return 0
```

## MySQL Decimal 类型处理（08-27教训）

pymysql从MySQL读取numeric/decimal字段时返回`decimal.Decimal`类型，需要显式转换：

**JSON序列化：**
```python
# ❌ 错误
json.dump(data, f)  # TypeError: Object of type Decimal is not JSON serializable

# ✅ 正确
json.dump(data, f, default=str)  # 所有非标准类型转字符串

# 或者显式转换
data['amount'] = float(data['amount'])
json.dump(data, f)
```

**计算时：**
```python
# ❌ 错误：float / Decimal 会报错
current_return = (fd['nav'] / pos['buy_nav'] - 1) * 100

# ✅ 正确：先转换为float
buy_nav = float(pos['buy_nav'])
current_return = (fd['nav'] / buy_nav - 1) * 100
```

**需要转换的常见字段：**
- `pos['buy_nav']` — pymysql返回Decimal
- `pos['amount']` — pymysql返回Decimal
- `total_invested` — SUM(amount)返回Decimal
