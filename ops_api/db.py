"""SQLite database manager for the trading ops layer.

WAL mode enabled for concurrent reader/writer safety.
All timestamps stored as ISO-8601 UTC strings.
Thread-safe: each operation opens its own connection.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Raw incoming webhook alerts
CREATE TABLE IF NOT EXISTS webhook_alerts (
    id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL DEFAULT '',
    raw_payload TEXT NOT NULL DEFAULT '{}',
    received_at TEXT NOT NULL,
    source_ip TEXT NOT NULL DEFAULT '',
    authenticated INTEGER NOT NULL DEFAULT 0,
    normalized_id TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_webhook_alerts_alert_id ON webhook_alerts(alert_id);

-- Normalized signals from parsed alerts
CREATE TABLE IF NOT EXISTS normalized_signals (
    id TEXT PRIMARY KEY,
    webhook_alert_id TEXT NOT NULL DEFAULT '',
    alert_id TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT 'BUY',
    strategy TEXT NOT NULL DEFAULT '',
    timeframe TEXT NOT NULL DEFAULT '',
    price REAL NOT NULL DEFAULT 0.0,
    signal_timestamp TEXT,
    reason TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'webhook',
    data_source TEXT NOT NULL DEFAULT 'production',
    normalized_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_alert_id ON normalized_signals(alert_id);

-- Validation results
CREATE TABLE IF NOT EXISTS validation_results (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL DEFAULT '',
    passed INTEGER NOT NULL DEFAULT 0,
    checks TEXT NOT NULL DEFAULT '[]',
    rejection_reason TEXT NOT NULL DEFAULT '',
    validated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_validation_signal_id ON validation_results(signal_id);

-- Order execution records
CREATE TABLE IF NOT EXISTS execution_orders (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL DEFAULT '',
    validation_id TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'paper',
    symbol TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT 'BUY',
    quantity INTEGER NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0.0,
    order_type TEXT NOT NULL DEFAULT 'LIMIT',
    status TEXT NOT NULL DEFAULT 'pending',
    external_order_id TEXT,
    strategy TEXT NOT NULL DEFAULT '',
    dedup_key TEXT UNIQUE,
    error_message TEXT NOT NULL DEFAULT '',
    data_source TEXT NOT NULL DEFAULT 'production',
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_dedup_key ON execution_orders(dedup_key);
CREATE INDEX IF NOT EXISTS idx_orders_signal_id ON execution_orders(signal_id);

-- Position snapshots (append-only history)
CREATE TABLE IF NOT EXISTS position_snapshots (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT 'NONE',
    quantity INTEGER NOT NULL DEFAULT 0,
    entry_price REAL NOT NULL DEFAULT 0.0,
    current_price REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl REAL NOT NULL DEFAULT 0.0,
    realized_pnl REAL NOT NULL DEFAULT 0.0,
    trades_today INTEGER NOT NULL DEFAULT 0,
    daily_pnl REAL NOT NULL DEFAULT 0.0,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pos_snap_time ON position_snapshots(timestamp);

-- Bot status (singleton row, id=1)
CREATE TABLE IF NOT EXISTS bot_status (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    status TEXT NOT NULL DEFAULT 'stopped',
    mode TEXT NOT NULL DEFAULT 'paper',
    current_symbol TEXT,
    position_side TEXT,
    position_qty INTEGER NOT NULL DEFAULT 0,
    position_entry_price REAL NOT NULL DEFAULT 0.0,
    trades_today INTEGER NOT NULL DEFAULT 0,
    daily_pnl REAL NOT NULL DEFAULT 0.0,
    cumulative_pnl REAL NOT NULL DEFAULT 0.0,
    wins_today INTEGER NOT NULL DEFAULT 0,
    losses_today INTEGER NOT NULL DEFAULT 0,
    max_drawdown_today REAL NOT NULL DEFAULT 0.0,
    last_heartbeat_at TEXT,
    last_alert_at TEXT,
    last_order_at TEXT,
    active_strategy TEXT,
    kite_connected INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- Bot commands (API -> bot communication, polled by bot)
CREATE TABLE IF NOT EXISTS bot_commands (
    id TEXT PRIMARY KEY,
    command TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL DEFAULT '{}',
    issued_at TEXT NOT NULL,
    issued_by TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    acked_at TEXT,
    completed_at TEXT,
    result TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cmds_pending ON bot_commands(status);

-- Health check snapshots
CREATE TABLE IF NOT EXISTS health_checks (
    id TEXT PRIMARY KEY,
    component TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pass',
    detail TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_time ON health_checks(checked_at);

-- Heartbeat records
CREATE TABLE IF NOT EXISTS heartbeats (
    id TEXT PRIMARY KEY,
    bot_status TEXT NOT NULL DEFAULT 'stopped',
    bot_mode TEXT NOT NULL DEFAULT 'paper',
    last_action TEXT NOT NULL DEFAULT '',
    trades_today INTEGER NOT NULL DEFAULT 0,
    daily_pnl REAL NOT NULL DEFAULT 0.0,
    kite_connected INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hb_time ON heartbeats(timestamp);

-- Control action event log
CREATE TABLE IF NOT EXISTS control_events (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL DEFAULT '',
    triggered_by TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT 'success',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ce_time ON control_events(created_at);

-- Daily risk counters
CREATE TABLE IF NOT EXISTS risk_counters (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    trades_today INTEGER NOT NULL DEFAULT 0,
    daily_pnl REAL NOT NULL DEFAULT 0.0,
    consecutive_losses INTEGER NOT NULL DEFAULT 0,
    max_drawdown REAL NOT NULL DEFAULT 0.0,
    max_drawdown_pct REAL NOT NULL DEFAULT 0.0,
    peak_pnl REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_date ON risk_counters(date);

-- Kill switch events (activation and reset history)
CREATE TABLE IF NOT EXISTS kill_switch_events (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    triggered_by TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- Notification log (Telegram, etc.)
CREATE TABLE IF NOT EXISTS notification_log (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL DEFAULT 'telegram',
    event_type TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'INFO',
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'sent',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def _now_utc() -> str:
    """Return ISO-8601 UTC timestamp string."""
    return datetime.utcnow().isoformat()


def _ensure_path(path: str) -> None:
    """Ensure parent directory for db file exists."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)


