import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Set

from config import (SCALPING, SWING, SIGNAL_BROADCAST_INTERVAL, MIN_SIGNAL_SCORE,
                    TRADE_WINDOW_START, TRADE_WINDOW_END)
from core.market_data import MarketDataManager
from core.signal_engine import SignalEngine
from core.risk_manager import RiskManager
from core.trade_engine import TradeEngine
import core.supabase_client as db

log = logging.getLogger("bot_controller")


class BotController:
    def __init__(self):
        self._running  = False
        self._md       = MarketDataManager()
        self._risk     = RiskManager()
        self._engine:  Optional[TradeEngine] = None
        self._signals: Optional[SignalEngine] = None

        self._mode:         str   = "demo"
        self._style:        str   = "scalping"
        self._pairs:        List[str] = []
        self._capital_pct:  float = 1.0
        self._leverage:     float = 5.0
        self._reverse_direction: bool = False

        self._broadcast_cb: Optional[Callable] = None
        self._tasks:        List[asyncio.Task] = []

        # Last signal per pair (in-memory cache)
        self._last_signals: Dict[str, Dict] = {}

        # Night-gate skip log dedupe: pair -> (direction, 5m bucket) last logged.
        # The signal loop runs every 2s, so without this one blocked signal
        # would be logged ~150 times per 5m candle.
        self._gate_skip_logged: Dict[str, tuple] = {}

        # EMA9-filter skip log dedupe — same shape and reason as above.
        self._ema9_skip_logged: Dict[str, tuple] = {}

    # ─── Lifecycle ──────────────────────────────────────────

    async def start(self, mode: str, style: str, pairs: List[str],
                    capital_pct: float, broadcast_cb: Callable, leverage: float = 5.0,
                    trader_name: str = "Unknown", reverse_direction: bool = False):
        # main.py fires this via asyncio.create_task() and returns immediately —
        # an unhandled exception here is swallowed by asyncio (only visible as
        # "Task exception was never retrieved" in the process's own stderr/
        # journalctl, never in the app's log broadcast). That made a real start()
        # crash look identical to "nothing happened" in the frontend Logs panel.
        # Wrap the whole body so any failure is logged, broadcast, and _running
        # is reset — otherwise a crash mid-start also leaves the bot stuck
        # "running" with no way to retry without a server restart.
        try:
            await self._start_inner(mode, style, pairs, capital_pct, broadcast_cb,
                                    leverage, trader_name, reverse_direction)
        except Exception as e:
            log.error(f"Bot start failed: {e}", exc_info=True)
            self._running = False
            # Use the broadcast_cb PARAMETER, not self._broadcast_cb/self._broadcast() —
            # a crash early in _start_inner (before it assigns self._broadcast_cb) would
            # otherwise leave this silent, the exact failure mode this fix exists for.
            try:
                await broadcast_cb({
                    "type": "bot_status",
                    "data": {"running": False, "mode": mode, "style": style,
                            "pairs": pairs, "error": str(e)}
                })
            except Exception as be:
                log.debug(f"Broadcast of start-failure error failed: {be}")

    async def _start_inner(self, mode: str, style: str, pairs: List[str],
                           capital_pct: float, broadcast_cb: Callable, leverage: float = 5.0,
                           trader_name: str = "Unknown", reverse_direction: bool = False):
        if self._running:
            log.warning("Bot already running")
            return

        self._mode        = mode
        self._style       = style
        self._pairs       = pairs
        self._capital_pct = capital_pct
        self._leverage    = leverage
        self._trader_name = trader_name
        self._reverse_direction = reverse_direction
        self._broadcast_cb = broadcast_cb
        self._running     = True

        log.info(f"Bot starting | mode={mode} style={style} pairs={pairs} capital={capital_pct}% "
                 f"leverage={leverage}x reverse_direction={reverse_direction}")

        # Update DB config
        db.update_bot_config(
            is_running=True, mode=mode, style=style,
            capital_pct=capital_pct, selected_pairs=pairs,
        )

        # Init trade engine
        self._engine = TradeEngine(
            risk=self._risk,
            on_update=self._broadcast,
            mode=mode,
            leverage=leverage,
            trader_name=trader_name,
            reverse_direction=reverse_direction,
        )
        self._engine.set_price_getter(self._md.get_price)
        self._engine.set_running(True)
        self._engine.load_wallet()
        await self._engine.sync_live_balance()

        # Fresh start — clear circuit breaker, cooldowns, and entry locks
        self._risk.reset()
        self._engine._sl_cooldown.clear()
        self._engine._entry_fail_cooldown.clear()
        self._engine._entering.clear()

        # Init signal engine
        self._signals = SignalEngine(self._md)

        # Start market data
        await self._md.start(pairs, style)

        # Recover any positions left open from previous session (stop/start without server restart)
        await self._engine.recover_open_positions()

        # Rebuild the adaptive per-pair filter from closed-trade history, so a
        # restart doesn't forget which pairs have been losing.
        n_adaptive = await self._engine.warm_start_adaptive()
        if n_adaptive:
            blocked = self._engine.adaptive_snapshot().get("blocked", [])
            log.info(f"Adaptive filter warm-started from {n_adaptive} trades"
                     + (f" — currently blocking: {', '.join(blocked)}" if blocked else ""))

        # Live mode: immediately reconcile with Binance — catch orphan positions not in DB
        # (e.g. entry executed on Binance but Supabase write failed due to server disconnect)
        if self._mode == "live":
            await self._engine._reconcile_binance_positions()

        # Launch main loop tasks
        self._tasks = [
            asyncio.create_task(self._signal_loop()),
            asyncio.create_task(self._wallet_broadcast_loop()),
            asyncio.create_task(self._price_ticker_loop()),
            asyncio.create_task(self._binance_reconcile_loop()),
        ]

        await self._broadcast({"type": "bot_status", "data": {
            "running": True, "mode": mode, "style": style, "pairs": pairs,
            "reverse_direction": reverse_direction,
        }})
        log.info("Bot started")

    async def stop(self):
        if not self._running:
            return
        self._running = False
        self._engine.set_running(False)

        # Cancel signal/wallet/price tasks
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

        # Cancel all open position monitor tasks so they don't run as orphans
        if self._engine:
            monitor_tasks = [
                entry["monitor_task"]
                for entries in self._engine._open.values()
                for entry in entries
                if entry.get("monitor_task") and not entry["monitor_task"].done()
            ]
            if monitor_tasks:
                for task in monitor_tasks:
                    task.cancel()
                await asyncio.gather(*monitor_tasks, return_exceptions=True)
                log.info(f"Cancelled {len(monitor_tasks)} position monitor task(s)")

        await self._md.stop()
        db.update_bot_config(is_running=False)
        await self._broadcast({"type": "bot_status", "data": {"running": False}})
        log.info("Bot stopped")

    def is_running(self) -> bool:
        return self._running

    # ─── Trading Window ─────────────────────────────────────

    IST = timezone(timedelta(hours=5, minutes=30))

    def _in_trade_window(self) -> bool:
        """True when new entries are allowed (night gate added 2026-09-11).
        Handles a window that crosses midnight (START > END) too, though the
        current config's allowed window 01:00-18:00 does not need it."""
        if TRADE_WINDOW_START is None or TRADE_WINDOW_END is None:
            return True
        now = datetime.now(self.IST)
        t   = (now.hour, now.minute)
        if TRADE_WINDOW_START <= TRADE_WINDOW_END:
            return TRADE_WINDOW_START <= t < TRADE_WINDOW_END
        return t >= TRADE_WINDOW_START or t < TRADE_WINDOW_END

    @staticmethod
    def _fmt_window() -> str:
        return (f"{TRADE_WINDOW_START[0]:02d}:{TRADE_WINDOW_START[1]:02d}–"
                f"{TRADE_WINDOW_END[0]:02d}:{TRADE_WINDOW_END[1]:02d} IST")

    @staticmethod
    def _fmt_blocked_window() -> str:
        """The BLOCKED side of the window (END -> START), e.g. 18:00–01:00 IST —
        what the logs name, since that is how the gate is described."""
        return (f"{TRADE_WINDOW_END[0]:02d}:{TRADE_WINDOW_END[1]:02d}–"
                f"{TRADE_WINDOW_START[0]:02d}:{TRADE_WINDOW_START[1]:02d} IST")

    # ─── Signal Loop ────────────────────────────────────────

    async def _signal_loop(self):
        warm_up_scans = 0          # skip entries for first 2 scans after restart
        _outside_announced = False # log the window open/close once, not every scan
        while self._running:
            try:
                # Signals keep being scored and broadcast outside the window —
                # only entries are gated, so the UI stays live all day.
                in_window = self._in_trade_window()
                if not in_window and not _outside_announced:
                    log.warning(f"🌙 Night gate ON ({self._fmt_blocked_window()}) — "
                                f"new entries paused; open positions unaffected")
                    _outside_announced = True
                elif in_window and _outside_announced:
                    log.info(f"☀️ Night gate OFF — entries resumed "
                             f"(trading window {self._fmt_window()})")
                    _outside_announced = False
                    self._gate_skip_logged.clear()

                await self._process_signals(
                    allow_entry=warm_up_scans >= 2 and in_window,
                    gate_blocked=warm_up_scans >= 2 and not in_window,
                )
                if warm_up_scans < 2:
                    warm_up_scans += 1
                    log.info(f"Warm-up scan {warm_up_scans}/2 — entries paused (stale signal guard)")
                if warm_up_scans == 2:
                    # After warm-up, push snapshot so UI gets all signals at once
                    await self._broadcast({"type": "snapshot", "data": self.snapshot()})
            except Exception as e:
                log.error(f"Signal loop error: {e}", exc_info=True)
            await asyncio.sleep(SIGNAL_BROADCAST_INTERVAL)

    async def _process_signals(self, allow_entry: bool = True, gate_blocked: bool = False):
        """gate_blocked=True means entries are paused ONLY by the night gate
        (warm-up already done) — a signal that would otherwise have been
        entered is logged as skipped instead."""
        if not self._pairs:
            return

        # Get BTC trend direction first — used as bias gate for all altcoins
        btc_direction = None
        if "BTC" in self._pairs:
            try:
                btc_result = self._signals.score("BTC", self._style)
                if btc_result.trend_regime == 1:
                    btc_direction = btc_result.trend_direction  # "long" or "short"
                # neutral/ranging → btc_direction stays None → gate skipped for altcoins
            except Exception as e:
                log.error(f"BTC pre-scan error: {e}", exc_info=True)

        entered_this_cycle = False   # max 1 new trade per scan cycle
        for pair in self._pairs:
            if not self._running:
                break
            try:
                bias = None if pair == "BTC" else btc_direction
                result = self._signals.score(pair, self._style, btc_direction=bias)

                # Upsert to Supabase only when score or direction changes — reduces DB writes
                prev = self._last_signals.get(pair, {})
                if (prev.get("total_score") != result.total_score or
                        prev.get("signal_direction") != result.signal_direction):
                    try:
                        db.upsert_signal(pair, result.to_dict())
                    except Exception as db_err:
                        log.debug(f"Signal upsert failed [{pair}]: {db_err}")

                self._last_signals[pair] = result.to_dict()

                # Broadcast to WebSocket clients — quality gate fields added separately (not in DB)
                await self._broadcast({
                    "type": "signal_update",
                    "data": {
                        "pair":         pair,
                        "price":        self._md.get_price(pair),
                        "trade_signal": result.trade_signal,
                        "btc_bias":     result.btc_bias,
                        **result.to_dict(),
                    }
                })

                # ── Check if trade should be entered ─────────────
                score        = result.total_score
                open_count   = self._engine.count_open_positions(pair)
                total_open   = self._engine.total_open_positions()

                can_enter = (
                    allow_entry
                    and result.trade_signal
                    and total_open < self._risk.max_trades()
                    and open_count == 0
                    and not entered_this_cycle   # max 1 trade per scan cycle
                )

                if gate_blocked and result.trade_signal and open_count == 0:
                    # Log once per pair per direction per 5m candle — the same
                    # signal stays true for the whole candle.
                    now_ist = datetime.now(self.IST)
                    key = (result.signal_direction, int(now_ist.timestamp()) // 300)
                    if self._gate_skip_logged.get(pair) != key:
                        self._gate_skip_logged[pair] = key
                        log.info(f"🌙 Night gate: {pair} {result.signal_direction.upper()} "
                                 f"signal (score {score}/7) skipped @ "
                                 f"{now_ist:%H:%M} IST price={self._md.get_price(pair)}")

                if allow_entry and result.ema9_blocked and open_count == 0:
                    # Signal passed every other check but the 1H EMA9 distance
                    # gate (signal_engine). Logged once per pair per direction
                    # per 5m candle; skipped during the night gate, which logs
                    # on its own.
                    now_ist = datetime.now(self.IST)
                    key = (result.signal_direction, int(now_ist.timestamp()) // 300)
                    if self._ema9_skip_logged.get(pair) != key:
                        self._ema9_skip_logged[pair] = key
                        min_dist = SCALPING.get("min_h1_ema9_dist_pct")
                        log.info(f"📏 EMA9 filter: {pair} {result.signal_direction.upper()} "
                                 f"signal (score {score}/7) skipped — 1H EMA9 distance "
                                 f"{result.h1_ema9_dist_pct:.2f}% (need > {min_dist}%) @ "
                                 f"{now_ist:%H:%M} IST price={self._md.get_price(pair)}")

                if can_enter:
                    # Weak-combo half-sizing removed 2026-07-10 per user request —
                    # every entry now uses the full capital_pct the bot was started
                    # with, regardless of whether L2/CVD-divergence fired.
                    eff_capital = self._capital_pct
                    log.info(f">>> TRADE SIGNAL: {pair} {result.signal_direction.upper()} "
                             f"score={score}/7 positions={open_count+1} price={self._md.get_price(pair)}")
                    task = asyncio.create_task(
                        self._engine.enter(pair, self._style, result, eff_capital, score)
                    )
                    task.add_done_callback(
                        lambda t: log.error(f"Enter task failed: {t.exception()}")
                        if not t.cancelled() and t.exception() else None
                    )
                    entered_this_cycle = True
            except Exception as e:
                log.error(f"Signal processing error [{pair}]: {e}", exc_info=True)

    # ─── Price Ticker ────────────────────────────────────────────

    async def _price_ticker_loop(self):
        """Broadcast live prices every 1s — separate from signal loop (which runs every 2s)."""
        while self._running:
            try:
                prices = {
                    pair: self._md.get_price(pair)
                    for pair in self._pairs
                    if self._md.get_price(pair) > 0
                }
                if prices:
                    await self._broadcast({"type": "price_update", "data": prices})
            except Exception as e:
                log.debug(f"Price ticker error: {e}")
            await asyncio.sleep(1)

    # ─── Wallet Broadcast ────────────────────────────────────

    async def _wallet_broadcast_loop(self):
        while self._running:
            try:
                wallet      = self._engine.wallet_snapshot() if self._engine else {}
                risk_status = self._engine.risk.status(self._mode, self._trader_name) if self._engine else {}
                await self._broadcast({
                    "type": "wallet_update",
                    "data": {**wallet, "risk_status": risk_status},
                })
            except Exception as e:
                log.debug(f"Wallet broadcast error: {e}")
            await asyncio.sleep(5)

    # ─── Broadcast ──────────────────────────────────────────

    async def _broadcast(self, message: Dict):
        if self._broadcast_cb:
            try:
                await self._broadcast_cb(message)
            except Exception as e:
                log.debug(f"Broadcast error: {e}")

    # ─── Status / Snapshot ──────────────────────────────────

    def snapshot(self) -> Dict:
        wallet    = self._engine.wallet_snapshot() if self._engine else {}
        positions = self._engine.positions_snapshot() if self._engine else []
        return {
            "running":      self._running,
            "mode":         self._mode,
            "style":        self._style,
            "pairs":        self._pairs,
            "capital_pct":  self._capital_pct,
            "reverse_direction": self._reverse_direction,
            "wallet":       wallet,
            "signals":      self._last_signals,
            "has_position": self._engine.has_open_position() if self._engine else False,
            "open_pairs":   list(self._engine._open.keys()) if self._engine else [],
            "positions":    positions,
        }

    async def _binance_reconcile_loop(self):
        """
        Live mode: every 5 min, detect orphaned Binance positions not tracked by the bot.
        Startup check is done separately in start() right after recover_open_positions(),
        so this loop sleeps first before its first periodic check.
        """
        while self._running:
            await asyncio.sleep(5 * 60)   # wait 5 min before first periodic check
            if not self._running:
                break
            try:
                if self._engine and self._engine.mode == "live":
                    log.info("Binance reconcile check...")
                    await self._engine._reconcile_binance_positions()
            except Exception as e:
                log.error(f"Binance reconcile loop error: {e}", exc_info=True)

    async def force_close_current(self):
        if not self._engine:
            return
        for pair in list(self._engine._open.keys()):
            price = self._md.get_price(pair)
            if price > 0:
                await self._engine.force_close(pair, price)

    async def force_close_pair(self, pair: str):
        if not self._engine:
            return
        price = self._md.get_price(pair)
        if price > 0:
            await self._engine.force_close(pair, price)
