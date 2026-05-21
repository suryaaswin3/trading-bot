"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { env } from "@/lib/env";
import { api } from "@/lib/api";
import { safeArray } from "@/lib/utils";
import { useWebSocket, type WsMessage } from "./useWebSocket";
import type { DashboardData } from "@/types/dashboard";

interface DashboardState {
  data: DashboardData | null;
  loading: boolean;
  error: string | null;
  lastSuccessTime: number;
}

interface UseDashboardResult extends DashboardState {
  isStale: boolean;
  isOffline: boolean;
  signals: ReturnType<typeof safeArray>;
  orders: ReturnType<typeof safeArray>;
  errors: ReturnType<typeof safeArray>;
  events: ReturnType<typeof safeArray>;
}

const INITIAL: DashboardState = {
  data: null,
  loading: true,
  error: null,
  lastSuccessTime: 0,
};

function deriveWsUrl(): string {
  const base = env.opsApiUrl.replace(/\/+$/, "");
  // If the URL is relative (starts with /), use the page's origin
  if (base.startsWith("/")) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${base}/ws/dashboard`;
  }
  // Absolute URL: swap http/https to ws/wss
  return base.replace(/^http/, "ws") + "/ws/dashboard";
}

export function useDashboardData(pollIntervalMs = env.dashboardPollIntervalMs): UseDashboardResult {
  const [state, setState] = useState<DashboardState>(INITIAL);
  const [wsConnected, setWsConnected] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  const polling = useRef(false);

  // Polling fallback
  const poll = useCallback(async () => {
    const result = await api.getDashboardData();
    if (!mountedRef.current) return;
    setState((prev) => ({
      ...prev,
      data: result.data,
      error: result.error,
      loading: false,
      lastSuccessTime:
        !result.error && result.data ? Date.now() : prev.lastSuccessTime,
    }));
  }, []);

  // Handle WebSocket messages
  const onWsMessage = useCallback((msg: WsMessage) => {
    if (!mountedRef.current) return;
    if (msg.type === "snapshot" && msg.data) {
      polling.current = false;
      setState({
        data: msg.data as DashboardData,
        loading: false,
        error: null,
        lastSuccessTime: Date.now(),
      });
    }
    // heartbeat updates lastSuccessTime to avoid stale detection
    if (msg.type === "heartbeat") {
      setState((prev) => ({ ...prev, lastSuccessTime: Date.now() }));
    }
  }, []);

  const ws = useWebSocket({
    url: deriveWsUrl(),
    onMessage: onWsMessage,
    onStatusChange: (status) => {
      setWsConnected(status === "connected");
    },
  });

  // Fallback to polling when WS is not connected
  useEffect(() => {
    mountedRef.current = true;

    // Start polling after a grace period if WS hasn't connected
    const fallbackTimer = setTimeout(() => {
      if (!wsConnected && mountedRef.current) {
        polling.current = true;
        poll();
        intervalRef.current = setInterval(poll, pollIntervalMs);
      }
    }, 5_000);

    return () => {
      mountedRef.current = false;
      clearTimeout(fallbackTimer);
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [wsConnected, poll, pollIntervalMs]);

  // Switch from polling to WS when WS connects
  useEffect(() => {
    if (wsConnected && intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
      polling.current = false;
    }
  }, [wsConnected]);

  const isStale =
    !state.loading &&
    state.lastSuccessTime > 0 &&
    Date.now() - state.lastSuccessTime > env.staleThresholdMs;

  const isOffline = !state.loading && state.error !== null && state.data === null;

  return {
    ...state,
    isStale,
    isOffline,
    signals: safeArray<DashboardData["recent_signals"][number]>(state.data?.recent_signals),
    orders: safeArray<DashboardData["recent_orders"][number]>(state.data?.recent_orders),
    errors: safeArray<string>(state.data?.recent_errors),
    events: safeArray<DashboardData["recent_events"][number]>(state.data?.recent_events),
  };
}