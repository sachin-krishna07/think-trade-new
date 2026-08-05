import logging
import time
from typing import Dict, Optional, Tuple

from config import SCALPING, SWING, MIN_SIGNAL_SCORE, style_cfg
from core.indicators import (
    ema, adx, rsi, atr, vwap,
    cvd_divergence, dom_imbalance,
    detect_fvg, detect_liquidity_sweep,
    ema_pullback, vwap_retracement,
)
from core.market_data import MarketDataManager

log = logging.getLogger("signal_engine")


class SignalResult:
    def __init__(self):
        self.total_score:       int   = 0
        self.signal_direction:  str   = "none"   # "long" | "short" | "none"
        self.trade_signal:      bool  = False

        # Layer results
        self.trend_regime:    int   = 0   # 1 or 0
        self.trend_direction: str   = "neutral"
        self.adx_value:       float = 0.0
        self.ema9:            float = 0.0
        self.ema21:           float = 0.0

        self.cvd_divergence:  int   = 0
        self.cvd_value:       float = 0.0

        self.vwap_deviation:  int   = 0
        self.vwap_value:      float = 0.0
        self.vwap_dev_pct:    float = 0.0

        self.dom_imbalance:   int   = 0
        self.dom_ratio:       float = 1.0

        self.rsi2_extreme:    int   = 0
        self.rsi2_value:      float = 50.0

        self.liquidity_sweep: int   = 0
        self.sweep_type:      str   = ""

        self.fair_value_gap:  int   = 0
        self.fvg_type:        str   = ""
        self.fvg_level:       float = 0.0

        self.atr_value:       float = 0.0
        self.current_price:   float = 0.0

        # L8 — EMA Pullback (mandatory gate)
        self.ema_pullback:    int   = 0   # 1 = pullback confirmed, 0 = not yet

        # 1H RSI Extreme Gate
        self.h1_rsi_value:    float = 50.0   # 1H RSI value
        self.h1_rsi_state:    str   = "neutral"  # "overbought" | "oversold" | "neutral"
        self.h1_rsi_blocked:  bool  = False  # True = trade blocked by 1H RSI

        # Quality gate results (internal — not sent to Supabase)
        self.btc_bias:         str  = "n/a"  # long | short | n/a

    def to_dict(self) -> Dict:
        return {
            "total_score":      self.total_score,
            "signal_direction": self.signal_direction,
            "trade_signal":     self.trade_signal,
            "trend_regime":     self.trend_regime,
            "trend_direction":  self.trend_direction,
            "adx_value":        self.adx_value,
            "ema9_value":       self.ema9,
            "ema21_value":      self.ema21,
            "cvd_divergence":   self.cvd_divergence,
            "cvd_value":        self.cvd_value,
            "vwap_deviation":   self.vwap_deviation,
            "vwap_value":       self.vwap_value,
            "vwap_dev_pct":     self.vwap_dev_pct,
            "dom_imbalance":    self.dom_imbalance,
            "dom_ratio":        self.dom_ratio,
            "rsi2_extreme":     self.rsi2_extreme,
            "rsi2_value":       self.rsi2_value,
            "liquidity_sweep":  self.liquidity_sweep,
            "sweep_type":       self.sweep_type,
            "fair_value_gap":   self.fair_value_gap,
            "fvg_type":         self.fvg_type,
            "fvg_level":        self.fvg_level,
            "atr_value":        self.atr_value,
            "price":            self.current_price,
            "ema_pullback":     self.ema_pullback,
            "h1_rsi_value":     self.h1_rsi_value,
            "h1_rsi_state":     self.h1_rsi_state,
            "h1_rsi_blocked":   self.h1_rsi_blocked,
        }


