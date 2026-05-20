"""Market data tests — OHLCV cache, provider interface, Kite provider."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from ops_api.market_data.base import OHLCVCache, BarSnapshot
from ops_api.market_data.kite_provider import KiteConnectMarketData


class TestBarSnapshot:
    def test_creates_with_minimal_fields(self) -> None:
        bar = BarSnapshot(symbol="NIFTY", interval="60", open=18100.0, high=18200.0, low=18000.0, close=18150.0, volume=500000, timestamp=1234567890.0)
        assert bar.symbol == "NIFTY"
        assert bar.close == 18150.0


class TestOHLCVCache:
    def test_store_and_retrieve(self) -> None:
        cache = OHLCVCache()
        bars = [BarSnapshot(symbol="NIFTY", interval="60", open=100.0, high=105.0, low=99.0, close=102.0, volume=1000, timestamp=1.0)]
        cache.set("NIFTY", "60", bars)
        retrieved = cache.get("NIFTY", "60")
        assert retrieved is not None and len(retrieved) == 1 and retrieved[0].close == 102.0

    def test_get_missing_returns_none(self) -> None:
        assert OHLCVCache().get("NIFTY", "60") is None

    def test_cache_ttl_expiry(self) -> None:
        cache = OHLCVCache(ttl_seconds=0.1)
        cache.set("NIFTY", "60", [BarSnapshot(symbol="NIFTY", interval="60", open=100.0, high=105.0, low=99.0, close=102.0, volume=1000, timestamp=1.0)])
        assert cache.get("NIFTY", "60") is not None
        time.sleep(0.15)
        assert cache.get("NIFTY", "60") is None

    def test_cache_clear(self) -> None:
        cache = OHLCVCache()
        cache.set("NIFTY", "60", [BarSnapshot(symbol="NIFTY", interval="60", open=100.0, close=102.0, high=105.0, low=99.0, volume=1000, timestamp=1.0)])
        cache.clear()
        assert cache.get("NIFTY", "60") is None


class TestKiteConnectMarketData:
    def test_fetch_returns_bars_with_mocked_kite(self) -> None:
        mock_kite = MagicMock()
        mock_kite.historical_data.return_value = [{"date": "2026-05-20T09:15:00+05:30", "open": 18100.0, "high": 18200.0, "low": 18000.0, "close": 18150.0, "volume": 500000}]
        provider = KiteConnectMarketData(mock_kite)
        bars = provider.fetch("NIFTY", "60", count=1)
        assert len(bars) == 1 and bars[0].close == 18150.0

    def test_fetch_error_returns_empty(self) -> None:
        mock_kite = MagicMock()
        mock_kite.historical_data.side_effect = RuntimeError("API error")
        assert KiteConnectMarketData(mock_kite).fetch("NIFTY", "60") == []