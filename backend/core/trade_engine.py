import asyncio
import logging
import time
import hmac
import hashlib
import aiohttp
from urllib.parse import urlencode
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Any

from config import (SCALPING, SWING, POSITION_CHECK_INTERVAL, BINANCE_API_KEY,
                    BINANCE_SECRET_KEY, style_cfg)
from core.signal_engine import SignalResult
from core.risk_manager import RiskManager
from core.adaptive_filter import AdaptiveFilter
import core.supabase_client as db

log = logging.getLogger("trade_engine")

# Binance Futures taker fee: 0.05% per side (raised from 0.04% on 2026-07-03)
TAKER_FEE_RATE = 0.05 / 100

BINANCE_FUTURES_BASE = "https://fapi.binance.com"

# Minimum quantity precision per symbol (Binance requirement)
SYMBOL_PRECISION = {
    # TIER 1
    "JUPUSDT": 1, "NEARUSDT": 1, "SUIUSDT": 1, "STXUSDT": 1,
    "OPUSDT": 1, "DOGEUSDT": 0, "WIFUSDT": 0, "SOLUSDT": 1,
    "NOTUSDT": 0, "APTUSDT": 1,
    # TIER 2
    "TONUSDT": 0, "ADAUSDT": 0, "AVAXUSDT": 1, "ARBUSDT": 1,
    "TIAUSDT": 1, "ICPUSDT": 1, "BTCUSDT": 3, "ETHUSDT": 3,
    "LINKUSDT": 1, "HBARUSDT": 0,
    # TIER 3
    "DOTUSDT": 1, "ATOMUSDT": 1, "EIGENUSDT": 1, "UNIUSDT": 1,
    "RUNEUSDT": 1, "SEIUSDT": 0, "PEPEUSDT": 0,
    # TIER 4
    "TAOUSDT": 2, "ONDOUSDT": 1, "ENAUSDT": 0, "FETUSDT": 1,
    "WLDUSDT": 1, "BONKUSDT": 0, "BCHUSDT": 3, "POLUSDT": 0,
}

# Binance stop price tick size per symbol (decimal places for price rounding)
PRICE_PRECISION = {
    # TIER 1
    "JUPUSDT": 4, "NEARUSDT": 4, "SUIUSDT": 4, "STXUSDT": 4,
    "OPUSDT": 4, "DOGEUSDT": 5, "WIFUSDT": 4, "SOLUSDT": 3,
    "NOTUSDT": 6, "APTUSDT": 3,
    # TIER 2
    "TONUSDT": 4, "ADAUSDT": 4, "AVAXUSDT": 3, "ARBUSDT": 4,
    "TIAUSDT": 4, "ICPUSDT": 3, "BTCUSDT": 1, "ETHUSDT": 2,
    "LINKUSDT": 3, "HBARUSDT": 5,
    # TIER 3
    "DOTUSDT": 3, "ATOMUSDT": 3, "EIGENUSDT": 4, "UNIUSDT": 4,
    "RUNEUSDT": 4, "SEIUSDT": 4, "PEPEUSDT": 7,
    # TIER 4
    "TAOUSDT": 2, "ONDOUSDT": 4, "ENAUSDT": 4, "FETUSDT": 4,
    "WLDUSDT": 4, "BONKUSDT": 7, "BCHUSDT": 2, "POLUSDT": 4,
}


def get_price_precision(symbol: str) -> int:
    """Shared lookup for SL/TP price rounding. PRICE_PRECISION is populated from
    Binance's real tick sizes at bot startup (see TradeEngine.sync_live_balance) —
    the hardcoded table above and the `4` fallback here are last-resort only.
    A flat 4-decimal fallback badly distorts SL/TP for sub-cent tokens (confirmed
    bug on ALT/PENGU/SKL — 0.0001 tick was coarser than the intended R-distance)."""
    return PRICE_PRECISION.get(symbol, 4)


