# ThinkTrade Version-2.0 — Logic Changelog

Har logic change yahan date ke saath likhna — taaki baad me analysis karte waqt
pata rahe ki kaunsi trades kis logic ki hain.

> Supabase me is bot ki trades: `trader_name = 'Version-2.0'`, `mode = 'demo'`.
> Sab time **IST** me hain. GitHub repo: `think-trade-new`.

---

## 11 Sep 2026 — Aaj ke updates

**Commit:** `____________` ← commit hash yahan likhna
**VPS deploy date-time (IST):** `____________` ← deploy karte hi likhna (naye logic ka analysis yahin se shuru)

### Summary
| # | Change | Pehle | Ab | File |
|---|---|---|---|---|
| 1 | Daily loss lockout | ON — 3 loss ke baad us din nayi entry band | **Hata diya** | `backend/core/risk_manager.py`, `backend/config.py` (note) |
| 2 | 1H RSI extreme block | ON — 1H RSI ≥ 75 par long signal nahi, ≤ 25 par short signal nahi | **Band** (RSI sirf display hota hai) | `backend/core/signal_engine.py` |
| 3 | Fee gate | risk ≥ 5× fee (SL ≥ ~0.5% price) | **risk ≥ 4× fee** (SL ≥ ~0.4% price) | `backend/core/trade_engine.py` |
| 4 | Shadow trade limit | 1R SL > 2.5% → shadow | **1R SL > 3.0% → shadow** | `backend/config.py` (`MAX_SL_PCT`) |
| 5 | Night gate | Nahi tha — 24 ghante entry | **6:00 PM – 1:00 AM IST nayi entry band** | `backend/config.py`, `backend/core/bot_controller.py` |
| 6 | 1H EMA9 distance filter | Nahi tha | **Price 1H EMA9 se signal direction me > 2% door ho tabhi trade** | `backend/config.py`, `backend/core/signal_engine.py`, `backend/core/bot_controller.py` |

### Detail

**1. Daily loss lockout hataya**
- `RiskManager.check()` ab `count_today_losses()` nahi padhta; `status()` se `daily_losses` /
  `daily_loss_block_active` fields bhi hat gaye (frontend inhe use nahi karta tha).
- `MAX_DAILY_LOSSES_PER_TRADER = 3` config me rakha hai sirf purane references ke liye — koi use nahi karta.
- Wajah: `bot_logs` me 22 Aug – 11 Sep lagbhag har din
  `Trade blocked — Daily loss limit hit for Version-2.0: 3 losing trades today` aa raha tha.
- Daily loss % aur weekly drawdown checks waise hi hain (dono 100%, yaani effectively off).

**2. 1H RSI extreme block band**
- 1H RSI value aur state (`overbought`/`oversold`/`neutral`) abhi bhi calculate hoke UI/`signals_at_entry` me jaati hai.
- Signal cancel nahi hota. `h1_rsi_blocked` hamesha `False`.
- 1H trend bias gate (1h ADX ≥ 20 aur 1h trend ulta → no signal) **abhi bhi chalu** hai.

**3. Fee gate 5× → 4×**
- `risk_amount < total_fee_est × 4.0` → entry skip.
- Note: 2026-07-17 ke sweep me 5× best tha — fresh data par dobara check karna.

**4. Shadow limit 2.5% → 3.0%**
- `MAX_SL_PCT = 0.030`. 1R SL distance (ATR × 1.35) price ka 3.0% se zyada → shadow trade
  (record hoti hai, wallet/stats me count nahi, exchange par nahi jaati).
- Asli SL 1.2R par hota hai, isliye limit ke just neeche wale pair ka real stop ~3.6% door hota hai.

**5. Night gate (6 PM – 1 AM IST)**
- `TRADE_WINDOW_START = (1, 0)`, `TRADE_WINDOW_END = (18, 0)` — yeh **allowed** window hai.
- Sirf nayi entry rukti hai. Khuli position apne SL/TP/trailing se hi exit hogi. Signals UI par chalte rahenge.
- `None` karne se gate band.
- Logs (Logs page + Supabase `bot_logs`):
  - `🌙 Night gate ON (18:00–01:00 IST) — new entries paused; open positions unaffected`
  - `🌙 Night gate: PAIR LONG signal (score 4/7) skipped @ HH:MM IST price=…` (per pair per 5-min candle ek baar)
  - `☀️ Night gate OFF — entries resumed (trading window 01:00–18:00 IST)`
