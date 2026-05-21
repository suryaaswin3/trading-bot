"""Tests for deterministic market regime detection."""
from __future__ import annotations

import pytest
from ops_api.regime import (
    RegimeConfig, RegimeState, detect_regime,
    _detect_ema_separation, _detect_vwap_slope,
    _detect_atr_ratio, _detect_range_ratio, _detect_candle_overlap,
)


def _bar(open, high, low, close, volume, timestamp=0.0):
    return {"open": open, "high": high, "low": low, "close": close, "volume": volume}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _trend_bars(up: bool = True, strength: float = 0.5, count: int = 60):
    """Generate trending bars. Up or down with given per-bar strength."""
    direction = 1.0 if up else -1.0
    closes = [100 + i * direction * strength for i in range(count)]
    return [_bar(c - 1, c + 2, c - 1.5, c, 1000) for c in closes]


def _range_bars(center: float = 100, width: float = 3, count: int = 60):
    """Generate range-bound bars oscillating around center."""
    bars = []
    for i in range(count):
        offset = (i % 6 - 3) * width / 3
        c = center + offset
        bars.append(_bar(c - 1 + offset * 0.3, c + 1.5 + abs(offset) * 0.5, c - 1.5 - abs(offset) * 0.5, c, 500))
    return bars


def _volatile_bars():
    """Generate bars with a sudden volatility spike at the end.

    First 45 bars: quiet (range ~2). Next 9 bars: moderately wide (range ~6).
    Last bar: extreme spike (range 24+). This creates a high ATR ratio AND
    high range ratio because avg_range (over 14 prior bars) is ~mid and
    current bar range is huge.
    """
    bars = []
    for i in range(45):
        c = 100
        bars.append(_bar(c - 1, c + 1, c - 1, c, 500))
    for i in range(9):
        wiggle = (i % 2) * 0.5
        c = 100 + wiggle
        bars.append(_bar(c - 2, c + 4, c - 3, c + 1, 1500))
    # Final bar: extreme volatility spike
    bars.append(_bar(100, 120, 96, 115, 5000))
    return bars


def _dead_bars():
    """Generate bars with a sudden compression at the end.

    First 45 bars: moderate range (~3). Next 9 bars: narrowing (range ~0.5).
    Last bar: doji with tiny range (~0.1) and a small body so overlap
    detection works.
    """
    bars = []
    for i in range(45):
        c = 100
        bars.append(_bar(c - 1.5, c + 1.5, c - 1.5, c, 500))
    for i in range(9):
        bars.append(_bar(100, 100.5, 99.5, 100, 200))
    # Final bar: doji with tiny range and non-zero body for overlap detection
    bars.append(_bar(99.98, 100.05, 99.95, 100.02, 100))
    return bars


# ── EMA Separation ──────────────────────────────────────────────────────────


class TestEMASeparation:
    def test_rising_trend_separation(self):
        """Rising prices → positive EMA separation."""
        bars = _trend_bars(up=True, strength=0.5)
        result = _detect_ema_separation(bars, RegimeConfig())
        assert result["sep"] > 0.005
        assert result["direction"] > 0

    def test_falling_trend_separation(self):
        """Falling prices → negative EMA direction."""
        bars = _trend_bars(up=False, strength=0.5)
        result = _detect_ema_separation(bars, RegimeConfig())
        assert result["sep"] > 0.005
        assert result["direction"] < 0

    def test_flat_no_separation(self):
        """Flat prices → minimal EMA separation."""
        bars = _dead_bars()
        result = _detect_ema_separation(bars, RegimeConfig())
        assert result["sep"] < 0.005

    def test_insufficient_bars(self):
        """Not enough bars → zero separation."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(10)]
        result = _detect_ema_separation(bars, RegimeConfig())
        assert result["sep"] == 0.0


# ── VWAP Slope ──────────────────────────────────────────────────────────────


class TestVWAPSlope:
    def test_rising_slope(self):
        """Rising prices → positive VWAP slope."""
        bars = _trend_bars(up=True, strength=0.3, count=30)
        slope = _detect_vwap_slope(bars)
        assert slope > 0

    def test_falling_slope(self):
        """Falling prices → negative VWAP slope."""
        bars = _trend_bars(up=False, strength=0.3, count=30)
        slope = _detect_vwap_slope(bars)
        assert slope < 0

    def test_flat_slope(self):
        """Flat prices → near-zero VWAP slope."""
        bars = _dead_bars()
        slope = _detect_vwap_slope(bars)
        assert abs(slope) < 0.001

    def test_insufficient_bars(self):
        """Not enough bars → zero."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(3)]
        assert _detect_vwap_slope(bars) == 0.0


# ── ATR Ratio ────────────────────────────────────────────────────────────────


