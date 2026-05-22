"""Tests for entry timing refinement."""
from __future__ import annotations

import pytest
from ops_api.timing import (
    TimingConfig, TimingResult, check_entry_timing,
    check_oversized_candle, check_exhausted_breakout,
    check_retest, check_pullback, check_micro_consolidation,
)


def _bar(open, high, low, close, volume, timestamp=0.0):
    return {"open": open, "high": high, "low": low, "close": close, "volume": volume}


def _flat_bars(count: int = 20, vol: float = 1000):
    return [_bar(100, 102, 98, 101, vol) for _ in range(count)]


def _trend_bars(up: bool = True, count: int = 60):
    direction = 1.0 if up else -1.0
    closes = [100 + i * direction * 0.3 for i in range(count)]
    return [_bar(c - 1, c + 1, c - 1, c, 1000) for c in closes]


# ── Oversized Candle ────────────────────────────────────────────────────────


class TestOversizedCandle:
    def test_normal_candle(self):
        """Normal range → allowed (None)."""
        bars = _flat_bars(20)
        bars[-1] = _bar(100, 102, 99, 101, 1000)  # range=3 at ATR=2 → 3 < 5
        result = check_oversized_candle(bars, atr_value=2.0, config=TimingConfig())
        assert result is None

    def test_oversized_range(self):
        """Range >> ATR → rejected."""
        bars = _flat_bars(20)
        bars[-1] = _bar(100, 115, 85, 110, 1000)  # range=30 >> 2*2.5=5
        result = check_oversized_candle(bars, atr_value=2.0, config=TimingConfig())
        assert result is not None
        assert not result.allowed
        assert "oversized_candle" in result.reason

    def test_volume_spike(self):
        """Volume >> avg → rejected."""
        vol = [1000] * 19 + [10000]
        bars = [_bar(100, 102, 98, 101, v) for v in vol]
        result = check_oversized_candle(bars, atr_value=2.0, config=TimingConfig())
        assert result is not None
        assert not result.allowed
        assert "volume_spike" in result.reason

    def test_insufficient_bars(self):
        """Less than 2 bars → None."""
        result = check_oversized_candle(
            [_bar(100, 102, 98, 101, 1000)], atr_value=2.0, config=TimingConfig(),
        )
        assert result is None

    def test_zero_atr(self):
        """Zero ATR → skip range check, may still fail volume."""
        bars = [_bar(100, 115, 85, 110, 1000) for _ in range(20)]
        result = check_oversized_candle(bars, atr_value=0.0, config=TimingConfig())
        assert result is None or not result.allowed


# ── Exhausted Breakout ──────────────────────────────────────────────────────


class TestExhaustedBreakout:
    def test_healthy_momentum(self):
        """Sustained ranges → not exhausted (None)."""
        bars = _flat_bars(15)
        bars += [_bar(100, 110, 90, 105, 2000) for _ in range(5)]  # sustained
        result = check_exhausted_breakout(bars, atr_value=2.0, config=TimingConfig())
        assert result is None

    def test_exhausted(self):
        """Ranges shrinking → exhausted."""
        # Start wide, end narrow
        bars = _flat_bars(15)
        bars += [_bar(100, 112, 88, 105, 2000)]  # wide
        bars += [_bar(100, 108, 92, 104, 1800)]  # less wide
        bars += [_bar(100, 103, 97, 102, 1500)]  # narrow
        bars += [_bar(100, 102, 98, 101, 1200)]  # narrower
        bars += [_bar(100, 101, 99, 100, 1000)]  # narrowest
        result = check_exhausted_breakout(bars, atr_value=2.0, config=TimingConfig())
        assert result is not None
        assert not result.allowed
        assert "exhausted_breakout" in result.reason

    def test_insufficient_bars(self):
        """Less than breakout_lookback + 3 → None."""
        bars = _flat_bars(5)
        result = check_exhausted_breakout(bars, atr_value=2.0, config=TimingConfig())
        assert result is None

    def test_flat_market(self):
        """All bars flat → None (no exhaustion pattern)."""
        bars = _flat_bars(20)
        result = check_exhausted_breakout(bars, atr_value=2.0, config=TimingConfig())
        assert result is None


# ── Retest ──────────────────────────────────────────────────────────────────


