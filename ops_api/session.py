"""Trading session lifecycle management.

Replaces module-level globals (``_last_entry_candle_time``, ``PAPER_ORDER_ID``,
the ``state`` dict) with a bounded session object that owns its lifecycle.
Each trading day gets one session; sessions are persisted in SQLite and
survive restarts.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

_SESSION_DEFAULTS: dict[str, Any] = {
    "last_entry_candle_time": None,  # datetime | None
    "paper_order_id": 0,             # counter for PAPER_XXXXXX ids
    "position_status": None,         # None | "LONG" | "SHORT"
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


@dataclass
class SessionSnapshot:
    """Immutable read-only view of a session's current state."""

    session_id: str
    status: str  # ACTIVE | CLOSED | RECOVERED
    start_timestamp: str
    end_timestamp: str | None
    mode: str
    initial_capital: float
    trades: int
    wins: int
    losses: int
    pnl: float
    current_drawdown: float


@dataclass
class TradingSession:
    """One trading day's session. Owns its metrics and mutable state dict."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None
    status: str = "ACTIVE"  # ACTIVE | CLOSED | RECOVERED

    # ── Session-level metrics ─────────────────────────────────────────
    initial_capital: float = 0.0
    final_pnl: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    max_drawdown: float = 0.0
    peak_pnl: float = 0.0
    mode: str = "paper"

    # ── Mutable per-session state (replaces module-level globals) ─────
    state: dict[str, Any] = field(default_factory=lambda: dict(_SESSION_DEFAULTS))

    def next_paper_order_id(self) -> str:
        """Increment and format the paper order ID counter."""
        self.state["paper_order_id"] += 1
        return f"PAPER_{self.state['paper_order_id']:06d}"

    def record_trade(self, pnl: float, win: bool) -> None:
        """Record a completed trade's PnL and update session metrics."""
        self.trades += 1
        if win:
            self.wins += 1
        else:
            self.losses += 1
        self.final_pnl += pnl
        self.peak_pnl = max(self.peak_pnl, self.final_pnl)
        dd = self.peak_pnl - self.final_pnl
        self.max_drawdown = max(self.max_drawdown, dd)

    def snapshot(self) -> SessionSnapshot:
        """Return an immutable read-only view."""
        return SessionSnapshot(
            session_id=self.session_id,
            status=self.status,
            start_timestamp=self.start_timestamp.isoformat() if self.start_timestamp else "",
            end_timestamp=self.end_timestamp.isoformat() if self.end_timestamp else None,
            mode=self.mode,
            initial_capital=self.initial_capital,
            trades=self.trades,
            wins=self.wins,
            losses=self.losses,
            pnl=self.final_pnl,
            current_drawdown=self.max_drawdown,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for DB storage."""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "start_timestamp": self.start_timestamp.isoformat() if self.start_timestamp else "",
            "end_timestamp": self.end_timestamp.isoformat() if self.end_timestamp else None,
            "mode": self.mode,
            "initial_capital": self.initial_capital,
            "final_pnl": self.final_pnl,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "max_drawdown": self.max_drawdown,
            "peak_pnl": self.peak_pnl,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradingSession:
        """Deserialize from DB row."""
        session = cls(
            session_id=data.get("session_id", str(uuid.uuid4())),
            status=data.get("status", "ACTIVE"),
            initial_capital=data.get("initial_capital", 0.0),
            final_pnl=data.get("final_pnl", 0.0),
            trades=data.get("trades", 0),
            wins=data.get("wins", 0),
            losses=data.get("losses", 0),
            max_drawdown=data.get("max_drawdown", 0.0),
            peak_pnl=data.get("peak_pnl", 0.0),
            mode=data.get("mode", "paper"),
        )
        st = data.get("start_timestamp")
        if st:
            session.start_timestamp = datetime.fromisoformat(st)
        et = data.get("end_timestamp")
        if et:
            session.end_timestamp = datetime.fromisoformat(et)
        return session


class SessionManager:
    """Manages session lifecycle — start, end, persist, recover.

    Wraps a ``DatabaseManager`` for persistence and exposes the
    ``current_session`` property.
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._current: TradingSession | None = None

    @staticmethod
    def _parse_metadata(meta: Any) -> dict:
        """Parse metadata field which may be a JSON string or dict."""
        if isinstance(meta, dict):
            return meta
        if isinstance(meta, str) and meta:
            try:
                return json.loads(meta)
            except (json.JSONDecodeError, ValueError):
                pass
        return {}

    def current_session(self) -> TradingSession | None:
        """Return the active session, or None."""
        return self._current

    def start_session(self, mode: str = "paper", initial_capital: float = 0.0) -> TradingSession:
        """Create and persist a new trading session.

        If an ACTIVE session already exists, it's recovered instead.
        """
        existing = self._db.get_active_session()
        if existing is not None:
            logger.info("Recovering existing active session {}", existing["session_id"])
            self._current = TradingSession.from_dict(existing)
            # Restore persisted state if available
            meta = self._parse_metadata(existing.get("metadata"))
            if meta:
                state_data = meta.get("state", {})
                if state_data:
                    self._current.state.update(state_data)
            self._current.status = "RECOVERED"
            self._db.update_session_status(self._current.session_id, "RECOVERED")
            # Persist recovered state back to DB metadata
            self.persist_state()
            return self._current

        now = datetime.utcnow()
        self._current = TradingSession(
            start_timestamp=now,
            mode=mode,
            initial_capital=initial_capital,
        )
        self._db.insert_session(self._current.to_dict())
        # Persist initial state dict as metadata
        self.persist_state()
        logger.info("Session started: {} mode={}", self._current.session_id, mode)
        return self._current

    def end_session(self) -> SessionSnapshot | None:
        """Close the current session, persist summary, return snapshot."""
        session = self._current
        if session is None:
            return None

        session.end_timestamp = datetime.utcnow()
        session.status = "CLOSED"
        # Persist final state before closing so recovery has context
        self.persist_state()
        self._db.update_session_end(
            session_id=session.session_id,
            end_timestamp=session.end_timestamp.isoformat(),
            final_pnl=session.final_pnl,
            trades=session.trades,
            wins=session.wins,
            losses=session.losses,
            max_drawdown=session.max_drawdown,
            peak_pnl=session.peak_pnl,
        )
        snap = session.snapshot()
        logger.info("Session ended: {} pnl={:.2f} trades={}", session.session_id, session.final_pnl, session.trades)
        self._current = None
        return snap

    def recover_incomplete(self) -> TradingSession | None:
        """Called on startup — detect and recover an incomplete session."""
        existing = self._db.get_active_session()
        if existing is None:
            return None

        self._current = TradingSession.from_dict(existing)
        meta = self._parse_metadata(existing.get("metadata"))
        if meta:
            state_data = meta.get("state", {})
            if state_data:
                self._current.state.update(state_data)
        self._current.status = "RECOVERED"
        self._db.update_session_status(self._current.session_id, "RECOVERED")
        logger.warning("Recovered incomplete session {} ({} trades, pnl={:.2f})", self._current.session_id, self._current.trades, self._current.final_pnl)
        return self._current

    def persist_state(self) -> None:
        """Save the current session's state dict as metadata in the DB.

        Call after any mutation to ``self._current.state`` so that
        crash recovery can restore the exact trading context.
        """
        if self._current is None:
            return
        metadata = json.dumps({"state": self._current.state})
        self._db.update_session_metadata(self._current.session_id, metadata)

    def recover_cooldown(self) -> int:
        """Read cooldown state from DB and return remaining seconds.

        Returns 0 if no cooldown is active or no cooldown row exists.
        """
        row = self._db.get_cooldown_state()
        if row is None:
            return 0
        remaining = row.get("remaining_seconds", 0)
        if remaining > 0:
            logger.info("Recovered cooldown: {}s remaining", remaining)
        return remaining

    def get_ordered_ids(self) -> list[str]:
        """Return session IDs from newest to oldest (for tagging new signals)."""
        sessions = self._db.get_recent_sessions(limit=5)
        return [s["session_id"] for s in sessions]

    @property
    def active(self) -> bool:
        return self._current is not None and self._current.status in ("ACTIVE", "RECOVERED")