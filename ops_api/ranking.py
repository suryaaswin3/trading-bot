"""Dynamic symbol ranking — stateless, pure functions.

Ranks symbols by multi-dimensional scores and returns only the top-N
for scanner attention. Dimensions: RVOL, ATR expansion, trend strength,
breakout quality proxy, liquidity, directional efficiency.

Usage::

    ranks = rank_symbols(bars_by_symbol)
    top3 = ranks[:3]  # scanner only evaluates these
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class RankingConfig:
    """Tunable thresholds and weights for symbol ranking."""

    top_n: int = 5
    min_score: float = 0.20

    rvol_period: int = 20
    atr_period: int = 14
    ema_fast: int = 20
    ema_slow: int = 50
    trend_lookback: int = 5

    # Weights (autonormalised to sum to 1.0)
    weight_rvol: float = 0.25
    weight_atr_expansion: float = 0.15
    weight_trend_strength: float = 0.20
    weight_breakout_quality: float = 0.15
    weight_liquidity: float = 0.10
    weight_directional_efficiency: float = 0.15


# ── Result ──────────────────────────────────────────────────────────────────


@dataclass
class SymbolRank:
    """Score breakdown for one symbol."""

    symbol: str
    rvol: float
    atr_expansion: float
    trend_strength: float
    breakout_quality: float
    liquidity: float
    directional_efficiency: float
    total: float


# ── Helpers ─────────────────────────────────────────────────────────────────


def _sma(values: list[float], period: int) -> list[float]:
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


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ── Scoring Dimensions ──────────────────────────────────────────────────────


def score_rvol(bars: list[dict[str, Any]], period: int = 20) -> float:
    """Relative volume vs average.

    3x+ average = 1.0, 1x = 0.0, linear in between.
    """
    if len(bars) < period + 1:
        return 0.0
    volumes = [b["volume"] for b in bars]
    current = volumes[-1]
    avg = sum(volumes[-(period + 1) : -1]) / period
    if avg <= 0:
        return 0.0
    return _clamp((current / avg - 1.0) / 2.0)


def score_atr_expansion(bars: list[dict[str, Any]], period: int = 14) -> float:
    """Current ATR vs average ATR over lookback.

    1.5x average = 1.0, 0.5x = 0.0, linear.
    """
    if len(bars) < period + period:
        return 0.0

    # Compute ATR
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

    atr_current = sum(tr_values[-period:]) / period
    atr_avg = sum(tr_values[-(period + period) : -period]) / period if len(tr_values) >= 2 * period else atr_current

    if atr_avg <= 0:
        return 0.0
    ratio = atr_current / atr_avg
    return _clamp((ratio - 0.5) / 1.0)


def score_trend_strength(
    bars: list[dict[str, Any]],
    fast: int = 20,
    slow: int = 50,
    lookback: int = 5,
) -> float:
    """EMA slope + separation as trend strength.

    Steady directional slope + wide separation = strong trend.
    """
    if len(bars) < slow + lookback:
        return 0.0

    closes = [b["close"] for b in bars]

    # Fast EMA slope
    multiplier_f = 2.0 / (fast + 1)
    fast_vals: list[float] = []
    for i, c in enumerate(closes):
        if i < fast:
            fast_vals.append(sum(closes[: i + 1]) / (i + 1))
        else:
            fast_vals.append((c - fast_vals[i - 1]) * multiplier_f + fast_vals[i - 1])

    # Slow EMA slope
    multiplier_s = 2.0 / (slow + 1)
    slow_vals: list[float] = []
    for i, c in enumerate(closes):
        if i < slow:
            slow_vals.append(sum(closes[: i + 1]) / (i + 1))
        else:
            slow_vals.append((c - slow_vals[i - 1]) * multiplier_s + slow_vals[i - 1])

    f_slope = (fast_vals[-1] - fast_vals[-1 - lookback]) / fast_vals[-1 - lookback] if fast_vals[-1 - lookback] != 0 else 0.0
    s_slope = (slow_vals[-1] - slow_vals[-1 - lookback]) / slow_vals[-1 - lookback] if slow_vals[-1 - lookback] != 0 else 0.0

    sep = abs(fast_vals[-1] - slow_vals[-1]) / slow_vals[-1] if slow_vals[-1] != 0 else 0.0

    slope_score = _clamp(abs(f_slope + s_slope) / 0.02)  # 2% combined slope = 1.0
    sep_score = _clamp(sep / 0.03)  # 3% separation = 1.0

    return slope_score * 0.5 + sep_score * 0.5


def score_breakout_quality(bars: list[dict[str, Any]]) -> float:
    """Breakout quality proxy: recent candle conviction.

    Checks the last 3 bars for expanding range + strong close.
    A proxy used when the signal is not yet known (direction-agnostic).
    """
    if len(bars) < 4:
        return 0.0

    recent = bars[-3:]
    ranges = [b["high"] - b["low"] for b in recent]
    if ranges[0] <= 0:
        return 0.0

    expanding = ranges[-1] > ranges[0]
    range_growth = _clamp((ranges[-1] / ranges[0] - 1.0) / 1.0) if ranges[0] > 0 else 0.0

    # Close in outer third of range = conviction (direction-agnostic)
    outer_third_count = 0
    for b in recent:
        r = b["high"] - b["low"]
        if r <= 0:
            continue
        close_pos = (b["close"] - b["low"]) / r
        if close_pos > 0.67 or close_pos < 0.33:
            outer_third_count += 1

    conviction = outer_third_count / 3.0

    score = (range_growth * 0.6) + (conviction * 0.4)
    return _clamp(score)


def score_liquidity(bars: list[dict[str, Any]]) -> float:
    """Absolute volume-based liquidity score.

    Log-normalised to [0, 1]. Higher raw volume = more liquid.
    """
    if len(bars) < 5:
        return 0.0

    avg_vol = sum(b["volume"] for b in bars[-5:]) / 5.0
    if avg_vol <= 0:
        return 0.0

    return _clamp(avg_vol / 500000)  # 500K avg volume = 1.0


def score_directional_efficiency(bars: list[dict[str, Any]], lookback: int = 5) -> float:
    """How efficiently price moves in one direction.

    Net move / total bar range over lookback.
    1.0 = perfectly directional. 0.0 = pure chop.
    """
    if len(bars) < lookback:
        return 0.0

    segment = bars[-lookback:]
    net_move = abs(segment[-1]["close"] - segment[0]["open"])
    total_range = sum(b["high"] - b["low"] for b in segment)

    if total_range <= 0:
        return 0.0
    return _clamp(net_move / total_range)


# ── Aggregation ─────────────────────────────────────────────────────────────


def rank_symbols(
    bars_by_symbol: dict[str, list[Any]],
    config: RankingConfig | None = None,
) -> list[SymbolRank]:
    """Rank all symbols by multi-dimensional score.

    Parameters
    ----------
    bars_by_symbol:
        Mapping of symbol → list of OHLCV bar dicts/BarSnapshots.
    config:
        Optional RankingConfig. Defaults used if None.

    Returns
    -------
    List of SymbolRank, sorted by total descending, filtered by min_score.
    Only symbols with sufficient bars are ranked.
    """
    if config is None:
        config = RankingConfig()

    total_weight = (
        config.weight_rvol
        + config.weight_atr_expansion
        + config.weight_trend_strength
        + config.weight_breakout_quality
        + config.weight_liquidity
        + config.weight_directional_efficiency
    )

    results: list[SymbolRank] = []

    for symbol, raw_bars in bars_by_symbol.items():
        bars: list[dict[str, Any]] = []
        for b in raw_bars:
            if hasattr(b, "open"):
                bars.append({
                    "open": b.open, "high": b.high, "low": b.low,
                    "close": b.close, "volume": b.volume,
                })
            else:
                bars.append(b)

        if len(bars) < config.ema_slow + 5:
            continue

        rvol = score_rvol(bars, config.rvol_period)
        atr = score_atr_expansion(bars, config.atr_period)
        trend = score_trend_strength(bars, config.ema_fast, config.ema_slow, config.trend_lookback)
        bq = score_breakout_quality(bars)
        liq = score_liquidity(bars)
        de = score_directional_efficiency(bars)

        total = (
            rvol * config.weight_rvol
            + atr * config.weight_atr_expansion
            + trend * config.weight_trend_strength
            + bq * config.weight_breakout_quality
            + liq * config.weight_liquidity
            + de * config.weight_directional_efficiency
        ) / total_weight  # normalise so max is 1.0

        if total >= config.min_score:
            results.append(SymbolRank(
                symbol=symbol, rvol=rvol, atr_expansion=atr,
                trend_strength=trend, breakout_quality=bq,
                liquidity=liq, directional_efficiency=de,
                total=total,
            ))

    results.sort(key=lambda r: r.total, reverse=True)
    return results[: config.top_n]