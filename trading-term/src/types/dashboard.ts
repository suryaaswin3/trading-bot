// ── Dashboard Data (GET /dashboard/data) ──────────────────────────────

export interface DashboardData {
  bot_status: string;
  bot_mode: string;
  last_heartbeat: Record<string, unknown> | null;
  current_position: CurrentPosition | null;
  daily_pnl: number;
  cumulative_pnl: number;
  trades_today: number;
  wins_today: number;
  losses_today: number;
  max_drawdown_today: number;
  kite_connected: boolean;
  last_order: Record<string, unknown> | null;
  last_alert: Record<string, unknown> | null;
  last_validation: Record<string, unknown> | null;
  recent_alerts: WebhookAlert[];
  recent_signals: NormalizedSignal[];
  recent_orders: ExecutionOrder[];
  recent_events: ControlEvent[];
  recent_errors: string[];
  kill_switch: KillSwitchState;
  telegram_healthy: boolean | null;
  positions?: PositionState[];
  portfolio_snapshot?: PortfolioSnapshot;
  closed_positions?: PositionState[];
}

export interface CurrentPosition {
  symbol: string | null;
  side: string | null;
  quantity: number;
  entry_price: number;
}

export interface PositionState {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  realized_pnl: number;
  unrealized_pnl: number;
  status: string;
  strategy_id: string;
  opened_at: string;
  closed_at: string | null;
  updated_at: string;
}

export interface PortfolioSnapshot {
  positions: PositionState[];
  total_exposure: number;
  total_unrealized_pnl: number;
  total_realized_pnl: number;
  position_count: number;
  largest_position_symbol: string;
  largest_position_pct: number;
  updated_at: string;
}

// ── Execution Orders ──────────────────────────────────────────────────

export type OrderStatus =
  | "pending"
  | "submitted"
  | "partially_filled"
  | "filled"
  | "rejected"
  | "cancelled";

export interface ExecutionOrder {
  id: string;
  signal_id: string;
  validation_id: string | null;
  mode: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number | null;
  order_type: string;
  status: OrderStatus;
  external_order_id: string | null;
  strategy: string;
  dedup_key: string | null;
  created_at: string;
  updated_at: string;
  validation_passed?: boolean | null;
  rejection_reason?: string | null;
}

// ── Webhook Alerts & Signals ──────────────────────────────────────────

export interface WebhookAlert {
  id: string;
  alert_id: string;
  received_at: string;
  authenticated: boolean;
  normalized_id: string | null;
}

export interface NormalizedSignal {
  id: string;
  webhook_alert_id: string;
  alert_id: string;
  symbol: string;
  side: string;
  strategy: string;
  timeframe: string;
  price: number | null;
  signal_timestamp: string;
  reason: string | null;
  normalized_at: string;
}

// ── Validation ────────────────────────────────────────────────────────

export interface ValidationCheckItem {
  check: string;
  passed: boolean;
  detail: string | null;
}

export interface ValidationResult {
  id: string;
  signal_id: string;
  passed: boolean;
  checks: ValidationCheckItem[];
  rejection_reason: string | null;
  validated_at: string;
}

// ── Positions ─────────────────────────────────────────────────────────

export interface PositionSnapshot {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  trades_today: number;
  daily_pnl: number;
  timestamp: string;
}

// ── Controls ──────────────────────────────────────────────────────────

export interface KillSwitchState {
  active: boolean;
  triggered_by: string;
  triggered_at: string | null;
  reason: string;
}

export interface ControlEvent {
  id: string;
  action: string;
  triggered_by: string;
  source: string;
  result: string;
  detail: string | null;
  created_at: string;
}

export interface ControlResponse {
  status: "success" | "error";
  action: string;
  command_id: string;
  message: string;
}

// ── Analytics (GET /dashboard/analytics) ──────────────────────────────

export interface DashboardAnalyticsData {
  execution_events: ExecutionOrder[];
  pnl_by_strategy: PnLByStrategy[];
  rejection_stats: RejectionStat[];
  daily_pnl_history: DailyPnlHistory[];
}

export interface PnLByStrategy {
  strategy: string;
  side: string;
  price: number;
  status: string;
  created_at: string;
}

export interface RejectionStat {
  rejection_reason: string;
  count: number;
}

export interface DailyPnlHistory {
  date: string;
  daily_pnl: number;
  trades_today: number;
  consecutive_losses: number;
}

// ── Equity Curve Point ────────────────────────────────────────────────

export interface EquityPoint {
  timestamp: string;
  daily_pnl: number;
  realized_pnl: number;
}