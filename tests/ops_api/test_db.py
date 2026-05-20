"""Database CRUD tests — each test uses a tempfile-backed DatabaseManager."""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime

import pytest

from ops_api.db import DatabaseManager


@pytest.fixture
def db() -> DatabaseManager:
    """Create an isolated temp database for each test."""
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


class TestSchema:
    def test_init_schema_creates_tables(self, db: DatabaseManager) -> None:
        """Verify all tables exist after schema init."""
        conn = db._connect()
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [t["name"] for t in tables]
            required = [
                "webhook_alerts",
                "normalized_signals",
                "validation_results",
                "execution_orders",
                "position_snapshots",
                "bot_status",
                "bot_commands",
                "health_checks",
                "heartbeats",
                "control_events",
                "risk_counters",
            ]
            for t in required:
                assert t in table_names, f"Missing table: {t}"
        finally:
            conn.close()

    def test_init_schema_idempotent(self, db: DatabaseManager) -> None:
        """Calling init_schema multiple times should not error."""
        db.init_schema()
        db.init_schema()
        db.init_schema()
        conn = db._connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table'"
            ).fetchone()["cnt"]
            assert count >= 11
        finally:
            conn.close()


class TestWebhookAlerts:
    def test_insert_and_get_by_alert_id(self, db: DatabaseManager) -> None:
        alert = {
            "id": str(uuid.uuid4()),
            "alert_id": "tv_001",
            "raw_payload": {"symbol": "NIFTY", "side": "BUY"},
            "received_at": "2026-05-11T10:00:00.000Z",
            "source_ip": "192.168.1.1",
            "authenticated": True,
            "normalized_id": None,
        }
        db.insert_alert(alert)
        found = db.get_alert_by_alert_id("tv_001")
        assert found is not None
        assert found["alert_id"] == "tv_001"

    def test_get_recent_alerts_empty(self, db: DatabaseManager) -> None:
        assert db.get_recent_alerts(limit=10) == []

    def test_duplicate_alert_id_ignored(self, db: DatabaseManager) -> None:
        alert1 = {
            "id": str(uuid.uuid4()),
            "alert_id": "dup",
            "raw_payload": {},
            "received_at": "2026-05-11T10:00:00.000Z",
            "source_ip": "x",
            "authenticated": True,
            "normalized_id": None,
        }
        alert2 = {
            "id": str(uuid.uuid4()),
            "alert_id": "dup",
            "raw_payload": {},
            "received_at": "2026-05-11T10:01:00.000Z",
            "source_ip": "x",
            "authenticated": True,
            "normalized_id": None,
        }
        db.insert_alert(alert1)
        db.insert_alert(alert2)  # INSERT OR IGNORE — should not raise
        assert len(db.get_recent_alerts(limit=10)) == 1


class TestSignals:
    def test_insert_and_recent(self, db: DatabaseManager) -> None:
        signal = {
            "id": str(uuid.uuid4()),
            "webhook_alert_id": str(uuid.uuid4()),
            "alert_id": "tv_001",
            "symbol": "NIFTY",
            "side": "BUY",
            "strategy": "VWAP_PULLBACK",
            "timeframe": "5min",
            "price": 18150.0,
            "signal_timestamp": None,
            "reason": "test",
            "normalized_at": "2026-05-11T10:00:00.000Z",
        }
        db.insert_signal(signal)
        recent = db.get_recent_signals(limit=10)
        assert len(recent) == 1
        assert recent[0]["symbol"] == "NIFTY"


class TestValidationResults:
    def test_insert_and_last(self, db: DatabaseManager) -> None:
        v = {
            "id": str(uuid.uuid4()),
            "signal_id": str(uuid.uuid4()),
            "passed": True,
            "checks": [{"check": "market_open", "passed": True, "detail": ""}],
            "rejection_reason": "",
            "validated_at": "2026-05-11T10:00:00.000Z",
        }
        db.insert_validation(v)
        last = db.get_last_validation()
        assert last is not None
        assert last["passed"] == 1

    def test_get_last_when_empty(self, db: DatabaseManager) -> None:
        assert db.get_last_validation() is None


