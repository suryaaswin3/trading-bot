"use client";

import { useApiStatus } from "@/hooks/useApiStatus";
import {
  deriveConnectionState,
  getStatusErrorMessage,
} from "@/lib/api";
import {
  BotStatusBadge,
  ModeBadge,
  KiteBadge,
  HeartbeatBadge,
  KillSwitchBadge,
  HealthBadge,
  ConnectionBadge,
} from "./StatusBadges";

export function TopStatusBar() {
  const {
    botStatus,
    statusError,
    health,
    healthError,
    killSwitch,
    loading,
    consecutiveFailures,
    heartbeatAge,
  } = useApiStatus();

  const conn = deriveConnectionState({
    health,
    healthError,
    botStatus,
    statusError,
    killSwitch,
    loading,
    consecutiveFailures,
    lastSuccessTime: 0,
  });

  const online = conn === "connected";
  const degraded = conn === "degraded";
  const errorMessage = getStatusErrorMessage(statusError ?? healthError);

  // Extract kite status from heartbest or health checks
  const kiteConnected =
    botStatus?.status === "running" &&
    !statusError;

  return (
    <header className="sticky top-0 z-50 border-b border-zinc-800 bg-zinc-950/95 backdrop-blur-sm">
      <div className="flex items-center gap-2 overflow-x-auto px-3 py-2 text-xs">
        {/* Left cluster — primary status */}
        <div className="flex items-center gap-2">
          <BotStatusBadge
            status={botStatus?.status ?? null}
            degraded={!online}
          />
          <ModeBadge
            mode={botStatus?.mode ?? null}
            degraded={!online}
          />
          <KiteBadge connected={kiteConnected} />
        </div>

        <span className="mx-1 h-4 w-px bg-zinc-800" />

        {/* Center cluster — operational metrics */}
        <div className="flex items-center gap-2">
          <HeartbeatBadge ageSec={heartbeatAge} />
          <KillSwitchBadge active={killSwitch} />
          <HealthBadge status={health?.status ?? null} />
        </div>

        {/* Right cluster — connection state fills the gap */}
        <div className="ml-auto flex items-center gap-2">
          <ConnectionBadge online={online} degraded={degraded} />
          {errorMessage && (
            <span
              className="max-w-48 truncate text-zinc-500"
              title={errorMessage}
            >
              {errorMessage}
            </span>
          )}
        </div>
      </div>
    </header>
  );
}