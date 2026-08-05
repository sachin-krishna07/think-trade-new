import { motion } from "framer-motion";
import { SignalData } from "@/hooks/useBotSocket";

interface Props {
  signals: Record<string, SignalData>;
  selectedPairs?: string[];
  running?: boolean;
  knownPairs?: string[];
  style?: string;
}

const LAYERS = [
  { key: "trend_regime",    label: "L1", name: "Trend",    weight: "MANDATORY" },
  { key: "cvd_divergence",  label: "L2", name: "CVD",      weight: "HIGH"      },
  { key: "vwap_deviation",  label: "L3", name: "VWAP",     weight: "MEDIUM"    },
  { key: "dom_imbalance",   label: "L4", name: "DOM",      weight: "MEDIUM"    },
  { key: "rsi2_extreme",    label: "L5", name: "RSI",      weight: "MEDIUM"    },
  { key: "liquidity_sweep", label: "L6", name: "Sweep",    weight: "HIGH"      },
  { key: "fair_value_gap",  label: "L7", name: "FVG",      weight: "HIGH"      },
];

function fmt(n: number | undefined, dec = 2) {
  if (n === undefined || n === null) return "—";
  return Number(n).toFixed(dec);
}

function getDetail(sig: SignalData, key: string): string {
  switch (key) {
    case "trend_regime":    return `ADX ${fmt(sig.adx_value, 1)}`;
    case "cvd_divergence":  return `CVD ${fmt(sig.cvd_value, 0)}`;
    case "vwap_deviation":  return `${fmt(sig.vwap_dev_pct, 2)}%`;
    case "dom_imbalance":   return `${fmt(sig.dom_ratio, 1)}:1`;
    case "rsi2_extreme":    return `RSI ${fmt(sig.rsi2_value, 1)}`;
    case "liquidity_sweep": return (sig as any)["liquidity_sweep"] === 1 ? "Swept" : "None";
    case "fair_value_gap":  return (sig as any)["fair_value_gap"] === 1 ? `@ ${fmt(sig.fvg_level, 2)}` : "None";
    default: return "";
  }
}

