import asyncio
import json
import logging
from collections import deque
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import PAIRS
from core.bot_controller import BotController
import core.supabase_client as db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
log = logging.getLogger("main")

# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

# ─── In-memory log buffer ───────────────────────────────────
# Captures logs from bot components and streams them to the Logs UI page.

_log_buffer: deque = deque(maxlen=500)

# Only capture trade-relevant loggers — market_data & signal_engine are too noisy
_CAPTURE_LOGGERS = {"trade_engine", "bot_controller", "risk_manager"}
_DB_SAVE_LOGGERS = {"trade_engine", "bot_controller", "risk_manager"}


class _BotLogHandler(logging.Handler):
    """Stores log records in buffer, broadcasts via WebSocket, and persists to Supabase."""

    def emit(self, record: logging.LogRecord):
        if record.name not in _CAPTURE_LOGGERS:
            return
        entry = {
            "ts":    record.created,
            "level": record.levelname,
            "name":  record.name,
            "msg":   record.getMessage(),
        }
        _log_buffer.append(entry)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Broadcast to WebSocket clients (all captured loggers)
                loop.create_task(_broadcast_log(entry))
                # Persist to Supabase (trade-relevant loggers, INFO and above only)
                if record.name in _DB_SAVE_LOGGERS and record.levelno >= logging.INFO:
                    loop.create_task(_save_log(entry))
        except Exception:
            pass


async def _broadcast_log(entry: dict):
    await broadcast({"type": "log_entry", "data": entry})


async def _save_log(entry: dict):
    try:
        await asyncio.to_thread(db.save_log, entry)
    except Exception:
        pass


# Attach handler to root logger so all child loggers are captured
_log_handler = _BotLogHandler()
_log_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_log_handler)

