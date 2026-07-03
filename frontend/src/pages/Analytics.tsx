import { useEffect, useState, useMemo } from "react";
import { useBotSocketContext } from "@/hooks/BotSocketContext";
import { createClient } from "@supabase/supabase-js";
import { useExchangeRate } from "@/hooks/useExchangeRate";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Cell, ComposedChart, Line,
} from "recharts";
import {
  TrendingUp, TrendingDown, Target, Zap,
  Trophy, AlertTriangle, CheckCircle, Info,
  BarChart2, Activity, Clock, Coins,
} from "lucide-react";

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

const LAYER_KEYS = [
  { key: "trend_regime",    label: "L1", name: "Multi-TF Trend"  },
  { key: "cvd_divergence",  label: "L2", name: "CVD Divergence"  },
  { key: "vwap_deviation",  label: "L3", name: "VWAP Deviation"  },
  { key: "dom_imbalance",   label: "L4", name: "DOM Imbalance"   },
  { key: "rsi2_extreme",    label: "L5", name: "RSI Extreme"     },
  { key: "liquidity_sweep", label: "L6", name: "Liquidity Sweep" },
  { key: "fair_value_gap",  label: "L7", name: "Fair Value Gap"  },
];

interface Trade {
  pnl: number;
  net_pnl: number;
  r_multiple: number;
  fee: number;
  signals_at_entry: any;
  pair: string;
  direction: string;
  exit_reason: string;
  created_at: string;
  style: string;
  signal_score: number;
}

function winRate(wins: number, total: number) {
  return total > 0 ? Math.round((wins / total) * 100) : 0;
}
function avgR(rSum: number, total: number) {
  return total > 0 ? Math.round((rSum / total) * 100) / 100 : 0;
}

const exitLabel: Record<string, string> = {
  sl: "Stop Loss", tp: "Take Profit", trailing: "Trailing SL",
  "2r_target": "2R Target", "3r_target": "3R Target",
  "4r_target": "4R Target", breakeven: "Breakeven", manual: "Manual",
};

// Custom tooltip for charts
function ChartTooltip({ active, payload, label, fmt }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#0d1117] border border-[#2a3045] rounded-lg px-3 py-2 text-xs shadow-xl">
      <div className="text-gray-400 mb-1">{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color }} className="font-bold font-mono">
          {fmt ? fmt(p.value) : p.value}
        </div>
      ))}
    </div>
  );
}

