"""Simple module-level state tracking for the trading bot.

In Phase 2 this gets replaced by a proper StateManager class.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytz

_IST = pytz.timezone("Asia/Kolkata")


# ── Module-level state dict ─────────────────────────────────────────────

state: dict[str, Any] = {
    # Position tracking
    "position_status": None,  # None | "LONG" | "SHORT"
    "entry_price": 0.0,
    "entry_time": None,
    "entry_order_id": None,
    "symbol": None,  # trading symbol of the option
    "instrument_token": None,
    "quantity": 0,
    "option_type": None,  # "CE" | "PE"
    # Order mgmt
    "sl_order_id": None,
    "target_order_id": None,
    # Daily counters
    "trades_today": 0,
    "last_trade_time": None,
    "daily_pnl": 0.0,
    # Strategy
    "active_strategy": None,  # "ORB" | "VWAP_PULLBACK"
    "orb_high": None,
    "orb_low": None,
    "entry_candle_time": None,
}


# ── Helper functions ────────────────────────────────────────────────────


def reset_state() -> None:
    """Reset all dynamic state (for EOD or fresh start)."""
    state.update(
        {
            "position_status": None,
            "entry_price": 0.0,
            "entry_time": None,
            "entry_order_id": None,
            "symbol": None,
            "instrument_token": None,
            "quantity": 0,
            "option_type": None,
            "sl_order_id": None,
            "target_order_id": None,
            "trades_today": 0,
            "last_trade_time": None,
            "daily_pnl": 0.0,
            "active_strategy": None,
            "orb_high": None,
            "orb_low": None,
            "entry_candle_time": None,
        }
    )


def open_position(
    side: str,  # "LONG" | "SHORT"
    symbol: str,
    token: int,
    option_type: str,
    price: float,
    qty: int,
    order_id: str,
    strategy: str,
    entry_time: datetime | None = None,
    entry_candle_time: datetime | None = None,
    orb_high: float | None = None,
    orb_low: float | None = None,
) -> None:
    """Record a newly opened position."""
    state["position_status"] = side
    state["symbol"] = symbol
    state["instrument_token"] = token
    state["option_type"] = option_type
    state["entry_price"] = price
    state["quantity"] = qty
    state["entry_order_id"] = order_id
    state["entry_time"] = entry_time or datetime.now(_IST)
    state["entry_candle_time"] = entry_candle_time
    state["active_strategy"] = strategy
    state["orb_high"] = orb_high
    state["orb_low"] = orb_low


def close_position(exit_price: float) -> float:
    """Close the current position and return P&L.

    Updates daily_pnl and trades_today counter.
    """
    qty = state["quantity"]
    entry = state["entry_price"]
    side = state["position_status"]

    if side not in ("LONG", "SHORT"):
        return 0.0

    pnl = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty

    state["daily_pnl"] = (state["daily_pnl"] or 0.0) + pnl
    state["trades_today"] = (state["trades_today"] or 0) + 1
    state["last_trade_time"] = datetime.now(_IST)

    # Clear position
    state["position_status"] = None
    state["symbol"] = None
    state["instrument_token"] = None
    state["entry_price"] = 0.0
    state["entry_time"] = None
    state["quantity"] = 0
    state["option_type"] = None
    state["entry_order_id"] = None
    state["sl_order_id"] = None
    state["target_order_id"] = None
    state["active_strategy"] = None
    state["orb_high"] = None
    state["orb_low"] = None
    state["entry_candle_time"] = None

    return pnl


def in_position() -> bool:
    """Check if there is an open position."""
    return state["position_status"] is not None


def can_trade(config) -> tuple[bool, str]:
    """Check if we can enter a new trade.

    Returns (allowed: bool, reason: str).
    """
    if in_position():
        return False, "Position already open"

    trades = state.get("trades_today") or 0
    if trades >= config.max_trades_per_day:
        return False, f"Max trades ({config.max_trades_per_day}) reached for today"

    last_trade = state.get("last_trade_time")
    if last_trade is not None:
        elapsed = (datetime.now(_IST) - last_trade).total_seconds() / 60
        if elapsed < config.cooldown_minutes:
            return (
                False,
                f"Cooldown active ({elapsed:.0f}/{config.cooldown_minutes} min)",
            )

    daily_pnl = state.get("daily_pnl") or 0.0
    if daily_pnl <= -config.max_daily_loss:
        return False, f"Daily loss limit ({config.max_daily_loss}) breached"

    return True, ""


def should_exit(
    current_price: float,
    config,
) -> tuple[bool, str, float]:
    """Check if current position should be exited.

    Returns (should_exit: bool, reason: str, exit_price: float).
    """
    if not in_position():
        return False, "No position", 0.0

    entry = state["entry_price"]
    side = state["position_status"]
    stop_loss_amount = entry * (config.stop_loss_pct / 100.0)
    target_amount = stop_loss_amount * config.target_multiplier

    if side == "LONG":
        stop_loss = entry - stop_loss_amount
        target = entry + target_amount
        if current_price <= stop_loss:
            return True, "Stop loss hit", current_price
        if current_price >= target:
            return True, "Target reached", current_price
    else:
        stop_loss = entry + stop_loss_amount
        target = entry - target_amount
        if current_price >= stop_loss:
            return True, "Stop loss hit", current_price
        if current_price <= target:
            return True, "Target reached", current_price

    return False, "", 0.0


def get_summary() -> dict[str, Any]:
    """Return a readable summary of current state."""
    return {
        k: str(v) if isinstance(v, datetime) else v
        for k, v in state.items()
        if v is not None
    }


__all__ = [
    "can_trade",
    "close_position",
    "get_summary",
    "in_position",
    "open_position",
    "reset_state",
    "should_exit",
    "state",
]
