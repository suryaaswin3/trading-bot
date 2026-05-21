"""Tests for deterministic breakout quality scoring."""
from __future__ import annotations

import pytest
from ops_api.quality import (
    QualityConfig, QualityScore, score_breakout,
    score_rvol, score_candle_strength, score_vwap,
    score_ema_trend, score_range_expansion, score_time_window,
)


def _bar(open, high, low, close, volume, timestamp=0.0):
    return {"open": open, "high": high, "low": low, "close": close, "volume": volume}


# ── RVOL ────────────────────────────────────────────────────────────────────


class TestRVOL:
    def test_high_volume(self):
        """Current vol >> avg → score near 1.0."""
        bars = [_bar(100, 105, 95, 102, v) for v in [100]*20 + [300]]
        assert score_rvol(bars) >= 0.8

    def test_average_volume(self):
        """Current vol ≈ avg → score near 0."""
        bars = [_bar(100, 105, 95, 102, v) for v in [100]*21]
        assert score_rvol(bars) < 0.1

    def test_low_volume(self):
        """Current vol below avg → score 0."""
        bars = [_bar(100, 105, 95, 102, v) for v in [100]*20 + [50]]
        assert score_rvol(bars) == 0.0

    def test_insufficient_bars(self):
        """Not enough bars → score 0."""
        assert score_rvol([_bar(100, 105, 95, 102, 100) for _ in range(5)]) == 0.0


# ── Candle Strength ─────────────────────────────────────────────────────────


class TestCandleStrength:
    def test_strong_buy_candle(self):
        """Full body, close at high → near 1.0."""
        bar = _bar(100, 110, 100, 110, 1000)
        assert score_candle_strength(bar, "BUY") >= 0.9

    def test_weak_buy_candle(self):
        """Small body, close near middle → low score."""
        bar = _bar(100, 110, 90, 103, 1000)
        assert score_candle_strength(bar, "BUY") < 0.3

    def test_strong_sell_candle(self):
        """Full body, close at low → near 1.0."""
        bar = _bar(110, 110, 100, 100, 1000)
        assert score_candle_strength(bar, "SELL") >= 0.9

    def test_buy_candle_close_low(self):
        """BUY signal with close at range low → 0."""
        bar = _bar(110, 110, 100, 100, 1000)
        assert score_candle_strength(bar, "BUY") == 0.0

    def test_flat_range(self):
        """No range → 0."""
        bar = _bar(100, 100, 100, 100, 1000)
        assert score_candle_strength(bar, "BUY") == 0.0


# ── VWAP Alignment ──────────────────────────────────────────────────────────


class TestVWAP:
    def test_buy_above_vwap(self):
        """BUY signal above VWAP → positive score."""
        # Flat baseline then slight uptick — VWAP lags slightly, price near VWAP
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(10)]
        bars += [_bar(101, 103, 99, 102, 1000) for _ in range(10)]
        assert score_vwap(bars, "BUY") > 0.5

    def test_buy_below_vwap(self):
        """BUY signal below VWAP → 0."""
        bars = [_bar(100 - i, 105 - i, 95 - i, 102 - i, 1000) for i in range(20)]
        assert score_vwap(bars, "BUY") == 0.0

    def test_sell_below_vwap(self):
        """SELL signal below VWAP → positive score."""
        bars = [_bar(100 - i, 105 - i, 95 - i, 102 - i, 1000) for i in range(20)]
        assert score_vwap(bars, "SELL") > 0.5

    def test_sell_above_vwap(self):
        """SELL signal above VWAP → 0."""
        bars = [_bar(100 + i, 105 + i, 95 + i, 102 + i, 1000) for i in range(20)]
        assert score_vwap(bars, "SELL") == 0.0


# ── EMA Trend ───────────────────────────────────────────────────────────────


class TestEMATrend:
    def test_rising_trend(self):
        """EMA20 > EMA50, both rising → high score."""
        closes = [100 + i * 0.5 for i in range(60)]
        bars = [_bar(c - 2, c + 2, c - 2, c, 1000) for c in closes]
        assert score_ema_trend(bars) > 0.5

    def test_falling_trend(self):
        """Both EMAs falling → still positive (trend strength, not direction)."""
        closes = [200 - i * 0.5 for i in range(60)]
        bars = [_bar(c - 2, c + 2, c - 2, c, 1000) for c in closes]
        assert score_ema_trend(bars) > 0.5

    def test_flat_market(self):
        """No clear trend → low score."""
        closes = [100] * 60
        bars = [_bar(c - 2, c + 2, c - 2, c, 1000) for c in closes]
        assert score_ema_trend(bars) < 0.5

    def test_insufficient_bars(self):
        """Not enough bars → 0."""
        bars = [_bar(100, 105, 95, 102, 1000) for _ in range(10)]
        assert score_ema_trend(bars) == 0.0