class TestRetest:
    def test_buy_retest(self):
        """BUY: price pulling back to breakout level → allowed."""
        # Breakout bar then pullback
        bars = _flat_bars(10)
        bars += [_bar(100, 115, 95, 112, 5000)]  # breakout (range=20)
        bars += [_bar(112, 113, 108, 109, 2000)]  # pullback ~15% of range
        result = check_retest(bars, "BUY", atr_value=5.0, config=TimingConfig())
        assert result is not None
        assert result.allowed
        assert result.method == "retest"
        assert result.preferred_entry == "limit"

    def test_sell_retest(self):
        """SELL: price pulling back to breakout level → allowed."""
        bars = _flat_bars(10)
        bars += [_bar(110, 115, 95, 98, 5000)]  # breakout down (range=20)
        bars += [_bar(98, 102, 95, 100, 2000)]  # pullback ~10% of range
        result = check_retest(bars, "SELL", atr_value=5.0, config=TimingConfig())
        assert result is not None
        assert result.allowed
        assert result.method == "retest"

    def test_no_retest(self):
        """Price continued away from breakout → None."""
        bars = _flat_bars(10)
        bars += [_bar(100, 115, 95, 112, 5000)]  # breakout
        bars += [_bar(112, 120, 110, 118, 3000)]  # continuation, no pullback
        result = check_retest(bars, "BUY", atr_value=5.0, config=TimingConfig())
        assert result is None

    def test_insufficient_bars(self):
        """Less than retest_max_bars + 2 → None."""
        bars = _flat_bars(3)
        result = check_retest(bars, "BUY", atr_value=2.0, config=TimingConfig())
        assert result is None

    def test_flat_breakout_range(self):
        """All bars have zero range → None."""
        bars = [_bar(100, 100, 100, 100, 1000) for _ in range(10)]
        bars += [_bar(100, 100, 100, 100, 1000)]  # zero-range
        bars += [_bar(100, 100, 100, 100, 1000)]  # also zero-range
        result = check_retest(bars, "BUY", atr_value=5.0, config=TimingConfig())
        assert result is None  # breakout_range <= 0 returns None


# ── Pullback ────────────────────────────────────────────────────────────────


class TestPullback:
    def test_buy_pullback(self):
        """BUY in uptrend, price near EMA → allowed."""
        # Strong uptrend, last bar dips near EMA (deviation within -0.3 to 0.15)
        # Use high ATR (20) so deviation stays tiny
        closes = [100 + i * 0.3 for i in range(30)]
        bars = [_bar(c - 1, c + 1, c - 1, c, 1000) for c in closes]
        bars[-1] = _bar(108, 109, 107, 107.5, 1000)  # near EMA
        result = check_pullback(bars, "BUY", atr_value=20.0, config=TimingConfig())
        assert result is not None
        assert result.allowed
        assert result.method == "pullback"
        assert result.preferred_entry == "limit"

    def test_buy_no_trend(self):
        """No uptrend → None."""
        bars = _flat_bars(30)
        result = check_pullback(bars, "BUY", atr_value=2.0, config=TimingConfig())
        assert result is None

    def test_insufficient_bars(self):
        """Less than 25 bars → None."""
        bars = _flat_bars(10)
        result = check_pullback(bars, "BUY", atr_value=2.0, config=TimingConfig())
        assert result is None

    def test_zero_atr(self):
        """Zero ATR → deviation=0, still within bounds → pullback detected."""
        bars = _trend_bars(up=True, count=30)
        result = check_pullback(bars, "BUY", atr_value=0.0, config=TimingConfig())
        # deviation = (close - ema) / 0 → Runtime handling: the function uses
        # `if atr_value > 0 else 0.0` so deviation will be 0.0, within bounds
        assert result is not None


# ── Micro Consolidation ─────────────────────────────────────────────────────


