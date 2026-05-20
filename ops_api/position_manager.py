"""PositionManager -- single source of truth for position lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ops_api.db import DatabaseManager
from ops_api.position_models import (
    MutationAction,
    PositionMutationResult,
    PortfolioSnapshot,
    PositionState,
)


def _row_to_state(row: dict[str, Any]) -> PositionState:
    return PositionState(
        id=row["id"],
        symbol=row["symbol"],
        side=row["side"],
        quantity=row["quantity"],
        entry_price=row["entry_price"],
        current_price=row["current_price"],
        realized_pnl=row["realized_pnl"],
        unrealized_pnl=row["unrealized_pnl"],
        status=row["status"],
        strategy_id=row.get("strategy_id", ""),
        opened_at=row["opened_at"],
        closed_at=row.get("closed_at"),
        updated_at=row["updated_at"],
    )


class PositionManager:
    """Single source of truth for position lifecycle.

    All position mutations flow through this class.
    Strategies express intent only -- PositionManager owns state.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # -- Lifecycle ----------------------------------------------------------

    def open_or_adjust(
        self,
        symbol: str,
        side: str,  # BUY or SELL (trading action)
        quantity: int,
        price: float,
        strategy_id: str = "",
    ) -> PositionMutationResult:
        """Open, adjust, reduce, close, or reverse a position.

        Net-account semantics:
        - Same direction as existing -> adjust entry price (weighted average)
        - Opposite direction, smaller qty -> reduce position, realize PnL
        - Opposite direction, equal qty -> close position, realize PnL
        - Opposite direction, larger qty -> close + reverse, realize PnL on full close

        side is the trading action (BUY/SELL). Maps to position side:
          BUY -> LONG (opens/adjusts LONG, reduces/closes SHORT)
          SELL -> SHORT (opens/adjusts SHORT, reduces/closes LONG)
        """
        existing = self._db.get_position_by_symbol(symbol)
        prev = _row_to_state(existing) if existing else None

        position_side = "LONG" if side == "BUY" else "SHORT"

        if existing is None:
            # No existing position -- open new
            self._db.upsert_open_position(symbol, position_side, quantity, price, strategy_id)
            self._db.insert_position_snapshot_for_compat(symbol, position_side, quantity, price, price, 0.0, 0.0)
            self._db.update_bot_status_position_compat(symbol, position_side, quantity, price)
            new = _row_to_state(self._db.get_position_by_symbol(symbol))
            return PositionMutationResult(
                mutation_id=str(uuid.uuid4()),
                symbol=symbol,
                action=MutationAction.OPENED,
                previous_side="",
                previous_quantity=0,
                new_side=position_side,
                new_quantity=quantity,
                price=price,
                realized_pnl_delta=0.0,
                previous_state=prev,
                new_state=new,
                timestamp=datetime.utcnow().isoformat(),
            )

        if existing["side"] == position_side:
            # Same direction -- adjust (weighted average entry price)
            total_qty = existing["quantity"] + quantity
            avg_entry = ((existing["entry_price"] * existing["quantity"]) + (price * quantity)) / total_qty
            self._db.upsert_open_position(symbol, position_side, total_qty, avg_entry, strategy_id)
            self._db.insert_position_snapshot_for_compat(symbol, position_side, total_qty, avg_entry, price, 0.0, 0.0)
            self._db.update_bot_status_position_compat(symbol, position_side, total_qty, avg_entry)
            new = _row_to_state(self._db.get_position_by_symbol(symbol))
            return PositionMutationResult(
                mutation_id=str(uuid.uuid4()),
                symbol=symbol,
                action=MutationAction.ADJUSTED,
                previous_side=existing["side"],
                previous_quantity=existing["quantity"],
                new_side=position_side,
                new_quantity=total_qty,
                price=price,
                realized_pnl_delta=0.0,
                previous_state=prev,
                new_state=new,
                timestamp=datetime.utcnow().isoformat(),
            )

        # Opposite direction -- reduce, close, or reverse
        # PnL direction depends on which position side is being closed
        # Closing LONG (existing side is LONG, incoming is SELL): direction = 1
        #   realized = (exit - entry) * qty * 1  (profit when exit > entry)
        # Closing SHORT (existing side is SHORT, incoming is BUY): direction = -1
        #   realized = (exit - entry) * qty * -1 = (entry - exit) * qty (profit when exit < entry)
        direction = 1 if existing["side"] == "LONG" else -1

        if quantity < existing["quantity"]:
            # Partial close (reduce)
            realized = (price - existing["entry_price"]) * quantity * direction
            self._db.reduce_position(symbol, quantity, price)
            self._db.insert_position_snapshot_for_compat(
                symbol, existing["side"], existing["quantity"] - quantity,
                existing["entry_price"], price, realized, 0.0,
            )
            updated = self._db.get_position_by_symbol(symbol)
            self._db.update_bot_status_position_compat(symbol, updated["side"], updated["quantity"], updated["entry_price"])
            new = _row_to_state(updated)
            return PositionMutationResult(
                mutation_id=str(uuid.uuid4()),
                symbol=symbol,
                action=MutationAction.REDUCED,
                previous_side=existing["side"],
                previous_quantity=existing["quantity"],
                new_side=existing["side"],
                new_quantity=existing["quantity"] - quantity,
                price=price,
                realized_pnl_delta=realized,
                previous_state=prev,
                new_state=new,
                timestamp=datetime.utcnow().isoformat(),
            )

        # quantity >= existing["quantity"] -- full close, possibly reverse
        realized = (price - existing["entry_price"]) * existing["quantity"] * direction
        self._db.close_position(symbol, price)
        self._db.insert_position_snapshot_for_compat(
            symbol, existing["side"], 0, existing["entry_price"], price, realized, 0.0,
        )
        self._db.update_bot_status_position_compat(symbol, "", 0, 0.0)

        reverse_qty = quantity - existing["quantity"]
        if reverse_qty > 0:
            # Reverse: close old -> open new opposite
            new_side = "SHORT" if position_side == "SHORT" else "LONG"
            self._db.upsert_open_position(symbol, new_side, reverse_qty, price, strategy_id)
            self._db.insert_position_snapshot_for_compat(symbol, new_side, reverse_qty, price, price, 0.0, 0.0)
            self._db.update_bot_status_position_compat(symbol, new_side, reverse_qty, price)
            new_state = _row_to_state(self._db.get_position_by_symbol(symbol))
            action = MutationAction.REVERSED
        else:
            new_state = None
            action = MutationAction.CLOSED

        return PositionMutationResult(
            mutation_id=str(uuid.uuid4()),
            symbol=symbol,
            action=action,
            previous_side=existing["side"],
            previous_quantity=existing["quantity"],
            new_side=new_state.side if new_state else "",
            new_quantity=reverse_qty if new_state else 0,
            price=price,
            realized_pnl_delta=realized,
            previous_state=prev,
            new_state=new_state,
            timestamp=datetime.utcnow().isoformat(),
        )

    def close(self, symbol: str, exit_price: float) -> PositionMutationResult:
        """Force-close an open position. No reverse."""
        existing = self._db.get_position_by_symbol(symbol)
        if existing is None:
            raise ValueError(f"No open position for {symbol}")
        prev = _row_to_state(existing)
        direction = 1 if existing["side"] == "LONG" else -1
        realized = (exit_price - existing["entry_price"]) * existing["quantity"] * direction
        self._db.close_position(symbol, exit_price)
        self._db.insert_position_snapshot_for_compat(
            symbol, existing["side"], 0, existing["entry_price"], exit_price, realized, 0.0,
        )
        self._db.update_bot_status_position_compat(symbol, "", 0, 0.0)
        return PositionMutationResult(
            mutation_id=str(uuid.uuid4()),
            symbol=symbol,
            action=MutationAction.CLOSED,
            previous_side=existing["side"],
            previous_quantity=existing["quantity"],
            new_side="",
            new_quantity=0,
            price=exit_price,
            realized_pnl_delta=realized,
            previous_state=prev,
            new_state=None,
            timestamp=datetime.utcnow().isoformat(),
        )

    # -- Read ---------------------------------------------------------------

    def get_position(self, symbol: str) -> PositionState | None:
        row = self._db.get_position_by_symbol(symbol)
        return _row_to_state(row) if row else None

    def get_all_positions(self) -> list[PositionState]:
        rows = self._db.get_all_open_positions()
        return [_row_to_state(r) for r in rows]

    def get_closed_positions(self, limit: int = 50) -> list[PositionState]:
        rows = self._db.get_closed_positions(limit)
        return [_row_to_state(r) for r in rows]

    # -- MTM ----------------------------------------------------------------

    def mark_to_market(self, symbol: str, current_price: float) -> PositionState:
        """Update current_price and unrealized_pnl only. Never mutates realized_pnl."""
        self._db.update_position_mtm(symbol, current_price)
        return _row_to_state(self._db.get_position_by_symbol(symbol))

    # -- Portfolio ----------------------------------------------------------

    def get_portfolio(self) -> PortfolioSnapshot:
        positions = self.get_all_positions()
        total_exposure = sum(p.quantity * p.current_price for p in positions)
        total_unrealized = sum(p.unrealized_pnl for p in positions)
        total_realized = sum(p.realized_pnl for p in positions)
        position_count = len(positions)
        largest = max(positions, key=lambda p: p.quantity * p.current_price) if positions else None
        largest_pct = ((largest.quantity * largest.current_price) / total_exposure * 100) if largest and total_exposure > 0 else 0.0
        return PortfolioSnapshot(
            positions=positions,
            total_exposure=total_exposure,
            total_unrealized_pnl=total_unrealized,
            total_realized_pnl=total_realized,
            position_count=position_count,
            largest_position_symbol=largest.symbol if largest else "",
            largest_position_pct=largest_pct,
            updated_at=datetime.utcnow().isoformat(),
        )

    def flatten(self) -> list[PositionMutationResult]:
        """Synthetic paper-mode flatten: close all open positions at current price.

        Future live flatten must route through broker execution.
        """
        positions = self.get_all_positions()
        results = []
        for pos in positions:
            results.append(self.close(pos.symbol, pos.current_price))
        return results