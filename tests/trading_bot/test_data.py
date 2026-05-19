"""Candle data and VWAP calculation tests."""

from __future__ import annotations

from datetime import datetime

import pytz

from trading_bot.data import (
    Candle,
    build_candles,
    compute_atr,
    compute_average_volume,
    compute_ema,
    compute_ema_slope,
    compute_vwap,
    detect_market_regime,
    get_orb_range,
)

_IST = pytz.timezone("Asia/Kolkata")


def _candle(
    o: float,
    h: float,
    lo: float,
    c: float,
    v: int = 10000,
    i: int = 0,
) -> Candle:
    return Candle(
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=v,
        timestamp=datetime(2025, 6, 15, 10, 0, 0, tzinfo=_IST)
        + __import__("datetime").timedelta(minutes=5 * i),
    )


def _trending_candles(count: int = 55) -> list[Candle]:
    """N candles trending up strongly from 18000 (10 pts/candle)."""
    return [
        _candle(18000 + i * 10, 18100 + i * 10, 17900 + i * 10, 18050 + i * 10, i=i)
        for i in range(count)
    ]


def _flat_candles(count: int = 55) -> list[Candle]:
    """N candles in a tight range."""
    return [_candle(18000, 18020, 17980, 18000, v=10000, i=i) for i in range(count)]


# ========================================================================
# BUILD CANDLES
# ========================================================================
class TestBuildCandles:
    def test_none_input(self) -> None:
        assert build_candles(None) == []

    def test_empty_list(self) -> None:
        assert build_candles([]) == []

    def test_valid_candles(self) -> None:
        raw = [
            {
                "date": "2025-06-15T09:15:00+05:30",
                "open": "18100",
                "high": "18150",
                "low": "18080",
                "close": "18120",
                "volume": "50000",
            },
        ]
        result = build_candles(raw)
        assert len(result) == 1
        c = result[0]
        assert c.open == 18100.0
        assert c.high == 18150.0
        assert c.low == 18080.0
        assert c.close == 18120.0
        assert c.volume == 50000
        assert c.timestamp.tzinfo is not None

    def test_skip_bad_data(self) -> None:
        raw = [
            {"open": "1", "high": "2", "low": "1", "close": "2", "volume": "10"},
            {
                "date": "2025-06-15T09:15:00+05:30",
                "open": "18100",
                "high": "18150",
                "low": "18080",
                "close": "18120",
                "volume": "50000",
            },
        ]
        result = build_candles(raw)
        assert len(result) == 1  # First row skipped (no date)


# ========================================================================
# VWAP
# ========================================================================
class TestComputeVWAP:
    def test_empty_candles(self) -> None:
        assert compute_vwap([]) is None

    def test_zero_volume(self) -> None:
        candles = [
            Candle(
                open=100,
                high=110,
                low=90,
                close=105,
                volume=0,
                timestamp=datetime.now(_IST),
            ),
        ]
        assert compute_vwap(candles) is None

    def test_basic_vwap(self) -> None:
        candles = [
            Candle(
                open=100,
                high=110,
                low=90,
                close=105,
                volume=1000,
                timestamp=datetime.now(_IST),
            ),
            Candle(
                open=106,
                high=115,
                low=100,
                close=110,
                volume=2000,
                timestamp=datetime.now(_IST),
            ),
        ]
        # Candle 1 typical = (110+90+105)/3 = 101.6667
        # Candle 2 typical = (115+100+110)/3 = 108.3333
        # VWAP = (101.6667*1000 + 108.3333*2000) / 3000 = 106.1111
        vwap = compute_vwap(candles)
        assert vwap is not None
        assert abs(vwap - 106.1111) < 0.01


