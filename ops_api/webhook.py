"""TradingView webhook ingestion — secure receipt, dedup, normalization.

Flow:
  1. Receive POST from TradingView
  2. Verify auth (secret match OR HMAC)
  3. Reject malformed payloads
  4. Check idempotency key (alert_id)
  5. Normalize into internal signal model
  6. Store raw + normalized to DB
  7. Pass to validation layer
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import time
from datetime import datetime
from typing import Any

from loguru import logger

from ops_api.db import DatabaseManager
from ops_api.models import NormalizedSignal, SignalSide
from ops_api.sensitive import redact_dict, sanitize_payload_for_storage

_UTC_STR = "%Y-%m-%dT%H:%M:%S.%fZ"

# ── Rate limiting (in-memory token bucket) ──────────────────────────────
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX = 10  # requests per window per IP
_RATE_LIMIT_BURST = 3
_RATE_LOG_COOLDOWN = 60.0  # seconds between rate-limit log messages per IP
_buckets: dict[str, tuple[float, int]] = {}  # ip -> (window_start, count)
_rate_logs: dict[str, float] = {}  # ip -> last_log_time
_LOCALHOST_PREFIXES = ("127.", "::1", "localhost")


def _check_rate_limit(source_ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited.

    Exempt localhost / internal IPs entirely.
    """
    if any(source_ip.startswith(p) for p in _LOCALHOST_PREFIXES):
        return True

    now = time.monotonic()
    window_start, count = _buckets.get(source_ip, (now, 0))

    if now - window_start > _RATE_LIMIT_WINDOW:
        window_start = now
        count = 0

    count += 1
    _buckets[source_ip] = (window_start, count)

    allowed = count <= _RATE_LIMIT_MAX + _RATE_LIMIT_BURST
    if not allowed:
        last_log = _rate_logs.get(source_ip, 0.0)
        if now - last_log > _RATE_LOG_COOLDOWN:
            logger.warning("Rate limit exceeded for IP={}", source_ip)
            _rate_logs[source_ip] = now

    return allowed


def _utcnow() -> str:
    return datetime.utcnow().isoformat()


def _generate_id() -> str:
    import uuid

    return str(uuid.uuid4())


# ── Auth ─────────────────────────────────────────────────────────────────


def verify_webhook_secret(
    payload: dict[str, Any],
    secret: str,
    signature_header: str | None = None,
    raw_body: bytes | None = None,
) -> bool:
    """Verify webhook authenticity.

    Two methods (checked in order):
    1. **HMAC header** — If ``signature_header`` and ``raw_body`` are provided,
       compute HMAC-SHA256 of the body and compare (timing-safe).
    2. **JSON secret** — Compare ``payload.get('secret')`` against the stored
       secret (constant-time-ish).

    Returns ``True`` if either method passes.
    """
    if not secret:
        return True  # no secret configured → allow (dev mode)

    # Method 1: HMAC signature
    if signature_header and raw_body:
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(signature_header, expected):
            return True
        logger.warning("Webhook HMAC signature mismatch")

    # Method 2: JSON body secret
    body_secret = payload.get("secret", "")
    if body_secret and body_secret == secret:
        return True

    if body_secret:
        logger.warning("Webhook JSON secret mismatch")
        return False

    return False


# ── Payload Validation ───────────────────────────────────────────────────


def validate_payload(payload: dict[str, Any]) -> list[str]:
    """Check required fields. Returns list of error strings (empty = valid)."""
    errors: list[str] = []
    required_fields = {"alert_id", "symbol", "side", "strategy"}
    missing = required_fields - set(payload.keys())
    if missing:
        errors.append(f"Missing required fields: {', '.join(sorted(missing))}")

    if "symbol" in payload and not isinstance(payload["symbol"], str):
        errors.append("symbol must be a string")

    side = payload.get("side", "").upper()
    if side and side not in ("BUY", "SELL"):
        errors.append(f"Invalid side: {side} (must be BUY or SELL)")

    if "price" in payload:
        try:
            float(payload["price"])
        except ValueError, TypeError:
            errors.append("price must be numeric")

    return errors


# ── Normalization ────────────────────────────────────────────────────────


