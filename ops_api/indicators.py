"""Pure-function technical indicators operating on OHLCV bar dicts.

Each indicator takes a list of bar dicts with keys:
    open, high, low, close, volume

And returns a list of computed values — one per input bar — so the
result index i corresponds to input bar i.
"""

from __future__ import annotations

from typing import Any


def ema(bars: list[dict[str, Any]], period: int = 20) -> list[float]:
    """Exponential Moving Average.

    First ``period - 1`` values use simple average of available data (SMA),
    then switches to EMA smoothing::

        multiplier = 2 / (period + 1)
        ema[i] = (close[i] - ema[i-1]) * multiplier + ema[i-1]
    """
    if not bars:
        return []

    closes = [b["close"] for b in bars]
    result: list[float] = []
    multiplier = 2.0 / (period + 1)

    for i, close in enumerate(closes):
        if i < period:
            window = closes[: i + 1]
            result.append(sum(window) / len(window))
        else:
            result.append((close - result[i - 1]) * multiplier + result[i - 1])

    return result


def atr(bars: list[dict[str, Any]], period: int = 14) -> list[float]:
    """Average True Range (Smoothed).

    True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))

    First ``period`` true-range values are SMA-averaged, then EMA-smoothed
    like Wilder's ATR. Returns 0.0 for bars where there isn't enough
    history yet.
    """
    if not bars:
        return []

    tr_values: list[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            tr = b["high"] - b["low"]
        else:
            tr = max(
                b["high"] - b["low"],
                abs(b["high"] - bars[i - 1]["close"]),
                abs(b["low"] - bars[i - 1]["close"]),
            )
        tr_values.append(tr)

    result: list[float] = []
    for i in range(len(tr_values)):
        if i < period:
            window = tr_values[: i + 1]
            result.append(sum(window) / len(window))
        else:
            result.append(
                (result[i - 1] * (period - 1) + tr_values[i]) / period
            )

    return result


def vwap(bars: list[dict[str, Any]]) -> list[float]:
    """Volume-Weighted Average Price (cumulative).

    VWAP[i] = sum(tp[j] * vol[j] for j <= i) / sum(vol[j] for j <= i)

    Where typical price tp = (high + low + close) / 3
    """
    cum_pv = 0.0
    cum_vol = 0.0
    result: list[float] = []

    for b in bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_pv += tp * b["volume"]
        cum_vol += b["volume"]
        result.append(cum_pv / cum_vol if cum_vol > 0 else 0.0)

    return result