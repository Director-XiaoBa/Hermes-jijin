# 09-02 Session: System Architecture Upgrade to v2.1

## What happened
Massive overhaul of the fund management system from reactive daily scanning to three-layer proactive architecture.

## Key changes

### Architecture
- Three-layer: Monthly strategy → Weekly tactics → Daily execution
- Mode C (Industry Trend): 30-90 day hold, exit on thesis invalidation
- Position management: ¥5000 cap, conviction-based sizing
- Parallel data collection (8 sources, 6/8 succeed, ~5s)

### New scripts
- monthly_strategy.py, pre_trade_check.py, position_manager.py
- mode_c_backtest.py, info_pipeline.py, fund_data_collector.py
- report_format_check.py

### Cron optimization
- 14:00+14:05 merged, 14:40 made conditional
- Saturday review + cognitive progress merged
- All version refs updated to v2.0

### MySQL tables (6 new)
- monthly_strategy, industry_trend_signals, industry_trend_positions
- position_history, dragon_tiger, event_calendar

## Key learnings

### User preferences
- Iterative verification required after every change
- Response-type > Prediction-type for sector discovery
- Extract principles, not chase specific events
- Report format must be consistent via templates
- "全面检查" means check LOGIC and DATA QUALITY, not just syntax/existence
- User wants "取其精华去其糟粕" - don't copy solutions wholesale, adapt them

### Technical patterns
- Serial data collection → incomplete reports. Parallel with timeout/retry solves it.
- events table: event_time (not event_date), intensity (not impact_level), related_funds (JSON)
- pymysql: use DictCursor, not dictionary=True
- Push2 API needs retry logic (but cloud IPs are blocked entirely)
- MySQL strict mode: GROUP BY must include all non-aggregated columns, or use ANY_VALUE()
- fund_nav_update.py only computes indicators for current day - historical backfill needed

### Strategic insights
- Mode C backtest: post-news buy 30d = 2.7% win rate. Can't blindly chase.
- Cold sector: detect via sector fund flow "资金先到价格后动"
- 80/20: monthly strategy + 14:00 scan + pre-trade checklist = 80% of value
- System complexity is risk (8 cron had version mismatch post-upgrade)
- Prediction accuracy: 5d=100%, 1d=62.5%, 3d=40% - weekly predictions most reliable
- Attribution analysis: 83.3% accuracy on event-impact predictions