app = FastAPI(title="ThinkTrade Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Globals ────────────────────────────────────────────────
bot = BotController()


# ─── Per-client queue connection ────────────────────────────

class ClientConn:
    """Wraps a WebSocket with a dedicated sender task.
    All sends go through an asyncio.Queue, so concurrent broadcasts
    from multiple loops never collide on the same socket."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=300)

    def enqueue(self, payload: str) -> None:
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # slow client — drop oldest would be better, but drop new is safe

    async def run(self) -> None:
        """Drain queue until cancelled or a send fails."""
        while True:
            try:
                payload = await self._queue.get()
                await self.ws.send_text(payload)
            except asyncio.CancelledError:
                return
            except Exception:
                return


clients: set[ClientConn] = set()


# ─── WebSocket broadcast ────────────────────────────────────

def _safe_json(obj):
    """Recursively replace NaN/Inf floats with None so json.dumps never crashes."""
    if isinstance(obj, float):
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    return obj

async def broadcast(message: dict):
    try:
        payload = json.dumps(_safe_json(message))
    except Exception as e:
        log.error(f"broadcast: serialization failed (type={message.get('type')}): {e}")
        return
    for conn in list(clients):
        conn.enqueue(payload)


# ─── WebSocket endpoint ─────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    conn = ClientConn(websocket)
    clients.add(conn)
    log.info(f"Client connected ({len(clients)} total)")

    sender = asyncio.create_task(conn.run())
    try:
        snap = bot.snapshot()
        conn.enqueue(json.dumps(_safe_json({"type": "snapshot", "data": snap})))

        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=60)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(conn)
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass
        log.info(f"Client disconnected ({len(clients)} total)")


# ─── REST Models ────────────────────────────────────────────

class StartConfig(BaseModel):
    mode:        str   = "demo"
    style:       str   = "scalping"
    pairs:       list  = ["BTC", "ETH", "SOL", "BNB", "XRP"]
    capital_pct: float = 1.0
    leverage:    float = 5.0
    trader_name: str   = "Unknown"
    reverse_direction: bool = False


# ─── REST Endpoints ─────────────────────────────────────────

@app.post("/api/bot/start")
async def start_bot(config: StartConfig):
    if bot.is_running():
        return {"ok": False, "msg": "Bot already running"}
    # Drop pairs no longer in config (e.g. blocklisted coins still cached
    # in the frontend's localStorage) — unknown pairs crash market_data.
    valid_pairs = [p for p in config.pairs if p in PAIRS]
    if not valid_pairs:
        return {"ok": False, "msg": "No valid pairs selected"}
    asyncio.create_task(
        bot.start(
            mode=config.mode,
            style=config.style,
            pairs=valid_pairs,
            capital_pct=config.capital_pct,
            broadcast_cb=broadcast,
            leverage=config.leverage,
            trader_name=config.trader_name,
            reverse_direction=config.reverse_direction,
        )
    )
    return {"ok": True, "msg": "Bot starting..."}


@app.post("/api/bot/stop")
async def stop_bot():
    if not bot.is_running():
        return {"ok": False, "msg": "Bot not running"}
    await bot.stop()
    return {"ok": True, "msg": "Bot stopped"}


@app.post("/api/bot/force-close")
async def force_close():
    await bot.force_close_current()
    return {"ok": True, "msg": "All positions force closed"}

@app.post("/api/bot/force-close/{pair}")
async def force_close_pair(pair: str):
    await bot.force_close_pair(pair)
    return {"ok": True, "msg": f"{pair} force closed"}


@app.get("/api/bot/status")
async def get_status():
    return bot.snapshot()


@app.get("/api/adaptive")
async def get_adaptive():
    """Per-pair adaptive filter state — which pairs it has learned to skip."""
    engine = getattr(bot, "_engine", None)
    if engine is None or not hasattr(engine, "adaptive_snapshot"):
        return {"enabled": False, "pairs": {}, "blocked": []}
    return engine.adaptive_snapshot()


@app.get("/api/trades")
async def get_trades(mode: str = "demo", limit: int = 50):
    return {"trades": db.get_trades(mode, limit)}


@app.get("/api/wallet")
async def get_wallet(mode: str = "demo"):
    wallet = db.get_wallet(mode)
    if mode == "live":
        try:
            from core.trade_engine import BinanceFutures
            from config import BINANCE_API_KEY, BINANCE_SECRET_KEY
            if BINANCE_API_KEY and BINANCE_SECRET_KEY:
                bn = BinanceFutures(BINANCE_API_KEY, BINANCE_SECRET_KEY)
                bal = await bn.get_account_balance()
                wallet["balance"] = bal["total_usdt"]
                wallet["initial_balance"] = bal["total_usdt"]
                wallet["futures_usdt"] = bal["futures_usdt"]
                wallet["spot_usdt"] = bal["spot_usdt"]
                wallet["binance_live"] = True
        except Exception as e:
            wallet["binance_error"] = str(e)
    return wallet


@app.get("/api/performance")
async def get_performance(mode: str = "demo"):
    result = db.get_client().table("performance")\
        .select("*").eq("mode", mode)\
        .order("date", desc=True).limit(30).execute()
    return {"performance": result.data or []}


@app.get("/api/logs")
async def get_logs(limit: int = 300, level: str = "", name: str = "", source: str = "db"):
    if source == "memory":
        # Return in-memory buffer (includes signal_engine/market_data live logs)
        logs = list(_log_buffer)
        if level:
            logs = [l for l in logs if l["level"] == level.upper()]
        if name:
            logs = [l for l in logs if l["name"] == name]
        return {"logs": logs[-limit:], "source": "memory"}
    else:
        # Return from Supabase (persisted, survives restarts)
        logs = await asyncio.to_thread(db.get_logs_from_db, limit, level, name)
        return {"logs": logs, "source": "db"}


@app.get("/health")
async def health():
    return {"status": "ok", "bot_running": bot.is_running()}


# ─── Startup ────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    log.info("ThinkTrade Bot API started — http://localhost:8000")
    cfg = db.get_bot_config()
    if cfg.get("is_running"):
        db.update_bot_config(is_running=False)
    # Clean up any positions/trades left open from a crashed session
    try:
        db.get_client().table("positions").update({
            "status": "closed", "updated_at": "now()"
        }).eq("status", "active").execute()
        db.get_client().table("trades").update({
            "status": "closed", "exit_reason": "crash_recovery",
            "exit_time": "now()"
        }).eq("status", "open").execute()
        log.info("Startup cleanup done")
    except Exception as e:
        log.warning(f"Startup cleanup failed: {e}")
