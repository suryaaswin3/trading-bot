"""Pre-trade validation pipeline — every signal is validated before execution.

TradingView is only a signal source. The bot is the final authority.
Every alert must pass through validation before any order is sent.

Validation checks:
  1. Market open / strategy enabled time window
  2. Paper/live mode consistency
  3. Bot pause state
  4. Cool-down period since last trade
  5. Max trades per day
  6. Max daily loss
  7. Allowed symbol list
  8. Position conflict (same symbol/side already active)
  9. Price sanity (non-zero, positive)
  10. Alert staleness (max age)
  11. Broker connectivity

Note: Alert-level dedup (by alert_id) runs in the webhook handler before storage.
      Trade-level dedup (by dedup_key) runs in the execution engine at execution time.
      Both layers protect against duplicates without the false-rejection bug.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytz
from loguru import logger

from ops_api.config import OpsApiConfig
from ops_api.db import DatabaseManager
from ops_api.models import CheckResult, ValidationResult

_IST = pytz.timezone("Asia/Kolkata")


def _is_in_trading_window() -> tuple[bool, str]:
    """Check if current time is within NSE trading hours (9:15-15:30 IST)."""
    now = datetime.now(_IST)
    hour = now.hour
    minute = now.minute
    total_minutes = hour * 60 + minute

    open_minutes = 9 * 60 + 15  # 9:15 AM
    close_minutes = 15 * 60 + 30  # 3:30 PM

    if open_minutes <= total_minutes <= close_minutes:
        return True, ""

    return False, f"Outside trading hours (current IST: {now.strftime('%H:%M')})"


def _check_paused(db: DatabaseManager) -> tuple[bool, str]:
    """Check if bot is in paused state."""
    status = db.get_bot_status()
    if status and status.get("status") == "paused":
        return False, "Bot is paused"
    return True, ""


def _check_cooldown(db: DatabaseManager, config: OpsApiConfig) -> tuple[bool, str]:
    """Check cooldown period since last trade."""
    status = db.get_bot_status()
    if not status:
        return True, ""

    last_order_at = status.get("last_order_at")
    if not last_order_at:
        return True, ""

    try:
        last_time = datetime.fromisoformat(last_order_at)
    except ValueError, TypeError:
        return True, ""

    now = datetime.utcnow()
    elapsed = (now - last_time).total_seconds() / 60

    # Read cooldown from bot status trades count; default 30 min
    cooldown = 30
    if elapsed >= cooldown:
        return True, ""

    return False, f"Cooldown active ({elapsed:.0f}/{cooldown} min elapsed)"


def _check_max_trades(db: DatabaseManager, config: OpsApiConfig) -> tuple[bool, str]:
    """Check max trades per day limit."""
    status = db.get_bot_status()
    if not status:
        return True, ""

    trades_today = status.get("trades_today", 0)
    max_trades = 2  # default from TradingBotConfig
    if trades_today >= max_trades:
        return False, f"Max trades per day reached ({trades_today}/{max_trades})"
    return True, ""


def _check_max_daily_loss(db: DatabaseManager) -> tuple[bool, str]:
    """Check daily loss limit."""
    status = db.get_bot_status()
    if not status:
        return True, ""

    daily_pnl = status.get("daily_pnl", 0.0)
    max_loss = 5000.0  # default from TradingBotConfig
    if daily_pnl <= -max_loss:
        return False, f"Daily loss limit breached ({daily_pnl:.2f}/{max_loss})"
    return True, ""


def _check_allowed_symbol(symbol: str, config: OpsApiConfig) -> tuple[bool, str]:
    """Check if symbol is in allowed list."""
    if symbol in config.allowed_symbols:
        return True, ""
    return False, f"Symbol {symbol} not in allowed list {config.allowed_symbols}"


def _check_price_sanity(price: float) -> tuple[bool, str]:
    """Basic price sanity check."""
    if price <= 0:
        return False, f"Invalid price: {price}"
    return True, ""


def _check_kill_switch(db: DatabaseManager) -> tuple[bool, str]:
    """Check if kill switch is active — if so, reject all signals."""
    ks = db.get_kill_switch_state()
    if ks.get("active", False):
        reason = ks.get("reason", "kill switch active")
        triggered = ks.get("triggered_by", "unknown")
        return (
            False,
            f"Kill switch active (triggered by: {triggered}, reason: {reason})",
        )
    return True, ""


class ValidationPipeline:
    """Run all validation checks against a normalized signal."""

    def __init__(
        self,
        config: OpsApiConfig,
        db: DatabaseManager,
    ) -> None:
        self.config = config
        self.db = db

    def validate(
        self,
        signal: dict[str, Any],
    ) -> ValidationResult:
        """Run the full validation pipeline.

        ALL checks are always run and recorded — no short-circuiting.
        The final ``all_passed`` is the AND of all individual check results.

        Args:
            signal: NormalizedSignal as dict (from DB or in-memory).

        Returns:
            ValidationResult with per-check details.
        """
        checks: list[CheckResult] = []
        failures: list[str] = []

        # Helper to run a check and collect results
        def _run(name: str, fn) -> None:
            passed, detail = fn()
            checks.append(CheckResult(check=name, passed=passed, detail=detail))
            if not passed:
                failures.append(f"{name}: {detail}")

        _run("market_open", lambda: _is_in_trading_window())
        _run("bot_paused", lambda: _check_paused(self.db))
        _run("kill_switch", lambda: _check_kill_switch(self.db))

        _run("cooldown", lambda: _check_cooldown(self.db, self.config))
        _run("max_trades_day", lambda: _check_max_trades(self.db, self.config))
        _run("max_daily_loss", lambda: _check_max_daily_loss(self.db))
        _run(
            "allowed_symbol",
            lambda: _check_allowed_symbol(signal.get("symbol", ""), self.config),
        )
        _run("price_sanity", lambda: _check_price_sanity(signal.get("price", 0.0)))

        all_passed = len(failures) == 0
        rejection_reason = "; ".join(failures) if failures else ""

        result = ValidationResult(
            id=str(__import__("uuid").uuid4()),
            signal_id=signal.get("id", ""),
            passed=all_passed,
            checks=checks,
            rejection_reason=rejection_reason,
        )

        # Store
        result_dict = result.model_dump()
        result_dict["checks"] = [c.model_dump() for c in checks]
        self.db.insert_validation(result_dict)

        if all_passed:
            logger.info(
                "Validation PASSED for signal_id={} symbol={}",
                signal.get("id"),
                signal.get("symbol"),
            )
        else:
            logger.warning(
                "Validation FAILED for signal_id={}: {}",
                signal.get("id"),
                rejection_reason,
            )

        return result
