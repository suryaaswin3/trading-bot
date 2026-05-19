"""Config dataclass tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from trading_bot.config import TradingBotConfig, load_config_from_env


class TestDefaults:
    """Verify all config fields have expected defaults."""

    def test_debug_mode_defaults_to_false(self) -> None:
        assert TradingBotConfig().debug_mode is False

    def test_paper_mode_defaults_to_true(self) -> None:
        assert TradingBotConfig().paper_mode is True

    def test_max_trades_per_day(self) -> None:
        assert TradingBotConfig().max_trades_per_day == 2

    def test_cooldown_minutes(self) -> None:
        assert TradingBotConfig().cooldown_minutes == 30

    def test_vwap_lookback_candles(self) -> None:
        assert TradingBotConfig().vwap_lookback_candles == 10

    def test_ema_fast_period(self) -> None:
        assert TradingBotConfig().ema_fast_period == 20

    def test_ema_slow_period(self) -> None:
        assert TradingBotConfig().ema_slow_period == 50

    def test_min_body_ratio(self) -> None:
        assert TradingBotConfig().min_body_ratio == 0.3

    def test_orb_min_range_default(self) -> None:
        assert TradingBotConfig().orb_min_range == 0.0

    def test_max_consecutive_losses_default(self) -> None:
        assert TradingBotConfig().max_consecutive_losses == 3

    def test_market_atr_low_threshold_default(self) -> None:
        assert TradingBotConfig().market_atr_low_threshold == 50.0

    def test_heartbeat_interval_default(self) -> None:
        assert TradingBotConfig().heartbeat_interval_minutes == 0


class TestFrozen:
    """Verify the dataclass is truly frozen."""

    def test_cannot_set_attributes(self) -> None:
        cfg = TradingBotConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.debug_mode = True  # type: ignore[misc]


class TestEnvOverride:
    """Verify TB_* env vars override defaults."""

    def test_debug_mode_env_var_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TB_DEBUG_MODE", "1")
        cfg = load_config_from_env()
        assert cfg.debug_mode is True

    def test_debug_mode_env_var_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TB_DEBUG_MODE", raising=False)
        cfg = load_config_from_env()
        assert cfg.debug_mode is False

    def test_paper_mode_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TB_PAPER_MODE", "false")
        cfg = load_config_from_env()
        assert cfg.paper_mode is False

    def test_int_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TB_MAX_TRADES_PER_DAY", "5")
        cfg = load_config_from_env()
        assert cfg.max_trades_per_day == 5

    def test_float_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TB_STOP_LOSS_PCT", "15.5")
        cfg = load_config_from_env()
        assert cfg.stop_loss_pct == 15.5

    def test_str_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TB_STATE_FILE_PATH", "/tmp/test_state.json")
        cfg = load_config_from_env()
        assert cfg.state_file_path == "/tmp/test_state.json"

    def test_comprehensive_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All fields overridden via env should match."""
        overrides = {
            "TB_PAPER_MODE": "false",
            "TB_DEBUG_MODE": "true",
            "TB_VWAP_LOOKBACK_CANDLES": "15",
            "TB_EMA_FAST_PERIOD": "10",
            "TB_MIN_BODY_RATIO": "0.5",
            "TB_ORB_MIN_RANGE": "25.0",
            "TB_MAX_CONSECUTIVE_LOSSES": "5",
            "TB_MAX_TRADES_PER_DAY": "3",
            "TB_HEARTBEAT_INTERVAL_MINUTES": "5",
        }
        for key, val in overrides.items():
            monkeypatch.setenv(key, val)

        cfg = load_config_from_env()
        assert cfg.paper_mode is False
        assert cfg.debug_mode is True
        assert cfg.vwap_lookback_candles == 15
        assert cfg.ema_fast_period == 10
        assert cfg.min_body_ratio == 0.5
        assert cfg.orb_min_range == 25.0
        assert cfg.max_consecutive_losses == 5
        assert cfg.max_trades_per_day == 3
        assert cfg.heartbeat_interval_minutes == 5
