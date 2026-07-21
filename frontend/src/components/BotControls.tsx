import { useState, useEffect } from "react";
import { Play, Square, AlertTriangle, Zap, TrendingUp, Monitor, Radio, Repeat } from "lucide-react";
import { useExchangeRate } from "@/hooks/useExchangeRate";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// Blocklisted 2026-07-03 (2.0 trade data): SUI, NEAR, TON, OP, POL, HBAR, NOT, ARB
// Rebuilt 2026-07-10 to match backend config.py — sorted by exchange volume,
// high to low. Must stay in sync with PAIRS in backend/config.py.
const ALL_PAIRS = [
  "BTC", "ETH", "XAUT", "PAXG", "SOL", "XRP", "ZEC", "SKL",
  "DOGE", "AAVE", "ALLO", "BNB", "UNI", "LINK", "BCH", "ADA",
  "LTC", "AVAX", "KAITO", "EIGEN", "PARTI", "GRAM", "DOT", "TAO",
  "JTO", "TRX", "MMT", "PENDLE", "TIA", "MUBARAK", "ONDO", "XLM",
  "MANA", "ETHFI", "WLD", "LDO", "ZRO", "TRB", "JUP", "PEOPLE",
  "IO", "JASMY", "WIF", "ORDI", "INJ", "ENA", "1000SATS", "AIGENSYN",
  "SAHARA", "DYDX", "PENGU", "BLUR", "ASTER", "TRUMP", "KITE", "EDEN",
  "BIO", "TST", "ALT", "RSR", "CHIP", "SEI", "DOGS", "WCT",
  "XPL", "DASH", "GIGGLE", "RED", "LISTA", "VANA", "FIL", "CAKE",
  "KSM", "LAYER", "VIRTUAL", "DUSK", "ZK", "PROVE", "SAGA", "ETC",
  "BERA", "PNUT", "ACT", "FRAX",
];

interface Props {
  running: boolean;
  mode: string;
  style: string;
  reverseDirection: boolean;  // server truth — what the running bot is actually using
  onStart: (cfg: any) => Promise<void>;
  onStop: () => Promise<void>;
  onForceClose: () => Promise<void>;
  hasPosition: boolean;
  walletBalance?: number;  // USD balance from wallet
}

