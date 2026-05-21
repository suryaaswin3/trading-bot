"""Deterministic breakout quality scoring — stateless, pure functions.

Each scoring dimension is an independent function returning 0.0–1.0.
score_breakout() aggregates all six into a QualityScore dataclass.

Usage::

    qs = score_breakout(bars, signal)
    if qs.accepted:
        ...  # dispatch to strategy engine
    else:
        logger.info("Rejected: %s", qs.reason)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class QualityConfig:
    """Tunable thresholds for breakout quality scoring."""

    min_quality: float = 0.5
    rvol_period: int = 20
    rvol_threshold: float = 1.5
    min_candle_body_pct: float = 0.4
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    range_multiple: float = 1.0
    enable_time_window: bool = True

    # Component weights (must sum to 1.0)
    weight_rvol: float = 0.25
    weight_candle: float = 0.20
    weight_vwap: float = 0.20
    weight_ema: float = 0.15
    weight_range: float = 0.10
    weight_time: float = 0.10


# ── Result ──────────────────────────────────────────────────────────────────


@dataclass
class QualityScore:
    """Result of breakout quality assessment."""

    rvol: float
    candle_strength: float
    vwap_alignment: float
    ema_trend: float
    range_expansion: float
    time_quality: float
    total: float
    accepted: bool
    reason: str


# ── Helpers ─────────────────────────────────────────────────────────────────


def _ema(values: list[float], period: int) -> list[float]:
    """Simple EMA for internal use — operates on float lists."""
    if not values:
        return []
    result: list[float] = []
    multiplier = 2.0 / (period + 1)
    for i, v in enumerate(values):
        if i < period:
            window = values[: i + 1]
            result.append(sum(window) / len(window))
        else:
            result.append((v - result[i - 1]) * multiplier + result[i - 1])
    return result


def _atr(bars: list[dict[str, Any]], period: int) -> list[float]:
    """Simple ATR for internal use."""
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
            result.append((result[i - 1] * (period - 1) + tr_values[i]) / period)
    return result


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ── Scoring Dimensions ──────────────────────────────────────────────────────


def score_rvol(bars: list[dict[str, Any]], period: int = 20) -> float:
    """Relative volume. 1.0 = 3x+ average volume, 0.0 = at or below threshold."""
    if len(bars) < period + 1:
        return 0.0
    volumes = [b["volume"] for b in bars]
    current_vol = volumes[-1]
    avg_vol = sum(volumes[-(period + 1) : -1]) / period
    if avg_vol <= 0:
        return 0.0
    rvol = current_vol / avg_vol
    # 1.5x threshold → score 0.25, 3x → 1.0, linear in between
    return _clamp((rvol - 1.0) / 2.0)


def score_candle_strength(last_bar: dict[str, Any], side: str) -> float:
    """Candle body-to-range ratio with direction check.

    BUY: close should be in top 50% of range, strong body = conviction
    SELL: close should be in bottom 50% of range
    """
    high = last_bar["high"]
    low = last_bar["low"]
    o = last_bar["open"]
    close = last_bar["close"]
    rng = high - low
    if rng <= 0:
        return 0.0
    body = abs(close - o)
    body_pct = body / rng

    # Direction check: where is close relative to the range?
    # BUY: close in top half → 1.0, at midpoint → 0.5, bottom → 0.0
    # SELL: close in bottom half → 1.0, at midpoint → 0.5, top → 0.0
    close_position = (close - low) / rng  # 0.0 = low, 1.0 = high
    if side == "BUY":
        dir_score = _clamp((close_position - 0.5) * 2.0)  # 0.0 at mid, 1.0 at high
    else:
        dir_score = _clamp((0.5 - close_position) * 2.0)  # 1.0 at low, 0.0 at mid

    # Combine: both must be decent
    return body_pct * dir_score


def score_vwap(bars: list[dict[str, Any]], side: str, atr_period: int = 14) -> float:
    """VWAP alignment score.

    Price near VWAP on the correct side = confident trend.
    BUY above VWAP = positive; SELL below VWAP = positive.
    Score decays linearly from 1.0 at VWAP to 0.0 at 2 ATR away.
    """
    if len(bars) < 2:
        return 0.0
    last_close = bars[-1]["close"]

    # Compute VWAP
    cum_pv = 0.0
    cum_vol = 0.0
    for b in bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_pv += tp * b["volume"]
        cum_vol += b["volume"]
    vwap_val = cum_pv / cum_vol if cum_vol > 0 else last_close

    atr_val = _atr(bars, atr_period)[-1] if len(bars) >= atr_period else 0.0
    if atr_val <= 0:
        atr_val = abs(last_close - vwap_val) or 1.0

    distance = (last_close - vwap_val) / atr_val  # signed ATR units

    if side == "BUY":
        # Positive distance = above VWAP = good
        if distance <= 0:
            return 0.0
        return _clamp(1.0 - distance / 2.0)
    else:
        # Negative distance = below VWAP = good
        if distance >= 0:
            return 0.0
        return _clamp(1.0 + distance / 2.0)


def score_ema_trend(bars: list[dict[str, Any]],
                    fast: int = 20, slow: int = 50) -> float:
    """EMA trend alignment score.

    Evaluates slope of both EMAs and separation between them.
    Rising EMAs with positive separation = high score for BUY.
    """
    if len(bars) < slow + 5:
        return 0.0
    closes = [b["close"] for b in bars]
    fast_vals = _ema(closes, fast)
    slow_vals = _ema(closes, slow)
    f = fast_vals[-1]
    s = slow_vals[-1]

    # Slope over last 3 bars (absolute — strength not direction)
    f_slope = abs((fast_vals[-1] - fast_vals[-4]) / fast_vals[-4] * 100) if len(fast_vals) >= 4 else 0.0
    s_slope = abs((slow_vals[-1] - slow_vals[-4]) / slow_vals[-4] * 100) if len(slow_vals) >= 4 else 0.0

    # Separation as % of slow EMA
    sep = abs(f - s) / s if s != 0 else 0.0

    # Score: trending = slope + separation (direction-agnostic)
    slope_score = _clamp((f_slope + s_slope) / 2.0 / 0.5)  # 0.5% slope = 1.0
    sep_score = _clamp(sep / 0.02)  # 2% separation = 1.0

    return slope_score * 0.6 + sep_score * 0.4


def score_range_expansion(bars: list[dict[str, Any]], period: int = 14) -> float:
    """Range expansion vs ATR. 1.5x ATR = 1.0, 0.5x ATR = 0.33."""
    if len(bars) < period + 1:
        return 0.0
    current_range = bars[-1]["high"] - bars[-1]["low"]
    atr_vals = _atr(bars, period)
    atr_val = atr_vals[-1] if atr_vals else 0.0
    if atr_val <= 0:
        return 0.0
    ratio = current_range / atr_val
    return _clamp(ratio / 1.5)


def score_time_window(timestamp_epoch: float | None = None) -> float:
    """Time-window quality based on session phase.

    Returns 0.0 during last 30 minutes of session (end-of-day noise).
    """
    if timestamp_epoch is None:
        return 1.0  # no timestamp = skip filter

    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(timestamp_epoch, tz=timezone.utc)
    # Convert to IST for NSE session
    ist_offset = 5.5 * 3600
    seconds = (dt.timestamp() + ist_offset) % 86400
    hours = seconds / 3600

    # NSE: 9:15-15:30 IST
    # Peak: 9:15-11:15 (hours 9.25-11.25) → 1.0
    # Mid: 11:15-15:00 (hours 11.25-15.0) → 0.5
    # Close: 15:00-15:30 (hours 15.0-15.5) → 0.0
    if hours < 9.25 or hours > 15.5:
        return 0.0  # outside trading hours
    if hours <= 11.25:
        return 1.0  # peak liquidity
    if hours <= 15.0:
        return 0.5  # midday
    return 0.0  # last 30 min


# ── Aggregation ─────────────────────────────────────────────────────────────


def score_breakout(bars: list[dict[str, Any]] | list[Any],
                   signal: dict[str, Any] | Any,
                   config: QualityConfig | None = None,
                   min_quality_override: float | None = None) -> QualityScore:
    """Assess breakout quality across all dimensions.

    Parameters
    ----------
    bars:
        OHLCV bar dicts with keys: open, high, low, close, volume.
        Can also be BarSnapshot objects with .open, .high, .low, .close, .volume.
    signal:
        Dict with keys: side, price. Optionally: symbol, strategy, timeframe.
    config:
        Optional QualityConfig. Defaults used if None.

    Returns
    -------
    QualityScore with component scores, weighted total, and accept/reject.
    """
    if config is None:
        config = QualityConfig()

    # Normalize bars to dicts if they're BarSnapshot objects
    raw_bars: list[dict[str, Any]] = []
    for b in bars:
        if hasattr(b, "open"):
            raw_bars.append({
                "open": b.open, "high": b.high, "low": b.low,
                "close": b.close, "volume": b.volume,
            })
        else:
            raw_bars.append(b)

    side = signal.get("side", "BUY")
    if hasattr(side, "value"):
        side = side.value

    last_bar = raw_bars[-1] if raw_bars else {"high": 0, "low": 0, "open": 0, "close": 0, "volume": 0}

    rvol = score_rvol(raw_bars, config.rvol_period)
    candle = score_candle_strength(last_bar, side)
    vwap = score_vwap(raw_bars, side, config.atr_period)
    ema = score_ema_trend(raw_bars, config.ema_fast, config.ema_slow)
    rng = score_range_expansion(raw_bars, config.atr_period)
    time_q = 0.0
    if raw_bars and config.enable_time_window:
        time_q = score_time_window(getattr(raw_bars[-1], "timestamp", None))

    total = (
        rvol * config.weight_rvol
        + candle * config.weight_candle
        + vwap * config.weight_vwap
        + ema * config.weight_ema
        + rng * config.weight_range
        + time_q * config.weight_time
    )

    threshold = min_quality_override if min_quality_override is not None else config.min_quality
    accepted = total >= threshold

    reasons = []
    if rvol < 0.3:
        reasons.append(f"rvol={rvol:.2f}")
    if candle < 0.3:
        reasons.append(f"candle={candle:.2f}")
    if vwap < 0.3:
        reasons.append(f"vwap={vwap:.2f}")
    if ema < 0.3:
        reasons.append(f"ema={ema:.2f}")
    if rng < 0.3:
        reasons.append(f"range={rng:.2f}")
    if time_q < 0.3:
        reasons.append(f"time={time_q:.2f}")
    reason = "; ".join(reasons) if reasons else "all_good"

    return QualityScore(
        rvol=rvol, candle_strength=candle, vwap_alignment=vwap,
        ema_trend=ema, range_expansion=rng, time_quality=time_q,
        total=total, accepted=accepted, reason=reason,
    )