"""Tests for trade plan enforcement."""
from __future__ import annotations

import pytest
from ops_api.trade_plan import TradePlan, PlanCheckResult, get_active_plan, set_active_plan, reset_plan


class TestTradePlanCheck:
    def test_approves_within_limits(self):
        plan = TradePlan(max_trades_per_session=5)
        result = plan.check({"trades": 0, "final_pnl": 0.0})
        assert result.approved
        assert result.reason == ""

    def test_rejects_max_trades(self):
        plan = TradePlan(max_trades_per_session=5)
        result = plan.check({"trades": 5, "final_pnl": 100.0})
        assert not result.approved
        assert "Max trades" in result.reason

    def test_rejects_daily_loss(self):
        plan = TradePlan(max_daily_loss=5000.0)
        result = plan.check({"trades": 1, "final_pnl": -6000.0})
        assert not result.approved
        assert "loss limit" in result.reason

    def test_rejects_daily_gain(self):
        plan = TradePlan(max_daily_gain=10000.0)
        result = plan.check({"trades": 1, "final_pnl": 12000.0})
        assert not result.approved
        assert "gain limit" in result.reason

    def test_default_plan(self):
        plan = TradePlan()
        assert plan.max_trades_per_session == 5
        assert plan.allowed_regimes == ("TREND", "VOLATILE")
        assert plan.min_quality is None
        assert plan.min_alignment is None


class TestTradePlanSerde:
    def test_to_dict(self):
        plan = TradePlan(plan_id="test-plan", max_trades_per_session=3)
        d = plan.to_dict()
        assert d["plan_id"] == "test-plan"
        assert d["max_trades_per_session"] == 3
        assert d["min_quality"] is None

    def test_from_dict(self):
        plan = TradePlan.from_dict({
            "plan_id": "loaded",
            "max_trades_per_session": 2,
            "min_quality": 0.7,
            "allowed_regimes": ["TREND"],
        })
        assert plan.plan_id == "loaded"
        assert plan.max_trades_per_session == 2
        assert plan.min_quality == 0.7
        assert plan.allowed_regimes == ("TREND",)


class TestActivePlan:
    def test_default_active(self):
        reset_plan()
        plan = get_active_plan()
        assert plan.plan_id == "default"

    def test_set_active(self):
        reset_plan()
        plan = TradePlan(plan_id="custom", max_trades_per_session=2)
        set_active_plan(plan)
        assert get_active_plan().plan_id == "custom"
        assert get_active_plan().max_trades_per_session == 2

    def test_reset(self):
        plan = TradePlan(plan_id="custom")
        set_active_plan(plan)
        reset_plan()
        assert get_active_plan().plan_id == "default"