"""Ops API configuration — loaded from environment variables."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import dotenv

_DEFAULT_ALLOWED = ("NIFTY", "BANKNIFTY")


@dataclass(frozen=True)
class OpsApiConfig:
    # ── Server ──────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8080
    reload: bool = False
    log_level: str = "info"

    # ── Database ────────────────────────────────────────────────────────
    db_path: str = "ops_data.db"
    db_pool_timeout: float = 5.0

    # ── Data retention (days) ───────────────────────────────────────────
    retention_days: int = 90

    # ── Webhook ─────────────────────────────────────────────────────────
    webhook_secret: str = ""
    """Shared secret for HMAC-based TradingView webhook authentication."""

    # ── Authentication ──────────────────────────────────────────────────
    api_key: str = ""
    """API key for dashboard and control endpoint authentication."""
    api_key_header: str = "X-API-Key"
    """Header name for API key authentication."""

    # ── Heartbeat ───────────────────────────────────────────────────────
    heartbeat_interval_seconds: int = 60
    heartbeat_file_path: str = "/tmp/trading-bot-heartbeat.txt"

    # ── Dashboard ───────────────────────────────────────────────────────
    dashboard_port: int = 8501

    # ── Trading ─────────────────────────────────────────────────────────
    allowed_symbols: tuple[str, ...] = field(
        default_factory=lambda: _DEFAULT_ALLOWED
    )
    max_staleness_seconds: int = 300
    """Max age in seconds for a webhook alert before it's considered stale."""

    # ── Dashboard auth for streamlit (set in env for streamlit) ─────────
    dashboard_password: str = ""
    dashboard_username: str = "admin"

    # ── Telegram notifications ──────────────────────────────────────────
    telegram_bot_token: str = ""
    """Telegram bot token from @BotFather."""
    telegram_chat_id: str = ""
    """Telegram chat/group ID to send alerts to."""

    # ── Kill switch ─────────────────────────────────────────────────────
    flatten_on_kill: bool = False
    """If True, flatten all positions when kill switch is activated."""

    # ── Strategy Engine ─────────────────────────────────────────
    use_strategy_engine: bool = True

    # ── Scanner Engine ──────────────────────────────────────────
    scanner_enabled: bool = True
    scanner_interval_seconds: int = 60
    scanner_symbols: tuple[str, ...] = field(
        default_factory=lambda: ("NIFTY", "BANKNIFTY")
    )

    def validate(self) -> list[str]:
        """Run startup validation. Returns list of warning/error messages.

        Call during application startup. Warnings do not prevent running;
        errors do (caller should abort).
        """
        issues: list[str] = []

        if not self.webhook_secret:
            issues.append("[WARN] OA_WEBHOOK_SECRET is not set — webhook auth disabled")

        if not self.api_key:
            issues.append("[WARN] OA_API_KEY is not set — control endpoints have no auth")

        if self.telegram_bot_token and not self.telegram_chat_id:
            issues.append("[WARN] OA_TELEGRAM_BOT_TOKEN set but OA_TELEGRAM_CHAT_ID missing")

        if not self.telegram_bot_token:
            issues.append("[WARN] Telegram notifier disabled (no OA_TELEGRAM_BOT_TOKEN)")

        chat = self.telegram_chat_id.strip()
        if chat and chat.startswith("-"):
            try:
                int(chat)
            except ValueError:
                issues.append(f"[WARN] OA_TELEGRAM_CHAT_ID looks unusual: {chat[:20]}")

        if not (0 < self.port < 65536):
            issues.append(f"[ERR] Invalid OA_PORT: {self.port}")

        if not _DEFAULT_ALLOWED:
            issues.append("[ERR] OA_ALLOWED_SYMBOLS is empty — no tradable symbols")

        if self.retention_days < 1:
            issues.append(f"[WARN] OA_RETENTION_DAYS={self.retention_days} — disabling cleanup")

        return issues

    def has_fatal_issues(self) -> bool:
        """Return True if there are issues that should prevent startup."""
        return any(i.startswith("[ERR]") for i in self.validate())


def load_ops_config() -> OpsApiConfig:
    """Load Ops API config from ``OA_*`` env vars / ``.env`` file."""
    dotenv.load_dotenv()

    prefix = "OA_"

    kwargs = {}

    # Manual mapping for type coercion
    bool_keys = {"OA_RELOAD", "OA_FLATTEN_ON_KILL", "OA_USE_STRATEGY_ENGINE", "OA_SCANNER_ENABLED"}
    int_keys = {
        "OA_PORT",
        "OA_DASHBOARD_PORT",
        "OA_HEARTBEAT_INTERVAL_SECONDS",
        "OA_MAX_STALENESS_SECONDS",
        "OA_DB_POOL_TIMEOUT",
        "OA_RETENTION_DAYS",
        "OA_SCANNER_INTERVAL_SECONDS",
    }

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        field_name = key[len(prefix) :].lower()

        if value.strip() == "":
            continue

        if key in bool_keys:
            kwargs[field_name] = value.strip().lower() in ("1", "true", "yes")
        elif key in int_keys:
            kwargs[field_name] = int(value)
        elif key == "OA_ALLOWED_SYMBOLS":
            kwargs["allowed_symbols"] = tuple(
                s.strip() for s in value.split(",") if s.strip()
            )
        elif key == "OA_SCANNER_SYMBOLS":
            kwargs["scanner_symbols"] = tuple(
                s.strip() for s in value.split(",") if s.strip()
            )
        else:
            kwargs[field_name] = value

    return OpsApiConfig(**kwargs)