"""Multi-timeframe confirmation for breakout signals — stateless, pure functions.

Confirms lower-timeframe (5m) breakout signals by checking alignment
with higher-timeframe (15m) trend context. Six dimensions: EMA alignment,
VWAP agreement, candle structure, direction agreement, countertrend
rejection, and exhaustion detection.

Usage::

    cs = confirm_signal(ltf_bars, htf_bars, signal)
    if cs.accepted:
        ...  # dispatch to strategy engine
    else:
        logger.info("Confirmation reject {}: {}", symbol, cs.reason)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class ConfirmationConfig:
    """Tunable thresholds for multi-timeframe confirmation."""

    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14

    # Minimum overall alignment to accept
    min_alignment: float = 0.35

    # Component weights (must sum to 1.0)
    weight_ema_alignment: float = 0.30
    weight_vwap_alignment: float = 0.25
    weight_candle_structure: float = 0.20
    weight_direction_agreement: float = 0.25

    # Countertrend: reject when HTF trend is strongly against signal
    htf_countertrend_sep: float = 0.006  # 0.6%+ EMA sep against signal → reject

    # Exhaustion: reject when LTF move is extended beyond HTF mean range
    exhaustion_multiple: float = 2.5     # LTF bar range > HTF avg range * this


# ── Result ──────────────────────────────────────────────────────────────────


@dataclass
class ConfirmationState:
    """Result of multi-timeframe confirmation."""

    accepted: bool                         # True → allow execution
    confidence: float                      # 0.0–1.0
    alignment_score: float                 # weighted component total
    reason: str                            # rejection reason or "all_aligned"
    metrics: dict[str, float] = field(default_factory=dict)


# ── Helpers ─────────────────────────────────────────────────────────────────


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


def _atr(bars: list[dict[str, Any]], period: int) -> list[float]:
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


# ── Confirmation Dimensions ─────────────────────────────────────────────────


def _get_side(signal: dict[str, Any]) -> str:
    """Extract side from signal dict or object."""
    side = signal.get("side", "BUY")
    if hasattr(side, "value"):
        side = side.value
    return side


def _ema_separation(bars: list[dict[str, Any]],
                    fast: int, slow: int) -> dict[str, float]:
    """EMA separation as fraction of price with direction."""
    if len(bars) < slow + 3:
        return {"sep": 0.0, "direction": 0.0, "fast_val": 0.0, "slow_val": 0.0}
    closes = [b["close"] for b in bars]
    fast_vals = _ema(closes, fast)
    slow_vals = _ema(closes, slow)
    if slow_vals[-1] == 0:
        return {"sep": 0.0, "direction": 0.0, "fast_val": fast_vals[-1], "slow_val": slow_vals[-1]}
    sep = abs(fast_vals[-1] - slow_vals[-1]) / slow_vals[-1]
    direction = 1.0 if fast_vals[-1] > slow_vals[-1] else (-1.0 if fast_vals[-1] < slow_vals[-1] else 0.0)
    return {"sep": sep, "direction": direction, "fast_val": fast_vals[-1], "slow_val": slow_vals[-1]}


def _vwap(bars: list[dict[str, Any]]) -> float:
    """Compute VWAP for all bars."""
    cum_pv = 0.0
    cum_vol = 0.0
    for b in bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_pv += tp * b["volume"]
        cum_vol += b["volume"]
    return cum_pv / cum_vol if cum_vol > 0 else bars[-1]["close"]


def _avg_range(bars: list[dict[str, Any]], period: int = 14) -> float:
    """Average bar range over lookback."""
    if len(bars) < period:
        return 0.0
    return sum(b["high"] - b["low"] for b in bars[-period:]) / period


# ── Dimension Scoring ───────────────────────────────────────────────────────


def score_htf_ema_alignment(htf_bars: list[dict[str, Any]],
                            side: str,
                            fast: int = 20, slow: int = 50) -> float:
    """Higher timeframe EMA alignment with signal direction.

    BUY signal + bull EMA alignment → 1.0
    SELL signal + bear EMA alignment → 1.0
    Crossed EMAs against signal → 0.0
    Strength proportional to separation magnitude.
    """
    info = _ema_separation(htf_bars, fast, slow)
    if info["sep"] <= 0:
        return 0.5  # no strong trend on HTF = neutral

    bull = info["direction"] > 0
    buy_signal = side == "BUY"

    if (buy_signal and bull) or (not buy_signal and not bull):
        return _clamp(info["sep"] / 0.015)  # 1.5% separation = 1.0
    return 0.0  # HTF trend opposes signal


def score_vwap_alignment(ltf_bars: list[dict[str, Any]],
                         htf_bars: list[dict[str, Any]],
                         side: str, atr_period: int = 14) -> float:
    """VWAP directional agreement between timeframes.

    Both VWAPs on same side of price = aligned.
    One above, one below = conflicted.
    """
    if len(ltf_bars) < 2 or len(htf_bars) < 2:
        return 0.5

    ltf_last = ltf_bars[-1]["close"]
    htf_last = htf_bars[-1]["close"]
    ltf_vwap = _vwap(ltf_bars)
    htf_vwap = _vwap(htf_bars)

    ltf_above = ltf_last >= ltf_vwap
    htf_above = htf_last >= htf_vwap

    buy_signal = side == "BUY"

    # Desired: price above VWAP for BUY, below for SELL
    ltf_ok = ltf_above if buy_signal else not ltf_above
    htf_ok = htf_above if buy_signal else not htf_above

    if ltf_ok and htf_ok:
        return 1.0  # both aligned
    elif ltf_ok or htf_ok:
        return 0.5  # one aligned
    return 0.0  # both against


def score_candle_structure(htf_bars: list[dict[str, Any]],
                           side: str) -> float:
    """Higher TF candle structure quality.

    Evaluates the last HTF candle: body strength, wick ratio, and
    whether it supports the signal direction.
    """
    if len(htf_bars) < 2:
        return 0.5

    last = htf_bars[-1]
    rng = last["high"] - last["low"]
    if rng <= 0:
        return 0.0

    body = abs(last["close"] - last["open"])
    body_pct = body / rng

    # Wick ratio: small wicks on the breakout side = strong
    upper_wick = last["high"] - max(last["open"], last["close"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    wick_ratio = (upper_wick + lower_wick) / rng if rng > 0 else 0.5

    close_position = (last["close"] - last["low"]) / rng
    buy_signal = side == "BUY"

    # Direction support: close in top half for BUY, bottom half for SELL
    if buy_signal:
        dir_score = _clamp((close_position - 0.4) * 3.0)
    else:
        dir_score = _clamp((0.6 - close_position) * 3.0)

    # Body score: larger body = more conviction
    body_score = _clamp(body_pct * 2.0)

    # Wick penalty: large wicks against direction reduce quality
    wick_penalty = 1.0 - wick_ratio * 0.5

    return dir_score * 0.5 + body_score * 0.3 + wick_penalty * 0.2


def score_direction_agreement(ltf_bars: list[dict[str, Any]],
                              htf_bars: list[dict[str, Any]],
                              side: str) -> float:
    """Direction agreement between timeframes.

    LTF price slope == HTF price slope = agreed direction.
    Opposing slopes = conflicted.
    """
    if len(ltf_bars) < 5 or len(htf_bars) < 5:
        return 0.5

    # Slope over last 5 bars
    ltf_slope = (ltf_bars[-1]["close"] - ltf_bars[-5]["close"]) / ltf_bars[-5]["close"]
    htf_slope = (htf_bars[-1]["close"] - htf_bars[-5]["close"]) / htf_bars[-5]["close"]

    buy_signal = side == "BUY"

    # LTF should agree with signal
    ltf_agrees = (ltf_slope > 0) if buy_signal else (ltf_slope < 0)
    if not ltf_agrees:
        return 0.0  # LTF itself doesn't agree with signal

    # Both in same direction
    both_up = ltf_slope > 0 and htf_slope > 0
    both_down = ltf_slope < 0 and htf_slope < 0

    if both_up or both_down:
        return 1.0
    return 0.3  # HTF neutral or mildly conflicting


def check_countertrend(htf_bars: list[dict[str, Any]],
                       side: str,
                       config: ConfirmationConfig) -> float:
    """Countertrend penalty. Returns 0.0 if countertrend, 1.0 if aligned.

    BUY signal when HTF EMAs are bearish with strong separation → reject.
    SELL signal when HTF EMAs are bullish with strong separation → reject.
    """
    info = _ema_separation(htf_bars, config.ema_fast, config.ema_slow)
    if info["sep"] < config.htf_countertrend_sep:
        return 1.0  # not strongly trending against

    bull = info["direction"] > 0
    buy_signal = side == "BUY"

    if (buy_signal and not bull) or (not buy_signal and bull):
        return 0.0  # countertrend: strong HTF trend opposes signal
    return 1.0


def check_exhaustion(ltf_bars: list[dict[str, Any]],
                     htf_bars: list[dict[str, Any]],
                     config: ConfirmationConfig) -> float:
    """Exhaustion check. Returns 0.0 if exhausted, 1.0 if healthy.

    LTF bar range >> HTF avg range → potential exhaustion.
    LTF body small relative to range after large move → fading momentum.
    """
    if len(ltf_bars) < 2 or len(htf_bars) < config.atr_period:
        return 1.0

    htf_avg_rng = _avg_range(htf_bars, config.atr_period)
    if htf_avg_rng <= 0:
        return 1.0

    ltf_last = ltf_bars[-1]
    ltf_range = ltf_last["high"] - ltf_last["low"]
    ltf_body = abs(ltf_last["close"] - ltf_last["open"])

    # Exhaustion: LTF range >> HTF normal range
    range_ratio = ltf_range / htf_avg_rng
    if range_ratio > config.exhaustion_multiple:
        # Also check if body is small relative to range (blow-off top/bottom)
        if ltf_range > 0 and ltf_body / ltf_range < 0.3:
            return 0.0  # wide range, tiny body = exhaustion
        return 0.3  # wide range but reasonable body = caution

    return 1.0


# ── Aggregation ─────────────────────────────────────────────────────────────


def confirm_signal(
    lower_tf_bars: list[Any],
    higher_tf_bars: list[Any],
    signal: dict[str, Any] | Any,
    config: ConfirmationConfig | None = None,
) -> ConfirmationState:
    """Assess multi-timeframe confirmation for a breakout signal.

    Parameters
    ----------
    lower_tf_bars:
        Primary timeframe OHLCV bars (e.g., 5m).
    higher_tf_bars:
        Confirmation timeframe OHLCV bars (e.g., 15m).
    signal:
        Dict with key ``side``. Optionally: price, symbol, strategy.
    config:
        Optional ConfirmationConfig. Defaults used if None.

    Returns
    -------
    ConfirmationState with acceptance, confidence, and metrics.
    """
    if config is None:
        config = ConfirmationConfig()

    ltf_bars = _normalize_bars(lower_tf_bars)
    htf_bars = _normalize_bars(higher_tf_bars)

    if len(ltf_bars) < 30 or len(htf_bars) < 20:
        return ConfirmationState(
            accepted=False,
            confidence=0.0,
            alignment_score=0.0,
            reason="insufficient_data",
            metrics={"ltf_bar_count": len(ltf_bars), "htf_bar_count": len(htf_bars)},
        )

    side = _get_side(signal)

    # Hard gates: countertrend and exhaustion
    ct_score = check_countertrend(htf_bars, side, config)
    ex_score = check_exhaustion(ltf_bars, htf_bars, config)

    reasons: list[str] = []
    if ct_score < 0.5:
        reasons.append("countertrend")
    if ex_score < 0.5:
        reasons.append("exhaustion")

    # Compute component scores
    ema_score = score_htf_ema_alignment(htf_bars, side, config.ema_fast, config.ema_slow)
    vwap_score = score_vwap_alignment(ltf_bars, htf_bars, side, config.atr_period)
    candle_score = score_candle_structure(htf_bars, side)
    dir_score = score_direction_agreement(ltf_bars, htf_bars, side)

    # Weighted alignment (conditional on hard gates passing)
    alignment = (
        ema_score * config.weight_ema_alignment
        + vwap_score * config.weight_vwap_alignment
        + candle_score * config.weight_candle_structure
        + dir_score * config.weight_direction_agreement
    )

    # Red alert counters
    if ema_score <= 0.1:
        reasons.append("htf_ema_opposes")
    if dir_score <= 0.1:
        reasons.append("direction_conflict")

    # Hard gate: countertrend kills regardless of alignment
    if ct_score < 0.5:
        return ConfirmationState(
            accepted=False,
            confidence=0.0,
            alignment_score=alignment,
            reason="; ".join(reasons) if reasons else "countertrend",
            metrics={
                "ema_alignment": round(ema_score, 4),
                "vwap_alignment": round(vwap_score, 4),
                "candle_structure": round(candle_score, 4),
                "direction_agreement": round(dir_score, 4),
                "countertrend": round(ct_score, 4),
                "exhaustion": round(ex_score, 4),
                "alignment": round(alignment, 4),
            },
        )

    # Exhaustion: reduce confidence but don't hard-reject
    confidence = alignment * ex_score

    accepted = alignment >= config.min_alignment

    reason = "; ".join(reasons) if reasons else ("all_aligned" if accepted else f"low_alignment={alignment:.2f}")

    return ConfirmationState(
        accepted=accepted,
        confidence=round(confidence, 4),
        alignment_score=round(alignment, 4),
        reason=reason,
        metrics={
            "ema_alignment": round(ema_score, 4),
            "vwap_alignment": round(vwap_score, 4),
            "candle_structure": round(candle_score, 4),
            "direction_agreement": round(dir_score, 4),
            "countertrend": round(ct_score, 4),
            "exhaustion": round(ex_score, 4),
            "alignment": round(alignment, 4),
        },
    )