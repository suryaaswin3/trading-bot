"""Default strategy — migration bridge that reproduces existing v0.3.1 behavior."""

from __future__ import annotations

from typing import Any

from ops_api.strategies.base import (
    BaseStrategy,
    OrderSpec,
    StrategyMetadata,
    StrategyVerdict,
)

_DEFAULT_METADATA = StrategyMetadata(
    id="default",
    display_name="Default (Legacy)",
    description="Backward-compatible strategy matching v0.3.1 behavior. Acts as fallback for unmatched signals.",
    timeframes=("15", "60"),
    symbols=("NIFTY", "BANKNIFTY"),
)


class DefaultStrategy(BaseStrategy):
    """Migration bridge — never matched by get_for_signal(), used as explicit fallback."""

    def __init__(self) -> None:
        super().__init__(_DEFAULT_METADATA)

    def matches(self, signal: dict[str, Any]) -> bool:
        return False  # fallback only, never auto-matched

    def validate_signal(
        self,
        signal: dict[str, Any],
        market_state: dict[str, Any] | None = None,
        portfolio: dict[str, Any] | None = None,
    ) -> StrategyVerdict:
        return StrategyVerdict(accepted=True)

    def compute_order(
        self,
        signal: dict[str, Any],
        portfolio: dict[str, Any] | None = None,
    ) -> OrderSpec | None:
        qty = 25 if "BANKNIFTY" in signal.get("symbol", "").upper() else 50
        return OrderSpec(
            symbol=signal.get("symbol", ""),
            side=signal.get("side", "BUY"),
            quantity=qty,
            order_type="LIMIT",
            price=float(signal.get("price", 0.0)),
        )

    def on_execution_result(
        self,
        result: dict[str, Any],
        portfolio: dict[str, Any] | None = None,
    ) -> None:
        return