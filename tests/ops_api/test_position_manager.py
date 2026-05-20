"""Comprehensive test suite for PositionManager.

Tests lifecycle rules (open/adjust/reduce/close/reverse), PnL computation,
mark-to-market, portfolio aggregation, flatten, reversal semantics, and queries.
"""

from __future__ import annotations

import tempfile

import pytest

from ops_api.db import DatabaseManager
from ops_api.position_manager import PositionManager
from ops_api.position_models import (
    MutationAction,
    PortfolioSnapshot,
    PositionMutationResult,
    PositionState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db() -> DatabaseManager:
    """Isolated tempfile-backed database per test."""
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


@pytest.fixture
def pm(db: DatabaseManager) -> PositionManager:
    """PositionManager bound to the isolated database."""
    return PositionManager(db)


# ===================================================================
# TestOpenAdjust -- lifecycle rules (open / adjust / reduce /
#                   close / reverse)
# ===================================================================


class TestOpenAdjust:
    """Verify every branch of open_or_adjust()."""

    # -- open ------------------------------------------------------------

    def test_open_new_long(self, pm: PositionManager) -> None:
        """BUY action opens a LONG position."""
        result = pm.open_or_adjust("TEST", "BUY", 10, 100.0)

        assert result.action == MutationAction.OPENED
        assert result.new_side == "LONG"
        assert result.new_quantity == 10
        assert result.realized_pnl_delta == 0.0
        assert result.previous_state is None

        pos = pm.get_position("TEST")
        assert pos is not None
        assert pos.side == "LONG"
        assert pos.quantity == 10
        assert pos.entry_price == 100.0
        assert pos.current_price == 100.0
        assert pos.realized_pnl == 0.0
        assert pos.unrealized_pnl == 0.0
        assert pos.status == "open"

    def test_open_new_short(self, pm: PositionManager) -> None:
        """SELL action opens a SHORT position."""
        result = pm.open_or_adjust("TEST", "SELL", 10, 100.0)

        assert result.action == MutationAction.OPENED
        assert result.new_side == "SHORT"
        assert result.new_quantity == 10

        pos = pm.get_position("TEST")
        assert pos is not None
        assert pos.side == "SHORT"
        assert pos.quantity == 10
        assert pos.entry_price == 100.0

    # -- adjust ----------------------------------------------------------

    def test_adjust_same_side_long(self, pm: PositionManager) -> None:
        """Same side as existing LONG -> weighted average entry price."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        result = pm.open_or_adjust("TEST", "BUY", 5, 110.0)

        assert result.action == MutationAction.ADJUSTED
        assert result.new_quantity == 15
        expected_avg = (100.0 * 10 + 110.0 * 5) / 15

        pos = pm.get_position("TEST")
        assert pos is not None
        assert pos.quantity == 15
        assert pos.entry_price == pytest.approx(expected_avg, abs=0.01)
        assert pos.realized_pnl == 0.0

    def test_adjust_same_side_short(self, pm: PositionManager) -> None:
        """Same side as existing SHORT -> weighted average entry price."""
        pm.open_or_adjust("TEST", "SELL", 10, 100.0)
        result = pm.open_or_adjust("TEST", "SELL", 5, 90.0)

        assert result.action == MutationAction.ADJUSTED
        assert result.new_quantity == 15
        expected_avg = (100.0 * 10 + 90.0 * 5) / 15

        pos = pm.get_position("TEST")
        assert pos is not None
        assert pos.quantity == 15
        assert pos.entry_price == pytest.approx(expected_avg, abs=0.01)
        assert pos.realized_pnl == 0.0

    # -- reduce ----------------------------------------------------------

    def test_reduce_long(self, pm: PositionManager) -> None:
        """Opposite side, smaller qty for LONG -> reduce with realized PnL."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        result = pm.open_or_adjust("TEST", "SELL", 4, 110.0)

        assert result.action == MutationAction.REDUCED
        assert result.new_quantity == 6
        # LONG: realized = (exit - entry) * qty = (110 - 100) * 4
        assert result.realized_pnl_delta == pytest.approx(40.0, abs=0.01)

        pos = pm.get_position("TEST")
        assert pos is not None
        assert pos.quantity == 6
        assert pos.entry_price == 100.0  # unchanged on reduce
        assert pos.realized_pnl == pytest.approx(40.0, abs=0.01)

    def test_reduce_short(self, pm: PositionManager) -> None:
        """Opposite side, smaller qty for SHORT -> reduce with realized PnL."""
        pm.open_or_adjust("TEST", "SELL", 10, 100.0)
        result = pm.open_or_adjust("TEST", "BUY", 4, 90.0)

        assert result.action == MutationAction.REDUCED
        assert result.new_quantity == 6
        # SHORT: realized = (entry - exit) * qty = (100 - 90) * 4
        assert result.realized_pnl_delta == pytest.approx(40.0, abs=0.01)

        pos = pm.get_position("TEST")
        assert pos is not None
        assert pos.quantity == 6
        assert pos.realized_pnl == pytest.approx(40.0, abs=0.01)

    # -- close -----------------------------------------------------------

    def test_close_long(self, pm: PositionManager) -> None:
        """Opposite side, equal qty for LONG -> close with realized PnL."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        result = pm.open_or_adjust("TEST", "SELL", 10, 110.0)

        assert result.action == MutationAction.CLOSED
        assert result.new_state is None
        assert result.new_quantity == 0
        assert result.realized_pnl_delta == pytest.approx(100.0, abs=0.01)

        pos = pm.get_position("TEST")
        assert pos is None  # no open position remains

    def test_close_short(self, pm: PositionManager) -> None:
        """Opposite side, equal qty for SHORT -> close with realized PnL."""
        pm.open_or_adjust("TEST", "SELL", 10, 100.0)
        result = pm.open_or_adjust("TEST", "BUY", 10, 90.0)

        assert result.action == MutationAction.CLOSED
        assert result.new_state is None
        assert result.realized_pnl_delta == pytest.approx(100.0, abs=0.01)

        pos = pm.get_position("TEST")
        assert pos is None

    # -- reverse ---------------------------------------------------------

    def test_reverse_long_to_short(self, pm: PositionManager) -> None:
        """Opposite side, larger qty for LONG -> close + open opposite."""
        pm.open_or_adjust("TEST", "BUY", 5, 100.0)
        result = pm.open_or_adjust("TEST", "SELL", 8, 110.0)

        assert result.action == MutationAction.REVERSED
        # LONG close: realized = (110 - 100) * 5 = 50
        assert result.realized_pnl_delta == pytest.approx(50.0, abs=0.01)
        assert result.new_side == "SHORT"
        assert result.new_quantity == 3

        pos = pm.get_position("TEST")
        assert pos is not None
        assert pos.side == "SHORT"
        assert pos.quantity == 3
        assert pos.entry_price == 110.0

    def test_reverse_short_to_long(self, pm: PositionManager) -> None:
        """Opposite side, larger qty for SHORT -> close + open opposite."""
        pm.open_or_adjust("TEST", "SELL", 5, 100.0)
        result = pm.open_or_adjust("TEST", "BUY", 8, 90.0)

        assert result.action == MutationAction.REVERSED
        # SHORT close: realized = (100 - 90) * 5 = 50
        assert result.realized_pnl_delta == pytest.approx(50.0, abs=0.01)
        assert result.new_side == "LONG"
        assert result.new_quantity == 3

        pos = pm.get_position("TEST")
        assert pos is not None
        assert pos.side == "LONG"
        assert pos.quantity == 3
        assert pos.entry_price == 90.0

    # -- validation ------------------------------------------------------

    def test_empty_symbol_raises(self, pm: PositionManager) -> None:
        """Empty symbol should raise ValueError."""
        with pytest.raises(ValueError):
            pm.open_or_adjust("", "BUY", 10, 100.0)


# ===================================================================
# TestMTM -- mark_to_market
# ===================================================================


class TestMTM:
    """Verify mark_to_market updates only unrealized fields."""

    def test_mtm_updates_unrealized(self, pm: PositionManager) -> None:
        """LONG position: MTM at higher price -> positive unrealized PnL."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        state = pm.mark_to_market("TEST", 110.0)

        assert state.current_price == 110.0
        # LONG: unrealized = (110 - 100) * 10 = 100
        assert state.unrealized_pnl == pytest.approx(100.0, abs=0.01)

    def test_mtm_does_not_touch_realized(self, pm: PositionManager) -> None:
        """MTM must never mutate realized_pnl."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        before = pm.get_position("TEST")
        assert before is not None
        assert before.realized_pnl == 0.0

        pm.mark_to_market("TEST", 110.0)
        after = pm.get_position("TEST")
        assert after is not None
        assert after.realized_pnl == 0.0

    def test_mtm_short(self, pm: PositionManager) -> None:
        """SHORT position: MTM at lower price -> positive unrealized PnL."""
        pm.open_or_adjust("TEST", "SELL", 10, 100.0)
        state = pm.mark_to_market("TEST", 90.0)

        assert state.current_price == 90.0
        # SHORT: unrealized = (entry - current) * qty = (100 - 90) * 10
        assert state.unrealized_pnl == pytest.approx(100.0, abs=0.01)

    def test_mtm_nonexistent_symbol(self, pm: PositionManager) -> None:
        """MTM on absent symbol should raise ValueError."""
        with pytest.raises(ValueError):
            pm.mark_to_market("NONEXISTENT", 100.0)


# ===================================================================
# TestPortfolio -- portfolio aggregation
# ===================================================================


class TestPortfolio:
    """Verify get_portfolio() aggregation logic."""

    def test_empty_portfolio(self, pm: PositionManager) -> None:
        """Empty portfolio returns zeroed snapshot."""
        snapshot = pm.get_portfolio()

        assert snapshot.position_count == 0
        assert snapshot.total_exposure == 0.0
        assert snapshot.total_unrealized_pnl == 0.0
        assert snapshot.total_realized_pnl == 0.0
        assert snapshot.largest_position_symbol == ""
        assert snapshot.largest_position_pct == 0.0
        assert snapshot.positions == []

    def test_single_position(self, pm: PositionManager) -> None:
        """One position with correct exposure and PnL."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        snapshot = pm.get_portfolio()

        assert snapshot.position_count == 1
        assert snapshot.total_exposure == 1000.0  # 10 * 100
        assert snapshot.total_unrealized_pnl == 0.0
        assert snapshot.total_realized_pnl == 0.0
        assert snapshot.largest_position_symbol == "TEST"
        assert snapshot.largest_position_pct == 100.0

    def test_multiple_positions(self, pm: PositionManager) -> None:
        """Multiple positions aggregating correctly."""
        pm.open_or_adjust("AAPL", "BUY", 10, 100.0)   # exposure = 1000
        pm.open_or_adjust("GOOG", "BUY", 5, 50.0)     # exposure = 250

        snapshot = pm.get_portfolio()

        assert snapshot.position_count == 2
        assert snapshot.total_exposure == 1250.0
        assert snapshot.largest_position_symbol == "AAPL"
        largest_pct = 1000.0 / 1250.0 * 100
        assert snapshot.largest_position_pct == pytest.approx(largest_pct, abs=0.01)

    def test_largest_position_pct(self, pm: PositionManager) -> None:
        """Largest position percentage is correctly computed."""
        pm.open_or_adjust("BIG", "BUY", 10, 100.0)    # exposure = 1000
        pm.open_or_adjust("SML", "BUY", 3, 50.0)      # exposure = 150
        pm.open_or_adjust("MID", "BUY", 5, 80.0)      # exposure = 400

        snapshot = pm.get_portfolio()

        assert snapshot.largest_position_symbol == "BIG"
        expected_pct = 1000.0 / (1000.0 + 150.0 + 400.0) * 100
        assert snapshot.largest_position_pct == pytest.approx(expected_pct, abs=0.01)

    def test_portfolio_type(self, pm: PositionManager) -> None:
        """get_portfolio returns a PortfolioSnapshot dataclass."""
        snapshot = pm.get_portfolio()
        assert isinstance(snapshot, PortfolioSnapshot)
        assert hasattr(snapshot, "updated_at")

        # With a position, it should still be a PortfolioSnapshot
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        snapshot2 = pm.get_portfolio()
        assert isinstance(snapshot2, PortfolioSnapshot)
        assert len(snapshot2.positions) == 1
        assert isinstance(snapshot2.positions[0], PositionState)


# ===================================================================
# TestReversalSemantics -- reversal lifecycle details
# ===================================================================


class TestReversalSemantics:
    """Verify that a reversal correctly closes the old position and opens
    a new one as a distinct row."""

    def test_reversal_creates_new_position(self, pm: PositionManager, db: DatabaseManager) -> None:
        """Two distinct position rows exist after reversal."""
        result1 = pm.open_or_adjust("TEST", "BUY", 5, 100.0)
        old_id = result1.new_state.id if result1.new_state else ""

        result2 = pm.open_or_adjust("TEST", "SELL", 8, 110.0)
        new_id = result2.new_state.id if result2.new_state else ""

        assert old_id != ""
        assert new_id != ""
        assert old_id != new_id

        # Two distinct rows in the DB
        closed_positions = pm.get_closed_positions(limit=10)
        open_pos = pm.get_position("TEST")

        assert open_pos is not None
        assert open_pos.id == new_id
        assert open_pos.status == "open"

        closed_ids = {p.id for p in closed_positions}
        assert old_id in closed_ids

    def test_reversal_closes_old_position(self, pm: PositionManager) -> None:
        """Old position has status='closed' and a closed_at timestamp."""
        result1 = pm.open_or_adjust("TEST", "BUY", 5, 100.0)
        old_id = result1.new_state.id if result1.new_state else ""

        pm.open_or_adjust("TEST", "SELL", 8, 110.0)

        closed = [p for p in pm.get_closed_positions(limit=10) if p.id == old_id]
        assert len(closed) == 1
        assert closed[0].status == "closed"
        assert closed[0].closed_at is not None

    def test_reversal_pnl_correct(self, pm: PositionManager) -> None:
        """Realized PnL on reversal reflects the full close of the old position."""
        pm.open_or_adjust("TEST", "BUY", 5, 100.0)
        result = pm.open_or_adjust("TEST", "SELL", 8, 110.0)

        # LONG close 5 @ 110: realized = (110 - 100) * 5 = 50
        assert result.realized_pnl_delta == pytest.approx(50.0, abs=0.01)


# ===================================================================
# TestFlatten -- synthetic paper-mode close-all
# ===================================================================


class TestFlatten:
    """Verify flatten() closes all open positions."""

    def test_flatten_closes_all(self, pm: PositionManager) -> None:
        """All open positions closed after flatten."""
        pm.open_or_adjust("AAPL", "BUY", 10, 100.0)
        pm.open_or_adjust("GOOG", "BUY", 5, 200.0)

        results = pm.flatten()

        assert len(results) == 2

        pos_aapl = pm.get_position("AAPL")
        pos_goog = pm.get_position("GOOG")
        assert pos_aapl is None
        assert pos_goog is None

        closed = pm.get_closed_positions(limit=10)
        closed_symbols = {p.symbol for p in closed}
        assert "AAPL" in closed_symbols
        assert "GOOG" in closed_symbols

    def test_flatten_empty(self, pm: PositionManager) -> None:
        """Flatten with no open positions is a no-op."""
        results = pm.flatten()
        assert results == []

    def test_flatten_returns_mutations(self, pm: PositionManager) -> None:
        """Flatten returns a list of PositionMutationResult."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        results = pm.flatten()

        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], PositionMutationResult)
        assert results[0].action == MutationAction.CLOSED
        assert results[0].symbol == "TEST"


# ===================================================================
# TestGetMethods -- query methods
# ===================================================================


class TestGetMethods:
    """Verify get_position, get_all_positions, and get_closed_positions."""

    def test_get_position(self, pm: PositionManager) -> None:
        """Returns correct PositionState for an open position."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        pos = pm.get_position("TEST")

        assert isinstance(pos, PositionState)
        assert pos.symbol == "TEST"
        assert pos.side == "LONG"
        assert pos.quantity == 10
        assert pos.entry_price == 100.0
        assert pos.status == "open"
        assert pos.opened_at != ""

    def test_get_position_none(self, pm: PositionManager) -> None:
        """Returns None when no open position exists."""
        pos = pm.get_position("NONEXISTENT")
        assert pos is None

    def test_get_all_open_positions(self, pm: PositionManager) -> None:
        """Returns only open positions, not closed ones."""
        pm.open_or_adjust("OPEN1", "BUY", 10, 100.0)
        pm.open_or_adjust("OPEN2", "BUY", 5, 50.0)
        pm.open_or_adjust("OPEN1", "SELL", 10, 110.0)  # closes OPEN1

        all_open = pm.get_all_positions()
        symbols = {p.symbol for p in all_open}

        assert "OPEN2" in symbols
        assert "OPEN1" not in symbols
        assert len(all_open) == 1

    def test_get_closed_positions(self, pm: PositionManager) -> None:
        """Returns closed position history."""
        pm.open_or_adjust("TEST", "BUY", 10, 100.0)
        pm.open_or_adjust("TEST", "SELL", 10, 110.0)

        closed = pm.get_closed_positions(limit=10)

        assert len(closed) >= 1
        assert closed[0].symbol == "TEST"
        assert closed[0].status == "closed"
        assert closed[0].closed_at is not None