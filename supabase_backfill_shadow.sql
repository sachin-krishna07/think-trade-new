-- ============================================================
-- Backfill: flag historical trades whose SL exceeded 2.5% of position,
-- then resync wallet + performance so every view agrees.
--
-- Run AFTER supabase_migration_shadow.sql.
-- Run the whole file top-to-bottom in one go.
--
-- Expected on the 19-trade demo history: 3 rows flagged
--   TST  6.26%  -9,260
--   TST  3.91%  -6,416
--   DUSK 2.78%  +2,851
-- Wallet total_pnl -12,208 -> +617, balance 87,792 -> 100,617
-- ============================================================

-- ─── 0. Backup (rollback safety net) ────────────────────────
DROP TABLE IF EXISTS trades_backup_shadow;
CREATE TABLE trades_backup_shadow AS SELECT * FROM trades;

DROP TABLE IF EXISTS wallet_backup_shadow;
CREATE TABLE wallet_backup_shadow AS SELECT * FROM wallet;

DROP TABLE IF EXISTS performance_backup_shadow;
CREATE TABLE performance_backup_shadow AS SELECT * FROM performance;


-- ─── 1. Flag the oversized-SL trades ────────────────────────
-- Mirrors risk_manager: is_shadow = (sl_distance / entry_price) > MAX_SL_PCT
UPDATE trades
SET    is_shadow = TRUE
WHERE  entry_price > 0
  AND  ABS(sl_price - entry_price) / entry_price > 0.025;


-- ─── 2. Resync wallet (mirrors get_total_pnl / get_today_pnl) ──
UPDATE wallet w
SET
  total_pnl = COALESCE((
      SELECT SUM(t.net_pnl) FROM trades t
      WHERE t.mode = w.mode AND t.status = 'closed' AND t.is_shadow = FALSE
  ), 0),
  balance = w.initial_balance + COALESCE((
      SELECT SUM(t.net_pnl) FROM trades t
      WHERE t.mode = w.mode AND t.status = 'closed' AND t.is_shadow = FALSE
  ), 0),
  daily_pnl = COALESCE((
      SELECT SUM(t.pnl) FROM trades t
      WHERE t.mode = w.mode AND t.status = 'closed' AND t.is_shadow = FALSE
        AND t.exit_time >= (date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata')
                            AT TIME ZONE 'Asia/Kolkata')
  ), 0),
  updated_at = NOW();

-- percentages derived from the values just written
UPDATE wallet
SET total_pnl_pct = CASE WHEN initial_balance > 0
                         THEN ROUND(total_pnl / initial_balance * 100, 4) ELSE 0 END,
    daily_pnl_pct = CASE WHEN initial_balance > 0
                         THEN ROUND(daily_pnl / initial_balance * 100, 4) ELSE 0 END;


-- ─── 3. Rebuild performance (mirrors upsert_performance) ────
-- Days that still have real trades
UPDATE performance p
SET trades_total = s.n,
    trades_won   = s.won,
    trades_lost  = s.n - s.won,
    win_rate     = ROUND(s.won::numeric / s.n * 100, 2),
    total_pnl    = s.pnl_sum,
    avg_r        = ROUND(COALESCE(s.avg_r, 0), 4),
    best_trade   = s.best,
    worst_trade  = s.worst
FROM (
    SELECT (exit_time AT TIME ZONE 'Asia/Kolkata')::date AS d,
           mode,
           COUNT(*)                          AS n,
           COUNT(*) FILTER (WHERE pnl > 0)   AS won,
           SUM(pnl)                          AS pnl_sum,
           AVG(r_multiple)                   AS avg_r,
           MAX(pnl)                          AS best,
           MIN(pnl)                          AS worst
    FROM   trades
    WHERE  status = 'closed' AND is_shadow = FALSE AND exit_time IS NOT NULL
    GROUP  BY 1, 2
) s
WHERE p.date = s.d AND p.mode = s.mode;

-- Days whose every trade became shadow — zero them so no stale row survives
UPDATE performance p
SET trades_total = 0, trades_won = 0, trades_lost = 0, win_rate = 0,
    total_pnl = 0, avg_r = 0, best_trade = 0, worst_trade = 0
WHERE NOT EXISTS (
    SELECT 1 FROM trades t
    WHERE t.status = 'closed' AND t.is_shadow = FALSE AND t.exit_time IS NOT NULL
      AND t.mode = p.mode
      AND (t.exit_time AT TIME ZONE 'Asia/Kolkata')::date = p.date
);


-- ─── 4. Verify ──────────────────────────────────────────────
SELECT pair,
       ROUND(ABS(sl_price - entry_price) / entry_price * 100, 2) AS sl_pct,
       net_pnl, exit_reason, is_shadow
FROM   trades
WHERE  is_shadow = TRUE
ORDER  BY sl_pct DESC;

SELECT mode, initial_balance, balance, total_pnl, total_pnl_pct, daily_pnl
FROM   wallet ORDER BY mode;

SELECT date, mode, trades_total, trades_won, win_rate, total_pnl
FROM   performance ORDER BY date DESC, mode;
