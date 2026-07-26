import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

import aiohttp
import websockets

from config import BINANCE_REST_BASE, BINANCE_WS_BASE, PAIRS, SCALPING, SWING, style_cfg

log = logging.getLogger("market_data")

# Candle structure: [open, high, low, close, volume, timestamp]
Candle = Dict[str, float]


class MarketDataManager:
    def __init__(self):
        # candles[pair][timeframe] = deque of Candle dicts (max 200)
        self.candles: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=200))
        )
        # orderbook[pair] = {"bids": [(price, qty)...], "asks": [(price, qty)...]}
        self.orderbook: Dict[str, Dict] = defaultdict(lambda: {"bids": [], "asks": []})
        # dom_history[pair] = last 5 orderbook snapshots for spoof-resistant averaging
        self.dom_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5))
        # cvd[pair] = float (cumulative volume delta)
        self.cvd: Dict[str, float] = defaultdict(float)
        # cvd_history[pair] = per-aggTrade CVD (kept for raw display only)
        self.cvd_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        # cvd_at_close[pair][tf] = CVD snapshotted at each candle close for that TF
        # Candle-synced so divergence math compares same time windows as price.
        self.cvd_at_close: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=150))
        )
        # price_history[pair] = close prices (kept for legacy; prefer candle closes)
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        # current price per pair
        self.last_price: Dict[str, float] = {}

        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        self._selected_pairs: List[str] = []
        self._style: str = "scalping"

    # ─── Public API ─────────────────────────────────────────

    def get_candles(self, pair: str, tf: str, closed_only: bool = False) -> List[Candle]:
        # The last candle in the buffer is the still-forming (live) candle — it
        # updates in-place on every tick until it closes. Computing EMA/ADX/RSI on
        # it causes "repaint": a partial candle can briefly look bullish, fire an
        # entry, then flip neutral when it closes. closed_only=True drops that last
        # candle so indicators use only completed candles.
        buf = list(self.candles[pair][tf])
        if closed_only and len(buf) > 1:
            return buf[:-1]
        return buf

    def get_orderbook(self, pair: str) -> Dict:
        return self.orderbook[pair]

    def get_dom_history(self, pair: str) -> List[Dict]:
        return list(self.dom_history[pair])

    def get_cvd(self, pair: str) -> float:
        return self.cvd[pair]

    def get_cvd_history(self, pair: str) -> List[float]:
        return list(self.cvd_history[pair])

    def get_cvd_at_close(self, pair: str, tf: str) -> List[float]:
        return list(self.cvd_at_close[pair][tf])

    def get_price_history(self, pair: str) -> List[float]:
        return list(self.price_history[pair])

    def get_price(self, pair: str) -> float:
        return self.last_price.get(pair, 0.0)

    def is_ready(self, pair: str, style: str) -> bool:
        cfg = style_cfg(style)
        confirm_tfs = cfg.get("confirm_tfs", [cfg["trend_tf"], cfg["entry_tf"]])
        return all(len(self.candles[pair][tf]) >= 50 for tf in confirm_tfs)

    # ─── Lifecycle ──────────────────────────────────────────

    async def start(self, pairs: List[str], style: str):
        self._selected_pairs = pairs
        self._style          = style
        self._running        = True
        log.info(f"MarketData starting for {pairs} in {style} mode")
        await self._fetch_historical(pairs, style)
        self._ws_task = asyncio.create_task(self._ws_loop(pairs, style))

    async def stop(self):
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

    # ─── Historical Fetch ────────────────────────────────────

    async def _fetch_historical(self, pairs: List[str], style: str):
        cfg = style_cfg(style)
        confirm_tfs = cfg.get("confirm_tfs", [cfg["trend_tf"], cfg["entry_tf"]])
        bias_tf     = cfg.get("bias_tf")
        tfs = list(dict.fromkeys(confirm_tfs + ([bias_tf] if bias_tf else [])))  # deduplicate, preserve order

        sem = asyncio.Semaphore(3)  # max 3 parallel API calls — safe under Binance rate limit

        async def fetch_with_sem(session, pair, symbol, tf):
            async with sem:
                await self._fetch_klines(session, pair, symbol, tf)
                await asyncio.sleep(0.05)  # small delay per slot

        async with aiohttp.ClientSession() as session:
            tasks = [
                fetch_with_sem(session, pair, PAIRS[pair], tf)
                for pair in pairs
                for tf in tfs
            ]
            await asyncio.gather(*tasks)
            log.info(f"Historical fetch complete — {len(tasks)} streams fetched in parallel")

    async def _fetch_klines(self, session: aiohttp.ClientSession,
                             pair: str, symbol: str, tf: str):
        url = f"{BINANCE_REST_BASE}/klines"
        params = {"symbol": symbol, "interval": tf, "limit": 150}
        try:
            async with session.get(url, params=params) as r:
                if r.status == 200:
                    data = await r.json()
                    for row in data:
                        candle = {
                            "ts":     int(row[0]),
                            "open":   float(row[1]),
                            "high":   float(row[2]),
                            "low":    float(row[3]),
                            "close":  float(row[4]),
                            "volume": float(row[5]),
                        }
                        self.candles[pair][tf].append(candle)
                    log.info(f"Fetched {len(data)} {tf} candles for {pair}")
        except Exception as e:
            log.error(f"Failed to fetch {tf} klines for {pair}: {e}")

    # ─── WebSocket Loop ─────────────────────────────────────

    async def _ws_loop(self, pairs: List[str], style: str):
        cfg = style_cfg(style)
        confirm_tfs = cfg.get("confirm_tfs", [cfg["trend_tf"], cfg["entry_tf"]])
        bias_tf     = cfg.get("bias_tf")
        tfs = list(dict.fromkeys(confirm_tfs + ([bias_tf] if bias_tf else [])))  # deduplicate, preserve order
        streams = []
        for pair in pairs:
            sym = PAIRS[pair].lower()
            for tf in tfs:
                streams.append(f"{sym}@kline_{tf}")
            streams.append(f"{sym}@depth20@500ms")
            streams.append(f"{sym}@aggTrade")

        url = f"{BINANCE_WS_BASE}?streams=" + "/".join(streams)
        log.info(f"Connecting to Binance WS: {len(streams)} streams")

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    log.info("Binance WebSocket connected")
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                            await self._handle_message(msg, pairs)
                        except Exception as e:
                            log.debug(f"Message parse error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"WS disconnected: {e} — reconnecting in 3s")
                if self._running:
                    await asyncio.sleep(3)

    async def _handle_message(self, msg: dict, pairs: List[str]):
        stream = msg.get("stream", "")
        data   = msg.get("data", {})

        # Identify pair from stream name — must match the symbol prefix exactly
        # (stream format is "{symbol}@{type}"). A substring check here is unsafe:
        # e.g. "iousdt" (IO) is a substring of "biousdt" (BIO), which silently
        # misattributed every BIO price/kline update to IO.
        pair = None
        for p in pairs:
            if stream.startswith(PAIRS[p].lower() + "@"):
                pair = p
                break
        if pair is None:
            return

        if "@kline_" in stream:
            await self._handle_kline(pair, data, stream)
        elif "@depth" in stream:
            self._handle_depth(pair, data)
        elif "@aggTrade" in stream:
            self._handle_agg_trade(pair, data)

    async def _handle_kline(self, pair: str, data: dict, stream: str):
        k  = data.get("k", {})
        tf = k.get("i", "")
        if not tf:
            # infer from stream
            for part in stream.split("@"):
                if "kline_" in part:
                    tf = part.replace("kline_", "")
        candle = {
            "ts":     int(k["t"]),
            "open":   float(k["o"]),
            "high":   float(k["h"]),
            "low":    float(k["l"]),
            "close":  float(k["c"]),
            "volume": float(k["v"]),
        }
        is_closed = k.get("x", False)

        buf = self.candles[pair][tf]
        if buf and buf[-1]["ts"] == candle["ts"]:
            buf[-1] = candle          # update live candle in-place
        else:
            buf.append(candle)        # new candle — always add (live or closed)

        # Always update current price
        self.last_price[pair] = candle["close"]

        if is_closed:
            self.price_history[pair].append(candle["close"])
            # Snapshot CVD at this candle's close — keeps CVD and price time-aligned
            # so divergence detection compares the same time windows.
            self.cvd_at_close[pair][tf].append(self.cvd[pair])

    def _handle_depth(self, pair: str, data: dict):
        bids = [(float(p), float(q)) for p, q in data.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in data.get("asks", [])]
        snapshot = {"bids": bids, "asks": asks}
        self.orderbook[pair] = snapshot
        self.dom_history[pair].append(snapshot)

    def _handle_agg_trade(self, pair: str, data: dict):
        qty     = float(data.get("q", 0))
        price   = float(data.get("p", 0))
        is_sell = data.get("m", False)  # True = maker is buyer = sell side
        if is_sell:
            self.cvd[pair] -= qty
        else:
            self.cvd[pair] += qty
        self.cvd_history[pair].append(self.cvd[pair])
        # Update price from every trade — much more real-time than kline
        if price > 0:
            self.last_price[pair] = price
