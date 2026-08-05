import { useEffect, useRef, useState, useCallback } from "react";

const WS_URL = import.meta.env.VITE_BOT_WS_URL || "ws://localhost:8000/ws";
const API_URL = import.meta.env.VITE_BOT_API_URL || "http://localhost:8000";

export interface SignalData {
  pair: string;
  price: number;
  trend_regime: number;
  trend_direction: string;
  adx_value: number;
  ema9_value: number;
  ema21_value: number;
  cvd_divergence: number;
  cvd_value: number;
  vwap_deviation: number;
  vwap_value: number;
  vwap_dev_pct: number;
  dom_imbalance: number;
  dom_ratio: number;
  rsi2_extreme: number;
  rsi2_value: number;
  liquidity_sweep: number;
  sweep_type: string;
  fair_value_gap: number;
  fvg_type: string;
  fvg_level: number;
  total_score: number;
  signal_direction: string;
  trade_signal: boolean;  // true = all gates passed, bot will enter
  btc_bias: string;
  atr_value: number;
  ema_pullback: number;
  h1_rsi_value: number;
  h1_rsi_state: string;   // "overbought" | "oversold" | "neutral"
  h1_rsi_blocked: boolean;
}

export interface PositionData {
  pair: string;
  direction: string;
  entry: number;
  current: number;
  sl: number;
  tp: number;
  pnl: number;
  pnl_pct: number;
  r: number;
  highest_pnl: number;
  trailing_armed: boolean;
  /** false when there's no hard target — `tp` is a placeholder bracket */
  has_hard_tp?: boolean;
  profit_locked: boolean;
  trailing_sl: number | null;
  elapsed_sec: number;
  size_usd: number;
  risk_usd: number;
}

export interface WalletData {
  balance: number;
  initial_balance: number;
  total_pnl: number;
  daily_pnl: number;
  total_pnl_pct: number;
}

export interface RiskStatus {
  trade_mode: string;              // "normal" | "semi_normal" | "restricted" | "cooldown"
  max_trades: number;
  cooldown_level: number;
  cooldown_remaining_sec: number | null;
  cooldown_total_min: number | null;
  consecutive_wins: number;
}

export interface LogEntry {
  ts: number;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  name: string;
  msg: string;
}

export interface BotState {
  connected: boolean;
  running: boolean;
  mode: string;
  style: string;
  reverseDirection: boolean;
  pairs: string[];
  signals: Record<string, SignalData>;
  positions: Record<string, PositionData>;
  wallet: WalletData | null;
  riskStatus: RiskStatus | null;
  lastTrade: any | null;
  logs: LogEntry[];
}

const initialState: BotState = {
  connected: false,
  running: false,
  mode: "demo",
  style: "scalping",
  reverseDirection: false,
  pairs: [],
  signals: {},
  positions: {},
  wallet: null,
  riskStatus: null,
  lastTrade: null,
  logs: [],
};

const entryAudio = new Audio(new URL("../ringtone/enrty.mp3", import.meta.url).href);
const exitAudio  = new Audio(new URL("../ringtone/exit-trade.mp3", import.meta.url).href);

