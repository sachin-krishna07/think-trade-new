import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEMO_INITIAL_BALANCE = float(os.getenv("DEMO_INITIAL_BALANCE", 10000))
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")

# ─── Pairs: display name → Binance symbol ───────────────────
# Blocklisted 2026-07-03 from 2.0 trade history (295 trades, 19-30 Jun):
# SUI(-$12.3k), NEAR(-$5.3k), TON(22% WR), OP(14% WR), POL(33% WR),
# HBAR(0% WR), NOT(25% WR), ARB(-$6.2k in 3.0). Re-run pair analysis
# monthly before re-adding.
#
# Rebuilt 2026-07-10 from a live-exchange volume screen (~150 pairs) —
# cross-checked against Binance's actual symbol list, blocklist re-applied,
# lowest-liquidity ~20 dropped. Sorted by screen volume, high to low.
#
# NOTE: tried switching market data (market_data.py) to Binance FUTURES
# WebSocket so futures-only listings (no spot market — ~35 candidates:
# HYPE, FARTCOIN, XMR, RIVER, AIN, etc.) could be included too. Verified
# live via a demo bot run: futures WS connects and depth/bookTicker stream
# fine, but @kline_* and @aggTrade never deliver a single message (tested
# up to 65s, vs. instant on spot) — price stayed stuck at 0.0 the whole
# run, which would silently block every entry. Reverted market data to the
# spot feed (proven working) and dropped the 35 spot-less coins from this
# list rather than ship an unverified data path. Re-attempt only after
# confirming @kline_/@aggTrade actually deliver on futures from the
# production VPS, not just this dev machine.
PAIRS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "XAUT": "XAUTUSDT",
    "PAXG": "PAXGUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
    "ZEC": "ZECUSDT",
    "SKL": "SKLUSDT",
    "DOGE": "DOGEUSDT",
    "AAVE": "AAVEUSDT",
    "ALLO": "ALLOUSDT",
    "BNB": "BNBUSDT",
    "UNI": "UNIUSDT",
    "LINK": "LINKUSDT",
    "BCH": "BCHUSDT",
    "ADA": "ADAUSDT",
    "LTC": "LTCUSDT",
    "AVAX": "AVAXUSDT",
    "KAITO": "KAITOUSDT",
    "EIGEN": "EIGENUSDT",
    "PARTI": "PARTIUSDT",
    "GRAM": "GRAMUSDT",
    "DOT": "DOTUSDT",
    "TAO": "TAOUSDT",
    "JTO": "JTOUSDT",
    "TRX": "TRXUSDT",
    "MMT": "MMTUSDT",
    "PENDLE": "PENDLEUSDT",
    "TIA": "TIAUSDT",
    "MUBARAK": "MUBARAKUSDT",
    "ONDO": "ONDOUSDT",
    "XLM": "XLMUSDT",
    "MANA": "MANAUSDT",
    "ETHFI": "ETHFIUSDT",
    "WLD": "WLDUSDT",
    "LDO": "LDOUSDT",
    "ZRO": "ZROUSDT",
    "TRB": "TRBUSDT",
    "JUP": "JUPUSDT",
    "PEOPLE": "PEOPLEUSDT",
    "IO": "IOUSDT",
    "JASMY": "JASMYUSDT",
    "WIF": "WIFUSDT",
    "ORDI": "ORDIUSDT",
    "INJ": "INJUSDT",
    "ENA": "ENAUSDT",
    "1000SATS": "1000SATSUSDT",
    "AIGENSYN": "AIGENSYNUSDT",
    "SAHARA": "SAHARAUSDT",
    "DYDX": "DYDXUSDT",
    "PENGU": "PENGUUSDT",
    "BLUR": "BLURUSDT",
    "ASTER": "ASTERUSDT",
    "TRUMP": "TRUMPUSDT",
    "KITE": "KITEUSDT",
    "EDEN": "EDENUSDT",
    "BIO": "BIOUSDT",
    "TST": "TSTUSDT",
    "ALT": "ALTUSDT",
    "RSR": "RSRUSDT",
    "CHIP": "CHIPUSDT",
    "SEI": "SEIUSDT",
    "DOGS": "DOGSUSDT",
    "WCT": "WCTUSDT",
    "XPL": "XPLUSDT",
    "DASH": "DASHUSDT",
    "GIGGLE": "GIGGLEUSDT",
    "RED": "REDUSDT",
    "LISTA": "LISTAUSDT",
    "VANA": "VANAUSDT",
    "FIL": "FILUSDT",
    "CAKE": "CAKEUSDT",
    "KSM": "KSMUSDT",
    "LAYER": "LAYERUSDT",
    "VIRTUAL": "VIRTUALUSDT",
    "DUSK": "DUSKUSDT",
    "ZK": "ZKUSDT",
    "PROVE": "PROVEUSDT",
    "SAGA": "SAGAUSDT",
    "ETC": "ETCUSDT",
    "BERA": "BERAUSDT",
    "PNUT": "PNUTUSDT",
    "ACT": "ACTUSDT",
    "FRAX": "FRAXUSDT",
}

