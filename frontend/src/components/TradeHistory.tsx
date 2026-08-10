import React, { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";
import { useExchangeRate } from "@/hooks/useExchangeRate";

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

interface Trade {
  id: string;
  pair: string;
  direction: string;
  style: string;
  entry_price: number;
  exit_price: number;
  position_size_usd: number;
  risk_amount: number;
  pnl: number;
  pnl_pct: number;
  r_multiple: number;
  fee: number;
  net_pnl: number;
  exit_reason: string;
  status: string;
  created_at: string;
  exit_time: string;
  duration_seconds: number;
  trader_name: string;
  is_shadow: boolean;
}

interface Props {
  mode: string;
}

const PAGE_SIZE = 20;

function formatDuration(s: number | null) {
  if (!s) return "—";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function formatDate(iso: string) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function formatTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" });
}

function getDateLabel(iso: string | null | undefined) {
  if (!iso) return "Unknown";
  const IST = "Asia/Kolkata";
  const d   = new Date(iso);
  // Compare calendar dates in IST — not a 24h rolling window
  const tradeDate = d.toLocaleDateString("en-CA", { timeZone: IST }); // YYYY-MM-DD
  const today     = new Date().toLocaleDateString("en-CA", { timeZone: IST });
  const yesterday = new Date(Date.now() - 86400000).toLocaleDateString("en-CA", { timeZone: IST });
  if (tradeDate === today)     return "Today";
  if (tradeDate === yesterday) return "Yesterday";
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: IST });
}

function getPaginationPages(current: number, total: number): (number | "...")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  if (current <= 4) return [1, 2, 3, 4, 5, "...", total];
  if (current >= total - 3) return [1, "...", total - 4, total - 3, total - 2, total - 1, total];
  return [1, "...", current - 1, current, current + 1, "...", total];
}