class TestMicroConsolidation:
    def test_consolidation_detected(self):
        """Tight range bars → allowed."""
        # Wide bar then tight bars (range must be < 0.3 * ATR)
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(10)]
        bars += [_bar(100, 115, 85, 110, 5000)]  # breakout (range=30)
        # Tight: range/ATR = 1.0/10.0 = 0.1 < 0.3 ✓; 1.5/10.0 = 0.15 < 0.3 ✓
        bars += [_bar(110, 111, 110, 110.5, 800)]  # range=1.0, tight
        bars += [_bar(110.5, 111.5, 110, 111, 800)]  # range=1.5, tight
        result = check_micro_consolidation(bars, atr_value=10.0, config=TimingConfig())
        assert result is not None
        assert result.allowed
        assert result.method == "consolidation"

    def test_no_consolidation(self):
        """Wide range bars → None."""
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(10)]
        bars += [_bar(100, 115, 85, 110, 5000)]
        bars += [_bar(110, 118, 102, 115, 3000)]  # wide, not tight
        result = check_micro_consolidation(bars, atr_value=5.0, config=TimingConfig())
        assert result is None

    def test_insufficient_bars(self):
        """Less than consolidation_max_bars + 2 → None."""
        bars = _flat_bars(3)
        result = check_micro_consolidation(bars, atr_value=2.0, config=TimingConfig())
        assert result is None

    def test_zero_breakout_range(self):
        """Breakout bar zero range → None."""
        bars = _flat_bars(10)
        bars += [_bar(100, 100, 100, 100, 1000)]
        bars += [_bar(100, 101, 99, 100, 1000) for _ in range(2)]
        result = check_micro_consolidation(bars, atr_value=2.0, config=TimingConfig())
        assert result is None


# ── Aggregation ─────────────────────────────────────────────────────────────


class TestCheckEntryTiming:
    def test_insufficient_data(self):
        """Too few bars → immediate entry allowed."""
        result = check_entry_timing(
            [_bar(100, 102, 98, 101, 1000) for _ in range(10)], "BUY",
        )
        assert result.allowed
        assert result.method == "immediate"
        assert "insufficient_data" in result.reason

    def test_no_atr(self):
        """Zero ATR → immediate entry."""
        result = check_entry_timing(
            [_bar(100, 100, 100, 100, 1000) for _ in range(20)], "BUY",
        )
        assert result.allowed
        assert "no_atr" in result.reason

    def test_normal_entry(self):
        """Normal conditions → immediate entry."""
        bars = _trend_bars(up=True, count=30)
        result = check_entry_timing(bars, "BUY")
        assert result.allowed

    def test_oversized_rejected(self):
        """Oversized candle → rejected."""
        bars = _flat_bars(20)
        bars[-1] = _bar(100, 120, 80, 115, 5000)  # massive range
        result = check_entry_timing(bars, "BUY")
        assert not result.allowed
        assert "oversized_candle" in result.reason

    def test_retest_preferred(self):
        """Retest pattern → allowed with retest method."""
        bars = _flat_bars(15)  # 15+ for ATR
        bars += [_bar(100, 115, 95, 112, 5000)]  # breakout (range=20)
        bars += [_bar(112, 113, 108, 109, 2000)]  # pullback (peak=115, close=109, pullback=6/20=0.3)
        result = check_entry_timing(bars, "BUY")
        assert result.allowed
        assert result.method == "retest"

    def test_empty_bars(self):
        """Empty bars → no crash."""
        result = check_entry_timing([], "BUY")
        assert result.allowed
        assert "insufficient_data" in result.reason



    def test_custom_config(self):
        """Custom config overrides defaults."""
        bars = _flat_bars(20)
        config = TimingConfig(max_candle_atr_multiple=0.5)  # very tight
        bars[-1] = _bar(100, 103, 97, 101, 1000)  # range=6 > 0.5*2
        result = check_entry_timing(bars, "BUY", config=config)
        assert not result.allowed

    def test_result_type(self):
        """Returns TimingResult dataclass."""
        result = check_entry_timing([], "BUY")
        assert isinstance(result, TimingResult)

    def test_barsnapshot_input(self):
        """BarSnapshot-like objects accepted."""
        from types import SimpleNamespace
        bars = [SimpleNamespace(open=100 + i, high=102 + i, low=98 + i, close=101 + i, volume=1000) for i in range(30)]
        result = check_entry_timing(bars, "BUY")
        assert isinstance(result, TimingResult)

    def test_sell_side(self):
        """SELL side processes without error."""
        bars = _trend_bars(up=False, count=30)
        result = check_entry_timing(bars, "SELL")
        assert isinstance(result.allowed, bool)

    def test_metrics_present(self):
        """Result may contain metrics."""
        bars = _flat_bars(20)
        bars[-1] = _bar(100, 120, 80, 115, 5000)
        result = check_entry_timing(bars, "BUY")
        assert isinstance(result.metrics, dict)