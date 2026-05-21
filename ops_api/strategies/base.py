"""Base strategy abstractions for the ops trading engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RiskConfig:
    """Risk management configuration for a strategy."""

    max_trades_per_day: int = 2
    max_daily_loss: float = 5000.0
    cooldown_minutes: int = 30
    max_consecutive_losses: int = 3
    max_position_size: int = 50


@dataclass(frozen=True)
class StrategyMetadata:
    """Immutable metadata describing a strategy."""

    id: str = ""
    display_name: str = ""
    description: str = ""
    timeframes: tuple = ()
    symbols: list[str] | None = None
    risk_defaults: RiskConfig = field(default_factory=RiskConfig)


@dataclass
class StrategyVerdict:
    """Result of strategy-level signal validation."""

    accepted: bool = True
    rejection_reason: str = ""
    overrides: dict[str, Any] | None = None


@dataclass
class OrderSpec:
    """Specification for an order to be placed."""

    symbol: str = ""
    side: str = "BUY"
    quantity: int = 0
    order_type: str = "LIMIT"
    price: float = 0.0


class BaseStrategy(ABC):
    """Abstract base for pluggable trading strategies."""

    def __init__(self, metadata: StrategyMetadata | str) -> None:
        if isinstance(metadata, str):
            metadata = StrategyMetadata(id=metadata)
        self.metadata = metadata

    def matches(self, signal: dict) -> bool:
        """Return True if this strategy should handle the given signal."""
        return signal.get("strategy", "") == self.metadata.id

    def validate_signal(
        self,
        signal: dict,
        market_state: Any = None,
        portfolio: Any = None,
    ) -> StrategyVerdict:
        """Validate whether this signal should be acted on.  Override to add strategy-specific checks."""
        return StrategyVerdict(accepted=True)

    def compute_order(
        self,
        signal: dict,
        portfolio: Any = None,
    ) -> OrderSpec | None:
        """Derive an order from the validated signal."""
        quantity = 25 if signal.get("symbol", "").upper() == "BANKNIFTY" else 50
        return OrderSpec(
            symbol=signal.get("symbol", ""),
            side=signal.get("side", "BUY"),
            quantity=quantity,
            order_type="LIMIT",
            price=signal.get("price", 0.0),
        )

    def on_execution_result(
        self,
        result: dict[str, Any],
        portfolio: Any = None,
    ) -> None:
        """Hook called after an order derived from this strategy is executed."""
        return None