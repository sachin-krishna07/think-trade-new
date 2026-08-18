from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))  # Indian Standard Time

def _ist_today_utc_start() -> str:
    """Return UTC ISO string of IST midnight (start of today in IST)."""
    now_ist    = datetime.now(IST)
    ist_midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return ist_midnight.astimezone(timezone.utc).isoformat()

def _ist_date() -> str:
    """Return today's date string in IST (YYYY-MM-DD)."""
    return datetime.now(IST).date().isoformat()
from typing import Optional, Dict, Any
import logging

log = logging.getLogger("supabase_client")

_client: Optional[Client] = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def _db_call(fn, *args, retries: int = 3, **kwargs):
    """Execute a DB call with auto-reconnect on disconnect errors.
    Retries up to `retries` times, recreating the client on ServerDisconnected.
    """
    global _client
    last_err = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if any(x in err_str for x in ("server disconnected", "connection", "timeout", "reset")):
                log.warning(f"Supabase connection error (attempt {attempt+1}/{retries}): {e} — reconnecting...")
                _client = None  # force new client on next get_client() call
                import time; time.sleep(0.5 * (attempt + 1))
            else:
                raise  # non-connection error — don't retry
    raise last_err


# ─── Bot Config ─────────────────────────────────────────────

def get_bot_config() -> Dict:
    row = get_client().table("bot_config").select("*").limit(1).execute()
    return row.data[0] if row.data else {}

def update_bot_config(**kwargs) -> None:
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    get_client().table("bot_config").update(kwargs).neq("id", "00000000-0000-0000-0000-000000000000").execute()


# ─── Wallet ─────────────────────────────────────────────────

def get_wallet(mode: str) -> Dict:
    row = get_client().table("wallet").select("*").eq("mode", mode).limit(1).execute()
    return row.data[0] if row.data else {}

def update_wallet(mode: str, balance: float, total_pnl: float, initial: float,
                  daily_pnl: float) -> None:
    total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0
    daily_pnl_pct = (daily_pnl / initial * 100) if initial > 0 else 0
    get_client().table("wallet").update({
        "balance":       balance,
        "total_pnl":     total_pnl,
        "total_pnl_pct": round(total_pnl_pct, 4),
        "daily_pnl":     daily_pnl,
        "daily_pnl_pct": round(daily_pnl_pct, 4),
        "updated_at":    datetime.now(timezone.utc).isoformat(),
    }).eq("mode", mode).execute()

def reset_daily_pnl(mode: str) -> None:
    get_client().table("wallet").update({
        "daily_pnl":     0,
        "daily_pnl_pct": 0,
        "updated_at":    datetime.now(timezone.utc).isoformat(),
    }).eq("mode", mode).execute()


# ─── Trades ─────────────────────────────────────────────────

def open_trade(trade_data: Dict) -> str:
    # is_shadow is deliberately NOT optional. If the column is missing it must not
    # be stripped like the others — a stripped flag would file a shadow trade as a
    # real one and let its PnL through into the wallet, which is the exact outcome
    # the flag exists to prevent. Fail loudly instead.
    _OPTIONAL_COLS = {"signal_score"}
    data = trade_data
    for attempt in range(len(_OPTIONAL_COLS) + 1):
        try:
            result = _db_call(lambda d: get_client().table("trades").insert(d).execute(), data)
            return result.data[0]["id"] if result.data else None
        except Exception as e:
            if "is_shadow" in str(e):
                log.error(
                    "trades.is_shadow column is missing — run "
                    "supabase_migration_shadow.sql in the Supabase SQL Editor before "
                    "starting the bot. Refusing to insert without it."
                )
                raise
            missing = next((c for c in _OPTIONAL_COLS if c in str(e) and c in data), None)
            if missing:
                data = {k: v for k, v in data.items() if k != missing}
            else:
                raise

def close_trade(trade_id: str, exit_price: float, pnl: float, pnl_pct: float,
                r_multiple: float, exit_reason: str, duration_sec: int,
                fee: float = 0, net_pnl: float = 0) -> None:
    get_client().table("trades").update({
        "exit_price":       exit_price,
        "pnl":              pnl,
        "pnl_pct":          pnl_pct,
        "r_multiple":       r_multiple,
        "status":           "closed",
        "exit_reason":      exit_reason,
        "exit_time":        datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration_sec,
        "fee":              round(fee, 4),
        "net_pnl":          round(net_pnl, 4),
    }).eq("id", trade_id).execute()

def mark_order_failed(trade_id: str) -> None:
    """Mark a trade as failed — order never executed on exchange.
    Uses status='failed' so it is never shown in trade history (which filters status='closed')."""
    get_client().table("trades").update({
        "status":      "failed",
        "exit_reason": "order_failed",
        "exit_time":   datetime.now(timezone.utc).isoformat(),
    }).eq("id", trade_id).execute()

