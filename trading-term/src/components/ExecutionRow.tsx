"use client";

import type { ExecutionOrder } from "@/types/dashboard";
import { cn } from "@/lib/utils";

interface ExecutionRowProps {
  order: ExecutionOrder;
  isLatest?: boolean;
}

const STATUS_LABELS: Record<string, string> = {
  filled: "FILLED",
  partially_filled: "PART",
  submitted: "SUBMIT",
  pending: "PEND",
  rejected: "REJECT",
  cancelled: "CANCEL",
};

const STATUS_COLORS: Record<string, string> = {
  filled: "text-emerald-400",
  partially_filled: "text-emerald-300",
  submitted: "text-sky-400",
  pending: "text-amber-400",
  rejected: "text-red-400",
  cancelled: "text-zinc-500",
};

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "--:--:--";
  }
}

export function ExecutionRow({ order, isLatest }: ExecutionRowProps) {
  const pnl = 0; // ExecutionOrder doesn't carry PnL in this API version
  const pnlColor =
    pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-red-400" : "text-zinc-500";
  const statusColor = STATUS_COLORS[order.status] ?? "text-zinc-500";

  return (
    <div
      className={cn(
        "flex items-center gap-2 border-b border-zinc-800/30 px-3 py-1 text-xs transition-colors hover:bg-zinc-800/30",
        isLatest && "bg-emerald-950/10",
      )}
    >
      <span className="w-16 shrink-0 font-mono text-zinc-500">
        {formatTime(order.created_at)}
      </span>
      <span className="w-14 shrink-0 font-medium text-zinc-200">
        {order.symbol}
      </span>
      <span
        className={cn(
          "w-10 shrink-0 font-medium",
          order.side === "BUY" ? "text-emerald-400" : "text-red-400",
        )}
      >
        {order.side}
      </span>
      <span className="w-10 shrink-0 text-right text-zinc-300">
        {order.quantity}
      </span>
      <span className={cn("w-14 shrink-0 font-medium", statusColor)}>
        {STATUS_LABELS[order.status] ?? order.status}
      </span>
      <span className={cn("w-16 shrink-0 text-right", pnlColor)}>
        {pnl === 0 ? "--" : pnl > 0 ? `+${pnl}` : `${pnl}`}
      </span>
      <span className="min-w-0 flex-1 truncate text-zinc-400">
        {order.strategy ?? "--"}
      </span>
      <span
        className={cn(
          "w-12 shrink-0 text-right font-medium",
          order.validation_passed === true && "text-emerald-400",
          order.validation_passed === false && "text-red-400",
          order.validation_passed == null && "text-zinc-600",
        )}
      >
        {order.validation_passed === true
          ? "PASS"
          : order.validation_passed === false
            ? "FAIL"
            : "--"}
      </span>
    </div>
  );
}