export function useBotSocket() {
  const [state, setState] = useState<BotState>(initialState);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout>>();
  const handleMessageRef = useRef<(msg: { type: string; data: any }) => void>(() => {});
  const snapshotPollRef = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setState((s) => ({ ...s, connected: true }));
      clearTimeout(reconnectRef.current);
      const ping = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, 25000);
      (ws as any)._pingInterval = ping;
    };

    ws.onclose = () => {
      clearInterval((ws as any)._pingInterval);
      setState((s) => ({ ...s, connected: false }));
      reconnectRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessageRef.current(msg);
      } catch (_) {}
    };
  }, []);

  const handleMessage = (msg: { type: string; data: any }) => {
    switch (msg.type) {
      case "snapshot": {
        // Rebuild positions map from snapshot array
        const posMap: Record<string, any> = {};
        (msg.data.positions || []).forEach((p: any) => {
          posMap[p.pair] = p;
        });
        setState((s) => ({
          ...s,
          running:   msg.data.running,
          mode:      msg.data.mode,
          style:     msg.data.style,
          reverseDirection: msg.data.reverse_direction ?? s.reverseDirection,
          pairs:     msg.data.pairs || [],
          signals:   msg.data.signals || {},
          wallet:    msg.data.wallet,
          positions: posMap,
        }));
        break;
      }

      case "signal_update":
        setState((s) => ({
          ...s,
          signals: { ...s.signals, [msg.data.pair]: msg.data },
        }));
        break;

      case "position_update":
        setState((s) => ({
          ...s,
          positions: { ...s.positions, [msg.data.pair]: msg.data },
        }));
        break;

      case "trade_opened":
        entryAudio.currentTime = 0; entryAudio.play().catch(() => {});
        setState((s) => ({
          ...s,
          positions: {
            ...s.positions,
            [msg.data.pair]: { ...msg.data, elapsed_sec: 0, r: 0, pnl_pct: 0, pnl: 0 },
          },
        }));
        break;

      case "trade_closed":
        exitAudio.currentTime = 0; exitAudio.play().catch(() => {});
        setState((s) => {
          const { [msg.data.pair]: _removed, ...remaining } = s.positions;
          return { ...s, positions: remaining, lastTrade: msg.data };
        });
        break;

      case "price_update":
        setState((s) => {
          let changed = false;
          const entries = Object.entries(msg.data as Record<string, number>);
          const next: typeof s.signals = {};
          for (const [pair, sig] of Object.entries(s.signals)) {
            const newPrice = (msg.data as Record<string, number>)[pair];
            if (newPrice !== undefined && newPrice !== sig.price) {
              next[pair] = { ...sig, price: newPrice };
              changed = true;
            } else {
              next[pair] = sig;
            }
          }
          void entries; // suppress unused warning
          return changed ? { ...s, signals: next } : s;
        });
        break;

      case "wallet_update": {
        const { risk_status, ...walletData } = msg.data;
        setState((s) => ({
          ...s,
          wallet: walletData,
          riskStatus: risk_status || s.riskStatus,
        }));
        break;
      }

      case "bot_status":
        setState((s) => ({
          ...s,
          running: msg.data.running,
          mode: msg.data.mode || s.mode,
          style: msg.data.style || s.style,
          reverseDirection: msg.data.reverse_direction ?? s.reverseDirection,
          pairs: msg.data.pairs || s.pairs,
        }));
        // If bot just started, poll REST as a safety net in case WS signal_updates
        // were missed (e.g. due to timing). Cancel any previous poll first.
        if (msg.data.running) {
          clearTimeout(snapshotPollRef.current);
          snapshotPollRef.current = setTimeout(async () => {
            setState((s) => {
              if (s.running && Object.keys(s.signals).length === 0) {
                fetch(`${API_URL}/api/bot/status`)
                  .then((r) => r.json())
                  .then((snap) => {
                    if (snap.signals && Object.keys(snap.signals).length > 0) {
                      setState((prev) => ({ ...prev, signals: snap.signals }));
                    }
                  })
                  .catch(() => {});
              }
              return s;
            });
          }, 8000);
        }
        break;

      case "log_entry":
        setState((s) => ({
          ...s,
          logs: [...s.logs.slice(-299), msg.data as LogEntry],
        }));
        break;
    }
  };

  handleMessageRef.current = handleMessage;

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectRef.current);
      clearTimeout(snapshotPollRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // ─── API calls ──────────────────────────────────────────

  const startBot = async (config: {
    mode: string;
    style: string;
    pairs: string[];
    capital_pct: number;
    leverage?: number;
    trader_name?: string;
    reverse_direction?: boolean;
  }) => {
    const r = await fetch(`${API_URL}/api/bot/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    return r.json();
  };

  const stopBot = async () => {
    const r = await fetch(`${API_URL}/api/bot/stop`, { method: "POST" });
    return r.json();
  };

  const forceClose = async (pair?: string) => {
    const url = pair
      ? `${API_URL}/api/bot/force-close/${pair}`
      : `${API_URL}/api/bot/force-close`;
    const r = await fetch(url, { method: "POST" });
    return r.json();
  };

  return { state, startBot, stopBot, forceClose };
}