def get_trades(mode: str, limit: int = 50) -> list:
    result = get_client().table("trades")\
        .select("*")\
        .eq("mode", mode)\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
    return result.data or []

def get_closed_for_adaptive(mode: str, trader_name: str = "", limit: int = 600) -> list:
    """Closed trades (oldest first) for warm-starting the adaptive per-pair filter.

    Returns pair / net_pnl / risk_amount so the caller can compute net R. Scoped
    to trader_name when given — the trades table is shared by more than one bot
    instance, and mixing them would poison the per-pair stats.
    """
    q = get_client().table("trades")\
        .select("pair,net_pnl,risk_amount,exit_time")\
        .eq("mode", mode)\
        .eq("status", "closed")\
        .eq("is_shadow", False)
    if trader_name:
        q = q.eq("trader_name", trader_name)
    result = q.order("exit_time", desc=True).limit(limit).execute()
    rows = result.data or []
    rows.reverse()          # oldest first, so the rolling window ends up correct
    return rows

def count_consecutive_losses(mode: str) -> int:
    result = get_client().table("trades")\
        .select("pnl")\
        .eq("mode", mode)\
        .eq("status", "closed")\
        .eq("is_shadow", False)\
        .order("exit_time", desc=True)\
        .limit(10)\
        .execute()
    count = 0
    for row in (result.data or []):
        if row["pnl"] is not None and row["pnl"] < 0:
            count += 1
        else:
            break
    return count

def count_losses_in_window(mode: str, window: int = 5) -> int:
    """Count total losses (not necessarily consecutive) in last `window` closed trades."""
    result = get_client().table("trades")\
        .select("pnl")\
        .eq("mode", mode)\
        .eq("status", "closed")\
        .eq("is_shadow", False)\
        .order("exit_time", desc=True)\
        .limit(window)\
        .execute()
    return sum(1 for r in (result.data or []) if r["pnl"] is not None and r["pnl"] < 0)

def get_total_pnl(mode: str) -> float:
    result = get_client().table("trades")\
        .select("net_pnl")\
        .eq("mode", mode)\
        .eq("status", "closed")\
        .eq("is_shadow", False)\
        .execute()
    return sum(r["net_pnl"] for r in (result.data or []) if r["net_pnl"] is not None)

def get_today_pnl(mode: str) -> float:
    ist_start = _ist_today_utc_start()  # IST midnight in UTC
    result = get_client().table("trades")\
        .select("pnl")\
        .eq("mode", mode)\
        .eq("status", "closed")\
        .eq("is_shadow", False)\
        .gte("exit_time", ist_start)\
        .execute()
    return sum(r["pnl"] for r in (result.data or []) if r["pnl"] is not None)

def count_today_losses(mode: str, trader_name: str) -> int:
    """Count this trader's losing trades (pnl < 0, any amount) closed since IST
    midnight today. Scoped to trader_name — the trades table is shared by more
    than one bot instance, so an unscoped count would block the wrong trader.
    Shadow trades are excluded (is_shadow=False) — they never touch the wallet
    and must not gate real entries. Backs the daily per-trader loss lockout in
    RiskManager.check() — see MAX_DAILY_LOSSES_PER_TRADER in config.py.
    """
    ist_start = _ist_today_utc_start()
    result = get_client().table("trades")\
        .select("pnl")\
        .eq("mode", mode)\
        .eq("trader_name", trader_name)\
        .eq("status", "closed")\
        .eq("is_shadow", False)\
        .gte("exit_time", ist_start)\
        .execute()
    return sum(1 for r in (result.data or []) if r["pnl"] is not None and r["pnl"] < 0)


# ─── Position ────────────────────────────────────────────────

def open_position(pos_data: Dict) -> str:
    result = get_client().table("positions").insert(pos_data).execute()
    return result.data[0]["id"] if result.data else None

def update_position(pos_id: str, current_price: float, unrealized_pnl: float,
                    unrealized_pnl_pct: float, highest_pnl: float,
                    trailing_sl: Optional[float] = None,
                    breakeven_hit: bool = False,
                    lock_profit_hit: bool = False,
                    sl_price: Optional[float] = None) -> None:
    payload: Dict[str, Any] = {
        "current_price":      current_price,
        "unrealized_pnl":     unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "highest_pnl":        highest_pnl,
        "breakeven_hit":      breakeven_hit,
        "lock_profit_hit":    lock_profit_hit,
        "updated_at":         datetime.now(timezone.utc).isoformat(),
    }
    if trailing_sl is not None:
        payload["trailing_sl"] = trailing_sl
    if sl_price is not None:
        payload["sl_price"] = sl_price
    get_client().table("positions").update(payload).eq("id", pos_id).execute()

