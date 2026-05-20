"""Indicator tests — EMA, ATR, VWAP as pure functions."""

from __future__ import annotations

import math

import pytest

from ops_api.indicators import atr, ema, vwap


def _make_bars(prices: list[float]) -> list[dict]:
    """Convert close-price list to OHLCV bar dicts (HL=close*1.02/0.98 for range)."""
    bars = []
    for i, c in enumerate(prices):
        high = round(c * 1.02, 2)
        low = round(c * 0.98, 2)
        bars.append({
            "open": round(c * 0.99, 2),
            "high": high,
            "low": low,
            "close": c,
            "volume": 100000 + i * 100,
        })
    return bars


class TestEMA:
    def test_ema_returns_correct_length(self) -> None:
        bars = _make_bars([float(i) for i in range(1, 21)])
        result = ema(bars, period=10)
        assert len(result) == len(bars)

    def test_ema_early_values_are_sma(self) -> None:
        bars = _make_bars([float(i) for i in range(1, 11)])
        result = ema(bars, period=5)
        # first period-1 values are SMA of available data
        assert math.isclose(result[0], 1.0, rel_tol=1e-3)
        assert math.isclose(result[1], 1.5, rel_tol=1e-3)
        assert math.isclose(result[2], 2.0, rel_tol=1e-3)
        assert math.isclose(result[3], 2.5, rel_tol=1e-3)

    def test_ema_trending_up(self) -> None:
        bars = _make_bars([float(i) for i in range(1, 31)])
        result = ema(bars, period=10)
        assert result[-1] < bars[-1]["close"]

    def test_ema_known_values(self) -> None:
        closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
        bars = _make_bars(closes)
        result = ema(bars, period=5)
        assert all(math.isfinite(v) for v in result)
        assert result[-1] > 14.0


class TestATR:
    def test_atr_returns_correct_length(self) -> None:
        bars = _make_bars([float(i) for i in range(1, 21)])
        result = atr(bars, period=14)
        assert len(result) == len(bars)

    def test_atr_early_values_nonzero(self) -> None:
        bars = _make_bars([float(i) for i in range(1, 11)])
        result = atr(bars, period=5)
        # first period values are SMA of TR, which is > 0 for _make_bars
        for i in range(4):
            assert result[i] > 0.0
        # first TR = high-low for bar[0]
        assert math.isclose(result[0], 0.04, rel_tol=1e-3)

    def test_atr_positive_value(self) -> None:
        bars = _make_bars([float(i) for i in range(1, 31)])
        result = atr(bars, period=14)
        assert result[-1] > 0.0

    def test_atr_high_volatility(self) -> None:
        low_vol = _make_bars([100.0 + i for i in range(30)])
        high_vol = []
        for i in range(30):
            high_vol.append({
                "open": 100.0 + i,
                "high": 100.0 + i + 5,
                "low": 100.0 + i - 5,
                "close": 100.0 + i,
                "volume": 100000,
            })
        low_atr = atr(low_vol, period=14)[-1]
        high_atr = atr(high_vol, period=14)[-1]
        assert high_atr > low_atr


class TestVWAP:
    def test_vwap_single_bar(self) -> None:
        bars = [{"high": 105, "low": 95, "close": 100, "volume": 1000}]
        result = vwap(bars)
        assert math.isclose(result[-1], 100.0, rel_tol=1e-3)

    def test_vwap_multi_bar(self) -> None:
        bars = [
            {"high": 105, "low": 95, "close": 100, "volume": 1000},
            {"high": 115, "low": 105, "close": 110, "volume": 2000},
        ]
        result = vwap(bars)
        assert math.isclose(result[-1], 106.67, rel_tol=1e-2)

    def test_vwap_returns_all_bars(self) -> None:
        bars = [
            {"high": 105, "low": 95, "close": 100, "volume": 1000},
            {"high": 115, "low": 105, "close": 110, "volume": 2000},
        ]
        result = vwap(bars)
        assert len(result) == 2