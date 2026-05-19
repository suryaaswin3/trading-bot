"""Shared fixtures for trading bot tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
import pytz

from trading_bot.config import TradingBotConfig
from trading_bot.data import Candle
from trading_bot.state import reset_state

_IST = pytz.timezone("Asia/Kolkata")


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module-level state before each test that touches trading_bot.state."""
    reset_state()
    yield


@pytest.fixture
def sample_config() -> TradingBotConfig:
    """Default config with paper_mode=True for safe testing."""
    return TradingBotConfig()


@pytest.fixture
def market_open_config() -> TradingBotConfig:
    """Config with debug_mode=True for tests that verify debug logging."""
    return TradingBotConfig(debug_mode=True)


@pytest.fixture
def sample_candles() -> list[Candle]:
    """55 realistic candles for VWAP/strategy tests.

    Prices start at 18000 and gradually increase, creating a bullish trend.
    VWAP settles around 18050.
    """
    base = 18000.0
    candles: list[Candle] = []
    for i in range(55):
        o = base + i * 2.0
        h = o + 15.0
        l = o - 10.0
        c = o + 5.0
        dt = datetime(2025, 6, 15, 10, 0, 0, tzinfo=_IST) + __import__(
            "datetime"
        ).timedelta(minutes=5 * i)
        candles.append(
            Candle(open=o, high=h, low=l, close=c, volume=10000, timestamp=dt)
        )
    return candles


@pytest.fixture
def sample_candle_bearish() -> list[Candle]:
    """55 bearish candles — prices decrease, creating a downtrend."""
    base = 18200.0
    candles: list[Candle] = []
    for i in range(55):
        o = base - i * 2.0
        h = o + 10.0
        l = o - 15.0
        c = o - 5.0
        dt = datetime(2025, 6, 15, 10, 0, 0, tzinfo=_IST) + __import__(
            "datetime"
        ).timedelta(minutes=5 * i)
        candles.append(
            Candle(open=o, high=h, low=l, close=c, volume=10000, timestamp=dt)
        )
    return candles


@pytest.fixture
def mock_config() -> TradingBotConfig:
    """Config overridden with test-safe values for main_loop tests."""
    return TradingBotConfig(
        paper_mode=True,
        debug_mode=False,
        kite_api_key="test_key",
        kite_access_token="test_token",
    )


@pytest.fixture
def mock_kite() -> MagicMock:
    """Mock KiteClient with canned responses for main_loop tests."""
    kite = MagicMock()
    kite.is_connected.return_value = True
    kite.get_instruments.return_value = []
    kite.get_historical_data.return_value = []
    kite.get_ltp.return_value = {}
    kite.place_order.return_value = "TEST_ORDER_001"
    return kite
