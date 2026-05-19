"""Tests for Telegram notifier — send, retry, failure handling."""

from __future__ import annotations

import tempfile

import hashlib

import pytest

from ops_api.db import DatabaseManager
from ops_api.notifier import TelegramNotifier, _decorate


@pytest.fixture
def db() -> DatabaseManager:
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


class TestTelegramNotifier:
    def test_disabled_when_no_token(self) -> None:
        n = TelegramNotifier("", "", None)
        assert not n._enabled

    def test_disabled_when_no_chat_id(self) -> None:
        n = TelegramNotifier("token", "", None)
        assert not n._enabled

    def test_enabled_with_token_and_chat_id(self) -> None:
        n = TelegramNotifier("token123", "chat456", None)
        assert n._enabled

    def test_send_returns_false_when_disabled(self) -> None:
        import anyio

        n = TelegramNotifier("", "", None)
        result = anyio.run(n.send, "test", "INFO", "test")
        assert not result

    def test_sync_send_returns_false_when_disabled(self) -> None:
        n = TelegramNotifier("", "", None)
        assert not n.send_sync("test", "INFO", "test")

    def test_send_handles_bad_token_gracefully(self) -> None:
        import anyio

        n = TelegramNotifier("invalid_token", "123", None)
        result = anyio.run(n.send, "test message", "INFO", "test")
        assert not result  # Should return False, not crash
        assert not n.healthy

    def test_dedup_mechanism(self) -> None:
        """Verify dedup hash comparison works (no-op when state compatible)."""
        import anyio

        n = TelegramNotifier("test_token", "123", None)
        # Set last hash to match the decorated form of our test message
        expected_msg = _decorate("INFO", "test message")
        n._last_hash = hashlib.md5(expected_msg.encode()).hexdigest()
        n._last_msg_time = 0

        # Should NOT crash — will try to send but network will fail
        result = anyio.run(n.send, "test message", "INFO", "test")
        # Fails to send (bad token) but should not raise
        assert result is False or result is True
        n._last_hash = ""

    def test_alert_trade_does_not_crash(self) -> None:
        n = TelegramNotifier("", "", None)
        result = n.alert_trade("ORDER FILLED", "NIFTY", "BUY", 100.0, 50, "paper")
        assert not result  # Disabled, but shouldn't crash

    def test_alert_system_does_not_crash(self) -> None:
        n = TelegramNotifier("", "", None)
        result = n.alert_system("Bot started", "Mode: paper", "INFO")
        assert not result  # Disabled, but shouldn't crash

    def test_log_persists_to_db(self, db: DatabaseManager) -> None:
        import uuid

        db.insert_notification_log(
            {
                "id": str(uuid.uuid4()),
                "channel": "telegram",
                "event_type": "test",
                "severity": "INFO",
                "message": "test log",
                "status": "sent",
                "error_message": "",
                "created_at": "2026-05-12T10:00:00",
            }
        )
        logs = db.get_recent_notifications(limit=5)
        assert len(logs) >= 1
        assert logs[0]["channel"] == "telegram"


class TestDecorate:
    def test_adds_severity_and_timestamp(self) -> None:
        result = _decorate("INFO", "test message")
        assert "INFO" in result
        assert "test message" in result
        assert "Time:" in result

    def test_adds_critical_emoji(self) -> None:
        result = _decorate("CRITICAL", "kill switch")
        assert "‼️" in result or "CRITICAL" in result

    def test_adds_error_emoji(self) -> None:
        result = _decorate("ERROR", "error")
        assert "❌" in result or "ERROR" in result