def normalize_alert(
    payload: dict[str, Any],
    webhook_alert_id: str,
) -> NormalizedSignal:
    """Convert raw TradingView payload into a normalized internal signal."""
    side_raw = payload.get("side", "").upper()
    side = SignalSide.BUY if side_raw == "BUY" else SignalSide.SELL

    ts_raw = payload.get("timestamp", "")
    signal_ts = None
    if ts_raw:
        with contextlib.suppress(ValueError, TypeError):
            signal_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))

    return NormalizedSignal(
        id=_generate_id(),
        webhook_alert_id=webhook_alert_id,
        alert_id=str(payload.get("alert_id", "")),
        symbol=str(payload.get("symbol", "")).upper(),
        side=side,
        strategy=str(payload.get("strategy", "")),
        timeframe=str(payload.get("timeframe", "")),
        price=float(payload.get("price", 0.0)),
        signal_timestamp=signal_ts,
        reason=str(payload.get("reason", "")),
    )


# ── Main handler ─────────────────────────────────────────────────────────


async def handle_tradingview_webhook(
    payload: dict[str, Any],
    db: DatabaseManager,
    webhook_secret: str,
    source_ip: str = "",
    signature_header: str | None = None,
    raw_body: bytes | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Process an incoming TradingView webhook.

    Returns a dict suitable for JSON response:
        ``{"status": ..., "alert_id": ..., "signal_id": ..., "message": ...}``
    """
    # ── Rate limit (localhost exempt) ───────────────────────────────
    if not _check_rate_limit(source_ip):
        return {
            "status": "rate_limited",
            "alert_id": payload.get("alert_id", ""),
            "signal_id": "",
            "message": "Rate limited — try again later",
        }

    # ── Auth ────────────────────────────────────────────────────────
    authenticated = verify_webhook_secret(
        payload, webhook_secret, signature_header, raw_body
    )
    if not authenticated and webhook_secret:
        logger.warning("Unauthenticated webhook rejected from {}", source_ip)
        return {
            "status": "rejected",
            "alert_id": "",
            "signal_id": "",
            "message": "Authentication failed",
        }

    # ── Payload validation ──────────────────────────────────────────
    errors = validate_payload(payload)
    if errors:
        logger.warning(
            "Malformed webhook payload: {} (payload={})",
            "; ".join(errors),
            redact_dict(payload),
        )
        return {
            "status": "rejected",
            "alert_id": payload.get("alert_id", ""),
            "signal_id": "",
            "message": "; ".join(errors),
        }

    alert_id = str(payload.get("alert_id", ""))

    # ── Dedup ───────────────────────────────────────────────────────
    existing = db.get_alert_by_alert_id(alert_id)
    if existing:
        logger.info("Duplicate webhook alert_id={} — skipping", alert_id)
        return {
            "status": "duplicate",
            "alert_id": alert_id,
            "signal_id": existing.get("normalized_id", ""),
            "message": "Duplicate alert, already processed",
        }

    # ── Store raw alert (secret stripped) ───────────────────────────
    alert_uuid = _generate_id()
    safe_payload = sanitize_payload_for_storage(payload)
    alert_record = {
        "id": alert_uuid,
        "alert_id": alert_id,
        "raw_payload": safe_payload,
        "received_at": _utcnow(),
        "source_ip": source_ip,
        "authenticated": authenticated,
    }
    db.insert_alert(alert_record)
    logger.info(
        "Webhook alert stored: alert_id={} id={} payload={}",
        alert_id,
        alert_uuid,
        redact_dict(safe_payload),
    )

    # ── Normalize ───────────────────────────────────────────────────
    signal = normalize_alert(payload, alert_uuid)
    signal_dict = signal.model_dump()
    signal_dict["normalized_at"] = _utcnow()
    signal_dict["data_source"] = "production"
    signal_dict["session_id"] = session_id
    db.insert_signal(signal_dict)

    # Update alert with normalized_id
    conn_alert = db._connect()
    try:
        conn_alert.execute(
            "UPDATE webhook_alerts SET normalized_id = ? WHERE id = ?",
            (signal.id, alert_uuid),
        )
        conn_alert.commit()
    finally:
        conn_alert.close()

    logger.info(
        "Signal normalized: alert_id={} symbol={} side={} strategy={}",
        alert_id,
        signal.symbol,
        signal.side.value,
        signal.strategy,
    )

    return {
        "status": "received",
        "alert_id": alert_id,
        "signal_id": signal.id,
        "message": "Signal received and normalized",
    }