class TestExecutionOrders:
    def test_insert_and_dedup(self, db: DatabaseManager) -> None:
        dedup_key = f"test_dedup_{uuid.uuid4()}"
        order = {
            "id": str(uuid.uuid4()),
            "signal_id": str(uuid.uuid4()),
            "validation_id": str(uuid.uuid4()),
            "mode": "paper",
            "symbol": "NIFTY",
            "side": "BUY",
            "quantity": 50,
            "price": 150.0,
            "order_type": "LIMIT",
            "status": "pending",
            "external_order_id": None,
            "strategy": "VWAP_PULLBACK",
            "dedup_key": dedup_key,
            "error_message": "",
            "created_at": "2026-05-11T10:00:00.000Z",
            "updated_at": None,
        }
        db.insert_order(order)

        # Duplicate dedup_key should be silently ignored
        order2 = order.copy()
        order2["id"] = str(uuid.uuid4())
        db.insert_order(order2)

        # Only one should exist
        found = db.get_order_by_dedup_key(dedup_key)
        assert found is not None

    def test_update_order(self, db: DatabaseManager) -> None:
        oid = str(uuid.uuid4())
        order = {
            "id": oid,
            "signal_id": str(uuid.uuid4()),
            "validation_id": str(uuid.uuid4()),
            "mode": "paper",
            "symbol": "NIFTY",
            "side": "BUY",
            "quantity": 50,
            "price": 150.0,
            "order_type": "LIMIT",
            "status": "pending",
            "external_order_id": None,
            "strategy": "VWAP_PULLBACK",
            "dedup_key": f"dedup_{uuid.uuid4()}",
            "error_message": "",
            "created_at": "2026-05-11T10:00:00.000Z",
            "updated_at": None,
        }
        db.insert_order(order)
        db.update_order(oid, {"status": "filled", "external_order_id": "KITE001"})
        updated = db.get_order_by_dedup_key(order["dedup_key"])
        assert updated is not None
        assert updated["status"] == "filled"

    def test_get_last_order(self, db: DatabaseManager) -> None:
        assert db.get_last_order() is None
        oid = str(uuid.uuid4())
        db.insert_order(
            {
                "id": oid,
                "signal_id": str(uuid.uuid4()),
                "validation_id": str(uuid.uuid4()),
                "mode": "paper",
                "symbol": "NIFTY",
                "side": "BUY",
                "quantity": 50,
                "price": 150.0,
                "order_type": "LIMIT",
                "status": "filled",
                "external_order_id": None,
                "strategy": "V",
                "dedup_key": f"dk_{uuid.uuid4()}",
                "error_message": "",
                "created_at": "2026-05-11T10:00:00.000Z",
                "updated_at": None,
            }
        )
        assert db.get_last_order() is not None


class TestBotStatus:
    def test_upsert_and_read(self, db: DatabaseManager) -> None:
        assert db.get_bot_status() is None
        db.upsert_bot_status({"status": "running", "mode": "paper"})
        status = db.get_bot_status()
        assert status is not None
        assert status["status"] == "running"

    def test_upsert_replaces(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "running", "mode": "paper", "trades_today": 0})
        db.upsert_bot_status({"status": "paused", "mode": "paper", "trades_today": 3})
        status = db.get_bot_status()
        assert status["status"] == "paused"
        assert status["trades_today"] == 3

    def test_only_one_row(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "running", "mode": "paper"})
        db.upsert_bot_status({"status": "stopped", "mode": "live"})
        conn = db._connect()
        try:
            count = conn.execute("SELECT COUNT(*) as cnt FROM bot_status").fetchone()[
                "cnt"
            ]
            assert count == 1
        finally:
            conn.close()


class TestBotCommands:
    def test_insert_and_pending(self, db: DatabaseManager) -> None:
        db.insert_command(
            {
                "id": str(uuid.uuid4()),
                "command": "pause",
                "params": {},
                "issued_at": "2026-05-11T10:00:00.000Z",
                "issued_by": "test",
                "status": "pending",
                "result": "",
            }
        )
        pending = db.get_pending_commands()
        assert len(pending) == 1

    def test_ack_and_complete(self, db: DatabaseManager) -> None:
        cid = str(uuid.uuid4())
        db.insert_command(
            {
                "id": cid,
                "command": "flatten",
                "params": {},
                "issued_at": "2026-05-11T10:00:00.000Z",
                "issued_by": "test",
                "status": "pending",
                "result": "",
            }
        )
        db.ack_command(cid)
        db.complete_command(cid, "All positions closed")
        pending = db.get_pending_commands()
        assert len(pending) == 0


class TestHeartbeats:
    def test_insert_and_latest(self, db: DatabaseManager) -> None:
        assert db.get_latest_heartbeat() is None
        db.insert_heartbeat(
            {
                "id": str(uuid.uuid4()),
                "bot_status": "running",
                "bot_mode": "paper",
                "last_action": "",
                "trades_today": 5,
                "daily_pnl": 100.0,
                "kite_connected": 1,
                "timestamp": "2026-05-11T10:00:00.000Z",
            }
        )
        hb = db.get_latest_heartbeat()
        assert hb is not None
        assert hb["trades_today"] == 5


class TestRiskCounters:
    def test_upsert_todays(self, db: DatabaseManager) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        assert db.get_todays_risk_counter() is None
        db.upsert_risk_counter(
            {
                "id": str(uuid.uuid4()),
                "date": today,
                "trades_today": 3,
                "daily_pnl": 500.0,
                "consecutive_losses": 0,
                "max_drawdown": 0.0,
                "max_drawdown_pct": 0.0,
                "peak_pnl": 500.0,
            }
        )
        rc = db.get_todays_risk_counter()
        assert rc is not None
        assert rc["trades_today"] == 3

    def test_upsert_updates_existing(self, db: DatabaseManager) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        db.upsert_risk_counter(
            {
                "id": str(uuid.uuid4()),
                "date": today,
                "trades_today": 1,
                "daily_pnl": 100.0,
                "consecutive_losses": 0,
                "max_drawdown": 0.0,
                "max_drawdown_pct": 0.0,
                "peak_pnl": 100.0,
            }
        )
        db.upsert_risk_counter(
            {
                "id": str(uuid.uuid4()),
                "date": today,
                "trades_today": 2,
                "daily_pnl": 200.0,
                "consecutive_losses": 0,
                "max_drawdown": 0.0,
                "max_drawdown_pct": 0.0,
                "peak_pnl": 200.0,
            }
        )
        rc = db.get_todays_risk_counter()
        assert rc is not None
        assert rc["trades_today"] == 2
        assert rc["daily_pnl"] == 200.0


