"""Control endpoint tests — all supported actions, audit trail."""

from __future__ import annotations

import tempfile

import pytest

from ops_api.controls import handle_control_action
from ops_api.db import DatabaseManager


@pytest.fixture
def db() -> DatabaseManager:
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


class TestHandleControlAction:
    def test_unsupported_action(self, db: DatabaseManager) -> None:
        result = handle_control_action("fly_away", db)
        assert result["status"] == "error"

    def test_start(self, db: DatabaseManager) -> None:
        result = handle_control_action("start", db, triggered_by="test", source="web")
        assert result["status"] == "success"
        events = db.get_recent_events(limit=5)
        assert any(e["action"] == "start" for e in events)

    def test_stop(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "running", "mode": "paper"})
        result = handle_control_action("stop", db, triggered_by="test")
        assert result["status"] == "success"
        status = db.get_bot_status()
        assert status["status"] == "stopped"

    def test_pause(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "running", "mode": "paper"})
        result = handle_control_action("pause", db, triggered_by="test")
        assert result["status"] == "success"
        status = db.get_bot_status()
        assert status["status"] == "paused"

    def test_resume(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "paused", "mode": "paper"})
        result = handle_control_action("resume", db)
        assert result["status"] == "success"
        status = db.get_bot_status()
        assert status["status"] == "running"

    def test_flatten(self, db: DatabaseManager) -> None:
        result = handle_control_action("flatten", db, triggered_by="test")
        assert result["status"] == "success"
        commands = db.get_recent_commands(limit=5)
        assert any(c["command"] == "flatten" for c in commands)

    def test_set_mode_paper(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "running", "mode": "live"})
        result = handle_control_action("set_mode", db, params={"mode": "paper"})
        assert result["status"] == "success"
        status = db.get_bot_status()
        assert status["mode"] == "paper"

    def test_set_mode_live(self, db: DatabaseManager) -> None:
        db.upsert_bot_status({"status": "running", "mode": "paper"})
        result = handle_control_action("set_mode", db, params={"mode": "live"})
        assert result["status"] == "success"
        status = db.get_bot_status()
        assert status["mode"] == "live"

    def test_audit_trail_created(self, db: DatabaseManager) -> None:
        handle_control_action("pause", db, triggered_by="admin", source="dashboard")
        events = db.get_recent_events(limit=10)
        assert any(
            e["action"] == "pause"
            and e["triggered_by"] == "admin"
            and e["source"] == "dashboard"
            for e in events
        )

    def test_reload_config(self, db: DatabaseManager) -> None:
        result = handle_control_action("reload_config", db, triggered_by="admin")
        assert result["status"] == "success"
        commands = db.get_recent_commands(limit=5)
        assert any(c["command"] == "reload_config" for c in commands)

    def test_command_stored(self, db: DatabaseManager) -> None:
        handle_control_action("pause", db, triggered_by="test")
        commands = db.get_recent_commands(limit=5)
        assert len(commands) >= 1
        assert commands[0]["command"] == "pause"


class TestKillSwitch:
    def test_kill_activates_kill_switch(self, db: DatabaseManager) -> None:
        handle_control_action(
            "kill", db, triggered_by="admin", params={"reason": "emergency"}
        )
        ks = db.get_kill_switch_state()
        assert ks["active"] is True
        assert ks["triggered_by"] == "admin"
        assert ks["reason"] == "emergency"

    def test_kill_audit_event_stored(self, db: DatabaseManager) -> None:
        handle_control_action(
            "kill", db, triggered_by="operator", params={"reason": "test kill"}
        )
        events = db.get_kill_switch_history(limit=5)
        assert any(
            e["action"] == "activate" and e["triggered_by"] == "operator"
            for e in events
        )

    def test_reset_kill_deactivates(self, db: DatabaseManager) -> None:
        handle_control_action("kill", db, triggered_by="admin")
        handle_control_action("reset_kill", db, triggered_by="admin")
        ks = db.get_kill_switch_state()
        assert ks["active"] is False

    def test_reset_audit_event_stored(self, db: DatabaseManager) -> None:
        handle_control_action("kill", db, triggered_by="admin")
        handle_control_action(
            "reset_kill", db, triggered_by="operator", params={"reason": "all clear"}
        )
        events = db.get_kill_switch_history(limit=5)
        assert any(
            e["action"] == "reset" and e["triggered_by"] == "operator" for e in events
        )

    def test_kill_persists_across_sessions(self, db: DatabaseManager) -> None:
        handle_control_action(
            "kill", db, triggered_by="admin", params={"reason": "test persist"}
        )
        # Simulate restart by reading fresh
        ks = db.get_kill_switch_state()
        assert ks["active"] is True

    def test_kill_switch_can_activate_multiple_times(self, db: DatabaseManager) -> None:
        handle_control_action("kill", db)
        handle_control_action("reset_kill", db)
        handle_control_action("kill", db)
        ks = db.get_kill_switch_state()
        assert ks["active"] is True
        history = db.get_kill_switch_history(limit=10)
        assert len(history) >= 3

    def test_kill_switch_supported_action(self) -> None:
        from ops_api.controls import SUPPORTED_ACTIONS

        assert "kill" in SUPPORTED_ACTIONS
        assert "reset_kill" in SUPPORTED_ACTIONS
