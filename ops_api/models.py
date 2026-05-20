"""Pydantic models for all ops API data entities."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# ── Enums ────────────────────────────────────────────────────────────────


class SignalSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class BotStatusValue(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    STARTING = "starting"
    ERROR = "error"


class BotMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class ControlAction(StrEnum):
    START = "start"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"
    FLATTEN = "flatten"
    SET_MODE = "set_mode"
    RELOAD_CONFIG = "reload_config"


class ValidationCheck(StrEnum):
    MARKET_OPEN = "market_open"
    STRATEGY_ENABLED = "strategy_enabled"
    BOT_MODE = "bot_mode"
    BOT_PAUSED = "bot_paused"
    DUPLICATE_ALERT = "duplicate_alert"
    COOLDOWN = "cooldown"
    MAX_TRADES_DAY = "max_trades_day"
    MAX_DAILY_LOSS = "max_daily_loss"
    ALLOWED_SYMBOL = "allowed_symbol"
    POSITION_CONFLICT = "position_conflict"
    PRICE_SANITY = "price_sanity"
    ALERT_STALE = "alert_stale"
    BROKER_CONNECTIVITY = "broker_connectivity"


class HealthComponent(StrEnum):
    API_SERVER = "api_server"
    DATABASE = "database"
    KITE_CONNECT = "kite_connect"
    BOT_PROCESS = "bot_process"
    CONFIG_LOAD = "config_load"


class CommandStatus(StrEnum):
    PENDING = "pending"
    ACKED = "acked"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Webhook Models ───────────────────────────────────────────────────────


class TradingViewAlert(BaseModel):
    """Expected contract from TradingView webhook POST body."""

    secret: str = ""
    alert_id: str = ""
    symbol: str = ""
    side: SignalSide | str = ""
    strategy: str = ""
    timeframe: str = ""
    price: float = 0.0
    timestamp: str = ""
    reason: str = ""


class WebhookAlert(BaseModel):
    """Stored raw webhook alert."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    alert_id: str = ""
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=datetime.utcnow)
    source_ip: str = ""
    authenticated: bool = False
    normalized_id: str | None = None


class NormalizedSignal(BaseModel):
    """Cleaned/normalized signal extracted from a webhook alert."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    webhook_alert_id: str = ""
    alert_id: str = ""
    symbol: str = ""
    side: SignalSide = SignalSide.BUY
    strategy: str = ""
    timeframe: str = ""
    price: float = 0.0
    signal_timestamp: datetime | None = None
    reason: str = ""
    source: str = "webhook"
    normalized_at: datetime = Field(default_factory=datetime.utcnow)


# ── Validation Models ────────────────────────────────────────────────────


class CheckResult(BaseModel):
    """Result of a single validation check."""

    check: str = ""
    passed: bool = False
    detail: str = ""


class ValidationResult(BaseModel):
    """Result of the full validation pipeline for a signal."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    signal_id: str = ""
    passed: bool = False
    checks: list[CheckResult] = Field(default_factory=list)
    rejection_reason: str = ""
    validated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Execution Models ─────────────────────────────────────────────────────


class ExecutionOrder(BaseModel):
    """An order that was (or will be) sent to the broker."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    signal_id: str = ""
    validation_id: str = ""
    mode: ExecutionMode = ExecutionMode.PAPER
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    quantity: int = 0
    price: float = 0.0
    order_type: str = "LIMIT"
    status: OrderStatus = OrderStatus.PENDING
    external_order_id: str | None = None
    strategy: str = ""
    dedup_key: str = ""
    """Unique key to prevent double-submission on retries."""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None


class ExecutionResult(BaseModel):
    """Result from broker after order submission."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    order_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: float = 0.0
    fill_timestamp: datetime | None = None
    broker_response: dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Position Models ──────────────────────────────────────────────────────


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class PositionSnapshot(BaseModel):
    """Point-in-time snapshot of the current position."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str = ""
    side: PositionSide = PositionSide.NONE
    quantity: int = 0
    entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    trades_today: int = 0
    daily_pnl: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Bot Status Models ────────────────────────────────────────────────────


class BotStatus(BaseModel):
    """Current state of the bot."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    status: BotStatusValue = BotStatusValue.STOPPED
    mode: BotMode = BotMode.PAPER
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: str = "system"
    detail: str = ""


class Heartbeat(BaseModel):
    """Periodic heartbeat record."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    bot_status: BotStatusValue = BotStatusValue.RUNNING
    bot_mode: BotMode = BotMode.PAPER
    last_action: str = ""
    trades_today: int = 0
    daily_pnl: float = 0.0
    kite_connected: bool = False


# ── Health Models ────────────────────────────────────────────────────────


class HealthCheckResult(BaseModel):
    """Result of checking a single health component."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    component: HealthComponent = HealthComponent.API_SERVER
    status: str = "pass"
    detail: str = ""
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class HealthSummary(BaseModel):
    """Aggregated health status."""

    status: str = "pass"
    checks: list[HealthCheckResult] = Field(default_factory=list)


# ── Control Models ───────────────────────────────────────────────────────


class ControlEvent(BaseModel):
    """Record of a control action."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    action: ControlAction = ControlAction.PAUSE
    triggered_by: str = ""
    source: str = ""  # "web", "dashboard", "system"
    result: str = "success"
    detail: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BotCommand(BaseModel):
    """Command for the bot to execute (bot polls this table)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    command: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=datetime.utcnow)
    issued_by: str = ""
    status: CommandStatus = CommandStatus.PENDING
    acked_at: datetime | None = None
    completed_at: datetime | None = None
    result: str = ""


# ── Risk Models ──────────────────────────────────────────────────────────


class RiskCounter(BaseModel):
    """Daily rolling risk counters."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    date: str = ""  # "YYYY-MM-DD"
    trades_today: int = 0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    peak_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Dashboard / API Response Models ──────────────────────────────────────


class DashboardData(BaseModel):
    """Full dashboard payload."""

    bot_status: BotStatusValue = BotStatusValue.STOPPED
    bot_mode: BotMode = BotMode.PAPER
    last_heartbeat: Heartbeat | None = None
    current_position: PositionSnapshot | None = None
    market_status: str = "unknown"
    daily_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    trades_today: int = 0
    wins_today: int = 0
    losses_today: int = 0
    max_drawdown_today: float = 0.0
    last_alert: WebhookAlert | None = None
    last_validation: ValidationResult | None = None
    last_order: ExecutionOrder | None = None
    recent_errors: list[str] = Field(default_factory=list)
    recent_events: list[ControlEvent] = Field(default_factory=list)
    recent_signals: list[NormalizedSignal] = Field(default_factory=list)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)


class ControlRequest(BaseModel):
    """Request body for control endpoints."""

    action: ControlAction
    params: dict[str, Any] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    """Response returned to TradingView webhook caller."""

    status: str = "received"
    alert_id: str = ""
    signal_id: str = ""
    validation_passed: bool = True
    message: str = ""
    execution: dict[str, Any] | None = None
    """Execution result dict from the executor (populated when validation passes)."""


class ApiError(BaseModel):
    """Standard API error response."""

    error: str = ""
    detail: str = ""
