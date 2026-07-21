import { useState, useRef, useCallback, useEffect } from "react";
import { useBotSocketContext } from "@/hooks/BotSocketContext";
import BotControls from "@/components/BotControls";
import SignalPanel from "@/components/SignalPanel";
import WalletCard from "@/components/WalletCard";
import PositionCard from "@/components/PositionCard";
import PerfStats from "@/components/PerfStats";
import AppHeader from "@/components/AppHeader";
import { Clock, TrendingUp, TrendingDown, ChevronUp, ChevronDown, Activity } from "lucide-react";
import { useExchangeRate } from "@/hooks/useExchangeRate";

function formatSeconds(s: number) {
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

const MIN_HEIGHT = 40;   // collapsed — only header visible
const DEFAULT_HEIGHT = 220;
const MAX_HEIGHT = 520;
const MOBILE_NAV_HEIGHT = 84;

export default function Index() {
  const { state, startBot, stopBot, forceClose } = useBotSocketContext();
  const [sidebarOpen, setSidebarOpen]   = useState(false);
  const [drawerHeight, setDrawerHeight] = useState(MIN_HEIGHT);
  const [isOpen, setIsOpen]             = useState(false);
  const { fmtINR } = useExchangeRate();

  const positions   = Object.values(state.positions);
  const totalPnl    = positions.reduce((sum, p) => sum + (p.pnl ?? 0), 0);
  const totalPnlPct = positions.reduce((sum, p) => sum + (p.pnl_pct ?? 0), 0);
  const isDragging  = useRef(false);
  const startY      = useRef(0);
  const startHeight = useRef(0);

  // Auto-expand when trade opens
  useEffect(() => {
    if (positions.length > 0 && !isOpen) {
      setIsOpen(true);
      setDrawerHeight(DEFAULT_HEIGHT);
    }
  }, [positions.length]);

  const toggleDrawer = () => {
    if (isOpen) {
      setIsOpen(false);
      setDrawerHeight(MIN_HEIGHT);
    } else {
      setIsOpen(true);
      setDrawerHeight(DEFAULT_HEIGHT);
    }
  };

  // Drag to resize
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current  = true;
    startY.current      = e.clientY;
    startHeight.current = drawerHeight;
    document.body.style.cursor     = "ns-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const delta  = startY.current - ev.clientY;
      const newH   = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, startHeight.current + delta));
      setDrawerHeight(newH);
      setIsOpen(newH > MIN_HEIGHT + 10);
    };
    const onUp = () => {
      isDragging.current             = false;
      document.body.style.cursor     = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [drawerHeight]);

  const currentHeight = isOpen ? drawerHeight : MIN_HEIGHT;

  return (
    <div className="h-screen flex flex-col bg-[#070a10] text-white overflow-hidden pb-[84px] md:pb-0">
      <AppHeader
        connected={state.connected}
        running={state.running}
        mode={state.mode}
        style={state.style}
        riskStatus={state.riskStatus}
        sidebarOpen={sidebarOpen}
        onSidebarToggle={() => setSidebarOpen((v) => !v)}
      />

      {/* Body */}
      <div className="flex flex-1 overflow-hidden relative">
        {/* Mobile backdrop */}
        {sidebarOpen && (
          <div className="fixed inset-0 z-50 bg-black/60 md:hidden"
            onClick={() => setSidebarOpen(false)} />
        )}

        {/* Sidebar */}
        <aside className={`
            fixed md:relative inset-y-0 left-0 z-[60] md:z-auto
            w-[300px] md:w-80 flex-shrink-0
            flex flex-col gap-4
            border-r border-[#1e2433] bg-[#070a10]
            overflow-y-auto p-4
            transition-transform duration-200 ease-in-out
            ${sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}
            pt-[57px] md:pt-4
          `}
        >
          <BotControls
            running={state.running}
            mode={state.mode}
            style={state.style}
            reverseDirection={state.reverseDirection}
            hasPosition={positions.length > 0}
            onStart={startBot}
            onStop={stopBot}
            onForceClose={forceClose}
            walletBalance={state.wallet?.balance}
          />
          <WalletCard mode={state.mode} />
          {positions.length > 0
            ? positions.map((p) => (
                <PositionCard key={p.pair} position={p} lastTrade={state.lastTrade} onForceClose={() => forceClose(p.pair)} />
              ))
            : <PositionCard position={null} lastTrade={state.lastTrade} onForceClose={() => forceClose()} />
          }
          <PerfStats mode={state.mode || "demo"} />
        </aside>

        {/* Main Panel */}
        <main
          className="flex-1 overflow-y-auto p-4 space-y-4 bg-[#07090f] min-w-0"
          style={{ paddingBottom: `${currentHeight + MOBILE_NAV_HEIGHT + 16}px` }}
        >
          <div className="flex items-center justify-between gap-3 border-b border-[#1a2030] pb-3 mb-1">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center flex-shrink-0">
                <Activity size={15} className="text-indigo-400" />
              </div>
              <div>
                <h1 className="text-base font-bold text-white leading-tight">Live Signal Monitor</h1>
                <p className="text-[10px] text-gray-500 hidden sm:block">7-layer confluence engine · min 4/7 signals required to trade</p>
              </div>
            </div>
            {state.running && (
              <div className="text-xs text-gray-500 bg-[#0d1117] border border-[#1e2433] px-3 py-1.5 rounded-lg flex-shrink-0">
                {Object.keys(state.signals).length > 0
                  ? `${Object.keys(state.signals).length} pairs tracked`
                  : state.pairs.length > 0
                    ? `${state.pairs.length} pairs loading...`
                    : "loading..."}
              </div>
            )}
          </div>

          <SignalPanel
            signals={state.signals}
            selectedPairs={state.running ? undefined : []}
            running={state.running}
            knownPairs={state.pairs}
          />
        </main>

        {/* ── Bottom Drawer (VS Code style) ── */}
        <div
          className="fixed bottom-[84px] right-0 z-40 flex flex-col md:bottom-0 md:left-80 left-0"
          style={{
            height: `${currentHeight}px`,
            transition: isDragging.current ? "none" : "height 0.2s ease",
            background: "linear-gradient(180deg, #0a0f1a 0%, #080c15 100%)",
            borderTop: "1px solid #2a3a5c",
            borderRadius: "12px 12px 0 0",
            boxShadow: "0 -4px 24px rgba(0,0,0,0.4), 0 -1px 0 rgba(99,102,241,0.15)",
          }}
        >
          {/* Resize handle */}
          <div
            onMouseDown={onMouseDown}
            className="w-full flex items-center justify-center cursor-ns-resize group"
            style={{ height: "6px", flexShrink: 0 }}
          >
            <div className="w-10 h-1 rounded-full bg-white/30 group-hover:bg-white/60 transition-colors" />
          </div>

          {/* Header bar */}
          <div
            className="flex items-center justify-between px-4 flex-shrink-0 cursor-pointer select-none"
            style={{ height: "34px" }}
            onClick={toggleDrawer}
          >
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">
                Active Trades
              </span>
              {positions.length > 0 && (
                <>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/20 text-green-400 animate-pulse">
                    {positions.length} open
                  </span>
                  <span className={`text-[10px] font-bold font-mono px-2 py-0.5 rounded-full border ${
                    totalPnl >= 0
                      ? "bg-green-500/10 border-green-500/20 text-green-400"
                      : "bg-red-500/10 border-red-500/20 text-red-400"
                  }`}>
                    {totalPnl >= 0 ? "+" : ""}{fmtINR(totalPnl)} ({totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%)
                  </span>
                </>
              )}
              {positions.length === 0 && (
                <span className="text-[10px] text-gray-600">0 open</span>
              )}
            </div>
            <div className="text-white/60 hover:text-white transition-colors"
              style={{ animation: "drawerBounce 1.5s ease-in-out infinite" }}>
              {isOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
            </div>
          </div>

          {/* Content */}
          {isOpen && (
            <div className="flex-1 overflow-auto">
              {positions.length === 0 ? (
                <div className="px-4 py-6 text-center text-gray-700 text-xs">No active trades</div>
              ) : (
                <table className="w-full text-xs min-w-[700px]">
                  <thead className="sticky top-0 bg-[#0d1117]">
                    <tr className="border-b border-[#1a2030] text-[10px] uppercase text-gray-600 tracking-wider">
                      <th className="px-4 py-2 text-left">Pair</th>
                      <th className="px-3 py-2 text-right">P&L</th>
                      <th className="px-3 py-2 text-right">Entry</th>
                      <th className="px-3 py-2 text-right">Current</th>
                      <th className="px-3 py-2 text-right">Stop Loss</th>
                      <th className="px-3 py-2 text-right">Target</th>
                      <th className="px-3 py-2 text-right">Size</th>
                      <th className="px-3 py-2 text-right">R</th>
                      <th className="px-3 py-2 text-right">Time</th>
                      <th className="px-3 py-2 text-left">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#111827]">
                    {positions.map((p) => {
                      const isLong = p.direction === "long";
                      const pnlUp  = (p.pnl ?? 0) >= 0;
                      const r      = p.r ?? 0;
                      return (
                        <tr key={p.pair} className={`hover:bg-[#111827] transition-colors ${
                          pnlUp ? "border-l-2 border-l-green-500/30" : "border-l-2 border-l-red-500/30"
                        }`}>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <span className={`flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                                isLong
                                  ? "bg-green-500/10 border-green-500/25 text-green-400"
                                  : "bg-red-500/10 border-red-500/25 text-red-400"
                              }`}>
                                {isLong ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
                                {p.direction?.toUpperCase()}
                              </span>
                              <span className="font-bold text-white text-sm">{p.pair}</span>
                            </div>
                          </td>
                          <td className="px-3 py-3 text-right">
                            <div className={`font-bold font-mono text-sm ${pnlUp ? "text-green-400" : "text-red-400"}`}>
                              {pnlUp ? "+" : ""}{fmtINR(p.pnl ?? 0)}
                            </div>
                            <div className={`text-[10px] font-mono ${pnlUp ? "text-green-400/60" : "text-red-400/60"}`}>
                              {(p.pnl_pct ?? 0) >= 0 ? "+" : ""}{p.pnl_pct?.toFixed(2)}%
                            </div>
                          </td>
                          <td className="px-3 py-3 text-right font-mono text-gray-300 text-sm">{p.entry?.toFixed(4)}</td>
                          <td className="px-3 py-3 text-right">
                            <span className={`font-mono font-bold text-sm ${pnlUp ? "text-green-400" : "text-red-400"}`}>{p.current?.toFixed(4)}</span>
                          </td>
                          <td className="px-3 py-3 text-right font-mono text-red-400 text-sm">{p.sl?.toFixed(4)}</td>
                          <td className="px-3 py-3 text-right font-mono text-yellow-400 text-sm">{p.tp?.toFixed(4)}</td>
                          <td className="px-3 py-3 text-right font-mono text-indigo-300 text-sm font-bold">{fmtINR(p.size_usd ?? 0, 0)}</td>
                          <td className="px-3 py-3 text-right">
                            <span className={`font-mono font-bold text-sm ${r >= 0 ? "text-indigo-400" : "text-red-400"}`}>
                              {r >= 0 ? "+" : ""}{r.toFixed(2)}R
                            </span>
                          </td>
                          <td className="px-3 py-3 text-right text-gray-600 whitespace-nowrap">
                            <Clock size={10} className="inline mr-1 mb-0.5" />
                            {formatSeconds(p.elapsed_sec || 0)}
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex items-center gap-1">
                              {p.trailing_sl && p.breakeven_hit ? (
                                <span className="text-[10px] px-1.5 py-0.5 rounded border border-purple-500/25 bg-purple-500/10 text-purple-400 font-bold">TRAIL</span>
                              ) : (
                                <span className="text-[10px] px-1.5 py-0.5 rounded border border-gray-700 bg-gray-800/50 text-gray-600 font-bold">OPEN</span>
                              )}
                              {p.profit_locked && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded border border-green-500/25 bg-green-500/10 text-green-400 font-bold">🔒</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
