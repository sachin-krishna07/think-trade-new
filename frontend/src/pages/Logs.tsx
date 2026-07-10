import { useEffect, useRef, useState } from "react";
import { LogEntry } from "@/hooks/useBotSocket";
import { useBotSocketContext } from "@/hooks/BotSocketContext";
import { Search, Trash2, ArrowDown } from "lucide-react";

const API_URL = import.meta.env.VITE_BOT_API_URL || "http://localhost:8000";

const LEVEL_STYLE: Record<string, string> = {
  ERROR:   "text-red-400 bg-red-500/10 border-red-500/30",
  WARNING: "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  INFO:    "text-blue-300 bg-blue-500/5 border-blue-500/20",
  DEBUG:   "text-gray-500 bg-transparent border-transparent",
};

const LEVEL_DOT: Record<string, string> = {
  ERROR:   "bg-red-400",
  WARNING: "bg-yellow-400",
  INFO:    "bg-blue-400",
  DEBUG:   "bg-gray-600",
};

const NAME_COLOR: Record<string, string> = {
  trade_engine:   "text-purple-400",
  signal_engine:  "text-indigo-400",
  bot_controller: "text-cyan-400",
  market_data:    "text-teal-400",
  risk_manager:   "text-orange-400",
};

function fmt(ts: number) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-IN", { hour12: false }) +
    "." + String(d.getMilliseconds()).padStart(3, "0");
}

