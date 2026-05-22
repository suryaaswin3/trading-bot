"""Tests for deterministic exit strategy evaluation."""
from __future__ import annotations

import pytest
from ops_api.exits import (
    ExitConfig, ExitSignal, evaluate_exits,
    trailing_stop, break_even_stop, chandelier_exit,
    momentum_fade_exit, time_based_exit, vwap_loss_of_control,
)


def _bar(open, high, low, close, volume, timestamp=0.0):
    return {"open": open, "high": high, "low": low, "close": close, "volume": volume}


def _trend_bars(up: bool = True, count: int = 60):
    direction = 1.0 if up else -1.0
    closes = [100 + i * direction * 0.3 for i in range(count)]
    return [_bar(c - 1, c + 2, c - 1, c, 1000) for c in closes]


# ── Trailing Stop ───────────────────────────────────────────────────────────


class TestTrailingStop:
    def test_not_activated(self):
        """Price hasn't moved far enough → not triggered."""
        signal = trailing_stop(
            "LONG", entry_price=100.0, current_price=100.5,
            atr_value=2.0, bars_since_entry=5, config=ExitConfig(),
        )
        assert not signal.triggered
        assert "not_activated" in signal.reason

    def test_activated_long(self):
        """LONG, price moved favourably → sets exit level."""
        signal = trailing_stop(
            "LONG", entry_price=100.0, current_price=105.0,
            atr_value=2.0, bars_since_entry=10, config=ExitConfig(),
        )
        assert not signal.triggered  # Evaluated by caller
        assert signal.exit_price > 0
        assert signal.strategy == "trailing_stop"

    def test_activated_short(self):
        """SHORT, price moved favourably → sets exit level."""
        signal = trailing_stop(
            "SHORT", entry_price=100.0, current_price=94.0,
            atr_value=2.0, bars_since_entry=10, config=ExitConfig(),
        )
        assert not signal.triggered
        assert signal.exit_price > 0

    def test_priority(self):
        """Trailing stop has priority 3."""
        signal = trailing_stop(
            "LONG", 100, 105, atr_value=2.0,
            bars_since_entry=10, config=ExitConfig(),
        )
        assert signal.priority == 3


# ── Break-Even Stop ─────────────────────────────────────────────────────────