export default function Analytics() {
  const { state } = useBotSocketContext();
  const [mode, setMode]                   = useState<"demo" | "live">("demo");
  const [trades, setTrades]               = useState<Trade[]>([]);
  const [loading, setLoading]             = useState(true);
  const [traders, setTraders]             = useState<string[]>([]);
  const [selectedTrader, setSelectedTrader] = useState<string | null>("Version-2.0");
  const [equityPeriod, setEquityPeriod]   = useState<string>("All");
  const [hourlyPeriod, setHourlyPeriod]   = useState<string>("All");
  const [heatmapPeriod, setHeatmapPeriod] = useState<string>("6M");
  const [dailyVisible, setDailyVisible]   = useState<number>(15);
  const { fmtINR } = useExchangeRate();

  useEffect(() => {
    const isMobile = window.innerWidth < 640;
    setHeatmapPeriod(isMobile ? "3M" : "1Y");
  }, []);

  // Auto-sync with bot mode (live/demo) whenever it changes
  useEffect(() => {
    if (state.mode === "live" || state.mode === "demo") {
      setMode(state.mode as "demo" | "live");
    }
  }, [state.mode]);

  const PERIODS = ["1D", "7D", "1M", "3M", "6M", "9M", "1Y", "All"];

  const periodDays: Record<string, number> = {
    "1D": 1, "7D": 7, "1M": 30, "3M": 90,
    "6M": 180, "9M": 270, "1Y": 365,
  };

  const fetchTraders = async (m: string) => {
    const { data } = await supabase
      .from("trades")
      .select("trader_name")
      .eq("mode", m)
      .eq("status", "closed")
      .not("trader_name", "is", null);
    if (data) {
      const unique = [...new Set(
        (data as { trader_name: string }[]).map((t) => t.trader_name).filter(Boolean)
      )];
      setTraders(unique);
    }
  };

  const fetchTrades = async (m: string, traderFilter: string | null = null) => {
    setLoading(true);
    let query = supabase
      .from("trades")
      .select("pnl, net_pnl, r_multiple, fee, signals_at_entry, pair, direction, exit_reason, created_at, style, signal_score")
      .eq("mode", m).eq("status", "closed")
      .order("created_at", { ascending: true })
      .limit(2000);
    if (traderFilter) query = query.eq("trader_name", traderFilter);
    const { data } = await query;
    setTrades((data as Trade[]) || []);
    setLoading(false);
  };

  const handleTraderSelect = (trader: string | null) => {
    setSelectedTrader(trader);
    fetchTrades(mode, trader);
  };

  useEffect(() => {
    fetchTrades(mode, selectedTrader);
    fetchTraders(mode);
  }, [mode]);

  useEffect(() => {
    const chName = `analytics_watch_${mode}_${selectedTrader ?? "all"}_${Date.now()}`;
    const ch = supabase.channel(chName)
      .on("postgres_changes", { event: "*", schema: "public", table: "trades", filter: `mode=eq.${mode}` },
        () => { fetchTrades(mode, selectedTrader); fetchTraders(mode); }).subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [mode, selectedTrader]);

  // ── Compute all stats ──────────────────────────────────────
  const stats = useMemo(() => {
    const IST_OFFSET = 5.5 * 60 * 60 * 1000;
    const total = trades.length;
    const wins  = trades.filter(t => t.pnl > 0).length;
    const totalPnl = trades.reduce((s, t) => s + (t.net_pnl || t.pnl || 0), 0);
    const totalR   = trades.reduce((s, t) => s + (t.r_multiple || 0), 0);
    const totalFees = trades.reduce((s, t) => s + (t.fee || 0), 0);
    const wr = winRate(wins, total);
    const ar = avgR(totalR, total);

    // Equity curve
    let running = 0;
    const equity = trades.map((t, i) => {
      running += t.net_pnl || t.pnl || 0;
      return { i: i + 1, pnl: Math.round(running * 100) / 100 };
    });

    // By pair
    const pairMap: Record<string, { wins: number; losses: number; total: number; rSum: number; pnl: number }> = {};
    trades.forEach(t => {
      if (!pairMap[t.pair]) pairMap[t.pair] = { wins: 0, losses: 0, total: 0, rSum: 0, pnl: 0 };
      pairMap[t.pair].total++;
      pairMap[t.pair].pnl += t.pnl || 0;
      pairMap[t.pair].rSum += t.r_multiple || 0;
      if (t.pnl > 0) pairMap[t.pair].wins++;
      else pairMap[t.pair].losses++;
    });
    const pairStats = Object.entries(pairMap).map(([pair, s]) => ({
      pair, ...s, wr: winRate(s.wins, s.total), ar: avgR(s.rSum, s.total),
    })).sort((a, b) => b.pnl - a.pnl);

    // Direction
    const dirMap: Record<string, { wins: number; total: number; rSum: number }> = {
      long: { wins:0,total:0,rSum:0 }, short: { wins:0,total:0,rSum:0 }
    };
    trades.forEach(t => {
      if (!dirMap[t.direction]) return;
      dirMap[t.direction].total++;
      dirMap[t.direction].rSum += t.r_multiple || 0;
      if (t.pnl > 0) dirMap[t.direction].wins++;
    });

    // Exit reasons
    const exitMap: Record<string, { total: number; rSum: number; wins: number }> = {};
    trades.forEach(t => {
      const r = t.exit_reason || "unknown";
      if (!exitMap[r]) exitMap[r] = { total: 0, rSum: 0, wins: 0 };
      exitMap[r].total++;
      exitMap[r].rSum += t.r_multiple || 0;
      if (t.pnl > 0) exitMap[r].wins++;
    });
    const exitStats = Object.entries(exitMap).map(([reason, s]) => ({
      reason, name: exitLabel[reason] || reason, ...s,
      wr: winRate(s.wins, s.total), ar: avgR(s.rSum, s.total),
    })).sort((a, b) => b.total - a.total);

    // Score map
    const scoreMap: Record<number, { wins: number; total: number; rSum: number }> = {};
    trades.forEach(t => {
      const sc = Number(t.signal_score || t.signals_at_entry?.total_score);
      if (!sc) return;
      if (!scoreMap[sc]) scoreMap[sc] = { wins: 0, total: 0, rSum: 0 };
      scoreMap[sc].total++;
      scoreMap[sc].rSum += t.r_multiple || 0;
      if (t.pnl > 0) scoreMap[sc].wins++;
    });
    const scoreData = Object.entries(scoreMap)
      .sort((a, b) => Number(a[0]) - Number(b[0]))
      .map(([sc, s]) => ({ sc: `${sc}/7`, wr: winRate(s.wins, s.total), total: s.total, ar: avgR(s.rSum, s.total) }));

    // Layer combos
    const comboMap: Record<string, { wins: number; total: number; rSum: number }> = {};
    trades.forEach(t => {
      const sig = t.signals_at_entry || {};
      const layers = LAYER_KEYS.filter(l => sig[l.key] === 1).map(l => l.label);
      if (!layers.length) return;
      const key = layers.join("+");
      if (!comboMap[key]) comboMap[key] = { wins: 0, total: 0, rSum: 0 };
      comboMap[key].total++;
      comboMap[key].rSum += t.r_multiple || 0;
      if (t.pnl > 0) comboMap[key].wins++;
    });
    const comboStats = Object.entries(comboMap).map(([combo, s]) => ({
      combo, layers: combo.split("+"), ...s,
      wr: winRate(s.wins, s.total), ar: avgR(s.rSum, s.total),
      quality: winRate(s.wins, s.total) * Math.min(1, s.total / 5),
    })).sort((a, b) => b.quality - a.quality).slice(0, 12);

    // Insights
    const insights: { type: "good" | "warn" | "info"; text: string }[] = [];
    if (total >= 5) {
      const bestPair = pairStats[0];
      const worstPair = [...pairStats].sort((a,b) => a.wr - b.wr)[0];
      if (bestPair && bestPair.wr >= 60) insights.push({ type: "good", text: `${bestPair.pair} is your best pair — ${bestPair.wr}% win rate, avg ${bestPair.ar}R` });
      if (worstPair && worstPair.wr <= 30 && worstPair.total >= 3) insights.push({ type: "warn", text: `${worstPair.pair} dragging performance — ${worstPair.wr}% win rate across ${worstPair.total} trades` });
      const longWr = winRate(dirMap.long.wins, dirMap.long.total);
      const shortWr = winRate(dirMap.short.wins, dirMap.short.total);
      if (dirMap.long.total >= 3 && dirMap.short.total >= 3) {
        if (longWr > shortWr + 15) insights.push({ type: "info", text: `Longs outperforming shorts (${longWr}% vs ${shortWr}%) — focus on long setups` });
        else if (shortWr > longWr + 15) insights.push({ type: "info", text: `Shorts outperforming longs (${shortWr}% vs ${longWr}%) — focus on short setups` });
      }
      if (wr < 40 && total >= 10) insights.push({ type: "warn", text: `Win rate ${wr}% is below 40% — consider raising MIN_SIGNAL_SCORE to 5` });
      if (ar < 0 && total >= 5) insights.push({ type: "warn", text: `Average R is negative (${ar}R) — SL exits outweigh profits` });
      const bestCombo = comboStats[0];
      if (bestCombo && bestCombo.wr >= 65 && bestCombo.total >= 3) insights.push({ type: "good", text: `Best combo ${bestCombo.combo} — ${bestCombo.wr}% win rate (${bestCombo.total} trades)` });
    }

    return { total, wins, totalPnl, totalFees, wr, ar, equity, pairStats, dirMap, exitStats, scoreData, comboStats, insights };
  }, [trades]);

  const equityUp = stats.totalPnl >= 0;
  const [hoveredDay, setHoveredDay] = useState<{ date: string; pnl: number; x: number; y: number } | null>(null);

  // ── Hourly data (depends on period filter) ────────────────
  const hourlyData = useMemo(() => {
    const IST_MS = 5.5 * 60 * 60 * 1000;
    const nowMs  = Date.now();

    // Filter trades by selected period
    let filtered = trades;
    if (hourlyPeriod !== "All") {
      let startMs: number;
      if (hourlyPeriod === "1D") {
        // IST midnight today
        const istNow = new Date(nowMs + IST_MS);
        startMs = new Date(`${istNow.toISOString().slice(0, 10)}T00:00:00+05:30`).getTime();
      } else {
        const days = periodDays[hourlyPeriod] || 0;
        startMs = nowMs - days * 86400000;
      }
      filtered = trades.filter(t => new Date(t.created_at).getTime() >= startMs);
    }

    // Bucket into 24 hours (IST)
    const hourMap: Record<number, { wins: number; losses: number; total: number; profit: number; loss: number; rSum: number }> = {};
    for (let h = 0; h < 24; h++) hourMap[h] = { wins: 0, losses: 0, total: 0, profit: 0, loss: 0, rSum: 0 };

    filtered.forEach(t => {
      if (!t.created_at) return;
      const hour = (new Date(new Date(t.created_at).getTime() + IST_MS)).getUTCHours();
      const pnl  = t.net_pnl || t.pnl || 0;
      hourMap[hour].total++;
      hourMap[hour].rSum += t.r_multiple || 0;
      if (pnl > 0) { hourMap[hour].wins++;   hourMap[hour].profit += pnl; }
      else         { hourMap[hour].losses++; hourMap[hour].loss   += Math.abs(pnl); }
    });

    return Array.from({ length: 24 }, (_, h) => {
      const s = hourMap[h];
      const label = h === 0 ? "12am" : h < 12 ? `${h}am` : h === 12 ? "12pm" : `${h - 12}pm`;
      return {
        hour:   h,
        label,
        total:  s.total,
        profit: +(s.profit.toFixed(2)),
        loss:   +((-s.loss).toFixed(2)),
        wr:     winRate(s.wins, s.total),
        ar:     avgR(s.rSum, s.total),
        wins:   s.wins,
        losses: s.losses,
      };
    });
  }, [trades, hourlyPeriod]);

  // ── Trade Heatmap ─────────────────────────────────────────
  const IST_OFFSET = 5.5 * 60 * 60 * 1000; // UTC+5:30 in ms

  const heatmapData = useMemo(() => {
    // Group trades by IST date → daily net PnL
    const dayMap: Record<string, number> = {};
    trades.forEach(t => {
      if (!t.created_at) return;
      // Convert UTC timestamp to IST date
      const day = new Date(new Date(t.created_at).getTime() + IST_OFFSET)
        .toISOString().slice(0, 10);
      dayMap[day] = (dayMap[day] || 0) + (t.net_pnl || t.pnl || 0);
    });

    // Build 52-week grid ending today (IST)
    const today = new Date(Date.now() + IST_OFFSET);
    today.setHours(0, 0, 0, 0);
    // Start from Sunday 52 weeks ago
    const start = new Date(today);
    start.setDate(start.getDate() - 364);
    // Align to Sunday
    start.setDate(start.getDate() - start.getDay());

    const weeks: { date: string; pnl: number | null }[][] = [];
    const cur = new Date(start);

    while (cur <= today) {
      const week: { date: string; pnl: number | null }[] = [];
      for (let d = 0; d < 7; d++) {
        // Use IST date for cell key (add offset then take date part)
        const iso = new Date(cur.getTime() + IST_OFFSET).toISOString().slice(0, 10);
        week.push({ date: iso, pnl: dayMap[iso] ?? null });
        cur.setDate(cur.getDate() + 1);
      }
      weeks.push(week);
    }

    // Max abs PnL for intensity scaling
    const vals = Object.values(dayMap).map(Math.abs);
    const maxPnl = vals.length > 0 ? Math.max(...vals) : 1;

    return { weeks, maxPnl, dayMap };
  }, [trades]);

  function heatColor(pnl: number | null, maxPnl: number): string {
    if (pnl === null) return "#111827";          // no trade
    if (Math.abs(pnl) < 0.01) return "#1a2035"; // ~zero
    const intensity = Math.min(Math.abs(pnl) / maxPnl, 1);
    if (pnl > 0) {
      // green: light → dark
      if (intensity < 0.25) return "#14532d";
      if (intensity < 0.50) return "#16a34a";
      if (intensity < 0.75) return "#22c55e";
      return "#4ade80";
    } else {
      // red: light → dark
      if (intensity < 0.25) return "#450a0a";
      if (intensity < 0.50) return "#b91c1c";
      if (intensity < 0.75) return "#ef4444";
      return "#f87171";
    }
  }

  // Daily stats breakdown
  const dailyStats = useMemo(() => {
    const dayMap: Record<string, { total: number; wins: number; losses: number; pnl: number; rSum: number }> = {};
    trades.forEach(t => {
      if (!t.created_at) return;
      const day = new Date(new Date(t.created_at).getTime() + IST_OFFSET)
        .toISOString().slice(0, 10);
      if (!dayMap[day]) dayMap[day] = { total: 0, wins: 0, losses: 0, pnl: 0, rSum: 0 };
      dayMap[day].total++;
      dayMap[day].pnl += t.net_pnl || t.pnl || 0;
      dayMap[day].rSum += t.r_multiple || 0;
      if ((t.net_pnl || t.pnl || 0) > 0) dayMap[day].wins++;
      else dayMap[day].losses++;
    });
    return Object.entries(dayMap)
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([date, s]) => ({
        date,
        ...s,
        wr: winRate(s.wins, s.total),
        ar: avgR(s.rSum, s.total),
      }));
  }, [trades]);

  // Filtered equity for selected period
  const filteredEquity = useMemo(() => {
    const days = periodDays[equityPeriod];

    // For 1D: use IST midnight (same as PerfStats) so both match
    // For other periods: rolling window from now
    const getStart = () => {
      if (equityPeriod === "1D") {
        return new Date(
          new Date(Date.now() + IST_OFFSET).toISOString().slice(0, 10) + "T00:00:00+05:30"
        ).getTime();
      }
      return days ? Date.now() - days * 86400000 : 0;
    };
    const startMs = getStart();

    const filtered = days || equityPeriod === "1D"
      ? trades.filter(t => new Date(t.created_at).getTime() >= startMs)
      : trades;
    let running = 0;
    return filtered.map((t, i) => {
      running += t.net_pnl || t.pnl || 0;
      return { i: i + 1, pnl: Math.round(running * 100) / 100 };
    });
  }, [trades, equityPeriod]);

  const filteredPnl = filteredEquity.length > 0 ? filteredEquity[filteredEquity.length - 1].pnl : 0;
  const filteredUp  = filteredPnl >= 0;

  // Zero-crossing gradient: green above 0, red below 0
  const equityMin = filteredEquity.length > 0 ? Math.min(...filteredEquity.map(d => d.pnl)) : 0;
  const equityMax = filteredEquity.length > 0 ? Math.max(...filteredEquity.map(d => d.pnl)) : 1;
  const equityRange = equityMax - equityMin || 1;
  // Percentage from top where zero line sits (0% = top, 100% = bottom)
  const zeroPct = equityMax > 0 ? `${Math.min(100, Math.max(0, (equityMax / equityRange) * 100)).toFixed(1)}%` : "0%";

  return (
    <main className="flex-1 overflow-y-auto bg-[#07090f]">

        {/* ── Page Header ─────────────────────────────── */}
        <div className="border-b border-[#1a2030] bg-[#070a10]/80 backdrop-blur-sm sticky top-0 z-10">
          <div className="px-4 py-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center flex-shrink-0">
                <BarChart2 size={15} className="text-indigo-400" />
              </div>
              <div className="min-w-0">
                <h1 className="text-base font-bold text-white leading-tight">Trade Analytics</h1>
                <p className="text-[10px] text-gray-500 hidden sm:block">Performance breakdown · signal quality · edge analysis</p>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {traders.length > 1 && (
                <select
                  value={selectedTrader ?? ""}
                  onChange={(e) => handleTraderSelect(e.target.value || null)}
                  className="bg-[#0d1117] border border-[#1e2433] text-xs text-gray-300 rounded-lg px-2 py-1.5
                             outline-none focus:border-indigo-500/60 cursor-pointer transition-colors max-w-[110px] sm:max-w-none"
                >
                  <option value="">All Traders</option>
                  {traders.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              )}
              <div className="flex gap-1 bg-[#0d1117] border border-[#1e2433] rounded-lg p-1">
                {(["demo", "live"] as const).map(m => (
                  <button key={m} onClick={() => setMode(m)}
                    className={`px-3 sm:px-4 py-1.5 rounded text-xs font-bold transition-all ${
                      mode === m
                        ? m === "live"
                          ? "bg-red-500/20 text-red-300 border border-red-500/40"
                          : "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40"
                        : "text-gray-500 hover:text-gray-300"
                    }`}>{m.toUpperCase()}</button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin" />
              <span className="text-gray-600 text-xs">Loading trades...</span>
            </div>
          </div>
        ) : stats.total === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <Activity size={32} className="text-gray-700" />
            <span className="text-gray-600 text-sm">No closed trades in {mode} mode yet</span>
          </div>
        ) : (
          <div className="p-4 space-y-4">

            {/* ── KPI Hero Cards ──────────────────────────── */}
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">

              {/* Total Trades */}
              <div className="relative bg-[#0d1117] border border-[#1e2433] rounded-2xl p-5 group hover:border-indigo-500/40 transition-colors duration-300 min-h-[130px]">
                <div className="absolute top-0 left-0 right-0 h-[2px] rounded-t-2xl bg-gradient-to-r from-transparent via-indigo-500/70 to-transparent" />
                <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-indigo-500/[0.06] via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                <div className="relative">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-[10px] text-gray-500 uppercase tracking-widest font-bold">Total Trades</span>
                    <div className="w-8 h-8 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center group-hover:bg-indigo-500/20 transition-colors duration-300">
                      <Zap size={14} className="text-indigo-400" />
                    </div>
                  </div>
                  <div className="text-4xl font-black text-white tracking-tight">{stats.total}</div>
                  <div className="flex items-center gap-2 mt-2.5">
                    <span className="text-[11px] font-bold text-green-400 bg-green-500/10 px-1.5 py-0.5 rounded">{stats.wins}W</span>
                    <span className="text-gray-700 text-xs">·</span>
                    <span className="text-[11px] font-bold text-red-400 bg-red-500/10 px-1.5 py-0.5 rounded">{stats.total - stats.wins}L</span>
                  </div>
                </div>
              </div>

              {/* Win Rate */}
              <div className={`relative bg-[#0d1117] border border-[#1e2433] rounded-2xl p-5 group min-h-[130px] ${stats.wr >= 50 ? "hover:border-green-500/40" : "hover:border-red-500/40"} transition-colors duration-300`}>
                <div className={`absolute top-0 left-0 right-0 h-[2px] rounded-t-2xl bg-gradient-to-r from-transparent ${stats.wr >= 50 ? "via-green-500/70" : "via-red-500/70"} to-transparent`} />
                <div className={`absolute inset-0 rounded-2xl bg-gradient-to-br ${stats.wr >= 50 ? "from-green-500/[0.06]" : "from-red-500/[0.06]"} via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
                <div className="relative">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-[10px] text-gray-500 uppercase tracking-widest font-bold">Win Rate</span>
                    <div className={`w-8 h-8 rounded-xl flex items-center justify-center border transition-colors duration-300 ${stats.wr >= 50 ? "bg-green-500/10 border-green-500/20 group-hover:bg-green-500/20" : "bg-red-500/10 border-red-500/20 group-hover:bg-red-500/20"}`}>
                      <Target size={14} className={stats.wr >= 50 ? "text-green-400" : "text-red-400"} />
                    </div>
                  </div>
                  <div className={`text-4xl font-black tracking-tight ${stats.wr >= 50 ? "text-green-400" : "text-red-400"}`}>{stats.wr}%</div>
                  <div className="mt-3 h-1.5 bg-[#1a2030] rounded-full overflow-hidden">
                    <div className={`h-full rounded-full transition-all duration-700 ${stats.wr >= 50 ? "bg-gradient-to-r from-green-600 to-green-400" : "bg-gradient-to-r from-red-700 to-red-500"}`}
                      style={{ width: `${stats.wr}%` }} />
                  </div>
                </div>
              </div>

              {/* Avg R */}
              <div className={`relative bg-[#0d1117] border border-[#1e2433] rounded-2xl p-5 group min-h-[130px] ${stats.ar >= 0 ? "hover:border-purple-500/40" : "hover:border-red-500/40"} transition-colors duration-300`}>
                <div className={`absolute top-0 left-0 right-0 h-[2px] rounded-t-2xl bg-gradient-to-r from-transparent ${stats.ar >= 0 ? "via-purple-500/70" : "via-red-500/70"} to-transparent`} />
                <div className={`absolute inset-0 rounded-2xl bg-gradient-to-br ${stats.ar >= 0 ? "from-purple-500/[0.06]" : "from-red-500/[0.06]"} via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
                <div className="relative">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-[10px] text-gray-500 uppercase tracking-widest font-bold">Avg R</span>
                    <div className={`w-8 h-8 rounded-xl flex items-center justify-center border transition-colors duration-300 ${stats.ar >= 0 ? "bg-purple-500/10 border-purple-500/20 group-hover:bg-purple-500/20" : "bg-red-500/10 border-red-500/20 group-hover:bg-red-500/20"}`}>
                      <TrendingUp size={14} className={stats.ar >= 0 ? "text-purple-400" : "text-red-400"} />
                    </div>
                  </div>
                  <div className={`text-4xl font-black tracking-tight ${stats.ar >= 0 ? "text-purple-400" : "text-red-400"}`}>
                    {stats.ar >= 0 ? "+" : ""}{stats.ar}R
                  </div>
                  <div className="text-[11px] text-gray-600 mt-2.5">per trade average</div>
                </div>
              </div>

              {/* Net P&L */}
              <div className={`relative bg-[#0d1117] border border-[#1e2433] rounded-2xl p-5 group min-h-[130px] ${equityUp ? "hover:border-green-500/40" : "hover:border-red-500/40"} transition-colors duration-300`}>
                <div className={`absolute top-0 left-0 right-0 h-[2px] rounded-t-2xl bg-gradient-to-r from-transparent ${equityUp ? "via-green-500/70" : "via-red-500/70"} to-transparent`} />
                <div className={`absolute inset-0 rounded-2xl bg-gradient-to-br ${equityUp ? "from-green-500/[0.06]" : "from-red-500/[0.06]"} via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
                <div className="relative">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-[10px] text-gray-500 uppercase tracking-widest font-bold">Net P&L</span>
                    <div className={`w-8 h-8 rounded-xl flex items-center justify-center border transition-colors duration-300 ${equityUp ? "bg-green-500/10 border-green-500/20 group-hover:bg-green-500/20" : "bg-red-500/10 border-red-500/20 group-hover:bg-red-500/20"}`}>
                      {equityUp ? <TrendingUp size={14} className="text-green-400" /> : <TrendingDown size={14} className="text-red-400" />}
                    </div>
                  </div>
                  <div className={`text-3xl font-black tracking-tight leading-none ${equityUp ? "text-green-400" : "text-red-400"}`}>
                    {equityUp ? "+" : ""}{fmtINR(stats.totalPnl, 0)}
                  </div>
                  <div className="text-[11px] text-gray-600 mt-2.5">after all fees</div>
                </div>
              </div>

              {/* Total Fees */}
              <div className="relative bg-[#0d1117] border border-[#1e2433] rounded-2xl p-5 group hover:border-amber-500/40 transition-colors duration-300 min-h-[130px]">
                <div className="absolute top-0 left-0 right-0 h-[2px] rounded-t-2xl bg-gradient-to-r from-transparent via-amber-500/70 to-transparent" />
                <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-amber-500/[0.06] via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                <div className="relative">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-[10px] text-gray-500 uppercase tracking-widest font-bold">Total Fees</span>
                    <div className="w-8 h-8 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center group-hover:bg-amber-500/20 transition-colors duration-300">
                      <Coins size={14} className="text-amber-400" />
                    </div>
                  </div>
                  <div className="text-3xl font-black tracking-tight leading-none text-amber-400">
                    {fmtINR(stats.totalFees, 0)}
                  </div>
                  <div className="text-[11px] text-gray-600 mt-2.5">
                    ~{fmtINR(stats.total > 0 ? stats.totalFees / stats.total : 0, 0)} per trade
                  </div>
                </div>
              </div>

            </div>

            {/* ── Equity Curve ────────────────────────────── */}
            <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
              {/* Header */}
              <div className="px-5 py-4 border-b border-[#1e2433] flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <Activity size={14} className="text-indigo-400" />
                  <span className="text-sm font-bold text-white">Equity Curve</span>
                  <span className={`text-xs font-bold font-mono px-2.5 py-1 rounded-lg ${
                    filteredUp ? "bg-green-500/10 text-green-400 border border-green-500/20" : "bg-red-500/10 text-red-400 border border-red-500/20"
                  }`}>
                    {filteredUp ? "+" : ""}{fmtINR(filteredPnl, 0)}
                  </span>
                </div>
                {/* Period filter buttons */}
                <div className="flex gap-1 bg-[#080b12] border border-[#1e2433] rounded-lg p-1">
                  {PERIODS.map(p => (
                    <button key={p} onClick={() => setEquityPeriod(p)}
                      className={`px-2.5 py-1 rounded text-[10px] font-bold transition-all ${
                        equityPeriod === p
                          ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40"
                          : "text-gray-600 hover:text-gray-400"
                      }`}>
                      {p}
                    </button>
                  ))}
                </div>
              </div>
              {/* Chart */}
              <div className="p-4 h-52 sm:h-72 md:h-96">
                {filteredEquity.length === 0 ? (
                  <div className="flex items-center justify-center h-full text-gray-600 text-xs">
                    No trades in this period
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={filteredEquity} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
                      <defs>
                        <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                          {/* Green above zero, red below zero */}
                          <stop offset="0%"       stopColor="#22c55e" stopOpacity={0.35} />
                          <stop offset={zeroPct}  stopColor="#22c55e" stopOpacity={0.05} />
                          <stop offset={zeroPct}  stopColor="#ef4444" stopOpacity={0.05} />
                          <stop offset="100%"     stopColor="#ef4444" stopOpacity={0.35} />
                        </linearGradient>
                        <linearGradient id="strokeGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%"      stopColor="#22c55e" stopOpacity={1} />
                          <stop offset={zeroPct} stopColor="#22c55e" stopOpacity={1} />
                          <stop offset={zeroPct} stopColor="#ef4444" stopOpacity={1} />
                          <stop offset="100%"    stopColor="#ef4444" stopOpacity={1} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="i" hide />
                      <YAxis hide />
                      <Tooltip content={<ChartTooltip fmt={(v: number) => fmtINR(v)} />} />
                      <Area
                        type="monotone" dataKey="pnl"
                        stroke="url(#strokeGrad)"
                        strokeWidth={2}
                        fill="url(#pnlGrad)"
                        dot={false} activeDot={{ r: 4, fill: filteredUp ? "#22c55e" : "#ef4444" }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>

            {/* ── Trade Heatmap ───────────────────────────── */}
            <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden relative">
              {/* Header */}
              <div className="px-4 py-3 border-b border-[#1e2433] flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <Activity size={14} className="text-indigo-400" />
                  <span className="text-sm font-bold text-white">Daily P&L Heatmap</span>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  {/* Period switcher */}
                  <div className="flex gap-1 bg-[#080b12] border border-[#1e2433] rounded-lg p-1">
                    {["1M","3M","6M","1Y","All"].map(p => (
                      <button key={p} onClick={() => setHeatmapPeriod(p)}
                        className={`px-2 py-1 rounded text-[10px] font-bold transition-all ${
                          heatmapPeriod === p
                            ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40"
                            : "text-gray-600 hover:text-gray-400"
                        }`}>
                        {p}
                      </button>
                    ))}
                  </div>
                  {/* Legend */}
                  <div className="flex items-center gap-1.5 text-[10px] text-gray-500 font-medium">
                    <span>Loss</span>
                    {["#b91c1c","#ef4444","#1a2035","#16a34a","#4ade80"].map((c,i) => (
                      <div key={i} className="w-3 h-3 rounded-sm border border-white/5" style={{ backgroundColor: c }} />
                    ))}
                    <span>Profit</span>
                  </div>
                </div>
              </div>

              {/* Grid */}
              {(() => {
                const heatPeriodWeeks: Record<string, number> = { "1M": 5, "3M": 13, "6M": 26, "1Y": 52 };
                const visibleWeeks = heatmapPeriod === "All"
                  ? heatmapData.weeks
                  : heatmapData.weeks.slice(-(heatPeriodWeeks[heatmapPeriod] ?? 52));
                return (
              <div className="px-4 py-4 overflow-x-auto">
                <div className="flex w-full">
                  {/* Day labels */}
                  <div className="flex flex-col gap-[3px] pr-2 flex-shrink-0" style={{ paddingTop: "20px" }}>
                    {["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].map((d, i) => (
                      <div key={i} className="text-[10px] text-gray-400 font-medium flex items-center" style={{ height: "14px" }}>
                        {d}
                      </div>
                    ))}
                  </div>

                  {/* Weeks */}
                  <div className="flex flex-col gap-[3px] flex-1">
                    {/* Month labels */}
                    <div className="flex mb-1">
                      {visibleWeeks.map((week, wi) => {
                        const d = new Date(week[0].date);
                        const show = d.getDate() <= 7;
                        return (
                          <div key={wi} className="flex-1 text-[10px] text-gray-400 font-semibold text-center truncate">
                            {show ? ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()] : ""}
                          </div>
                        );
                      })}
                    </div>

                    {/* Cells: 7 rows × N weeks */}
                    {[0,1,2,3,4,5,6].map(dayIdx => (
                      <div key={dayIdx} className="flex w-full gap-[3px]">
                        {visibleWeeks.map((week, wi) => {
                          const cell = week[dayIdx];
                          const color = heatColor(cell.pnl, heatmapData.maxPnl);
                          return (
                            <div key={wi}
                              className="flex-1 rounded-sm cursor-pointer transition-all hover:ring-1 hover:ring-white/50 hover:z-10"
                              style={{ backgroundColor: color, height: "13px", minWidth: 0 }}
                              onMouseEnter={e => {
                                if (cell.pnl !== null) {
                                  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                                  const x = Math.min(rect.left + rect.width / 2, window.innerWidth - 180);
                                  const y = rect.top - 10;
                                  setHoveredDay({ date: cell.date, pnl: cell.pnl, x, y });
                                }
                              }}
                              onMouseLeave={() => setHoveredDay(null)}
                            />
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
                );
              })()}

              {/* Hover popup */}
              {hoveredDay && (
                <div className="fixed z-50 pointer-events-none transition-all"
                  style={{ left: hoveredDay.x, top: hoveredDay.y - 75, transform: "translateX(-50%)" }}>
                  <div className="bg-[#0d1117] border border-[#2a3045] rounded-xl px-4 py-3 shadow-2xl min-w-[160px]">
                    <div className="text-[10px] text-gray-400 mb-1 font-medium">{hoveredDay.date}</div>
                    <div className={`text-xl font-black font-mono ${hoveredDay.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {hoveredDay.pnl >= 0 ? "+" : ""}{fmtINR(hoveredDay.pnl, 0)}
                    </div>
                    <div className={`text-[11px] font-semibold mt-1 ${hoveredDay.pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                      {hoveredDay.pnl >= 0 ? "✓ Profit day" : "✗ Loss day"}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ── Daily Breakdown ─────────────────────────── */}
            {dailyStats.length > 0 && (
              <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 border-b border-[#1e2433] flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <BarChart2 size={13} className="text-cyan-400" />
                    <span className="text-xs font-bold text-white uppercase tracking-widest">Daily Breakdown</span>
                  </div>
                  <span className="text-[10px] text-gray-600">{dailyStats.length} trading days</span>
                </div>

                {/* Mobile: cards | Desktop: table */}
                <div className="block sm:hidden divide-y divide-[#111827]">
                  {dailyStats.slice(0, dailyVisible).map((d) => {
                    const up = d.pnl >= 0;
                    const dow = new Date(d.date).toLocaleDateString("en-IN", { weekday: "short" });
                    const fmtDate = new Date(d.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
                    return (
                      <div key={d.date} className={`px-4 py-3 ${up ? "hover:bg-green-500/3" : "hover:bg-red-500/3"}`}>
                        <div className="flex items-center justify-between mb-2">
                          <div>
                            <span className="text-xs font-bold text-white">{fmtDate}</span>
                            <span className="text-[10px] text-gray-600 ml-1.5">{dow}</span>
                          </div>
                          <span className={`text-sm font-black font-mono ${up ? "text-green-400" : "text-red-400"}`}>
                            {up ? "+" : ""}{fmtINR(d.pnl, 0)}
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[10px] text-gray-500">Trades</span>
                            <span className="text-[11px] font-bold text-white">{d.total}</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] font-bold text-green-400">{d.wins}W</span>
                            <span className="text-gray-600 text-[10px]">/</span>
                            <span className="text-[10px] font-bold text-red-400">{d.losses}L</span>
                          </div>
                          <div className={`ml-auto text-[11px] font-black px-2 py-0.5 rounded-lg ${d.wr >= 50 ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400"}`}>
                            {d.wr}%
                          </div>
                          <span className={`text-[10px] font-bold font-mono ${d.ar >= 0 ? "text-purple-400" : "text-red-400"}`}>
                            {d.ar >= 0 ? "+" : ""}{d.ar}R
                          </span>
                        </div>
                        {/* Win rate bar */}
                        <div className="mt-2 h-1 bg-[#1a2030] rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${d.wr >= 50 ? "bg-green-500" : "bg-red-500"}`}
                            style={{ width: `${d.wr}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Desktop table */}
                <div className="hidden sm:block overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#1e2433] text-[10px] uppercase text-gray-600 tracking-wider">
                        <th className="px-5 py-2.5 text-left">Date</th>
                        <th className="px-3 py-2.5 text-center">Trades</th>
                        <th className="px-3 py-2.5 text-center">W / L</th>
                        <th className="px-3 py-2.5 text-center">Win Rate</th>
                        <th className="px-3 py-2.5 text-right">Avg R</th>
                        <th className="px-5 py-2.5 text-right">Net P&L</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#111827]">
                      {dailyStats.slice(0, dailyVisible).map((d) => {
                        const up = d.pnl >= 0;
                        const dow = new Date(d.date).toLocaleDateString("en-IN", { weekday: "short" });
                        const fmtDate = new Date(d.date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
                        return (
                          <tr key={d.date} className={`hover:bg-[#111827] transition-colors ${up ? "" : "bg-red-500/[0.02]"}`}>
                            <td className="px-5 py-3">
                              <span className="font-bold text-white">{fmtDate}</span>
                              <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded font-bold ${up ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"}`}>
                                {dow}
                              </span>
                            </td>
                            <td className="px-3 py-3 text-center font-mono font-bold text-white">{d.total}</td>
                            <td className="px-3 py-3 text-center">
                              <span className="text-green-400 font-bold">{d.wins}</span>
                              <span className="text-gray-600 mx-1">/</span>
                              <span className="text-red-400 font-bold">{d.losses}</span>
                            </td>
                            <td className="px-3 py-3 text-center">
                              <div className="flex items-center gap-2 justify-center">
                                <div className="w-16 h-1.5 bg-[#1a2030] rounded-full overflow-hidden">
                                  <div className={`h-full rounded-full ${d.wr >= 50 ? "bg-green-500" : "bg-red-500"}`}
                                    style={{ width: `${d.wr}%` }} />
                                </div>
                                <span className={`font-black text-[11px] w-8 ${d.wr >= 50 ? "text-green-400" : "text-red-400"}`}>
                                  {d.wr}%
                                </span>
                              </div>
                            </td>
                            <td className={`px-3 py-3 text-right font-mono font-bold ${d.ar >= 0 ? "text-purple-400" : "text-red-400"}`}>
                              {d.ar >= 0 ? "+" : ""}{d.ar}R
                            </td>
                            <td className="px-5 py-3 text-right">
                              <span className={`font-black font-mono text-sm ${up ? "text-green-400" : "text-red-400"}`}>
                                {up ? "+" : ""}{fmtINR(d.pnl, 0)}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* See More */}
                {dailyVisible < dailyStats.length && (
                  <div className="border-t border-[#111827] px-5 py-3 flex items-center justify-between">
                    <span className="text-[10px] text-gray-600">
                      Showing {Math.min(dailyVisible, dailyStats.length)} of {dailyStats.length} days
                    </span>
                    <button
                      onClick={() => setDailyVisible(v => v + 20)}
                      className="text-[11px] font-bold text-indigo-400 hover:text-indigo-300 px-3 py-1.5 rounded-lg border border-indigo-500/20 bg-indigo-500/5 hover:bg-indigo-500/10 transition-all"
                    >
                      See 20 more ↓
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* ── Insights ────────────────────────────────── */}
            {stats.insights.length > 0 && (
              <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 border-b border-[#1e2433] flex items-center gap-2.5">
                  <Zap size={13} className="text-yellow-400" />
                  <span className="text-xs font-bold text-white uppercase tracking-widest">Smart Insights</span>
                </div>
                <div className="divide-y divide-[#1a2030]">
                  {stats.insights.map((ins, i) => (
                    <div key={i} className={`px-5 py-3 flex items-start gap-3 ${
                      ins.type === "good" ? "hover:bg-green-500/3" :
                      ins.type === "warn" ? "hover:bg-yellow-500/3" : "hover:bg-blue-500/3"
                    }`}>
                      <div className={`w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${
                        ins.type === "good" ? "bg-green-500/15" :
                        ins.type === "warn" ? "bg-yellow-500/15" : "bg-blue-500/15"
                      }`}>
                        {ins.type === "good" && <CheckCircle size={11} className="text-green-400" />}
                        {ins.type === "warn" && <AlertTriangle size={11} className="text-yellow-400" />}
                        {ins.type === "info" && <Info size={11} className="text-blue-400" />}
                      </div>
                      <span className="text-xs text-gray-300 leading-relaxed">{ins.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Row: Long vs Short + Exit Reasons ───────── */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

              {/* Long vs Short */}
              <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 border-b border-[#1e2433] flex items-center gap-2.5">
                  <TrendingUp size={13} className="text-green-400" />
                  <span className="text-xs font-bold text-white uppercase tracking-widest">Long vs Short</span>
                </div>
                <div className="grid grid-cols-2 divide-x divide-[#1e2433]">
                  {["long", "short"].map(d => {
                    const s = stats.dirMap[d];
                    const wr2 = winRate(s.wins, s.total);
                    const ar2 = avgR(s.rSum, s.total);
                    const isLong = d === "long";
                    return (
                      <div key={d} className="p-5">
                        <div className="flex items-center gap-2 mb-4">
                          <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${isLong ? "bg-green-500/15" : "bg-red-500/15"}`}>
                            {isLong ? <TrendingUp size={13} className="text-green-400" /> : <TrendingDown size={13} className="text-red-400" />}
                          </div>
                          <div>
                            <div className="text-xs font-bold text-white uppercase">{d}</div>
                            <div className="text-[10px] text-gray-600">{s.total} trades</div>
                          </div>
                        </div>
                        {s.total === 0 ? (
                          <span className="text-xs text-gray-600">No trades</span>
                        ) : (
                          <>
                            <div className="mb-1 flex items-end gap-2">
                              <span className={`text-3xl font-black ${wr2 >= 50 ? "text-green-400" : "text-red-400"}`}>{wr2}%</span>
                              <span className="text-gray-600 text-xs mb-1">win rate</span>
                            </div>
                            <div className="h-1.5 bg-[#1a2030] rounded-full overflow-hidden mb-3">
                              <div className={`h-full rounded-full ${wr2 >= 50 ? "bg-green-500" : "bg-red-500"}`}
                                style={{ width: `${wr2}%` }} />
                            </div>
                            <div className={`text-xs font-bold font-mono ${ar2 >= 0 ? "text-purple-400" : "text-red-400"}`}>
                              avg {ar2 >= 0 ? "+" : ""}{ar2}R
                            </div>
                            <div className="text-[10px] text-gray-600 mt-0.5">{s.wins}W · {s.total - s.wins}L</div>
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Exit Reasons — donut style */}
              <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 border-b border-[#1e2433] flex items-center gap-2.5">
                  <Target size={13} className="text-orange-400" />
                  <span className="text-xs font-bold text-white uppercase tracking-widest">Exit Breakdown</span>
                </div>
                <div className="p-4 space-y-2.5">
                  {stats.exitStats.map(e => {
                    const pct = Math.round((e.total / stats.total) * 100);
                    const isWin = e.wr >= 50;
                    return (
                      <div key={e.reason}>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-white">{e.name}</span>
                            <span className="text-[10px] text-gray-600">{e.total} trades · {pct}%</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] font-bold font-mono ${e.ar >= 0 ? "text-purple-400" : "text-red-400"}`}>
                              {e.ar >= 0 ? "+" : ""}{e.ar}R
                            </span>
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${isWin ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400"}`}>
                              {e.wr}%
                            </span>
                          </div>
                        </div>
                        <div className="h-1 bg-[#1a2030] rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${isWin ? "bg-green-500" : e.reason === "sl" ? "bg-red-500" : "bg-orange-500"}`}
                            style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* ── Score vs Win Rate Chart ──────────────────── */}
            {stats.scoreData.length > 0 && (
              <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 border-b border-[#1e2433] flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <BarChart2 size={13} className="text-indigo-400" />
                    <span className="text-xs font-bold text-white uppercase tracking-widest">Score vs Win Rate</span>
                  </div>
                  <span className="text-[10px] text-gray-600">higher score = better edge?</span>
                </div>
                <div className="p-5">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {stats.scoreData.map(s => (
                      <div key={s.sc} className={`rounded-xl p-4 border text-center relative overflow-hidden ${
                        s.wr >= 50 ? "bg-green-500/5 border-green-500/20" : "bg-red-500/5 border-red-500/20"
                      }`}>
                        <div className="text-[10px] text-gray-500 mb-1 uppercase tracking-wider">{s.sc} layers</div>
                        <div className={`text-3xl font-black mb-1 ${s.wr >= 50 ? "text-green-400" : "text-red-400"}`}>{s.wr}%</div>
                        <div className="text-[10px] text-gray-600">{s.total} trades</div>
                        <div className={`text-[10px] font-mono font-bold mt-1 ${s.ar >= 0 ? "text-purple-400" : "text-red-400"}`}>
                          {s.ar >= 0 ? "+" : ""}{s.ar}R avg
                        </div>
                        {/* bg bar */}
                        <div className="absolute bottom-0 left-0 right-0 h-0.5">
                          <div className={`h-full ${s.wr >= 50 ? "bg-green-500" : "bg-red-500"}`}
                            style={{ width: `${s.wr}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            

            {/* ── Hourly Trade Analysis ───────────────────── */}
            {stats.total >= 3 && (
              <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 border-b border-[#1e2433] flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <Clock size={13} className="text-cyan-400" />
                    <span className="text-xs font-bold text-white uppercase tracking-widest">Hourly Trade Analysis</span>
                  </div>
                  <div className="flex gap-1 bg-[#080b12] border border-[#1e2433] rounded-lg p-1">
                    {PERIODS.map(p => (
                      <button key={p} onClick={() => setHourlyPeriod(p)}
                        className={`px-2.5 py-1 rounded text-[10px] font-bold transition-all ${
                          hourlyPeriod === p
                            ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                            : "text-gray-600 hover:text-gray-400"
                        }`}>
                        {p}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Trades count bar per hour */}
                <div className="px-4 pb-3 border-t border-[#1e2433]">
                  <div className="text-[10px] text-gray-600 uppercase tracking-wider pt-3 pb-2">Trades per hour</div>
                  {(() => {
                    const maxTotal = Math.max(...hourlyData.map(h => h.total), 1);
                    const MAX_H = typeof window !== "undefined" && window.innerWidth < 640 ? 140 : 200;
                    return (
                      <div className="flex items-end gap-[3px]" style={{ height: `${MAX_H}px` }}>
                        {hourlyData.map(h => {
                          const barH = h.total > 0 ? Math.max(4, Math.round((h.total / maxTotal) * MAX_H)) : 2;
                          return (
                            <div key={h.hour} className="flex-1 flex flex-col justify-end group relative" style={{ height: `${MAX_H}px` }}>
                              <div
                                className="w-full rounded-sm"
                                style={{
                                  height: `${barH}px`,
                                  backgroundColor: h.total === 0 ? "#1a2030" : h.wr >= 50 ? "#10b981" : "#ef4444",
                                  opacity: h.total === 0 ? 0.2 : 0.75,
                                }}
                              />
                              {h.total > 0 && (
                                <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:flex flex-col z-20 pointer-events-none">
                                  <div className="bg-[#0d1117] border border-[#2a3045] rounded-lg px-2.5 py-2 text-[10px] whitespace-nowrap shadow-xl">
                                    <div className="text-gray-400 font-bold mb-1">{h.label} IST</div>
                                    <div className="text-white font-bold">{h.total} trades</div>
                                    <div className="text-gray-500">{h.wins}W · {h.losses}L · {h.wr}%</div>
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })()}
                </div>

                {/* Best / Worst hour summary */}
                {(() => {
                  const active = hourlyData.filter(h => h.total >= 2);
                  if (active.length < 2) return null;
                  const best  = [...active].sort((a, b) => b.wr - a.wr)[0];
                  const worst = [...active].sort((a, b) => a.wr - b.wr)[0];
                  const busiest = [...active].sort((a, b) => b.total - a.total)[0];
                  return (
                    <div className="grid grid-cols-3 divide-x divide-[#1e2433] border-t border-[#1e2433]">
                      {[
                        { label: "Best Hour", hour: best, color: "text-emerald-400", bg: "bg-emerald-500/5" },
                        { label: "Worst Hour", hour: worst, color: "text-red-400", bg: "bg-red-500/5" },
                        { label: "Busiest Hour", hour: busiest, color: "text-cyan-400", bg: "bg-cyan-500/5" },
                      ].map(({ label, hour, color, bg }) => (
                        <div key={label} className={`px-4 py-3 ${bg}`}>
                          <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-1">{label}</div>
                          <div className={`text-lg font-black ${color}`}>{hour.label}</div>
                          <div className="text-[10px] text-gray-500 mt-0.5">{hour.total} trades · {hour.wr}% WR</div>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            )}

            {/* ── Layer Combo Rankings ─────────────────────── */}
            {stats.comboStats.length > 0 && (
              <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
                <div className="px-5 py-3.5 border-b border-[#1e2433] flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <Zap size={13} className="text-indigo-400" />
                    <span className="text-xs font-bold text-white uppercase tracking-widest">Layer Combo Rankings</span>
                  </div>
                  <span className="text-[10px] text-gray-600">best signal combinations</span>
                </div>
                <div className="divide-y divide-[#111827]">
                  {stats.comboStats.map((c, i) => {
                    const rankColors = ["text-yellow-400", "text-gray-300", "text-amber-600"];
                    return (
                      <div key={c.combo} className="px-5 py-3 flex items-center gap-4 hover:bg-[#111827] transition-colors">
                        <span className={`text-[11px] font-black w-6 flex-shrink-0 ${i < 3 ? rankColors[i] : "text-gray-700"}`}>
                          #{i+1}
                        </span>
                        <div className="flex flex-wrap gap-1 w-40 flex-shrink-0">
                          {c.layers.map(l => (
                            <span key={l} className="text-[10px] font-bold px-1.5 py-0.5 rounded-md bg-indigo-500/15 border border-indigo-500/25 text-indigo-300">
                              {l}
                            </span>
                          ))}
                        </div>
                        <div className="flex-1 hidden sm:block">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-[10px] text-gray-600">{c.total} trades</span>
                            <span className={`text-[10px] font-bold ${c.wr >= 50 ? "text-green-400" : "text-red-400"}`}>{c.wr}%</span>
                          </div>
                          <div className="h-1 bg-[#1a2030] rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${c.wr >= 50 ? "bg-green-500" : "bg-red-500"}`}
                              style={{ width: `${c.wr}%` }} />
                          </div>
                        </div>
                        <div className={`text-xs font-bold font-mono w-14 text-right flex-shrink-0 ${c.ar >= 0 ? "text-purple-400" : "text-red-400"}`}>
                          {c.ar >= 0 ? "+" : ""}{c.ar}R
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── Pair Performance Table ───────────────────── */}
            <div className="bg-[#0d1117] border border-[#1e2433] rounded-2xl overflow-hidden">
              <div className="px-5 py-3.5 border-b border-[#1e2433] flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <Trophy size={13} className="text-yellow-400" />
                  <span className="text-xs font-bold text-white uppercase tracking-widest">Coin Rankings</span>
                </div>
                <span className="text-[10px] text-gray-600">{stats.pairStats.length} pairs · sorted by P&L</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[#1e2433] text-[10px] uppercase text-gray-600 tracking-wider">
                      <th className="px-5 py-2.5 text-left">#</th>
                      <th className="px-3 py-2.5 text-left">Coin</th>
                      <th className="px-3 py-2.5 text-center">Trades</th>
                      <th className="px-3 py-2.5 text-center">W / L</th>
                      <th className="px-3 py-2.5 text-center">Win %</th>
                      <th className="px-3 py-2.5 text-right">Avg R</th>
                      <th className="px-5 py-2.5 text-right">P&L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#111827]">
                    {stats.pairStats.map((p, i) => {
                      const isTop3 = i < 3;
                      const rankColors = ["text-yellow-400", "text-gray-300", "text-amber-600"];
                      return (
                        <tr key={p.pair} className="hover:bg-[#111827] transition-colors group">
                          <td className="px-5 py-3">
                            <span className={`text-[11px] font-black ${isTop3 ? rankColors[i] : "text-gray-700"}`}>
                              {isTop3 ? ["🥇","🥈","🥉"][i] : `#${i+1}`}
                            </span>
                          </td>
                          <td className="px-3 py-3">
                            <span className="font-bold text-white text-sm">{p.pair}</span>
                          </td>
                          <td className="px-3 py-3 text-center text-gray-400 font-mono">{p.total}</td>
                          <td className="px-3 py-3 text-center">
                            <span className="text-green-400 font-bold">{p.wins}</span>
                            <span className="text-gray-600 mx-1">/</span>
                            <span className="text-red-400 font-bold">{p.losses}</span>
                          </td>
                          <td className="px-3 py-3 text-center">
                            <div className="flex items-center gap-1.5 justify-center">
                              <div className="w-12 h-1 bg-[#1a2030] rounded-full overflow-hidden">
                                <div className={`h-full rounded-full ${p.wr >= 50 ? "bg-green-500" : "bg-red-500"}`}
                                  style={{ width: `${p.wr}%` }} />
                              </div>
                              <span className={`font-bold text-[11px] w-8 ${p.wr >= 50 ? "text-green-400" : "text-red-400"}`}>
                                {p.wr}%
                              </span>
                            </div>
                          </td>
                          <td className={`px-3 py-3 text-right font-mono font-bold ${p.ar >= 0 ? "text-purple-400" : "text-red-400"}`}>
                            {p.ar >= 0 ? "+" : ""}{p.ar}R
                          </td>
                          <td className="px-5 py-3 text-right">
                            <span className={`font-bold font-mono ${p.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                              {p.pnl >= 0 ? "+" : ""}{fmtINR(p.pnl, 0)}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 border-[#1e2433] bg-[#080b12]">
                      <td colSpan={2} className="px-5 py-3 text-[10px] font-bold text-gray-500 uppercase tracking-wider">Total</td>
                      <td className="px-3 py-3 text-center font-bold text-white font-mono">{stats.total}</td>
                      <td className="px-3 py-3 text-center">
                        <span className="text-green-400 font-bold">{stats.wins}</span>
                        <span className="text-gray-600 mx-1">/</span>
                        <span className="text-red-400 font-bold">{stats.total - stats.wins}</span>
                      </td>
                      <td className="px-3 py-3 text-center">
                        <span className={`font-bold text-[11px] ${stats.wr >= 50 ? "text-green-400" : "text-red-400"}`}>{stats.wr}%</span>
                      </td>
                      <td className={`px-3 py-3 text-right font-bold font-mono ${stats.ar >= 0 ? "text-purple-400" : "text-red-400"}`}>
                        {stats.ar >= 0 ? "+" : ""}{stats.ar}R
                      </td>
                      <td className={`px-5 py-3 text-right font-bold font-mono ${stats.totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {stats.totalPnl >= 0 ? "+" : ""}{fmtINR(stats.totalPnl, 0)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>


          </div>
        )}
    </main>
  );
}
