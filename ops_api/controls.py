"""Control endpoints — safe bot management with auth and audit trail.

All control actions are:
  - Authenticated (API key required in headers)
  - Audited (logged to control_events table)
  - Communicated to the bot via the bot_commands table
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from ops_api.db import DatabaseManager


def _utcnow() -> str:
    return datetime.utcnow().isoformat()


def _generate_id() -> str:
    import uuid

    return str(uuid.uuid4())


SUPPORTED_ACTIONS = frozenset(
    {
        "start",
        "stop",
        "pause",
        "resume",
        "flatten",
        "set_mode",
        "reload_config",
        "kill",
        "reset_kill",
    }
)


def handle_control_action(
    action: str,
    db: DatabaseManager,
    triggered_by: str = "",
    source: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a control action and store the audit trail.

    Args:
        action: One of ``start``, ``stop``, ``pause``, ``resume``,
                ``flatten``, ``set_mode``, ``reload_config``.
        db: Database manager instance.
        triggered_by: Who triggered the action.
        source: ``"web"``, ``"dashboard"``, or ``"system"``.
        params: Optional parameters (e.g. ``{"mode": "live"}`` for set_mode).

    Returns:
        Dict with action result.
    """
    if action not in SUPPORTED_ACTIONS:
        return {
            "status": "error",
            "action": action,
            "message": f"Unsupported action: {action}",
        }

    params = params or {}
    cmd_id = _generate_id()

    # 1. Write command to bot_commands table for bot to pick up
    db.insert_command(
        {
            "id": cmd_id,
            "command": action,
            "params": params,
            "issued_at": _utcnow(),
            "issued_by": triggered_by or "api",
            "status": "pending",
            "result": "",
        }
    )

    # 2. For set_mode, also update bot_status immediately
    if action == "set_mode" and "mode" in params:
        new_mode = params["mode"]
        status = db.get_bot_status()
        current_mode = status.get("mode", "paper") if status else "paper"
        db.upsert_bot_status(
            {
                "status": status.get("status", "stopped") if status else "stopped",
                "mode": new_mode,
            }
        )
        detail = f"Mode changed: {current_mode} -> {new_mode}"
    elif action == "pause":
        status = db.get_bot_status()
        current_status = status.get("status", "stopped") if status else "stopped"
        db.upsert_bot_status(
            {
                "status": "paused",
                "mode": status.get("mode", "paper") if status else "paper",
            }
        )
        detail = f"Bot paused (was: {current_status})"
    elif action == "resume":
        status = db.get_bot_status()
        db.upsert_bot_status(
            {
                "status": "running",
                "mode": status.get("mode", "paper") if status else "paper",
            }
        )
        detail = "Bot resumed"
    elif action == "stop":
        status = db.get_bot_status()
        db.upsert_bot_status(
            {
                "status": "stopped",
                "mode": status.get("mode", "paper") if status else "paper",
            }
        )
        detail = "Bot stop command issued"
    elif action == "start":
        db.upsert_bot_status({"status": "starting", "mode": "paper"})
        detail = "Bot start command issued"
    elif action == "flatten":
        detail = "Flatten command issued"
    elif action == "reload_config":
        detail = "Config reload command issued"
    elif action == "kill":
        ks_reason = params.get("reason", "manual activation")
        now_ts = _utcnow()
        db.upsert_bot_status(
            {
                "status": "paused",
                "kill_switch_active": True,
                "kill_switch_triggered_by": triggered_by or "api",
                "kill_switch_triggered_at": now_ts,
                "kill_switch_reason": ks_reason,
            }
        )
        db.insert_kill_switch_event(
            {
                "id": cmd_id,
                "action": "activate",
                "triggered_by": triggered_by or "api",
                "reason": ks_reason,
                "created_at": now_ts,
            }
        )
        detail = f"Kill switch activated by {triggered_by or 'api'}: {ks_reason}"
    elif action == "reset_kill":
        now_ts = _utcnow()
        status = db.get_bot_status()
        db.upsert_bot_status(
            {
                "status": status.get("status", "stopped") if status else "stopped",
                "mode": status.get("mode", "paper") if status else "paper",
                "kill_switch_active": False,
                "kill_switch_triggered_by": None,
                "kill_switch_triggered_at": None,
                "kill_switch_reason": None,
            }
        )
        db.insert_kill_switch_event(
            {
                "id": cmd_id,
                "action": "reset",
                "triggered_by": triggered_by or "api",
                "reason": params.get("reason", "manual reset"),
                "created_at": now_ts,
            }
        )
        detail = f"Kill switch reset by {triggered_by or 'api'}"
    else:
        detail = f"Action {action} executed"

    # 3. Log to control_events
    db.insert_control_event(
        {
            "id": cmd_id,
            "action": action,
            "triggered_by": triggered_by or "api",
            "source": source or "web",
            "result": "success",
            "detail": detail,
            "created_at": _utcnow(),
        }
    )

    logger.info(
        "Control action: {} by {} from {} — {}",
        action,
        triggered_by or "api",
        source or "web",
        detail,
    )

    return {
        "status": "success",
        "action": action,
        "command_id": cmd_id,
        "message": detail,
    }