function PairSignalCard({ pair, sig }: { pair: string; sig?: SignalData; style?: string }) {
  if (!sig) {
    return (
      <div className="bg-[#0a0d14] border border-[#1e2433] rounded-2xl p-4 animate-pulse">
        <div className="h-4 bg-[#1a2035] rounded w-1/2 mb-3" />
        <div className="h-3 bg-[#1a2035] rounded w-full mb-2" />
        <div className="grid grid-cols-4 gap-1 mt-3">
          {Array.from({length: 8}).map((_,i) => <div key={i} className="h-8 bg-[#1a2035] rounded-lg" />)}
        </div>
      </div>
    );
  }

  const score       = sig.total_score || 0;
  const dir         = sig.signal_direction || "none";
  const l8Pass      = sig.ema_pullback === 1;
  const canTrade    = sig.trade_signal;
  const h1RsiState  = sig.h1_rsi_state  || "neutral";
  const h1RsiVal    = sig.h1_rsi_value  ?? null;
  const h1Blocked   = sig.h1_rsi_blocked === true;

  const isLong    = dir === "long";
  const isShort   = dir === "short";
  const isNeutral = dir === "none";

  const borderClass = canTrade
    ? "border-green-500/60 shadow-[0_0_20px_rgba(34,197,94,0.2)]"
    : isLong  ? "border-green-500/20"
    : isShort ? "border-red-500/20"
    : "border-[#1e2433]";

  const dirBg = isLong  ? "bg-green-500/15 text-green-400 border-green-500/30"
              : isShort ? "bg-red-500/15 text-red-400 border-red-500/30"
              : "bg-gray-700/20 text-gray-500 border-gray-700/30";

  const scoreColor = score >= 5 ? "text-green-400"
                   : score >= 4 ? "text-yellow-400"
                   : score >= 2 ? "text-orange-400"
                   : "text-gray-600";

  return (
    <div className={`bg-[#0a0d14] border rounded-2xl overflow-hidden transition-all duration-200 ${borderClass}`}>

      {/* Top accent bar */}
      <div className={`h-0.5 w-full ${
        canTrade ? "bg-gradient-to-r from-green-500 to-emerald-400" :
        isLong   ? "bg-gradient-to-r from-green-800 to-transparent" :
        isShort  ? "bg-gradient-to-r from-red-800 to-transparent" :
        "bg-transparent"
      }`} />

      <div className="p-3">
        {/* Header */}
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-2">
            <span className="text-white font-black text-sm tracking-wide">{pair}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-md font-bold border ${dirBg}`}>
              {isNeutral ? "NEUTRAL" : dir.toUpperCase()}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {h1RsiState === "overbought" && (
              <span className="text-[9px] px-1.5 py-0.5 rounded font-black bg-orange-500/20 border border-orange-500/40 text-orange-400">
                OB {h1RsiVal !== null ? h1RsiVal.toFixed(0) : ""}
              </span>
            )}
            {h1RsiState === "oversold" && (
              <span className="text-[9px] px-1.5 py-0.5 rounded font-black bg-blue-500/20 border border-blue-500/40 text-blue-400">
                OS {h1RsiVal !== null ? h1RsiVal.toFixed(0) : ""}
              </span>
            )}
            <span className="text-white font-mono font-bold text-xs">
              ${fmt(sig.price, sig.price > 100 ? 2 : 4)}
            </span>
            <span className={`text-base font-black ${scoreColor}`}>{score}/7</span>
          </div>
        </div>

        {/* Score bar */}
        <div className="flex gap-0.5 mb-2.5">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className={`flex-1 h-1 rounded-full transition-all ${
              i < score
                ? score >= 5 ? "bg-green-400" : score >= 4 ? "bg-yellow-400" : "bg-orange-500/70"
                : "bg-[#1e2433]"
            }`} />
          ))}
        </div>

        {/* Layer pills grid */}
        <div className="grid grid-cols-4 gap-1 mb-2">
          {LAYERS.map((l) => {
            const active = (sig as any)[l.key] === 1;
            const detail = getDetail(sig, l.key);
            return (
              <div key={l.key} className={`rounded-lg px-1.5 py-1.5 text-center transition-all ${
                active
                  ? "bg-green-500/15 border border-green-500/30"
                  : "bg-[#111827] border border-[#1e2433]"
              }`}>
                <div className={`text-[9px] font-black ${active ? "text-green-400" : "text-gray-600"}`}>
                  {l.label}
                </div>
                <div className={`text-[9px] font-mono truncate ${active ? "text-green-300/70" : "text-gray-700"}`}>
                  {detail}
                </div>
              </div>
            );
          })}

          {/* L8 pill */}
          <div className={`rounded-lg px-1.5 py-1.5 text-center transition-all ${
            l8Pass
              ? "bg-purple-500/15 border border-purple-500/30"
              : "bg-[#111827] border border-[#1e2433]"
          }`}>
            <div className={`text-[9px] font-black ${l8Pass ? "text-purple-400" : "text-gray-600"}`}>
              L8
            </div>
            <div className={`text-[9px] font-mono truncate ${l8Pass ? "text-purple-300/70" : "text-gray-700"}`}>
              {l8Pass ? "EMA✓" : "EMA…"}
            </div>
          </div>
        </div>

        {/* ATR */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-[9px] text-gray-600">ATR <span className="text-gray-400 font-mono">{fmt(sig.atr_value, sig.atr_value > 10 ? 1 : 4)}</span></span>
          {!isNeutral && (
            <span className="text-[9px] text-gray-600">
              VWAP dev <span className={`font-mono ${Math.abs(sig.vwap_dev_pct || 0) > 0.3 ? "text-orange-400" : "text-gray-400"}`}>
                {fmt(sig.vwap_dev_pct, 2)}%
              </span>
            </span>
          )}
        </div>

        {/* Entry signal banner */}
        {canTrade ? (
          <div className="flex items-center justify-center gap-1.5 py-1.5 rounded-xl
                          bg-green-500/15 border border-green-500/40 text-green-400 text-[11px] font-black tracking-wide">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            ENTRY · {dir.toUpperCase()} · {score}/7
          </div>
        ) : h1Blocked ? (
          <div className="flex items-center justify-center gap-1.5 py-1.5 rounded-xl
                          bg-orange-500/10 border border-orange-500/30 text-orange-400 text-[10px] font-semibold">
            🚫 1H RSI {h1RsiState === "overbought" ? "Overbought" : "Oversold"} · {dir.toUpperCase()} blocked
          </div>
        ) : score >= 4 && sig.trend_regime === 1 ? (
          <div className="flex items-center justify-center gap-1.5 py-1.5 rounded-xl
                          bg-orange-500/10 border border-orange-500/20 text-orange-400/80 text-[10px] font-semibold">
            ⚠ {!l8Pass ? "Waiting EMA-12 pullback" : "Signal blocked"}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function SignalPanel({ signals, selectedPairs, running, knownPairs, style }: Props) {
  const basePairs = selectedPairs?.length ? selectedPairs : Object.keys(signals);
  // Highest score first, so cards climb as their score rises.
  const signalPairs = [...basePairs].sort((a, b) =>
    (signals[b]?.total_score ?? -1) - (signals[a]?.total_score ?? -1)
  );

  if (running && signalPairs.length === 0) {
    const skeletonPairs = knownPairs && knownPairs.length > 0 ? knownPairs : null;
    if (skeletonPairs) {
      return (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {skeletonPairs.map((p) => <PairSignalCard key={p} pair={p} sig={undefined} style={style} />)}
        </div>
      );
    }
    return (
      <div className="bg-[#0a0d14] border border-[#1e2433] rounded-2xl p-8 text-center space-y-2">
        <div className="flex items-center justify-center gap-2 text-blue-400 text-sm font-medium">
          <span className="animate-spin inline-block w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full" />
          Loading market data...
        </div>
        <p className="text-gray-600 text-xs">Signals will appear automatically in a few seconds</p>
      </div>
    );
  }

  if (signalPairs.length === 0) {
    return (
      <div className="bg-[#0a0d14] border border-[#1e2433] rounded-2xl p-8 text-center text-gray-500 text-sm">
        Start the bot to see live signals
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
      {signalPairs.map((p) => (
        <motion.div key={p} layout transition={{ duration: 0.4, ease: "easeInOut" }}>
          <PairSignalCard pair={p} sig={signals[p]} style={style} />
        </motion.div>
      ))}
    </div>
  );
}