class TestATRRatio:
    def test_volatile_expansion(self):
        """Wide recent ranges → high ATR ratio."""
        bars = _volatile_bars()
        ratio = _detect_atr_ratio(bars, RegimeConfig())
        assert ratio > 1.3

    def test_dead_compression(self):
        """Narrow ranges → low ATR ratio."""
        bars = _dead_bars()
        ratio = _detect_atr_ratio(bars, RegimeConfig())
        assert ratio < 0.8

    def test_insufficient_bars(self):
        """Not enough bars → 1.0 (neutral)."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(5)]
        assert _detect_atr_ratio(bars, RegimeConfig()) == 1.0


# ── Range Ratio ──────────────────────────────────────────────────────────────


class TestRangeRatio:
    def test_wide_last_bar(self):
        """Last bar much wider than average → high ratio."""
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(15)]
        bars[-1] = _bar(100, 115, 95, 110, 2000)
        ratio = _detect_range_ratio(bars, RegimeConfig())
        assert ratio > 1.5

    def test_narrow_last_bar(self):
        """Last bar much narrower → low ratio."""
        bars = [_bar(100, 103, 97, 100, 1000) for _ in range(15)]
        bars[-1] = _bar(100, 100.5, 99.5, 100, 200)
        ratio = _detect_range_ratio(bars, RegimeConfig())
        assert ratio < 0.5

    def test_insufficient_bars(self):
        """Not enough bars → 1.0."""
        assert _detect_range_ratio([_bar(100, 101, 99, 100, 1000)], RegimeConfig()) == 1.0


# ── Candle Overlap ───────────────────────────────────────────────────────────


class TestCandleOverlap:
    def test_high_overlap(self):
        """Small bodies inside prior ranges → high overlap."""
        # Prior bar has wide range, current bodies are inside it
        bars = [
            _bar(100, 110, 90, 105, 1000),
            _bar(102, 108, 94, 106, 1000),
            _bar(103, 107, 95, 104, 1000),
            _bar(102, 109, 93, 107, 1000),
            _bar(101, 108, 94, 105, 1000),
            _bar(103, 106, 96, 104, 1000),
        ]
        overlap = _detect_candle_overlap(bars)
        assert overlap > 0.5

    def test_low_overlap(self):
        """Bodies extending beyond prior ranges → low overlap."""
        # Directional bars that push outside prior ranges
        bars = [
            _bar(100, 102, 98, 101, 1000),
            _bar(101, 105, 100, 104, 1000),
            _bar(104, 108, 103, 107, 1000),
            _bar(107, 112, 106, 111, 1000),
            _bar(111, 116, 110, 115, 1000),
            _bar(115, 120, 114, 119, 1000),
        ]
        overlap = _detect_candle_overlap(bars)
        assert overlap < 0.4

    def test_insufficient_bars(self):
        """Not enough bars → 0.5 (neutral)."""
        assert _detect_candle_overlap([_bar(100, 101, 99, 100, 1000)]) == 0.5


# ── Regime Classification ────────────────────────────────────────────────────


class TestDetectRegime:
    def test_trend_up(self):
        """Strong uptrend → TREND regime."""
        bars = _trend_bars(up=True, strength=0.5, count=60)
        result = detect_regime(bars)
        assert result.regime == "TREND"
        assert result.breakout_allowed is True

    def test_trend_down(self):
        """Strong downtrend → TREND regime."""
        bars = _trend_bars(up=False, strength=0.5, count=60)
        result = detect_regime(bars)
        assert result.regime == "TREND"
        assert result.breakout_allowed is True

    def test_range_market(self):
        """Oscillating market → RANGE regime."""
        bars = _range_bars(center=100, width=3, count=60)
        result = detect_regime(bars)
        assert result.regime == "RANGE"
        assert result.breakout_allowed is False

    def test_volatile_market(self):
        """Wide ranges, high ATR → VOLATILE regime."""
        bars = _volatile_bars()
        result = detect_regime(bars)
        assert result.regime == "VOLATILE"
        assert result.breakout_allowed is True

    def test_dead_market(self):
        """Flat, narrow range → DEAD regime."""
        bars = _dead_bars()
        result = detect_regime(bars)
        assert result.regime == "DEAD"
        assert result.breakout_allowed is False

    def test_empty_bars(self):
        """Empty bars → DEAD, no crash."""
        result = detect_regime([])
        assert result.regime == "DEAD"
        assert result.breakout_allowed is False
        assert "insufficient_data" in result.reasons

    def test_insufficient_bars(self):
        """< 30 bars → DEAD."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(20)]
        result = detect_regime(bars)
        assert result.regime == "DEAD"

    def test_barsnapshot_input(self):
        """BarSnapshot-like objects accepted."""
        from types import SimpleNamespace
        bars = [SimpleNamespace(open=100 + i * 0.3, high=102 + i * 0.3, low=98 + i * 0.3, close=101 + i * 0.3, volume=1000) for i in range(60)]
        result = detect_regime(bars)
        assert result.regime in ("TREND", "RANGE", "VOLATILE", "DEAD")
        assert hasattr(result, "confidence")

    def test_custom_config(self):
        """Custom config overrides defaults."""
        bars = _dead_bars()
        config = RegimeConfig(ema_sep_trend=0.001, atr_dead=0.1, atr_volatile=10.0)
        result = detect_regime(bars, config=config)
        assert isinstance(result, RegimeState)

    def test_result_type(self):
        """Returns RegimeState dataclass."""
        result = detect_regime([])
        assert isinstance(result, RegimeState)

    def test_confidence_range(self):
        """Confidence is always 0.0–1.0."""
        for gen in (_trend_bars(up=True), _range_bars(), _dead_bars(), _volatile_bars()):
            result = detect_regime(gen)
            assert 0.0 <= result.confidence <= 1.0

    def test_metrics_present(self):
        """Metrics dict has expected keys."""
        bars = _trend_bars(up=True)
        result = detect_regime(bars)
        for key in ("ema_separation", "ema_direction", "vwap_slope", "atr_ratio", "range_ratio", "candle_overlap"):
            assert key in result.metrics

    def test_reasons_nonempty(self):
        """Non-empty bars produce reasons."""
        bars = _trend_bars(up=True)
        result = detect_regime(bars)
        assert len(result.reasons) > 0


# ── RegimeConfig defaults ────────────────────────────────────────────────────


class TestRegimeConfig:
    def test_default_weights_valid(self):
        """Default config thresholds are self-consistent."""
        c = RegimeConfig()
        assert c.ema_sep_trend > c.ema_sep_dead
        assert c.atr_volatile > 1.0
        assert c.atr_dead < 1.0
        assert c.range_volatile > 1.0
        assert c.range_dead < 1.0
        assert 0 < c.min_confidence < 1