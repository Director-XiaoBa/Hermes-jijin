# Portfolio Sync Pitfall — 硬编码 vs 动态读取 (2026-08-27)

## 问题概述

**用户原话：** "不是一个好系统"、"需要你检查一下，如有不对需重新设计"、"就应该跟着我们的数据库，实时嘛对不对"

**核心问题：** 多个脚本使用硬编码的基金代码/持仓数据，而不是从 `trades` 表动态读取。

## ✅ 修复状态（08-27完成）

| 脚本 | 修复状态 | 说明 |
|:---|:---|:---|
| **fund_report.py** | ✅ 已修复 | 从trades表动态读取 |
| **fund_daily_pipeline_v2.py** | ✅ 已修复 | 3处硬编码替换为fund_common.py |
| **fund_event_collect.py** | ✅ 已修复 | HELD_FUNDS/WATCHLIST_FUNDS替换为fund_common.py |
| **fund_scan_data.py** | ✅ 已修复 | CODES/FUND_SECTOR替换为fund_common.py |

## ✅ 解决方案：fund_common.py 共享模块

**路径：** `~/.hermes/scripts/fund_common.py`

**所有脚本统一使用这个模块获取数据：**
```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_holdings, get_fund_etf_map, get_fund_sectors, get_watchlist
```

**核心函数：**
- `get_holdings()` — 从trades表读取当前持仓
- `get_fund_etf_map()` — 从funds表读取ETF映射
- `get_fund_sectors()` — 从funds表读取行业标签
- `get_watchlist()` — 从funds表读取观察列表
- `get_all_tracked_funds()` — 获取所有跟踪的基金代码（持仓+观察列表）
- `add_fund()` — 添加新基金到funds表
- `add_trade()` — 添加交易记录到trades表
- `add_decision()` — 记录决策日志

## ✅ 数据流向架构

```
trades表（唯一数据源）
    ↓
fund_common.py（共享模块）
    ↓
fund_report.py（收益报告）✅
fund_daily_pipeline_v2.py（技术分析）✅
fund_event_collect.py（事件收集）✅
fund_scan_data.py（信号扫描）✅
```

**好处：** 用户买入/卖出后，所有脚本自动生效，无需手动改代码。

## T+1确认逻辑

```python
from datetime import date

def calculate_profit(position, current_nav):
    today = date.today()
    buy_date = position['first_buy_date']
    
    # 今日买入，不计算收益
    if buy_date == today:
        return {
            'profit': 0,
            'profit_rate': 0,
            'status': '今日买入，明日计收益'
        }
    
    # 正常计算
    profit = (current_nav - position['buy_nav']) / position['buy_nav'] * position['total_invested']
    profit_rate = (current_nav - position['buy_nav']) / position['buy_nav'] * 100
    
    return {
        'profit': profit,
        'profit_rate': profit_rate,
        'status': '正常'
    }
```

## 验证清单

每次修改持仓计算逻辑后，必须验证：
- [x] 持仓数据从trades表动态读取（不是硬编码）✅ 08-27完成
- [x] 今日买入的基金显示"明日计收益"（不是当天涨幅）✅ 08-27完成
- [x] 总投入与trades表SUM(amount)一致 ✅ 08-27完成
- [x] 持有天数计算正确（含买入日）✅ 08-27完成
- [x] 7天内卖出费率1.5%，7天后0% ✅ 08-27完成
- [x] **所有脚本**都从trades表读取（不只是fund_report.py）✅ 08-27完成

## 关联定时任务

- 15:30 基金每日Pipeline入库（fund_daily_pipeline_v2.py）
- 15:50 基金每日复盘（验证上一个交易日操作）
- 22:30 基金最终净值更新（用官方净值+推送收益报告）

**注意：** 所有定时任务的收益报告都必须从trades表动态读取持仓，不能硬编码。

## 新增数据库对象（08-27）

### funds表扩展字段
```sql
ALTER TABLE funds ADD COLUMN etf_code VARCHAR(10) COMMENT '对应ETF代码';
ALTER TABLE funds ADD COLUMN sectors VARCHAR(200) COMMENT '行业标签，逗号分隔';
ALTER TABLE funds ADD COLUMN is_watchlist TINYINT DEFAULT 0 COMMENT '0=持仓 1=观察列表';
ALTER TABLE funds ADD COLUMN watchlist_reason TEXT COMMENT '观察理由';
ALTER TABLE funds ADD COLUMN watchlist_conditions TEXT COMMENT '进场条件JSON';
```

### decisions表（决策日志）
```sql
CREATE TABLE decisions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    decision_type ENUM('buy','sell','hold','watch') NOT NULL,
    decision_date DATE NOT NULL,
    reason TEXT COMMENT '决策依据',
    signal_source VARCHAR(50) COMMENT '信号来源：老道/AI/自主',
    market_state TEXT COMMENT '当时市场状态',
    confidence DECIMAL(3,2) COMMENT '信心度0-1',
    actual_outcome DECIMAL(8,4) COMMENT '实际结果',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fund_code (fund_code),
    INDEX idx_decision_date (decision_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='决策日志';
```

### strategy_backtest表（策略回测）
```sql
CREATE TABLE strategy_backtest (
    id INT AUTO_INCREMENT PRIMARY KEY,
    strategy_name VARCHAR(50) NOT NULL,
    fund_code VARCHAR(10) NOT NULL,
    backtest_period VARCHAR(20) COMMENT '回测区间',
    total_trades INT COMMENT '总交易次数',
    win_rate DECIMAL(5,2) COMMENT '胜率%',
    avg_return DECIMAL(8,4) COMMENT '平均收益率%',
    max_drawdown DECIMAL(8,4) COMMENT '最大回撤%',
    sharpe_ratio DECIMAL(5,2) COMMENT '夏普比率',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_strategy_name (strategy_name),
    INDEX idx_fund_code (fund_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略回测记录';
```

## 调试技巧

### pymysql Decimal类型问题
pymysql从MySQL读取numeric/decimal字段时返回`decimal.Decimal`类型，需要转换：
```python
# 计算时
buy_nav = float(pos['buy_nav'])  # Decimal → float

# JSON序列化时
json.dump(data, f, default=str)  # 所有非标准类型转字符串
```

### get_holdings()必须包含nav_price
SQL查询必须包含nav_price字段，否则计算持仓收益时会除零：
```sql
SELECT fund_code, fund_name, trade_date, amount, nav_price,
       stop_loss, take_profit, notes
FROM trades 
WHERE direction = '买入' AND trade_status = '持有'
```
