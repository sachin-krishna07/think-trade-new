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
PAIRS = {
    # ⭐ TIER 1
    "JUP":   "JUPUSDT",
    "STX":   "STXUSDT",
    "DOGE":  "DOGEUSDT",
    "WIF":   "WIFUSDT",
    "SOL":   "SOLUSDT",
    "APT":   "APTUSDT",

    # ✅ TIER 2
    "ADA":   "ADAUSDT",
    "AVAX":  "AVAXUSDT",
    "TIA":   "TIAUSDT",
    "ICP":   "ICPUSDT",
    "BTC":   "BTCUSDT",
    "ETH":   "ETHUSDT",
    "LINK":  "LINKUSDT",

    # 👀 TIER 3
    "DOT":   "DOTUSDT",
    "ATOM":  "ATOMUSDT",
    "EIGEN": "EIGENUSDT",
    "UNI":   "UNIUSDT",
    "RUNE":  "RUNEUSDT",
    "SEI":   "SEIUSDT",
    "PEPE":  "PEPEUSDT",

    # 🔬 TIER 4
    "TAO":   "TAOUSDT",
    "ONDO":  "ONDOUSDT",
    "ENA":   "ENAUSDT",
    "FET":   "FETUSDT",
    "WLD":   "WLDUSDT",
    "BONK":  "BONKUSDT",
    "BCH":   "BCHUSDT",

    # 🧪 PROBATION (added 2026-07-03, no trade history yet —
    # judge after ~20 trades each, same win-rate/net-pnl analysis)
    "XRP":   "XRPUSDT",
    "LTC":   "LTCUSDT",
    "INJ":   "INJUSDT",
    "AAVE":  "AAVEUSDT",
    # market-profile screened 2026-07-03: matched proven winners' volatility
    # (5m ATR 0.22-0.60%), trendiness and liquidity; all verified TRADING on
    # Binance spot + USDT-M perpetual futures.
    "ZEC":    "ZECUSDT",
    "XLM":    "XLMUSDT",
    "PENDLE": "PENDLEUSDT",
    "MORPHO": "MORPHOUSDT",
    "ME":     "MEUSDT",
    "FF":     "FFUSDT",
    "FIL":    "FILUSDT",
    "TRUMP":  "TRUMPUSDT",
    "PENGU":  "PENGUUSDT",
    "ORDI":   "ORDIUSDT",
    "BERA":   "BERAUSDT",
    "RENDER": "RENDERUSDT",
    "RED":    "REDUSDT",
    "DASH":   "DASHUSDT",
    "CRV":    "CRVUSDT",
}

BINANCE_WS_BASE  = "wss://stream.binance.com:9443/stream"
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

# Progressive cooldown: (losses_in_last_5_trades, cooldown_minutes)
LOSS_WINDOW      = 5
COOLDOWN_LEVELS  = [(3, 30), (4, 60), (5, 120)]

# Max simultaneous trades per mode
MAX_TRADES_NORMAL     = 3   # 0-2 losses in window
MAX_TRADES_SEMI       = 2   # recovering (1 win after restricted)
MAX_TRADES_RESTRICTED = 1   # just came out of cooldown

MAX_LEVERAGE             = 20.0  # hard ceiling — user can never go above this
DEFAULT_LEVERAGE         = 5.0   # default if user doesn't specify
MIN_SIGNAL_SCORE         = 4    # minimum layers out of 7

# ─── Quiet Hours (IST) ──────────────────────────────────────
# No new trade entries during this window. Format: (hour, minute) in IST (UTC+5:30).
QUIET_HOURS_START = (2, 0)    # 2:00 AM IST
QUIET_HOURS_END   = (8, 0)    # 8:00 AM IST

# ─── Bot internals ──────────────────────────────────────────
SIGNAL_BROADCAST_INTERVAL = 2   # seconds between WS broadcasts
POSITION_CHECK_INTERVAL   = 0.5 # seconds between position monitor ticks
KLINE_HISTORY_LIMIT       = 150 # candles to fetch on startup
