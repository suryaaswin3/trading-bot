"""Pre-execution risk gates with position-aware checks."""

from __future__ import annotations

from typing import Any

from loguru import logger

from ops_api.db import DatabaseManager
from ops_api.position_manager import PositionManager
from ops_api.strategies.base import BaseStrategy


class RiskEngine:
    """Pre-execution risk gates with position-aware checks.

    All checks are additive — old code paths work unchanged when
    position_manager is None and limits are 0.
    """

    def __init__(
        self,
        db: DatabaseManager,
        position_manager: PositionManager | None = None,
        max_position_per_symbol: int = 0,
        max_portfolio_exposure: float = 0.0,
        max_position_pct: float = 0.0,
    ) -> None:
        self._db = db
        self._position_manager = position_manager
        self._max_position_per_symbol = max_position_per_symbol
        self._max_portfolio_exposure = max_portfolio_exposure
        self._max_position_pct = max_position_pct

    def check(self, signal: dict[str, Any], strategy: BaseStrategy | None = None) -> bool:
        """Run all risk gates. Returns True if signal passes (safe to execute)."""
        # 1. Kill switch
        ks = self._db.get_kill_switch_state() if self._db is not None else {"active": False}
        if ks.get("active", False):
            logger.warning("Risk block: kill switch active")
            return False

        # 2. Position-aware checks
        if self._position_manager is not None:
            symbol = signal.get("symbol", "")
            side = signal.get("side", "")
            qty = signal.get("quantity", 0)

            existing = self._position_manager.get_position(symbol)
            price = signal.get("price", 0.0)

            # Per-symbol position limit
            if self._max_position_per_symbol > 0:
                current_qty = existing.quantity if existing else 0
                same_direction = existing is not None and existing.side == ("LONG" if side == "BUY" else "SHORT")
                if same_direction:
                    new_qty = current_qty + qty
                elif existing is not None:
                    new_qty = abs(current_qty - qty)
                else:
                    new_qty = qty
                if new_qty > self._max_position_per_symbol:
                    logger.warning("Risk block: {} position {} exceeds limit {}", symbol, new_qty, self._max_position_per_symbol)
                    return False

            # Portfolio exposure cap
            if self._max_portfolio_exposure > 0:
                portfolio = self._position_manager.get_portfolio()
                new_exposure = portfolio.total_exposure + (qty * price)
                if new_exposure > self._max_portfolio_exposure:
                    logger.warning("Risk block: portfolio exposure {} exceeds cap {}", new_exposure, self._max_portfolio_exposure)
                    return False

            # Position concentration limit
            if self._max_position_pct > 0 and existing is not None:
                portfolio = self._position_manager.get_portfolio()
                pos_value = existing.quantity * existing.current_price
                pct = (pos_value / portfolio.total_exposure * 100) if portfolio.total_exposure > 0 else 0
                if pct > self._max_position_pct:
                    logger.warning("Risk block: {} concentration {:.1f}% exceeds limit {}%", symbol, pct, self._max_position_pct)
                    return False

        # 3. Strategy-level checks
        if strategy is None:
            return True

        risk_config = strategy.metadata.risk_defaults
        if risk_config is None:
            return True

        status = self._db.get_bot_status()
        if status is None:
            return True

        trades_today = status.get("trades_today", 0)
        if trades_today >= risk_config.max_trades_per_day:
            logger.warning("Risk block: trades today {} >= limit {}", trades_today, risk_config.max_trades_per_day)
            return False

        daily_pnl = status.get("daily_pnl", 0.0)
        if daily_pnl <= -risk_config.max_daily_loss:
            logger.warning("Risk block: daily PnL {} exceeds loss limit {}", daily_pnl, -risk_config.max_daily_loss)
            return False

        return True