# ========================================================================
# EMA
# ========================================================================
class TestComputeEMA:
    def test_insufficient_data(self) -> None:
        assert compute_ema([1.0, 2.0], 5) is None

    def test_basic_ema(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        ema = compute_ema(values, 5)
        assert ema is not None
        assert ema > 0  # Basic sanity


# ========================================================================
# ORB
# ========================================================================
class TestGetORBRange:
    def test_insufficient_candles(self) -> None:
        assert get_orb_range([], 5) is None

    def test_basic_range(self) -> None:
        candles = [
            Candle(
                open=100,
                high=110,
                low=90,
                close=105,
                volume=1000,
                timestamp=datetime.now(_IST),
            ),
            Candle(
                open=106,
                high=112,
                low=102,
                close=108,
                volume=1000,
                timestamp=datetime.now(_IST),
            ),
        ]
        result = get_orb_range(candles, 2)
        assert result is not None
        high, low = result
        assert high == 112.0
        assert low == 90.0


# ========================================================================
# ATR
# ========================================================================
class TestComputeATR:
    def test_insufficient_candles(self) -> None:
        assert compute_atr([], 14) is None
        assert compute_atr([_candle(18000, 18100, 17900, 18050, i=0)], 14) is None

    def test_basic_atr(self) -> None:
        """All candles same range → ATR equals the range."""
        candles = [_candle(18000, 18100, 17900, 18050, i=i) for i in range(20)]
        atr = compute_atr(candles, 14)
        assert atr is not None
        # Each candle has range = 200, so ATR should be close to 200
        assert abs(atr - 200.0) < 10.0

    def test_atr_with_gaps(self) -> None:
        """Gaps between candles increase ATR."""
        candles = [
            Candle(
                open=100,
                high=110,
                low=90,
                close=105,
                volume=1000,
                timestamp=datetime.now(_IST),
            ),
            Candle(
                open=200,
                high=210,
                low=190,
                close=205,
                volume=1000,
                timestamp=datetime.now(_IST),
            ),
        ]
        candles.extend(
            Candle(
                open=200 + i,
                high=210 + i,
                low=190 + i,
                close=205 + i,
                volume=1000,
                timestamp=datetime.now(_IST),
            )
            for i in range(2, 20)
        )
        atr = compute_atr(candles, 14)
        assert atr is not None
        assert atr > 0


# ========================================================================
# EMA SLOPE
# ========================================================================
class TestComputeEMASlope:
    def test_insufficient_data(self) -> None:
        assert compute_ema_slope([1.0, 2.0], 5, 3) is None

    def test_positive_slope(self) -> None:
        values = list(range(100))
        slope = compute_ema_slope(values, 20, 3)
        assert slope is not None
        assert slope > 0

    def test_negative_slope(self) -> None:
        values = list(range(100, 0, -1))
        slope = compute_ema_slope(values, 20, 3)
        assert slope is not None
        assert slope < 0

    def test_flat_slope(self) -> None:
        values = [50.0] * 100
        slope = compute_ema_slope(values, 20, 3)
        assert slope is not None
        assert abs(slope) < 0.01


# ========================================================================
# AVERAGE VOLUME
# ========================================================================
class TestComputeAverageVolume:
    def test_insufficient_data(self) -> None:
        assert compute_average_volume([], 20) is None

    def test_basic_average(self) -> None:
        candles = [_candle(18000, 18100, 17900, 18050, v=10000, i=i) for i in range(20)]
        avg = compute_average_volume(candles, 20)
        assert avg is not None
        assert avg == 10000.0

    def test_partial_window(self) -> None:
        candles = [
            _candle(18000, 18100, 17900, 18050, v=i * 1000, i=i) for i in range(20)
        ]
        avg = compute_average_volume(candles, 10)
        assert avg is not None
        assert avg > 0


# ========================================================================
# MARKET REGIME DETECTION
# ========================================================================
class TestDetectMarketRegime:
    def test_trending_up(self) -> None:
        candles = _trending_candles(55)
        regime = detect_market_regime(
            candles, ema_slope_threshold=2.0, atr_threshold=50.0
        )
        assert regime == "TRENDING"

    def test_ranging(self) -> None:
        candles = _flat_candles(55)
        regime = detect_market_regime(
            candles, ema_slope_threshold=5.0, atr_threshold=5.0
        )
        # Slope is near-zero, ATR is > 5 (range is 40), so RANGING
        assert regime == "RANGING"

    def test_low_vol(self) -> None:
        """Low ATR with low slope → LOW_VOL."""
        candles = [_candle(18000, 18001, 17999, 18000, v=10000, i=i) for i in range(55)]
        regime = detect_market_regime(
            candles, ema_slope_threshold=5.0, atr_threshold=5.0
        )
        assert regime == "LOW_VOL"

    def test_insufficient_candles_returns_ranging(self) -> None:
        regime = detect_market_regime([], ema_slope_threshold=5.0, atr_threshold=50.0)
        assert regime == "RANGING"
