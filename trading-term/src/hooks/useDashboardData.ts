"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { env } from "@/lib/env";
import { api } from "@/lib/api";
import { safeArray } from "@/lib/utils";
import type { DashboardData } from "@/types/dashboard";

interface DashboardState {
  data: DashboardData | null;
  loading: boolean;
  error: string | null;
  lastSuccessTime: number;
}

const INITIAL: DashboardState = {
  data: null,
  loading: true,
  error: null,
  lastSuccessTime: 0,
};

export function useDashboardData(pollIntervalMs = env.dashboardPollIntervalMs) {
  const [state, setState] = useState<DashboardState>(INITIAL);
  const mountedRef = useRef(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    const result = await api.getDashboardData();
    if (!mountedRef.current) return;

    setState((prev) => ({
      ...prev,
      data: result.data,
      error: result.error,
      loading: false,
      lastSuccessTime:
        !result.error && result.data
          ? Date.now()
          : prev.lastSuccessTime,
    }));
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    poll();
    intervalRef.current = setInterval(poll, pollIntervalMs);
    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [poll, pollIntervalMs]);

  const isStale =
    !state.loading &&
    state.lastSuccessTime > 0 &&
    Date.now() - state.lastSuccessTime > env.staleThresholdMs;

  const isOffline = !state.loading && state.error !== null && state.data === null;

  return {
    ...state,
    isStale,
    isOffline,
    // Safe array helpers for consumers
    signals: safeArray<DashboardData["recent_signals"][number]>(state.data?.recent_signals),
    orders: safeArray<DashboardData["recent_orders"][number]>(state.data?.recent_orders),
    errors: safeArray<string>(state.data?.recent_errors),
    events: safeArray<DashboardData["recent_events"][number]>(state.data?.recent_events),
  };
}