export default function TradeHistory({ mode }: Props) {
  const [trades, setTrades]                 = useState<Trade[]>([]);
  const [loading, setLoading]               = useState(true);
  const [page, setPage]                     = useState(1);
  const [totalCount, setTotalCount]         = useState(0);
  const [traders, setTraders]               = useState<string[]>([]);
  const [selectedTrader, setSelectedTrader] = useState<string | null>("Version-2.0");
  const { fmtINR } = useExchangeRate();

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const fetchTraders = async (currentMode: string) => {
    const { data } = await supabase
      .from("trades")
      .select("trader_name")
      .eq("mode", currentMode)
      .eq("status", "closed")
      .not("trader_name", "is", null);
    if (data) {
      const unique = [...new Set(
        (data as { trader_name: string }[]).map((t) => t.trader_name).filter(Boolean)
      )];
      setTraders(unique);
    }
  };

  const fetchTrades = async (currentPage: number, traderFilter: string | null) => {
    setLoading(true);
    const offset = (currentPage - 1) * PAGE_SIZE;

    let query = supabase
      .from("trades")
      .select("*", { count: "exact" })
      .eq("mode", mode)
      .eq("status", "closed")
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE_SIZE - 1);

    if (traderFilter) query = query.eq("trader_name", traderFilter);

    const { data, count } = await query;
    if (data) setTrades(data as Trade[]);
    setTotalCount(count ?? 0);
    setLoading(false);
  };

  useEffect(() => {
    setPage(1);
    setSelectedTrader(null);
    fetchTrades(1, null);
    fetchTraders(mode);
  }, [mode]);

  useEffect(() => {
    const channel = supabase
      .channel("trades_changes")
      .on("postgres_changes", {
        event: "*", schema: "public", table: "trades",
        filter: `mode=eq.${mode}`,
      }, () => {
        fetchTrades(page, selectedTrader);
        fetchTraders(mode);
      })
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [mode, page, selectedTrader]);

  const handleTraderSelect = (trader: string | null) => {
    setSelectedTrader(trader);
    setPage(1);
    fetchTrades(1, trader);
  };

  const goToPage = (newPage: number) => {
    if (newPage < 1 || newPage > totalPages) return;
    setPage(newPage);
    fetchTrades(newPage, selectedTrader);
  };

  const closedTrades = trades.filter((t) => t.status === "closed");

  // Group trades by date — use exit_time if set, else created_at for date label
  const grouped: { date: string; trades: Trade[] }[] = [];
  closedTrades.forEach((t) => {
    const label = getDateLabel(t.exit_time || t.created_at);
    const last  = grouped[grouped.length - 1];
    if (last && last.date === label) {
      last.trades.push(t);
    } else {
      grouped.push({ date: label, trades: [t] });
    }
  });

  return (
    <div className="bg-[#0f1117] border border-[#1e2433] rounded-xl overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-[#1e2433]">
        <h2 className="text-white font-semibold text-sm uppercase tracking-wide">Trade History</h2>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Trader filter dropdown — only shown when 2+ distinct traders exist */}
          {traders.length > 1 && (
            <select
              value={selectedTrader ?? ""}
              onChange={(e) => handleTraderSelect(e.target.value || null)}
              className="bg-[#0d1117] border border-[#1e2433] text-xs text-gray-300 rounded-lg px-2.5 py-1.5
                         outline-none focus:border-indigo-500/60 cursor-pointer transition-colors"
            >
              <option value="">All Traders</option>
              {traders.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          )}

          <span className="text-xs text-gray-500">{closedTrades.length} trades</span>
        </div>
      </div>

      {loading ? (
        <div className="p-8 text-center text-gray-600 text-sm">Loading...</div>
      ) : closedTrades.length === 0 ? (
        <div className="p-8 text-center text-gray-600 text-sm">No completed trades yet</div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#1e2433] text-gray-500 text-[10px] uppercase">
                  <th className="px-4 py-2 text-left">Trader</th>
                  <th className="px-4 py-2 text-left">Pair</th>
                  <th className="px-3 py-2 text-left">Dir</th>
                  <th className="px-3 py-2 text-left">Style</th>
                  <th className="px-3 py-2 text-right">Entry</th>
                  <th className="px-3 py-2 text-right">Exit</th>
                  <th className="px-3 py-2 text-right">Size</th>
                  <th className="px-3 py-2 text-right">Risk</th>
                  <th className="px-3 py-2 text-right">Gross P&L</th>
                  <th className="px-3 py-2 text-right">Fee</th>
                  <th className="px-3 py-2 text-right">Net P&L</th>
                  <th className="px-3 py-2 text-right">R</th>
                  <th className="px-3 py-2 text-left">Reason</th>
                  <th className="px-3 py-2 text-left">Time</th>
                  <th className="px-3 py-2 text-left">Dur</th>
                </tr>
              </thead>
              <tbody>
                {grouped.map((group) => (
                  <React.Fragment key={group.date}>
                    {/* Date separator */}
                    <tr>
                      <td colSpan={15} className="px-4 pt-3 pb-1.5">
                        <div className="flex items-center gap-3">
                          <span className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest whitespace-nowrap">
                            {group.date}
                          </span>
                          <div className="flex-1 h-px bg-[#1e2433]" />
                          <span className="text-[10px] text-gray-600 whitespace-nowrap">
                            {group.trades.length} trade{group.trades.length > 1 ? "s" : ""}
                          </span>
                        </div>
                      </td>
                    </tr>

                    {group.trades.map((t) => {
                      const pnl    = t.pnl    ?? 0;
                      const netPnl = t.net_pnl ?? pnl;
                      const win    = pnl >= 0;
                      const shadow = t.is_shadow === true;
                      return (
                        <tr key={t.id}
                          className={`border-b border-[#1a2030] hover:bg-[#1a2030] transition-colors ${
                            shadow ? "opacity-60" : ""
                          }`}>
                          <td className="px-4 py-2.5">
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/15 border border-indigo-500/30 text-indigo-300">
                              {t.trader_name || "Unknown"}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 font-bold text-white whitespace-nowrap">
                            {t.pair}
                            {shadow && (
                              <span
                                title="Shadow trade — SL wider than 2.5% of position. Recorded for analysis only; not counted in wallet, stats or risk limits."
                                className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide
                                           bg-amber-500/15 border border-amber-500/40 text-amber-300 align-middle"
                              >
                                Shadow
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              t.direction === "long"
                                ? "bg-green-500/20 text-green-400"
                                : "bg-red-500/20 text-red-400"
                            }`}>
                              {t.direction?.toUpperCase()}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 text-gray-500 capitalize">{t.style}</td>
                          <td className="px-3 py-2.5 text-right text-gray-300 font-mono">
                            {t.entry_price?.toFixed(4) ?? "—"}
                          </td>
                          <td className="px-3 py-2.5 text-right text-gray-300 font-mono">
                            {t.exit_price?.toFixed(4) ?? "—"}
                          </td>
                          <td className="px-3 py-2.5 text-right text-indigo-300 font-mono font-medium">
                            {fmtINR(t.position_size_usd ?? 0)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-orange-300 font-mono">
                            {fmtINR(t.risk_amount ?? 0, 4)}
                          </td>
                          <td className={`px-3 py-2.5 text-right font-mono ${win ? "text-green-400/70" : "text-red-400/70"}`}>
                            {win ? "+" : ""}{fmtINR(pnl, 4)}
                          </td>
                          <td className="px-3 py-2.5 text-right font-mono text-red-400/60">
                            -{fmtINR(t.fee ?? 0, 4)}
                          </td>
                          <td className={`px-3 py-2.5 text-right font-bold font-mono ${netPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {netPnl >= 0 ? "+" : ""}{fmtINR(netPnl, 4)}
                          </td>
                          <td className={`px-3 py-2.5 text-right font-mono ${win ? "text-green-400/70" : "text-red-400/70"}`}>
                            {(t.r_multiple ?? 0) >= 0 ? "+" : ""}{(t.r_multiple ?? 0).toFixed(2)}R
                          </td>
                          <td className="px-3 py-2.5">
                            <span className="text-gray-500 capitalize">{t.exit_reason ?? "—"}</span>
                          </td>
                          <td className="px-3 py-2.5 text-gray-500 whitespace-nowrap">
                            {formatTime(t.exit_time)}
                          </td>
                          <td className="px-3 py-2.5 text-gray-500">
                            {formatDuration(t.duration_seconds)}
                          </td>
                        </tr>
                      );
                    })}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-4 py-3 border-t border-[#1e2433] flex items-center justify-between flex-wrap gap-2">
            <span className="text-[10px] text-gray-600">
              {totalCount > 0
                ? `Showing ${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, totalCount)} of ${totalCount} trades`
                : "0 trades"}
            </span>

            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <button
                  onClick={() => goToPage(page - 1)}
                  disabled={page === 1}
                  className="px-2.5 py-1 rounded text-xs text-gray-400 border border-[#1e2433]
                             hover:border-indigo-500/40 hover:text-indigo-300 disabled:opacity-30
                             disabled:cursor-not-allowed transition-all"
                >
                  ‹
                </button>

                {getPaginationPages(page, totalPages).map((p, i) =>
                  p === "..." ? (
                    <span key={`ellipsis-${i}`} className="px-1.5 text-xs text-gray-600">…</span>
                  ) : (
                    <button
                      key={p}
                      onClick={() => goToPage(p as number)}
                      className={`px-2.5 py-1 rounded text-xs font-semibold border transition-all ${
                        page === p
                          ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300"
                          : "border-[#1e2433] text-gray-400 hover:border-indigo-500/40 hover:text-indigo-300"
                      }`}
                    >
                      {p}
                    </button>
                  )
                )}

                <button
                  onClick={() => goToPage(page + 1)}
                  disabled={page === totalPages}
                  className="px-2.5 py-1 rounded text-xs text-gray-400 border border-[#1e2433]
                             hover:border-indigo-500/40 hover:text-indigo-300 disabled:opacity-30
                             disabled:cursor-not-allowed transition-all"
                >
                  ›
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
