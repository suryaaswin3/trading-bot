"""Deterministic market regime detection — stateless, pure functions.

Classifies market conditions into TREND, RANGE, VOLATILE, or DEAD regimes
using EMA separation, VWAP slope, ATR expansion, and range compression.

Usage::

    rs = detect_regime(bars)
    if not rs.breakout_allowed:
        logger.info("Regime reject {} {}: {}", symbol, strategy_name, rs.regime)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class RegimeConfig:
    """Tunable thresholds for regime detection."""

    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    atr_avg_period: int = 20

    # EMA separation thresholds (as fraction of price)
    ema_sep_trend: float = 0.008   # 0.8% separation → trending
    ema_sep_dead: float = 0.002    # 0.2% separation → dead

    # VWAP slope threshold (per-bar, as fraction of price)
    vwap_slope_trend: float = 0.0003

    # ATR expansion/compression (ratio to avg ATR)
    atr_volatile: float = 1.5      # 1.5x avg ATR → volatile
    atr_trend_cap: float = 1.8     # above this → volatile overrides trend
    atr_dead: float = 0.65         # 0.65x avg ATR → compressed

    # Range ratio (current bar range / avg range over lookback)
    range_volatile: float = 1.8
    range_dead: float = 0.5

    # Candle overlap threshold (fraction of body overlapped by prior candle)
    range_overlap: float = 0.6     # 60%+ average overlap → ranging

    # Minimum confidence to return a non-DEAD regime
    min_confidence: float = 0.3


# ── Result ──────────────────────────────────────────────────────────────────


@dataclass
class RegimeState:
    """Result of market regime detection."""

    regime: str                           # TREND | RANGE | VOLATILE | DEAD
    confidence: float                     # 0.0–1.0
    reasons: list[str] = field(default_factory=list)
    breakout_allowed: bool = True         # TREND/VOLATILE → True, RANGE/DEAD → False
    metrics: dict[str, float] = field(default_factory=dict)


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


def _sma(values: list[float], period: int) -> list[float]:
    """Simple moving average."""
    if not values or period <= 0:
        return []
    result: list[float] = []
    for i in range(len(values)):
        if i < period:
            window = values[: i + 1]
            result.append(sum(window) / len(window))
        else:
            result.append(sum(values[i - period + 1 : i + 1]) / period)
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


def _normalize_bars(bars: list[Any]) -> list[dict[str, Any]]:
    """Normalize BarSnapshot objects or dicts to dicts."""
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


# ── Detection Dimensions ────────────────────────────────────────────────────


def _detect_ema_separation(bars: list[dict[str, Any]],
                           config: RegimeConfig) -> dict[str, float]:
    """EMA20/50 separation as fraction of price.

    Returns separation magnitude and direction (1 = bullish, -1 = bearish).
    """
    if len(bars) < config.ema_slow + 3:
        return {"sep": 0.0, "direction": 0.0}

    closes = [b["close"] for b in bars]
    fast = _ema(closes, config.ema_fast)
    slow = _ema(closes, config.ema_slow)

    if slow[-1] == 0:
        return {"sep": 0.0, "direction": 0.0}

    sep = abs(fast[-1] - slow[-1]) / slow[-1]
    direction = 1.0 if fast[-1] > slow[-1] else (-1.0 if fast[-1] < slow[-1] else 0.0)
    return {"sep": sep, "direction": direction}


def _detect_vwap_slope(bars: list[dict[str, Any]],
                       lookback: int = 5) -> float:
    """VWAP slope over recent bars as fraction of price per bar.

    Computes VWAP for each of the last N bars, then fits a linear slope.
    """
    if len(bars) < lookback + 1:
        return 0.0

    vwaps: list[float] = []
    for i in range(len(bars) - lookback, len(bars)):
        segment = bars[: i + 1]
        cum_pv = 0.0
        cum_vol = 0.0
        for b in segment:
            tp = (b["high"] + b["low"] + b["close"]) / 3.0
            cum_pv += tp * b["volume"]
            cum_vol += b["volume"]
        vwap = cum_pv / cum_vol if cum_vol > 0 else segment[-1]["close"]
        vwaps.append(vwap)

    # Simple linear slope: (last - first) / lookback / first
    if vwaps[0] == 0:
        return 0.0
    return (vwaps[-1] - vwaps[0]) / lookback / abs(vwaps[0])


def _detect_atr_ratio(bars: list[dict[str, Any]],
                      config: RegimeConfig) -> float:
    """Current ATR relative to its own average (expansion/compression)."""
    if len(bars) < config.atr_period + config.atr_avg_period:
        return 1.0  # default neutral

    atr_vals = _atr(bars, config.atr_period)
    current_atr = atr_vals[-1]
    avg_atr = _sma(atr_vals, config.atr_avg_period)

    if len(avg_atr) == 0 or avg_atr[-1] <= 0:
        return 1.0

    return current_atr / avg_atr[-1]


def _detect_range_ratio(bars: list[dict[str, Any]],
                        config: RegimeConfig) -> float:
    """Last bar range vs average range over lookback."""
    if len(bars) < config.atr_period + 1:
        return 1.0

    current_range = bars[-1]["high"] - bars[-1]["low"]
    avg_range = sum(b["high"] - b["low"] for b in bars[-(config.atr_period + 1):-1]) / config.atr_period

    if avg_range <= 0:
        return 1.0
    return current_range / avg_range


def _detect_candle_overlap(bars: list[dict[str, Any]],
                           lookback: int = 5) -> float:
    """Average candle body overlap as fraction of body size.

    High overlap (>0.6) indicates tight range / compression.
    Low overlap (<0.3) indicates directional expansion.
    """
    if len(bars) < lookback + 1:
        return 0.5  # default neutral

    overlaps: list[float] = []
    for i in range(len(bars) - lookback, len(bars)):
        prev = bars[i - 1]
        curr = bars[i]

        prev_high = prev["high"]
        prev_low = prev["low"]
        curr_body_high = max(curr["open"], curr["close"])
        curr_body_low = min(curr["open"], curr["close"])

        body = curr_body_high - curr_body_low
        if body <= 0:
            continue

        # How much of current body is inside prior bar's full range?
        overlap_top = min(curr_body_high, prev_high)
        overlap_bottom = max(curr_body_low, prev_low)
        overlap_val = max(0.0, overlap_top - overlap_bottom)
        overlaps.append(overlap_val / body)

    return sum(overlaps) / len(overlaps) if overlaps else 0.5


# ── Aggregation ─────────────────────────────────────────────────────────────


def detect_regime(bars: list[Any],
                  config: RegimeConfig | None = None,
                  allowed_regimes_override: tuple[str, ...] | None = None) -> RegimeState:
    """Classify market regime based on bar data.

    Parameters
    ----------
    bars:
        OHLCV bar dicts or BarSnapshot objects with keys: open, high, low,
        close, volume.
    config:
        Optional RegimeConfig. Defaults used if None.
    allowed_regimes_override:
        Optional tuple of regime names allowed for breakout (e.g.,
        ``("TREND", "VOLATILE")``). Overrides the default TREND/VOLATILE-only
        logic when set.

    Returns
    -------
    RegimeState with regime, confidence, reasons, and computed metrics.
    """
    if config is None:
        config = RegimeConfig()

    raw_bars = _normalize_bars(bars)
    if len(raw_bars) < 30:
        return RegimeState(
            regime="DEAD",
            confidence=1.0,
            reasons=["insufficient_data"],
            breakout_allowed=False,
            metrics={"bar_count": len(raw_bars)},
        )

    # Compute all dimension metrics
    ema_info = _detect_ema_separation(raw_bars, config)
    vwap_slope = _detect_vwap_slope(raw_bars)
    atr_ratio = _detect_atr_ratio(raw_bars, config)
    range_ratio = _detect_range_ratio(raw_bars, config)
    overlap = _detect_candle_overlap(raw_bars)

    sep = ema_info["sep"]
    direction = ema_info["direction"]

    metrics = {
        "ema_separation": round(sep, 6),
        "ema_direction": direction,
        "vwap_slope": round(vwap_slope, 6),
        "atr_ratio": round(atr_ratio, 4),
        "range_ratio": round(range_ratio, 4),
        "candle_overlap": round(overlap, 4),
    }

    # ── Classification decision tree ────────────────────────────────────

    reasons: list[str] = []

    # DEAD signals
    if atr_ratio < config.atr_dead:
        reasons.append("atr_compressed")
    if sep < config.ema_sep_dead:
        reasons.append("ema_no_separation")
    if range_ratio < config.range_dead:
        reasons.append("narrow_range")
    if overlap > config.range_overlap:
        reasons.append("high_overlap")

    # Accumulate regime scores
    scores: dict[str, float] = {"TREND": 0.0, "RANGE": 0.0, "VOLATILE": 0.0, "DEAD": 0.0}

    # DEAD scoring
    dead_count = 0
    if atr_ratio < config.atr_dead:
        scores["DEAD"] += 0.3
        dead_count += 1
    if sep < config.ema_sep_dead:
        scores["DEAD"] += 0.3
        dead_count += 1
    if range_ratio < config.range_dead:
        scores["DEAD"] += 0.2
        dead_count += 1
    if overlap > config.range_overlap:
        scores["DEAD"] += 0.2
        dead_count += 1

    # RANGE scoring
    if sep < config.ema_sep_trend:
        scores["RANGE"] += 0.3
    if abs(vwap_slope) < config.vwap_slope_trend:
        scores["RANGE"] += 0.2
    if overlap > config.range_overlap:
        scores["RANGE"] += 0.2

    # TREND scoring
    if sep >= config.ema_sep_trend:
        scores["TREND"] += 0.35
    if abs(vwap_slope) >= config.vwap_slope_trend:
        scores["TREND"] += 0.3
    if atr_ratio >= config.atr_volatile * 0.8 and sep >= config.ema_sep_trend * 0.7:
        scores["TREND"] += 0.15

    # VOLATILE scoring
    if atr_ratio >= config.atr_volatile:
        scores["VOLATILE"] += 0.35
    if range_ratio >= config.range_volatile:
        scores["VOLATILE"] += 0.3

    # ── Final classification ────────────────────────────────────────────

    regime_reasons: list[str] = []

    sorted_scores = sorted(scores.values(), reverse=True)

    if sorted_scores[0] > 0 and (sorted_scores[0] + sorted_scores[1]) > 0:
        confidence = sorted_scores[0] / (sorted_scores[0] + sorted_scores[1])
    else:
        confidence = 0.0
    confidence = _clamp(confidence)

    if dead_count >= 3 and scores["DEAD"] >= 0.5:
        regime = "DEAD"
    elif atr_ratio >= config.atr_trend_cap and scores["VOLATILE"] >= 0.35:
        # Extreme volatility overrides trend — the spike is noise, not direction
        regime = "VOLATILE"
        if "high_volatility_override" not in [r for r in reasons]:
            regime_reasons.append("high_volatility_override")
    elif scores["TREND"] >= scores["VOLATILE"] and scores["TREND"] >= 0.35:
        regime = "TREND"
    elif scores["VOLATILE"] >= 0.35:
        regime = "VOLATILE"
    elif scores["RANGE"] >= 0.3:
        regime = "RANGE"
    else:
        # Fallback: weakest signal wins
        if atr_ratio >= config.atr_volatile * 0.9:
            regime = "VOLATILE"
        else:
            regime = "RANGE"

    # Confidence floor — if too low, fall back to RANGE
    if confidence < config.min_confidence and regime != "DEAD":
        regime = "RANGE"
        confidence = 0.3

    breakout_allowed = regime in (allowed_regimes_override if allowed_regimes_override is not None else ("TREND", "VOLATILE"))

    # Build unique reason list for the regime
    for r in reasons:
        if r not in regime_reasons:
            regime_reasons.append(r)

    return RegimeState(
        regime=regime,
        confidence=confidence,
        reasons=regime_reasons,
        breakout_allowed=breakout_allowed,
        metrics=metrics,
    )