"""Execution timing refinement — stateless, pure functions.

Avoids poor entries by detecting:
- Oversized candles (exhaustion / blow-off)
- Exhausted breakouts (momentum fading)
- Late momentum entries

Prefers:
- Breakout retest (price returning to breakout level after initial pop)
- Pullback entries (price pulling back to EMA/VWAP in a trend)
- Micro consolidation entries (tight range forming after a breakout)

Usage::

    timing = check_entry_timing(bars, signal)
    if not timing.allowed:
        logger.info("Timing reject: {}", timing.reason)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class TimingConfig:
    """Tunable thresholds for entry timing refinement."""

    # Oversized candle detection
    max_candle_atr_multiple: float = 2.5  # Reject if last candle > 2.5x ATR
    max_candle_volume_multiple: float = 3.0  # Reject if last vol > 3x avg

    # Exhausted breakout
    breakout_lookback: int = 5  # bars to check for momentum fade
    exhaustion_slope_threshold: float = 0.3  # slope decay ratio → exhausted

    # Retest detection
    retest_max_bars: int = 5  # max bars since breakout to check retest
    retest_max_pullback_pct: float = 0.5  # pullback up to 50% of breakout range
    retest_min_pullback_pct: float = 0.2  # must pull back at least 20%

    # Pullback entry
    pullback_max_deviation_pct: float = 0.3  # max deviation from EMA as % of ATR
    pullback_min_trend_atr: float = 0.5  # trend must have > 0.5 ATR momentum

    # Micro consolidation
    consolidation_max_range_pct: float = 0.3  # recent bars range as % of breakout bar
    consolidation_min_bars: int = 2  # min consecutive tight bars
    consolidation_max_bars: int = 5  # max bars before consolidation is stagnation


# ── Result ──────────────────────────────────────────────────────────────────


@dataclass
class TimingResult:
    """Result of entry timing assessment."""

    allowed: bool
    method: str              # "immediate" | "retest" | "pullback" | "consolidation" | ""
    reason: str
    preferred_entry: str = "market"  # "market" | "limit" | "wait"
    metrics: dict[str, float] = field(default_factory=dict)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _sma(values: list[float], period: int) -> float:
    if not values or period <= 0:
        return 0.0
    return sum(values[-period:]) / min(period, len(values))


def _compute_atr(bars: list[dict[str, Any]], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
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
    smoothed: list[float] = []
    for i in range(len(tr_values)):
        if i < period:
            window = tr_values[: i + 1]
            smoothed.append(sum(window) / len(window))
        else:
            smoothed.append((smoothed[i - 1] * (period - 1) + tr_values[i]) / period)
    return smoothed[-1]


def _ema(values: list[float], period: int) -> list[float]:
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


def _normalize_bars(bars: list[Any]) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for b in bars:
        if hasattr(b, "open"):
            raw.append({
                "open": b.open, "high": b.high, "low": b.low,
                "close": b.close, "volume": b.volume,
            })
        else:
            raw.append(b)
    return raw


# ── Checks ──────────────────────────────────────────────────────────────────


def check_oversized_candle(
    bars: list[dict[str, Any]],
    atr_value: float,
    config: TimingConfig,
) -> TimingResult | None:
    """Reject if last candle is oversized (blow-off top / capitulation).

    Returns None if ok, TimingResult with allowed=False if rejected.
    """
    if len(bars) < 2:
        return None

    last = bars[-1]
    last_range = last["high"] - last["low"]
    last_volume = last["volume"]

    # Range check vs ATR
    if atr_value > 0 and last_range > config.max_candle_atr_multiple * atr_value:
        return TimingResult(
            allowed=False,
            method="",
            reason=f"oversized_candle (range={last_range:.2f} > {config.max_candle_atr_multiple:.0f}ATR={config.max_candle_atr_multiple * atr_value:.2f})",
            preferred_entry="wait",
            metrics={"last_range_atr": round(last_range / atr_value, 2) if atr_value > 0 else 0.0},
        )

    # Volume spike check
    avg_vol = sum(b["volume"] for b in bars[-10: -1]) / 9 if len(bars) >= 10 else sum(b["volume"] for b in bars[:-1]) / max(len(bars) - 1, 1)
    if avg_vol > 0 and last_volume > config.max_candle_volume_multiple * avg_vol:
        return TimingResult(
            allowed=False,
            method="",
            reason=f"volume_spike (vol={last_volume:.0f} > {config.max_candle_volume_multiple:.0f}x avg={avg_vol:.0f})",
            preferred_entry="wait",
            metrics={"vol_ratio": round(last_volume / avg_vol, 2)},
        )

    return None


def check_exhausted_breakout(
    bars: list[dict[str, Any]],
    atr_value: float,
    config: TimingConfig,
) -> TimingResult | None:
    """Detect momentum fade over recent bars.

    If recent bar ranges are shrinking after an initial expansion,
    momentum is fading — wait for a reset.
    """
    if len(bars) < config.breakout_lookback + 3:
        return None

    recent = bars[-config.breakout_lookback:]
    ranges = [b["high"] - b["low"] for b in recent]

    # Check if ranges are shrinking (exhaustion pattern)
    initial_avg = sum(ranges[:2]) / 2 if len(ranges) >= 2 else ranges[0]
    final_avg = sum(ranges[-2:]) / 2 if len(ranges) >= 2 else ranges[-1]

    if initial_avg <= 0:
        return None

    slope_ratio = final_avg / initial_avg
    if slope_ratio < config.exhaustion_slope_threshold:
        return TimingResult(
            allowed=False,
            method="",
            reason=f"exhausted_breakout (range_shrunk {slope_ratio:.2f} < {config.exhaustion_slope_threshold:.2f})",
            preferred_entry="wait",
            metrics={"slope_ratio": round(slope_ratio, 4)},
        )

    return None


def check_retest(
    bars: list[dict[str, Any]],
    side: str,
    atr_value: float,
    config: TimingConfig,
) -> TimingResult | None:
    """Check if price is retesting the breakout level after an initial pop.

    Returns TimingResult with allowed=True if retest detected.
    """
    if len(bars) < config.retest_max_bars + 2:
        return None

    recent = bars[-config.retest_max_bars:]

    # Find the breakout bar (largest range bar in the window)
    breakout_idx = max(range(len(recent)), key=lambda i: recent[i]["high"] - recent[i]["low"])
    breakout_bar = recent[breakout_idx]
    breakout_range = breakout_bar["high"] - breakout_bar["low"]

    if breakout_range <= 0:
        return None

    # Current bar is pulling back to the breakout level
    current = recent[-1]
    if side == "BUY":
        # Retest: price pulled back from high, now near breakout bar's close or midpoint
        pullback_from_high = (max(b["high"] for b in recent[breakout_idx:]) - current["close"]) / breakout_range
        if config.retest_min_pullback_pct <= pullback_from_high <= config.retest_max_pullback_pct:
            return TimingResult(
                allowed=True,
                method="retest",
                reason=f"breakout_retest (pullback={pullback_from_high:.2f} of breakout range)",
                preferred_entry="limit",
                metrics={"pullback_pct": round(pullback_from_high, 4)},
            )
    else:
        pullback_from_low = (current["close"] - min(b["low"] for b in recent[breakout_idx:])) / breakout_range
        if config.retest_min_pullback_pct <= pullback_from_low <= config.retest_max_pullback_pct:
            return TimingResult(
                allowed=True,
                method="retest",
                reason=f"breakout_retest (pullback={pullback_from_low:.2f} of breakout range)",
                preferred_entry="limit",
                metrics={"pullback_pct": round(pullback_from_low, 4)},
            )

    return None


def check_pullback(
    bars: list[dict[str, Any]],
    side: str,
    atr_value: float,
    config: TimingConfig,
) -> TimingResult | None:
    """Check if price is pulling back to EMA/VWAP in a trend.

    Entry target: pullback to fast EMA with trend intact.
    """
    if len(bars) < 25:
        return None

    closes = [b["close"] for b in bars]
    fast_ema = _ema(closes, 20)

    if not fast_ema or fast_ema[-1] <= 0:
        return None

    last_close = bars[-1]["close"]
    ema_val = fast_ema[-1]

    # How far is price from EMA (in ATR units)?
    deviation = (last_close - ema_val) / atr_value if atr_value > 0 else 0.0

    if side == "BUY":
        # Price should be near or slightly below EMA in an uptrend
        upward_trend = fast_ema[-1] > fast_ema[-5] if len(fast_ema) >= 5 else True
        if not upward_trend:
            return None
        if -config.pullback_max_deviation_pct <= deviation <= config.pullback_max_deviation_pct * 0.5:
            return TimingResult(
                allowed=True,
                method="pullback",
                reason=f"ema_pullback (deviation={deviation:.2f} ATR)",
                preferred_entry="limit",
                metrics={"ema_deviation_atr": round(deviation, 4)},
            )
    else:
        downward_trend = fast_ema[-1] < fast_ema[-5] if len(fast_ema) >= 5 else True
        if not downward_trend:
            return None
        if -config.pullback_max_deviation_pct * 0.5 <= deviation <= config.pullback_max_deviation_pct:
            return TimingResult(
                allowed=True,
                method="pullback",
                reason=f"ema_pullback (deviation={deviation:.2f} ATR)",
                preferred_entry="limit",
                metrics={"ema_deviation_atr": round(deviation, 4)},
            )

    return None


def check_micro_consolidation(
    bars: list[dict[str, Any]],
    atr_value: float,
    config: TimingConfig,
) -> TimingResult | None:
    """Detect micro consolidation after a breakout.

    Tight range forming = spring-loaded for next move.
    """
    if len(bars) < config.consolidation_max_bars + 2:
        return None

    recent = bars[-config.consolidation_max_bars:]
    ranges = [b["high"] - b["low"] for b in recent]
    breakout_range = max(ranges[:-1]) if len(ranges) > 1 else ranges[0]

    if breakout_range <= 0:
        return None

    # Current and recent bars show tightness
    tight_count = sum(1 for r in ranges if r / atr_value < config.consolidation_max_range_pct)
    if tight_count >= config.consolidation_min_bars:
        return TimingResult(
            allowed=True,
            method="consolidation",
            reason=f"micro_consolidation ({tight_count}/{len(recent)} bars tight)",
            preferred_entry="market",
            metrics={"tight_bars": float(tight_count), "avg_range_atr": round(sum(ranges) / len(ranges) / atr_value, 4) if atr_value > 0 else 0.0},
        )

    return None


# ── Aggregation ─────────────────────────────────────────────────────────────


def check_entry_timing(
    bars: list[Any],
    side: str,
    config: TimingConfig | None = None,
) -> TimingResult:
    """Assess entry timing quality.

    Parameters
    ----------
    bars:
        OHLCV bar dicts or BarSnapshots.
    side:
        ``"BUY"`` or ``"SELL"``.
    config:
        Optional TimingConfig. Defaults used if None.

    Returns
    -------
    TimingResult with allowed status, preferred method, and reason.
    """
    if config is None:
        config = TimingConfig()

    raw_bars = _normalize_bars(bars)
    if len(raw_bars) < 15:
        return TimingResult(allowed=True, method="immediate", reason="insufficient_data")

    atr_value = _compute_atr(raw_bars)
    if atr_value <= 0:
        return TimingResult(allowed=True, method="immediate", reason="no_atr")

    # ── Hard blocks (return disallowed) ──────────────────────────────────

    oversized = check_oversized_candle(raw_bars, atr_value, config)
    if oversized is not None:
        return oversized

    exhausted = check_exhausted_breakout(raw_bars, atr_value, config)
    if exhausted is not None:
        return exhausted

    # ── Preferred timing methods (return allowed with method) ────────────

    retest = check_retest(raw_bars, side, atr_value, config)
    if retest is not None:
        return retest

    pullback = check_pullback(raw_bars, side, atr_value, config)
    if pullback is not None:
        return pullback

    consolidation = check_micro_consolidation(raw_bars, atr_value, config)
    if consolidation is not None:
        return consolidation

    # ── Fallback: immediate entry allowed ────────────────────────────────
    return TimingResult(
        allowed=True,
        method="immediate",
        reason="no_preferred_timing (default entry)",
        metrics={},
    )