class DatabaseManager:
    """Thread-safe SQLite database manager for trading ops data.

    Opens a new connection per operation using the configured db_path.
    WAL mode is enabled at schema creation time.
    """

    _local = threading.local()

    def __init__(self, db_path: str = "ops_data.db") -> None:
        self.db_path = db_path
        _ensure_path(db_path)

    # ── Connection ───────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        conn = self._connect()
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return dict(row)

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = self._connect()
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def init_schema(self) -> None:
        """Create all tables and indexes if they don't exist."""
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)

            # Add kill switch columns to bot_status for existing databases
            for col in (
                "kill_switch_active INTEGER NOT NULL DEFAULT 0",
                "kill_switch_triggered_by TEXT",
                "kill_switch_triggered_at TEXT",
                "kill_switch_reason TEXT",
                "last_notification_at TEXT",
            ):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(f"ALTER TABLE bot_status ADD COLUMN {col}")

            # Add data_source to existing tables
            for table in ("normalized_signals", "execution_orders"):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN data_source TEXT NOT NULL DEFAULT 'production'"
                    )

            # Positions table (Phase 4)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    entry_price REAL NOT NULL DEFAULT 0.0,
                    current_price REAL NOT NULL DEFAULT 0.0,
                    realized_pnl REAL NOT NULL DEFAULT 0.0,
                    unrealized_pnl REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'open',
                    strategy_id TEXT DEFAULT '',
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_open_symbol ON positions(symbol) WHERE status = 'open'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)")

            conn.commit()
        finally:
            conn.close()

    # ── Webhook Alerts ──────────────────────────────────────────────────

    def insert_alert(self, alert: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO webhook_alerts
                   (id, alert_id, raw_payload, received_at, source_ip, authenticated, normalized_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    alert["id"],
                    alert.get("alert_id", ""),
                    json.dumps(alert.get("raw_payload", {})),
                    alert.get("received_at", _now_utc()),
                    alert.get("source_ip", ""),
                    1 if alert.get("authenticated") else 0,
                    alert.get("normalized_id"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_alert_by_alert_id(self, alert_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM webhook_alerts WHERE alert_id = ?", (alert_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_recent_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM webhook_alerts ORDER BY received_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Normalized Signals ──────────────────────────────────────────────

    def insert_signal(self, signal: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO normalized_signals
                   (id, webhook_alert_id, alert_id, symbol, side, strategy, timeframe,
                    price, signal_timestamp, reason, source, normalized_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal["id"],
                    signal.get("webhook_alert_id", ""),
                    signal.get("alert_id", ""),
                    signal.get("symbol", ""),
                    signal.get("side", "BUY"),
                    signal.get("strategy", ""),
                    signal.get("timeframe", ""),
                    signal.get("price", 0.0),
                    signal.get("signal_timestamp"),
                    signal.get("reason", ""),
                    signal.get("source", "webhook"),
                    signal.get("normalized_at", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_signals(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM normalized_signals ORDER BY normalized_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Validation Results ──────────────────────────────────────────────

    def insert_validation(self, validation: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO validation_results
                   (id, signal_id, passed, checks, rejection_reason, validated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    validation["id"],
                    validation.get("signal_id", ""),
                    1 if validation.get("passed") else 0,
                    json.dumps(validation.get("checks", [])),
                    validation.get("rejection_reason", ""),
                    validation.get("validated_at", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_validations(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM validation_results ORDER BY validated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_last_validation(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM validation_results ORDER BY validated_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── Execution Orders ────────────────────────────────────────────────

    def insert_order(self, order: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO execution_orders
                   (id, signal_id, validation_id, mode, symbol, side, quantity, price,
                    order_type, status, external_order_id, strategy, dedup_key,
                    error_message, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order["id"],
                    order.get("signal_id", ""),
                    order.get("validation_id", ""),
                    order.get("mode", "paper"),
                    order.get("symbol", ""),
                    order.get("side", "BUY"),
                    order.get("quantity", 0),
                    order.get("price", 0.0),
                    order.get("order_type", "LIMIT"),
                    order.get("status", "pending"),
                    order.get("external_order_id"),
                    order.get("strategy", ""),
                    order.get("dedup_key"),
                    order.get("error_message", ""),
                    order.get("created_at", _now_utc()),
                    order.get("updated_at"),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        finally:
            conn.close()

    def update_order(self, order_id: str, updates: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            updates["updated_at"] = _now_utc()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = [*list(updates.values()), order_id]
            conn.execute(
                f"UPDATE execution_orders SET {set_clause} WHERE id = ?", values
            )
            conn.commit()
        finally:
            conn.close()

    def get_order_by_dedup_key(self, dedup_key: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM execution_orders WHERE dedup_key = ?", (dedup_key,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_recent_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM execution_orders ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_last_order(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM execution_orders ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── Position Snapshots ──────────────────────────────────────────────

    def insert_position_snapshot(self, snap: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO position_snapshots
                   (id, symbol, side, quantity, entry_price, current_price,
                    unrealized_pnl, realized_pnl, trades_today, daily_pnl, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snap["id"],
                    snap.get("symbol", ""),
                    snap.get("side", "NONE"),
                    snap.get("quantity", 0),
                    snap.get("entry_price", 0.0),
                    snap.get("current_price", 0.0),
                    snap.get("unrealized_pnl", 0.0),
                    snap.get("realized_pnl", 0.0),
                    snap.get("trades_today", 0),
                    snap.get("daily_pnl", 0.0),
                    snap.get("timestamp", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_positions(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM position_snapshots ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_position_history(self, limit: int = 500) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM position_snapshots ORDER BY timestamp ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Bot Status ──────────────────────────────────────────────────────

    def upsert_bot_status(self, status: dict[str, Any]) -> None:
        """Upsert singleton bot status row (id=1)."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO bot_status
                   (id, status, mode, current_symbol, position_side, position_qty,
                    position_entry_price, trades_today, daily_pnl, cumulative_pnl,
                    wins_today, losses_today, max_drawdown_today, last_heartbeat_at,
                    last_alert_at, last_order_at, active_strategy, kite_connected,
                    kill_switch_active, kill_switch_triggered_by,
                    kill_switch_triggered_at, kill_switch_reason, last_notification_at,
                    updated_at)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?)""",
                (
                    status.get("status", "stopped"),
                    status.get("mode", "paper"),
                    status.get("current_symbol"),
                    status.get("position_side"),
                    status.get("position_qty", 0),
                    status.get("position_entry_price", 0.0),
                    status.get("trades_today", 0),
                    status.get("daily_pnl", 0.0),
                    status.get("cumulative_pnl", 0.0),
                    status.get("wins_today", 0),
                    status.get("losses_today", 0),
                    status.get("max_drawdown_today", 0.0),
                    status.get("last_heartbeat_at"),
                    status.get("last_alert_at"),
                    status.get("last_order_at"),
                    status.get("active_strategy"),
                    1 if status.get("kite_connected") else 0,
                    1 if status.get("kill_switch_active") else 0,
                    status.get("kill_switch_triggered_by"),
                    status.get("kill_switch_triggered_at"),
                    status.get("kill_switch_reason"),
                    status.get("last_notification_at"),
                    status.get("updated_at", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_bot_status(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM bot_status WHERE id = 1").fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── Bot Commands ────────────────────────────────────────────────────

    def insert_command(self, cmd: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO bot_commands
                   (id, command, params, issued_at, issued_by, status, result)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    cmd["id"],
                    cmd.get("command", ""),
                    json.dumps(cmd.get("params", {})),
                    cmd.get("issued_at", _now_utc()),
                    cmd.get("issued_by", ""),
                    cmd.get("status", "pending"),
                    cmd.get("result", ""),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_pending_commands(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM bot_commands WHERE status = 'pending' ORDER BY issued_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def ack_command(self, cmd_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE bot_commands SET status = 'acked', acked_at = ? WHERE id = ?",
                (_now_utc(), cmd_id),
            )
            conn.commit()
        finally:
            conn.close()

    def complete_command(self, cmd_id: str, result: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE bot_commands SET status = 'completed', completed_at = ?, result = ? WHERE id = ?",
                (_now_utc(), result, cmd_id),
            )
            conn.commit()
        finally:
            conn.close()

    def fail_command(self, cmd_id: str, error: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE bot_commands SET status = 'failed', completed_at = ?, result = ? WHERE id = ?",
                (_now_utc(), error, cmd_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_commands(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM bot_commands ORDER BY issued_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Health Checks ──────────────────────────────────────────────────

    def insert_health_check(self, check: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO health_checks
                   (id, component, status, detail, checked_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    check["id"],
                    check.get("component", ""),
                    check.get("status", "pass"),
                    check.get("detail", ""),
                    check.get("checked_at", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_health_checks(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM health_checks ORDER BY checked_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Heartbeats ──────────────────────────────────────────────────────

    def insert_heartbeat(self, hb: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO heartbeats
                   (id, bot_status, bot_mode, last_action, trades_today, daily_pnl,
                    kite_connected, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    hb["id"],
                    hb.get("bot_status", "stopped"),
                    hb.get("bot_mode", "paper"),
                    hb.get("last_action", ""),
                    hb.get("trades_today", 0),
                    hb.get("daily_pnl", 0.0),
                    1 if hb.get("kite_connected") else 0,
                    hb.get("timestamp", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_latest_heartbeat(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM heartbeats ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_recent_heartbeats(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM heartbeats ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Control Events ─────────────────────────────────────────────────

    def insert_control_event(self, event: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO control_events
                   (id, action, triggered_by, source, result, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["id"],
                    event.get("action", ""),
                    event.get("triggered_by", ""),
                    event.get("source", ""),
                    event.get("result", "success"),
                    event.get("detail", ""),
                    event.get("created_at", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM control_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Risk Counters ───────────────────────────────────────────────────

    def upsert_risk_counter(self, counter: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT * FROM risk_counters WHERE date = ?",
                (counter.get("date", ""),),
            ).fetchone()

            if existing:
                merged = dict(existing)
                for k in (
                    "trades_today",
                    "daily_pnl",
                    "consecutive_losses",
                    "max_drawdown",
                    "max_drawdown_pct",
                    "peak_pnl",
                ):
                    if k in counter:
                        merged[k] = counter[k]
                merged["updated_at"] = _now_utc()
                conn.execute(
                    """UPDATE risk_counters SET
                       trades_today=?, daily_pnl=?, consecutive_losses=?,
                       max_drawdown=?, max_drawdown_pct=?, peak_pnl=?, updated_at=?
                       WHERE date=?""",
                    (
                        merged["trades_today"],
                        merged["daily_pnl"],
                        merged["consecutive_losses"],
                        merged["max_drawdown"],
                        merged["max_drawdown_pct"],
                        merged["peak_pnl"],
                        merged["updated_at"],
                        merged["date"],
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO risk_counters
                       (id, date, trades_today, daily_pnl, consecutive_losses,
                        max_drawdown, max_drawdown_pct, peak_pnl, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        counter["id"],
                        counter.get("date", ""),
                        counter.get("trades_today", 0),
                        counter.get("daily_pnl", 0.0),
                        counter.get("consecutive_losses", 0),
                        counter.get("max_drawdown", 0.0),
                        counter.get("max_drawdown_pct", 0.0),
                        counter.get("peak_pnl", 0.0),
                        _now_utc(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_todays_risk_counter(self) -> dict[str, Any] | None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM risk_counters WHERE date = ?", (today,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── Positions (Phase 4) ──────────────────────────────────────────

    def upsert_open_position(self, symbol: str, side: str, quantity: int,
                             entry_price: float, strategy_id: str = "") -> str:
        """UPSERT an open position for a symbol. Returns the position id."""
        now = datetime.utcnow().isoformat()
        pos_id = str(uuid.uuid4())
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO positions (id, symbol, side, quantity, entry_price,
                    current_price, realized_pnl, unrealized_pnl, status,
                    strategy_id, opened_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'open', ?, ?, ?)
                ON CONFLICT(symbol) WHERE status = 'open'
                DO UPDATE SET
                    side = excluded.side,
                    quantity = excluded.quantity,
                    entry_price = excluded.entry_price,
                    current_price = excluded.current_price,
                    strategy_id = excluded.strategy_id,
                    updated_at = excluded.updated_at
            """, (pos_id, symbol, side, quantity, entry_price,
                  entry_price, strategy_id, now, now))
            conn.commit()
        finally:
            conn.close()
        return pos_id

    def close_position(self, symbol: str, exit_price: float) -> dict | None:
        """Close an open position. Computes and stores realized PnL.
        Returns None if no open position exists."""
        now = datetime.utcnow().isoformat()
        open_pos = self.get_position_by_symbol(symbol)
        if not open_pos:
            return None
        direction = 1 if open_pos["side"] == "LONG" else -1
        realized = (exit_price - open_pos["entry_price"]) * open_pos["quantity"] * direction
        conn = self._connect()
        try:
            conn.execute("""
                UPDATE positions SET
                    status = 'closed',
                    closed_at = ?,
                    quantity = 0,
                    current_price = ?,
                    realized_pnl = realized_pnl + ?,
                    updated_at = ?
                WHERE id = ? AND status = 'open'
            """, (now, exit_price, realized, now, open_pos["id"]))
            conn.commit()
        finally:
            conn.close()
        return self._fetch_one("SELECT * FROM positions WHERE id = ?", (open_pos["id"],))

    def reduce_position(self, symbol: str, reduce_qty: int, exit_price: float) -> dict | None:
        """Reduce an open position by given qty. Computes realized PnL on reduced portion.
        Delegates to close_position when reduce_qty >= quantity."""
        open_pos = self.get_position_by_symbol(symbol)
        if not open_pos:
            return None
        if reduce_qty >= open_pos["quantity"]:
            return self.close_position(symbol, exit_price)
        direction = 1 if open_pos["side"] == "LONG" else -1
        realized = (exit_price - open_pos["entry_price"]) * reduce_qty * direction
        new_qty = open_pos["quantity"] - reduce_qty
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            conn.execute("""
                UPDATE positions SET
                    quantity = ?,
                    current_price = ?,
                    realized_pnl = realized_pnl + ?,
                    updated_at = ?
                WHERE id = ? AND status = 'open'
            """, (new_qty, exit_price, realized, now, open_pos["id"]))
            conn.commit()
        finally:
            conn.close()
        return self._fetch_one("SELECT * FROM positions WHERE id = ?", (open_pos["id"],))

    def update_position_mtm(self, symbol: str, current_price: float) -> dict:
        """Update current_price and unrealized_pnl only. Never mutates realized_pnl."""
        open_pos = self.get_position_by_symbol(symbol)
        if not open_pos:
            raise ValueError(f"No open position for {symbol}")
        direction = 1 if open_pos["side"] == "LONG" else -1
        unrealized = (current_price - open_pos["entry_price"]) * open_pos["quantity"] * direction
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            conn.execute("""
                UPDATE positions SET
                    current_price = ?,
                    unrealized_pnl = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'open'
            """, (current_price, unrealized, now, open_pos["id"]))
            conn.commit()
        finally:
            conn.close()
        return self._fetch_one("SELECT * FROM positions WHERE id = ?", (open_pos["id"],))

    def get_position_by_symbol(self, symbol: str) -> dict | None:
        """Get open position for symbol, or None."""
        return self._fetch_one(
            "SELECT * FROM positions WHERE symbol = ? AND status = 'open'",
            (symbol,)
        )

    def get_all_open_positions(self) -> list[dict]:
        """Get all currently open positions."""
        return self._fetch_all(
            "SELECT * FROM positions WHERE status = 'open' ORDER BY symbol"
        )

    def get_closed_positions(self, limit: int = 50) -> list[dict]:
        """Get closed position history."""
        return self._fetch_all(
            "SELECT * FROM positions WHERE status = 'closed' ORDER BY closed_at DESC LIMIT ?",
            (limit,)
        )

    def insert_position_snapshot_for_compat(self, symbol: str, side: str,
                                             quantity: int, entry_price: float,
                                             current_price: float,
                                             realized_pnl: float,
                                             unrealized_pnl: float) -> None:
        """Write a position_snapshot row for equity curve continuity (backward compat)."""
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO position_snapshots
                    (id, symbol, side, quantity, entry_price, current_price,
                     unrealized_pnl, realized_pnl, trades_today, daily_pnl, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            """, (str(uuid.uuid4()), symbol, side, quantity, entry_price,
                  current_price, unrealized_pnl, realized_pnl,
                  datetime.utcnow().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def update_bot_status_position_compat(self, symbol: str, side: str,
                                           quantity: int, entry_price: float) -> None:
        """Update bot_status singleton with primary position for legacy dashboard compat."""
        status = self.get_bot_status() or {}
        status["current_symbol"] = symbol
        status["position_side"] = side
        status["position_qty"] = quantity
        status["position_entry_price"] = entry_price
        self.upsert_bot_status(status)

    # ── Aggregation Queries ─────────────────────────────────────────────

    def get_equity_curve(self, limit: int = 500) -> list[dict[str, Any]]:
        """Get cumulative P&L over time from position snapshots."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT timestamp, daily_pnl, realized_pnl
                   FROM position_snapshots
                   ORDER BY timestamp ASC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_todays_trade_count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT trades_today FROM bot_status WHERE id = 1"
            ).fetchone()
            return row["trades_today"] if row else 0
        finally:
            conn.close()

    def get_recent_errors(self, limit: int = 20) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT detail FROM control_events
                   WHERE result = 'failure' OR action = 'error'
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [r["detail"] for r in rows]
        finally:
            conn.close()

    # ── Analytics Queries ───────────────────────────────────────────

    def get_pnl_by_strategy(self, limit: int = 1000) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT strategy, side, price, status, created_at
                   FROM execution_orders WHERE data_source = 'production'
                   ORDER BY created_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_rejection_stats(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT rejection_reason, COUNT(*) as count
                   FROM validation_results WHERE passed = 0
                   GROUP BY rejection_reason ORDER BY count DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_execution_events(self, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT eo.*, vr.rejection_reason, vr.passed as validation_passed
                   FROM execution_orders eo
                   LEFT JOIN validation_results vr ON vr.signal_id = eo.signal_id
                   WHERE eo.data_source = 'production'
                   ORDER BY eo.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_daily_pnl_history(self, limit: int = 30) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT date, daily_pnl, trades_today, consecutive_losses
                   FROM risk_counters ORDER BY date DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Kill Switch ────────────────────────────────────────────────────

    def get_kill_switch_state(self) -> dict[str, Any]:
        """Return current kill switch state with defaults if not set."""
        status = self.get_bot_status()
        if status is None:
            return {
                "active": False,
                "triggered_by": "",
                "triggered_at": None,
                "reason": "",
            }
        return {
            "active": bool(status.get("kill_switch_active", 0)),
            "triggered_by": status.get("kill_switch_triggered_by") or "",
            "triggered_at": status.get("kill_switch_triggered_at"),
            "reason": status.get("kill_switch_reason") or "",
        }

    def insert_kill_switch_event(self, event: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO kill_switch_events
                   (id, action, triggered_by, reason, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event["id"],
                    event.get("action", ""),
                    event.get("triggered_by", ""),
                    event.get("reason", ""),
                    event.get("created_at", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_kill_switch_history(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM kill_switch_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Notification Log ───────────────────────────────────────────────

    def insert_notification_log(self, log: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO notification_log
                   (id, channel, event_type, severity, message, status, error_message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    log["id"],
                    log.get("channel", "telegram"),
                    log.get("event_type", ""),
                    log.get("severity", "INFO"),
                    log.get("message", ""),
                    log.get("status", "sent"),
                    log.get("error_message", ""),
                    log.get("created_at", _now_utc()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_notifications(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM notification_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Maintenance ─────────────────────────────────────────────────────

    def wal_checkpoint(self) -> None:
        """Run WAL checkpoint to keep the WAL file small."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass  # In-memory DB or other transient issue
        finally:
            conn.close()

    def delete_old_data(self, days: int = 90) -> dict[str, int]:
        """Delete data older than `days` from high-volume tables.

        Returns dict of table_name -> rows_deleted.
        Uses separate transactions per table for safety.
        """
        counts: dict[str, int] = {}
        tables = {
            "heartbeats": "timestamp",
            "health_checks": "checked_at",
            "control_events": "created_at",
            "notification_log": "created_at",
            "kill_switch_events": "created_at",
        }
        for table, ts_col in tables.items():
            conn = self._connect()
            try:
                deleted = conn.execute(
                    f"DELETE FROM {table} WHERE {ts_col} < date('now', '-{days} days')"
                ).rowcount
                conn.commit()
                counts[table] = deleted
            except sqlite3.OperationalError:
                counts[table] = -1
            finally:
                conn.close()

        # Also prune raw payloads that are very old
        conn = self._connect()
        try:
            deleted = conn.execute(
                "DELETE FROM webhook_alerts WHERE received_at < date('now', '-{days} days')"
            ).rowcount
            conn.commit()
            counts["webhook_alerts"] = deleted
        except sqlite3.OperationalError:
            counts["webhook_alerts"] = -1
        finally:
            conn.close()

        return counts

    def vacuum(self) -> None:
        """Recover disk space. Run after bulk deletes outside peak hours."""
        conn = self._connect()
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    # ── Strategy Performance ───────────────────────────────────────────

    def get_strategy_performance(self) -> list[dict[str, Any]]:
        """Aggregate PnL and trade stats per strategy from execution_orders.

        Only considers filled orders with data_source='production'.
        Net PnL per order: BUY side = -(price * qty), SELL side = +(price * qty).
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT strategy, side, price, quantity, status
                   FROM execution_orders
                   WHERE status = 'filled' AND data_source = 'production'
                   ORDER BY strategy"""
            ).fetchall()
        finally:
            conn.close()

        from collections import defaultdict
        agg: dict[str, dict] = defaultdict(lambda: {
            "trade_count": 0, "net_pnl": 0.0, "wins": 0, "losses": 0,
            "buy_count": 0, "sell_count": 0, "total_buy_value": 0.0, "total_sell_value": 0.0,
        })
        for r in rows:
            d = dict(r)
            strat = d["strategy"]
            pnl_contrib = d["price"] * d["quantity"]
            agg[strat]["trade_count"] += 1
            if d["side"] == "BUY":
                pnl_contrib = -pnl_contrib
                agg[strat]["buy_count"] += 1
                agg[strat]["total_buy_value"] += d["price"] * d["quantity"]
            else:
                agg[strat]["sell_count"] += 1
                agg[strat]["total_sell_value"] += d["price"] * d["quantity"]
            agg[strat]["net_pnl"] += pnl_contrib
            if pnl_contrib > 0:
                agg[strat]["wins"] += 1
            else:
                agg[strat]["losses"] += 1

        results = []
        for strat, data in sorted(agg.items(), key=lambda x: x[1]["net_pnl"], reverse=True):
            results.append({"strategy": strat, **data})
        return results

    # ── Current Positions ──────────────────────────────────────────────

    def get_current_positions(self) -> list[dict[str, Any]]:
        """Get the latest position snapshot per symbol with quantity > 0."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT ps.* FROM position_snapshots ps
                   INNER JOIN (
                       SELECT symbol, MAX(timestamp) as max_ts
                       FROM position_snapshots GROUP BY symbol
                   ) latest ON ps.symbol = latest.symbol AND ps.timestamp = latest.max_ts
                   WHERE ps.quantity > 0
                   ORDER BY ps.symbol"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Portfolio Summary ──────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict[str, Any]:
        """Aggregate portfolio-level metrics from current positions."""
        positions = self.get_current_positions()
        if not positions:
            return {
                "positions": [], "total_exposure": 0.0, "total_unrealized_pnl": 0.0,
                "total_realized_pnl": 0.0, "position_count": 0,
                "largest_position_symbol": "", "largest_position_pct": 0.0,
                "updated_at": "",
            }
        total_exposure = sum(p["quantity"] * p["current_price"] for p in positions)
        total_unrealized = sum(p["unrealized_pnl"] for p in positions)
        total_realized = sum(p["realized_pnl"] for p in positions)
        largest = max(positions, key=lambda p: p["quantity"] * p["current_price"])
        largest_exposure = largest["quantity"] * largest["current_price"]
        largest_pct = (largest_exposure / total_exposure * 100) if total_exposure else 0.0
        latest_ts = max(p["timestamp"] for p in positions) if positions else ""
        return {
            "positions": positions,
            "total_exposure": round(total_exposure, 2),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_realized_pnl": round(total_realized, 2),
            "position_count": len(positions),
            "largest_position_symbol": largest["symbol"],
            "largest_position_pct": round(largest_pct, 2),
            "updated_at": latest_ts,
        }