class TestBreakEvenStop:
    def test_target_not_met(self):
        """Not enough favourable move → not triggered."""
        signal = break_even_stop(
            "LONG", entry_price=100.0, current_price=100.5,
            atr_value=2.0, config=ExitConfig(),
        )
        assert not signal.triggered
        assert "target_not_met" in signal.reason

    def test_activated_long(self):
        """LONG hit target → triggered, exit near entry + buffer."""
        signal = break_even_stop(
            "LONG", entry_price=100.0, current_price=104.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert signal.triggered
        assert signal.exit_price > 100.0  # entry + buffer

    def test_activated_short(self):
        """SHORT hit target → triggered, exit near entry - buffer."""
        signal = break_even_stop(
            "SHORT", entry_price=100.0, current_price=95.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert signal.triggered
        assert signal.exit_price < 100.0  # entry - buffer

    def test_priority(self):
        """Break-even has priority 5."""
        signal = break_even_stop("LONG", 100, 104, atr_value=2.0, config=ExitConfig())
        assert signal.priority == 5


# ── Chandelier Exit ─────────────────────────────────────────────────────────


class TestChandelierExit:
    def test_triggered_long(self):
        """LONG retraced more than threshold → triggered."""
        signal = chandelier_exit(
            "LONG", current_price=94.0, peak=100.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert signal.triggered
        assert signal.reason.startswith("retraced")
        assert signal.priority == 1

    def test_not_triggered_long(self):
        """LONG retraced less than threshold → not triggered."""
        signal = chandelier_exit(
            "LONG", current_price=98.0, peak=100.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert not signal.triggered

    def test_triggered_short(self):
        """SHORT retraced more than threshold → triggered."""
        signal = chandelier_exit(
            "SHORT", current_price=106.0, peak=100.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert signal.triggered

    def test_not_triggered_short(self):
        """SHORT retraced less than threshold → not triggered."""
        signal = chandelier_exit(
            "SHORT", current_price=102.0, peak=100.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert not signal.triggered

    def test_priority_one(self):
        """Chandelier has priority 1 (highest)."""
        signal = chandelier_exit(
            "LONG", current_price=94.0, peak=100.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert signal.priority == 1


# ── Momentum Fade Exit ──────────────────────────────────────────────────────


class TestMomentumFadeExit:
    def test_not_reached(self):
        """Price hasn't hit target → not triggered."""
        signal = momentum_fade_exit(
            "LONG", entry_price=100.0, current_price=102.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert not signal.triggered
        assert "building" in signal.reason

    def test_triggered_long(self):
        """LONG hit profit target → triggered."""
        signal = momentum_fade_exit(
            "LONG", entry_price=100.0, current_price=108.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert signal.triggered
        assert "profit_target_met" in signal.reason

    def test_triggered_short(self):
        """SHORT hit profit target → triggered."""
        signal = momentum_fade_exit(
            "SHORT", entry_price=100.0, current_price=92.0,
            atr_value=2.0, config=ExitConfig(),
        )
        assert signal.triggered

    def test_priority(self):
        """Momentum fade has priority 2."""
        signal = momentum_fade_exit("LONG", 100, 108, atr_value=2.0, config=ExitConfig())
        assert signal.priority == 2


# ── Time-Based Exit ─────────────────────────────────────────────────────────


class TestTimeBasedExit:
    def test_holding(self):
        """Under max hold → not triggered."""
        signal = time_based_exit(
            "LONG", entry_price=100.0, current_price=100.5,
            bars_since_entry=10, atr_value=2.0, config=ExitConfig(),
        )
        assert not signal.triggered
        assert "holding" in signal.reason

    def test_triggered_max_hold_reached(self):
        """Exceeded max hold with insufficient progress → triggered."""
        signal = time_based_exit(
            "LONG", entry_price=100.0, current_price=100.2,
            bars_since_entry=65, atr_value=2.0, config=ExitConfig(),
        )
        assert signal.triggered
        assert "max_hold_reached" in signal.reason

    def test_adequate_progress_extended(self):
        """Exceeded max hold but made progress → not triggered."""
        signal = time_based_exit(
            "LONG", entry_price=100.0, current_price=102.0,
            bars_since_entry=65, atr_value=2.0, config=ExitConfig(),
        )
        assert not signal.triggered
        assert "adequate_progress" in signal.reason

    def test_priority(self):
        """Time-based has priority 6 (lowest)."""
        signal = time_based_exit("LONG", 100, 100.2, bars_since_entry=65, atr_value=2.0, config=ExitConfig())
        assert signal.priority == 6


# ── VWAP Loss of Control ────────────────────────────────────────────────────


class TestVWAPLossOfControl:
    def test_insufficient_data(self):
        """No bars since entry → not triggered."""
        signal = vwap_loss_of_control(
            "LONG", current_price=100.0, vwap_value=0.0,
            atr_value=2.0, bars_since_entry=0, config=ExitConfig(),
        )
        assert not signal.triggered
        assert "insufficient_data" in signal.reason

    def test_long_below_vwap(self):
        """LONG below VWAP by threshold → triggered."""
        # Price at 97, VWAP at 100, deviation -3, atr=2 → |dev|/atr = 1.5 >= 1.0
        signal = vwap_loss_of_control(
            "LONG", current_price=97.0, vwap_value=100.0,
            atr_value=2.0, bars_since_entry=3, config=ExitConfig(),
        )
        assert signal.triggered
        assert "price_below_vwap" in signal.reason

    def test_long_above_vwap(self):
        """LONG above VWAP → not triggered (in control)."""
        signal = vwap_loss_of_control(
            "LONG", current_price=101.0, vwap_value=100.0,
            atr_value=2.0, bars_since_entry=3, config=ExitConfig(),
        )
        assert not signal.triggered
        assert "in_control" in signal.reason

    def test_short_above_vwap(self):
        """SHORT above VWAP by threshold → triggered."""
        signal = vwap_loss_of_control(
            "SHORT", current_price=103.0, vwap_value=100.0,
            atr_value=2.0, bars_since_entry=3, config=ExitConfig(),
        )
        assert signal.triggered
        assert "price_above_vwap" in signal.reason

    def test_short_below_vwap(self):
        """SHORT below VWAP → not triggered (in control)."""
        signal = vwap_loss_of_control(
            "SHORT", current_price=99.0, vwap_value=100.0,
            atr_value=2.0, bars_since_entry=3, config=ExitConfig(),
        )
        assert not signal.triggered

    def test_insufficient_confirmation_bars(self):
        """Less than confirmation_bars since entry → not triggered."""
        signal = vwap_loss_of_control(
            "LONG", current_price=97.0, vwap_value=100.0,
            atr_value=2.0, bars_since_entry=1, config=ExitConfig(),
        )
        assert not signal.triggered
        assert "insufficient_data" in signal.reason

    def test_priority(self):
        """VWAP LOC has priority 4."""
        signal = vwap_loss_of_control(
            "LONG", current_price=97.0, vwap_value=100.0,
            atr_value=2.0, bars_since_entry=3, config=ExitConfig(),
        )
        assert signal.priority == 4


# ── Aggregation ─────────────────────────────────────────────────────────────


class TestEvaluateExits:
    def test_returns_signals(self):
        """Returns list of ExitSignal."""
        bars = _trend_bars(up=True, count=60)
        signals = evaluate_exits(
            position_side="LONG", entry_price=100.0,
            current_price=105.0, bars=bars, entry_index=50,
        )
        assert len(signals) > 0
        assert all(isinstance(s, ExitSignal) for s in signals)

    def test_sorted_by_priority(self):
        """Signals sorted by priority ascending."""
        bars = _trend_bars(up=True, count=60)
        signals = evaluate_exits(
            position_side="LONG", entry_price=100.0,
            current_price=105.0, bars=bars, entry_index=50,
        )
        priorities = [s.priority for s in signals]
        assert priorities == sorted(priorities)

    def test_no_atr_returns_empty(self):
        """No ATR → empty list."""
        bars = [_bar(100, 100, 100, 100, 1000) for _ in range(3)]
        signals = evaluate_exits(
            position_side="LONG", entry_price=100.0,
            current_price=100.0, bars=bars, entry_index=0,
        )
        assert signals == []

    def test_empty_bars(self):
        """Empty bars → no crash."""
        signals = evaluate_exits(
            position_side="LONG", entry_price=100.0,
            current_price=100.0, bars=[], entry_index=0,
        )
        assert signals == []

    def test_barsnapshot_input(self):
        """BarSnapshot-like objects accepted."""
        from types import SimpleNamespace
        bars = [SimpleNamespace(open=100 + i, high=102 + i, low=98 + i, close=101 + i, volume=1000) for i in range(60)]
        signals = evaluate_exits(
            position_side="LONG", entry_price=100.0,
            current_price=105.0, bars=bars, entry_index=50,
        )
        assert len(signals) > 0

    def test_custom_config(self):
        """Custom config overrides defaults."""
        bars = _trend_bars(up=True, count=60)
        config = ExitConfig(chandelier_atr_multiple=0.5)  # very tight
        signals = evaluate_exits(
            position_side="LONG", entry_price=100.0,
            current_price=105.0, bars=bars, entry_index=50,
            config=config,
        )
        # Tight chandelier should be triggered
        chandelier = [s for s in signals if s.strategy == "chandelier"]
        assert chandelier[0].triggered

    def test_all_six_strategies(self):
        """All 6 exit strategies present."""
        bars = _trend_bars(up=True, count=60)
        signals = evaluate_exits(
            position_side="LONG", entry_price=100.0,
            current_price=105.0, bars=bars, entry_index=50,
        )
        strategies = {s.strategy for s in signals}
        expected = {"trailing_stop", "break_even", "chandelier", "momentum_fade", "time_based", "vwap_loc"}
        assert strategies == expected

    def test_sell_side(self):
        """SHORT side produces valid signals."""
        bars = _trend_bars(up=True, count=60)
        signals = evaluate_exits(
            position_side="SHORT", entry_price=100.0,
            current_price=95.0, bars=bars, entry_index=50,
        )
        assert len(signals) > 0
        assert all(isinstance(s, ExitSignal) for s in signals)