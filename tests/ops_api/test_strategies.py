"""Tests for strategy abstractions — RiskConfig, StrategyMetadata, StrategyVerdict,
OrderSpec, and BaseStrategy."""

from __future__ import annotations

import pytest

from ops_api.strategies.base import (
    BaseStrategy,
    OrderSpec,
    RiskConfig,
    StrategyMetadata,
    StrategyVerdict,
)
from ops_api.strategies.default import DefaultStrategy
from ops_api.strategies.registry import DuplicateStrategyError, StrategyRegistry


# ---------------------------------------------------------------------------
# RiskConfig
# ---------------------------------------------------------------------------


class TestRiskConfig:
    def test_defaults(self) -> None:
        cfg = RiskConfig()
        assert cfg.max_trades_per_day == 2
        assert cfg.max_daily_loss == 5000.0
        assert cfg.cooldown_minutes == 30
        assert cfg.max_consecutive_losses == 3
        assert cfg.max_position_size == 50

    def test_custom_values(self) -> None:
        cfg = RiskConfig(
            max_trades_per_day=5,
            max_daily_loss=10000.0,
            cooldown_minutes=15,
            max_consecutive_losses=1,
            max_position_size=100,
        )
        assert cfg.max_trades_per_day == 5
        assert cfg.max_daily_loss == 10000.0
        assert cfg.cooldown_minutes == 15
        assert cfg.max_consecutive_losses == 1
        assert cfg.max_position_size == 100

    def test_frozen_raises_attribute_error(self) -> None:
        cfg = RiskConfig()
        with pytest.raises(AttributeError):
            cfg.max_trades_per_day = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StrategyMetadata
# ---------------------------------------------------------------------------


class TestStrategyMetadata:
    def test_defaults(self) -> None:
        m = StrategyMetadata()
        assert m.id == ""
        assert m.display_name == ""
        assert m.description == ""
        assert m.timeframes == ()
        assert m.symbols is None
        assert isinstance(m.risk_defaults, RiskConfig)

    def test_frozen_raises_attribute_error(self) -> None:
        m = StrategyMetadata()
        with pytest.raises(AttributeError):
            m.id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StrategyVerdict
# ---------------------------------------------------------------------------


class TestStrategyVerdict:
    def test_default_accepted(self) -> None:
        v = StrategyVerdict()
        assert v.accepted is True
        assert v.rejection_reason == ""
        assert v.overrides is None

    def test_rejected_with_reason(self) -> None:
        v = StrategyVerdict(accepted=False, rejection_reason="max_drawdown_exceeded")
        assert v.accepted is False
        assert v.rejection_reason == "max_drawdown_exceeded"

    def test_with_overrides(self) -> None:
        v = StrategyVerdict(
            accepted=True,
            overrides={"max_position_size": 75, "take_profit": 200},
        )
        assert v.accepted is True
        assert v.overrides == {"max_position_size": 75, "take_profit": 200}


# ---------------------------------------------------------------------------
# OrderSpec
# ---------------------------------------------------------------------------


class TestOrderSpec:
    def test_defaults(self) -> None:
        o = OrderSpec()
        assert o.symbol == ""
        assert o.side == "BUY"
        assert o.quantity == 0
        assert o.order_type == "LIMIT"
        assert o.price == 0.0

    def test_custom_values(self) -> None:
        o = OrderSpec(
            symbol="NIFTY",
            side="SELL",
            quantity=50,
            order_type="MARKET",
            price=18150.0,
        )
        assert o.symbol == "NIFTY"
        assert o.side == "SELL"
        assert o.quantity == 50
        assert o.order_type == "MARKET"
        assert o.price == 18150.0


# ---------------------------------------------------------------------------
# BaseStrategy (via concrete subclass)
# ---------------------------------------------------------------------------


class _ConcreteStrategy(BaseStrategy):
    """Minimal concrete subclass for testing BaseStrategy behaviour."""


class TestBaseStrategy:
    def test_matches_by_strategy_name(self) -> None:
        metadata = StrategyMetadata(id="VWAP_PULLBACK")
        strategy = _ConcreteStrategy(metadata)
        assert strategy.matches({"strategy": "VWAP_PULLBACK"}) is True
        assert strategy.matches({"strategy": "OTHER"}) is False
        assert strategy.matches({}) is False

    def test_validate_signal_defaults_to_accepted(self) -> None:
        metadata = StrategyMetadata(id="TEST")
        strategy = _ConcreteStrategy(metadata)
        verdict = strategy.validate_signal({"strategy": "TEST"})
        assert verdict.accepted is True

    def test_compute_order_default_nifty_50(self) -> None:
        metadata = StrategyMetadata(id="TEST")
        strategy = _ConcreteStrategy(metadata)
        order = strategy.compute_order(
            {"symbol": "NIFTY", "side": "BUY", "price": 18150.0}
        )
        assert order is not None
        assert order.symbol == "NIFTY"
        assert order.side == "BUY"
        assert order.quantity == 50
        assert order.order_type == "LIMIT"
        assert order.price == 18150.0

    def test_compute_order_default_banknifty_25(self) -> None:
        metadata = StrategyMetadata(id="TEST")
        strategy = _ConcreteStrategy(metadata)
        order = strategy.compute_order(
            {"symbol": "BANKNIFTY", "side": "BUY", "price": 50000.0}
        )
        assert order is not None
        assert order.symbol == "BANKNIFTY"
        assert order.side == "BUY"
        assert order.quantity == 25
        assert order.order_type == "LIMIT"
        assert order.price == 50000.0

    def test_on_execution_result_is_noop(self) -> None:
        metadata = StrategyMetadata(id="TEST")
        strategy = _ConcreteStrategy(metadata)
        # Should not raise, should return None
        result = strategy.on_execution_result({"status": "filled"})
        assert result is None


