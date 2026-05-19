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
