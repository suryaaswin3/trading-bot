// ── Health ──────────────────────────────────────────────────────────

export type HealthStatus = "pass" | "warn" | "fail";

export interface HealthCheckItem {
  component: string;
  status: string;
  detail: string;
}

export interface HealthResponse {
  status: HealthStatus;
  checks: HealthCheckItem[];
}

// ── Heartbeat ───────────────────────────────────────────────────────

export interface HeartbeatData {
  bot_status: string;
  bot_mode: string;
  last_action: string;
  trades_today: number;
  daily_pnl: number;
  kite_connected: boolean;
  timestamp: string;
}

// ── Bot Status ──────────────────────────────────────────────────────

export interface BotStatusData {
  status: BotStatusValue;
  mode: BotMode;
  updated_at: string;
  updated_by: string;
  detail: string;
}

export type BotStatusValue = "running" | "stopped" | "paused" | "starting" | "error";
export type BotMode = "paper" | "live";

// ── Status Response ─────────────────────────────────────────────────

export interface KillSwitchState {
  active: boolean;
  triggered_by: string;
  triggered_at: string | null;
  reason: string;
}

export interface StatusResponse {
  bot_status: BotStatusData | Record<string, never>;
  latest_heartbeat: HeartbeatData | Record<string, never>;
  kill_switch: KillSwitchState;
}

// ── API Result Wrapper ──────────────────────────────────────────────

export interface ApiResult<T> {
  data: T | null;
  error: string | null;
  timestamp: number;
  consecutiveFailures: number;
}

// ── Derived State ───────────────────────────────────────────────────

export interface StatusState {
  health: HealthResponse | null;
  healthError: string | null;
  botStatus: BotStatusData | null;
  statusError: string | null;
  killSwitch: boolean;
  loading: boolean;
  consecutiveFailures: number;
  lastSuccessTime: number;
}

export type ConnectionState = "connected" | "degraded" | "offline";