"""Health checks and heartbeat management for the trading ops stack."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from ops_api.db import DatabaseManager

_UTC_STR = "%Y-%m-%dT%H:%M:%S.%fZ"
_STALE_SECONDS = 300  # heartbeat older than this is considered stale
HEARTBEAT_FILE = "/tmp/trading-bot-heartbeat.txt"


def _utcnow() -> str:
    return datetime.utcnow().isoformat()


def _generate_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _heartbeat_age_seconds(status: dict[str, Any] | None) -> int | None:
    """Compute heartbeat age from bot_status dict. Returns None if unknown."""
    if status is None:
        return None
    ts = status.get("last_heartbeat_at")
    if not ts:
        return None
    try:
        hb_dt = datetime.fromisoformat(ts)
        return int((datetime.utcnow() - hb_dt).total_seconds())
    except (ValueError, TypeError):
        return None


def check_database(db: DatabaseManager) -> dict[str, Any]:
    """Verify database is readable and writable."""
    try:
        db.init_schema()
        db.get_bot_status()
        return {"component": "database", "status": "pass", "detail": "OK"}
    except Exception as e:
        return {"component": "database", "status": "fail", "detail": str(e)}


def check_api(db: DatabaseManager) -> dict[str, Any]:
    """Verify API responds — always pass on reachable call."""
    return {"component": "api_server", "status": "pass", "detail": "OK"}


def check_config(has_config: bool) -> dict[str, Any]:
    """Verify config loaded OK."""
    if has_config:
        return {"component": "config_load", "status": "pass", "detail": "OK"}
    return {"component": "config_load", "status": "fail", "detail": "Config not loaded"}


def check_bot(db: DatabaseManager) -> dict[str, Any]:
    """Verify bot process status from DB with heartbeat freshness awareness."""
    status = db.get_bot_status()
    if status is None:
        return {"component": "bot_process", "status": "warn", "detail": "No bot status record yet"}

    bot_state = status.get("status", "unknown")
    age = _heartbeat_age_seconds(status)

    if age is not None and age > _STALE_SECONDS:
        return {
            "component": "bot_process",
            "status": "warn",
            "detail": f"Bot state: {bot_state}, heartbeat {age}s stale",
        }

    return {"component": "bot_process", "status": "pass", "detail": f"Bot state: {bot_state}"}


def check_kite(db: DatabaseManager) -> dict[str, Any]:
    """Report Kite connection status with staleness awareness."""
    hb = db.get_latest_heartbeat()
    if hb is None:
        status = db.get_bot_status()
        if status and status.get("kite_connected"):
            age = _heartbeat_age_seconds(status)
            if age is not None and age > _STALE_SECONDS:
                return {
                    "component": "kite_connect",
                    "status": "warn",
                    "detail": "Kite status unknown — heartbeat {age}s stale".format(age=age),
                }
        return {"component": "kite_connect", "status": "warn", "detail": "No heartbeat data"}

    kite_val = bool(hb.get("kite_connected", False))
    ts = hb.get("timestamp", "")
    age = None
    if ts:
        try:
            hb_dt = datetime.fromisoformat(ts)
            age = int((datetime.utcnow() - hb_dt).total_seconds())
        except (ValueError, TypeError):
            pass

    if age is not None and age > _STALE_SECONDS:
        return {
            "component": "kite_connect",
            "status": "warn",
            "detail": "Heartbeat {age}s stale".format(age=age),
        }

    if kite_val:
        return {"component": "kite_connect", "status": "pass", "detail": "Connected"}
    return {"component": "kite_connect", "status": "fail", "detail": "Disconnected"}


def check_kill_switch(db: DatabaseManager) -> dict[str, Any]:
    """Report kill switch state."""
    ks = db.get_kill_switch_state()
    if ks.get("active", False):
        return {
            "component": "kill_switch",
            "status": "warn",
            "detail": "ACTIVE — triggered by: {triggered_by}, reason: {reason}".format(
                triggered_by=ks["triggered_by"], reason=ks["reason"]
            ),
        }
    return {"component": "kill_switch", "status": "pass", "detail": "Inactive"}


def check_telegram(
    notifier_healthy: bool | None = None,
) -> dict[str, Any]:
    """Report Telegram notifier health."""
    if notifier_healthy is None:
        return {"component": "telegram", "status": "pass", "detail": "Not configured"}
    if notifier_healthy:
        return {"component": "telegram", "status": "pass", "detail": "Healthy"}
    return {"component": "telegram", "status": "warn", "detail": "Last send failed"}


_HEALTH_COUNTER = 0


def run_health_checks(
    db: DatabaseManager,
    config_loaded: bool = True,
    telegram_healthy: bool | None = None,
) -> list[dict[str, Any]]:
    """Run all health checks and return results."""
    global _HEALTH_COUNTER
    _HEALTH_COUNTER += 1

    results = [
        check_api(db),
        check_database(db),
        check_config(config_loaded),
        check_bot(db),
        check_kill_switch(db),
        check_kite(db),
        check_telegram(telegram_healthy),
    ]

    for r in results:
        r["id"] = _generate_id()
        r["checked_at"] = _utcnow()
        db.insert_health_check(r)

    for r in results:
        if r["status"] == "fail":
            logger.error("Health check FAIL: {} — {}", r["component"], r["detail"])
        elif r["status"] == "warn":
            logger.warning("Health check WARN: {} — {}", r["component"], r["detail"])

    if _HEALTH_COUNTER % 10 == 0:
        db.wal_checkpoint()

    return results


def write_heartbeat(
    db: DatabaseManager,
    bot_status: str = "stopped",
    bot_mode: str = "paper",
    last_action: str = "",
    trades_today: int = 0,
    daily_pnl: float = 0.0,
    kite_connected: bool = False,
) -> None:
    """Write a heartbeat record to DB and optional file."""
    hb = {
        "id": _generate_id(),
        "bot_status": bot_status,
        "bot_mode": bot_mode,
        "last_action": last_action,
        "trades_today": trades_today,
        "daily_pnl": daily_pnl,
        "kite_connected": 1 if kite_connected else 0,
        "timestamp": _utcnow(),
    }
    db.insert_heartbeat(hb)

    db.upsert_bot_status(
        {
            "status": bot_status,
            "mode": bot_mode,
            "last_heartbeat_at": _utcnow(),
            "trades_today": trades_today,
            "daily_pnl": daily_pnl,
            "kite_connected": kite_connected,
        }
    )

    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(
                f"{_utcnow()} | {bot_status} | {bot_mode} | trades={trades_today} | pnl={daily_pnl:.2f}\n"
            )
    except OSError:
        pass
