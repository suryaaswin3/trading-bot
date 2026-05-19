"use client";

import { useEffect, useLayoutEffect, useRef, useState, useCallback } from "react";
import { env } from "@/lib/env";
import { api } from "@/lib/api";
import { safeArray } from "@/lib/utils";
import type { ExecutionOrder } from "@/types/dashboard";

const MAX_ORDERS = 200;

export function useExecutionFeed() {
  const [orders, setOrders] = useState<ExecutionOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newItemCount, setNewItemCount] = useState(0);
  const [lastSuccessTime, setLastSuccessTime] = useState(0);
  const mountedRef = useRef(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Scroll anchor ─────────────────────────────────────────────────
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const prevScrollHeightRef = useRef(0);

  const poll = useCallback(async () => {
    const result = await api.getDashboardAnalytics();
    if (!mountedRef.current) return;

    setLoading(false);

    if (result.error) {
      setError(result.error);
      return;
    }

    setError(null);
    setLastSuccessTime(Date.now());

    const incoming = safeArray<ExecutionOrder>(result.data?.execution_events);
    if (incoming.length === 0) return;

    // Capture scroll height before DOM update
    const el = scrollRef.current;
    if (el) prevScrollHeightRef.current = el.scrollHeight;

    setOrders((prev) => {
      const existingIds = new Set(prev.map((o) => o.id));
      const newOrders = incoming.filter((o) => !existingIds.has(o.id));
      if (newOrders.length === 0) return prev;
      setNewItemCount((c) => c + newOrders.length);
      return [...newOrders, ...prev].slice(0, MAX_ORDERS);
    });
  }, []);

  // Stabilise scroll position after prepend
  // Runs synchronously after React commits the DOM update, before paint
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const prev = prevScrollHeightRef.current;
    if (prev > 0 && el.scrollHeight > el.clientHeight) {
      el.scrollTop += el.scrollHeight - prev;
    }
    prevScrollHeightRef.current = 0;
  });

  const clearNewCount = useCallback(() => {
    setNewItemCount(0);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    poll();
    intervalRef.current = setInterval(poll, env.analyticsPollIntervalMs);
    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [poll]);

  const isStale =
    !loading &&
    lastSuccessTime > 0 &&
    Date.now() - lastSuccessTime > env.staleThresholdMs;

  const isOffline = !loading && error !== null && orders.length === 0;

  return {
    orders,
    loading,
    error,
    newItemCount,
    clearNewCount,
    isStale,
    isOffline,
    scrollRef,
  };
}