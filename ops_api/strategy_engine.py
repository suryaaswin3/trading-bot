"""Strategy engine — routes signals through the strategy pipeline."""

from __future__ import annotations

from typing import Any

from loguru import logger

from ops_api.db import DatabaseManager
from ops_api.execution import ExecutionEngine
from ops_api.risk_engine import RiskEngine
from ops_api.position_manager import PositionManager
from ops_api.position_models import PortfolioSnapshot
from ops_api.strategies.base import BaseStrategy
from ops_api.strategies.registry import StrategyRegistry
from ops_api.validation import ValidationPipeline


class StrategyEngine:
    """Orchestrates the strategy pipeline for incoming signals."""

    def __init__(
        self,
        registry: StrategyRegistry,
        validator: ValidationPipeline,
        executor: ExecutionEngine,
        risk_engine: RiskEngine,
        db: DatabaseManager,
        position_manager: PositionManager | None = None,
    ) -> None:
        self.registry = registry
        self.validator = validator
        self.executor = executor
        self.risk_engine = risk_engine
        self.db = db
        self._position_manager = position_manager

    def process(
        self,
        signal: dict[str, Any],
        mode: str = "paper",
    ) -> dict[str, Any]:
        # 1. Resolve strategy
        strategy = self.registry.get_for_signal(signal)
        if strategy is None:
            strategy = self.registry.get("default")

        if strategy is None:
            logger.error("No strategy found and DefaultStrategy not registered")
            return {"status": "rejected", "strategy_id": "", "error": "No strategy available"}

        logger.info("StrategyEngine: processing signal {} via strategy '{}'", signal.get("id", "unknown"), strategy.metadata.id)

        # 2. Shared validation
        validation_result = self.validator.validate(signal)
        if not validation_result.passed:
            return {"status": "rejected", "strategy_id": strategy.metadata.id, "validation_passed": False, "error": validation_result.rejection_reason}

        # 3. Strategy-specific validation
        market_state: dict[str, Any] = {}
        if self._position_manager is not None:
            portfolio = self._position_manager.get_portfolio()
        else:
            portfolio = PortfolioSnapshot()
        verdict = strategy.validate_signal(signal, market_state, portfolio)
        if not verdict.accepted:
            return {"status": "rejected", "strategy_id": strategy.metadata.id, "validation_passed": False, "error": verdict.rejection_reason}

        # 4. Risk check
        if not self.risk_engine.check(signal, strategy):
            return {"status": "rejected", "strategy_id": strategy.metadata.id, "validation_passed": True, "error": "Risk check failed"}

        # 5. Compute order
        order_spec = strategy.compute_order(signal, portfolio)
        if order_spec is None:
            return {"status": "skipped", "strategy_id": strategy.metadata.id, "validation_passed": True, "error": "Strategy declined to trade"}

        # 6. Execute via existing ExecutionEngine
        validation_dict = validation_result.model_dump()
        validation_dict["checks"] = [c.model_dump() for c in validation_result.checks]

        if verdict.overrides:
            for key, value in verdict.overrides.items():
                if hasattr(order_spec, key):
                    setattr(order_spec, key, value)

        exec_result = self.executor.execute(signal, validation_dict, mode=mode)

        # 7. Lifecycle callback
        strategy.on_execution_result(exec_result, portfolio)

        # 8. Enrich result with strategy metadata
        exec_result["strategy_id"] = strategy.metadata.id
        exec_result["validation_passed"] = True

        return exec_result