class TestPositionsCRUD:
    """Tests for positions table CRUD operations (Phase 4)."""

    def test_upsert_new_position(self, db):
        """Insert a new open position returns an id."""
        pid = db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        assert pid is not None
        assert isinstance(pid, str) and len(pid) > 0

    def test_upsert_updates_existing(self, db):
        """Upserting same symbol overwrites with new values (PositionManager handles accumulation)."""
        db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        db.upsert_open_position("RELIANCE", "LONG", 15, 260.0)
        row = db.get_position_by_symbol("RELIANCE")
        assert row is not None
        assert row["quantity"] == 15
        assert row["entry_price"] == 260.0

    def test_upsert_allows_closed_duplicate(self, db):
        """Partial unique index allows same symbol after closing."""
        pid1 = db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        db.close_position("RELIANCE", 260.0)
        pid2 = db.upsert_open_position("RELIANCE", "LONG", 5, 255.0)
        assert pid2 is not None
        assert pid1 != pid2

    def test_close_position_long(self, db):
        """Close a long position computes realized PnL correctly."""
        db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        result = db.close_position("RELIANCE", 260.0)
        assert result is not None
        assert result["quantity"] == 0
        assert result["status"] == "closed"
        assert result["realized_pnl"] == pytest.approx(100.0)
        assert result["closed_at"] is not None

    def test_close_position_short(self, db):
        """Close a short position computes realized PnL correctly."""
        db.upsert_open_position("TCS", "SHORT", 5, 200.0)
        result = db.close_position("TCS", 190.0)
        assert result is not None
        assert result["realized_pnl"] == pytest.approx(50.0)

    def test_close_nonexistent_returns_none(self, db):
        """Closing a position that doesn't exist returns None."""
        result = db.close_position("NONEXIST", 100.0)
        assert result is None

    def test_reduce_position_long(self, db):
        """Reduce a long position: partial close with pro-rata realized PnL."""
        db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        result = db.reduce_position("RELIANCE", 4, 260.0)
        assert result is not None
        assert result["quantity"] == 6
        assert result["realized_pnl"] == pytest.approx(40.0)
        assert result["status"] == "open"

    def test_reduce_position_short(self, db):
        """Reduce a short position: partial close with correct PnL."""
        db.upsert_open_position("TCS", "SHORT", 5, 200.0)
        result = db.reduce_position("TCS", 2, 190.0)
        assert result is not None
        assert result["quantity"] == 3
        assert result["realized_pnl"] == pytest.approx(20.0)

    def test_reduce_full_quantity_closes(self, db):
        """Reducing all quantity delegates to close_position."""
        db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        result = db.reduce_position("RELIANCE", 10, 260.0)
        assert result is not None
        assert result["quantity"] == 0
        assert result["status"] == "closed"

    def test_mtm_updates_current_price(self, db):
        """MTM updates current_price and unrealized_pnl only."""
        db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        result = db.update_position_mtm("RELIANCE", 260.0)
        assert result is not None
        assert result["current_price"] == 260.0
        assert result["unrealized_pnl"] == pytest.approx(100.0)

    def test_mtm_preserves_realized_pnl(self, db):
        """MTM must not touch realized_pnl."""
        db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        result = db.update_position_mtm("RELIANCE", 260.0)
        assert result["realized_pnl"] == 0.0

    def test_get_all_open_positions(self, db):
        """Returns only open positions."""
        db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        db.upsert_open_position("TCS", "SHORT", 5, 200.0)
        db.close_position("TCS", 195.0)
        positions = db.get_all_open_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "RELIANCE"

    def test_get_closed_positions_history(self, db):
        """Returns closed positions in reverse chronological order."""
        db.upsert_open_position("RELIANCE", "LONG", 10, 250.0)
        db.close_position("RELIANCE", 260.0)
        db.upsert_open_position("TCS", "SHORT", 5, 200.0)
        db.close_position("TCS", 195.0)
        closed = db.get_closed_positions(limit=5)
        assert len(closed) == 2
        assert closed[0]["symbol"] == "TCS"

    def test_compat_snapshot_insert(self, db):
        """insert_position_snapshot_for_compat writes to position_snapshots."""
        db.insert_position_snapshot_for_compat("RELIANCE", "LONG", 10, 250.0, 260.0, 50.0, 100.0)
        curve = db.get_equity_curve(limit=10)
        assert len(curve) >= 1