class BinanceFutures:
    """Thin async wrapper around Binance USDT-M Futures REST API."""

    def __init__(self, api_key: str, secret: str):
        self.api_key = api_key
        self.secret  = secret

    def _sign(self, params: dict) -> str:
        query = urlencode(params)
        return hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def _request(self, method: str, path: str, params: dict = None, signed: bool = False):
        params = params or {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        url = BINANCE_FUTURES_BASE + path
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url, params=params, headers=headers) as r:
                    return await r.json()
            elif method == "POST":
                async with session.post(url, params=params, headers=headers) as r:
                    return await r.json()
            elif method == "DELETE":
                async with session.delete(url, params=params, headers=headers) as r:
                    return await r.json()

    async def fetch_precision(self) -> dict:
        """Fetch quantity & price precision for all USDT-M futures symbols from Binance."""
        qty_prec   = {}
        price_prec = {}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(BINANCE_FUTURES_BASE + "/fapi/v1/exchangeInfo") as r:
                    data = await r.json()
            for sym in data.get("symbols", []):
                name = sym["symbol"]
                for f in sym.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        step = f["stepSize"]            # e.g. "1", "0.1", "0.001"
                        decimals = len(step.rstrip("0").split(".")[-1]) if "." in step else 0
                        qty_prec[name] = decimals
                    if f["filterType"] == "PRICE_FILTER":
                        tick = f["tickSize"]
                        decimals = len(tick.rstrip("0").split(".")[-1]) if "." in tick else 0
                        price_prec[name] = decimals
            log.info(f"Binance precision fetched for {len(qty_prec)} symbols ✅")
        except Exception as e:
            log.warning(f"Precision fetch failed — using hardcoded fallback: {e}")
        return {"qty": qty_prec, "price": price_prec}

    async def set_leverage(self, symbol: str, leverage: int):
        return await self._request("POST", "/fapi/v1/leverage", {
            "symbol": symbol, "leverage": leverage
        }, signed=True)

    async def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """side: BUY or SELL"""
        precision = SYMBOL_PRECISION.get(symbol, 3)
        qty = round(quantity, precision)
        return await self._request("POST", "/fapi/v1/order", {
            "symbol":   symbol,
            "side":     side,
            "type":     "MARKET",
            "quantity": qty,
        }, signed=True)

    async def place_stop_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> dict:
        """Place STOP_MARKET order for SL — closePosition=true closes full position on trigger.
        Uses MARK_PRICE to prevent immediate trigger on spreads/spikes.
        quantity param kept for call-site compatibility but NOT sent to Binance —
        closePosition and quantity/reduceOnly are mutually exclusive on /fapi/v1/order."""
        price_prec = get_price_precision(symbol)
        return await self._request("POST", "/fapi/v1/order", {
            "symbol":        symbol,
            "side":          side,
            "type":          "STOP_MARKET",
            "stopPrice":     round(stop_price, price_prec),
            "closePosition": "true",
            "workingType":   "MARK_PRICE",
        }, signed=True)

    async def place_tp_order(self, symbol: str, side: str, quantity: float, tp_price: float) -> dict:
        """Place TAKE_PROFIT_MARKET order — closePosition=true closes full position on trigger.
        Uses MARK_PRICE to prevent premature trigger.
        quantity param kept for call-site compatibility but NOT sent to Binance."""
        price_prec = get_price_precision(symbol)
        return await self._request("POST", "/fapi/v1/order", {
            "symbol":        symbol,
            "side":          side,
            "type":          "TAKE_PROFIT_MARKET",
            "stopPrice":     round(tp_price, price_prec),
            "closePosition": "true",
            "workingType":   "MARK_PRICE",
        }, signed=True)

    async def cancel_all_orders(self, symbol: str):
        return await self._request("DELETE", "/fapi/v1/allOpenOrders", {
            "symbol": symbol
        }, signed=True)

    async def get_position_size(self, symbol: str) -> float:
        """Returns current open position quantity (0 if no position)."""
        try:
            data = await self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)
            for p in (data if isinstance(data, list) else []):
                if p.get("symbol") == symbol:
                    return abs(float(p.get("positionAmt", 0)))
        except Exception:
            pass
        return 0.0

    async def close_position(self, symbol: str, side: str, quantity: float):
        """Close position with market order"""
        close_side = "SELL" if side == "BUY" else "BUY"
        return await self.place_market_order(symbol, close_side, quantity)

    async def get_account_balance(self) -> dict:
        """Returns futures + spot USDT balance"""
        # Futures balance
        futures_balance = 0.0
        try:
            data = await self._request("GET", "/fapi/v2/account", signed=True)
            for asset in data.get("assets", []):
                if asset["asset"] == "USDT":
                    futures_balance = float(asset["walletBalance"])
        except Exception:
            pass

        # Spot balance
        spot_balance = 0.0
        try:
            import aiohttp
            params = {"timestamp": int(time.time() * 1000)}
            import hmac as _hmac, hashlib as _hashlib
            from urllib.parse import urlencode as _urlencode
            query = _urlencode(params)
            params["signature"] = _hmac.new(self.secret.encode(), query.encode(), _hashlib.sha256).hexdigest()
            headers = {"X-MBX-APIKEY": self.api_key}
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.binance.com/api/v3/account", params=params, headers=headers) as r:
                    spot_data = await r.json()
            for b in spot_data.get("balances", []):
                if b["asset"] == "USDT":
                    spot_balance = float(b["free"])
        except Exception as e:
            log.warning(f"Spot balance fetch failed: {e}")

        return {
            "futures_usdt": futures_balance,
            "spot_usdt": spot_balance,
            "total_usdt": futures_balance + spot_balance,
        }

    async def get_all_open_positions(self) -> list:
        """Returns ALL open Binance Futures positions (non-zero positionAmt)."""
        try:
            data = await self._request("GET", "/fapi/v2/positionRisk", {}, signed=True)
            result = []
            for p in (data if isinstance(data, list) else []):
                amt = float(p.get("positionAmt", 0))
                if abs(amt) > 0:
                    result.append({
                        "symbol":           p["symbol"],
                        "positionAmt":      amt,
                        "entryPrice":       float(p.get("entryPrice", 0)),
                        "markPrice":        float(p.get("markPrice", 0)),
                        "unrealizedProfit": float(p.get("unRealizedProfit", 0)),
                        "leverage":         int(p.get("leverage", 1)),
                    })
            return result
        except Exception as e:
            log.error(f"get_all_open_positions failed: {e}")
            return []

    async def get_open_orders(self, symbol: str) -> list:
        """Returns all open orders for a symbol — used to find existing SL during reconciliation."""
        try:
            data = await self._request("GET", "/fapi/v1/openOrders", {"symbol": symbol}, signed=True)
            return data if isinstance(data, list) else []
        except Exception as e:
            log.error(f"get_open_orders failed for {symbol}: {e}")
            return []


