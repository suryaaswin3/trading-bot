"""Health check and heartbeat tests."""

from __future__ import annotations

import tempfile

import pytest

from ops_api.db import DatabaseManager
from ops_api.health import (
    check_api,
    check_bot,
    check_config,
    check_database,
    run_health_checks,
    write_heartbeat,
)


@pytest.fixture
def db() -> DatabaseManager:
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


class TestHealthChecks:
    def test_check_database_pass(self, db: DatabaseManager) -> None:
        result = check_database(db)
        assert result["status"] == "pass"
        assert result["component"] == "database"

    def test_check_api(self, db: DatabaseManager) -> None:
        result = check_api(db)
        assert result["status"] == "pass"

    def test_check_config_pass(self) -> None:
        result = check_config(True)
        assert result["status"] == "pass"

    def test_check_config_fail(self) -> None:
        result = check_config(False)
        assert result["status"] == "fail"

    def test_check_bot_no_status(self, db: DatabaseManager) -> None:
        result = check_bot(db)
        assert result["status"] == "warn"

    def test_check_bot_running(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "running", "mode": "paper"})
        result = check_bot(db)
        assert result["status"] == "pass"

    def test_check_bot_paused(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "paused", "mode": "paper"})
        result = check_bot(db)
        assert result["status"] == "pass"

    def test_run_health_checks(self, db: DatabaseManager) -> None:
        results = run_health_checks(db, config_loaded=True)
        assert len(results) >= 4
        for r in results:
            assert "component" in r
            assert "status" in r

    def test_health_checks_stored_to_db(self, db: DatabaseManager) -> None:
        run_health_checks(db, config_loaded=True)
        checks = db.get_recent_health_checks(limit=10)
        assert len(checks) >= 4


class TestHeartbeat:
    def test_write_heartbeat_no_bot_status(self, db: DatabaseManager) -> None:
        write_heartbeat(
            db,
            bot_status="running",
            bot_mode="paper",
            trades_today=0,
            daily_pnl=0.0,
        )
        hb = db.get_latest_heartbeat()
        assert hb is not None
        assert hb["bot_status"] == "running"

    def test_write_heartbeat_updates_bot_status(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "stopped", "mode": "paper"})
        write_heartbeat(
            db,
            bot_status="running",
            bot_mode="live",
            trades_today=5,
            daily_pnl=100.0,
            kite_connected=True,
        )
        status = db.get_bot_status()
        assert status["status"] == "running"
        assert status["mode"] == "live"
        assert status["trades_today"] == 5
        assert status["daily_pnl"] == 100.0
        assert status["kite_connected"] == 1

    def test_multiple_heartbeats(self, db: DatabaseManager) -> None:
        write_heartbeat(db, bot_status="running")
        write_heartbeat(db, bot_status="running", trades_today=1)
        write_heartbeat(db, bot_status="paused", trades_today=2)
        hbs = db.get_recent_heartbeats(limit=10)
        assert len(hbs) == 3
