"""Risk engine tests — kill switch, per-strategy limits."""
from __future__ import annotations
import tempfile
import pytest
from ops_api.db import DatabaseManager
from ops_api.risk_engine import RiskEngine
from ops_api.strategies.base import BaseStrategy, RiskConfig, StrategyMetadata


class _TestStrategy(BaseStrategy):
    def __init__(self, sid: str = "test_strat", risk_config: RiskConfig | None = None) -> None:
        meta = StrategyMetadata(id=sid, risk_defaults=risk_config or RiskConfig(max_trades_per_day=5, max_daily_loss=2000.0, cooldown_minutes=10, max_consecutive_losses=3, max_position_size=50))
        super().__init__(meta)


@pytest.fixture
def db():
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


@pytest.fixture
def engine(db):
    return RiskEngine(db)


@pytest.fixture
def base_signal():
    return {"symbol": "NIFTY", "side": "BUY", "strategy": "test_strat"}


class TestRiskEngine:
    def test_passes_with_no_active_limits(self, engine, base_signal):
        assert engine.check(base_signal, _TestStrategy()) is True

    def test_passes_with_no_strategy(self, engine, base_signal):
        assert engine.check(base_signal, strategy=None) is True

    def test_blocks_on_kill_switch(self, engine, db, base_signal):
        db.upsert_bot_status({"kill_switch_active": True, "kill_switch_triggered_by": "admin"})
        assert engine.check(base_signal, _TestStrategy()) is False

    def test_blocks_on_max_trades(self, engine, db, base_signal):
        strategy = _TestStrategy(risk_config=RiskConfig(max_trades_per_day=3))
        db.upsert_bot_status({"trades_today": 3})
        assert engine.check(base_signal, strategy) is False

    def test_allows_under_max_trades(self, engine, db, base_signal):
        strategy = _TestStrategy(risk_config=RiskConfig(max_trades_per_day=5))
        db.upsert_bot_status({"trades_today": 3})
        assert engine.check(base_signal, strategy) is True

    def test_blocks_on_daily_loss(self, engine, db, base_signal):
        strategy = _TestStrategy(risk_config=RiskConfig(max_daily_loss=1000.0))
        db.upsert_bot_status({"daily_pnl": -1500.0})
        assert engine.check(base_signal, strategy) is False

    def test_allows_under_daily_loss(self, engine, db, base_signal):
        strategy = _TestStrategy(risk_config=RiskConfig(max_daily_loss=1000.0))
        db.upsert_bot_status({"daily_pnl": -500.0})
        assert engine.check(base_signal, strategy) is True

    def test_handles_null_bot_status(self, engine, base_signal):
        assert engine.check(base_signal, _TestStrategy()) is True


class TestRiskEnginePositionAware:
    """Tests for position-aware risk checks (Phase 4)."""

    def test_checks_pass_when_no_position_manager(self, engine, base_signal):
        """Without position_manager, position checks are skipped."""
        engine_no_pm = RiskEngine(None)
        assert engine_no_pm.check(base_signal, None) is True

    def test_checks_pass_when_no_existing_position(self, db):
        """No existing position for symbol — position checks pass."""
        from ops_api.position_manager import PositionManager
        pm = PositionManager(db)
        engine = RiskEngine(db, position_manager=pm, max_position_per_symbol=50)
        signal = {"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "price": 250.0}
        assert engine.check(signal, None) is True

    def test_per_symbol_limit_exceeded(self, db):
        """Existing position + incoming qty exceeds per-symbol limit."""
        from ops_api.position_manager import PositionManager
        pm = PositionManager(db)
        pm.open_or_adjust("RELIANCE", "BUY", 45, 250.0)
        engine = RiskEngine(db, position_manager=pm, max_position_per_symbol=50)
        signal = {"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "price": 250.0}
        assert engine.check(signal, None) is False

    def test_per_symbol_limit_not_exceeded(self, db):
        """Existing position + incoming qty within limit."""
        from ops_api.position_manager import PositionManager
        pm = PositionManager(db)
        pm.open_or_adjust("RELIANCE", "BUY", 30, 250.0)
        engine = RiskEngine(db, position_manager=pm, max_position_per_symbol=50)
        signal = {"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "price": 250.0}
        assert engine.check(signal, None) is True

    def test_portfolio_exposure_cap(self, db):
        """Total portfolio exposure exceeds max."""
        from ops_api.position_manager import PositionManager
        pm = PositionManager(db)
        pm.open_or_adjust("RELIANCE", "BUY", 10, 8000.0)
        engine = RiskEngine(db, position_manager=pm, max_portfolio_exposure=100000.0)
        signal = {"symbol": "TCS", "side": "BUY", "quantity": 10, "price": 2500.0}
        assert engine.check(signal, None) is False

    def test_portfolio_exposure_within_cap(self, db):
        """Total portfolio exposure within max."""
        from ops_api.position_manager import PositionManager
        pm = PositionManager(db)
        pm.open_or_adjust("RELIANCE", "BUY", 10, 8000.0)
        engine = RiskEngine(db, position_manager=pm, max_portfolio_exposure=100000.0)
        signal = {"symbol": "TCS", "side": "BUY", "quantity": 1, "price": 2500.0}
        assert engine.check(signal, None) is True

    def test_position_concentration_exceeded(self, db):
        """Single position exceeds max % of portfolio."""
        from ops_api.position_manager import PositionManager
        pm = PositionManager(db)
        pm.open_or_adjust("BIGPOS", "BUY", 80, 1000.0)
        pm.open_or_adjust("SMALLPOS", "BUY", 20, 100.0)
        engine = RiskEngine(db, position_manager=pm, max_position_pct=50.0)
        signal = {"symbol": "BIGPOS", "side": "BUY", "quantity": 10, "price": 1000.0}
        assert engine.check(signal, None) is False