export default function BotControls({ running, mode: curMode, style: curStyle,
  reverseDirection: curReverseDirection,
  onStart, onStop, onForceClose, hasPosition, walletBalance }: Props) {
  const actionPin = import.meta.env.VITE_BOT_ACTION_PIN;

  const [mode, setMode]             = useState(() => localStorage.getItem("bot_mode") || "demo");
  const [style, setStyle]           = useState(() => localStorage.getItem("bot_style") || "scalping");
  const [pairs, setPairs]           = useState<string[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("bot_pairs") || "null") as string[] | null;
      // Drop blocklisted coins that may still be cached from before
      const valid = saved?.filter((p) => ALL_PAIRS.includes(p));
      return valid && valid.length > 0 ? valid : ALL_PAIRS;
    }
    catch { return ALL_PAIRS; }
  });
  const [capitalPct, setCapitalPct] = useState(() => localStorage.getItem("bot_capital") || "1");
  const [leverage, setLeverage]     = useState(() => localStorage.getItem("bot_leverage") || "5");
  // Pre-start config only — once running, the badge below shows curReverseDirection (server truth) instead.
  const [reverseDirectionCfg, setReverseDirectionCfg] = useState(() => localStorage.getItem("bot_reverse") === "true");
  const [loading, setLoading]       = useState(false);
  const [pinDialogOpen, setPinDialogOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<"start" | "stop" | null>(null);
  const [pinValue, setPinValue] = useState("");
  const [pinError, setPinError] = useState("");
  const { fmtINR, rate }            = useExchangeRate();

  // Estimated trade size calculation
  const estTradeUsd = walletBalance
    ? (walletBalance * (parseFloat(capitalPct) || 0) / 100) * (parseFloat(leverage) || 1)
    : 0;
  const estTradeInr = estTradeUsd * (rate || 84);

  // Clear loading when running state confirms from WebSocket
  useEffect(() => {
    if (running) setLoading(false);
  }, [running]);

  useEffect(() => {
    if (!pinDialogOpen) {
      setPinValue("");
      setPinError("");
      setPendingAction(null);
    }
  }, [pinDialogOpen]);

  const togglePair = (p: string) =>
    setPairs((prev) => {
      const next = prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p];
      localStorage.setItem("bot_pairs", JSON.stringify(next));
      return next;
    });

  const handleSetMode = (m: string) => { setMode(m); localStorage.setItem("bot_mode", m); };
  const handleSetStyle = (s: string) => { setStyle(s); localStorage.setItem("bot_style", s); };
  const handleSetCapital = (v: string) => { setCapitalPct(v); localStorage.setItem("bot_capital", v); };
  const handleSetLeverage = (v: string) => { setLeverage(v); localStorage.setItem("bot_leverage", v); };
  const handleToggleReverse = () => {
    setReverseDirectionCfg((prev) => {
      const next = !prev;
      localStorage.setItem("bot_reverse", String(next));
      return next;
    });
  };

  const handleStart = async () => {
    const pct = parseFloat(capitalPct);
    if (isNaN(pct) || pct <= 0 || pct > 50) return;
    if (pairs.length === 0) return;
    setPendingAction("start");
    setPinDialogOpen(true);
  };

  const executeStart = async () => {
    const pct = parseFloat(capitalPct);
    if (isNaN(pct) || pct <= 0 || pct > 50) return;
    if (pairs.length === 0) return;
    try {
      setLoading(true);
      const lev = Math.min(Math.max(parseFloat(leverage) || 5, 1), 20);
      const traderName = import.meta.env.VITE_TRADER_NAME || "Unknown";
      await onStart({
        mode, style, pairs, capital_pct: pct, leverage: lev, trader_name: traderName,
        reverse_direction: reverseDirectionCfg,
      });
      // Don't clear loading here — wait for running=true via WebSocket (useEffect above)
    } catch {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setPendingAction("stop");
    setPinDialogOpen(true);
  };

  const executeStop = async () => {
    try {
      setLoading(true);
      await onStop();
    } finally {
      setLoading(false);
    }
  };

  const confirmPinAction = async () => {
    if (pinValue.length !== 4) {
      setPinError("Enter 4-digit PIN");
      return;
    }
    if (pinValue !== actionPin) {
      setPinError("Wrong PIN");
      return;
    }

    setPinDialogOpen(false);
    if (pendingAction === "start") {
      await executeStart();
    } else if (pendingAction === "stop") {
      await executeStop();
    }
  };

  return (
    <div className="bg-[#0d1117] border border-[#1e2433] rounded-xl p-4 space-y-4 w-full">

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-white font-semibold text-xs tracking-widest uppercase">Bot Controls</h2>
        <span className={`flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-full border ${
          running
            ? "bg-green-500/10 border-green-500/25 text-green-400"
            : "bg-[#1a2035] border-[#2a3045] text-gray-500"
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${running ? "bg-green-400 animate-pulse" : "bg-gray-600"}`} />
          {running ? `${curMode.toUpperCase()} · ${curStyle}` : "Stopped"}
        </span>
      </div>

      <div className="h-px bg-[#1e2433]" />

      {running ? (
        /* ── Bot running: show compact mode + style info ── */
        <div className="flex gap-2">
          <div className="flex-1 bg-[#111827] border border-[#1e2433] rounded-lg px-3 py-2 text-center">
            <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Mode</div>
            <div className={`flex items-center justify-center gap-1 text-xs font-bold ${curMode === "live" ? "text-red-300" : "text-indigo-300"}`}>
              {curMode === "live" ? <Radio size={11} /> : <Monitor size={11} />}
              {curMode === "demo" ? "DEMO" : "LIVE"}
            </div>
          </div>
          <div className="flex-1 bg-[#111827] border border-[#1e2433] rounded-lg px-3 py-2 text-center">
            <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Style</div>
            <div className="flex items-center justify-center gap-1 text-xs font-bold text-indigo-300">
              {curStyle === "scalping" ? <Zap size={11} /> : <TrendingUp size={11} />}
              {curStyle === "scalping" ? "Scalping" : "Swing"}
            </div>
          </div>
          {curReverseDirection && (
            <div className="flex-1 bg-[#111827] border border-orange-500/30 rounded-lg px-3 py-2 text-center">
              <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Direction</div>
              <div className="flex items-center justify-center gap-1 text-xs font-bold text-orange-300">
                <Repeat size={11} /> Reversed
              </div>
            </div>
          )}
        </div>
      ) : (
        /* ── Bot stopped: show full mode + style + pairs ── */
        <>
          {/* Mode */}
          <div className="space-y-2">
            <label className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Mode</label>
            <div className="flex gap-2">
              {["demo", "live"].map((m) => (
                <button key={m}
                  onClick={() => handleSetMode(m)}
                  className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all ${
                    mode === m
                      ? m === "live"
                        ? "bg-red-500/15 border border-red-500/40 text-red-300"
                        : "bg-indigo-500/15 border border-indigo-500/40 text-indigo-300"
                      : "bg-[#111827] border border-[#1e2433] text-gray-600 hover:text-gray-300 hover:border-[#2a3045]"
                  }`}>
                  <span className="flex items-center justify-center gap-1.5">
                    {m === "live" ? <Radio size={11} /> : <Monitor size={11} />}
                    {m === "demo" ? "DEMO" : "LIVE"}
                  </span>
                </button>
              ))}
            </div>
            {mode === "live" && (
              <p className="flex items-center gap-1.5 text-[11px] text-red-400/80 bg-red-500/5 border border-red-500/15 rounded-lg px-3 py-2">
                <AlertTriangle size={11} className="flex-shrink-0" /> Live mode uses real Binance Futures funds
              </p>
            )}
          </div>

          <div className="h-px bg-[#1e2433]" />

          {/* Style */}
          <div className="space-y-2">
            <label className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Trading Style</label>
            <div className="flex gap-2">
              {["scalping", "swing"].map((s) => (
                <button key={s}
                  onClick={() => handleSetStyle(s)}
                  className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all ${
                    style === s
                      ? "bg-indigo-500/15 border border-indigo-500/40 text-indigo-300"
                      : "bg-[#111827] border border-[#1e2433] text-gray-600 hover:text-gray-300 hover:border-[#2a3045]"
                  }`}>
                  <span className="flex items-center justify-center gap-1.5">
                    {s === "scalping" ? <Zap size={11} /> : <TrendingUp size={11} />}
                    {s === "scalping" ? "Scalping" : "Swing"}
                  </span>
                </button>
              ))}
            </div>
            <p className="text-[11px] text-gray-600 leading-relaxed">
              {style === "scalping"
                ? "2–8 min holds · 15m trend · 5m entry · RSI-2 signals"
                : "Hours–days · 4h trend · 1h entry · RSI-14 signals"}
            </p>
          </div>

          <div className="h-px bg-[#1e2433]" />

          {/* Reverse Direction */}
          <div className="space-y-2">
            <label className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Execution Direction</label>
            <button
              onClick={handleToggleReverse}
              className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-semibold transition-all ${
                reverseDirectionCfg
                  ? "bg-orange-500/15 border border-orange-500/40 text-orange-300"
                  : "bg-[#111827] border border-[#1e2433] text-gray-600 hover:text-gray-300 hover:border-[#2a3045]"
              }`}>
              <Repeat size={11} />
              {reverseDirectionCfg ? "Reversed — takes OPPOSITE of signal" : "Normal — takes signal's own direction"}
            </button>
          </div>

          <div className="h-px bg-[#1e2433]" />

          {/* Pairs */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Pairs</label>
              <span className="text-[10px] text-gray-600">{pairs.length} selected</span>
            </div>
            <div className="flex gap-1.5 flex-wrap">
              {ALL_PAIRS.map((p) => (
                <button key={p}
                  onClick={() => togglePair(p)}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-bold tracking-wide transition-all ${
                    pairs.includes(p)
                      ? "bg-indigo-500/15 border border-indigo-500/40 text-indigo-300"
                      : "bg-[#111827] border border-[#1e2433] text-gray-600 hover:text-gray-400 hover:border-[#2a3045]"
                  }`}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="h-px bg-[#1e2433]" />

      {/* Capital + Leverage */}
      <div className="space-y-2">
        <label className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Capital & Leverage</label>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <div className="text-[10px] text-gray-600">Capital % per trade</div>
            <div className="flex items-center gap-1.5">
              <input
                type="number" min="0.1" max="100" step="0.1"
                value={capitalPct}
                onChange={(e) => handleSetCapital(e.target.value)}
                disabled={running}
                className="w-full bg-[#111827] border border-[#1e2433] text-white rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:border-indigo-500/60 disabled:opacity-50 transition-all"
              />
              <span className="text-gray-500 text-xs">%</span>
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-[10px] text-gray-600">Leverage (max 20x)</div>
            <div className="flex items-center gap-1.5">
              <input
                type="number" min="1" max="20" step="1"
                value={leverage}
                onChange={(e) => handleSetLeverage(e.target.value)}
                disabled={running}
                className="w-full bg-[#111827] border border-yellow-500/30 text-yellow-300 rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:border-yellow-500/60 disabled:opacity-50 transition-all font-bold"
              />
              <span className="text-gray-500 text-xs">x</span>
            </div>
          </div>
        </div>
        {/* Estimated trade size */}
        {estTradeUsd > 0 && (
          <div className="flex items-center justify-between bg-[#111827] border border-[#1e2433] rounded-lg px-3 py-2">
            <span className="text-[10px] text-gray-500">Est. trade size</span>
            <div className="text-right">
              <span className="text-sm font-black text-indigo-300 font-mono">
                {fmtINR(estTradeInr, 0)}
              </span>
              <span className="text-[10px] text-gray-600 ml-1.5">
                (${Math.round(estTradeUsd).toLocaleString()})
              </span>
            </div>
          </div>
        )}
        <p className="text-[11px] text-gray-600">
          SL: ATR×1.35×0.75 · Max loss: -1.5R · Trailing from 1.1R (locks +0.85R)
        </p>
      </div>

      <Dialog open={pinDialogOpen} onOpenChange={setPinDialogOpen}>
        <DialogContent className="z-[120] border-[#1e2433] bg-[#0d1117] text-white sm:max-w-[360px]">
          <DialogHeader>
            <DialogTitle>{pendingAction === "start" ? "Start Bot" : "Stop Bot"}</DialogTitle>
            <DialogDescription className="text-gray-400">
              Enter 4-digit PIN to continue
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <input
              type="password"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={4}
              value={pinValue}
              onChange={(e) => {
                const digits = e.target.value.replace(/\D/g, "").slice(0, 4);
                setPinValue(digits);
                setPinError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") void confirmPinAction();
              }}
              autoFocus
              className="w-full rounded-xl border border-[#2a3045] bg-[#111827] px-4 py-3 text-center text-2xl font-bold tracking-[0.4em] text-white outline-none focus:border-indigo-500/60"
              placeholder="••••"
            />
            {pinError && (
              <div className="text-center text-sm text-red-400">{pinError}</div>
            )}
          </div>

          <DialogFooter className="gap-2 sm:justify-end">
            <button
              type="button"
              onClick={() => setPinDialogOpen(false)}
              className="rounded-lg border border-[#2a3045] px-4 py-2 text-sm font-semibold text-gray-300 transition-colors hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void confirmPinAction()}
              className="rounded-lg border border-indigo-500/40 bg-indigo-500/15 px-4 py-2 text-sm font-semibold text-indigo-300 transition-colors hover:bg-indigo-500/20"
            >
              Confirm
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Buttons */}
      <div className="flex gap-2 pt-1">
        {!running ? (
          <button
            onClick={handleStart}
            disabled={loading || pairs.length === 0}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg
                       bg-green-500/15 hover:bg-green-500/20 border border-green-500/30 hover:border-green-500/50
                       text-green-400 font-semibold text-sm transition-all disabled:opacity-40">
            <Play size={14} /> {loading ? "Starting..." : "START BOT"}
          </button>
        ) : (
          <>
            <button
              onClick={handleStop}
              disabled={loading}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg
                         bg-red-500/15 hover:bg-red-500/20 border border-red-500/30 hover:border-red-500/50
                         text-red-400 font-semibold text-sm transition-all disabled:opacity-40">
              <Square size={13} /> {loading ? "Stopping..." : "STOP BOT"}
            </button>
            {hasPosition && (
              <button
                onClick={onForceClose}
                className="px-3 py-2.5 rounded-lg
                           bg-orange-500/15 hover:bg-orange-500/20 border border-orange-500/30 hover:border-orange-500/50
                           text-orange-400 text-xs font-semibold transition-all whitespace-nowrap">
                CLOSE POS
              </button>
            )}
          </>
        )}
      </div>

    </div>
  );
}
