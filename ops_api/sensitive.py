"""Sensitive data redaction for logs and storage.

Centralised approach so redaction rules are defined once and always applied.
"""

from __future__ import annotations

from typing import Any

SENSITIVE_FIELD_NAMES = frozenset({
    "secret",
    "password",
    "passwd",
    "token",
    "api_key",
    "api_key_header",
    "webhook_secret",
    "telegram_bot_token",
    "kite_api_key",
    "kite_access_token",
    "kite_password",
    "kite_totp_secret",
    "authorization",
    "x-api-key",
    "x-signature",
})

_REPLACEMENT = "***"


def redact_value(key: str, value: Any) -> Any:
    """Return the redacted form of *value* if *key* looks sensitive, else value."""
    key_lower = key.lower().strip().replace("-", "_").replace(" ", "_")
    if key_lower in SENSITIVE_FIELD_NAMES:
        if isinstance(value, str) and len(value) > 8:
            return value[:4] + "****" + value[-4:]
        return _REPLACEMENT
    return value


def redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *d* with sensitive values replaced.

    Works recursively on nested dicts.
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        rv = redact_value(k, v)
        if isinstance(v, dict):
            rv = redact_dict(v)
        elif isinstance(v, list):
            rv = [redact_dict(i) if isinstance(i, dict) else i for i in v]
        out[k] = rv
    return out


def sanitize_payload_for_storage(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive fields entirely before persisting raw payloads.

    Unlike :func:`redact_dict` (which keeps field names with a placeholder),
    this removes the sensitive keys so they never touch disk.
    """
    out = dict(payload)
    for k in list(out.keys()):
        if k.lower().strip() in SENSITIVE_FIELD_NAMES:
            del out[k]
    return out
