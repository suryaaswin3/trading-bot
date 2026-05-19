"use client";

import type { NormalizedSignal } from "@/types/dashboard";
import { cn } from "@/lib/utils";

interface SignalRowProps {
  signal: NormalizedSignal;
}

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

export function SignalRow({ signal }: SignalRowProps) {
  return (
    <div className="flex items-center gap-2 border-b border-zinc-800/30 px-3 py-1 text-xs hover:bg-zinc-800/30 transition-colors">
      <span className="w-16 shrink-0 font-mono text-zinc-500">
        {formatTime(signal.signal_timestamp || signal.normalized_at)}
      </span>
      <span className="w-14 shrink-0 font-medium text-zinc-200">
        {signal.symbol}
      </span>
      <span
        className={cn(
          "w-12 shrink-0 font-medium",
          signal.side === "BUY" ? "text-emerald-400" : "text-red-400",
        )}
      >
        {signal.side}
      </span>
      <span className="min-w-0 flex-1 truncate text-zinc-400">
        {signal.strategy ?? "--"}
      </span>
      <span className="w-14 shrink-0 text-right font-medium text-sky-400">
        SIGNAL
      </span>
    </div>
  );
}
