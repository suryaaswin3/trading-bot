"""Candle data structures and calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pytz

_IST = pytz.timezone("Asia/Kolkata")


# ========================
# DATA STRUCTURES
# ========================
@dataclass(frozen=True)
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime


@dataclass(frozen=True)
class VWAPState:
    cumulative_typical: float
    cumulative_volume: int
    vwap: float


# ========================
# BUILD CANDLES
# ========================
def build_candles(
    raw_data: list[dict[str, Any]] | None,
) -> list[Candle]:
    if not raw_data:
        return []

    candles: list[Candle] = []

    for item in raw_data:
        dt = item.get("date")

        # --- SAFE DATETIME HANDLING ---
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)

        elif isinstance(dt, date) and not isinstance(dt, datetime):
            dt = datetime.combine(dt, datetime.min.time())

        elif not isinstance(dt, datetime):
            continue  # skip bad data

        # --- TIMEZONE FIX ---
        if dt.tzinfo is None:
            dt = _IST.localize(dt)

        candles.append(
            Candle(
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=int(item["volume"]),
                timestamp=dt,
            )
        )

    return candles


# ========================
# VWAP
# ========================
def compute_vwap(candles: list[Candle]) -> float | None:
    if not candles:
        return None

    cum_typical = 0.0
    cum_vol = 0

    for c in candles:
        typical = (c.high + c.low + c.close) / 3.0
        cum_typical += typical * c.volume
        cum_vol += c.volume

    if cum_vol == 0:
        return None

    return cum_typical / cum_vol


def compute_session_vwap(candles: list[Candle]) -> VWAPState | None:
    if not candles:
        return None

    cum_typical = 0.0
    cum_vol = 0

    for c in candles:
        typical = (c.high + c.low + c.close) / 3.0
        cum_typical += typical * c.volume
        cum_vol += c.volume

    if cum_vol == 0:
        return None

    return VWAPState(
        cumulative_typical=cum_typical,
        cumulative_volume=cum_vol,
        vwap=cum_typical / cum_vol,
    )


def update_vwap(state: VWAPState, candle: Candle) -> VWAPState:
    typical = (candle.high + candle.low + candle.close) / 3.0

    new_typical = state.cumulative_typical + typical * candle.volume
    new_vol = state.cumulative_volume + candle.volume

    return VWAPState(
        cumulative_typical=new_typical,
        cumulative_volume=new_vol,
        vwap=new_typical / new_vol,
    )


# ========================
# ORB
# ========================
def get_orb_range(
    candles: list[Candle],
    num_candles: int = 1,  # 🔥 FIX: true 5-min ORB
) -> tuple[float, float] | None:

    if len(candles) < num_candles:
        return None

    orb = candles[:num_candles]

    high = max(c.high for c in orb)
    low = min(c.low for c in orb)

    return high, low


# ========================
# EMA
# ========================
def compute_ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None

    multiplier = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


# ========================
# ATR (AVERAGE TRUE RANGE)
# ========================
def compute_atr(candles: list[Candle], period: int = 14) -> float | None:
    """Average True Range for volatility measurement.

    Returns ``None`` if fewer than ``period + 1`` candles are available
    (need at least one prior candle for the first true-range calculation).
    """
    if len(candles) < period + 1:
        return None

    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        prev = candles[i - 1]
        curr = candles[i]
        tr = max(
            curr.high - curr.low,
            abs(curr.high - prev.close),
            abs(curr.low - prev.close),
        )
        true_ranges.append(tr)

    # Simple SMA of the first ``period`` TR values, then EMA of the rest
    atr = sum(true_ranges[:period]) / period

    multiplier = 2.0 / (period + 1.0)
    for tr in true_ranges[period:]:
        atr = (tr - atr) * multiplier + atr

    return atr


# ========================
# EMA SLOPE
# ========================
def compute_ema_slope(
    values: list[float],
    period: int = 20,
    lookback: int = 3,
) -> float | None:
    """Slope of EMA over the last ``lookback`` periods.

    Returns price change per period (positive = rising, negative = falling,
    near-zero = sideways).  ``None`` if insufficient data.
    """
    ema = compute_ema(values, period)
    if ema is None:
        return None

    # Need at least lookback + 1 values to compute a meaningful slope
    if len(values) < period + lookback:
        return None

    # Compute a second EMA point ``lookback`` periods earlier
    earlier_ema = compute_ema(values[: len(values) - lookback], period)
    if earlier_ema is None:
        return None

    return (ema - earlier_ema) / lookback


# ========================
# AVERAGE VOLUME
# ========================
def compute_average_volume(candles: list[Candle], period: int = 20) -> float | None:
    """Average volume over the last N candles."""
    if len(candles) < period:
        return None

    return sum(c.volume for c in candles[-period:]) / period


# ========================
# MARKET REGIME DETECTION
# ========================
def detect_market_regime(
    candles: list[Candle],
    ema_slope_threshold: float = 5.0,
    atr_threshold: float = 50.0,
    ema_fast_period: int = 20,
    ema_slow_period: int = 50,
) -> str:
    """Classify market as ``"TRENDING"``, ``"RANGING"``, or ``"LOW_VOL"``.

    - **TRENDING**: absolute EMA slope exceeds  *ema_slope_threshold*.
    - **LOW_VOL**: ATR is below *atr_threshold*.
    - **RANGING**: everything else (low slope, normal volatility).

    Trending takes priority over low-vol (a trending market with low ATR
    is still trending).
    """
    closes = [c.close for c in candles]
    slope = compute_ema_slope(closes, ema_fast_period)
    atr = compute_atr(candles, ema_fast_period)

    if slope is not None and abs(slope) > ema_slope_threshold:
        return "TRENDING"
    if atr is not None and atr < atr_threshold:
        return "LOW_VOL"
    return "RANGING"


# ========================
# DATA VALIDATION
# ========================
def check_data_stale(
    last_update: datetime | None,
    threshold_seconds: float = 5.0,
) -> bool:
    if last_update is None:
        return True

    if last_update.tzinfo is None:
        last_update = _IST.localize(last_update)

    now = datetime.now(_IST)

    return (now - last_update).total_seconds() > threshold_seconds


# ========================
# UTILITIES
# ========================
def filter_candles_since(
    candles: list[Candle],
    since: datetime,
) -> list[Candle]:

    if since.tzinfo is None:
        since = _IST.localize(since)

    return [c for c in candles if c.timestamp >= since]


def candle_slice_by_count(candles: list[Candle], count: int) -> list[Candle]:
    return candles[-count:] if len(candles) >= count else list(candles)


def round_to_candle_time(dt: datetime, interval_minutes: int = 5) -> datetime:
    if dt.tzinfo is None:
        dt = _IST.localize(dt)

    ist_dt = dt.astimezone(_IST)

    truncated = ist_dt.replace(second=0, microsecond=0)
    floored = (truncated.minute // interval_minutes) * interval_minutes

    return truncated.replace(minute=floored)


__all__ = [
    "Candle",
    "VWAPState",
    "build_candles",
    "candle_slice_by_count",
    "check_data_stale",
    "compute_atr",
    "compute_average_volume",
    "compute_ema",
    "compute_ema_slope",
    "compute_session_vwap",
    "compute_vwap",
    "detect_market_regime",
    "filter_candles_since",
    "get_orb_range",
    "round_to_candle_time",
    "update_vwap",
]
