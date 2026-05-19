"use client";

import { useDashboardData } from "@/hooks/useDashboardData";
import { cn } from "@/lib/utils";
import { StaleIndicator } from "./StaleIndicator";

function PanelShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/50">
      <div className="border-b border-zinc-800 px-3 py-1.5">
        <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

function PanelShellWithIndicator({ title, stale, offline, children }: { title: string; stale: boolean; offline: boolean; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/50">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-1.5">
        <h2 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-zinc-400 uppercase">
          {title}
          <StaleIndicator stale={stale} offline={offline} />
        </h2>
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[10px] uppercase tracking-wider text-zinc-600">{label}</span>
      <span className={cn("text-xs font-medium", color ?? "text-zinc-300")}>{value}</span>
    </div>
  );
}

function formatPnl(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
}

function pnlColor(n: number): string | undefined {
  if (n > 0) return "text-emerald-400";
  if (n < 0) return "text-red-400";
  return undefined;
}

export function PnLRiskPanel() {
  const { data, loading, error, isStale, isOffline } = useDashboardData();

  if (loading && !data) {
    return (
      <PanelShell title="PnL & Risk">
        <div className="flex items-center justify-center py-6">
          <span className="text-xs text-zinc-600 animate-pulse">Loading...</span>
        </div>
      </PanelShell>
    );
  }

  if (error && !data) {
    return (
      <PanelShellWithIndicator title="PnL & Risk" stale={isStale} offline={isOffline}>
        <div className="flex items-center justify-center py-6">
          <span className="text-xs text-red-500">{error}</span>
        </div>
      </PanelShellWithIndicator>
    );
  }

  const dpnl = data?.daily_pnl ?? 0;
  const cpnl = data?.cumulative_pnl ?? 0;
  const trades = data?.trades_today ?? 0;
  const wins = data?.wins_today ?? 0;
  const losses = data?.losses_today ?? 0;
  const dd = data?.max_drawdown_today ?? 0;

  return (
    <PanelShellWithIndicator title="PnL & Risk" stale={isStale} offline={isOffline}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 px-3 py-2">
        <Metric label="Daily PnL" value={formatPnl(dpnl)} color={pnlColor(dpnl)} />
        <Metric label="Cum. PnL" value={formatPnl(cpnl)} color={pnlColor(cpnl)} />
        <Metric label="Trades" value={String(trades)} />
        <Metric label="Wins" value={String(wins)} color="text-emerald-400" />
        <Metric label="Losses" value={String(losses)} color="text-red-400" />
        <Metric label="Drawdown" value={formatPnl(dd)} color="text-red-400" />
      </div>
    </PanelShellWithIndicator>
  );
}