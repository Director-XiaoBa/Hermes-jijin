# Database Audit Report — 2026-09-02

## Audit Scope

Full schema consistency audit of `fund_research` MySQL database (31 tables + 1 view).

## Methodology

1. `SHOW TABLES` — list all tables
2. `DESCRIBE <table>` — compare columns with script INSERT/SELECT
3. `information_schema.KEY_COLUMN_USAGE` — check foreign keys
4. `grep -rn '<table>' ~/.hermes/scripts/fund_*.py` — confirm scripts reference each table

## Tables Inventory (31 tables + 1 view)

### Core Tables (19 original)
| Table | Status | Script Reference |
|:--|:--|:--|
| funds | ✅ OK | fund_common.py |
| nav_daily | ✅ OK | pipeline, fund_nav_update.py |
| market_daily | ✅ OK | pipeline |
| events | ✅ OK | fund_event_collect.py |
| signals | ✅ OK | skill doc |
| trades | ✅ OK | fund_common.py |
| ai_recommendations | ✅ OK | pipeline |
| decisions | ✅ OK | fund_common.py |
| strategy_backtest | ✅ OK | skill doc |
| sector_flow_daily | ✅ OK | pipeline |
| sector_return_daily | ✅ OK | pipeline |
| north_flow_daily | ✅ OK | pipeline |
| margin_trading_daily | ✅ OK | pipeline |
| etf_flow_daily | ✅ OK | pipeline |
| signal_resonance | ✅ OK | pipeline |
| predictions | ✅ OK | skill doc |
| improvement_log | ✅ OK | skill doc |
| monthly_stats | ✅ OK | skill doc |
| kol_tracking | ✅ OK | skill doc |

### Additional Tables
| Table | Status | Script Reference |
|:--|:--|:--|
| portfolio_daily | ✅ OK | fund_portfolio_tracker.py |
| catalyst_analysis | ✅ OK | fund_event_collect.py (_sync_to_catalyst) |
| market_snapshot | ✅ OK | pipeline |
| monthly_strategy | ✅ OK | monthly_strategy.py (1 row) |
| strategy_evolution | ⚠️ unclear | — |
| daily_predictions | ⚠️ unclear | — |
| fund_sector_map | ⚠️ unclear | — |
| signal_stats | ⚠️ unclear | — |
| **industry_trend_signals** | **⚠️ ORPHANED** | **No scripts** |
| **industry_trend_positions** | **⚠️ ORPHANED** | **No scripts** |
| v_catalyst_summary | ✅ OK (view) | — |

## Key Findings

### 1. Orphaned Tables (0 rows, no scripts)

**`industry_trend_signals`**
- Schema: id, signal_date, theme, trend_score, signals_json, related_funds, source_notes, created_at
- 0 rows. No Python script references this table.
- Likely created for monthly_strategy.py's `scan_industry_trends()` but never wired.

**`industry_trend_positions`**
- Schema: id, fund_code, fund_name, theme, entry_date, entry_nav, entry_amount, thesis, invalidation_signal, status, exit_date, exit_nav, exit_pnl_pct, exit_reason
- 0 rows. No Python script references this table.
- Designed for position tracking by theme, never implemented.

### 2. No Foreign Keys

Zero foreign key constraints exist. All cross-table references (trades→funds, nav_daily→funds, etc.) are application-level only.

### 3. trades vs fund_common.py — PERFECT MATCH

fund_common.py `get_holdings()`:
```sql
SELECT fund_code, fund_name, trade_date, amount, nav_price, stop_loss, take_profit, notes
FROM trades WHERE direction = '买入' AND trade_status = '持有'
```
All columns exist in trades table. ✅

fund_common.py `add_trade()`:
```sql
INSERT INTO trades (fund_code, fund_name, trade_date, direction, amount, nav_price, reason, signal_source, stop_loss, take_profit, trade_status, notes)
```
All columns exist. ✅

### 4. events vs fund_event_collect.py — PERFECT MATCH

Script INSERT columns: event_time, event_type, title, industry, direction, intensity, duration, related_funds, source, verified

Actual events columns match exactly. Key confirmations:
- `event_time` (datetime) — NOT `event_date` ✅
- `intensity` (tinyint) — NOT `impact_level` ✅
- `related_funds` (text, JSON array) — NOT `fund_code` ✅

### 5. monthly_strategy — CORRECTLY WIRED

monthly_strategy.py INSERT uses: strategy_month, generated_at, strategy_json, mainlines_json, macro_calendar_json
All columns exist. 1 row of data present. ✅

### 6. sector_flow_daily — EXTRA COLUMNS

Table has columns beyond what the skill doc describes:
- super_large_netflow, large_netflow, medium_netflow, small_netflow (size-based flow)
- main_pct (percentage)
These are present in the table but not documented in the skill.

## Recommendations

1. **Wire orphaned tables or drop them**: `industry_trend_signals` and `industry_trend_positions` should either get scripts that write to them, or be dropped to reduce confusion.
2. **Document strategy_evolution, daily_predictions, signal_stats**: These tables exist but their purpose and script references are unclear.
3. **Consider adding foreign keys**: While the current no-FK design works, adding FKs on trades.fund_code→funds.code and nav_daily.fund_code→funds.code would prevent orphaned data.
