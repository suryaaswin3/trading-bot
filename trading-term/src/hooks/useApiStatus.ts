"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { env } from "@/lib/env";
import { api, safeBotStatus, getHeartbeatAgeSec } from "@/lib/api";
import type { StatusState, HealthResponse, BotStatusData } from "@/lib/types";

const INITIAL: StatusState = {
  health: null,
  healthError: null,
  botStatus: null,
  statusError: null,
  killSwitch: false,
  loading: true,
  consecutiveFailures: 0,
  lastSuccessTime: 0,
};

export function useApiStatus() {
  const [state, setState] = useState<StatusState>(INITIAL);
  const [heartbeatAge, setHeartbeatAge] = useState<number | null>(null);
  const mountedRef = useRef(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    const [statusRes, healthRes] = await Promise.all([
      api.getStatus(),
      api.getHealth(),
    ]);

    if (!mountedRef.current) return;

    const botStatus = statusRes.data
      ? safeBotStatus(statusRes.data.bot_status)
      : null;

    setState((prev) => ({
      ...prev,
      health: healthRes.data as HealthResponse | null,
      healthError: healthRes.error,
      botStatus,
      statusError: statusRes.error,
      // kill_switch from API is { active: boolean } — extract the boolean
      killSwitch:
        typeof statusRes.data?.kill_switch === "object" &&
        statusRes.data?.kill_switch !== null
          ? (statusRes.data.kill_switch as { active: boolean }).active
          : typeof statusRes.data?.kill_switch === "boolean"
            ? statusRes.data.kill_switch
            : false,
      loading: false,
      consecutiveFailures: Math.max(
        healthRes.consecutiveFailures,
        statusRes.consecutiveFailures,
      ),
      lastSuccessTime:
        !healthRes.error && !statusRes.error
          ? Date.now()
          : prev.lastSuccessTime,
    }));

    if (statusRes.data?.latest_heartbeat?.timestamp) {
      const age = getHeartbeatAgeSec(
        botStatus,
        statusRes.data.latest_heartbeat.timestamp,
      );
      setHeartbeatAge(age);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    poll();
    intervalRef.current = setInterval(poll, env.pollIntervalMs);
    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [poll]);

  return { ...state, heartbeatAge };
}