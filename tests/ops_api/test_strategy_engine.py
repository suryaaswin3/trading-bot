"""Strategy engine tests — pipeline integration, fallback, strategy routing."""

from __future__ import annotations

import tempfile
from typing import Any
from unittest.mock import patch

import pytest

from ops_api.config import OpsApiConfig
from ops_api.db import DatabaseManager
from ops_api.execution import ExecutionEngine
from ops_api.risk_engine import RiskEngine
from ops_api.strategies.base import BaseStrategy, OrderSpec, StrategyMetadata, StrategyVerdict
from ops_api.strategies.default import DefaultStrategy
from ops_api.strategies.registry import StrategyRegistry
from ops_api.strategy_engine import StrategyEngine
from ops_api.validation import ValidationPipeline


class _PassThroughStrategy(BaseStrategy):
    """Accepts all signals and computes a default order."""

    def validate_signal(
        self,
        signal: dict[str, Any],
        market_state: dict[str, Any] | None = None,
        portfolio: dict[str, Any] | None = None,
    ) -> StrategyVerdict:
        return StrategyVerdict(accepted=True)


class _RejectingStrategy(BaseStrategy):
    """Rejects all signals at strategy-level validation."""

    def __init__(self) -> None:
        super().__init__(StrategyMetadata(id="rejector"))

    def validate_signal(
        self,
        signal: dict[str, Any],
        market_state: dict[str, Any] | None = None,
        portfolio: dict[str, Any] | None = None,
    ) -> StrategyVerdict:
        return StrategyVerdict(accepted=False, rejection_reason="strategy declined")


class _SkipStrategy(BaseStrategy):
    """Declines to trade by returning None from compute_order."""

    def __init__(self) -> None:
        super().__init__(StrategyMetadata(id="skipper"))

    def compute_order(
        self,
        signal: dict[str, Any],
        portfolio: dict[str, Any] | None = None,
    ) -> None:
        return None


@pytest.fixture
def db() -> DatabaseManager:
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


@pytest.fixture
def config() -> OpsApiConfig:
    return OpsApiConfig()


@pytest.fixture
def validator(config: OpsApiConfig, db: DatabaseManager) -> ValidationPipeline:
    return ValidationPipeline(config, db)


@pytest.fixture
def executor(config: OpsApiConfig, db: DatabaseManager) -> ExecutionEngine:
    return ExecutionEngine(config, db)


@pytest.fixture
def risk_engine(db: DatabaseManager) -> RiskEngine:
    return RiskEngine(db)


@pytest.fixture
def registry() -> StrategyRegistry:
    reg = StrategyRegistry()
    reg.register(DefaultStrategy())
    return reg


@pytest.fixture
def engine(
    registry: StrategyRegistry,
    validator: ValidationPipeline,
    executor: ExecutionEngine,
    risk_engine: RiskEngine,
    db: DatabaseManager,
) -> StrategyEngine:
    return StrategyEngine(registry, validator, executor, risk_engine, db)


class TestStrategyEngine:
    """Integration tests for the StrategyEngine pipeline."""

    @patch("ops_api.validation._is_in_trading_window", return_value=(True, ""))
    def test_default_strategy_fallback(
        self, mock_time: Any, engine: StrategyEngine, registry: StrategyRegistry
    ) -> None:
        """Unmatched signals fall through to DefaultStrategy."""
        signal = {
            "id": "sig_001",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 18100.0,
            "strategy": "unknown",
        }
        result = engine.process(signal, mode="paper")
        assert result.get("strategy_id") == "default"

    @patch("ops_api.validation._is_in_trading_window", return_value=(True, ""))
    def test_matched_strategy_used(
        self, mock_time: Any, registry: StrategyRegistry, engine: StrategyEngine
    ) -> None:
        """A strategy matching by ID is selected and its ID appears in the result."""
        registry.register(_PassThroughStrategy(StrategyMetadata(id="my_strat")))
        signal = {
            "id": "sig_002",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 18100.0,
            "strategy": "my_strat",
        }
        result = engine.process(signal, mode="paper")
        assert result.get("strategy_id") == "my_strat"

    @patch("ops_api.validation._is_in_trading_window", return_value=(True, ""))
    def test_strategy_rejection(
        self, mock_time: Any, registry: StrategyRegistry, engine: StrategyEngine
    ) -> None:
        """A strategy that rejects the signal returns status rejected."""
        registry.register(_RejectingStrategy())
        signal = {
            "id": "sig_003",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 18100.0,
            "strategy": "rejector",
        }
        result = engine.process(signal, mode="paper")
        assert result.get("status") == "rejected"
        assert "declined" in result.get("error", "")

    @patch("ops_api.validation._is_in_trading_window", return_value=(True, ""))
    def test_skip_strategy(
        self, mock_time: Any, registry: StrategyRegistry, engine: StrategyEngine
    ) -> None:
        """A strategy that returns None from compute_order yields a skipped result."""
        registry.register(_SkipStrategy())
        signal = {
            "id": "sig_004",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 18100.0,
            "strategy": "skipper",
        }
        result = engine.process(signal, mode="paper")
        assert result.get("status") == "skipped"

    def test_no_strategies_at_all(self, engine: StrategyEngine) -> None:
        """When DefaultStrategy is missing, engine reports an error."""
        engine.registry.clear()
        signal = {
            "id": "sig_005",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 100.0,
            "strategy": "anything",
        }
        result = engine.process(signal, mode="paper")
        assert result.get("status") == "rejected"
        assert "No strategy available" in result.get("error", "")


class TestScannerIntegration:
    """Scanner signals should flow through StrategyEngine like webhook signals."""

    @patch("ops_api.validation._is_in_trading_window", return_value=(True, ""))
    def test_scanner_signal_processed_by_strategy_engine(self, mock_time: Any, engine: StrategyEngine) -> None:
        signal = {
            "id": "scanner_sig_001", "symbol": "NIFTY", "side": "BUY", "price": 18200.0,
            "strategy": "MOMENTUM", "source": "scanner", "timeframe": "60",
        }
        result = engine.process(signal, mode="paper")
        assert result.get("strategy_id") in ("default", "MOMENTUM")
        assert result.get("status") in ("filled", "rejected", "skipped")

    @patch("ops_api.validation._is_in_trading_window", return_value=(True, ""))
    def test_scanner_signal_with_source_field(self, mock_time: Any, engine: StrategyEngine) -> None:
        signal = {
            "id": "scanner_sig_002", "symbol": "NIFTY", "side": "BUY", "price": 18200.0,
            "strategy": "default", "source": "scanner", "timeframe": "60",
        }
        result = engine.process(signal, mode="paper")
        assert "strategy_id" in result