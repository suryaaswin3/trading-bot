"""Execution engine tests — paper mode, live mode (mocked), dedup, flatten."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock

import pytest

from ops_api.config import OpsApiConfig
from ops_api.db import DatabaseManager
from ops_api.execution import ExecutionEngine, PaperBroker


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
def engine(config: OpsApiConfig, db: DatabaseManager) -> ExecutionEngine:
    return ExecutionEngine(config, db)


@pytest.fixture
def valid_signal() -> dict:
    return {
        "id": "sig_exec_001",
        "alert_id": "tv_exec_001",
        "symbol": "NIFTY",
        "side": "BUY",
        "price": 18150.0,
        "strategy": "VWAP_PULLBACK",
    }


@pytest.fixture
def passed_validation() -> dict:
    return {
        "id": "val_exec_001",
        "signal_id": "sig_exec_001",
        "passed": True,
        "checks": [],
        "rejection_reason": "",
    }


class TestPaperBroker:
    def test_place_order_returns_filled(self) -> None:
        broker = PaperBroker(OpsApiConfig())
        result = broker.place_order("NIFTY", "BUY", 50, 150.0, strategy="VWAP")
        assert result["external_order_id"].startswith("PAPER_")
        assert result["status"] == "filled"


class TestExecutionEngine:
    def test_rejects_unvalidated(
        self, engine: ExecutionEngine, valid_signal: dict
    ) -> None:
        result = engine.execute(valid_signal, {"passed": False}, mode="paper")
        assert result["status"] == "rejected"

    def test_paper_execution(
        self,
        engine: ExecutionEngine,
        valid_signal: dict,
        passed_validation: dict,
    ) -> None:
        result = engine.execute(valid_signal, passed_validation, mode="paper")
        assert result["status"] == "filled"
        assert "PAPER_" in (result.get("external_order_id") or "")

    def test_dedup_prevents_double_execution(
        self,
        engine: ExecutionEngine,
        valid_signal: dict,
        passed_validation: dict,
    ) -> None:
        # First execution
        engine.execute(valid_signal, passed_validation, mode="paper")
        # Second execution — same dedup key
        result = engine.execute(valid_signal, passed_validation, mode="paper")
        assert result["status"] == "duplicate"

    def test_live_mode_with_mocked_kite(
        self,
        config: OpsApiConfig,
        db: DatabaseManager,
        valid_signal: dict,
        passed_validation: dict,
    ) -> None:
        mock_kite = MagicMock()
        mock_kite.place_order.return_value = "KITE_ORDER_001"
        engine = ExecutionEngine(config, db, kite_client=mock_kite)

        result = engine.execute(valid_signal, passed_validation, mode="live")
        assert result["status"] in ("filled", "submitted", "failed")
        mock_kite.place_order.assert_called_once()

    def test_live_mode_kite_error(
        self,
        config: OpsApiConfig,
        db: DatabaseManager,
        valid_signal: dict,
        passed_validation: dict,
    ) -> None:
        mock_kite = MagicMock()
        mock_kite.place_order.side_effect = RuntimeError("Kite error")
        engine = ExecutionEngine(config, db, kite_client=mock_kite)

        result = engine.execute(valid_signal, passed_validation, mode="live")
        assert result["status"] == "failed"

    def test_flatten_returns_ok(self, engine: ExecutionEngine) -> None:
        result = engine.flatten()
        assert result["status"] == "completed"