BINANCE_WS_BASE   = "wss://stream.binance.com:9443/stream"
BINANCE_REST_BASE = "https://api.binance.com/api/v3"

# ─── Scalping Strategy Params ───────────────────────────────
SCALPING = {
    "trend_tf":          "15m",           # primary trend TF (legacy, used as fallback)
    "entry_tf":          "5m",            # entry signal TF
    "confirm_tfs":       ["30m", "15m", "5m"],  # multi-TF trend check (high→low)
    "bias_tf":           "1h",            # higher TF bias gate — must agree with signal
    "mtf_min_align":     2,               # min TFs that must agree (out of 3)
    "atr_period":        14,
    "atr_sl_mult":       1.35,
    "sl_entry_r":        1.0,   # changed 2026-07-26 from 2.5 → 1.0 per user request.
                                 # SL-out now reports -1.00R.
    "tp_entry_r":        2.5,   # changed 2026-07-26 from 3.5 → 2.5 per user request —
                                 # this is now the hard-cap exit, not a plain TP.
    # Continuous trailing stop: once peak R reaches trail_trigger_r, the stop
    # becomes (peak_r - trail_gap_r) and re-tightens upward every tick as peak_r
    # grows. Replaces the old single-shot breakeven lock (be_trigger_r/be_stop_r,
    # removed 2026-07-26 per user request).
    "trail_trigger_r":   1.1,
    "trail_gap_r":       0.4,
    "atr_tp_mult":       20.0,  # effectively disabled — exits via trailing SL only
    "max_hold_sec":      None,  # disabled — exit only via SL / TP / trailing SL
    "min_adx":           22,              # raised from 20 on 2026-07-03 — DB analysis of 329 scalping
                                           # trades: ADX 18-22 zone lost -$26,598 (38-44% WR), ADX 22+
                                           # made +$23,661 (52-62% WR). 20 was too loose; 25 too tight
                                           # (24-27 bucket was ~breakeven). 22 is the actual breakpoint.
    "rsi_period":        5,
    "rsi_oversold":      25,              # slightly relaxed from 20 — RSI rarely hits 20 on 5m
    "rsi_overbought":    75,              # slightly relaxed from 80 — catch overbought earlier
    "vwap_dev_pct":      0.30,            # raised from 0.15 — requires stronger VWAP extension before retracement fires
    "dom_ratio":         1.5,             # lowered from 2.0 — 2:1 orderbook imbalance is too rare
    "dom_levels":        10,
    "fvg_candles":       3,
    "sweep_threshold":   0.002,   # max spread between equal lows/highs to form a cluster
    "trend_candles":     100,
    "entry_candles":     100,
}

# ─── VWAP Fade (mean reversion) ─────────────────────────────
# Added 2026-07-27. This is NOT the 7-layer signal — it is a standalone
# mean-reversion rule that fades stretched moves back toward VWAP:
#     LONG  when price <= vwap_dev_pct BELOW session VWAP and RSI(5) < rsi_long
#     SHORT when price >= vwap_dev_pct ABOVE session VWAP and RSI(5) > rsi_short
# No trend/ADX/multi-TF gating — it deliberately trades AGAINST the move.
#
# Chosen after a 50-pair / 4-window candle backtest (8 Jun - 26 Jul, ~232k
# trigger bars) that compared 6 strategy families against a random control:
#     vwapfade  +0.022 median R/trade, 77% of its configs positive, 4/4 windows
#     meanrev   +0.014, 65% positive
#     trend_pb  -0.116, 0% positive   <- the 7-layer signal's family
#     RANDOM    -0.079, 0% positive
# Best config pooled +0.046 R/trade at CURRENT taker fees (+0.066 with maker
# entry), 33/50 pairs net-positive, top pair only 9% of net.
#
# Re-validated on 1-MINUTE exit paths (5m bars are optimistic when stop and
# target sit close together). On its WEAKEST window the 1m path moved it
# +0.082: taker -0.089 -> -0.007, maker -0.064 -> +0.018. The wide trailing
# stop is why finer bars help here rather than hurt.
#
# CAUTION - sizing: atr_sl_mult 4.5 puts sl_dist_pct around 2%, and
# risk = position_size x sl_dist_pct. At capital_pct 20% x 10x leverage that is
# ~4% of balance risked per trade, which breaches a 6% daily loss limit in under
# two losers. Drop capital_pct to ~6% before running this. See VWAPFADE_MAX_CAPITAL_PCT.
# CAUTION - hold time: median hold measured at ~6.5 hours. This is not scalping.
VWAPFADE = {
    "entry_tf":          "5m",
    "trend_tf":          "5m",          # unused, kept for market_data compatibility
    "confirm_tfs":       ["5m"],        # only 5m is needed — no MTF gate
    "atr_period":        14,
    "atr_sl_mult":       4.5,           # wide stop — also cuts fee_R proportionally
    "sl_entry_r":        1.0,           # exit at -1.0R
    "tp_entry_r":        None,          # NO hard target — trailing is the only exit
    "trail_trigger_r":   1.5,
    "trail_gap_r":       0.5,
    "max_hold_sec":      None,
    # entry rule
    "vwap_period":       60,            # bars of 5m VWAP (~5h session anchor)
    "vwap_dev_pct":      0.008,         # 0.8% stretch from VWAP required
    "rsi_period":        5,
    "rsi_long":          30,            # RSI(5) below this for a LONG fade
    "rsi_short":         70,            # RSI(5) above this for a SHORT fade
    "min_sl_pct":        0.004,         # skip if sl_dist < 0.4% (fee gate)
    "entry_candles":     120,
    "trend_candles":     120,
}

