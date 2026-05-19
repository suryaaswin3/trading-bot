import { env } from "./env";
import type {
  ApiResult,
  StatusResponse,
  HealthResponse,
  StatusState,
  ConnectionState,
  BotStatusData,
} from "./types";
import type {
  DashboardData,
  DashboardAnalyticsData,
  ControlResponse,
} from "@/types/dashboard";

// ── Low-Level Fetch with Timeout ────────────────────────────────────

async function fetchWithTimeout<T>(
  path: string,
  timeoutMs = env.requestTimeoutMs,
): Promise<ApiResult<T>> {
  const url = `${env.opsApiUrl}${path}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return {
        data: null,
        error: `HTTP ${response.status}`,
        timestamp: Date.now(),
        consecutiveFailures: 0,
      };
    }
    const text = await response.text();
    let parsed: T;
    try {
      parsed = JSON.parse(text) as T;
    } catch {
      return {
        data: null,
        error: "Invalid JSON response",
        timestamp: Date.now(),
        consecutiveFailures: 0,
      };
    }
    return {
      data: parsed,
      error: null,
      timestamp: Date.now(),
      consecutiveFailures: 0,
    };
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return {
        data: null,
        error: "timeout",
        timestamp: Date.now(),
        consecutiveFailures: 0,
      };
    }
    const message =
      err instanceof TypeError
        ? "network_error"
        : err instanceof Error
          ? err.message
          : "unknown";
    return {
      data: null,
      error: message,
      timestamp: Date.now(),
      consecutiveFailures: 0,
    };
  } finally {
    clearTimeout(timeoutId);
  }
}

// ── High-Level API ──────────────────────────────────────────────────

const _failureTracker = { count: 0 };

export const api = {
  async getStatus(): Promise<ApiResult<StatusResponse>> {
    const result = await fetchWithTimeout<StatusResponse>("/status");
    if (result.error) {
      _failureTracker.count++;
      return { ...result, consecutiveFailures: _failureTracker.count };
    }
    _failureTracker.count = 0;
    return result;
  },

  async getHealth(): Promise<ApiResult<HealthResponse>> {
    const result = await fetchWithTimeout<HealthResponse>("/health");
    if (result.error) {
      _failureTracker.count++;
      return { ...result, consecutiveFailures: _failureTracker.count };
    }
    _failureTracker.count = 0;
    return result;
  },

  async getDashboardData(): Promise<ApiResult<DashboardData>> {
    const result = await fetchWithTimeout<DashboardData>("/dashboard/data");
    if (result.error) {
      _failureTracker.count++;
      return { ...result, consecutiveFailures: _failureTracker.count };
    }
    _failureTracker.count = 0;
    return result;
  },

  async getDashboardAnalytics(): Promise<ApiResult<DashboardAnalyticsData>> {
    const result = await fetchWithTimeout<DashboardAnalyticsData>("/dashboard/analytics");
    if (result.error) {
      _failureTracker.count++;
      return { ...result, consecutiveFailures: _failureTracker.count };
    }
    _failureTracker.count = 0;
    return result;
  },

  get failureCount(): number {
    return _failureTracker.count;
  },
};

// ── Controls ──────────────────────────────────────────────────────────

let _controlApiKey: string | null = null;

export function setControlApiKey(key: string) {
  _controlApiKey = key;
}

export async function postControlAction(
  action: string,
  params?: Record<string, unknown>,
): Promise<ApiResult<ControlResponse>> {
  const url = `${env.opsApiUrl}/control/${action}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), env.requestTimeoutMs);

  try {
    const response = await fetch(url, {
      method: "POST",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(_controlApiKey ? { "X-API-Key": _controlApiKey } : {}),
      },
      body: params ? JSON.stringify({ params }) : "{}",
    });
    if (!response.ok) {
      return {
        data: null,
        error: `HTTP ${response.status}`,
        timestamp: Date.now(),
        consecutiveFailures: 0,
      };
    }
    const text = await response.text();
    const parsed: ControlResponse = JSON.parse(text);
    return {
      data: parsed,
      error: null,
      timestamp: Date.now(),
      consecutiveFailures: 0,
    };
  } catch (err) {
    const message =
      err instanceof TypeError
        ? "network_error"
        : err instanceof Error
          ? err.message
          : "unknown";
    return {
      data: null,
      error: message,
      timestamp: Date.now(),
      consecutiveFailures: 0,
    };
  } finally {
    clearTimeout(timeoutId);
  }
}

// ── Stale Detection ─────────────────────────────────────────────────────────────

export function isStale(timestamp: number): boolean {
  return Date.now() - timestamp > env.staleThresholdMs;
}

// ── Heartbeat Age ───────────────────────────────────────────────────

export function getHeartbeatAgeSec(
  botStatus: BotStatusData | null,
  heartbeatTimestamp?: string,
): number | null {
  if (!heartbeatTimestamp) return null;
  try {
    const hb = new Date(heartbeatTimestamp).getTime();
    return Math.floor((Date.now() - hb) / 1000);
  } catch {
    return null;
  }
}

export function isHeartbeatStale(ageSec: number | null): boolean {
  return ageSec !== null && ageSec > env.heartbeatStaleThresholdSec;
}

// ── Connection State ────────────────────────────────────────────────

export function deriveConnectionState(
  state: StatusState,
): ConnectionState {
  if (state.loading) return "connected";
  if (state.consecutiveFailures >= 3) return "offline";
  if (state.consecutiveFailures >= 1) return "degraded";
  return "connected";
}

// ── Status Error Normalization ──────────────────────────────────────

export function getStatusErrorMessage(error: string | null): string | null {
  if (!error) return null;
  switch (error) {
    case "timeout":
      return "Backend request timed out";
    case "network_error":
      return "Cannot reach backend server";
    default:
      return `API error: ${error}`;
  }
}

// ── Safe Bot Status Extractors ──────────────────────────────────────

export function safeBotStatus(raw: StatusResponse["bot_status"]): BotStatusData | null {
  if (!raw || typeof raw !== "object" || !("status" in raw)) return null;
  const s = raw as Record<string, unknown>;
  if (typeof s.status !== "string") return null;
  return {
    status: s.status as BotStatusData["status"],
    mode: (s.mode as BotStatusData["mode"]) ?? "paper",
    updated_at: (s.updated_at as string) ?? "",
    updated_by: (s.updated_by as string) ?? "",
    detail: (s.detail as string) ?? "",
  };
}