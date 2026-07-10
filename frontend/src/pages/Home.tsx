import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  BadgeIndianRupee,
  Receipt,
  TrendingDown,
  TrendingUp,
  UserRound,
  Wallet,
} from "lucide-react";
import { createClient } from "@supabase/supabase-js";
import { useBotSocketContext } from "@/hooks/BotSocketContext";
import { useExchangeRate } from "@/hooks/useExchangeRate";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

type TraderTrade = {
  net_pnl: number;
  pnl: number;
  fee: number;
};

type WalletRow = {
  initial_balance: number;
};

function SmallCard({
  label,
  value,
  icon,
  valueClass = "text-white",
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  valueClass?: string;
}) {
  return (
    <section className="rounded-[24px] border border-[#1e2433] bg-[#0d1117] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-gray-500">{label}</p>
        <div className="flex h-10 w-10 items-center justify-center rounded-[16px] border border-white/10 bg-white/[0.03] text-white/75">
          {icon}
        </div>
      </div>
      <div className={`mt-4 text-[20px] font-semibold leading-none tracking-tight tabular-nums sm:text-[24px] ${valueClass}`}>
        {value}
      </div>
    </section>
  );
}

function SelectShell({
  value,
  onChange,
  placeholder,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-11 rounded-[16px] border-white/10 bg-[#0f141d] px-3 text-sm font-medium text-gray-200 ring-offset-0 focus:ring-1 focus:ring-cyan-400/50 focus:ring-offset-0 [&>span]:truncate">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="rounded-[18px] border-[#1f2937] bg-[#0f141d] text-gray-200 shadow-[0_16px_40px_rgba(0,0,0,0.45)]">
        {options.map((option) => (
          <SelectItem
            key={option.value}
            value={option.value}
            className="rounded-[12px] py-2.5 text-sm font-medium text-gray-200 focus:bg-cyan-400/10 focus:text-cyan-200"
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export default function Home() {
  const { state } = useBotSocketContext();
  const { fmtINR } = useExchangeRate();

  const runningMode = (state.mode === "live" || state.mode === "demo") ? state.mode : "demo";
  const runningTrader = import.meta.env.VITE_TRADER_NAME || "Unknown";

  const [selectedMode, setSelectedMode] = useState<"demo" | "live">(runningMode);
  const [selectedTrader, setSelectedTrader] = useState<string>(runningTrader);
  const [traders, setTraders] = useState<string[]>([]);
  const [trades, setTrades] = useState<TraderTrade[]>([]);
  const [initialBalance, setInitialBalance] = useState<number>(state.wallet?.initial_balance ?? 0);

  const positions = Object.values(state.positions);

  useEffect(() => {
    setSelectedMode(runningMode);
  }, [runningMode]);

  useEffect(() => {
    setSelectedTrader(runningTrader);
  }, [runningTrader]);

  useEffect(() => {
    let active = true;

    const fetchWalletSeed = async () => {
      const { data } = await supabase
        .from("wallet")
        .select("initial_balance")
        .eq("mode", selectedMode)
        .limit(1)
        .single();

      if (active) {
        const row = data as WalletRow | null;
        setInitialBalance(row?.initial_balance ?? 0);
      }
    };

    fetchWalletSeed();

    return () => {
      active = false;
    };
  }, [selectedMode]);

  useEffect(() => {
    let active = true;

    const fetchTraders = async () => {
      const { data } = await supabase
        .from("trades")
        .select("trader_name")
        .eq("mode", selectedMode)
        .eq("status", "closed")
        .not("trader_name", "is", null);

      const unique = [...new Set(
        ((data as { trader_name: string }[] | null) || [])
          .map((item) => item.trader_name)
          .filter(Boolean)
      )];

      if (!active) return;
      setTraders(unique);
      if (unique.length > 0 && !unique.includes(selectedTrader)) {
        setSelectedTrader(unique.includes(runningTrader) ? runningTrader : unique[0]);
      }
    };

    fetchTraders();

    return () => {
      active = false;
    };
  }, [selectedMode, selectedTrader, runningTrader]);

  useEffect(() => {
    let active = true;

    const fetchTraderTrades = async () => {
      let query = supabase
        .from("trades")
        .select("net_pnl, pnl, fee")
        .eq("mode", selectedMode)
        .eq("status", "closed")
        .order("created_at", { ascending: true })
        .limit(2000);

      if (selectedTrader) {
        query = query.eq("trader_name", selectedTrader);
      }

      const { data } = await query;
      if (active) setTrades((data as TraderTrade[]) || []);
    };

    fetchTraderTrades();

    const channel = supabase
      .channel(`wallet_trader_${selectedMode}_${selectedTrader}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "trades", filter: `mode=eq.${selectedMode}` },
        fetchTraderTrades
      )
      .subscribe();

    return () => {
      active = false;
      supabase.removeChannel(channel);
    };
  }, [selectedMode, selectedTrader]);

  const traderStats = useMemo(() => {
    const totalNetPnl = trades.reduce((sum, trade) => sum + (trade.net_pnl || trade.pnl || 0), 0);
    const totalFees = trades.reduce((sum, trade) => sum + (trade.fee || 0), 0);
    const totalTrades = trades.length;
    const traderBalance = initialBalance + totalNetPnl;
    const totalPct = initialBalance > 0 ? (totalNetPnl / initialBalance) * 100 : 0;

    return {
      traderBalance,
      totalNetPnl,
      totalFees,
      totalTrades,
      totalPct,
    };
  }, [initialBalance, trades]);

  const isProfitUp = traderStats.totalNetPnl >= 0;
  const liveOpenTrades = selectedMode === runningMode ? positions.length : 0;
  const traderOptions = traders.length === 0
    ? [{ value: runningTrader, label: runningTrader }]
    : traders.map((trader) => ({ value: trader, label: trader }));
  const modeOptions = [
    { value: "demo", label: "DEMO" },
    { value: "live", label: "LIVE" },
  ];

  return (
    <main className="flex-1 overflow-y-auto bg-[#07090f] p-3 pb-24 md:p-4 md:pb-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-3">
        <section className="rounded-[28px] border border-[#1e2433] bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.10),_transparent_26%),linear-gradient(180deg,_#0d1117_0%,_#090d14_100%)] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/15 bg-cyan-400/8 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.18em] text-cyan-300">
                <Wallet size={12} />
                Wallet
              </div>
              <div className="mt-4 text-[30px] font-semibold leading-none tracking-tight text-white tabular-nums sm:text-[36px]">
                {fmtINR(traderStats.traderBalance)}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <span className={`text-sm font-semibold ${isProfitUp ? "text-green-400" : "text-red-400"}`}>
                  {isProfitUp ? "+" : ""}{fmtINR(traderStats.totalNetPnl)}
                </span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${isProfitUp ? "bg-green-500/10 text-green-300" : "bg-red-500/10 text-red-300"}`}>
                  {traderStats.totalPct >= 0 ? "+" : ""}{traderStats.totalPct.toFixed(2)}%
                </span>
              </div>
            </div>

            <div className="flex h-11 w-11 items-center justify-center rounded-[18px] border border-white/10 bg-white/[0.03] text-cyan-300">
              <UserRound size={20} />
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2">
            <SelectShell
              value={selectedMode}
              onChange={(value) => setSelectedMode(value as "demo" | "live")}
              placeholder="Select mode"
              options={modeOptions}
            />

            <SelectShell
              value={selectedTrader}
              onChange={setSelectedTrader}
              placeholder="Select trader"
              options={traderOptions}
            />
          </div>
        </section>

        <div className="grid grid-cols-2 gap-3">
          <SmallCard
            label="Start"
            value={fmtINR(initialBalance)}
            icon={<BadgeIndianRupee size={16} />}
          />
          <SmallCard
            label="Gain"
            value={`${isProfitUp ? "+" : ""}${fmtINR(traderStats.totalNetPnl)}`}
            icon={isProfitUp ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
            valueClass={isProfitUp ? "text-green-400" : "text-red-400"}
          />
          <SmallCard
            label="Fees"
            value={fmtINR(traderStats.totalFees)}
            icon={<Receipt size={16} />}
            valueClass="text-orange-300"
          />
          <SmallCard
            label="Trades"
            value={String(traderStats.totalTrades).padStart(2, "0")}
            icon={<Activity size={16} />}
          />
        </div>

        <section className="rounded-[24px] border border-[#1e2433] bg-[#0d1117] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-gray-500">Running</p>
            <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] font-medium text-gray-300">
              {selectedMode.toUpperCase()}
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-sm text-gray-400">Open Trades</span>
            <span className="text-lg font-semibold tracking-tight text-white tabular-nums">{liveOpenTrades}</span>
          </div>
        </section>
      </div>
    </main>
  );
}
