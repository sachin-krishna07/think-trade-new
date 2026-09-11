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
    "confirm_tfs":       ["1h", "30m", "15m", "5m"],  # multi-TF trend check (high→low)
    "bias_tf":           "1h",            # higher TF bias gate — must agree with signal
    "mtf_min_align":     4,               # ALL 4 TFs (1h/30m/15m/5m) must agree — no majority, full alignment required
    "atr_period":        14,
    "atr_sl_mult":       1.35,
    "sl_entry_r":        1.2,   # 2.5 → 1.0 (2026-07-26) → 1.2 (backported from 3.0).
                                 # SL-out reports -1.20R.
    "tp_entry_r":        2.0,   # 3.5 → 2.5 (2026-07-26) → 2.0 (backported from 3.0) —
                                 # hard-cap exit, not a plain TP.
    # Trailing ladder: [(peak_r_trigger, stop_r), ...], lowest trigger first. The
    # first time peak R touches a trigger, the stop jumps to that step's level.
    # The stop only ever tightens — a later step can raise it, nothing lowers it —
    # and it does NOT ratchet continuously between steps. Absent/empty = trailing
    # off. Replaces the old scalar trail_trigger_r/trail_gap_r pair (backported
    # from 3.0). A step's level may be NEGATIVE: (0.8, -0.5) is a loss cut on a
    # trade that showed +0.8R and reversed, not a profit lock.
    "trail_steps":       [(0.8, -0.5), (1.5, 1.0)],
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
    # 1H EMA9 distance gate — added 2026-09-11 per user request. A signal is
    # traded only when price is MORE than this many % beyond the 1H EMA9 in the
    # SIGNAL's direction (above it for a long signal, below it for a short
    # signal): dist% = (price - 1H EMA9) / price * 100, sign flipped for short.
    # Measured on the signal direction, not the executed direction, so it does
    # not change meaning when the frontend "reverse" toggle is on.
    # Version-2.0 history (day-time trades, 8 Aug-11 Sep) did NOT show a steady
    # edge: dist > 3% went 68% WR / +7,191 on 8-27 Aug but 30% WR / -5,647 from
    # 28 Aug. Review after 1-2 weeks. Set to None to disable the gate.
    # Blocked signals are logged by bot_controller ("EMA9 filter: ... skipped").
    "min_h1_ema9_dist_pct": 2.0,
}

def style_cfg(style: str) -> dict:
    """Single source of truth for style -> params. Was duplicated as
    `SCALPING if style == "scalping" else SWING` in 8 places, which silently
    routed any new style to SWING."""
    return {"scalping": SCALPING, "swing": SWING}.get(style, SCALPING)


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

# Per-trader daily loss-count lockout — added 2026-08-18 per user request.
# Any 3 losing trades (pnl < 0, any amount) closed by the SAME trader_name on
# the SAME IST calendar day blocks that trader's new entries for the rest of
# that day (existing open positions are untouched; resets at IST midnight).
# Losses do not need to be consecutive. Shadow trades never count — they
# never touch the wallet and shouldn't gate real entries either.
# Replaces the old CONSECUTIVE_LOSS_LIMIT (3-in-a-row -> 1hr cooldown) rule,
# which this makes redundant: any 3-in-a-row is also 3-that-day, and this
# rule fires at the same time or earlier while blocking for the whole day
# instead of 1 hour.
#
# REMOVED 2026-09-11 per user request: RiskManager.check() no longer reads
# this, so 3 losing trades in a day no longer block new entries. bot_logs
# showed it firing almost every day 22 Aug-11 Sep. Constant kept only so old
# references don't break.
MAX_DAILY_LOSSES_PER_TRADER = 3

# Max simultaneous trades
MAX_TRADES_NORMAL = 7

MAX_LEVERAGE             = 20.0  # hard ceiling — user can never go above this
DEFAULT_LEVERAGE         = 5.0   # default if user doesn't specify
MIN_SIGNAL_SCORE         = 4    # minimum layers out of 7

# ─── Trading Window (IST) ───────────────────────────────────
# New entries are opened ONLY inside this window, as (hour, minute) in IST
# (UTC+5:30). Set either side to None to disable the gate entirely.
#
# This blocks new entries only. Positions already open are untouched — they
# run to their own SL/TP/trailing exit whatever the clock says.
#
# Added 2026-09-11 as a NIGHT GATE, per user request: no new entries
# 6:00 PM - 1:00 AM IST. Values below are the ALLOWED window
# (01:00 -> 18:00), so the blocked window is END -> START (18:00 -> 01:00).
# The gate handles wrap-around, so a window crossing midnight works too.
# Logs name the blocked window ("Night gate ON (18:00–01:00 IST)") and every
# skipped signal (once per pair per 5m candle). See bot_controller.py.
TRADE_WINDOW_START = (1, 0)     # 1:00 AM IST — entries allowed from here
TRADE_WINDOW_END   = (18, 0)    # 6:00 PM IST — night gate starts here

# Shadow-trade threshold — max SL distance as a fraction of position size.
# SL% is exactly risk_amount / position_size_usd, so this caps "how much of the
# money in the market can one trade lose".
#
# Added 2026-08-10 from a 19-trade DB review: 17 trades sat at 0.56-2.78% SL,
# but two TST shorts ran 3.91% and 6.26% and lost -$6,416 and -$9,260 — together
# more than the account's entire -$12,208 drawdown. Position size never looks at
# ATR, so a volatile pair's wide ATR-derived SL scales the dollar loss with
# nothing to stop it (no max_sl / risk cap existed anywhere in the codebase).
#
# Trades above this threshold are NOT skipped — they are taken as "shadow"
# trades: fully recorded with their natural (wide) SL so the data stays honest,
# but excluded from wallet, stats, and every risk counter. Once enough shadow
# trades accumulate, this threshold can be re-tuned on real evidence instead of
# the two data points available today.
#
# Raised 2.5% -> 3.0% on 2026-09-11 per user request.
# Measured against the 1R distance (atr * atr_sl_mult), NOT against the stop
# actually placed — sl_entry_r is 1.2, so a pair sitting just under this cap
# has its real stop ~3.6% away. See risk_manager.calculate_position.
MAX_SL_PCT = 0.030   # 3.0%

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
