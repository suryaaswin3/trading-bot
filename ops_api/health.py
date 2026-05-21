"""Health checks and heartbeat management for the trading ops stack."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from ops_api.db import DatabaseManager
from ops_api.scan_metrics import ScanMetrics

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


def check_scanner(
    scheduler_running: bool | None = None,
    scan_metrics: ScanMetrics | None = None,
    scanner_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Report scanner engine health and metrics.

    When *scanner_status* is provided (from the ``scanner_status`` DB table),
    its data takes precedence — this is how the API process monitors the
    standalone scanner process across process boundaries.
    """
    # If we have scanner_status from the DB (standalone scanner process)
    if scanner_status is not None:
        status = scanner_status.get("status", "unknown")
        tick_count = scanner_status.get("tick_count", 0)
        error_count = scanner_status.get("error_count", 0)
        market_phase = scanner_status.get("market_phase", "")
        last_tick_at = scanner_status.get("last_tick_at", "")
        uptime = scanner_status.get("uptime_seconds", 0)

        if status == "running":
            # Check if the last tick is stale
            stale = False
            if last_tick_at:
                try:
                    delta = (datetime.utcnow() - datetime.fromisoformat(last_tick_at)).total_seconds()
                    if delta > _STALE_SECONDS:
                        stale = True
                except (ValueError, TypeError):
                    pass
            if stale:
                return {
                    "component": "scanner_engine",
                    "status": "warn",
                    "detail": f"Scanner heartbeat stale (last tick {last_tick_at})",
                }
            return {
                "component": "scanner_engine",
                "status": "pass",
                "detail": (
                    f"Scanner running | ticks={tick_count} errors={error_count} "
                    f"phase={market_phase} uptime={uptime:.0f}s"
                ),
            }
        elif status == "stopped":
            return {"component": "scanner_engine", "status": "warn", "detail": "Scanner process is stopped"}
        elif status == "error":
            return {"component": "scanner_engine", "status": "fail", "detail": f"Scanner in error state ({error_count} errors)"}
        return {"component": "scanner_engine", "status": "warn", "detail": f"Scanner status: {status}"}

    # Fallback: use the old scheduler_running / scan_metrics approach
    if scheduler_running is None:
        return {"component": "scanner_engine", "status": "pass", "detail": "Scanner not configured"}
    if not scheduler_running:
        return {"component": "scanner_engine", "status": "warn", "detail": "Scanner scheduler not running"}
    parts = ["Scanner running"]
    if scan_metrics is not None:
        m = scan_metrics.snapshot()
        parts.append(f"scans={m['total_scans']} signals={m['signals_found']} cache_hit={m['cache_hit_rate']:.0%}")
    return {"component": "scanner_engine", "status": "pass", "detail": " | ".join(parts)}


def check_memory() -> dict[str, Any]:
    """Read RSS memory usage from ``/proc/self/status`` (Linux only)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        kb = int(parts[1])
                        mb = kb / 1024
                        return {"component": "memory", "status": "pass", "detail": f"RSS {mb:.0f} MB"}
                    break
        return {"component": "memory", "status": "pass", "detail": "RSS not available"}
    except (FileNotFoundError, IOError, ValueError):
        return {"component": "memory", "status": "pass", "detail": "Not available (non-Linux)"}


_HEALTH_COUNTER = 0


def run_health_checks(
    db: DatabaseManager,
    config_loaded: bool = True,
    telegram_healthy: bool | None = None,
    scheduler_running: bool | None = None,
    scan_metrics: ScanMetrics | None = None,
    scanner_status: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run all health checks and return results."""
    global _HEALTH_COUNTER
    _HEALTH_COUNTER += 1

    results = [
        check_api(db),
        check_database(db),
        check_config(config_loaded),
        check_bot(db),
        check_memory(),
        check_kill_switch(db),
        check_kite(db),
        check_telegram(telegram_healthy),
        check_scanner(scheduler_running, scan_metrics, scanner_status),
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