# Guard rail: the engine caps capital_pct at this when style == "vwapfade",
# because the 4.5x ATR stop makes each trade risk ~3x what the scalping config
# does at the same capital_pct.
VWAPFADE_MAX_CAPITAL_PCT = 6.0


def style_cfg(style: str) -> dict:
    """Single source of truth for style -> params. Was duplicated as
    `SCALPING if style == "scalping" else SWING` in 8 places, which silently
    routed any new style to SWING."""
    return {"scalping": SCALPING, "swing": SWING, "vwapfade": VWAPFADE}.get(style, SCALPING)


# ─── Swing Strategy Params ──────────────────────────────────
SWING = {
    "trend_tf":          "4h",
    "entry_tf":          "1h",
    "confirm_tfs":       ["4h", "1h", "30m"],   # multi-TF trend check (high→low)
    "mtf_min_align":     2,
    "atr_period":        14,
    "atr_sl_mult":       3.0,
    "atr_tp_mult":       9.0,
    "max_hold_sec":      None,  # disabled — exit only via SL / TP / trailing SL
    "min_adx":           18,              # swing trends develop slower, lower threshold ok
    "rsi_period":        14,
    "rsi_oversold":      35,              # slightly relaxed from 30
    "rsi_overbought":    65,              # slightly relaxed from 70
    "vwap_dev_pct":      0.8,             # lowered from 1.0 — 1% deviation is rare on swing
    "dom_ratio":         1.5,             # lowered from 2.0
    "dom_levels":        10,
    "fvg_candles":       3,
    "sweep_threshold":   0.002,
    "trend_candles":     100,
    "entry_candles":     100,
}

# ─── Risk Rules (hardcoded, never bypass) ───────────────────
MAX_DAILY_LOSS_PCT       = 100.0
MAX_WEEKLY_DRAWDOWN_PCT  = 100.0

# Max simultaneous trades
MAX_TRADES_NORMAL = 7

MAX_LEVERAGE             = 20.0  # hard ceiling — user can never go above this
DEFAULT_LEVERAGE         = 5.0   # default if user doesn't specify
MIN_SIGNAL_SCORE         = 4    # minimum layers out of 7

# ─── Adaptive Per-Pair Filter ───────────────────────────────
# Learns from this bot's OWN closed trades: keeps a rolling window of the last
# ADAPTIVE_K net-R results per pair and blocks new entries on pairs whose recent
# mean net-R is negative. Causal by construction — only CLOSED trades feed it.
#
# Tuned 2026-07-26 on a 3-window / 50-pair / 17,214-signal candle backtest
# (20 Jun - 26 Jul). At current taker fees the per-pair bucket cut the loss
# roughly in half: -0.092 -> -0.045 R/trade, win rate 66.3% -> 67.8%.
# K=20 beat K=10 (-0.048) and K=40 (-0.050). Feeding it only TAKEN trades beat
# feeding it every signal, by a wide margin.
ADAPTIVE_ENABLED         = True
ADAPTIVE_K               = 20    # rolling window of recent net-R per pair
ADAPTIVE_MIN_SAMPLES     = 10    # need this many before the filter can block
# A blocked pair records no new results, so without this it would stay blocked
# forever. Every PROBE_SECS one trade is let through to re-test the pair.
#
# Measured 2026-07-26 (36 days, taker fees) — a probe is by construction a trade
# on a pair already known to be losing, so short intervals destroy the filter:
#     permanent block  -0.045 R/trade   (best, but winds down to ~7 trades/day,
#                                        94% of pairs blocked, 4 zero-trade days)
#     probe 7d         -0.063           (keeps ~10 trades/day, no silent days)
#     baseline / off   -0.092
#     probe 6h         -0.136  WORSE than no filter at all
# A "shadow" variant (track blocked pairs on paper, unblock when they recover)
# was also tested and came out at -0.105 — also worse than baseline, because it
# lets pairs back in on noise. Rejected.
#
# 7d is the compromise: still beats baseline, and the bot never goes silent.
# Set very high (e.g. 10**9) for permanent blocks = best measured R/trade.
ADAPTIVE_PROBE_SECS      = 7 * 86400

# ─── Bot internals ──────────────────────────────────────────
SIGNAL_BROADCAST_INTERVAL = 2   # seconds between WS broadcasts
POSITION_CHECK_INTERVAL   = 0.2 # seconds between position monitor ticks (0.5→0.2 on
                                # 2026-07-17 to cut SL/TP exit overshoot on volatile coins.
                                # Reads local WS price (last_price dict), NOT Binance REST —
                                # so no extra exchange API load.
KLINE_HISTORY_LIMIT       = 150 # candles to fetch on startup
