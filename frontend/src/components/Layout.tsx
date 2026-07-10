import { useState } from "react";
import { useBotSocketContext } from "@/hooks/BotSocketContext";
import AppHeader from "./AppHeader";
import BotControls from "./BotControls";
import WalletCard from "./WalletCard";
import PositionCard from "./PositionCard";
import PerfStats from "./PerfStats";

interface Props {
  children: React.ReactNode;
}

export default function Layout({ children }: Props) {
  const { state, startBot, stopBot, forceClose } = useBotSocketContext();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const positions = Object.values(state.positions);

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

      <div className="flex flex-1 overflow-hidden relative">
        {/* Mobile backdrop */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-50 bg-black/60 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
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
        `}>
          <BotControls
            running={state.running}
            mode={state.mode}
            style={state.style}
            hasPosition={positions.length > 0}
            onStart={startBot}
            onStop={stopBot}
            onForceClose={forceClose}
            walletBalance={state.wallet?.balance}
          />
          <WalletCard mode={state.mode} />
          {positions.length > 0
            ? positions.map((p) => (
                <PositionCard
                  key={p.pair}
                  position={p}
                  lastTrade={state.lastTrade}
                  onForceClose={() => forceClose(p.pair)}
                />
              ))
            : <PositionCard position={null} lastTrade={state.lastTrade} onForceClose={() => forceClose()} />
          }
          <PerfStats mode={state.mode || "demo"} />
        </aside>

        {/* Page content */}
        <div className="flex-1 overflow-hidden flex flex-col min-w-0">
          {children}
        </div>
      </div>
    </div>
  );
}
