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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[10px] uppercase tracking-wider text-zinc-600">{label}</span>
      <span className="text-xs font-medium text-zinc-300">{value}</span>
    </div>
  );
}

function formatPrice(n: number): string {
  return n.toFixed(2);
}

export function PositionPanel() {
  const { data, loading, error, isStale, isOffline } = useDashboardData();
  const pos = data?.current_position;
  const hasPosition = pos && pos.symbol && pos.side;

  if (loading && !data) {
    return (
      <PanelShell title="Position">
        <div className="flex items-center justify-center py-8">
          <span className="text-xs text-zinc-600 animate-pulse">Loading...</span>
        </div>
      </PanelShell>
    );
  }

  if (error && !data) {
    return (
      <PanelShellWithIndicator title="Position" stale={isStale} offline={isOffline}>
        <div className="flex items-center justify-center py-8">
          <span className="text-xs text-red-500">{error}</span>
        </div>
      </PanelShellWithIndicator>
    );
  }

  if (!hasPosition) {
    return (
      <PanelShellWithIndicator title="Position" stale={isStale} offline={isOffline}>
        <div className="flex items-center justify-center py-8">
          <span className="text-xs text-zinc-700">No open position</span>
        </div>
      </PanelShellWithIndicator>
    );
  }

  return (
    <PanelShellWithIndicator title="Position" stale={isStale} offline={isOffline}>
      <div className="space-y-1.5 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-zinc-100">{pos.symbol}</span>
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
              pos.side === "LONG"
                ? "bg-emerald-950/60 text-emerald-400"
                : "bg-red-950/60 text-red-400",
            )}
          >
            {pos.side}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-1 pt-1">
          <Metric label="Qty" value={String(pos.quantity)} />
          <Metric label="Entry" value={pos.entry_price ? formatPrice(pos.entry_price) : "--"} />
          <Metric label="Real. PnL" value="--" />
          <Metric label="Unreal. PnL" value="--" />
          <Metric
            label="Exposure"
            value={
              pos.quantity && pos.entry_price
                ? formatPrice(pos.quantity * pos.entry_price)
                : "--"
            }
          />
        </div>
      </div>
    </PanelShellWithIndicator>
  );
}