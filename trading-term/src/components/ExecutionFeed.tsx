"use client";

import { useExecutionFeed } from "@/hooks/useExecutionFeed";
import { ExecutionRow } from "./ExecutionRow";
import { StaleIndicator } from "./StaleIndicator";

export function ExecutionFeed() {
  const { orders, loading, error, newItemCount, clearNewCount, isStale, isOffline, scrollRef } = useExecutionFeed();
  const isEmpty = !loading && orders.length === 0;
  const showNewBadge = newItemCount > 0;

  return (
    <section className="flex flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/50">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-1.5">
        <h2 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-zinc-400 uppercase">
          Execution Feed
          <StaleIndicator stale={isStale} offline={isOffline} />
        </h2>
        <div className="flex items-center gap-2">
          {showNewBadge && (
            <button
              onClick={clearNewCount}
              className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300 transition-colors"
            >
              {newItemCount} new
            </button>
          )}
          <span className="text-[10px] text-zinc-600">{orders.length}</span>
        </div>
      </div>

      {/* Column headers */}
      <div className="flex items-center gap-2 border-b border-zinc-800/50 px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
        <span className="w-16 shrink-0">Time</span>
        <span className="w-14 shrink-0">Symbol</span>
        <span className="w-10 shrink-0">Side</span>
        <span className="w-10 shrink-0 text-right">Qty</span>
        <span className="w-14 shrink-0">Status</span>
        <span className="w-16 shrink-0 text-right">PnL</span>
        <span className="min-w-0 flex-1">Strategy</span>
        <span className="w-12 shrink-0">Val.</span>
      </div>

      {/* Rows */}
      <div ref={scrollRef} className="max-h-[60vh] overflow-y-auto">
        {loading && orders.length === 0 && (
          <div className="flex items-center justify-center py-12">
            <span className="text-xs text-zinc-600 animate-pulse">Loading...</span>
          </div>
        )}

        {error && orders.length === 0 && (
          <div className="flex items-center justify-center py-12">
            <span className="text-xs text-red-500">{error}</span>
          </div>
        )}

        {isEmpty && (
          <div className="flex items-center justify-center py-12">
            <span className="text-xs text-zinc-700">No executions yet</span>
          </div>
        )}

        {orders.map((order, i) => (
          <ExecutionRow
            key={order.id || i}
            order={order}
            isLatest={i === 0}
          />
        ))}
      </div>
    </section>
  );
}