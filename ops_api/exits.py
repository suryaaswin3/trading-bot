"""Deterministic exit strategy evaluation — stateless, pure functions.

Evaluates multiple exit strategies for an open position and returns
actionable exit signals. Each exit is independent; the caller decides
which to honour based on priority.

Supported exits:
- Trailing stop (trail by ATR multiple from peak)
- Break-even stop (move stop to entry after profit target reached)
- ATR trailing (chandelier: exit when price retraces N ATR from high)
- Momentum fade (profit target based on avg ATR expansion)
- Time-based (exit after N bars if no progress toward target)
- VWAP loss-of-control (exit when price decisively crosses VWAP against position)

Usage::

    signals = evaluate_exits(
        position=position_state,
        current_price=last_price,
        bars=all_bars,
        entry_index=entry_idx,
    )
    for s in signals:
        if s.triggered:
            close_position(s)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class ExitConfig:
    """Tunable thresholds for all exit strategies."""

    # Trailing stop
    trail_atr_multiple: float = 2.0       # Trail N ATR from peak
    trail_activation_pct: float = 0.5     # Activate after price moves 0.5 ATR favourably

    # Break-even stop
    be_atr_target: float = 1.0            # Move stop to entry after 1 ATR favourable move
    be_slip_buffer: float = 0.5           # Place stop 0.5 ATR below entry (breakeven + buffer)

    # ATR trailing (chandelier)
    chandelier_atr_multiple: float = 3.0  # Exit if price retraces 3 ATR from peak

    # Momentum fade (profit target)
    fade_atr_target: float = 2.5          # Take profit at 2.5 ATR from entry
    fade_scale_pct: float = 0.5           # Exit 50% at target, rest trails

    # Time-based exit
    max_hold_bars: int = 60               # Exit after 60 bars (60min on 1m, 5hr on 5m)
    min_progress_atr: float = 0.3         # Must show 0.3 ATR progress within max_hold

    # VWAP loss-of-control
    vwap_deviation_atr: float = 1.0       # Exit if price crosses VWAP by N ATR against position
    vwap_confirmation_bars: int = 2       # Must hold for N consecutive bars


# ── Result ──────────────────────────────────────────────────────────────────


@dataclass
class ExitSignal:
    """Signal from a single exit strategy."""

    strategy: str       # "trailing_stop" | "break_even" | "chandelier" | "momentum_fade" | "time_based" | "vwap_loc"
    triggered: bool
    exit_price: float
    reason: str
    priority: int = 0  # lower = higher priority


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


def _compute_atr(bars: list[dict[str, Any]], period: int = 14) -> float:
    """Compute latest ATR value."""
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


def _compute_vwap(bars: list[dict[str, Any]]) -> float:
    cum_pv = 0.0
    cum_vol = 0.0
    for b in bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_pv += tp * b["volume"]
        cum_vol += b["volume"]
    return cum_pv / cum_vol if cum_vol > 0 else bars[-1]["close"]


def _bars_since_entry(bars: list[dict[str, Any]], entry_index: int) -> int:
    """Number of bars since entry (clamped to available bars)."""
    if entry_index < 0 or entry_index >= len(bars):
        return 0
    return len(bars) - entry_index - 1


def _peak_price(bars: list[dict[str, Any]], entry_index: int, side: str) -> float:
    """Highest (LONG) or lowest (SHORT) price since entry."""
    segment = bars[entry_index:]
    if side == "LONG":
        return max(b["high"] for b in segment)
    else:
        return min(b["low"] for b in segment)


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


# ── Exit Strategies ─────────────────────────────────────────────────────────


def trailing_stop(
    position_side: str,
    entry_price: float,
    current_price: float,
    atr_value: float,
    bars_since_entry: int,
    config: ExitConfig,
) -> ExitSignal:
    """Trailing stop that follows the price at N ATR from peak.

    Only activates after price has moved favourably by activation_pct of ATR.
    """
    favourable_move = (
        (current_price - entry_price) if position_side == "LONG"
        else (entry_price - current_price)
    )
    activation_threshold = config.trail_activation_pct * atr_value

    if favourable_move < activation_threshold:
        return ExitSignal(
            strategy="trailing_stop",
            triggered=False,
            exit_price=0.0,
            reason=f"not_activated ({favourable_move:.2f} < {activation_threshold:.2f})",
            priority=3,
        )

    # Stop is N ATR below peak (LONG) or above peak (SHORT)
    peak = current_price  # Use current as reference; caller should pass true peak
    if position_side == "LONG":
        exit_price = peak - config.trail_atr_multiple * atr_value
    else:
        exit_price = peak + config.trail_atr_multiple * atr_value

    return ExitSignal(
        strategy="trailing_stop",
        triggered=False,  # Evaluated by caller on each tick
        exit_price=round(exit_price, 2),
        reason=f"trailing {config.trail_atr_multiple:.0f}ATR from peak",
        priority=3,
    )


def break_even_stop(
    position_side: str,
    entry_price: float,
    current_price: float,
    atr_value: float,
    config: ExitConfig,
) -> ExitSignal:
    """Move stop to entry + buffer after price hits profit target.

    Once activated, returns a triggered signal so the caller can tighten.
    The exit_price is set to entry + buffer for LONG, entry - buffer for SHORT.
    """
    favourable_move = (
        (current_price - entry_price) if position_side == "LONG"
        else (entry_price - current_price)
    )
    be_target = config.be_atr_target * atr_value

    if favourable_move < be_target:
        return ExitSignal(
            strategy="break_even",
            triggered=False,
            exit_price=0.0,
            reason=f"target_not_met ({favourable_move:.2f} < {be_target:.2f})",
            priority=5,
        )

    buffer = config.be_slip_buffer * atr_value
    if position_side == "LONG":
        exit_price = entry_price + buffer
    else:
        exit_price = entry_price - buffer

    return ExitSignal(
        strategy="break_even",
        triggered=True,  # Caller should tighten stop to this level
        exit_price=round(exit_price, 2),
        reason=f"break_even_active (entry ± {buffer:.2f})",
        priority=5,
    )


def chandelier_exit(
    position_side: str,
    current_price: float,
    peak: float,
    atr_value: float,
    config: ExitConfig,
) -> ExitSignal:
    """Chandelier exit: exit when price retraces N ATR from peak.

    Returns triggered=True when retracement exceeds threshold.
    """
    if position_side == "LONG":
        retracement = peak - current_price
        threshold = config.chandelier_atr_multiple * atr_value
        stop_price = peak - threshold
    else:
        retracement = current_price - peak
        threshold = config.chandelier_atr_multiple * atr_value
        stop_price = peak + threshold

    if retracement >= threshold:
        return ExitSignal(
            strategy="chandelier",
            triggered=True,
            exit_price=round(stop_price, 2),
            reason=f"retraced {retracement:.2f} >= {threshold:.2f} ({config.chandelier_atr_multiple:.0f}ATR from peak)",
            priority=1,
        )

    return ExitSignal(
        strategy="chandelier",
        triggered=False,
        exit_price=round(stop_price, 2),
        reason=f"trailing {config.chandelier_atr_multiple:.0f}ATR from peak ({retracement:.2f} < {threshold:.2f})",
        priority=1,
    )


def momentum_fade_exit(
    position_side: str,
    entry_price: float,
    current_price: float,
    atr_value: float,
    config: ExitConfig,
) -> ExitSignal:
    """Profit target based on ATR expansion.

    Triggers when price has moved N ATR from entry (fade the move).
    """
    move = (
        (current_price - entry_price) if position_side == "LONG"
        else (entry_price - current_price)
    )
    target = config.fade_atr_target * atr_value

    if move >= target:
        return ExitSignal(
            strategy="momentum_fade",
            triggered=True,
            exit_price=round(current_price, 2),
            reason=f"profit_target_met ({move:.2f} >= {target:.2f})",
            priority=2,
        )

    return ExitSignal(
        strategy="momentum_fade",
        triggered=False,
        exit_price=0.0,
        reason=f"building ({move:.2f} / {target:.2f})",
        priority=2,
    )


def time_based_exit(
    position_side: str,
    entry_price: float,
    current_price: float,
    bars_since_entry: int,
    atr_value: float,
    config: ExitConfig,
) -> ExitSignal:
    """Exit after max hold bars if insufficient progress.

    Prevents capital being locked in stagnant positions.
    """
    if bars_since_entry < config.max_hold_bars:
        return ExitSignal(
            strategy="time_based",
            triggered=False,
            exit_price=0.0,
            reason=f"holding ({bars_since_entry}/{config.max_hold_bars} bars)",
            priority=6,
        )

    # Check progress
    progress = (
        (current_price - entry_price) if position_side == "LONG"
        else (entry_price - current_price)
    )

    if progress >= config.min_progress_atr * atr_value:
        return ExitSignal(
            strategy="time_based",
            triggered=False,
            exit_price=0.0,
            reason=f"adequate_progress ({progress:.2f}), extending hold",
            priority=6,
        )

    return ExitSignal(
        strategy="time_based",
        triggered=True,
        exit_price=round(current_price, 2),
        reason=f"max_hold_reached ({bars_since_entry} bars, progress={progress:.2f})",
        priority=6,
    )


def vwap_loss_of_control(
    position_side: str,
    current_price: float,
    vwap_value: float,
    atr_value: float,
    bars_since_entry: int,
    config: ExitConfig,
) -> ExitSignal:
    """Exit when price decisively crosses VWAP against position.

    LONG: price closes below VWAP by N ATR → loss of control
    SHORT: price closes above VWAP by N ATR → loss of control
    """
    if vwap_value <= 0 or bars_since_entry < config.vwap_confirmation_bars:
        return ExitSignal(
            strategy="vwap_loc",
            triggered=False,
            exit_price=0.0,
            reason="insufficient_data",
            priority=4,
        )

    deviation = current_price - vwap_value

    if position_side == "LONG":
        # Price below VWAP is bad for a long
        if deviation < 0 and abs(deviation) >= config.vwap_deviation_atr * atr_value:
            return ExitSignal(
                strategy="vwap_loc",
                triggered=True,
                exit_price=round(current_price, 2),
                reason=f"price_below_vwap ({abs(deviation):.2f} >= {config.vwap_deviation_atr:.0f}ATR)",
                priority=4,
            )
    else:
        # Price above VWAP is bad for a short
        if deviation > 0 and abs(deviation) >= config.vwap_deviation_atr * atr_value:
            return ExitSignal(
                strategy="vwap_loc",
                triggered=True,
                exit_price=round(current_price, 2),
                reason=f"price_above_vwap ({abs(deviation):.2f} >= {config.vwap_deviation_atr:.0f}ATR)",
                priority=4,
            )

    return ExitSignal(
        strategy="vwap_loc",
        triggered=False,
        exit_price=0.0,
        reason=f"in_control (deviation={deviation:.2f})",
        priority=4,
    )


# ── Aggregation ─────────────────────────────────────────────────────────────


def evaluate_exits(
    position_side: str,
    entry_price: float,
    current_price: float,
    bars: list[Any],
    entry_index: int,
    config: ExitConfig | None = None,
) -> list[ExitSignal]:
    """Evaluate all exit strategies for a position.

    Parameters
    ----------
    position_side:
        ``"LONG"`` or ``"SHORT"``.
    entry_price:
        Position entry price.
    current_price:
        Current market price.
    bars:
        Full OHLCV bar list (dicts or BarSnapshots).
    entry_index:
        Index in ``bars`` where the position was entered.
    config:
        Optional ExitConfig. Defaults used if None.

    Returns
    -------
    List of ExitSignal, one per strategy. The caller should action
    any with ``triggered=True``, ordered by priority (lower = sooner).
    """
    if config is None:
        config = ExitConfig()

    raw_bars = _normalize_bars(bars)
    atr_value = _compute_atr(raw_bars)
    if atr_value <= 0:
        return []  # Can't evaluate exits without ATR

    bse = _bars_since_entry(raw_bars, entry_index)
    peak = _peak_price(raw_bars, entry_index, position_side)
    vwap = _compute_vwap(raw_bars)

    signals: list[ExitSignal] = [
        trailing_stop(position_side, entry_price, current_price, atr_value, bse, config),
        break_even_stop(position_side, entry_price, current_price, atr_value, config),
        chandelier_exit(position_side, current_price, peak, atr_value, config),
        momentum_fade_exit(position_side, entry_price, current_price, atr_value, config),
        time_based_exit(position_side, entry_price, current_price, bse, atr_value, config),
        vwap_loss_of_control(position_side, current_price, vwap, atr_value, bse, config),
    ]

    # Sort by priority (lower = more urgent)
    signals.sort(key=lambda s: s.priority)
    return signals