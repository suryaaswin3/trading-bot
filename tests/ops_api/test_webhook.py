"""Webhook tests — HMAC auth, payload validation, dedup, normalization."""

from __future__ import annotations

import json
import tempfile

import pytest

from ops_api.db import DatabaseManager
from ops_api.webhook import (
    handle_tradingview_webhook,
    normalize_alert,
    validate_payload,
    verify_webhook_secret,
)


@pytest.fixture
def db() -> DatabaseManager:
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


VALID_PAYLOAD = {
    "secret": "test_secret",
    "alert_id": "tv_001",
    "symbol": "NIFTY",
    "side": "BUY",
    "strategy": "VWAP_PULLBACK",
    "timeframe": "5min",
    "price": 18150.0,
    "timestamp": "2026-05-11T10:00:00Z",
    "reason": "VWAP pullback signal",
}


class TestVerifyWebhookSecret:
    def test_no_secret_configured_allows_all(self) -> None:
        assert verify_webhook_secret({"secret": ""}, "")

    def test_valid_json_secret(self) -> None:
        assert verify_webhook_secret({"secret": "mypass"}, "mypass")

    def test_invalid_json_secret(self) -> None:
        assert not verify_webhook_secret({"secret": "wrong"}, "mypass")

    def test_valid_hmac(self) -> None:
        raw = json.dumps({"alert_id": "test"}).encode()
        import hashlib
        import hmac

        expected = hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
        assert verify_webhook_secret(
            {"alert_id": "test"},
            "secret",
            signature_header=expected,
            raw_body=raw,
        )

    def test_invalid_hmac(self) -> None:
        raw = json.dumps({"alert_id": "test"}).encode()
        assert not verify_webhook_secret(
            {"alert_id": "test"},
            "secret",
            signature_header="wrongsig",
            raw_body=raw,
        )

    def test_hmac_takes_priority(self) -> None:
        """Valid HMAC should pass even if JSON secret is wrong."""
        raw = json.dumps({"secret": "wrong", "alert_id": "test"}).encode()
        import hashlib
        import hmac

        expected = hmac.new(b"realsecret", raw, hashlib.sha256).hexdigest()
        assert verify_webhook_secret(
            {"secret": "wrong", "alert_id": "test"},
            "realsecret",
            signature_header=expected,
            raw_body=raw,
        )


class TestValidatePayload:
    def test_valid_payload_returns_empty(self) -> None:
        errors = validate_payload(VALID_PAYLOAD)
        assert errors == []

    def test_missing_required_fields(self) -> None:
        errors = validate_payload({"symbol": "NIFTY"})
        assert len(errors) >= 1
        assert any("alert_id" in e for e in errors)

    def test_invalid_side(self) -> None:
        errors = validate_payload({**VALID_PAYLOAD, "side": "INVALID"})
        assert any("side" in e for e in errors)

    def test_non_numeric_price(self) -> None:
        errors = validate_payload({**VALID_PAYLOAD, "price": "not_a_number"})
        assert any("price" in e for e in errors)

    def test_empty_payload(self) -> None:
        errors = validate_payload({})
        assert len(errors) >= 1


class TestNormalizeAlert:
    def test_basic_normalization(self) -> None:
        signal = normalize_alert(VALID_PAYLOAD, "alert_uuid_123")
        assert signal.symbol == "NIFTY"
        assert signal.side.value == "BUY"
        assert signal.strategy == "VWAP_PULLBACK"
        assert signal.price == 18150.0

    def test_side_mapping(self) -> None:
        signal = normalize_alert({**VALID_PAYLOAD, "side": "SELL"}, "id")
        assert signal.side.value == "SELL"


class TestHandleTradingViewWebhook:
    @pytest.fixture(autouse=True)
    def _db(self):
        """Create a fresh temp DB per test method."""
        tmp = tempfile.mktemp(suffix=".db")
        mgr = DatabaseManager(tmp)
        mgr.init_schema()
        self._db_instance = mgr
        yield

    @pytest.mark.asyncio
    async def test_rejected_no_secret(self) -> None:
        result = await handle_tradingview_webhook(
            payload={
                "secret": "",
                "alert_id": "test",
                "symbol": "NIFTY",
                "side": "BUY",
                "strategy": "VWAP",
            },
            db=self._db_instance,
            webhook_secret="secret",
            signature_header=None,
            raw_body=None,
        )
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_rejected_malformed(self) -> None:
        result = await handle_tradingview_webhook(
            payload={"secret": "s"},
            db=self._db_instance,
            webhook_secret="s",
        )
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_successful_ingestion(self) -> None:
        result = await handle_tradingview_webhook(
            payload={**VALID_PAYLOAD, "secret": ""},
            db=self._db_instance,
            webhook_secret="",
            source_ip="127.0.0.1",
        )
        assert result["status"] == "received"
        assert result["alert_id"] == "tv_001"
        assert len(result.get("signal_id", "")) > 0

    @pytest.mark.asyncio
    async def test_duplicate_rejection(self) -> None:
        # First call
        await handle_tradingview_webhook(
            payload={**VALID_PAYLOAD, "secret": ""},
            db=self._db_instance,
            webhook_secret="",
        )
        # Second call — should be duplicate
        result = await handle_tradingview_webhook(
            payload={**VALID_PAYLOAD, "secret": ""},
            db=self._db_instance,
            webhook_secret="",
        )
        assert result["status"] == "duplicate"

    @pytest.mark.asyncio
    async def test_valid_with_secret(self) -> None:
        result = await handle_tradingview_webhook(
            payload={**VALID_PAYLOAD, "secret": "mypass"},
            db=self._db_instance,
            webhook_secret="mypass",
        )
        assert result["status"] == "received"
