import asyncio
import logging
import time
import hmac
import hashlib
import aiohttp
from urllib.parse import urlencode
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Any

from config import SCALPING, SWING, POSITION_CHECK_INTERVAL, BINANCE_API_KEY, BINANCE_SECRET_KEY
from core.signal_engine import SignalResult
from core.risk_manager import RiskManager
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
        price_prec = PRICE_PRECISION.get(symbol, 4)
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
        price_prec = PRICE_PRECISION.get(symbol, 4)
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
    def __init__(self, risk: RiskManager, on_update: Callable, mode: str = "demo", leverage: float = 5.0, trader_name: str = "Unknown"):
        self.risk        = risk
        self.on_update   = on_update
        self.mode        = mode
        self.leverage    = leverage
        self.trader_name = trader_name

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
        """Live mode: sync actual Binance futures balance + precision into _balance."""
        if self.mode != "live" or not self._binance:
            return
        try:
            bal = await self._binance.get_account_balance()
            binance_bal = bal.get("futures_usdt", 0)
            if binance_bal > 0:
                self._balance         = binance_bal
                self._initial_balance = binance_bal
                log.info(f"Live balance synced from Binance: ${binance_bal:.2f}")
        except Exception as e:
            log.warning(f"Binance balance sync failed: {e}")

        # Auto-fetch precision from Binance — overrides hardcoded fallback
        try:
            prec = await self._binance.fetch_precision()
            self._qty_prec   = prec["qty"]
            self._price_prec = prec["price"]
        except Exception as e:
            log.warning(f"Precision fetch failed: {e}")

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
        cfg = SCALPING if style == "scalping" else SWING

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

        wallet = await asyncio.to_thread(db.get_wallet, self.mode)
        if not wallet:
            log.error(f"Wallet not found for mode={self.mode} — run supabase_schema.sql in Supabase SQL Editor!")
            return False

        allowed, reason = self.risk.check(self.mode, wallet)
        if not allowed:
            log.info(f"Trade blocked — {reason}")
            return False

        entry_price = signal.current_price
        if entry_price <= 0:
            log.warning(f"Entry blocked — price is 0 for {pair}")
            return False

        sizing = self.risk.calculate_position(
            self._balance, capital_pct,
            entry_price, signal.atr_value, cfg["atr_sl_mult"],
            user_leverage=self.leverage
        )

        # Reversed 2026-07-10 per user request — execute the OPPOSITE of what the
        # signal engine detects. All 7 layers + L8 still score/gate the TRUE
        # direction above; only the actual executed side flips here.
        direction = "short" if signal.signal_direction == "long" else "long"
        sl_dist   = sizing["sl_distance"]

        # Actual SL is placed tighter than the full 1R distance (risk_amount stays
        # anchored to sl_dist, so an SL-out reports sl_entry_r, e.g. -0.75R, not -1.00R).
        sl_entry_dist = sl_dist * cfg.get("sl_entry_r", 1.0)

        # Fixed 1:1 R:R — TP at +1R, no trailing SL (removed 2026-07-10 per user
        # request). TP distance matches the actual SL distance, not the full 1R
        # risk_amount reference, so TP lands exactly where SL would if it were at 1R.
        tp_dist = sl_entry_dist

        if direction == "long":
            sl_price = entry_price - sl_entry_dist
            tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_entry_dist
            tp_price = entry_price - tp_dist

        # Entry fee (taker 0.05%) on position size
        entry_fee    = sizing["position_size_usd"] * TAKER_FEE_RATE
        total_fee_est = entry_fee * 2  # entry + exit

        # Gate: risk must be at least 3× total fee
        if sizing["risk_amount"] < total_fee_est * 3.0:
            log.info(f"{pair}: skipped — risk ₹{sizing['risk_amount']:.1f} too small vs fee ₹{total_fee_est:.1f}")
            return False

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
        }

        trade_id = await asyncio.to_thread(db.open_trade, trade_data)
        if not trade_id:
            log.error("Failed to insert trade into Supabase — check table exists & RLS disabled")
            return False

        # ── Live: Place actual Binance Futures order ──────────
        if self.mode == "live" and self._binance:
            symbol = pair + "USDT" if not pair.endswith("USDT") else pair

            # Use Binance-fetched precision if available, else hardcoded fallback
            if self._qty_prec:
                SYMBOL_PRECISION[symbol]  = self._qty_prec.get(symbol,  SYMBOL_PRECISION.get(symbol, 2))
                PRICE_PRECISION[symbol]   = self._price_prec.get(symbol, PRICE_PRECISION.get(symbol, 4))

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

        log.info(f"TRADE OPENED: {direction.upper()} {pair} @ {entry_price:.4f} | "
                 f"SL:{sl_price:.4f} TP:{tp_price:.4f} | ${sizing['risk_amount']:.2f} risk")

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

        highest_pnl = 0.0

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

                # Update position in DB (every 5 checks to reduce writes)
                if int(elapsed * 2) % 10 == 0:
                    try:
                        await asyncio.to_thread(
                            db.update_position,
                            position_id, current_price,
                            round(pnl, 4), round(pnl_pct * 100, 4),
                            round(highest_pnl, 4),
                            sl_price=round(sl_price, 6),
                        )
                    except Exception as e:
                        log.warning(f"{pair} DB update failed (non-fatal): {e}")

                await self.on_update({
                    "type": "position_update",
                    "data": {
                        "pair":          pair,
                        "direction":     direction,
                        "entry":         entry_price,
                        "current":       current_price,
                        "sl":            sl_price,
                        "tp":            tp_price,
                        "pnl":           round(pnl, 4),
                        "pnl_pct":       round(pnl_pct * 100, 4),
                        "r":             round(r_current, 3),
                        "highest_pnl":   round(highest_pnl, 4),
                        "elapsed_sec":   int(elapsed),
                        "size_usd":      round(pos_size_usd, 2),
                        "risk_usd":      round(risk_amount, 2),
                    }
                })

                # ── Exit conditions — fixed SL (-1R) / fixed TP (+1R), no trailing ──
                exit_reason = None
                if direction == "long":
                    if current_price <= sl_price:
                        exit_reason = "sl"
                    elif current_price >= tp_price:
                        exit_reason = "tp"
                else:
                    if current_price >= sl_price:
                        exit_reason = "sl"
                    elif current_price <= tp_price:
                        exit_reason = "tp"

                if exit_reason:
                    exit_p = sl_price if exit_reason == "sl" else tp_price
                    if direction == "long":
                        exit_pct = (exit_p - entry_price) / entry_price
                    else:
                        exit_pct = (entry_price - exit_p) / entry_price
                    exit_pnl = exit_pct * pos_size_usd

                    await self._close_position(pair, trade_id, position_id, pos_snapshot,
                                               exit_p, exit_pnl, exit_pct, risk_amount,
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

        # SL cooldown — set on SL exit to block re-entry for 20 min
        if reason == "sl":
            self._sl_cooldown[pair] = time.time()
            log.info(f"{pair}: SL cooldown started — no re-entry for 20 min")

        # ── Live: Close position on Binance ──────────────────
        if self.mode == "live" and self._binance:
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

        log.info(f"TRADE CLOSED: {pair} | {reason.upper()} | PnL=${pnl:.2f} ({pnl_pct*100:.2f}%) | R={r_multiple:.2f}")

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
            cfg_map = {"scalping": SCALPING, "swing": SWING}
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
                    "_entry_time":       datetime.now(timezone.utc),  # approximate from now
                }
                trade_id    = p["trade_id"]
                position_id = p["position_id"]
                style       = p.get("style", "scalping")
                cfg         = cfg_map.get(style, SCALPING)
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
                price_prec = PRICE_PRECISION.get(symbol, 4)
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

                    # Start software position monitor (trailing, -1R exit, etc.)
                    monitor_task = asyncio.create_task(
                        self._monitor_position(pair, "scalping", SCALPING, trade_id, pos_id, pos_snapshot)
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
        return sum(len(v) for v in self._open.values())

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

                if direction == "long":
                    pnl_pct = (current - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current) / entry_price

                pnl       = pnl_pct * pos_size_usd
                r_current = pnl / risk_amount if risk_amount > 0 else 0

                # Calculate actual elapsed time from stored entry_time
                entry_time  = pos.get("_entry_time")
                elapsed_sec = int((datetime.now(timezone.utc) - entry_time).total_seconds()) \
                              if entry_time else 0

                result.append({
                    "pair":          pair,
                    "direction":     direction,
                    "entry":         entry_price,
                    "current":       current,
                    "sl":            sl_price,
                    "tp":            tp_price,
                    "pnl":           round(pnl, 4),
                    "pnl_pct":       round(pnl_pct * 100, 4),
                    "r":             round(r_current, 3),
                    "highest_pnl":   0,
                    "breakeven_hit": False,
                    "profit_locked": False,
                    "trailing_sl":   sl_price,
                    "elapsed_sec":   elapsed_sec,
                    "size_usd":      round(pos_size_usd, 2),
                    "risk_usd":      round(risk_amount, 2),
                })
        return result
