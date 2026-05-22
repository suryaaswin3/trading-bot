"""Deterministic options strike selection — stateless, pure functions.

Selects the appropriate strike for an option trade based on market
conditions, volatility, and expiry awareness.

Decision tree:
- Continuation (low vol, trending): ATM strike
- Volatile conditions: slight ITM (buffer against whipsaw)
- Illiquid strikes: rejected (premium below threshold)
- Expiry-aware: skip if <1hr to close on same-day expiry
- Premium-range filtering: reject if premium outside configured band

Usage::

    selection = select_strike(
        underlying_price=22350.0,
        atr_percent=0.8,
        side="BUY",
        expiry_days=6,
        is_call=True,
    )
    if selection.accepted:
        print(selection.strike)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class OptionsConfig:
    """Tunable thresholds for strike selection."""

    # Volatility thresholds (ATR % of underlying)
    volatile_threshold: float = 1.5  # ATR >= 1.5% → volatile conditions

    # Strike selection
    atm_straddle_buffer: float = 0.0  # NSE lots: 0 = exact ATM
    itm_buffer_steps: int = 1  # how many strikes ITM in volatile mode

    # Premium filtering (fraction of underlying)
    min_premium_pct: float = 0.001  # 0.1% — reject dust
    max_premium_pct: float = 0.05   # 5% — reject too-expensive

    # Expiry limits
    min_expiry_hours: float = 1.0  # reject if <1hr to close

    # Liquidity proxy: minimum open interest / volume ratio
    min_oi_volume_ratio: float = 0.5

    # ATM step for underlying (Nifty = 50, BankNifty = 100)
    atm_step: float = 50.0


# ── Result ──────────────────────────────────────────────────────────────────


@dataclass
class StrikeSelection:
    """Result of strike selection."""

    accepted: bool
    strike: float
    is_call: bool
    is_itm: bool
    premium_estimate: float
    expiry_days: int
    reason: str
    method: str = ""  # "atm" | "itm"
    metrics: dict[str, float] = field(default_factory=dict)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _round_to_strike(price: float, step: float) -> float:
    """Round price to nearest strike step."""
    return round(price / step) * step


def _estimate_premium(
    underlying: float,
    strike: float,
    is_call: bool,
    atr_percent: float,
    expiry_days: float,
) -> float:
    """Rough premium estimate using intrinsic value + time value.

    Uses a simplified model: intrinsic + (ATR * sqrt(expiry_days/365) * 0.5).
    This is NOT a pricing model — just a sanity filter for rejection.
    """
    intrinsic = 0.0
    if is_call and underlying > strike:
        intrinsic = underlying - strike
    elif not is_call and underlying < strike:
        intrinsic = strike - underlying

    time_value = (atr_percent / 100.0) * underlying * (expiry_days / 365.0) ** 0.5 * 0.5
    return intrinsic + time_value


# ── Decision ────────────────────────────────────────────────────────────────


def select_strike(
    underlying_price: float,
    atr_percent: float,
    side: str,  # "BUY" or "SELL"
    expiry_days: float,
    is_call: bool = True,
    config: OptionsConfig | None = None,
    oi_volume_ratio: float | None = None,
) -> StrikeSelection:
    """Select the optimal options strike for current conditions.

    Parameters
    ----------
    underlying_price:
        Current price of the underlying.
    atr_percent:
        Current ATR as percentage of underlying price.
    side:
        Signal side: ``"BUY"`` (long) or ``"SELL"`` (short).
    expiry_days:
        Days until option expiry.
    is_call:
        True for Call, False for Put.
    config:
        Optional OptionsConfig. Defaults used if None.
    oi_volume_ratio:
        Optional open-interest / volume ratio for liquidity check.
        Pass ``None`` to skip this check.

    Returns
    -------
    StrikeSelection with acceptance, selected strike, and reasoning.
    """
    if config is None:
        config = OptionsConfig()

    # ── Expiry gate ─────────────────────────────────────────────────────
    if expiry_days < 0:
        return StrikeSelection(
            accepted=False,
            strike=0.0,
            is_call=is_call,
            is_itm=False,
            premium_estimate=0.0,
            expiry_days=int(expiry_days),
            reason="expired",
        )

    if expiry_days < (config.min_expiry_hours / 24.0):
        return StrikeSelection(
            accepted=False,
            strike=0.0,
            is_call=is_call,
            is_itm=False,
            premium_estimate=0.0,
            expiry_days=int(expiry_days),
            reason=f"expiry_too_close ({expiry_days:.2f}d < {config.min_expiry_hours / 24.0:.2f}d)",
        )

    # ── Liquidity gate ──────────────────────────────────────────────────
    if oi_volume_ratio is not None and oi_volume_ratio < config.min_oi_volume_ratio:
        return StrikeSelection(
            accepted=False,
            strike=0.0,
            is_call=is_call,
            is_itm=False,
            premium_estimate=0.0,
            expiry_days=int(expiry_days),
            reason=f"low_liquidity (oi/vol={oi_volume_ratio:.2f})",
        )

    # ── Determine strike ────────────────────────────────────────────────
    atm_strike = _round_to_strike(underlying_price, config.atm_step)

    is_volatile = atr_percent >= config.volatile_threshold

    if is_volatile:
        # Slight ITM for volatile: buffer against whipsaw
        if is_call:
            strike = atm_strike - config.itm_buffer_steps * config.atm_step
        else:
            strike = atm_strike + config.itm_buffer_steps * config.atm_step
        method = "itm"
    else:
        # ATM for continuation / normal conditions
        strike = atm_strike
        method = "atm"

    is_itm = (is_call and strike < underlying_price) or (not is_call and strike > underlying_price)

    # ── Premium filter ──────────────────────────────────────────────────
    premium = _estimate_premium(underlying_price, strike, is_call, atr_percent, expiry_days)
    premium_pct = premium / underlying_price if underlying_price > 0 else 0.0

    if premium_pct < config.min_premium_pct:
        return StrikeSelection(
            accepted=False,
            strike=strike,
            is_call=is_call,
            is_itm=is_itm,
            premium_estimate=premium,
            expiry_days=int(expiry_days),
            reason=f"premium_too_low ({premium_pct:.4%})",
            method=method,
            metrics={"premium_pct": premium_pct, "atr_percent": atr_percent},
        )

    if premium_pct > config.max_premium_pct:
        return StrikeSelection(
            accepted=False,
            strike=strike,
            is_call=is_call,
            is_itm=is_itm,
            premium_estimate=premium,
            expiry_days=int(expiry_days),
            reason=f"premium_too_high ({premium_pct:.4%})",
            method=method,
            metrics={"premium_pct": premium_pct, "atr_percent": atr_percent},
        )

    return StrikeSelection(
        accepted=True,
        strike=strike,
        is_call=is_call,
        is_itm=is_itm,
        premium_estimate=round(premium, 2),
        expiry_days=int(expiry_days),
        reason="accepted",
        method=method,
        metrics={
            "premium_pct": round(premium_pct, 6),
            "atr_percent": round(atr_percent, 4),
            "volatile": 1.0 if is_volatile else 0.0,
        },
    )