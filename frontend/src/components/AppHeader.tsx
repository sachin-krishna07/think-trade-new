import { useLocation, Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { Wifi, WifiOff, LayoutDashboard, BarChart2, History, Wallet, Terminal, Menu, X, Activity, Clock, AlertTriangle } from "lucide-react";
import { RiskStatus } from "@/hooks/useBotSocket";

interface Props {
  connected?: boolean;
  running?: boolean;
  mode?: string;
  style?: string;
  riskStatus?: RiskStatus | null;
  sidebarOpen?: boolean;
  onSidebarToggle?: () => void;
}

const DESKTOP_TABS = [
  { path: "/",          label: "Dashboard", icon: LayoutDashboard },
  { path: "/analytics", label: "Analytics", icon: BarChart2 },
  { path: "/history",   label: "History",   icon: History },
  { path: "/logs",      label: "Logs",      icon: Terminal },
];

const MOBILE_TABS = [
  { path: "/",          label: "Dashboard", icon: LayoutDashboard },
  { path: "/analytics", label: "Analytics", icon: BarChart2 },
  { path: "/history",   label: "History",   icon: History },
  { path: "/wallet",    label: "Wallet",    icon: Wallet },
];

const MOBILE_NAV_HEIGHT = 84;

function fmtSecs(secs: number) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export default function AppHeader({
  connected, running, mode, style, riskStatus, sidebarOpen, onSidebarToggle,
}: Props) {
  const { pathname } = useLocation();
  const [remaining, setRemaining] = useState<number | null>(null);

  // Sync from server (every 5s via WS), then tick locally every 1s
  useEffect(() => {
    if (riskStatus?.cooldown_remaining_sec != null) {
      setRemaining(riskStatus.cooldown_remaining_sec);
    } else {
      setRemaining(null);
    }
  }, [riskStatus?.cooldown_remaining_sec]);

  useEffect(() => {
    if (remaining == null || remaining <= 0) return;
    const t = setInterval(() => setRemaining((r) => (r != null && r > 0 ? r - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [remaining]);

  const inCooldown  = riskStatus?.trade_mode === "cooldown" && remaining != null && remaining > 0;
  const inRestricted = riskStatus?.trade_mode === "restricted" && !inCooldown;

  return (
    <header className="flex-shrink-0 z-30" style={{ background: "linear-gradient(180deg, #060910 0%, #070c15 100%)", borderBottom: "1px solid #1a2235" }}>

      {/* Top bar */}
      <div className="flex items-center justify-between px-4 sm:px-5 md:px-8" style={{ height: "64px" }}>

        {/* Left: hamburger + logo */}
        <div className="flex items-center gap-2 sm:gap-4">
          {onSidebarToggle && (
            <button
              onClick={onSidebarToggle}
              className="relative z-20 flex h-10 w-10 flex-shrink-0 touch-manipulation items-center justify-center rounded-xl border border-white/5 bg-white/[0.04] text-gray-300 transition-colors hover:bg-white/6 hover:text-white md:hidden"
              aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
              type="button"
            >
              {sidebarOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          )}

          <div className="flex items-center gap-2 sm:gap-3">
            <div className="relative flex h-14 w-14 items-center justify-center sm:h-16 sm:w-20 pointer-events-none">
              {/* Glow burst ring */}
              <span className="pointer-events-none absolute inset-0 rounded-full animate-ping"
                style={{ background: "radial-gradient(circle, rgba(255,255,255,0.18) 0%, transparent 70%)", animationDuration: "2.4s" }} />
              <span className="pointer-events-none absolute inset-0 rounded-full animate-ping"
                style={{ background: "radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 65%)", animationDuration: "3.2s", animationDelay: "0.8s" }} />
              <img src="/trade thinker.png" alt="TradeThinker" className="w-full h-full object-contain relative z-10"
                style={{ filter: "drop-shadow(0 0 8px rgba(255,255,255,0.30)) drop-shadow(0 0 3px rgba(255,255,255,0.18))" }} />
            </div>
            <div className="flex flex-col leading-none min-w-0">
              <span className="text-white text-base sm:text-xl" style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, letterSpacing: "-0.01em" }}>
                TradeThinker
              </span>
              <span className="text-[9px] sm:text-[10px] font-medium hidden sm:block" style={{ color: "#4f6a9a", letterSpacing: "0.12em" }}>
                CRYPTO AUTOBOT
              </span>
            </div>
          </div>
        </div>

        {/* Right: status pills */}
        <div className="flex items-center gap-1.5 sm:gap-3">

          {/* Cooldown pill — always visible, ticks every second */}
          {inCooldown && (
            <div
              className="flex items-center gap-1 sm:gap-1.5 text-xs font-bold px-2 sm:px-3 py-1.5 rounded-full border border-red-500/40"
              style={{ background: "rgba(239,68,68,0.12)", color: "#f87171" }}
            >
              <Clock size={11} className="animate-pulse" />
              <span>{fmtSecs(remaining!)}</span>
              {riskStatus?.cooldown_total_min && (
                <span className="hidden sm:inline" style={{ color: "rgba(248,113,113,0.5)" }}>
                  / {riskStatus.cooldown_total_min}m
                </span>
              )}
            </div>
          )}

          {/* Restricted pill */}
          {inRestricted && (
            <div
              className="flex items-center gap-1 sm:gap-1.5 text-xs font-bold px-2 sm:px-3 py-1.5 rounded-full border border-orange-500/40"
              style={{ background: "rgba(249,115,22,0.1)", color: "#fb923c" }}
            >
              <AlertTriangle size={11} />
              <span className="hidden sm:inline">RESTRICTED</span>
              <span className="sm:hidden">1T</span>
            </div>
          )}

          {/* Connection pill — hidden on mobile */}
          {connected !== undefined && (
            <div className={`hidden sm:flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full ${
              connected
                ? "text-emerald-400 bg-emerald-500/10 border border-emerald-500/20"
                : "text-red-400 bg-red-500/10 border border-red-500/20"
            }`}>
              {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
              <span>{connected ? "Connected" : "Offline"}</span>
            </div>
          )}

          {/* Bot status pill */}
          {running !== undefined && (
            <div className={`flex items-center gap-1.5 text-xs font-bold px-2.5 sm:px-4 py-2 rounded-full transition-all ${
              running
                ? "text-emerald-300 border border-emerald-500/30"
                : "text-gray-500 border border-white/5"
            }`}
              style={running ? {
                background: "linear-gradient(135deg, rgba(16,185,129,0.12) 0%, rgba(16,185,129,0.06) 100%)",
                boxShadow: "0 0 20px rgba(16,185,129,0.15)"
              } : { background: "rgba(255,255,255,0.03)" }}>
              {running ? (
                <>
                  <Activity size={11} className="animate-pulse" />
                  <span className="hidden sm:inline tracking-widest">{mode?.toUpperCase()} · {style?.toUpperCase()}</span>
                  <span className="sm:hidden">{mode?.toUpperCase()}</span>
                </>
              ) : (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-gray-700" />
                  <span>STOPPED</span>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Nav tabs — scrollable on mobile */}
      <div
        className="hidden md:flex overflow-x-auto px-4 sm:px-5 md:px-8"
        style={{ borderTop: "1px solid #111827", scrollbarWidth: "none", msOverflowStyle: "none" }}
      >
        {DESKTOP_TABS.map((tab) => {
          const active = pathname === tab.path;
          const Icon   = tab.icon;
          return (
            <Link
              key={tab.path}
              to={tab.path}
              className={`relative flex-shrink-0 flex items-center gap-1.5 sm:gap-2 px-3 sm:px-5 py-3 text-xs font-semibold transition-all ${
                active ? "text-indigo-400" : "text-gray-600 hover:text-gray-300"
              }`}
            >
              <Icon size={13} />
              {tab.label}
              {active && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 rounded-full"
                  style={{ background: "linear-gradient(90deg, transparent, #6366f1, transparent)", boxShadow: "0 0 8px #6366f1" }} />
              )}
            </Link>
          );
        })}
      </div>
      <div
        className="fixed bottom-0 left-0 right-0 z-50 px-3 pt-2 pb-[max(12px,env(safe-area-inset-bottom))] md:hidden"
        style={{
          minHeight: `${MOBILE_NAV_HEIGHT}px`,
          background: "linear-gradient(180deg, rgba(7,10,16,0.92) 0%, rgba(5,8,13,0.98) 100%)",
          borderTop: "1px solid #1a2235",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
        }}
      >
        <div className="grid h-14 grid-cols-4 gap-1.5 rounded-[18px] border border-white/5 bg-white/[0.02] px-1.5 py-1.5 shadow-[0_-8px_30px_rgba(0,0,0,0.35)]">
          {MOBILE_TABS.map((tab) => {
            const active = pathname === tab.path;
            const Icon = tab.icon;

            return (
              <Link
                key={tab.path}
                to={tab.path}
                className={`flex min-w-0 flex-col items-center justify-center gap-0.5 rounded-2xl px-1 py-1 text-[9px] font-semibold leading-none transition-all ${
                  active ? "text-indigo-200" : "text-gray-500"
                }`}
                style={active ? {
                  background: "linear-gradient(180deg, rgba(99,102,241,0.22) 0%, rgba(59,130,246,0.08) 100%)",
                  border: "1px solid rgba(99,102,241,0.25)",
                  boxShadow: "0 10px 24px rgba(79,70,229,0.18), inset 0 1px 0 rgba(255,255,255,0.08)",
                } : undefined}
              >
                <Icon size={16} />
                <span className="w-full truncate text-center">{tab.label}</span>
              </Link>
            );
          })}
        </div>
      </div>
    </header>
  );
}