def close_position(pos_id: str) -> None:
    get_client().table("positions").update({
        "status":     "closed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", pos_id).execute()

def get_active_position() -> Optional[Dict]:
    result = get_client().table("positions")\
        .select("*")\
        .eq("status", "active")\
        .limit(1)\
        .execute()
    return result.data[0] if result.data else None


def get_all_active_positions(mode: str) -> list:
    """Get all active positions with their trade data — used for recovery on bot restart."""
    try:
        pos_result = get_client().table("positions")\
            .select("*")\
            .eq("status", "active")\
            .execute()
        positions = pos_result.data or []
        enriched = []
        for pos in positions:
            trade_result = get_client().table("trades")\
                .select("*")\
                .eq("id", pos["trade_id"])\
                .eq("mode", mode)\
                .eq("status", "open")\
                .execute()
            if not trade_result.data:
                continue
            trade = trade_result.data[0]
            enriched.append({
                "position_id":       pos["id"],
                "trade_id":          trade["id"],
                "pair":              trade["pair"],
                "direction":         trade["direction"],
                "style":             trade.get("style", "scalping"),
                "entry_price":       trade["entry_price"],
                "sl_price":          pos.get("sl_price") or trade["sl_price"],
                "tp_price":          pos.get("tp_price") or trade["tp_price"],
                "position_size_usd": trade["position_size_usd"],
                "risk_amount":       trade["risk_amount"],
                "quantity":          trade["quantity"],
                "fee":               trade.get("fee", 0),
                # Must survive the restart — without it a recovered shadow trade
                # would close as a real one and land in the wallet.
                "is_shadow":         trade.get("is_shadow", False),
            })
        return enriched
    except Exception as e:
        import logging
        logging.getLogger("supabase_client").error(f"get_all_active_positions failed: {e}")
        return []


# ─── Signals ─────────────────────────────────────────────────

def upsert_signal(pair: str, data: Dict) -> None:
    MAX_VAL = 9_999_999_999.9999
    cleaned: Dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, float):
            if v != v or abs(v) == float("inf"):
                cleaned[k] = None
            else:
                cleaned[k] = max(-MAX_VAL, min(MAX_VAL, round(v, 4)))
        else:
            cleaned[k] = v
    cleaned["pair"]       = pair
    cleaned["updated_at"] = datetime.now(timezone.utc).isoformat()
    get_client().table("signals").upsert(cleaned, on_conflict="pair").execute()


# ─── Bot Logs ────────────────────────────────────────────────

def save_log(entry: dict) -> None:
    """Insert a single log entry into bot_logs table. Silently ignores errors."""
    try:
        get_client().table("bot_logs").insert({
            "ts":    entry["ts"],
            "level": entry["level"],
            "name":  entry["name"],
            "msg":   entry["msg"],
        }).execute()
    except Exception:
        pass  # Never raise from here — would cause infinite logging loop

def get_logs_from_db(limit: int = 300, level: str = "", name: str = "") -> list:
    q = get_client().table("bot_logs").select("ts,level,name,msg")
    if level:
        q = q.eq("level", level.upper())
    if name:
        q = q.eq("name", name)
    result = q.order("ts", desc=True).limit(limit).execute()
    return list(reversed(result.data or []))


# ─── Performance ─────────────────────────────────────────────

def upsert_performance(mode: str) -> None:
    today     = _ist_date()           # IST date string for the record key
    ist_start = _ist_today_utc_start() # IST midnight in UTC for filtering
    trades_result = get_client().table("trades")\
        .select("pnl, r_multiple")\
        .eq("mode", mode)\
        .eq("status", "closed")\
        .eq("is_shadow", False)\
        .gte("exit_time", ist_start)\
        .execute()
    rows = trades_result.data or []
    total   = len(rows)
    won     = sum(1 for r in rows if r["pnl"] and r["pnl"] > 0)
    lost    = total - won
    pnl_sum = sum(r["pnl"] for r in rows if r["pnl"] is not None)
    rmults  = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
    avg_r   = sum(rmults) / len(rmults) if rmults else 0
    pnls    = [r["pnl"] for r in rows if r["pnl"] is not None]
    best    = max(pnls) if pnls else 0
    worst   = min(pnls) if pnls else 0
    get_client().table("performance").upsert({
        "date":         today,
        "mode":         mode,
        "trades_total": total,
        "trades_won":   won,
        "trades_lost":  lost,
        "win_rate":     round(won / total * 100, 2) if total > 0 else 0,
        "total_pnl":    pnl_sum,
        "avg_r":        round(avg_r, 4),
        "best_trade":   best,
        "worst_trade":  worst,
    }, on_conflict="date,mode").execute()
