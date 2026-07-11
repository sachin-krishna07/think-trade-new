import numpy as np
from typing import List, Tuple, Optional

# ─── EMA ────────────────────────────────────────────────────

def ema(prices: List[float], period: int) -> float:
    if len(prices) < 2:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    val = prices[0]
    for p in prices[1:]:
        val = p * k + val * (1 - k)
    return val

def ema_series(prices: List[float], period: int) -> List[float]:
    if not prices:
        return []
    k = 2.0 / (period + 1)
    series = [prices[0]]
    for p in prices[1:]:
        series.append(p * k + series[-1] * (1 - k))
    return series


# ─── RSI ────────────────────────────────────────────────────

def rsi(closes: List[float], period: int = 14) -> float:
    """Wilder's RSI — same formula used by TradingView and most platforms."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(np.array(closes, dtype=float))
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # Seed with simple average of first `period` bars
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    # Wilder's smoothing for remaining bars
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 4)


# ─── ATR ────────────────────────────────────────────────────

def atr(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> float:
    if len(closes) < 2:
        return highs[-1] - lows[-1] if highs and lows else 0.0
    h = np.array(highs[-period-2:])
    l = np.array(lows[-period-2:])
    c = np.array(closes[-period-2:])
    tr = np.maximum(h[1:] - l[1:],
         np.maximum(np.abs(h[1:] - c[:-1]),
                    np.abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-period:]))


# ─── ADX ────────────────────────────────────────────────────

def adx(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> Tuple[float, float, float]:
    """Returns (adx_value, plus_di, minus_di)"""
    n = len(closes)
    if n < period * 2 + 1:
        return 0.0, 0.0, 0.0

    h = np.array(highs)
    l = np.array(lows)
    c = np.array(closes)

    up_moves   = h[1:] - h[:-1]
    down_moves = l[:-1] - l[1:]

    plus_dm  = np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0.0)
    minus_dm = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0.0)
    tr_arr   = np.maximum(h[1:] - l[1:],
               np.maximum(np.abs(h[1:] - c[:-1]),
                          np.abs(l[1:] - c[:-1])))

    def wilder_smooth(arr, p):
        res = np.zeros(len(arr))
        res[p-1] = np.sum(arr[:p])
        for i in range(p, len(arr)):
            res[i] = res[i-1] - res[i-1] / p + arr[i]
        return res

    sm_tr   = wilder_smooth(tr_arr, period)
    sm_pdm  = wilder_smooth(plus_dm, period)
    sm_mdm  = wilder_smooth(minus_dm, period)

    with np.errstate(divide='ignore', invalid='ignore'):
        pdi = np.where(sm_tr > 0, 100 * sm_pdm / sm_tr, 0.0)
        mdi = np.where(sm_tr > 0, 100 * sm_mdm / sm_tr, 0.0)
        dx  = np.where((pdi + mdi) > 0, 100 * np.abs(pdi - mdi) / (pdi + mdi), 0.0)

    adx_val = float(np.mean(dx[period*2-1:])) if len(dx) >= period*2 else float(np.mean(dx))
    return round(adx_val, 4), round(float(pdi[-1]), 4), round(float(mdi[-1]), 4)


# ─── VWAP ───────────────────────────────────────────────────

def vwap(highs: List[float], lows: List[float], closes: List[float],
         volumes: List[float]) -> float:
    if not closes or not volumes:
        return closes[-1] if closes else 0.0
    tp  = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    tpv = sum(p * v for p, v in zip(tp, volumes))
    vol = sum(volumes)
    return tpv / vol if vol > 0 else closes[-1]


# ─── CVD — Cumulative Volume Delta ──────────────────────────

def update_cvd(current_cvd: float, buy_vol: float, sell_vol: float) -> float:
    return current_cvd + buy_vol - sell_vol

def cvd_divergence(prices: List[float], cvd_values: List[float],
                   direction: str, lookback: int = 10) -> bool:
    """
    Slope-based CVD divergence — price and CVD moving in opposite directions.

    LONG  (bullish div): price falling + CVD rising  → smart money buying the dip
    SHORT (bearish div): price rising  + CVD falling → smart money selling the rally

    Guards:
    - Both series must have real variance (not flat) — prevents false slopes
      when CVD is near zero (bot just started) or price is stuck.
    - cvd_range uses raw ptp (no np.abs) — fixes distortion when CVD crosses zero
      (e.g. +500→-500 has range 1000, not 500).
    - min_slope applied after normalization so it scales with move size.
    """
    if len(prices) < lookback or len(cvd_values) < lookback:
        return False

    p   = np.array(prices[-lookback:],     dtype=float)
    cvd = np.array(cvd_values[-lookback:], dtype=float)
    x   = np.arange(lookback, dtype=float)

    p_range   = float(np.ptp(p))
    cvd_range = float(np.ptp(cvd))

    # Skip if either series is flat — no real move to compare
    if p_range < 1e-8 or cvd_range < 1e-8:
        return False

    # Normalize relative to first value so both start at 0
    p_norm   = (p   - p[0])   / p_range
    cvd_norm = (cvd - cvd[0]) / cvd_range

    price_slope = float(np.polyfit(x, p_norm,   1)[0])
    cvd_slope   = float(np.polyfit(x, cvd_norm, 1)[0])

    min_slope = 0.03  # both series must move meaningfully after normalization

    if direction == "long":
        # Price falling + CVD rising → institutional buying during pullback
        return price_slope < -min_slope and cvd_slope > min_slope

    if direction == "short":
        # Price rising + CVD falling → institutional selling during rally
        return price_slope > min_slope and cvd_slope < -min_slope

    return False


# ─── Fair Value Gap ─────────────────────────────────────────

def detect_fvg(highs: List[float], lows: List[float],
               current_price: float, direction: str,
               min_gap_pct: float = 0.001,
               lookback: int = 20) -> Tuple[bool, Optional[float]]:
    """Returns (fvg_detected, gap_midpoint).
    min_gap_pct: minimum gap size as fraction of price.
    lookback: how many candles back to scan for FVGs.
    """
    if len(highs) < 3:
        return False, None

    for i in range(len(highs) - 3, max(len(highs) - lookback, 0) - 1, -1):
        c1_high = highs[i]
        c1_low  = lows[i]
        c3_high = highs[i + 2]
        c3_low  = lows[i + 2]

        if direction == "long":
            # Bullish FVG: gap up — c1 high < c3 low, price returning into gap
            gap = c3_low - c1_high
            if gap > 0 and gap / c1_high >= min_gap_pct:
                midpoint = (c1_high + c3_low) / 2
                if c1_high <= current_price <= c3_low:
                    return True, midpoint

        if direction == "short":
            # Bearish FVG: gap down — c1 low > c3 high, price returning into gap
            gap = c1_low - c3_high
            if gap > 0 and gap / c3_high >= min_gap_pct:
                midpoint = (c1_low + c3_high) / 2
                if c3_high <= current_price <= c1_low:
                    return True, midpoint

    return False, None


# ─── Liquidity Sweep ────────────────────────────────────────

def detect_liquidity_sweep(highs: List[float], lows: List[float],
                            closes: List[float], direction: str,
                            threshold: float = 0.002,
                            lookback: int = 20) -> bool:
    """
    Liquidity sweep (stop hunt): price spikes through a cluster of equal
    highs/lows (where stops accumulate), then closes back on the other side.

    Step 1 — Find a stop cluster: 2+ historical highs/lows within `threshold`
             of each other. This is where the market knows stops are sitting.
    Step 2 — Confirm the hunt: recent candle's wick pierces the cluster level
             (any distance — 0.5%, 1%, doesn't matter).
    Step 3 — Confirm the reversal: close is back on the correct side of the level.

    Fix vs old version: old code compared recent candle's high to historical
    highs and required them to be within threshold of EACH OTHER — meaning
    sweeps > 0.15% above the level were missed entirely. Now threshold only
    governs how tight the historical cluster must be, not the sweep distance.
    """
    if len(highs) < 5:
        return False

    recent_high  = highs[-1]
    recent_low   = lows[-1]
    recent_close = closes[-1]

    window_highs = highs[-lookback - 1:-1]
    window_lows  = lows[-lookback - 1:-1]

    if direction == "long":
        # Find a cluster of equal lows (accumulated buy-stops below)
        for level in window_lows:
            if level <= 0:
                continue
            equal_count = sum(
                1 for lo in window_lows
                if lo > 0 and abs(lo - level) / level <= threshold
            )
            if equal_count >= 2:
                # Recent candle swept below the cluster and closed back above
                if recent_low < level and recent_close > level:
                    return True

    if direction == "short":
        # Find a cluster of equal highs (accumulated sell-stops above)
        for level in window_highs:
            if level <= 0:
                continue
            equal_count = sum(
                1 for h in window_highs
                if h > 0 and abs(h - level) / level <= threshold
            )
            if equal_count >= 2:
                # Recent candle swept above the cluster and closed back below
                if recent_high > level and recent_close < level:
                    return True

    return False


# ─── DOM Imbalance ──────────────────────────────────────────

def dom_imbalance(bids: List[Tuple[float, float]],
                  asks: List[Tuple[float, float]],
                  levels: int = 10,
                  threshold: float = 2.0) -> Tuple[int, float]:
    """
    Weighted DOM imbalance — top 3 levels weighted 3x, next 3 weighted 2x, rest 1x.
    Returns (signal, ratio): 1=buy pressure, -1=sell pressure, 0=neutral
    """
    if not bids or not asks:
        return 0, 1.0

    def weighted_vol(book: List[Tuple[float, float]]) -> float:
        vol = 0.0
        for i, (_, qty) in enumerate(book[:levels]):
            weight = 3 if i < 3 else (2 if i < 6 else 1)
            vol += qty * weight
        return vol

    bid_vol = weighted_vol(bids)
    ask_vol = weighted_vol(asks)

    if ask_vol == 0 or bid_vol == 0:
        return 0, 1.0

    ratio = bid_vol / ask_vol
    if ratio >= threshold:
        return 1, round(ratio, 4)
    if ratio <= 1.0 / threshold:
        return -1, round(ratio, 4)
    return 0, round(ratio, 4)


# ─── EMA Pullback ────────────────────────────────────────────

def ema_pullback(closes: List[float], direction: str,
                 period: int = 9, tolerance_pct: float = 0.0075) -> bool:
    """
    Advanced EMA-9 pullback detector — 4 conditions must ALL pass.

    C1 — PROXIMITY:  Price is near EMA-9 right now (entry zone).
    C2 — EMA SLOPE:  EMA-9 is still trending in the trade direction.
                     Ensures trend is intact, not reversing.
    C3 — EXTENSION:  Price was meaningfully away from EMA recently.
                     Confirms a real move happened before the pullback.
    C4 — APPROACH:   Price is coming FROM the correct side toward EMA.
                     LONG → price came DOWN to EMA (at least 2 of last 5
                     candles were higher than now = genuine pullback).
                     SHORT → price came UP to EMA (at least 2 of last 5
                     candles were lower than now = genuine bounce).
                     This prevents false triggers when price SURGES THROUGH
                     EMA (e.g. RSI 85 pump crossing EMA upward = not a pullback).
    """
    if len(closes) < period + 8:
        return False

    ema_vals      = ema_series(closes, period)
    current_price = closes[-1]
    current_ema   = ema_vals[-1]

    if current_ema <= 0 or len(ema_vals) < 7:
        return False

    dev       = (current_price - current_ema) / current_ema
    ema_slope = (ema_vals[-1] - ema_vals[-6]) / ema_vals[-6]  # % change over 5 candles

    if direction == "long":
        # C1: price near EMA — wider zone, allow more overshoot both sides
        if not (-0.005 <= dev <= tolerance_pct * 1.5):
            return False

        # C2: EMA must be sloping UP — flat or falling EMA = no trend
        if ema_slope <= 0.0001:
            return False

        # C3: price was extended ABOVE EMA recently — relaxed threshold
        peak_ext = max(
            (closes[-i] - ema_vals[-i]) / ema_vals[-i]
            for i in range(2, min(13, len(closes)))
        )
        if peak_ext < tolerance_pct * 0.8:
            return False

        # C4: price approached from ABOVE — at least 1 of last 5 closes higher than now
        candles_higher = sum(
            1 for i in range(2, min(7, len(closes)))
            if closes[-i] > current_price * 1.001
        )
        if candles_higher < 1:
            return False

        # C5: EMA not broken — at least 4 of last 5 candles closed ABOVE EMA
        # Prevents entering after trend break that is just retesting EMA as resistance
        ema_above = sum(
            1 for i in range(2, min(7, len(closes)))
            if closes[-i] >= ema_vals[-i]
        )
        if ema_above < 4:
            return False

        return True

    if direction == "short":
        # C1: price near EMA — wider zone, allow more overshoot both sides
        if not (-tolerance_pct * 1.5 <= dev <= 0.005):
            return False

        # C2: EMA must be sloping DOWN — flat or rising EMA = no trend
        if ema_slope >= -0.0001:
            return False

        # C3: price was extended BELOW EMA recently — relaxed threshold
        trough_ext = min(
            (closes[-i] - ema_vals[-i]) / ema_vals[-i]
            for i in range(2, min(13, len(closes)))
        )
        if trough_ext > -tolerance_pct * 0.8:
            return False

        # C4: price approached from BELOW — at least 1 of last 5 closes lower than now
        candles_lower = sum(
            1 for i in range(2, min(7, len(closes)))
            if closes[-i] < current_price * 0.999
        )
        if candles_lower < 1:
            return False

        # C5: EMA not broken — at least 4 of last 5 candles closed BELOW EMA
        # Prevents entering after trend break that is just retesting EMA as support
        ema_below = sum(
            1 for i in range(2, min(7, len(closes)))
            if closes[-i] <= ema_vals[-i]
        )
        if ema_below < 4:
            return False

        return True

    return False


# ─── Market Structure ────────────────────────────────────────

def detect_market_structure(highs: List[float], lows: List[float],
                             lookback: int = 50) -> str:
    """
    Detects swing-based market structure.
    Returns "bullish" (HH+HL), "bearish" (LH+LL), or "sideways".
    """
    n = min(len(highs), lookback)
    if n < 10:
        return "sideways"

    h = highs[-n:]
    l = lows[-n:]
    size = len(h)

    swing_highs = [
        h[i] for i in range(2, size - 2)
        if h[i] >= h[i-1] and h[i] >= h[i-2] and h[i] >= h[i+1] and h[i] >= h[i+2]
    ]
    swing_lows = [
        l[i] for i in range(2, size - 2)
        if l[i] <= l[i-1] and l[i] <= l[i-2] and l[i] <= l[i+1] and l[i] <= l[i+2]
    ]

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "sideways"

    hh = swing_highs[-1] > swing_highs[-2]
    hl = swing_lows[-1]  > swing_lows[-2]
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1]  < swing_lows[-2]

    if hh and hl:
        return "bullish"
    if lh and ll:
        return "bearish"
    return "sideways"


def is_consolidating(highs: List[float], lows: List[float],
                     atr_val: float, lookback: int = 15, mult: float = 1.5) -> bool:
    """Returns True if price is trapped in a tight range (< ATR × mult)."""
    if len(highs) < lookback or atr_val <= 0:
        return False
    rng = max(highs[-lookback:]) - min(lows[-lookback:])
    return rng < atr_val * mult


# ─── VWAP Retracement ────────────────────────────────────────

def vwap_retracement(closes: List[float], highs: List[float],
                     lows: List[float], volumes: List[float],
                     direction: str, min_dev_pct: float = 0.15,
                     precomputed_vwap: float = 0.0) -> bool:
    """
    Returns True if price was extended from VWAP and is now meaningfully
    returning toward it — confirming real mean reversion, not just noise.

    Changes vs old version:
    - Recovery threshold: was flat 0.05% (almost nothing), now 30% of peak
      extension. Price must actually travel back before signal fires.
    - Lookback: was 3-8 candles (40 min on 5m), now 3-12 (60 min).
      Catches pullbacks that take longer to develop.
    - VWAP: accepts precomputed value to avoid double calculation.
      Falls back to computing internally if not provided.
    """
    if len(closes) < 10:
        return False

    vwap_val = precomputed_vwap if precomputed_vwap > 0 else vwap(highs, lows, closes, volumes)
    if vwap_val <= 0:
        return False

    current_dev = (closes[-1] - vwap_val) / vwap_val * 100

    # Peak extension over last 3–12 candles (wider window than before)
    past_devs = [
        (closes[-i] - vwap_val) / vwap_val * 100
        for i in range(3, min(13, len(closes)))
    ]
    if not past_devs:
        return False

    if direction == "long":
        peak_neg = min(past_devs)
        if peak_neg >= -min_dev_pct:
            return False
        # Price must have recovered at least 50% of the peak drop (lowered from
        # 70% on 2026-07-10 — fires on a smaller retracement)
        recovery_needed = peak_neg * 0.50  # e.g. peak=-0.5% → need to reach -0.25%
        return current_dev >= recovery_needed

    if direction == "short":
        peak_pos = max(past_devs)
        if peak_pos <= min_dev_pct:
            return False
        # Price must have fallen back at least 50% of the peak rise (lowered from
        # 70% on 2026-07-10 — fires on a smaller retracement)
        recovery_needed = peak_pos * 0.50  # e.g. peak=+0.5% → need to drop to +0.25%
        return current_dev <= recovery_needed

    return False
