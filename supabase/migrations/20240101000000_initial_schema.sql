-- ============================================================
-- ThinkTrade CryptoBot — Supabase Schema
-- Run this entire file in Supabase SQL Editor
-- ============================================================

-- Drop existing tables if rebuilding
DROP TABLE IF EXISTS performance CASCADE;
DROP TABLE IF EXISTS signals CASCADE;
DROP TABLE IF EXISTS positions CASCADE;
DROP TABLE IF EXISTS trades CASCADE;
DROP TABLE IF EXISTS wallet CASCADE;
DROP TABLE IF EXISTS bot_config CASCADE;

-- ─── Bot Config ─────────────────────────────────────────────
CREATE TABLE bot_config (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  is_running    BOOLEAN DEFAULT FALSE,
  mode          TEXT DEFAULT 'demo' CHECK (mode IN ('demo', 'live')),
  style         TEXT DEFAULT 'scalping' CHECK (style IN ('scalping', 'swing', 'vwapfade')),
  capital_pct   DECIMAL(5,2) DEFAULT 1.0,
  selected_pairs TEXT[] DEFAULT ARRAY['BTC','ETH','SOL','BNB','XRP'],
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO bot_config DEFAULT VALUES;

-- ─── Virtual Wallet ─────────────────────────────────────────
CREATE TABLE wallet (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  mode            TEXT NOT NULL DEFAULT 'demo',
  balance         DECIMAL(15,4) NOT NULL DEFAULT 10000,
  initial_balance DECIMAL(15,4) NOT NULL DEFAULT 10000,
  total_pnl       DECIMAL(15,4) DEFAULT 0,
  total_pnl_pct   DECIMAL(8,4) DEFAULT 0,
  daily_pnl       DECIMAL(15,4) DEFAULT 0,
  daily_pnl_pct   DECIMAL(8,4) DEFAULT 0,
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO wallet (mode, balance, initial_balance) VALUES ('demo', 10000, 10000);
INSERT INTO wallet (mode, balance, initial_balance) VALUES ('live', 0, 0);

-- ─── Trades ─────────────────────────────────────────────────
CREATE TABLE trades (
  id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  mode              TEXT NOT NULL,
  pair              TEXT NOT NULL,
  direction         TEXT NOT NULL CHECK (direction IN ('long','short')),
  style             TEXT NOT NULL,
  entry_price       DECIMAL(15,6),
  exit_price        DECIMAL(15,6),
  quantity          DECIMAL(15,6),
  position_size_usd DECIMAL(15,4),
  leverage          DECIMAL(5,2),
  risk_amount       DECIMAL(15,4),
  sl_price          DECIMAL(15,6),
  tp_price          DECIMAL(15,6),
  pnl               DECIMAL(15,4),
  pnl_pct           DECIMAL(8,4),
  r_multiple        DECIMAL(8,4),
  status            TEXT DEFAULT 'open' CHECK (status IN ('open','closed','cancelled')),
  exit_reason       TEXT,
  signals_at_entry  JSONB,
  capital_pct       DECIMAL(5,2),
  entry_time        TIMESTAMPTZ DEFAULT NOW(),
  exit_time         TIMESTAMPTZ,
  duration_seconds  INTEGER,
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Open Position ──────────────────────────────────────────
CREATE TABLE positions (
  id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  trade_id            UUID REFERENCES trades(id) ON DELETE CASCADE,
  pair                TEXT NOT NULL,
  direction           TEXT NOT NULL,
  entry_price         DECIMAL(15,6),
  current_price       DECIMAL(15,6),
  quantity            DECIMAL(15,6),
  position_size_usd   DECIMAL(15,4),
  sl_price            DECIMAL(15,6),
  tp_price            DECIMAL(15,6),
  sl_pct              DECIMAL(8,4),
  tp_pct              DECIMAL(8,4),
  unrealized_pnl      DECIMAL(15,4) DEFAULT 0,
  unrealized_pnl_pct  DECIMAL(8,4) DEFAULT 0,
  highest_pnl         DECIMAL(15,4) DEFAULT 0,
  trailing_sl         DECIMAL(15,6),
  breakeven_hit       BOOLEAN DEFAULT FALSE,
  lock_profit_hit     BOOLEAN DEFAULT FALSE,
  status              TEXT DEFAULT 'active',
  opened_at           TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Live Signals (rolling, 1 row per pair) ─────────────────
CREATE TABLE signals (
  id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  pair              TEXT NOT NULL UNIQUE,
  price             DECIMAL(15,6),
  trend_regime      INTEGER DEFAULT 0,
  trend_direction   TEXT DEFAULT 'neutral',
  adx_value         DECIMAL(8,4),
  ema9_value        DECIMAL(15,6),
  ema21_value       DECIMAL(15,6),
  cvd_divergence    INTEGER DEFAULT 0,
  cvd_value         DECIMAL(15,4),
  vwap_deviation    INTEGER DEFAULT 0,
  vwap_value        DECIMAL(15,6),
  vwap_dev_pct      DECIMAL(8,4),
  dom_imbalance     INTEGER DEFAULT 0,
  dom_ratio         DECIMAL(8,4),
  rsi2_extreme      INTEGER DEFAULT 0,
  rsi2_value        DECIMAL(8,4),
  liquidity_sweep   INTEGER DEFAULT 0,
  sweep_type        TEXT,
  fair_value_gap    INTEGER DEFAULT 0,
  fvg_type          TEXT,
  fvg_level         DECIMAL(15,6),
  total_score       INTEGER DEFAULT 0,
  signal_direction  TEXT DEFAULT 'none',
  atr_value         DECIMAL(15,6),
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO signals (pair) VALUES ('BTC'),('ETH'),('SOL'),('BNB'),('XRP')
ON CONFLICT (pair) DO NOTHING;

-- ─── Daily Performance ──────────────────────────────────────
CREATE TABLE performance (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  date          DATE DEFAULT CURRENT_DATE,
  mode          TEXT NOT NULL,
  trades_total  INTEGER DEFAULT 0,
  trades_won    INTEGER DEFAULT 0,
  trades_lost   INTEGER DEFAULT 0,
  win_rate      DECIMAL(5,2) DEFAULT 0,
  total_pnl     DECIMAL(15,4) DEFAULT 0,
  avg_r         DECIMAL(8,4) DEFAULT 0,
  max_drawdown  DECIMAL(8,4) DEFAULT 0,
  best_trade    DECIMAL(15,4) DEFAULT 0,
  worst_trade   DECIMAL(15,4) DEFAULT 0,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(date, mode)
);

-- ─── Enable Realtime ────────────────────────────────────────
ALTER PUBLICATION supabase_realtime ADD TABLE wallet;
ALTER PUBLICATION supabase_realtime ADD TABLE positions;
ALTER PUBLICATION supabase_realtime ADD TABLE trades;
ALTER PUBLICATION supabase_realtime ADD TABLE signals;
ALTER PUBLICATION supabase_realtime ADD TABLE bot_config;
ALTER PUBLICATION supabase_realtime ADD TABLE performance;

-- ─── Disable RLS (personal bot, no multi-user) ──────────────
ALTER TABLE bot_config DISABLE ROW LEVEL SECURITY;
ALTER TABLE wallet DISABLE ROW LEVEL SECURITY;
ALTER TABLE trades DISABLE ROW LEVEL SECURITY;
ALTER TABLE positions DISABLE ROW LEVEL SECURITY;
ALTER TABLE signals DISABLE ROW LEVEL SECURITY;
ALTER TABLE performance DISABLE ROW LEVEL SECURITY;
