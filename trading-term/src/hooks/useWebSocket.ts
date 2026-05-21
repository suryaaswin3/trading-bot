"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { env } from "@/lib/env";

// ── Types ─────────────────────────────────────────────────────────────────

export type WsStatus = "connecting" | "connected" | "disconnected" | "error";

export interface WsMessage {
  type: string;
  data: unknown;
}

export interface UseWsOptions {
  /** WebSocket URL (ws://...). */
  url: string;
  /** Called for every parsed message from the server. */
  onMessage?: (msg: WsMessage) => void;
  /** Called when connection status changes. */
  onStatusChange?: (status: WsStatus) => void;
  /** Disable auto-connect (default true). */
  enabled?: boolean;
}

export interface UseWsResult {
  /** Current connection status. */
  status: WsStatus;
  /** Manually reconnect. */
  reconnect: () => void;
  /** Manually disconnect. */
  disconnect: () => void;
  /** Send a JSON message. */
  send: (msg: unknown) => void;
}

// ── Hook ──────────────────────────────────────────────────────────────────

export function useWebSocket(options: UseWsOptions): UseWsResult {
  const { url, onMessage, onStatusChange, enabled = true } = options;
  const [status, setStatus] = useState<WsStatus>("disconnected");

  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const onMsgRef = useRef(onMessage);
  const onStRef = useRef(onStatusChange);
  onMsgRef.current = onMessage;
  onStRef.current = onStatusChange;

  const updateStatus = useCallback((s: WsStatus) => {
    setStatus(s);
    onStRef.current?.(s);
  }, []);

  const disconnect = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    retryRef.current = 0;
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      if (
        wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING
      ) {
        wsRef.current.close();
      }
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!enabled) return;
    disconnect();

    updateStatus("connecting");

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      updateStatus("error");
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close();
        return;
      }
      retryRef.current = 0;
      updateStatus("connected");
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const parsed = JSON.parse(event.data) as WsMessage;
        onMsgRef.current?.(parsed);
      } catch {
        // Ignore non-JSON messages
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      if (mountedRef.current) {
        updateStatus("disconnected");
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onclose fires after onerror, so we just let onclose handle reconnect
      updateStatus("error");
    };

    wsRef.current = ws;
  }, [url, enabled, disconnect, updateStatus]);

  const scheduleReconnect = useCallback(() => {
    if (!enabled || !mountedRef.current) return;
    const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30_000);
    retryRef.current += 1;
    timerRef.current = setTimeout(() => {
      if (mountedRef.current) connect();
    }, delay);
  }, [enabled, connect]);

  const reconnect = useCallback(() => {
    retryRef.current = 0;
    connect();
  }, [connect]);

  const send = useCallback((msg: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) connect();
    return () => {
      mountedRef.current = false;
      disconnect();
    };
  }, [enabled, connect, disconnect]);

  return { status, reconnect, disconnect, send };
}