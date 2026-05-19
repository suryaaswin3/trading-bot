"use client";

import { useDashboardData } from "@/hooks/useDashboardData";
import { SignalRow } from "./SignalRow";
import { StaleIndicator } from "./StaleIndicator";

export function SignalFeed() {
  const { loading, error, signals, isStale, isOffline } = useDashboardData();
  const isEmpty = !loading && signals.length === 0;

  return (
    <section className="flex flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/50">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-1.5">
        <h2 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-zinc-400 uppercase">
          Signal Feed
          <StaleIndicator stale={isStale} offline={isOffline} />
        </h2>
      </div>

      {/* Column headers */}
      <div className="flex items-center gap-2 border-b border-zinc-800/50 px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
        <span className="w-16 shrink-0">Time</span>
        <span className="w-14 shrink-0">Symbol</span>
        <span className="w-12 shrink-0">Side</span>
        <span className="min-w-0 flex-1">Strategy</span>
        <span className="w-14 shrink-0">Status</span>
      </div>

      <div className="max-h-48 overflow-y-auto">
        {loading && signals.length === 0 && (
          <div className="flex items-center justify-center py-6">
            <span className="text-xs text-zinc-600 animate-pulse">Loading...</span>
          </div>
        )}

        {error && signals.length === 0 && (
          <div className="flex items-center justify-center py-6">
            <span className="text-xs text-red-500">{error}</span>
          </div>
        )}

        {isEmpty && (
          <div className="flex items-center justify-center py-6">
            <span className="text-xs text-zinc-700">No signals yet</span>
          </div>
        )}

        {signals.map((signal) => (
          <SignalRow key={signal.id} signal={signal} />
        ))}
      </div>
    </section>
  );
}