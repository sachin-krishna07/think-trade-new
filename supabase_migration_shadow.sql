-- ============================================================
-- Shadow trades — run this in the Supabase SQL Editor
-- BEFORE restarting the backend with the new code.
--
-- A "shadow" trade is one whose SL is wider than MAX_SL_PCT (2.5%) of its
-- position size. It is recorded in full so the setup can be studied later,
-- but is excluded from the wallet, performance stats and every risk counter,
-- and never reaches the exchange in live mode.
--
-- Safe to re-run: IF NOT EXISTS guards the column.
-- ============================================================

ALTER TABLE trades
  ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN NOT NULL DEFAULT FALSE;

-- Every existing row is a real trade — DEFAULT FALSE already backfills them,
-- so historical PnL and win-rate are untouched by this migration.

-- Stats queries filter on (mode, status, is_shadow); index that path.
CREATE INDEX IF NOT EXISTS trades_shadow_idx
  ON trades (mode, status, is_shadow);

-- ─── Verify ─────────────────────────────────────────────────
-- Expect: is_shadow | boolean | NO | false
SELECT column_name, data_type, is_nullable, column_default
FROM   information_schema.columns
WHERE  table_name = 'trades' AND column_name = 'is_shadow';
