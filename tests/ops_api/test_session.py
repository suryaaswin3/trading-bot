"""Tests for trading session lifecycle."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from ops_api.session import TradingSession, SessionManager


class TestTradingSession:
    def test_create_session(self):
        s = TradingSession()
        assert s.session_id is not None
        assert s.status == "ACTIVE"
        assert s.trades == 0
        assert s.final_pnl == 0.0

    def test_next_paper_order_id(self):
        s = TradingSession()
        oid1 = s.next_paper_order_id()
        assert oid1 == "PAPER_000001"
        oid2 = s.next_paper_order_id()
        assert oid2 == "PAPER_000002"

    def test_record_trade_win(self):
        s = TradingSession()
        s.record_trade(pnl=100.0, win=True)
        assert s.trades == 1
        assert s.wins == 1
        assert s.losses == 0
        assert s.final_pnl == 100.0

    def test_record_trade_loss(self):
        s = TradingSession()
        s.record_trade(pnl=-50.0, win=False)
        assert s.trades == 1
        assert s.wins == 0
        assert s.losses == 1
        assert s.final_pnl == -50.0

    def test_max_drawdown_tracking(self):
        s = TradingSession()
        s.record_trade(pnl=100.0, win=True)
        s.record_trade(pnl=-200.0, win=False)
        s.record_trade(pnl=50.0, win=True)
        assert s.peak_pnl == 100.0
        assert s.max_drawdown == 200.0

    def test_snapshot(self):
        s = TradingSession()
        s.record_trade(pnl=250.0, win=True)
        snap = s.snapshot()
        assert snap.trades == 1
        assert snap.pnl == 250.0
        assert snap.session_id == s.session_id
        assert snap.status == "ACTIVE"

    def test_to_dict_roundtrip(self):
        s = TradingSession()
        s.record_trade(pnl=100.0, win=True)
        d = s.to_dict()
        assert d["session_id"] == s.session_id
        assert d["trades"] == 1
        assert d["final_pnl"] == 100.0

        s2 = TradingSession.from_dict(d)
        assert s2.session_id == s.session_id
        assert s2.trades == 1
        assert s2.final_pnl == 100.0

    def test_from_dict_with_timestamps(self):
        data = {
            "session_id": "test-id",
            "status": "ACTIVE",
            "start_timestamp": "2026-05-21T09:15:00",
            "end_timestamp": None,
            "mode": "paper",
            "initial_capital": 0.0,
            "final_pnl": 500.0,
            "trades": 3,
            "wins": 2,
            "losses": 1,
            "max_drawdown": 100.0,
            "peak_pnl": 600.0,
        }
        s = TradingSession.from_dict(data)
        assert s.session_id == "test-id"
        assert s.status == "ACTIVE"
        assert s.trades == 3
        assert s.final_pnl == 500.0
        assert s.start_timestamp is not None


class TestSessionManager:
    def test_start_session(self):
        db = MagicMock()
        db.get_active_session.return_value = None
        sm = SessionManager(db)
        s = sm.start_session()
        assert s is not None
        assert s.status == "ACTIVE"
        db.insert_session.assert_called_once()

    def test_end_session(self):
        db = MagicMock()
        db.get_active_session.return_value = None
        sm = SessionManager(db)
        sm.start_session()
        snap = sm.end_session()
        assert snap is not None
        assert snap.status == "CLOSED"
        assert sm.current_session() is None

    def test_recover_incomplete(self):
        db = MagicMock()
        db.get_active_session.return_value = {
            "session_id": "recover-id",
            "status": "ACTIVE",
            "start_timestamp": "2026-05-21T09:15:00",
            "end_timestamp": None,
            "mode": "paper",
            "initial_capital": 0.0,
            "final_pnl": 200.0,
            "trades": 2,
            "wins": 1,
            "losses": 1,
            "max_drawdown": 50.0,
            "peak_pnl": 250.0,
            "metadata": "{}",
        }
        sm = SessionManager(db)
        recovered = sm.recover_incomplete()
        assert recovered is not None
        assert recovered.status == "RECOVERED"
        assert recovered.trades == 2

    def test_no_session_to_recover(self):
        db = MagicMock()
        db.get_active_session.return_value = None
        sm = SessionManager(db)
        assert sm.recover_incomplete() is None

    def test_double_start_recovery(self):
        db = MagicMock()
        db.get_active_session.side_effect = [
            {"session_id": "existing", "status": "ACTIVE",
             "start_timestamp": "2026-05-21T09:15:00", "end_timestamp": None,
             "mode": "paper", "initial_capital": 0.0, "final_pnl": 0.0,
             "trades": 0, "wins": 0, "losses": 0, "max_drawdown": 0.0,
             "peak_pnl": 0.0, "metadata": "{}"},
        ]
        sm = SessionManager(db)
        s = sm.start_session()
        assert s.status == "RECOVERED"
        assert s.session_id == "existing"