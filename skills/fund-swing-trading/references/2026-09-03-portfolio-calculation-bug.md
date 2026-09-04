# Portfolio市值计算Bug分析（09-03）

## 问题描述

系统计算的基金总市值与支付宝实际显示不一致，差异约37元。

## 根因分析

`fund_common.py` 的 `get_holdings()` 函数存在计算错误：

### 当前实现（错误）
```python
# SQL查询
SELECT t.fund_code, t.nav_price, agg.total_amount
FROM trades t
INNER JOIN (
    SELECT fund_code, SUM(amount) AS total_amount
    FROM trades WHERE direction = '买入' AND trade_status = '持有'
    GROUP BY fund_code
) agg ON t.fund_code = agg.fund_code
INNER JOIN (
    SELECT fund_code, MAX(trade_date) AS trade_date
    FROM trades WHERE direction = '买入' AND trade_status = '持有'
    GROUP BY fund_code
) latest ON t.fund_code = latest.fund_code AND t.trade_date = latest.trade_date
```

**问题**：`t.nav_price` 取的是**最后一条记录的买入价**，不是加权平均成本。

### 实际案例

以017470（科创芯片C）为例：
- 第1次买入：1000元 @ 2.8526 (2026-08-21)
- 第2次买入：300元 @ 2.8242 (2026-09-01)
- 总金额：1300元

**系统计算**：
- 使用买入价：2.8242（最后一条记录）
- 当前净值：2.7776
- 系统市值：1300 / 2.8242 × 2.7776 = 1278.55元

**正确计算**：
- 加权平均成本：(1000×2.8526 + 300×2.8242) ÷ 1300 = 2.8460
- 正确市值：1300 / 2.8460 × 2.7776 = 1268.74元

**差异**：1278.55 - 1268.74 = 9.81元

### 影响范围

所有分批买入的基金都会受影响：
- 017470：差异-9.81元
- 017811：差异-2.82元
- 025209：差异-20.64元
- **总差异**：-33.28元

## 支付宝对比数据

支付宝截图显示：
- 总市值：4,490.40元
- 持有收益：-109.60元

系统计算：
- 总市值：4,520.52元（使用最后买入价）
- 正确市值：4,487.25元（使用加权平均成本）
- 与支付宝差异：4,490.40 - 4,487.25 = 3.15元（精度差异）

## 修复方案

### 方案1：修改get_holdings()返回加权平均成本

```python
def get_holdings() -> List[Dict]:
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT
                    t.fund_code,
                    t.fund_name,
                    latest.trade_date,
                    agg.total_amount,
                    agg.avg_cost as nav_price,  -- 使用加权平均成本
                    t.stop_loss,
                    t.take_profit,
                    t.notes
                FROM trades t
                INNER JOIN (
                    SELECT 
                        fund_code, 
                        SUM(amount) AS total_amount,
                        SUM(amount * nav_price) / SUM(amount) as avg_cost
                    FROM trades
                    WHERE direction = '买入' AND trade_status = '持有'
                    GROUP BY fund_code
                ) agg ON t.fund_code = agg.fund_code
                INNER JOIN (
                    SELECT fund_code, MAX(trade_date) AS trade_date
                    FROM trades
                    WHERE direction = '买入' AND trade_status = '持有'
                    GROUP BY fund_code
                ) latest ON t.fund_code = latest.fund_code
                         AND t.trade_date = latest.trade_date
                WHERE t.direction = '买入' AND t.trade_status = '持有'
                ORDER BY t.trade_date
            """)
            # ... 返回结果
    finally:
        conn.close()
```

### 方案2：在返回值中增加avg_cost字段

保留原有nav_price（最后买入价），新增avg_cost字段供需要精确计算的场景使用。

## 验证方法

对比支付宝数据是发现此类计算bug的有效方法：
1. 截图支付宝基金页面
2. 逐只对比系统计算市值 vs 支付宝显示市值
3. 差异大于1元的基金需要检查计算逻辑

## 相关文件

- `fund_common.py`：get_holdings()函数
- `fund_portfolio_tracker.py`：get_current_holdings()方法
- `fund_report.py`：晚间报告生成
- `fund_scan_data.py`：14:00扫描报告

## 状态

- **发现时间**：2026-09-03
- **影响**：所有分批买入基金的市值计算不准确
- **修复优先级**：高（影响用户看到的收益数据）
- **待修复**：需要修改fund_common.py的get_holdings()函数
