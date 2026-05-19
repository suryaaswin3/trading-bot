"use client";

import { cn } from "@/lib/utils";

interface StaleIndicatorProps {
  stale: boolean;
  offline: boolean;
}

/** 4px dot indicating data freshness: green=fresh, amber=stale, red=offline. */
export function StaleIndicator({ stale, offline }: StaleIndicatorProps) {
  if (!stale && !offline) return null;

  return (
    <span
      className={cn(
        "inline-block h-2 w-2 rounded-full",
        offline ? "bg-red-500" : "bg-amber-400",
      )}
      title={offline ? "Offline" : "Stale data"}
    />
  );
}