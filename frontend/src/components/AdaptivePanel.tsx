import { useEffect, useState } from "react";
import { Brain, Ban, CheckCircle2 } from "lucide-react";

const API_URL = import.meta.env.VITE_BOT_API_URL || "http://localhost:8000";

interface PairState {
  samples: number;
  mean_r: number;
  wins: number;
  allowed: boolean;
  reason: string;
  blocked_since: number | null;
}

interface AdaptiveState {
  enabled: boolean;
  k: number;
  min_samples: number;
  probe_secs: number;
  pairs: Record<string, PairState>;
  blocked: string[];
}

/**
 * Adaptive per-pair filter state.
 *
 * The backend learns from its own CLOSED trades and stops entering pairs whose
 * recent mean net-R is negative. It needs `min_samples` closed trades on a pair
 * before it can act, so expect this to sit idle for a while on a fresh DB —
 * that is the filter learning, not a fault.
 */
export default function AdaptivePanel({ running }: { running?: boolean }) {
  const [state, setState] = useState<AdaptiveState | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch(`${API_URL}/api/adaptive`);
        if (!r.ok) return;
        const d = await r.json();
        if (alive) setState(d);
      } catch {
        /* backend down — leave last known state on screen */
      }
    };
    load();
    const t = setInterval(load, 15_000);
    return () => { alive = false; clearInterval(t); };
  }, [running]);

  if (!state || !state.enabled) return null;

  const pairs = Object.entries(state.pairs);
  const learning = pairs.filter(([, v]) => v.samples < state.min_samples);
  const active   = pairs.filter(([, v]) => v.samples >= state.min_samples);
  const blocked  = active.filter(([, v]) => !v.allowed);
  const allowed  = active.filter(([, v]) => v.allowed);

  return (
    <div className="bg-[#0d1117] border border-[#1e2433] rounded-xl p-4 space-y-3 w-full">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-[10px] font-bold text-gray-500 uppercase tracking-widest">
          <Brain size={11} /> Adaptive Filter
        </h2>
        <span className="text-[10px] text-gray-600">
          last {state.k} trades/pair
        </span>
      </div>

      {pairs.length === 0 ? (
        <p className="text-[11px] text-gray-600 leading-relaxed">
          No closed trades yet. The filter needs {state.min_samples} on a pair
          before it can block it.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-[#111827] border border-[#1e2433] rounded-lg py-2">
              <div className="text-[9px] text-gray-600 uppercase tracking-wider">Learning</div>
              <div className="text-sm font-bold text-gray-400">{learning.length}</div>
            </div>
            <div className="bg-[#111827] border border-green-500/20 rounded-lg py-2">
              <div className="text-[9px] text-gray-600 uppercase tracking-wider">Trading</div>
              <div className="text-sm font-bold text-green-400">{allowed.length}</div>
            </div>
            <div className="bg-[#111827] border border-red-500/20 rounded-lg py-2">
              <div className="text-[9px] text-gray-600 uppercase tracking-wider">Blocked</div>
              <div className="text-sm font-bold text-red-400">{blocked.length}</div>
            </div>
          </div>

          {blocked.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1 text-[10px] text-red-400/80 font-semibold">
                <Ban size={10} /> Paused — recent trades net-negative
              </div>
              <div className="space-y-1 max-h-32 overflow-y-auto">
                {blocked
                  .sort((a, b) => a[1].mean_r - b[1].mean_r)
                  .map(([p, v]) => (
                    <div key={p} className="flex items-center justify-between bg-red-500/5
                                            border border-red-500/15 rounded-lg px-2 py-1">
                      <span className="text-[11px] font-bold text-red-300">{p}</span>
                      <span className="text-[10px] font-mono text-red-400/70">
                        {v.mean_r >= 0 ? "+" : ""}{v.mean_r.toFixed(3)}R
                        <span className="text-gray-600"> · {v.wins}/{v.samples}W</span>
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {allowed.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1 text-[10px] text-green-400/80 font-semibold">
                <CheckCircle2 size={10} /> Trading
              </div>
              <div className="flex flex-wrap gap-1">
                {allowed
                  .sort((a, b) => b[1].mean_r - a[1].mean_r)
                  .map(([p, v]) => (
                    <span key={p}
                      className="text-[10px] px-1.5 py-0.5 rounded-md bg-green-500/10
                                 border border-green-500/20 text-green-300 font-mono">
                      {p} {v.mean_r >= 0 ? "+" : ""}{v.mean_r.toFixed(2)}R
                    </span>
                  ))}
              </div>
            </div>
          )}

          {learning.length > 0 && (
            <p className="text-[10px] text-gray-600 leading-relaxed">
              {learning.length} pair{learning.length === 1 ? "" : "s"} still
              gathering data ({state.min_samples} closed trades needed each).
            </p>
          )}
        </>
      )}
    </div>
  );
}
