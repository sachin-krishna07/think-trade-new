import { useState, useEffect } from "react";
import TradeHistory from "@/components/TradeHistory";
import { useBotSocketContext } from "@/hooks/BotSocketContext";
import { History as HistoryIcon } from "lucide-react";

export default function History() {
  const { state } = useBotSocketContext();
  const [mode, setMode] = useState<"demo" | "live">("demo");

  useEffect(() => {
    if (state.mode === "live" || state.mode === "demo") {
      setMode(state.mode as "demo" | "live");
    }
  }, [state.mode]);

  return (
    <main className="flex-1 overflow-y-auto p-4 pb-24 md:pb-4 space-y-4 bg-[#07090f]">
      <div className="flex items-center justify-between gap-3 border-b border-[#1a2030] pb-3 mb-1">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center flex-shrink-0">
            <HistoryIcon size={15} className="text-indigo-400" />
          </div>
          <div>
            <h1 className="text-base font-bold text-white leading-tight">Trade History</h1>
            <p className="text-[10px] text-gray-500 hidden sm:block">All completed trades</p>
          </div>
        </div>
        <div className="flex gap-1.5 bg-[#0d1117] border border-[#1e2433] rounded-lg p-1">
          {(["demo", "live"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
                mode === m
                  ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {m.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <TradeHistory mode={mode} />
    </main>
  );
}
