import { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";
import { TrendingUp, TrendingDown } from "lucide-react";

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

const LAYERS = [
  { key: "trend_regime",    name: "Multi-TF Trend",  layer: 1 },
  { key: "cvd_divergence",  name: "CVD Divergence",  layer: 2 },
  { key: "vwap_deviation",  name: "VWAP Deviation",  layer: 3 },
  { key: "dom_imbalance",   name: "DOM Imbalance",   layer: 4 },
  { key: "rsi2_extreme",    name: "RSI Extreme",     layer: 5 },
  { key: "liquidity_sweep", name: "Liquidity Sweep", layer: 6 },
  { key: "fair_value_gap",  name: "Fair Value Gap",  layer: 7 },
];

interface LayerStat {
  key: string;
  name: string;
  layer: number;
  total: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_r: number;
}

interface ScoreStat {
  score: number;
  total: number;
  wins: number;
  win_rate: number;
  avg_r: number;
}

interface Props {
  mode: string;
}

export default function LayerStats({ mode }: Props) {
  const [layers, setLayers]   = useState<LayerStat[]>([]);
  const [scores, setScores]   = useState<ScoreStat[]>([]);
  const [loading, setLoading] = useState(true);

  const compute = async () => {
    const { data } = await supabase
      .from("trades")
      .select("pnl, r_multiple, signals_at_entry")
      .eq("mode", mode)
      .eq("status", "closed")
      .eq("is_shadow", false);   // shadow trades are recorded, never scored

    if (!data) return;

    // ── Layer stats ─────────────────────────────────────
    const layerMap: Record<string, { wins: number; losses: number; r_sum: number }> = {};
    LAYERS.forEach((l) => { layerMap[l.key] = { wins: 0, losses: 0, r_sum: 0 }; });

    // ── Score stats ──────────────────────────────────────
    const scoreMap: Record<number, { wins: number; losses: number; r_sum: number }> = {};

    data.forEach((t: any) => {
      const sig  = t.signals_at_entry || {};
      const pnl  = t.pnl ?? 0;
      const r    = t.r_multiple ?? 0;
      const won  = pnl > 0;

      LAYERS.forEach((l) => {
        if (sig[l.key] === 1) {
          layerMap[l.key].r_sum += r;
          if (won) layerMap[l.key].wins++;
          else     layerMap[l.key].losses++;
        }
      });

      const score = Number(sig.total_score);
      if (score >= 1) {
        if (!scoreMap[score]) scoreMap[score] = { wins: 0, losses: 0, r_sum: 0 };
        scoreMap[score].r_sum += r;
        if (won) scoreMap[score].wins++;
        else     scoreMap[score].losses++;
      }
    });

    const layerStats: LayerStat[] = LAYERS.map((l) => {
      const s     = layerMap[l.key];
      const total = s.wins + s.losses;
      return {
        ...l,
        total,
        wins:     s.wins,
        losses:   s.losses,
        win_rate: total > 0 ? Math.round((s.wins / total) * 100) : 0,
        avg_r:    total > 0 ? Math.round((s.r_sum / total) * 100) / 100 : 0,
      };
    }).sort((a, b) => b.win_rate - a.win_rate || b.total - a.total);

    const scoreStats: ScoreStat[] = Object.entries(scoreMap)
      .map(([score, s]) => {
        const total = s.wins + s.losses;
        return {
          score:    Number(score),
          total,
          wins:     s.wins,
          win_rate: total > 0 ? Math.round((s.wins / total) * 100) : 0,
          avg_r:    total > 0 ? Math.round((s.r_sum / total) * 100) / 100 : 0,
        };
      })
      .sort((a, b) => b.score - a.score);

    setLayers(layerStats);
    setScores(scoreStats);
    setLoading(false);
  };

  useEffect(() => {
    compute();
    const channel = supabase
      .channel("layer_stats_watch")
      .on("postgres_changes", { event: "*", schema: "public", table: "trades", filter: `mode=eq.${mode}` },
        () => compute())
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [mode]);

  if (loading) return null;
  if (layers.every((l) => l.total === 0)) return null;

  return (
    <div className="space-y-3">

      {/* Layer Rankings */}
      <div className="bg-[#0d1117] border border-[#1e2433] rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#1e2433]">
          <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">
            Signal Layer Performance
          </span>
          <span className="text-[10px] text-gray-600">ranked by win rate</span>
        </div>

        <div className="divide-y divide-[#1a2030]">
          {layers.map((l, i) => {
            if (l.total === 0) return null;
            const good = l.win_rate >= 50;
            return (
              <div key={l.key} className="px-4 py-2.5 flex items-center gap-3">
                {/* Rank */}
                <span className={`text-[10px] font-black w-4 flex-shrink-0 ${
                  i === 0 ? "text-yellow-400" : i === 1 ? "text-gray-300" : i === 2 ? "text-amber-600" : "text-gray-600"
                }`}>
                  #{i + 1}
                </span>

                {/* Layer info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-gray-500 font-mono">L{l.layer}</span>
                      <span className="text-xs font-semibold text-white">{l.name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-gray-600">
                        {l.wins}W/{l.losses}L
                      </span>
                      <span className={`text-xs font-bold ${good ? "text-green-400" : "text-red-400"}`}>
                        {l.win_rate}%
                      </span>
                    </div>
                  </div>
                  {/* Win rate bar */}
                  <div className="h-1 bg-[#1a2030] rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${good ? "bg-green-500" : "bg-red-500"}`}
                      style={{ width: `${l.win_rate}%` }}
                    />
                  </div>
                </div>

                {/* Avg R */}
                <div className="text-right flex-shrink-0 w-14">
                  <div className="text-[10px] text-gray-600">Avg R</div>
                  <div className={`text-xs font-bold font-mono ${l.avg_r >= 0 ? "text-indigo-400" : "text-red-400"}`}>
                    {l.avg_r >= 0 ? "+" : ""}{l.avg_r}R
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Score Analysis */}
      {scores.length > 0 && (
        <div className="bg-[#0d1117] border border-[#1e2433] rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#1e2433]">
            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">
              Score vs Win Rate
            </span>
            <span className="text-[10px] text-gray-600">higher score = ?</span>
          </div>
          <div className="px-4 py-3 flex gap-2 flex-wrap">
            {scores.map((s) => {
              const good = s.win_rate >= 50;
              return (
                <div key={s.score}
                  className={`flex-1 min-w-[80px] rounded-lg p-2.5 border ${
                    good
                      ? "bg-green-500/5 border-green-500/20"
                      : "bg-red-500/5 border-red-500/20"
                  }`}>
                  <div className="text-[10px] text-gray-500 mb-0.5">{s.score}/7 score</div>
                  <div className={`text-lg font-black ${good ? "text-green-400" : "text-red-400"}`}>
                    {s.win_rate}%
                  </div>
                  <div className="text-[10px] text-gray-600">{s.total} trades</div>
                  <div className={`text-[10px] font-mono mt-0.5 ${s.avg_r >= 0 ? "text-indigo-400" : "text-red-400"}`}>
                    avg {s.avg_r >= 0 ? "+" : ""}{s.avg_r}R
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