# ── Range Expansion ─────────────────────────────────────────────────────────


class TestRangeExpansion:
    def test_wide_range(self):
        """Current range >> ATR → near 1.0."""
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(15)]
        bars[-1] = _bar(100, 115, 95, 110, 2000)  # wide expansion bar
        assert score_range_expansion(bars) >= 0.8

    def test_narrow_range(self):
        """Current range < ATR → low score."""
        bars = [_bar(100, 105, 95, 101, 1000) for _ in range(15)]
        bars[-1] = _bar(100, 101, 99, 100, 800)  # narrow bar
        assert score_range_expansion(bars) < 0.5

    def test_insufficient_bars(self):
        """Not enough bars → 0."""
        bars = [_bar(100, 105, 95, 101, 1000) for _ in range(5)]
        assert score_range_expansion(bars) == 0.0


# ── Time Window ─────────────────────────────────────────────────────────────


class TestTimeWindow:
    def test_peak_hours(self):
        """9:15-11:25 IST → 1.0."""
        # 10:00 IST = 4:30 UTC
        ts = 0 + 4.5 * 3600  # 4:30 UTC
        assert score_time_window(ts) == 1.0

    def test_midday(self):
        """11:25-15:00 IST → 0.5."""
        # 13:00 IST = 7:30 UTC
        ts = 0 + 7.5 * 3600  # 7:30 UTC
        assert score_time_window(ts) == 0.5

    def test_close_phase(self):
        """15:00-15:30 IST → 0.0."""
        # 15:15 IST = 9:45 UTC
        ts = 0 + 9.75 * 3600  # 9:45 UTC
        assert score_time_window(ts) == 0.0

    def test_outside_hours(self):
        """Before market open → 0.0."""
        ts = 0 + 3 * 3600  # 3:00 UTC = 8:30 IST
        assert score_time_window(ts) == 0.0

    def test_none_timestamp(self):
        """No timestamp → 1.0 (skip filter)."""
        assert score_time_window(None) == 1.0


# ── Aggregation ─────────────────────────────────────────────────────────────


class TestScoreBreakout:
    def test_accepted(self):
        """All dimensions strong → accepted=True."""
        closes = [100 + i * 0.5 for i in range(60)]
        bars = [_bar(c - 2, c + 2, c - 2, c, 1000) for c in closes]
        bars[-1] = _bar(125, 130, 124, 129, 5000)  # strong breakout bar
        result = score_breakout(bars, {"side": "BUY", "price": 129.0})
        assert result.accepted
        assert result.total >= 0.5

    def test_rejected(self):
        """All dimensions weak → accepted=False."""
        bars = [_bar(100, 101, 99, 100, 100) for _ in range(60)]
        result = score_breakout(bars, {"side": "BUY", "price": 100.0})
        assert not result.accepted
        assert result.reason != "" and result.reason != "all_good"

    def test_empty_bars(self):
        """Empty bars → no crash, all zeros."""
        result = score_breakout([], {"side": "BUY", "price": 0.0})
        assert result.total == 0.0
        assert not result.accepted

    def test_barsnapshot_input(self):
        """BarSnapshot-like objects accepted."""
        from types import SimpleNamespace
        bars = [SimpleNamespace(open=100, high=105, low=95, close=102, volume=1000, timestamp=0) for _ in range(60)]
        bars[-1] = SimpleNamespace(open=125, high=130, low=124, close=129, volume=5000, timestamp=0)
        result = score_breakout(bars, {"side": "BUY", "price": 129.0})
        assert result.accepted

    def test_custom_config(self):
        """Custom config overrides defaults."""
        bars = [_bar(100, 101, 99, 100, 100) for _ in range(60)]
        config = QualityConfig(min_quality=0.1)  # very low bar
        result = score_breakout(bars, {"side": "BUY", "price": 100.0}, config=config)
        assert result.accepted  # any positive score clears 0.1

    def test_result_type(self):
        """Returns QualityScore dataclass."""
        result = score_breakout([], {"side": "BUY", "price": 0.0})
        assert isinstance(result, QualityScore)


# ── Weights invariant ───────────────────────────────────────────────────────


class TestWeights:
    def test_weights_sum_to_one(self):
        """Default weights sum to 1.0."""
        c = QualityConfig()
        total = c.weight_rvol + c.weight_candle + c.weight_vwap + c.weight_ema + c.weight_range + c.weight_time
        assert abs(total - 1.0) < 0.001