# ---------------------------------------------------------------------------
# StrategyRegistry
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    def test_register_and_get(self) -> None:
        registry = StrategyRegistry()
        strategy = _ConcreteStrategy("strat_a")
        registry.register(strategy)
        assert registry.get("strat_a") is strategy

    def test_register_duplicate_raises(self) -> None:
        registry = StrategyRegistry()
        registry.register(_ConcreteStrategy("dup"))
        with pytest.raises(DuplicateStrategyError):
            registry.register(_ConcreteStrategy("dup"))

    def test_get_for_signal_matches(self) -> None:
        registry = StrategyRegistry()
        registry.register(_ConcreteStrategy("trend"))
        registry.register(_ConcreteStrategy("mean_rev"))
        matched = registry.get_for_signal({"strategy": "mean_rev"})
        assert matched is not None
        assert matched.metadata.id == "mean_rev"

    def test_get_for_signal_no_match(self) -> None:
        registry = StrategyRegistry()
        registry.register(_ConcreteStrategy("trend"))
        assert registry.get_for_signal({"strategy": "unknown"}) is None

    def test_get_for_signal_empty_registry(self) -> None:
        registry = StrategyRegistry()
        assert registry.get_for_signal({"strategy": "anything"}) is None

    def test_all_returns_all(self) -> None:
        registry = StrategyRegistry()
        s1 = _ConcreteStrategy("s1")
        s2 = _ConcreteStrategy("s2")
        registry.register(s1)
        registry.register(s2)
        assert set(registry.all()) == {s1, s2}

    def test_unregister_removes(self) -> None:
        registry = StrategyRegistry()
        registry.register(_ConcreteStrategy("temp"))
        registry.unregister("temp")
        assert registry.get("temp") is None

    def test_clear_removes_all(self) -> None:
        registry = StrategyRegistry()
        registry.register(_ConcreteStrategy("a"))
        registry.register(_ConcreteStrategy("b"))
        registry.clear()
        assert registry.all() == []

    def test_register_empty_id_raises(self) -> None:
        registry = StrategyRegistry()
        with pytest.raises(ValueError, match="non-empty"):
            registry.register(_ConcreteStrategy(""))

    def test_register_and_unregister_is_idempotent(self) -> None:
        registry = StrategyRegistry()
        registry.unregister("nonexistent")
        assert True


# ---------------------------------------------------------------------------
# DefaultStrategy
# ---------------------------------------------------------------------------


class TestDefaultStrategy:
    def test_matches_always_false(self):
        strategy = DefaultStrategy()
        assert not strategy.matches({"strategy": "default"})
        assert not strategy.matches({"strategy": ""})
        assert not strategy.matches({"strategy": "VWAP_PULLBACK"})
        assert not strategy.matches({})

    def test_validate_signal_always_accepted(self):
        strategy = DefaultStrategy()
        verdict = strategy.validate_signal({"symbol": "NIFTY"})
        assert verdict.accepted

    def test_metadata_id_is_default(self):
        strategy = DefaultStrategy()
        assert strategy.metadata.id == "default"
        assert "Default (Legacy)" in strategy.metadata.display_name

    def test_compute_order_nifty(self):
        strategy = DefaultStrategy()
        order = strategy.compute_order({"symbol": "NIFTY", "side": "BUY", "price": 18100.0})
        assert order is not None
        assert order.symbol == "NIFTY"
        assert order.side == "BUY"
        assert order.quantity == 50
        assert order.price == 18100.0

    def test_compute_order_banknifty(self):
        strategy = DefaultStrategy()
        order = strategy.compute_order({"symbol": "BANKNIFTY", "side": "SELL", "price": 42000.0})
        assert order is not None
        assert order.quantity == 25

    def test_compute_order_unknown_symbol(self):
        strategy = DefaultStrategy()
        order = strategy.compute_order({"symbol": "FINNIFTY", "side": "BUY", "price": 100.0})
        assert order is not None
        assert order.quantity == 50

    def test_on_execution_result_noop(self):
        strategy = DefaultStrategy()
        strategy.on_execution_result({"status": "filled"})