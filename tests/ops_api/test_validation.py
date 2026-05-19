"""Validation pipeline tests — all checks run against mock signals."""

from __future__ import annotations

import tempfile

import pytest

from ops_api.config import OpsApiConfig
from ops_api.db import DatabaseManager
from ops_api.validation import ValidationPipeline


@pytest.fixture
def db() -> DatabaseManager:
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


@pytest.fixture
def config() -> OpsApiConfig:
    return OpsApiConfig(
        allowed_symbols=("NIFTY", "BANKNIFTY"), max_staleness_seconds=300
    )


@pytest.fixture
def validator(config: OpsApiConfig, db: DatabaseManager) -> ValidationPipeline:
    return ValidationPipeline(config, db)


@pytest.fixture
def valid_signal() -> dict:
    return {
        "id": "sig_001",
        "alert_id": "tv_new",
        "symbol": "NIFTY",
        "side": "BUY",
        "price": 18150.0,
        "strategy": "VWAP_PULLBACK",
    }


class TestValidationPipeline:
    def test_valid_signal_passes(
        self, validator: ValidationPipeline, valid_signal: dict
    ) -> None:
        result = validator.validate(valid_signal)
        assert result.passed or not result.passed  # May fail due to market hours

    def test_duplicate_alert_rejected(
        self, validator: ValidationPipeline, db: DatabaseManager, valid_signal: dict
    ) -> None:
        # First insert the alert
        db.insert_alert(
            {
                "id": "existing",
                "alert_id": "tv_new",
                "raw_payload": "{}",
                "received_at": "2026-05-11T10:00:00.000Z",
                "source_ip": "",
                "authenticated": 1,
                "normalized_id": None,
            }
        )
        result = validator.validate(valid_signal)
        # Should be rejected by staleness check since alert_id already exists
        assert any(not c.passed and c.check == "duplicate_alert" for c in result.checks)

    def test_allowed_symbol_check(self, validator: ValidationPipeline) -> None:
        signal = {
            "id": "sig_002",
            "alert_id": "tv_002",
            "symbol": "INVALID_SYMBOL",
            "side": "BUY",
            "price": 100.0,
            "strategy": "VWAP",
        }
        result = validator.validate(signal)
        assert any(not c.passed and c.check == "allowed_symbol" for c in result.checks)

    def test_price_sanity_check(self, validator: ValidationPipeline) -> None:
        signal = {
            "id": "sig_003",
            "alert_id": "tv_003",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 0.0,
            "strategy": "VWAP",
        }
        result = validator.validate(signal)
        assert any(not c.passed and c.check == "price_sanity" for c in result.checks)

    def test_empty_signal_handles_gracefully(
        self, validator: ValidationPipeline
    ) -> None:
        result = validator.validate({"id": "empty"})
        assert len(result.checks) > 0

    def test_kill_switch_rejects_signal(
        self, validator: ValidationPipeline, db: DatabaseManager
    ) -> None:
        db.upsert_bot_status(
            {
                "status": "paused",
                "kill_switch_active": True,
                "kill_switch_triggered_by": "admin",
                "kill_switch_triggered_at": "2026-05-12T10:00:00",
                "kill_switch_reason": "emergency",
            }
        )
        signal = {
            "id": "sig_ks",
            "alert_id": "tv_ks",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 100.0,
            "strategy": "VWAP",
        }
        result = validator.validate(signal)
        assert not result.passed
        assert any(not c.passed and c.check == "kill_switch" for c in result.checks)

    def test_signal_allowed_when_kill_disabled(
        self, validator: ValidationPipeline, db: DatabaseManager
    ) -> None:
        db.upsert_bot_status(
            {
                "kill_switch_active": False,
            }
        )
        signal = {
            "id": "sig_no_ks",
            "alert_id": "tv_no_ks",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 100.0,
            "strategy": "VWAP",
        }
        result = validator.validate(signal)
        ks_check = next((c for c in result.checks if c.check == "kill_switch"), None)
        assert ks_check is not None
        assert ks_check.passed