export default function Logs() {
  const { state } = useBotSocketContext();
  const [localLogs, setLocalLogs] = useState<LogEntry[]>([]);
  const [filterLevel, setFilterLevel] = useState<string>("ALL");
  const [filterName, setFilterName]   = useState<string>("ALL");
  const [search, setSearch]           = useState<string>("");
  const [autoScroll, setAutoScroll]   = useState(true);
  const [source, setSource]           = useState<"db" | "memory">("memory");
  const [loading, setLoading]         = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Fetch logs from selected source
  const fetchLogs = (src: "db" | "memory") => {
    setLoading(true);
    fetch(`${API_URL}/api/logs?limit=300&source=${src}`)
      .then((r) => r.json())
      .then((data) => setLocalLogs(data.logs || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchLogs(source); }, [source]);

  // Merge WebSocket live logs (always, regardless of source)
  useEffect(() => {
    if (state.logs.length === 0) return;
    const latest = state.logs[state.logs.length - 1];
    setLocalLogs((prev) => {
      if (prev.length > 0 && prev[prev.length - 1].ts === latest.ts) return prev;
      return [...prev.slice(-499), latest];
    });
  }, [state.logs]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [localLogs, autoScroll]);

  // Detect manual scroll up → disable auto-scroll
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(atBottom);
  };

  // Filter
  const names = Array.from(new Set(localLogs.map((l) => l.name)));
  const filtered = localLogs.filter((l) => {
    if (filterLevel !== "ALL" && l.level !== filterLevel) return false;
    if (filterName !== "ALL" && l.name !== filterName)   return false;
    if (search && !l.msg.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="flex flex-col flex-1 overflow-hidden p-2 pb-24 sm:p-4 md:pb-4 gap-2 sm:gap-3">
        {/* Toolbar */}
        <div className="flex flex-col gap-2">
          {/* Row 1: Source + Level + Actions */}
          <div className="flex items-center gap-2 flex-wrap">

            {/* Level filter */}
            <div className="flex items-center gap-1 bg-[#0d1117] border border-[#1e2433] rounded-lg p-1 flex-wrap">
              {["ALL", "ERROR", "WARN", "INFO", "DEBUG"].map((lvl) => {
                const actual = lvl === "WARN" ? "WARNING" : lvl;
                return (
                  <button
                    key={lvl}
                    onClick={() => setFilterLevel(actual)}
                    className={`text-[10px] sm:text-[11px] font-bold px-2 py-1 rounded-md transition-all ${
                      filterLevel === actual
                        ? actual === "ERROR"   ? "bg-red-500/20 text-red-400"
                        : actual === "WARNING" ? "bg-yellow-500/20 text-yellow-400"
                        : actual === "INFO"    ? "bg-blue-500/20 text-blue-400"
                        : actual === "DEBUG"   ? "bg-gray-700 text-gray-400"
                        : "bg-[#1e2433] text-white"
                        : "text-gray-600 hover:text-gray-400"
                    }`}
                  >
                    {lvl}
                  </button>
                );
              })}
            </div>

            {/* Log count */}
            <span className="text-[11px] text-gray-600 ml-auto">
              {filtered.length}/{localLogs.length}
            </span>

            {/* Auto-scroll toggle */}
            <button
              onClick={() => {
                setAutoScroll(true);
                bottomRef.current?.scrollIntoView({ behavior: "smooth" });
              }}
              className={`flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg border transition-all ${
                autoScroll
                  ? "border-green-500/30 bg-green-500/10 text-green-400"
                  : "border-[#1e2433] text-gray-600 hover:text-gray-400"
              }`}
            >
              <ArrowDown size={11} />
              <span className="hidden sm:inline">Live</span>
            </button>

            {/* Clear */}
            <button
              onClick={() => setLocalLogs([])}
              className="flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg border border-[#1e2433] text-gray-600 hover:text-red-400 hover:border-red-500/30 transition-all"
            >
              <Trash2 size={11} />
              <span className="hidden sm:inline">Clear</span>
            </button>
          </div>

          {/* Row 2: Search + Component filter */}
          <div className="flex items-center gap-2">
            {/* Search */}
            <div className="flex items-center gap-1.5 bg-[#0d1117] border border-[#1e2433] rounded-lg px-2.5 py-1.5 flex-1">
              <Search size={12} className="text-gray-600 flex-shrink-0" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search logs..."
                className="bg-transparent text-[11px] text-gray-300 outline-none w-full placeholder:text-gray-700"
              />
            </div>

            {/* Component filter */}
            <select
              value={filterName}
              onChange={(e) => setFilterName(e.target.value)}
              className="text-[11px] bg-[#0d1117] border border-[#1e2433] rounded-lg px-2.5 py-1.5 text-gray-400 outline-none cursor-pointer max-w-[130px] sm:max-w-none"
            >
              <option value="ALL">All</option>
              {names.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Log list */}
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto overflow-x-hidden bg-[#060810] border border-[#1e2433] rounded-xl font-mono text-[10px] sm:text-[11px] leading-relaxed"
        >
          {loading ? (
            <div className="flex items-center justify-center h-full gap-2 text-gray-600 text-sm">
              <span className="animate-spin w-4 h-4 border-2 border-gray-600 border-t-indigo-400 rounded-full inline-block" />
              Loading...
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-700 text-sm p-4 text-center">
              {localLogs.length === 0
                ? "No logs yet — start the bot to see activity"
                : "No logs match the current filter"}
            </div>
          ) : (
            <div className="divide-y divide-[#0f1420]">
              {filtered.map((l, i) => (
                <div
                  key={i}
                  className={`flex flex-col sm:flex-row sm:items-start gap-0.5 sm:gap-0 px-2 py-1.5 hover:bg-white/[0.02] transition-colors ${
                    l.level === "ERROR" ? "bg-red-500/5" : ""
                  }`}
                >
                  {/* Mobile: top row — time + level + component */}
                  <div className="flex items-center gap-1.5 sm:contents">
                    {/* Time */}
                    <span className="text-gray-600 whitespace-nowrap sm:w-[90px] sm:px-1 sm:py-0 sm:align-top flex-shrink-0">
                      {fmt(l.ts)}
                    </span>

                    {/* Level badge */}
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-bold flex-shrink-0 ${LEVEL_STYLE[l.level] || LEVEL_STYLE.DEBUG}`}>
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${LEVEL_DOT[l.level] || "bg-gray-600"}`} />
                      <span className="hidden sm:inline">{l.level}</span>
                    </span>

                    {/* Component */}
                    <span className={`whitespace-nowrap font-semibold text-[10px] sm:w-[130px] sm:px-2 flex-shrink-0 ${NAME_COLOR[l.name] || "text-gray-500"}`}>
                      {l.name}
                    </span>
                  </div>

                  {/* Message */}
                  <span className={`pl-0 sm:pl-3 break-words min-w-0 ${
                    l.level === "ERROR"   ? "text-red-300" :
                    l.level === "WARNING" ? "text-yellow-200" :
                                            "text-gray-300"
                  }`}>
                    {l.msg}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
    </div>
  );
}
