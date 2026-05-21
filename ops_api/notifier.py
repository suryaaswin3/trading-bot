"""Telegram notification system for operational monitoring.

Async-safe, non-blocking, with retry and dedup.
Telegram failures NEVER crash the trading process.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from ops_api.db import DatabaseManager
from ops_api.models import BotMode, BotStatusValue

logger = logging.getLogger("ops_api.notifier")

ENDPOINT = "https://api.telegram.org/bot{token}/sendMessage"

_SEVERITY_EMOJI = {
    "CRITICAL": "‼️",  # ‼️
    "ERROR": "❌",  # ❌
    "WARNING": "⚠️",  # ⚠️
    "INFO": "ℹ️",  # ℹ️
}


def _decorate(severity: str, text: str) -> str:
    emoji = _SEVERITY_EMOJI.get(severity, "")
    return f"{emoji} {severity}\n{text}\nTime: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"  # noqa: E501


def _msg_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


class TelegramNotifier:
    """Async Telegram bot notifier with retry, dedup, and rate-limiting.

    Usage:
        notifier = TelegramNotifier(bot_token, chat_id, db)
        await notifier.send("Order filled", "INFO")
    """

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        db: DatabaseManager | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)
        self._db = db
        self._last_msg_time: float = 0
        self._last_hash: str = ""
        self._min_interval = 1.0  # seconds between sends
        self._dedup_window = 30.0  # skip identical messages within 30s
        self._per_type_last: dict[str, float] = {}  # event_type -> last send time
        self._per_type_min_interval = 30.0  # min seconds between same event_type
        self._http = httpx.AsyncClient(timeout=10.0)
        self._healthy = True
        self._last_success: float = 0

    @property
    def healthy(self) -> bool:
        return self._healthy

    async def send(
        self,
        message: str,
        severity: str = "INFO",
        event_type: str = "",
    ) -> bool:
        """Send a Telegram message. Never raises. Logs failures."""
        if not self._enabled:
            return False

        text = _decorate(severity, message)

        # ── Rate limit (global) ────────────────────────────────────
        now = time.time()
        elapsed = now - self._last_msg_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)

        # ── Per-type rate limit (prevents spam on same event) ──────
        if event_type:
            last_type = self._per_type_last.get(event_type, 0.0)
            if now - last_type < self._per_type_min_interval:
                logger.debug("Notification dedup: {} suppressed (per-type)", event_type)
                return True
            self._per_type_last[event_type] = now

        # ── Content dedup ───────────────────────────────────────────
        h = _msg_hash(text)
        if h == self._last_hash and (now - self._last_msg_time) < self._dedup_window:
            logger.debug("Telegram dedup: skipping duplicate message")
            return True

        # ── Send with retry ─────────────────────────────────────────
        url = ENDPOINT.format(token=self._token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        last_error = ""
        for attempt in range(3):
            try:
                resp = await self._http.post(url, json=payload)
                if resp.status_code == 200:
                    self._last_msg_time = now
                    self._last_hash = h
                    self._healthy = True
                    self._last_success = now
                    self._log("telegram", event_type, severity, message, "sent")
                    return True

                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if resp.status_code in (401, 403):
                    break  # auth error, retry won't help

            except httpx.TimeoutException:
                last_error = "timeout"
            except httpx.ConnectError:
                last_error = "connection failed"
            except Exception as e:
                last_error = str(e)

            if attempt < 2:
                await asyncio.sleep(2**attempt)

        # ── All retries exhausted ──────────────────────────────────
        self._healthy = False
        self._log("telegram", event_type, severity, message, "failed", last_error)
        logger.error("Telegram send failed: %s", last_error)
        return False

    def send_sync(
        self,
        message: str,
        severity: str = "INFO",
        event_type: str = "",
    ) -> bool:
        """Synchronous wrapper for non-async contexts. Fire-and-forget."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.send(message, severity, event_type))
                return True
            return loop.run_until_complete(self.send(message, severity, event_type))
        except RuntimeError:
            # No event loop running — create one
            return asyncio.run(self.send(message, severity, event_type))
        except Exception:
            logger.exception("Telegram sync send failed")
            return False

    def _log(
        self,
        channel: str,
        event_type: str,
        severity: str,
        message: str,
        status: str,
        error: str = "",
    ) -> None:
        """Persist notification to DB (best-effort)."""
        if self._db is None:
            return
        import uuid

        try:
            ts = datetime.utcnow().isoformat()
            self._db.insert_notification_log(
                {
                    "id": str(uuid.uuid4()),
                    "channel": channel,
                    "event_type": event_type,
                    "severity": severity,
                    "message": message[:500],
                    "status": status,
                    "error_message": error[:500],
                    "created_at": ts,
                }
            )
        except Exception:
            pass

    def alert_trade(
        self,
        event: str,
        symbol: str,
        side: str,
        price: float,
        qty: int,
        mode: str = "paper",
        order_id: str = "",
    ) -> bool:
        """Convenience: send a trading notification."""
        msg = (
            f"{event}\n"
            f"Symbol: {symbol}\n"
            f"Side: {side}\n"
            f"Price: {price}\n"
            f"Qty: {qty}\n"
            f"Mode: {mode.upper()}"
        )
        if order_id:
            msg += f"\nOrder: {order_id}"
        sev = "ERROR" if "REJECTED" in event or "FAILED" in event else "INFO"
        return self.send_sync(msg, sev, event)

    def alert_system(
        self,
        event: str,
        detail: str = "",
        severity: str = "INFO",
    ) -> bool:
        """Convenience: send a system notification."""
        msg = event
        if detail:
            msg += f"\nDetail: {detail}"
        return self.send_sync(msg, severity, event)

    # ── Phase 6 production alerts ──────────────────────────────────────────

    def alert_live_warning(self) -> bool:
        """CRITICAL alert when LIVE_TRADING is enabled.

        Must be called at startup — this is the safety gate that makes
        ``OA_LIVE_TRADING=true`` impossible to miss in the logs.
        """
        msg = (
            "🚨 LIVE TRADING IS ENABLED\n"
            "Real money execution is active.\n"
            "Kill switch available at POST /control/kill"
        )
        return self.send_sync(msg, "CRITICAL", "live_trading")

    def alert_shutdown(self, reason: str = "graceful shutdown") -> bool:
        """INFO alert on graceful shutdown."""
        return self.send_sync(
            f"Bot shutting down\nReason: {reason}",
            "INFO",
            "shutdown",
        )

    def alert_crash(self, error: str = "", traceback: str = "") -> bool:
        """ERROR alert when the process crashes unexpectedly."""
        msg = f"Bot crashed!\nError: {error[:200] if error else 'unknown'}"
        if traceback:
            # Last 10 lines of traceback (Telegram has 4096 char limit)
            tb_lines = traceback.strip().split("\n")
            tb_trim = "\n".join(tb_lines[-10:])
            msg += f"\n{tb_trim[:1500]}"
        return self.send_sync(msg, "ERROR", "crash")

    def alert_daily_summary(
        self,
        date: str = "",
        trades: int = 0,
        wins: int = 0,
        losses: int = 0,
        pnl: float = 0.0,
        drawdown: float = 0.0,
        status: str = "ACTIVE",
    ) -> bool:
        """INFO daily summary with key session metrics.

        Call at market close or at scheduled daily summary time.
        """
        winrate = (wins / trades * 100) if trades > 0 else 0.0
        msg = (
            f"📊 Daily Summary — {date or 'today'}\n"
            f"Status: {status}\n"
            f"Trades: {trades} (W: {wins} / L: {losses})\n"
            f"Win rate: {winrate:.1f}%\n"
            f"PnL: {pnl:+.2f}\n"
            f"Drawdown: {drawdown:.2f}"
        )
        return self.send_sync(msg, "INFO", "daily_summary")

    async def close(self) -> None:
        await self._http.aclose()


# ── Helper to build a notifier from config ────────────────────────────────


def create_notifier(config: Any, db: DatabaseManager | None = None) -> TelegramNotifier:
    """Build a notifier from an OpsApiConfig-like object."""
    token = getattr(config, "telegram_bot_token", "") or ""
    chat_id = getattr(config, "telegram_chat_id", "") or ""
    return TelegramNotifier(token, chat_id, db)
