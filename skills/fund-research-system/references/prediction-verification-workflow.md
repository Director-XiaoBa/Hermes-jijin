# Prediction Verification Workflow (09-02)

## Problem
The `predictions` table (written by 14:00 scan) had **zero automated verification**. Only `daily_predictions` was verified by the 22:45 cron job.

## Verification Logic

### For `predictions` table
```python
from datetime import timedelta

# Calculate verification date based on time_horizon
if '1d' in time_horizon:
    verify_after = prediction_date + timedelta(days=1)
elif '3d' in time_horizon:
    verify_after = prediction_date + timedelta(days=3)
elif '5d' in time_horizon:
    verify_after = prediction_date + timedelta(days=5)

# Verify when current_date >= verify_after
# Check actual_result, actual_direction, actual_return_pct, is_correct
```

### For `daily_predictions` table
```sql
-- The 22:45 cron job verifies by joining with nav_daily on target_date=CURDATE()
UPDATE daily_predictions dp
JOIN nav_daily nd ON dp.fund_code = nd.fund_code AND nd.trade_date = CURDATE()
SET dp.actual_nav = nd.nav,
    dp.actual_change_pct = nd.daily_return,
    dp.accuracy = CASE 
      WHEN ABS(dp.predicted_change_pct - nd.daily_return) < 1 THEN 'correct'
      WHEN SIGN(dp.predicted_change_pct) = SIGN(nd.daily_return) THEN 'partial'
      ELSE 'wrong'
    END,
    dp.validated_at = NOW()
WHERE dp.target_date = CURDATE();
```

## Accuracy Results (09-02 manual verification of 37 predictions)

### By Time Horizon
| Horizon | Correct | Total | Accuracy |
|:--|:--|:--|:--|
| 5d | 20 | 20 | **100%** |
| 1d | 10 | 16 | 62.5% |
| 3d | 4 | 10 | **40%** |

### By Prediction Type
| Type | Correct | Total | Accuracy |
|:--|:--|:--|:--|
| event_impact | 10 | 12 | **83.3%** |
| direction | 22 | 30 | 73.3% |
| exit | 1 | 1 | 100% |
| entry | 1 | 3 | 33.3% |

### Key Findings
1. **5d predictions are very reliable** (100%) — weekly direction calls are strong
2. **3d predictions are worst** (40%) — medium-term timing is unreliable
3. **event_impact judgments are strong** (83.3%) — the system correctly identifies event consequences
4. **entry predictions are weakest** (33.3%) — new position recommendations need improvement

## Cron Job Coverage Gap

| Table | Write Cron | Verify Cron | Gap |
|:--|:--|:--|:--|
| `predictions` | 14:00 scan | None | **No automated verification** |
| `daily_predictions` | Sun 09:00 | 22:45 daily | Covered (same-day only) |

## Fix Needed
Create a verification cron job for the `predictions` table, or extend the existing 22:45 job to also verify predictions where `verified_at IS NULL AND prediction_date + time_horizon <= CURDATE()`.
