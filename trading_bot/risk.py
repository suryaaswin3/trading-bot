"""Risk management — trade entry/exit validation.

Phase 2 additions (this release):
    - Consecutive-loss circuit breaker
    - Premium check on max_premium_per_trade
    - record_exit() / reset_daily() lifecycle methods
"""

from __future__ import annotations

from trading_bot.config import TradingBotConfig
from trading_bot.state import can_trade


class RiskManager:
    """First gate for trade entry validation. Called BEFORE _execute_entry_signal.

    The risk layer sits between signal detection and execution:
        Signal → risk_manager.can_enter() → _execute_entry_signal(can_trade inside)
                                     ↑ first gate                ↑ second gate
    """

    def __init__(self, config: TradingBotConfig) -> None:
        self.config = config
        self._consecutive_losses: int = 0

    def can_enter(self, signal: str) -> tuple[bool, str]:
        """First gate: validate entry before calling _execute_entry_signal.

        Checks in order:
        1. Signal direction validation.
        2. Consecutive-loss circuit breaker.
        3. Base state checks (trades_today, cooldown, daily_loss).

        Args:
            signal: One of ``"TRADE_CALL"``, ``"TRADE_PUT"``, or non-entry signal.

        Returns:
            ``(allowed, reason)``. Empty reason string means allowed.
        """
        # 1. Signal direction validation
        if signal not in ("TRADE_CALL", "TRADE_PUT"):
            return False, f"Invalid or non-entry signal: {signal}"

        # 2. Consecutive-loss circuit breaker
        if self._consecutive_losses >= self.config.max_consecutive_losses:
            return (
                False,
                f"Circuit breaker: {self._consecutive_losses} consecutive losses "
                f"(limit {self.config.max_consecutive_losses})",
            )

        # 3. Base state checks
        allowed, reason = can_trade(self.config)
        if not allowed:
            return False, reason

        return True, ""

    def record_exit(self, pnl: float) -> None:
        """Record an exit P&L and update the consecutive-loss counter.

        Call from ``main.py`` after ``close_position()``.
        """
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def reset_daily(self) -> None:
        """Reset the consecutive-loss counter (call at EOD / market start)."""
        self._consecutive_losses = 0


__all__ = [
    "RiskManager",
]
