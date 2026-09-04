# 14:00 扫描脚本 T+1 架构（08-28 修复记录）

## 问题背景

08-28 用户发现14:00报告有严重数据错误：
1. 持仓基金数量不对——观察列表基金混入持仓分析
2. T+1基金（08-27买入）的"3日累计"包含了买入前的历史涨跌
3. ETF盘中估算是硬编码的，缺017811映射
4. 资金流向信号包含已卖出的基金（018345/018123）

## 根因

`fund_common.py` 的 `get_all_tracked_funds()` 返回持仓+观察列表共8只基金，`fund_scan_data.py` 用它作为CODES列表，导致观察列表基金被当作持仓分析。

## 修复方案（三层分离）

### 1. fund_common.py 新增函数

```python
def get_holdings_for_scan() -> List[Dict]:
    """获取当前持仓基金+买入日期（用于14:00扫描，T+1计算）
    返回: [{fund_code, fund_name, buy_date, total_amount, etf_code}, ...]
    """
    holdings = get_holdings()
    etf_map = get_fund_etf_map()
    return [{
        'fund_code': h['fund_code'],
        'fund_name': h['fund_name'],
        'buy_date': h['buy_date'],
        'total_amount': h['total_amount'],
        'etf_code': etf_map.get(h['fund_code']),
    } for h in holdings]

def get_watchlist_codes() -> List[str]:
    """获取观察列表基金代码（不含持仓）"""
    return [w['code'] for w in get_watchlist()]
```

### 2. fund_scan_data.py 分区逻辑

| Section | 数据源 | 显示内容 |
|:--|:--|:--|
| 基金净值 | `get_holdings_for_scan()` | 只显示持仓5只，含T+1买入后累计 |
| 观察列表净值 | `get_watchlist_codes()` | 单独成节标注"仅参考" |
| ETF估算 | 持仓ETF映射动态获取 | 按ETF分组去重 |
| 资金流向信号 | `get_holdings_for_scan()` 过滤 | 只显示持仓基金 |
| 信号共振 | `get_holdings()` | 只显示持仓基金 |

### 3. T+1净值计算逻辑

```python
# 关键：只累计买入日期之后的涨跌
buy_ts = datetime.strptime(buy_date_str, '%Y-%m-%d').timestamp() * 1000
post_buy = [x for x in arr if x['x'] >= buy_ts]

if len(post_buy) >= 2:
    # 有持仓数据：累计买入后涨跌
    cum = 1.0
    for x in post_buy[1:]:  # 跳过买入当天
        cum *= (1 + x.get('equityReturn', 0) / 100)
    cum_label = f"持仓{days}日{(cum-1)*100:+.2f}%"
    # 输出近8日涨跌供参考
    out.append(f"  {c} {name} {cum_label} | {hist}")
else:
    # T+1：净值未出，不输出买入前历史涨跌
    out.append(f"  {c} {name} T+1未出净值")
    # ⚠️ 不跟历史涨跌！避免agent误填入报告表格
```

### 4. Cron Prompt 行为约束

T+1基金在报告表格中必须遵守：
- "买入后累计"列 → "T+1未出净值"
- "近8日涨跌"列 → 留空或"—"
- "估算后累计"列 → "待确认"

**原因：** 即使脚本不输出历史涨跌，agent仍可能从ETF估算区或自身知识补充历史数据到表格中。必须在prompt中明确禁止。

## 验证清单

修改fund_scan_data.py后必须验证：
- [ ] 持仓基金数量 = trades表中trade_status='持有'的记录数
- [ ] 观察列表基金单独成节
- [ ] T+1基金不显示买入前历史涨跌
- [ ] 资金流向信号不含已卖出基金
- [ ] ETF估算覆盖所有有etf_code的持仓基金
- [ ] 同ETF的基金合并显示（防重复）