class TradeEngine:
    def __init__(self, risk: RiskManager, on_update: Callable, mode: str = "demo", leverage: float = 5.0,
                 trader_name: str = "Unknown", reverse_direction: bool = False):
        self.risk        = risk
        self.on_update   = on_update
        self.mode        = mode
        self.leverage    = leverage
        self.trader_name = trader_name
        # Trade the opposite of the signal engine's direction. Set per-run from the
        # frontend "Reverse Direction" toggle (see bot_controller.start()) — this is
        # separate from the 2026-07 reverse-execution experiment that was tried and
        # reverted in code; this is a user-controlled runtime switch, not a default.
        self.reverse_direction = reverse_direction

        # Binance Futures client (only used in live mode)
        self._binance: Optional[BinanceFutures] = None
        if mode == "live" and BINANCE_API_KEY and BINANCE_SECRET_KEY:
            self._binance = BinanceFutures(BINANCE_API_KEY, BINANCE_SECRET_KEY)
            log.info("Binance Futures client initialized ✅")
        elif mode == "live":
            log.warning("Live mode but BINANCE_API_KEY/SECRET not set — falling back to demo simulation")

        # Precision overrides fetched from Binance at startup (live mode)
        self._qty_prec:   dict = {}
        self._price_prec: dict = {}

        # Safe defaults — overwritten by bot_controller before use
        self._running   = False
        self._get_price = lambda pair: 0.0

        # Per-pair open positions: pair -> List of {trade_id, position_id, pos, monitor_task}
        # Allows max 2 positions per pair (4-signal + 5-signal pyramid)
        self._open: Dict[str, List] = {}

        # Per-pair SL cooldown: pair -> timestamp of last SL/trailing hit
        # Prevents re-entry on same coin for 20 min after SL
        self._sl_cooldown: Dict[str, float] = {}
        self._sl_cooldown_secs: int = 20 * 60  # 20 minutes

        # Per-pair failed-entry cooldown: pair -> timestamp of last order failure
        # Prevents spam retries when margin is insufficient or order is rejected
        self._entry_fail_cooldown: Dict[str, float] = {}
        self._entry_fail_cooldown_secs: int = 5 * 60  # 5 minutes

        # Adaptive per-pair filter — learns from this bot's own closed trades and
        # stops entering pairs whose recent net-R mean is negative. Warm-started
        # from the DB in warm_start_adaptive() so a restart doesn't wipe learning.
        self.adaptive = AdaptiveFilter()

        # Per-pair entry lock — prevents double entry during Binance order placement.
        # SL retry can take 1-3s while signal loop fires every 2s, creating a race window
        # where _open dict doesn't have the pair yet → second enter() fires on Binance.
        # Pair added on enter() start, ALWAYS removed in finally (success, fail, or exception).
        self._entering: set = set()

        self._initial_balance: float = 10000
        self._balance:         float = 10000
        self._total_pnl:       float = 0
        self._daily_pnl:       float = 0

    # ─── Init ────────────────────────────────────────────────

    def load_wallet(self):
        w = db.get_wallet(self.mode)
        self._balance         = w.get("balance", 10000)
        self._initial_balance = w.get("initial_balance", 10000)
        self._total_pnl       = w.get("total_pnl", 0)
        self._daily_pnl       = db.get_today_pnl(self.mode)
        log.info(f"Wallet loaded: ${self._balance:.2f} ({self.mode})")

    async def sync_live_balance(self):
        """Live mode: sync actual Binance futures balance into _balance."""
        if self.mode == "live" and self._binance:
            try:
                bal = await self._binance.get_account_balance()
                binance_bal = bal.get("futures_usdt", 0)
                if binance_bal > 0:
                    self._balance         = binance_bal
                    self._initial_balance = binance_bal
                    log.info(f"Live balance synced from Binance: ${binance_bal:.2f}")
            except Exception as e:
                log.warning(f"Binance balance sync failed: {e}")

        # Fetch real tick precision from Binance's public exchangeInfo — runs in
        # every mode (demo included), no API key needed. Without this, symbols
        # missing from the hardcoded PRICE_PRECISION table fall back to 4 decimals,
        # which badly distorts SL/TP for sub-cent tokens (confirmed bug: ALT,
        # PENGU, SKL all ran far past their intended SL/TP R-multiple because a
        # 0.0001 tick was coarser than the intended stop distance). Merged into
        # the global dicts here, at startup, before any trade rounds a price —
        # not lazily per-symbol on first trade.
        precision_client = self._binance or BinanceFutures("", "")
        try:
            prec = await precision_client.fetch_precision()
            self._qty_prec   = prec["qty"]
            self._price_prec = prec["price"]
            SYMBOL_PRECISION.update(self._qty_prec)
            PRICE_PRECISION.update(self._price_prec)
            log.info(
                f"Price/qty precision merged for {len(self._price_prec)} symbols "
                f"(mode={self.mode})"
            )
        except Exception as e:
            log.warning(f"Precision fetch failed — using hardcoded fallback: {e}")

    # ─── Enter Trade ────────────────────────────────────────

    async def enter(self, pair: str, style: str,
                    signal: SignalResult, capital_pct: float,
                    signal_score: int = 4) -> bool:
        # Double-entry lock: if this pair's entry is already in progress, skip.
        # Prevents race condition where SL retry (1-3s) overlaps with next signal scan (2s).
        if pair in self._entering:
            log.info(f"{pair}: entry already in progress — duplicate blocked ✋")
            return False
        self._entering.add(pair)
        try:
            return await self._enter_inner(pair, style, signal, capital_pct, signal_score)
        except Exception as e:
            log.error(f"ENTER FAILED [{pair}]: {e}", exc_info=True)
            return False
        finally:
            # ALWAYS unlock — whether success, fail, or exception
            self._entering.discard(pair)

    async def _enter_inner(self, pair: str, style: str,
                           signal: SignalResult, capital_pct: float,
                           signal_score: int = 4) -> bool:
        cfg = style_cfg(style)

        log.info(f"Attempting entry: {pair} | score={signal.total_score} | dir={signal.signal_direction}")

        # Per-pair SL cooldown check
        if pair in self._sl_cooldown:
            elapsed = time.time() - self._sl_cooldown[pair]
            remaining = self._sl_cooldown_secs - elapsed
            if remaining > 0:
                log.info(f"{pair}: blocked by SL cooldown — {int(remaining/60)}m {int(remaining%60)}s remaining")
                return False

        # Per-pair failed-entry cooldown check (5 min after any rejected order)
        if pair in self._entry_fail_cooldown:
            elapsed = time.time() - self._entry_fail_cooldown[pair]
            remaining = self._entry_fail_cooldown_secs - elapsed
            if remaining > 0:
                log.info(f"{pair}: blocked by failed-entry cooldown — {int(remaining/60)}m {int(remaining%60)}s remaining")
                return False

        # Adaptive per-pair filter — skip pairs whose own recent closed trades
        # have a negative mean net-R. Checked here (not earlier) so the cheap
        # cooldown checks still short-circuit first.
        adaptive_ok, adaptive_reason = self.adaptive.allows(pair)
        if not adaptive_ok:
            log.info(f"{pair}: blocked by adaptive filter — {adaptive_reason}")
            return False

        wallet = await asyncio.to_thread(db.get_wallet, self.mode)
        if not wallet:
            log.error(f"Wallet not found for mode={self.mode} — run supabase_schema.sql in Supabase SQL Editor!")
            return False

        allowed, reason = self.risk.check(self.mode, wallet, self.trader_name)
        if not allowed:
            log.info(f"Trade blocked — {reason}")
            return False

        entry_price = signal.current_price
        if entry_price <= 0:
            # A pair can have enough REST-fetched candles for is_ready()/the signal
            # to fire while its live WS stream has never delivered a tick, leaving
            # last_price at 0. Without a cooldown this retries every scan cycle
            # forever (~2s), spamming logs and the DB — observed on MMT with the
            # signal re-firing indefinitely. Cool it down like any other failed entry.
            self._entry_fail_cooldown[pair] = time.time()
            log.warning(f"Entry blocked — no live price for {pair} yet "
                        f"(WS tick not received); pausing entries "
                        f"{self._entry_fail_cooldown_secs // 60}m")
            return False

        sizing = self.risk.calculate_position(
            self._balance, capital_pct,
            entry_price, signal.atr_value, cfg["atr_sl_mult"],
            user_leverage=self.leverage
        )

        # Trade the signal engine's own direction (no reversal). The 2026-07-10 flip
        # was removed 2026-07-17 per user request.
        direction = signal.signal_direction
        if self.reverse_direction:
            direction = "short" if direction == "long" else "long"
        sl_dist   = sizing["sl_distance"]

        # Actual SL is placed tighter than the full 1R distance (risk_amount stays
        # anchored to sl_dist, so an SL-out reports sl_entry_r, e.g. -0.75R, not -1.00R).
        sl_entry_dist = sl_dist * cfg.get("sl_entry_r", 1.0)

        # TP is independent of SL (changed 2026-07-14 per user request — was previously
        # forced 1:1 with sl_entry_dist).
        # tp_entry_r may be None: no hard target, trailing is the only profit
        # exit. A far-away placeholder TP is still placed on Binance so the
        # exchange-side bracket exists, but the monitor's trailing logic will close
        # long before it — see _monitor_position.
        tp_r_cfg = cfg.get("tp_entry_r", cfg.get("sl_entry_r", 1.0))
        has_hard_tp = tp_r_cfg is not None
        tp_dist = sl_dist * (tp_r_cfg if has_hard_tp else 20.0)

        if direction == "long":
            sl_price = entry_price - sl_entry_dist
            tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_entry_dist
            tp_price = entry_price - tp_dist

        # Round to the exchange's actual tradable price tick — without this, TP/SL
        # sit at a theoretical price the market can never exactly reach (only display-
        # rounds to look equal), so the monitor's >=/<= check never fires and the
        # position rides past target instead of closing.
        symbol_prec = pair + "USDT" if not pair.endswith("USDT") else pair
        price_prec  = get_price_precision(symbol_prec)
        sl_price    = round(sl_price, price_prec)
        tp_price    = round(tp_price, price_prec)

        # Entry fee (taker 0.05%) on position size
        entry_fee    = sizing["position_size_usd"] * TAKER_FEE_RATE
        total_fee_est = entry_fee * 2  # entry + exit

        # Gate: risk must be at least 4× total fee (lowered from 5× on
        # 2026-09-11 per user request — lets more entries through in quiet,
        # low-ATR conditions; effective floor is now SL >= 0.4% of price
        # instead of 0.5%).
        #
        # NOTE — this contradicts the 2026-07-17 tuning it replaces: a
        # last-5-days sweep (365 trades) found the ratio 3-5 band (fee ~20-33%
        # of R) was net -$11k while ratio>=5 was net +$13.7k, and 5x beat both
        # 4x and 6x on net. Re-run that sweep on fresh trade history before
        # keeping 4x long-term.
        if sizing["risk_amount"] < total_fee_est * 4.0:
            log.info(f"{pair}: skipped — risk ₹{sizing['risk_amount']:.1f} too small vs fee ₹{total_fee_est:.1f}")
            # Same setup will fail this exact check every scan cycle until the
            # signal itself changes — cooldown it so it doesn't spam-retry.
            self._entry_fail_cooldown[pair] = time.time()
            return False

        # Shadow trade: SL is wider than MAX_SL_PCT of the position. Recorded in
        # full so the setup can be studied later, but it must not touch real
        # money or any counter the live strategy depends on.
        is_shadow = sizing.get("is_shadow", False)

        trade_data = {
            "mode":              self.mode,
            "pair":              pair,
            "direction":         direction,
            "style":             style,
            "entry_price":       entry_price,
            "quantity":          sizing["quantity"],
            "position_size_usd": sizing["position_size_usd"],
            "leverage":          sizing["leverage"],
            "risk_amount":       sizing["risk_amount"],
            "sl_price":          sl_price,
            "tp_price":          tp_price,
            "capital_pct":       capital_pct,
            "status":            "open",
            "signals_at_entry":  signal.to_dict(),
            "fee":               round(entry_fee, 4),
            "signal_score":      signal_score,
            "trader_name":       self.trader_name,
            "is_shadow":         is_shadow,
        }

        trade_id = await asyncio.to_thread(db.open_trade, trade_data)
        if not trade_id:
            log.error("Failed to insert trade into Supabase — check table exists & RLS disabled")
            return False

        # ── Live: Place actual Binance Futures order ──────────
        # Shadow trades never reach the exchange. Their PnL is excluded from the
        # wallet, so placing a real order would put money at risk that nothing
        # accounts for — the one combination that must never happen.
        if self.mode == "live" and self._binance and not is_shadow:
            symbol = pair + "USDT" if not pair.endswith("USDT") else pair

            try:
                # Set leverage
                await self._binance.set_leverage(symbol, int(self.leverage))

                # Entry market order
                side = "BUY" if direction == "long" else "SELL"
                order = await self._binance.place_market_order(symbol, side, sizing["quantity"])
                if "code" in order:
                    log.error(f"Binance order failed: {order}")
                    await asyncio.to_thread(db.mark_order_failed, trade_id)
                    # Dedicated failed-entry cooldown — 5 min, separate from SL cooldown
                    self._entry_fail_cooldown[pair] = time.time()
                    return False
                log.info(f"Binance ENTRY order placed: {order.get('orderId')} | {side} {symbol}")

                # Recalculate SL/TP from actual fill price to prevent "would immediately trigger"
                actual_fill = float(order.get("avgPrice") or order.get("price") or entry_price)
                if actual_fill > 0 and actual_fill != entry_price:
                    log.info(f"{pair}: Fill adjusted {entry_price:.6f} → {actual_fill:.6f} — recalculating SL/TP")
                    if direction == "long":
                        sl_price = actual_fill - sl_entry_dist
                        tp_price = actual_fill + tp_dist
                    else:
                        sl_price = actual_fill + sl_entry_dist
                        tp_price = actual_fill - tp_dist
                    entry_price = actual_fill

                # SL order — retry up to 3 times
                sl_side  = "SELL" if direction == "long" else "BUY"
                sl_placed = False
                for attempt in range(3):
                    sl_result = await self._binance.place_stop_order(symbol, sl_side, sizing["quantity"], sl_price)
                    if "code" not in sl_result:
                        log.info(f"Binance SL placed: {sl_result.get('orderId')} @ {sl_price:.6f}")
                        sl_placed = True
                        break
                    log.warning(f"{pair}: SL attempt {attempt+1}/3 failed: {sl_result} — retrying...")
                    await asyncio.sleep(0.3)
                if not sl_placed:
                    log.error(f"{pair}: SL FAILED after 3 attempts — software -1R monitor active as fallback")

                # TP order — best effort, not critical
                tp_result = await self._binance.place_tp_order(symbol, sl_side, sizing["quantity"], tp_price)
                if "code" in tp_result:
                    log.warning(f"{pair}: TP order failed: {tp_result}")
                else:
                    log.info(f"Binance TP placed: {tp_result.get('orderId')} @ {tp_price:.6f}")

            except Exception as e:
                log.error(f"Binance live order error: {e}", exc_info=True)

        pos_data = {
            "trade_id":          trade_id,
            "pair":              pair,
            "direction":         direction,
            "entry_price":       entry_price,
            "current_price":     entry_price,
            "quantity":          sizing["quantity"],
            "position_size_usd": sizing["position_size_usd"],
            "sl_price":          sl_price,
            "tp_price":          tp_price,
            "sl_pct":            sizing["sl_distance_pct"] * 100,
            "tp_pct":            (tp_dist / entry_price) * 100,
            "trailing_sl":       None,
            "status":            "active",
        }

        pos_id = await asyncio.to_thread(db.open_position, pos_data)

        pos_snapshot = {**trade_data, **pos_data, "id": pos_id, "_entry_time": datetime.now(timezone.utc)}
        monitor_task = asyncio.create_task(
            self._monitor_position(pair, style, cfg, trade_id, pos_id, pos_snapshot)
        )
        entry = {
            "trade_id":    trade_id,
            "position_id": pos_id,
            "pos":         pos_snapshot,
            "monitor_task": monitor_task,
        }
        if pair not in self._open:
            self._open[pair] = []
        self._open[pair].append(entry)

        log.info(f"{'👻 SHADOW OPENED' if is_shadow else 'TRADE OPENED'}: "
                 f"{direction.upper()} {pair} @ {entry_price:.4f} | "
                 f"SL:{sl_price:.4f} ({sizing['sl_distance_pct']*100:.2f}%) "
                 f"TP:{tp_price:.4f} | ${sizing['risk_amount']:.2f} risk")

        await self.on_update({
            "type": "trade_opened",
            "data": {
                "pair":      pair,
                "direction": direction,
                "entry":     entry_price,
                "sl":        sl_price,
                "tp":        tp_price,
                "size_usd":  sizing["position_size_usd"],
                "risk_usd":  sizing["risk_amount"],
                "is_shadow": is_shadow,
            }
        })
        return True

    # ─── Position Monitor ────────────────────────────────────

    async def _monitor_position(self, pair: str, style: str, cfg: Dict,
                                trade_id: str, position_id: str, pos_snapshot: Dict):
        entry_price  = pos_snapshot["entry_price"]
        direction    = pos_snapshot["direction"]
        sl_price     = pos_snapshot["sl_price"]
        tp_price     = pos_snapshot["tp_price"]
        pos_size_usd = pos_snapshot["position_size_usd"]
        risk_amount  = pos_snapshot["risk_amount"]
        entry_time   = datetime.now(timezone.utc)

        # R-multiple exit thresholds — same lookup used at entry (see enter(),
        # sl_entry_dist/tp_dist), so the monitor's trigger always matches what
        # was actually intended for this trade.
        sl_r = cfg.get("sl_entry_r", 1.0)
        # None = no hard target at all; trailing is the only way out
        # on the profit side. Every use of tp_r below must be None-guarded.
        tp_r = cfg.get("tp_entry_r", cfg.get("sl_entry_r", 1.0))
        # [(peak_r_trigger, stop_r), ...], lowest trigger first. Empty = no trailing.
        trail_steps = sorted(cfg.get("trail_steps") or [], key=lambda s: s[0])

        highest_pnl = 0.0
        highest_r    = 0.0     # peak R reached — arms steps, does not move the stop
        trail_armed  = False   # True once any step has fired
        trail_stop_r = None    # current stop level in R; only ever tightens
        _last_db_write = 0.0  # ts of last DB position write — time-based throttle below

        _consecutive_errors = 0  # track back-to-back errors to detect hard failures

        while pair in self._open and self._open[pair] and self._running:
            try:
                await asyncio.sleep(POSITION_CHECK_INTERVAL)

                current_price = self._get_price(pair)
                if current_price <= 0:
                    continue

                elapsed = (datetime.now(timezone.utc) - entry_time).total_seconds()

                # ── PnL calculation ──────────────────────────────
                if direction == "long":
                    pnl_pct = (current_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current_price) / entry_price

                pnl = pnl_pct * pos_size_usd
                highest_pnl = max(highest_pnl, pnl)
                r_current = pnl / risk_amount if risk_amount > 0 else 0

                # Trailing ladder (config: trail_steps). Each step fires once, the
                # first tick whose PEAK R reaches its trigger, and moves the stop to
                # that step's level. The stop only tightens — a step whose level is
                # not above the current stop is ignored — and it does NOT ratchet
                # continuously between steps: a trade that peaks +1.9R with steps at
                # 1.5 still exits at that step's +1.0R, not +1.4R.
                #
                # Levels are read from the step, never derived from highest_r. At
                # sub-second ticks a volatile pair can jump clean past a trigger in
                # one tick, and using highest_r would silently set a different level
                # than the one configured.
                #
                # A step's level may be NEGATIVE — (0.8, -0.5) cuts the loss on a
                # trade that showed +0.8R and reversed. Such a step still counts as
                # armed (the trailing stop governs the exit from then on, replacing
                # sl_r below), but it is not a profit lock; see profit_locked.
                if r_current > highest_r:
                    highest_r = r_current
                for _trig, _stop in trail_steps:
                    if highest_r >= _trig and (trail_stop_r is None or _stop > trail_stop_r):
                        trail_stop_r = _stop
                        trail_armed  = True
                        log.info(f"{pair}: trail step {_trig:+.2f}R fired — stop now "
                                 f"{_stop:+.2f}R (peak +{highest_r:.2f}R)")

                # Convert the R-based trailing stop back to an actual price for
                # display/DB — inverse of r = pnl/risk_amount, pnl = pnl_pct*pos_size_usd.
                display_sl = sl_price
                if trail_armed and trail_stop_r is not None:
                    stop_pnl_pct = trail_stop_r * risk_amount / pos_size_usd
                    display_sl = (entry_price * (1 + stop_pnl_pct) if direction == "long"
                                  else entry_price * (1 - stop_pnl_pct))

                # Update position in DB every ~5s. Time-based so it's independent of
                # POSITION_CHECK_INTERVAL — the old int(elapsed*2)%10 hack assumed 0.5s
                # ticks and would fire repeatedly at the new 0.2s interval.
                _now = time.time()
                if _now - _last_db_write >= 5.0:
                    _last_db_write = _now
                    try:
                        await asyncio.to_thread(
                            db.update_position,
                            position_id, current_price,
                            round(pnl, 4), round(pnl_pct * 100, 4),
                            round(highest_pnl, 4),
                            sl_price=round(display_sl, 6),
                        )
                    except Exception as e:
                        log.warning(f"{pair} DB update failed (non-fatal): {e}")

                await self.on_update({
                    "type": "position_update",
                    "data": {
                        "pair":            pair,
                        "direction":       direction,
                        "entry":           entry_price,
                        "current":         current_price,
                        "sl":              round(display_sl, 6),
                        "tp":              tp_price,
                        # False when tp_r is None: tp_price is a far-away placeholder
                        # bracket, not a real target — the UI must not show it.
                        "has_hard_tp":     tp_r is not None,
                        "pnl":             round(pnl, 4),
                        "pnl_pct":         round(pnl_pct * 100, 4),
                        "r":               round(r_current, 3),
                        "highest_pnl":     round(highest_pnl, 4),
                        "trailing_armed":  trail_armed,
                        # Only true when the trailing stop actually sits in profit.
                        # A negative step (the 0.8R -> -0.5R loss cut) arms trailing
                        # but locks nothing — the UI's green LOCKED badge would lie.
                        "profit_locked":   trail_stop_r is not None and trail_stop_r > 0,
                        "trailing_sl":     round(display_sl, 6) if trail_armed else None,
                        "elapsed_sec":     int(elapsed),
                        "size_usd":        round(pos_size_usd, 2),
                        "risk_usd":        round(risk_amount, 2),
                    }
                })

                # ── Exit conditions — R-multiple based, not raw price ──────────────
                # r_current's sign already encodes direction via pnl (long/short
                # handled above), so this check is direction-agnostic. Using R
                # instead of comparing current_price against sl_price/tp_price
                # avoids the exchange-tick-size rounding that previously let
                # trades run far past their intended SL/TP (confirmed bug: ALT,
                # PENGU, SKL all missed their exit because the rounded sl_price/
                # tp_price landed at the wrong tick for sub-cent tokens).
                exit_reason = None
                if tp_r is not None and r_current >= tp_r:
                    exit_reason = "tp"   # hard-cap exit
                elif trail_armed and r_current <= trail_stop_r:
                    # trailing stop hit — peak cleared a trail_steps trigger, then
                    # pulled back to that step's level. Note this fires for negative
                    # steps too, so a "trailing" exit is not necessarily a profit.
                    exit_reason = "trailing"
                elif not trail_armed and r_current <= -sl_r:
                    exit_reason = "sl"

                if exit_reason:
                    # Use the actual current price/pnl at trigger time, not the
                    # theoretical sl_price/tp_price target — more accurate and
                    # immune to any remaining price-rounding distortion.
                    await self._close_position(pair, trade_id, position_id, pos_snapshot,
                                               current_price, pnl, pnl_pct, risk_amount,
                                               exit_reason, entry_time)
                    return

                # Reset error counter on successful iteration
                _consecutive_errors = 0

            except asyncio.CancelledError:
                raise  # always let cancellation propagate
            except Exception as e:
                _consecutive_errors += 1
                log.error(f"{pair} monitor error #{_consecutive_errors}: {e}", exc_info=True)
                if _consecutive_errors >= 10:
                    log.critical(f"{pair} monitor: 10 consecutive errors — stopping monitor to prevent silent failure")
                    return
                await asyncio.sleep(1)  # brief pause before retrying

    # ─── Close Position ──────────────────────────────────────

    async def _close_position(self, pair: str, trade_id: str, position_id: str,
                               pos_snapshot: Dict, exit_price: float, pnl: float,
                               pnl_pct: float, risk_amount: float, reason: str,
                               entry_time: Optional[datetime] = None):
        if pair not in self._open:
            return

        # Remove this specific trade from the list
        self._open[pair] = [e for e in self._open[pair] if e["trade_id"] != trade_id]
        if not self._open[pair]:
            del self._open[pair]

        # Post-exit cooldown — set on SL or TP exit to block re-entry for 20 min
        if reason in ("sl", "tp"):
            self._sl_cooldown[pair] = time.time()
            log.info(f"{pair}: post-exit cooldown started ({reason.upper()}) — no re-entry for 20 min")

        is_shadow = pos_snapshot.get("is_shadow", False)

        # ── Live: Close position on Binance ──────────────────
        # Nothing was ever opened on the exchange for a shadow trade.
        if self.mode == "live" and self._binance and not is_shadow:
            symbol = pair + "USDT" if not pair.endswith("USDT") else pair
            try:
                await self._binance.cancel_all_orders(symbol)
                # Guard: only place market close if Binance still holds an open position.
                # If Binance SL/TP already fired, position is gone — placing a market order
                # here would open a new opposite position unintentionally.
                live_qty = await self._binance.get_position_size(symbol)
                if live_qty > 0:
                    direction  = pos_snapshot.get("direction", "long")
                    close_side = "SELL" if direction == "long" else "BUY"
                    order = await self._binance.place_market_order(symbol, close_side, live_qty)
                    log.info(f"Binance CLOSE order placed: {order.get('orderId')} | {reason}")
                else:
                    log.info(f"{pair}: Binance position already closed (SL/TP fired) — skipping market order")
            except Exception as e:
                log.error(f"Binance close order error: {e}", exc_info=True)

        r_multiple = pnl / risk_amount if risk_amount > 0 else 0
        duration   = int((datetime.now(timezone.utc) - entry_time).total_seconds()) if entry_time else 0

        # Fee: entry fee already stored — add exit fee here
        pos_size_usd = pos_snapshot.get("position_size_usd", 0)
        exit_fee     = pos_size_usd * TAKER_FEE_RATE
        entry_fee    = pos_snapshot.get("fee", pos_size_usd * TAKER_FEE_RATE)
        total_fee    = round(entry_fee + exit_fee, 4)
        net_pnl      = round(pnl - total_fee, 4)

        await asyncio.to_thread(
            db.close_trade, trade_id, exit_price,
            round(pnl, 4), round(pnl_pct * 100, 4),
            round(r_multiple, 4), reason, duration,
            total_fee, net_pnl
        )
        await asyncio.to_thread(db.close_position, position_id)

        # A shadow trade's result is written to `trades` and stops there. It never
        # moves the wallet, never feeds the loss-streak counter, and never teaches
        # the adaptive filter — otherwise a setup the strategy deliberately refused
        # to fund would still be steering it. The DB helpers below already exclude
        # is_shadow rows, so the wallet stays correct without special-casing here;
        # skipping the calls outright just avoids pointless round-trips.
        if not is_shadow:
            # Wallet — always recalculate from DB to stay accurate
            self._total_pnl = await asyncio.to_thread(db.get_total_pnl, self.mode)
            self._daily_pnl = await asyncio.to_thread(db.get_today_pnl, self.mode)
            self._balance   = self._initial_balance + self._total_pnl
            await asyncio.to_thread(
                db.update_wallet, self.mode, self._balance,
                self._total_pnl, self._initial_balance, self._daily_pnl
            )
            await asyncio.to_thread(db.upsert_performance, self.mode)

            self.risk.record_trade_result(pnl, self.mode)

            # Feed the adaptive filter. Uses NET R (after both fees) — fees run ~0.16R
            # per trade here, so gross r_multiple would make every pair look better
            # than it is. Recorded only now, at close, which keeps the filter causal.
            net_r = net_pnl / risk_amount if risk_amount > 0 else None
            self.adaptive.record(pair, net_r)

        log.info(f"{'👻 SHADOW CLOSED' if is_shadow else 'TRADE CLOSED'}: {pair} | "
                 f"{reason.upper()} | PnL=${pnl:.2f} ({pnl_pct*100:.2f}%) | R={r_multiple:.2f}"
                 f"{' — not counted in wallet/stats' if is_shadow else ''}")

        await self.on_update({
            "type": "trade_closed",
            "data": {
                "pair":      pair,
                "exit":      exit_price,
                "pnl":       round(pnl, 4),
                "pnl_pct":   round(pnl_pct * 100, 4),
                "r":         round(r_multiple, 4),
                "reason":    reason,
                "balance":   round(self._balance, 4),
                "total_pnl": round(self._total_pnl, 4),
                "is_shadow": is_shadow,
            }
        })

    async def force_close(self, pair: str, price: float):
        entries = list(self._open.get(pair, []))  # copy to avoid mutation during iteration
        for entry in entries:
            pos          = entry["pos"]
            entry_price  = pos["entry_price"]
            direction    = pos["direction"]
            pos_size_usd = pos["position_size_usd"]
            risk_amount  = pos.get("risk_amount", 1)
            # Recover entry_time for correct duration calculation
            entry_time   = pos.get("_entry_time")
            if direction == "long":
                pnl_pct = (price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - price) / entry_price
            pnl = pnl_pct * pos_size_usd
            await self._close_position(pair, entry["trade_id"], entry["position_id"],
                                       pos, price, pnl, pnl_pct, risk_amount, "manual", entry_time)

    async def recover_open_positions(self):
        """On bot start, recover any DB-open positions from previous session and restart monitors."""
        try:
            open_positions = await asyncio.to_thread(db.get_all_active_positions, self.mode)
            if not open_positions:
                return
            log.info(f"Recovering {len(open_positions)} open position(s) from previous session...")
            for p in open_positions:
                pair = p["pair"]
                # Skip if already in _open (shouldn't happen on fresh start)
                if self.has_open_position(pair):
                    continue
                pos_snapshot = {
                    "trade_id":          p["trade_id"],
                    "id":                p["position_id"],
                    "pair":              pair,
                    "direction":         p["direction"],
                    "entry_price":       p["entry_price"],
                    "sl_price":          p["sl_price"],
                    "tp_price":          p["tp_price"],
                    "position_size_usd": p["position_size_usd"],
                    "risk_amount":       p["risk_amount"],
                    "quantity":          p["quantity"],
                    "fee":               p.get("fee", 0),
                    "mode":              self.mode,
                    "is_shadow":         p.get("is_shadow", False),
                    "_entry_time":       datetime.now(timezone.utc),  # approximate from now
                }
                trade_id    = p["trade_id"]
                position_id = p["position_id"]
                style       = p.get("style", "scalping")
                cfg         = style_cfg(style)
                monitor_task = asyncio.create_task(
                    self._monitor_position(pair, style, cfg, trade_id, position_id, pos_snapshot)
                )
                entry = {
                    "trade_id":    trade_id,
                    "position_id": position_id,
                    "pos":         pos_snapshot,
                    "monitor_task": monitor_task,
                }
                if pair not in self._open:
                    self._open[pair] = []
                self._open[pair].append(entry)
                log.info(f"Recovered: {p['direction'].upper()} {pair} @ {p['entry_price']:.6f} "
                         f"SL:{p['sl_price']:.6f}")
        except Exception as e:
            log.error(f"Position recovery failed: {e}", exc_info=True)

    async def _reconcile_binance_positions(self):
        """
        Detect positions open on Binance but NOT tracked in _open dict (orphans).
        Called on bot start (after recover_open_positions) and every 5 min by reconcile loop.

        For each orphan:
          1. Check Binance open orders for existing SL price
          2. If no SL found → use 1% of entry price as default SL
          3. If current price already past SL → close immediately (market order)
          4. Otherwise → create DB record, place SL+TP on Binance, start software monitor
        """
        if self.mode != "live" or not self._binance:
            return

        try:
            binance_positions = await self._binance.get_all_open_positions()
            if not binance_positions:
                return

            for bp in binance_positions:
                symbol = bp["symbol"]

                # Only handle USDT-M futures pairs
                if not symbol.endswith("USDT"):
                    continue

                # Re-check _open at each iteration (not a stale snapshot built before awaits)
                # This prevents a race where signal loop enters a pair mid-reconcile
                pair = symbol[:-4]  # strip "USDT" → "APT", "BTC" etc.
                if pair in self._open and self._open[pair]:
                    continue  # already tracked — skip
                amt         = bp["positionAmt"]
                entry_price = bp["entryPrice"]
                mark_price  = bp["markPrice"]
                direction   = "long" if amt > 0 else "short"
                quantity    = abs(amt)

                if entry_price <= 0 or mark_price <= 0:
                    log.warning(f"Orphan {symbol}: entry_price={entry_price} or mark_price={mark_price} is 0 — skipping")
                    continue

                log.warning(
                    f"⚠️  ORPHAN POSITION DETECTED: {direction.upper()} {symbol} "
                    f"qty={quantity} entry={entry_price} mark={mark_price}"
                )

                # ── Step 1: Find existing SL in Binance open orders ──────────────────
                sl_price         = None
                using_default_sl = False
                try:
                    open_orders = await self._binance.get_open_orders(symbol)
                    for order in open_orders:
                        otype = order.get("type", "")
                        oside = order.get("side", "")
                        # SL must be on the CLOSING side
                        is_sl_side = (
                            (direction == "long"  and oside == "SELL") or
                            (direction == "short" and oside == "BUY")
                        )
                        if otype == "STOP_MARKET" and is_sl_side:
                            sl_candidate = float(order.get("stopPrice", 0))
                            if sl_candidate > 0:
                                sl_price = sl_candidate
                                log.info(f"{symbol}: Existing SL found @ {sl_price}")
                                break
                except Exception as e:
                    log.error(f"{symbol}: Could not fetch open orders: {e}")

                # ── Step 2: No SL found → use 1% default ─────────────────────────────
                DEFAULT_SL_PCT = 0.01
                if sl_price is None or sl_price <= 0:
                    using_default_sl = True
                    if direction == "long":
                        sl_price = entry_price * (1.0 - DEFAULT_SL_PCT)
                    else:
                        sl_price = entry_price * (1.0 + DEFAULT_SL_PCT)
                    log.info(f"{symbol}: No SL found — 1% default SL @ {sl_price:.6f}")

                # ── Step 3: Check if current price already past SL ───────────────────
                sl_breached = (
                    (direction == "long"  and mark_price <= sl_price) or
                    (direction == "short" and mark_price >= sl_price)
                )

                if sl_breached:
                    log.warning(
                        f"🚨 {symbol}: Orphan already past SL "
                        f"(mark={mark_price:.6f} {'≤' if direction == 'long' else '≥'} "
                        f"sl={sl_price:.6f}) — CLOSING IMMEDIATELY"
                    )
                    try:
                        await self._binance.cancel_all_orders(symbol)
                        close_side  = "SELL" if direction == "long" else "BUY"
                        close_order = await self._binance.place_market_order(symbol, close_side, quantity)
                        if "code" in close_order:
                            log.error(f"{symbol}: Emergency close failed: {close_order}")
                        else:
                            log.info(f"{symbol}: Emergency close ✅ orderId={close_order.get('orderId')}")
                    except Exception as e:
                        log.error(f"{symbol}: Emergency close error: {e}", exc_info=True)
                    continue  # don't track — position is being closed

                # ── Step 4: Take ownership — create DB record + monitor ───────────────
                sl_dist          = abs(entry_price - sl_price)
                risk_amount      = round(sl_dist * quantity, 4)
                position_size_usd = round(quantity * entry_price, 4)
                entry_fee        = round(position_size_usd * TAKER_FEE_RATE, 4)

                # TP: 2:1 R:R from entry price
                tp_dist = sl_dist * 2.0
                if direction == "long":
                    tp_price = entry_price + tp_dist
                else:
                    tp_price = entry_price - tp_dist

                # Round prices to symbol precision
                price_prec = get_price_precision(symbol)
                sl_price   = round(sl_price,  price_prec)
                tp_price   = round(tp_price,  price_prec)

                trade_data = {
                    "mode":              self.mode,
                    "pair":              pair,
                    "direction":         direction,
                    "style":             "scalping",
                    "entry_price":       entry_price,
                    "quantity":          quantity,
                    "position_size_usd": position_size_usd,
                    "leverage":          bp.get("leverage", int(self.leverage)),
                    "risk_amount":       risk_amount,
                    "sl_price":          sl_price,
                    "tp_price":          tp_price,
                    "capital_pct":       1.0,
                    "status":            "open",
                    "fee":               entry_fee,
                    "signal_score":      0,
                    "trader_name":       self.trader_name,
                    "signals_at_entry":  {
                        "note":              "orphan_recovered",
                        "using_default_sl":  using_default_sl,
                    },
                }

                try:
                    trade_id = await asyncio.to_thread(db.open_trade, trade_data)
                    if not trade_id:
                        log.error(f"{symbol}: DB trade insert failed for orphan — skipping")
                        continue

                    sl_pct = round((sl_dist / entry_price) * 100, 4)
                    tp_pct = round((tp_dist / entry_price) * 100, 4)

                    pos_data = {
                        "trade_id":          trade_id,
                        "pair":              pair,
                        "direction":         direction,
                        "entry_price":       entry_price,
                        "current_price":     mark_price,
                        "quantity":          quantity,
                        "position_size_usd": position_size_usd,
                        "sl_price":          sl_price,
                        "tp_price":          tp_price,
                        "sl_pct":            sl_pct,
                        "tp_pct":            tp_pct,
                        "trailing_sl":       None,
                        "status":            "active",
                    }

                    pos_id = await asyncio.to_thread(db.open_position, pos_data)
                    if not pos_id:
                        log.error(f"{symbol}: DB position insert failed for orphan — skipping")
                        continue

                    # Place fresh SL + TP on Binance
                    sl_side = "SELL" if direction == "long" else "BUY"
                    try:
                        await self._binance.cancel_all_orders(symbol)
                        await asyncio.sleep(0.3)
                        sl_result = await self._binance.place_stop_order(symbol, sl_side, quantity, sl_price)
                        if "code" in sl_result:
                            log.warning(f"{symbol}: SL placement failed: {sl_result} — software monitor active")
                        else:
                            log.info(f"{symbol}: SL placed @ {sl_price} ✅")
                        tp_result = await self._binance.place_tp_order(symbol, sl_side, quantity, tp_price)
                        if "code" in tp_result:
                            log.warning(f"{symbol}: TP placement failed: {tp_result}")
                        else:
                            log.info(f"{symbol}: TP placed @ {tp_price} ✅")
                    except Exception as e:
                        log.warning(f"{symbol}: SL/TP placement error (software monitor active): {e}")

                    # Build pos_snapshot — same shape as normal trade entry
                    pos_snapshot = {
                        **trade_data,
                        "id":          pos_id,
                        "_entry_time": datetime.now(timezone.utc),
                    }

                    # Start software position monitor. This path's risk_amount IS the
                    # actual placed SL distance (sl_dist * quantity) and tp_dist is a
                    # fixed 2x that — a 1R/2R relationship, NOT the SCALPING cfg's
                    # sl_entry_r/tp_entry_r (which are multiples of a separate ATR-based
                    # reference distance). Override so the R-based exit check matches
                    # what was actually placed on Binance, instead of the primary
                    # entry path's thresholds.
                    orphan_cfg = {**SCALPING, "sl_entry_r": 1.0, "tp_entry_r": 2.0}
                    monitor_task = asyncio.create_task(
                        self._monitor_position(pair, "scalping", orphan_cfg, trade_id, pos_id, pos_snapshot)
                    )
                    entry_record = {
                        "trade_id":     trade_id,
                        "position_id":  pos_id,
                        "pos":          pos_snapshot,
                        "monitor_task": monitor_task,
                    }
                    if pair not in self._open:
                        self._open[pair] = []
                    self._open[pair].append(entry_record)

                    log.info(
                        f"✅ ORPHAN RECOVERED: {direction.upper()} {pair} "
                        f"entry={entry_price} SL={sl_price} TP={tp_price} "
                        f"risk=${risk_amount:.2f} | Monitor started"
                    )

                except Exception as e:
                    log.error(f"{symbol}: Orphan recovery error: {e}", exc_info=True)

        except Exception as e:
            log.error(f"_reconcile_binance_positions failed: {e}", exc_info=True)

    async def warm_start_adaptive(self) -> int:
        """Rebuild the adaptive filter from this bot's closed trades in the DB.

        Called once at startup — without it every restart would begin with an
        empty window and trade blocked pairs again until it relearned them.
        """
        if not self.adaptive.enabled:
            return 0
        try:
            rows = await asyncio.to_thread(
                db.get_closed_for_adaptive, self.mode, self.trader_name, 600
            )
            return self.adaptive.warm_start(rows)
        except Exception as e:
            log.warning(f"Adaptive warm-start failed (non-fatal, starts empty): {e}")
            return 0

    def adaptive_snapshot(self) -> Dict:
        return self.adaptive.snapshot()

    def set_price_getter(self, fn):
        self._get_price = fn

    def set_running(self, val: bool):
        self._running = val

    def has_open_position(self, pair: Optional[str] = None) -> bool:
        if pair:
            return pair in self._open and len(self._open[pair]) > 0
        return any(len(v) > 0 for v in self._open.values())

    def count_open_positions(self, pair: str) -> int:
        return len(self._open.get(pair, []))

    def total_open_positions(self) -> int:
        """Real open trades only — this feeds the max-concurrent-trades gate, and
        shadow trades must never consume one of those slots."""
        return sum(
            1
            for entries in self._open.values()
            for e in entries
            if not e["pos"].get("is_shadow", False)
        )

    def wallet_snapshot(self) -> Dict:
        return {
            "balance":         round(self._balance, 4),
            "initial_balance": round(self._initial_balance, 4),
            "total_pnl":       round(self._total_pnl, 4),
            "daily_pnl":       round(self._daily_pnl, 4),
            "total_pnl_pct":   round(self._total_pnl / self._initial_balance * 100, 4)
                               if self._initial_balance > 0 else 0,
        }

    def positions_snapshot(self) -> list:
        """Snapshot of all open positions — sent to reconnecting clients."""
        result = []
        for pair, entries in self._open.items():
            for e in entries:
                current      = self._get_price(pair)
                if current <= 0:
                    continue
                pos          = e.get("pos", {})
                direction    = pos.get("direction", "long")
                entry_price  = pos.get("entry_price", 0)
                sl_price     = pos.get("sl_price", 0)
                tp_price     = pos.get("tp_price", 0)
                pos_size_usd = pos.get("position_size_usd", 0)
                risk_amount  = pos.get("risk_amount", 1)
                style        = pos.get("style", "scalping")

                if direction == "long":
                    pnl_pct = (current - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current) / entry_price

                pnl       = pnl_pct * pos_size_usd
                r_current = pnl / risk_amount if risk_amount > 0 else 0

                # Reconnect snapshot has no memory of this position's historical peak
                # R (that lives in _monitor_position's closure) — best-effort using
                # r_current as the peak; the next live tick from the running monitor
                # corrects this immediately.
                cfg = style_cfg(style)
                trail_steps  = sorted(cfg.get("trail_steps") or [], key=lambda s: s[0])
                trail_stop_r = None
                for _trig, _stop in trail_steps:
                    if r_current >= _trig and (trail_stop_r is None or _stop > trail_stop_r):
                        trail_stop_r = _stop
                trail_armed = trail_stop_r is not None
                display_sl = sl_price
                if trail_armed:
                    stop_pnl_pct = trail_stop_r * risk_amount / pos_size_usd if pos_size_usd else 0
                    display_sl = (entry_price * (1 + stop_pnl_pct) if direction == "long"
                                  else entry_price * (1 - stop_pnl_pct))

                # Calculate actual elapsed time from stored entry_time
                entry_time  = pos.get("_entry_time")
                elapsed_sec = int((datetime.now(timezone.utc) - entry_time).total_seconds()) \
                              if entry_time else 0

                result.append({
                    "pair":            pair,
                    "direction":       direction,
                    "entry":           entry_price,
                    "current":         current,
                    "sl":              round(display_sl, 6),
                    "tp":              tp_price,
                    "has_hard_tp":     cfg.get("tp_entry_r", 1.0) is not None,
                    "pnl":             round(pnl, 4),
                    "pnl_pct":         round(pnl_pct * 100, 4),
                    "r":               round(r_current, 3),
                    "highest_pnl":     0,
                    "trailing_armed":  trail_armed,
                    # see _monitor_position: a negative step arms trailing without
                    # locking any profit
                    "profit_locked":   trail_stop_r is not None and trail_stop_r > 0,
                    "trailing_sl":     round(display_sl, 6) if trail_armed else None,
                    "elapsed_sec":     elapsed_sec,
                    "size_usd":        round(pos_size_usd, 2),
                    "risk_usd":        round(risk_amount, 2),
                })
        return result