class SignalEngine:
    def __init__(self, market_data: MarketDataManager):
        self.md = market_data

    def score(self, pair: str, style: str, btc_direction: str = None) -> SignalResult:
        cfg = style_cfg(style)
        result = SignalResult()
        result.current_price = self.md.get_price(pair)

        if not self.md.is_ready(pair, style):
            return result

        # closed_only=True → drop the still-forming candle so all indicators
        # (ATR, VWAP, RSI, sweeps, FVG) are computed on completed candles only.
        # current_price above stays live for display/exit logic.
        entry_candles = self.md.get_candles(pair, cfg["entry_tf"], closed_only=True)

        if len(entry_candles) < 20:
            return result

        e_closes  = [c["close"]  for c in entry_candles]
        e_highs   = [c["high"]   for c in entry_candles]
        e_lows    = [c["low"]    for c in entry_candles]
        e_volumes = [c["volume"] for c in entry_candles]

        price = result.current_price or e_closes[-1]

        # Always compute display metrics upfront so the UI shows real values
        # even when L1 fails and we early-return (avoids misleading 0s in UI).
        _entry_atr = atr(e_highs, e_lows, e_closes, cfg["atr_period"])
        result.atr_value = round(_entry_atr, 6)

        # Session VWAP: only today's UTC candles so anchor is fresh each day.
        # Falls back to all available candles if today has < 5 candles (early session).
        utc_day_start = int(time.time() // 86400) * 86400 * 1000  # midnight UTC in ms
        session_mask  = [c for c in entry_candles if c["ts"] >= utc_day_start]
        vwap_candles  = session_mask if len(session_mask) >= 5 else entry_candles
        _vh = [c["high"]   for c in vwap_candles]
        _vl = [c["low"]    for c in vwap_candles]
        _vc = [c["close"]  for c in vwap_candles]
        _vv = [c["volume"] for c in vwap_candles]
        _e_vwap = vwap(_vh, _vl, _vc, _vv)
        result.vwap_value   = round(_e_vwap, 6)
        result.vwap_dev_pct = round((price - _e_vwap) / _e_vwap * 100, 4) if _e_vwap > 0 else 0.0

        result.cvd_value  = round(self.md.get_cvd(pair), 4)
        result.rsi2_value = rsi(e_closes, cfg["rsi_period"])

        # ── Layer 1: Multi-TF Trend Regime (MANDATORY) ──────
        # Checks 30m → 15m → 5m (scalping) or 4h → 1h → 30m (swing)
        # Minimum mtf_min_align TFs must agree on same direction
        confirm_tfs = cfg.get("confirm_tfs", [cfg["trend_tf"], cfg["entry_tf"]])
        mtf_min     = cfg.get("mtf_min_align", 2)

        tf_directions = []
        for i, tf in enumerate(confirm_tfs):
            # closed_only=True — the multi-TF trend must be read from CLOSED
            # candles. A forming 30m candle can flip the EMA/ADX/DI trend for up
            # to 30 min, which is the #1 cause of false-trend entries.
            tf_candles = self.md.get_candles(pair, tf, closed_only=True)
            if len(tf_candles) < 30:
                tf_directions.append("neutral")
                continue

            tf_closes = [c["close"] for c in tf_candles]
            tf_highs  = [c["high"]  for c in tf_candles]
            tf_lows   = [c["low"]   for c in tf_candles]

            tf_ema9          = ema(tf_closes, 9)
            tf_ema21         = ema(tf_closes, 21)
            tf_adx, tf_pdi, tf_mdi = adx(tf_highs, tf_lows, tf_closes, 14)

            # Use highest TF (first in list) values for display
            if i == 0:
                result.adx_value = round(tf_adx, 4)
                result.ema9      = round(tf_ema9, 6)
                result.ema21     = round(tf_ema21, 6)

            if tf_adx >= cfg["min_adx"]:
                if tf_ema9 > tf_ema21 and tf_pdi > tf_mdi:
                    tf_directions.append("long")
                elif tf_ema9 < tf_ema21 and tf_mdi > tf_pdi:
                    tf_directions.append("short")
                else:
                    tf_directions.append("neutral")
            else:
                tf_directions.append("neutral")

        long_count  = tf_directions.count("long")
        short_count = tf_directions.count("short")

        # Entry TF (last in confirm_tfs = 5m) MUST agree with signal direction.
        # Prevents lagging 30m/15m EMAs from triggering a trade when 5m is opposite.
        entry_tf_dir = tf_directions[-1] if tf_directions else "neutral"

        if long_count >= mtf_min and entry_tf_dir == "long":
            result.trend_direction = "long"
            result.trend_regime    = 1
        elif short_count >= mtf_min and entry_tf_dir == "short":
            result.trend_direction = "short"
            result.trend_regime    = 1
        else:
            result.trend_direction = "neutral"
            result.trend_regime    = 0

        # Layer 1 is mandatory — no aligned multi-TF trend = no trade
        if not result.trend_regime:
            result.total_score      = 0
            result.signal_direction = "none"
            return result

        direction = result.trend_direction
        score     = 1  # Layer 1 counts

        # ── Quality Gate: BTC Bias — REMOVED ───────────────────
        quality_ok      = True
        result.btc_bias = "n/a"

        # ── 1H Trend Bias Gate + RSI Extreme Gate ───────────────
        # 1) 1H trend must agree with signal direction
        # 2) 1H RSI overbought (>75) → LONG blocked | oversold (<25) → SHORT blocked
        H1_RSI_OB = 75   # overbought threshold
        H1_RSI_OS = 25   # oversold threshold
        try:
            h1_candles = self.md.get_candles(pair, "1h", closed_only=True)
            if len(h1_candles) >= 30:
                h1_closes = [c["close"] for c in h1_candles]
                h1_highs  = [c["high"]  for c in h1_candles]
                h1_lows   = [c["low"]   for c in h1_candles]
                h1_ema9   = ema(h1_closes, 9)
                h1_ema21  = ema(h1_closes, 21)
                h1_adx, h1_pdi, h1_mdi = adx(h1_highs, h1_lows, h1_closes, 14)

                # ── 1H RSI check ─────────────────────────────
                h1_rsi_val = rsi(h1_closes, 14)
                result.h1_rsi_value = round(h1_rsi_val, 1)

                if h1_rsi_val >= H1_RSI_OB:
                    result.h1_rsi_state = "overbought"
                elif h1_rsi_val <= H1_RSI_OS:
                    result.h1_rsi_state = "oversold"
                else:
                    result.h1_rsi_state = "neutral"

                # Block: overbought → no LONG | oversold → no SHORT
                rsi_blocked = (
                    (result.h1_rsi_state == "overbought" and direction == "long") or
                    (result.h1_rsi_state == "oversold"   and direction == "short")
                )
                if rsi_blocked:
                    result.h1_rsi_blocked   = True
                    result.total_score      = score
                    result.signal_direction = direction
                    result.trade_signal     = False
                    log.debug(f"{pair}: blocked by 1H RSI={h1_rsi_val:.1f} ({result.h1_rsi_state}) signal={direction}")
                    return result

                # ── 1H Trend Bias check ───────────────────────
                if h1_adx >= 20:
                    if h1_ema9 > h1_ema21 and h1_pdi > h1_mdi:
                        h1_bias = "long"
                    elif h1_ema9 < h1_ema21 and h1_mdi > h1_pdi:
                        h1_bias = "short"
                    else:
                        h1_bias = "neutral"

                    if h1_bias != "neutral" and h1_bias != direction:
                        log.debug(f"{pair}: blocked by 1H bias={h1_bias} (signal={direction})")
                        result.total_score      = score
                        result.signal_direction = direction
                        result.trade_signal     = False
                        return result
        except Exception:
            pass  # 1H data unavailable — skip gate, don't block

        # ── Layer 2: CVD Divergence ──────────────────────────
        # Use candle-close-synced CVD so price and CVD are over the same time window.
        # cvd_at_close is snapshotted once per candle close (same rate as e_closes).
        cvd_hist = self.md.get_cvd_at_close(pair, cfg["entry_tf"])
        p_hist   = e_closes  # candle closes — aligned with cvd_at_close

        if cvd_divergence(p_hist, cvd_hist, direction, lookback=10):
            result.cvd_divergence = 1
            score += 1

        # ── Layer 3: VWAP Retracement ────────────────────────
        # Price must have been extended from VWAP and now returning toward it.
        # Confirms real mean reversion — not just proximity noise.
        if vwap_retracement(
            e_closes, e_highs, e_lows, e_volumes, direction,
            min_dev_pct=cfg["vwap_dev_pct"],
            precomputed_vwap=result.vwap_value,
        ):
            result.vwap_deviation = 1
            score += 1

        # ── Layer 4: DOM Imbalance ───────────────────────────
        # Spoof-resistant: require majority of last 3 snapshots to agree.
        # A single outsized order (spoof) lasts 1-2 ticks; genuine imbalance persists.
        dom_snapshots = self.md.get_dom_history(pair)
        if not dom_snapshots:
            dom_snapshots = [self.md.get_orderbook(pair)]

        dom_votes = []
        dom_ratios = []
        for snap in dom_snapshots[-3:]:
            sig, ratio = dom_imbalance(
                snap["bids"], snap["asks"],
                levels=cfg["dom_levels"],
                threshold=cfg["dom_ratio"],
            )
            dom_votes.append(sig)
            dom_ratios.append(ratio)

        result.dom_ratio = round(sum(dom_ratios) / len(dom_ratios), 4)

        long_votes  = sum(1 for v in dom_votes if v ==  1)
        short_votes = sum(1 for v in dom_votes if v == -1)
        needed      = max(2, (len(dom_votes) + 1) // 2)  # majority

        if direction == "long"  and long_votes  >= needed:
            result.dom_imbalance = 1
            score += 1
        elif direction == "short" and short_votes >= needed:
            result.dom_imbalance = 1
            score += 1

        # ── Layer 5: RSI Extreme + Hook ──────────────────────
        # Level: RSI must be in extreme zone (oversold/overbought).
        # Hook:  RSI must be turning back — current > prev for LONG,
        #        current < prev for SHORT. Prevents entry while still falling.
        rsi_val  = result.rsi2_value  # already computed above
        rsi_prev = rsi(e_closes[:-1], cfg["rsi_period"])

        if direction == "long" and rsi_val <= cfg["rsi_oversold"]:
            if rsi_val >= rsi_prev:  # hook: RSI turning up from extreme
                result.rsi2_extreme = 1
                score += 1
        elif direction == "short" and rsi_val >= cfg["rsi_overbought"]:
            if rsi_val <= rsi_prev:  # hook: RSI turning down from extreme
                result.rsi2_extreme = 1
                score += 1

        # ── Layer 6: Liquidity Sweep ─────────────────────────
        swept = detect_liquidity_sweep(
            e_highs, e_lows, e_closes, direction,
            threshold=cfg["sweep_threshold"],
        )
        if swept:
            result.liquidity_sweep = 1
            result.sweep_type      = direction
            score += 1

        # ── Layer 7: Fair Value Gap ──────────────────────────
        fvg_hit, fvg_mid = detect_fvg(e_highs, e_lows, price, direction)
        if fvg_hit:
            result.fair_value_gap = 1
            result.fvg_type       = direction
            result.fvg_level      = round(fvg_mid or 0, 6)
            score += 1

        # ── Final signal ─────────────────────────────────────
        result.total_score      = score
        result.signal_direction = direction

        # ── L8: EMA Pullback (mandatory gate — restored 2026-07-26 per user
        # request). Price near EMA-9 pullback/bounce check. Not counted toward
        # total_score (still out of 7), but trade_signal requires it green.
        pullback_ok = ema_pullback(e_closes, direction, period=9, tolerance_pct=0.0075)
        result.ema_pullback = 1 if pullback_ok else 0

        if score >= MIN_SIGNAL_SCORE and quality_ok and pullback_ok:
            result.trade_signal = True
        else:
            result.trade_signal = False

        return result
