import { PositionData } from "@/hooks/useBotSocket";
import { Clock, Shield, X } from "lucide-react";
import { useState } from "react";
import { useExchangeRate } from "@/hooks/useExchangeRate";

interface Props {
  position: PositionData | null;
  lastTrade: any | null;
  onForceClose?: () => Promise<any>;
}

function formatSeconds(s: number) {
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default function PositionCard({ position, lastTrade, onForceClose }: Props) {
  const [closing, setClosing] = useState(false);
  const { fmtINR } = useExchangeRate();

  if (!position) {
    return (
      <div className="bg-[#0d1117] border border-[#1e2433] rounded-xl p-4 space-y-3 w-full">
        <h2 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Open Position</h2>
        <div className="text-center py-5 text-gray-700">
          <div className="text-2xl mb-1.5">—</div>
          <div className="text-xs">No open position</div>
        </div>

        {/* Last trade */}
        {lastTrade && (
          <div className={`rounded-lg p-3 border ${
            lastTrade.pnl >= 0
              ? "bg-green-500/5 border-green-500/20"
              : "bg-red-500/5 border-red-500/20"
          }`}>
            <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1.5">Last Trade</div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-white font-semibold">{lastTrade.pair} · {lastTrade.reason?.toUpperCase()}</span>
              <span className={`text-sm font-bold font-mono ${lastTrade.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                {lastTrade.pnl >= 0 ? "+" : ""}{fmtINR(lastTrade.pnl ?? 0)}
              </span>
            </div>
            <div className="text-[10px] text-gray-600 mt-1">
              R: {lastTrade.r?.toFixed(2)} · Bal: {fmtINR(lastTrade.balance ?? 0)}
            </div>
          </div>
        )}
      </div>
    );
  }

  const handleForceClose = async () => {
    if (!confirm("Close this trade now?")) return;
    setClosing(true);
    try {
      await onForceClose?.();
    } finally {
      setClosing(false);
    }
  };

  const isLong = position.direction === "long";
  const pnlUp  = position.pnl >= 0;
  const r      = position.r ?? 0;

  return (
    <div className={`bg-[#0d1117] border rounded-xl p-4 space-y-3 w-full ${
      pnlUp ? "border-green-500/30" : "border-red-500/30"
    }`}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Position</h2>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold border ${
            isLong
              ? "bg-green-500/10 border-green-500/25 text-green-400"
              : "bg-red-500/10 border-red-500/25 text-red-400"
          }`}>
            {isLong ? "▲ LONG" : "▼ SHORT"}
          </span>
          <span className="text-xs text-indigo-400 font-bold">{position.pair}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-gray-600 text-[11px]">
            <Clock size={11} />
            {formatSeconds(position.elapsed_sec || 0)}
          </div>
          <button
            onClick={handleForceClose}
            disabled={closing}
            className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border border-red-500/30 bg-red-500/10 text-red-400 font-semibold hover:bg-red-500/20 transition disabled:opacity-50"
          >
            <X size={10} />
            {closing ? "Closing..." : "Exit"}
          </button>
        </div>
      </div>

      {/* PnL */}
      <div className={`rounded-lg p-3 border ${
        pnlUp
          ? "bg-green-500/5 border-green-500/20"
          : "bg-red-500/5 border-red-500/20"
      }`}>
        <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Unrealized P&L</div>
        <div className={`text-2xl font-bold font-mono ${pnlUp ? "text-green-400" : "text-red-400"}`}>
          {pnlUp ? "+" : ""}{fmtINR(position.pnl ?? 0)}
        </div>
        <div className={`text-xs font-medium mt-0.5 ${pnlUp ? "text-green-400/70" : "text-red-400/70"}`}>
          {position.pnl_pct >= 0 ? "+" : ""}{position.pnl_pct?.toFixed(3)}% · R: {r.toFixed(2)}
        </div>
      </div>

      {/* Price grid */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="bg-[#111827] border border-[#1e2433] rounded-lg p-2 text-center">
          <div className="text-gray-600 mb-1 text-[10px] uppercase tracking-wider">Entry</div>
          <div className="text-white font-mono font-medium">{position.entry?.toFixed(4)}</div>
        </div>
        <div className="bg-[#111827] border border-[#1e2433] rounded-lg p-2 text-center">
          <div className="text-gray-600 mb-1 text-[10px] uppercase tracking-wider">Current</div>
          <div className={`font-mono font-bold ${pnlUp ? "text-green-400" : "text-red-400"}`}>
            {position.current?.toFixed(4)}
          </div>
        </div>
        <div className="bg-[#111827] border border-[#1e2433] rounded-lg p-2 text-center">
          <div className="text-gray-600 mb-1 text-[10px] uppercase tracking-wider">Target</div>
          {position.has_hard_tp === false ? (
            <div className="text-purple-400 font-medium text-[11px]" title="No fixed target — trailing stop is the only profit exit">
              Trailing
            </div>
          ) : (
            <div className="text-yellow-400 font-mono font-medium">{position.tp?.toFixed(4)}</div>
          )}
        </div>
      </div>

      {/* Position size row */}
      {position.size_usd > 0 && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="bg-[#111827] border border-[#1e2433] rounded-lg p-2 text-center">
            <div className="text-gray-600 mb-1 text-[10px] uppercase tracking-wider">Position Size</div>
            <div className="text-indigo-300 font-mono font-bold">
              {fmtINR(position.size_usd ?? 0, 0)}
            </div>
          </div>
          <div className="bg-[#111827] border border-[#1e2433] rounded-lg p-2 text-center">
            <div className="text-gray-600 mb-1 text-[10px] uppercase tracking-wider">At Risk</div>
            <div className="text-orange-300 font-mono font-bold">
              {fmtINR(position.risk_usd ?? 0)}
            </div>
          </div>
        </div>
      )}

      {/* SL row */}
      <div className="flex items-center justify-between text-xs flex-wrap gap-2">
        <div className="flex items-center gap-1.5 text-red-400">
          <Shield size={11} />
          <span>SL: <span className="font-mono font-medium">{position.sl?.toFixed(4)}</span></span>
          {position.trailing_sl && position.trailing_armed && (
            <span className="text-gray-600 text-[10px]">(trailing)</span>
          )}
        </div>
        <div className="flex gap-1.5">
          {position.trailing_armed && (
            <span className="text-[10px] px-2 py-0.5 rounded-full border border-purple-500/25 bg-purple-500/10 text-purple-400 font-semibold">
              TRAILING
            </span>
          )}
          {position.profit_locked && (
            <span className="text-[10px] px-2 py-0.5 rounded-full border border-green-500/25 bg-green-500/10 text-green-400 font-semibold">
              LOCKED
            </span>
          )}
        </div>
      </div>

    </div>
  );
}