- Data (21 Aug – 11 Sep, 18:00–01:00 ki entries): 7 trades, 2 win, net −5,253 — sample chhota hai.

**6. 1H EMA9 distance filter (> 2%)**
- Formula: `dist % = (price − 1H EMA9) / price × 100`, **short signal par sign ulta**.
  Signal tabhi banega jab `dist > 2.0`.
- **Signal direction** par naapa jaata hai, executed direction par nahi — reverse toggle ON/OFF se matlab nahi badalta.
- Config: `SCALPING["min_h1_ema9_dist_pct"] = 2.0` (`None` = band). Sirf tab chalta hai jab
  `confirm_tfs[0] == "1h"`. SWING par nahi lagta.
- Naye fields `h1_ema9_dist_pct`, `ema9_blocked` sirf in-memory hain — `to_dict()` / `signals` table me nahi jaate.
- Log (sirf jab baaki saare checks pass hon aur sirf EMA9 ne roka ho; night gate ke time nahi):
  `📏 EMA9 filter: PAIR LONG signal (score 4/7) skipped — 1H EMA9 distance 1.23% (need > 2.0%) @ HH:MM IST price=…`
- ⚠️ Data warning (day-time trades, signal-direction distance):
  | Dist | 8–27 Aug | 28 Aug – 11 Sep |
  |---|---|---|
  | ≤ 1% | 21 trades, 45% WR, −2,124 | 19 trades, 47% WR, +3,590 |
  | 1–2% | 37 trades, 51% WR, −6,861 | 27 trades, 48% WR, −4,183 |
  | 2–3% | 23 trades, 59% WR, +2,698 | 24 trades, 30% WR, −9,569 |
  | > 3% | 20 trades, 68% WR, +7,191 | 10 trades, 30% WR, −5,647 |

  Pattern 28 Aug ke baad ulta raha — **1–2 hafte baad zaroor review karna.**

### Kya NAHI badla
- Signal layers (7 layers, min score 4), multi-TF trend (1h/30m/15m/5m sab aligned, ADX ≥ 22),
  1H trend bias gate, 5m EMA pullback (0.75%).
- Exit: SL 1.2R, TP 2.0R, trailing `[(0.8, −0.5), (1.5, +1.0)]`.
- Adaptive per-pair filter, max 7 trades, leverage default 5x, coin list (84 pairs).
- Trade direction reverse — frontend toggle se start par decide hota hai.

### Testing status
- Local PC par Python nahi hai — code run karke test **nahi** hua. Sirf diff review + imports check.
- **Deploy ke baad logs zaroor check karna** (`journalctl -u thinktrade -n 100 --no-pager`).

---

## Isse pehle ka result (reference ke liye)

Version-2.0 ki pehli trade 8 Aug 2026; shuru se har trade signal ki **ulti direction** me (reverse).

| Period | Logic us waqt | Trades | Win rate | Net |
|---|---|---|---|---|
| 8–17 Aug | Purana exit (SL 1.0R / TP 2.5R), lockout nahi | 45 | 61.4% | +5,409 |
| 18–27 Aug | Purana exit + daily loss lockout | 64 | 50.0% | −7,632 |
| 28 Aug – 11 Sep | SL 1.2R / TP 2.0R / trailing + lockout | 85 | 39.0% | −20,040 |
| **Total** | | **194** | **47.9%** | **−22,263** |

Shadow trades (alag): 6 trades, net −18,365. Fees total ~23,805.

---

## Naye logic ka analysis kaise karna
```sql
SELECT COUNT(*) trades,
       SUM((net_pnl > 0)::int) wins,
       ROUND(100.0 * AVG((net_pnl > 0)::int), 1) win_pct,
       ROUND(SUM(net_pnl), 0) net
FROM trades
WHERE trader_name = 'Version-2.0' AND mode = 'demo'
  AND status = 'closed' AND NOT is_shadow
  AND entry_time >= '<DEPLOY DATE-TIME>+05:30';
```

EMA9 filter ne kitne signal roke:
```sql
SELECT COUNT(*) FROM bot_logs
WHERE msg LIKE '%EMA9 filter:%skipped%'
  AND to_timestamp(ts) >= '<DEPLOY DATE-TIME>+05:30';
```
