import { useEffect, useState, useMemo } from "react";
import { createClient } from "@supabase/supabase-js";
import { useExchangeRate } from "@/hooks/useExchangeRate";

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

interface Props { mode: string; }

interface Trade {
  pnl: number;
  net_pnl: number;
  r_multiple: number;
  exit_time: string;
}

function Tile({ label, value, sub, color }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="bg-[#0a0d14] rounded-lg p-3">
      <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-bold font-mono ${color || "text-white"}`}>{value}</div>
      {sub && <div className="text-[10px] text-gray-600">{sub}</div>}
    </div>
  );
}

const IST_OFFSET = 5.5 * 60 * 60 * 1000; // UTC+5:30

export default function PerfStats({ mode }: Props) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const { fmtINR } = useExchangeRate();

  const fetchTrades = async () => {
    // IST midnight in UTC. Filtered on exit_time — P&L belongs to the day the
    // trade closed. The equity curve, heatmap and daily breakdown key off the
    // same field (Analytics.tsx `dayOf`), as does the backend performance table.
    const istMidnight = new Date(
      new Date(Date.now() + IST_OFFSET).toISOString().slice(0, 10) + "T00:00:00+05:30"
    ).toISOString();

    const { data } = await supabase
      .from("trades")
      .select("pnl, net_pnl, r_multiple, exit_time")
      .eq("mode", mode)
      .eq("status", "closed")
      .eq("is_shadow", false)   // shadow trades never move the day's numbers
      .gte("exit_time", istMidnight);

    setTrades((data as Trade[]) || []);
  };

  useEffect(() => {
    fetchTrades();
    const ch = supabase.channel("perf_live")
      .on("postgres_changes", { event: "*", schema: "public", table: "trades", filter: `mode=eq.${mode}` },
        fetchTrades)
      .subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [mode]);

  const perf = useMemo(() => {
    // Exclude crash_recovery (0 pnl, 0 r_multiple)
    const real = trades.filter(t => t.pnl !== 0 || t.r_multiple !== 0);
    const total  = real.length;
    const wins   = real.filter(t => t.pnl > 0).length;
    const losses = total - wins;
    const totalPnl = real.reduce((s, t) => s + (t.net_pnl || t.pnl || 0), 0);
    const totalR   = real.reduce((s, t) => s + (t.r_multiple || 0), 0);
    const avgR     = total > 0 ? Math.round((totalR / total) * 100) / 100 : 0;
    const winRate  = total > 0 ? Math.round((wins / total) * 100 * 10) / 10 : 0;
    const pnls     = real.map(t => t.net_pnl || t.pnl || 0);
    const best     = pnls.length > 0 ? Math.max(...pnls) : 0;
    const worst    = pnls.length > 0 ? Math.min(...pnls) : 0;
    return { total, wins, losses, totalPnl, avgR, winRate, best, worst };
  }, [trades]);

  const winColor =
    perf.winRate >= 60 ? "text-green-400" :
    perf.winRate >= 50 ? "text-yellow-400" : "text-red-400";

  return (
    <div className="bg-[#0f1117] border border-[#1e2433] rounded-xl p-4 space-y-3">
      <h2 className="text-white font-semibold text-sm uppercase tracking-wide">Today's Performance</h2>
      <div className="grid grid-cols-2 gap-2">
        <Tile label="Win Rate"
          value={perf.total > 0 ? `${perf.winRate.toFixed(1)}%` : "—"}
          sub={perf.total > 0 ? `${perf.wins}W / ${perf.losses}L` : ""}
          color={perf.total > 0 ? winColor : undefined} />
        <Tile label="Total Trades"
          value={perf.total > 0 ? `${perf.total}` : "—"}
          color="text-white" />
        <Tile label="Total P&L"
          value={perf.total > 0 ? `${perf.totalPnl >= 0 ? "+" : ""}${fmtINR(perf.totalPnl, 2)}` : "—"}
          color={perf.total > 0 ? (perf.totalPnl >= 0 ? "text-green-400" : "text-red-400") : undefined} />
        <Tile label="Avg R-Multiple"
          value={perf.total > 0 ? `${perf.avgR >= 0 ? "+" : ""}${perf.avgR.toFixed(2)}R` : "—"}
          color={perf.total > 0 ? (perf.avgR >= 0 ? "text-green-400" : "text-red-400") : undefined} />
        <Tile label="Best Trade"
          value={perf.best > 0 ? `+${fmtINR(perf.best, 2)}` : "—"}
          color="text-green-400" />
        <Tile label="Worst Trade"
          value={perf.worst < 0 ? `${fmtINR(perf.worst, 2)}` : "—"}
          color="text-red-400" />
      </div>
    </div>
  );
}
