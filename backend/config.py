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
    "sl_entry_r":        1.5,   # changed 2026-07-17 from 1.0 → 1.5 per user request.
                                 # SL-out now reports -1.50R.
    "tp_entry_r":        2.2,   # changed 2026-07-17 from 1.75 → 2.2 per user request.
                                 # TP-out reports +2.20R.
    # Breakeven lock: once peak R hits be_trigger_r, the stop jumps to be_stop_r
    # (+0.2R — covers the ~0.17R round-trip fee, so a stop-out there is a tiny net
    # gain, not a scratch loss). Set be_trigger_r to None to disable the move.
    "be_trigger_r":      1.5,
    "be_stop_r":         0.2,
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

# Max simultaneous trades
MAX_TRADES_NORMAL = 7

MAX_LEVERAGE             = 20.0  # hard ceiling — user can never go above this
DEFAULT_LEVERAGE         = 5.0   # default if user doesn't specify
MIN_SIGNAL_SCORE         = 4    # minimum layers out of 7

# ─── Bot internals ──────────────────────────────────────────
SIGNAL_BROADCAST_INTERVAL = 2   # seconds between WS broadcasts
POSITION_CHECK_INTERVAL   = 0.2 # seconds between position monitor ticks (0.5→0.2 on
                                # 2026-07-17 to cut SL/TP exit overshoot on volatile coins.
                                # Reads local WS price (last_price dict), NOT Binance REST —
                                # so no extra exchange API load.
KLINE_HISTORY_LIMIT       = 150 # candles to fetch on startup
