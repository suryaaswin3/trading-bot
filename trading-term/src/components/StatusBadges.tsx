"use client";

import type { BotStatusValue, BotMode } from "@/lib/types";
import { cn } from "@/lib/utils";

// ── Shared badge ring ───────────────────────────────────────────────

const BADGE_BASE =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium tracking-wide ring-1 ring-inset";

// ── Bot Status Badge ────────────────────────────────────────────────

const STATUS_STYLES: Record<BotStatusValue, string> = {
  running:
    "bg-emerald-950/60 text-emerald-400 ring-emerald-800/60",
  stopped: "bg-red-950/60 text-red-400 ring-red-800/60",
  paused: "bg-amber-950/60 text-amber-400 ring-amber-800/60",
  starting: "bg-sky-950/60 text-sky-400 ring-sky-800/60",
  error: "bg-rose-950/60 text-rose-400 ring-rose-800/60",
};

const STATUS_LABELS: Record<BotStatusValue, string> = {
  running: "RUNNING",
  stopped: "STOPPED",
  paused: "PAUSED",
  starting: "STARTING",
  error: "ERROR",
};

interface BotStatusBadgeProps {
  status: BotStatusValue | null | undefined;
  degraded?: boolean;
}

export function BotStatusBadge({ status, degraded }: BotStatusBadgeProps) {
  if (!status || degraded) {
    return (
      <span className={cn(BADGE_BASE, "bg-zinc-800/60 text-zinc-500 ring-zinc-700/60")}>
        <span className="h-1.5 w-1.5 rounded-full bg-zinc-600" />
        ?OFFLINE
      </span>
    );
  }
  return (
    <span className={cn(BADGE_BASE, STATUS_STYLES[status])}>
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "running" && "bg-emerald-400",
          status === "stopped" && "bg-red-400",
          status === "paused" && "bg-amber-400",
          status === "starting" && "bg-sky-400",
          status === "error" && "bg-rose-400",
        )}
      />
      {STATUS_LABELS[status]}
    </span>
  );
}

// ── Mode Badge ──────────────────────────────────────────────────────

interface ModeBadgeProps {
  mode: BotMode | null | undefined;
  degraded?: boolean;
}

export function ModeBadge({ mode, degraded }: ModeBadgeProps) {
  if (!mode || degraded) {
    return (
      <span className={cn(BADGE_BASE, "bg-zinc-800/60 text-zinc-500 ring-zinc-700/60")}>
        ????
      </span>
    );
  }
  const isPaper = mode === "paper";
  return (
    <span
      className={cn(
        BADGE_BASE,
        isPaper
          ? "bg-amber-950/60 text-amber-400 ring-amber-800/60"
          : "bg-red-950/60 text-red-400 ring-red-800/60",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          isPaper ? "bg-amber-400" : "bg-red-400",
        )}
      />
      {isPaper ? "PAPER" : "LIVE"}
    </span>
  );
}

// ── Kite Badge ──────────────────────────────────────────────────────

interface KiteBadgeProps {
  connected: boolean | null | undefined;
}

export function KiteBadge({ connected }: KiteBadgeProps) {
  const isConn = connected === true;
  return (
    <span
      className={cn(
        BADGE_BASE,
        isConn
          ? "bg-emerald-950/60 text-emerald-400 ring-emerald-800/60"
          : "bg-red-950/60 text-red-400 ring-red-800/60",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          isConn ? "bg-emerald-400" : "bg-red-400",
        )}
      />
      KITE {isConn ? "CONNECTED" : "DISCONNECTED"}
    </span>
  );
}

// ── Heartbeat Age Badge ─────────────────────────────────────────────

interface HeartbeatBadgeProps {
  ageSec: number | null;
}

export function HeartbeatBadge({ ageSec }: HeartbeatBadgeProps) {
  const stale = ageSec !== null && ageSec >= 120;
  const missing = ageSec === null;

  let color: string;
  let label: string;

  if (missing) {
    color = "bg-zinc-800/60 text-zinc-500 ring-zinc-700/60";
    label = "HB: --";
  } else if (stale) {
    color = "bg-red-950/60 text-red-400 ring-red-800/60";
    label = `HB: ${ageSec}s STALE`;
  } else {
    color = "bg-emerald-950/60 text-emerald-400 ring-emerald-800/60";
    label = `HB: ${ageSec}s`;
  }

  return (
    <span className={cn(BADGE_BASE, color)}>
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          missing && "bg-zinc-600",
          stale && "bg-red-400",
          !missing && !stale && "bg-emerald-400",
        )}
      />
      {label}
    </span>
  );
}

// ── Kill Switch Badge ───────────────────────────────────────────────

interface KillSwitchBadgeProps {
  active: boolean;
}

export function KillSwitchBadge({ active }: KillSwitchBadgeProps) {
  return (
    <span
      className={cn(
        BADGE_BASE,
        active
          ? "bg-red-950/60 text-red-400 ring-red-800/60"
          : "bg-zinc-800/60 text-zinc-500 ring-zinc-600/60",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          active ? "bg-red-400" : "bg-zinc-600",
        )}
      />
      KILL {active ? "ACTIVE" : "SAFE"}
    </span>
  );
}

// ── Health Badge ────────────────────────────────────────────────────

interface HealthBadgeProps {
  status: string | null | undefined;
}

export function HealthBadge({ status }: HealthBadgeProps) {
  if (!status) {
    return (
      <span className={cn(BADGE_BASE, "bg-zinc-800/60 text-zinc-500 ring-zinc-700/60")}>
        HEALTH: --
      </span>
    );
  }

  const color =
    status === "pass"
      ? "bg-emerald-950/60 text-emerald-400 ring-emerald-800/60"
      : status === "warn"
        ? "bg-amber-950/60 text-amber-400 ring-amber-800/60"
        : "bg-red-950/60 text-red-400 ring-red-800/60";

  return (
    <span className={cn(BADGE_BASE, color)}>
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "pass" && "bg-emerald-400",
          status === "warn" && "bg-amber-400",
          status !== "pass" && status !== "warn" && "bg-red-400",
        )}
      />
      HEALTH: {status.toUpperCase()}
    </span>
  );
}

// ── Connection Indicator ────────────────────────────────────────────

interface ConnectionBadgeProps {
  online: boolean;
  degraded: boolean;
}

export function ConnectionBadge({ online, degraded }: ConnectionBadgeProps) {
  if (online && !degraded) return null;

  const color = degraded
    ? "bg-amber-950/60 text-amber-400 ring-amber-800/60"
    : "bg-red-950/60 text-red-400 ring-red-800/60";
  const label = degraded ? "DEGRADED" : "OFFLINE";

  return (
    <span className={cn(BADGE_BASE, color)}>
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          degraded ? "bg-amber-400" : "bg-red-400",
        )}
      />
      {label}
    </span>
  );
}