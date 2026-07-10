import logging
from typing import Dict, Tuple

from config import (
    MAX_DAILY_LOSS_PCT, MAX_WEEKLY_DRAWDOWN_PCT,
    MAX_TRADES_NORMAL,
    MAX_LEVERAGE, DEFAULT_LEVERAGE,
)
import core.supabase_client as db

log = logging.getLogger("risk_manager")

# Trade modes — loss-triggered cooldown removed, bot always trades at full capacity.
MODE_NORMAL = "normal"


class RiskManager:
    def __init__(self):
        self._trade_mode: str = MODE_NORMAL

    def reset(self):
        """Fresh start on bot restart."""
        self._trade_mode = MODE_NORMAL
        log.info("Risk manager reset — fresh start")

    def record_trade_result(self, pnl: float, mode: str):
        """Called after every trade closes. Loss-window cooldown removed — no mode
        changes happen here anymore, this is purely informational logging."""
        if pnl >= 0:
            log.info(f"✅ Trade closed in profit (pnl={pnl:.2f})")
        else:
            log.info(f"❌ Trade closed in loss (pnl={pnl:.2f})")

    def check(self, mode: str, wallet: Dict) -> Tuple[bool, str]:
        """Returns (allowed, reason). Called before every trade entry."""
        # ── 3. Daily loss limit ──────────────────────────────────
        balance  = wallet.get("balance", 0)
        initial  = wallet.get("initial_balance", balance)
        daily_pnl = db.get_today_pnl(mode)
        daily_loss_pct = abs(daily_pnl) / initial * 100 if initial > 0 and daily_pnl < 0 else 0

        if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
            return False, f"Daily loss limit hit: {daily_loss_pct:.2f}% (max {MAX_DAILY_LOSS_PCT}%)"

        # ── 4. Weekly drawdown check ─────────────────────────────
        total_pnl    = wallet.get("total_pnl", 0)
        weekly_dd_pct = abs(total_pnl) / initial * 100 if initial > 0 and total_pnl < 0 else 0
        if weekly_dd_pct >= MAX_WEEKLY_DRAWDOWN_PCT:
            return False, f"Weekly drawdown limit: {weekly_dd_pct:.2f}% (max {MAX_WEEKLY_DRAWDOWN_PCT}%)"

        return True, "ok"

    def max_trades(self) -> int:
        """How many simultaneous trades are allowed. Loss-window cooldown removed —
        always full capacity."""
        return MAX_TRADES_NORMAL

    def status(self) -> Dict:
        """Snapshot for logging/broadcast. Cooldown fields kept (always empty) so
        the frontend risk-status shape stays unchanged."""
        return {
            "trade_mode":             self._trade_mode,
            "max_trades":             self.max_trades(),
            "cooldown_level":         0,
            "cooldown_remaining_sec": None,
            "cooldown_total_min":     None,
            "consecutive_wins":       0,
        }

    def calculate_position(self, balance: float, capital_pct: float,
                           entry_price: float, atr_val: float,
                           sl_mult: float, user_leverage: float = DEFAULT_LEVERAGE) -> Dict:
        leverage          = min(user_leverage, MAX_LEVERAGE)
        position_size_usd = balance * (capital_pct / 100) * leverage
        quantity          = position_size_usd / entry_price if entry_price > 0 else 0

        sl_distance     = atr_val * sl_mult
        sl_distance_pct = sl_distance / entry_price if entry_price > 0 else 0.005
        risk_amount     = position_size_usd * sl_distance_pct

        log.info(f"Position: {capital_pct}% × {leverage}x = ${position_size_usd:.2f} | SL risk ~${risk_amount:.2f}")

        return {
            "risk_amount":       round(risk_amount, 4),
            "position_size_usd": round(position_size_usd, 4),
            "quantity":          round(quantity, 6),
            "leverage":          round(leverage, 2),
            "sl_distance":       round(sl_distance, 6),
            "sl_distance_pct":   round(sl_distance_pct, 6),
        }
