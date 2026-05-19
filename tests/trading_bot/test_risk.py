"""RiskManager tests — signal validation, state-gated blocking, circuit breaker."""

from __future__ import annotations

from trading_bot.config import TradingBotConfig
from trading_bot.risk import RiskManager
from trading_bot.state import state


class TestCanEnter:
    def test_invalid_signal_rejected(self) -> None:
        rm = RiskManager(TradingBotConfig())
        allowed, reason = rm.can_enter("WAIT")
        assert not allowed
        assert "Invalid" in reason

    def test_unknown_signal_rejected(self) -> None:
        rm = RiskManager(TradingBotConfig())
        allowed, reason = rm.can_enter("UNKNOWN")
        assert not allowed
        assert "Invalid" in reason

    def test_trade_call_allowed_with_clean_state(self) -> None:
        rm = RiskManager(TradingBotConfig())
        allowed, reason = rm.can_enter("TRADE_CALL")
        assert allowed
        assert reason == ""

    def test_trade_put_allowed_with_clean_state(self) -> None:
        rm = RiskManager(TradingBotConfig())
        allowed, reason = rm.can_enter("TRADE_PUT")
        assert allowed
        assert reason == ""

    def test_blocked_when_max_trades_reached(self) -> None:
        state["trades_today"] = 2
        rm = RiskManager(TradingBotConfig(max_trades_per_day=2))
        allowed, reason = rm.can_enter("TRADE_CALL")
        assert not allowed
        assert "Max trades" in reason


class TestConsecutiveLosses:
    """Circuit breaker: should block after N consecutive losses."""

    def test_allows_with_no_losses(self) -> None:
        rm = RiskManager(TradingBotConfig(max_consecutive_losses=3))
        allowed, _ = rm.can_enter("TRADE_CALL")
        assert allowed

    def test_allows_before_limit(self) -> None:
        rm = RiskManager(TradingBotConfig(max_consecutive_losses=3))
        rm.record_exit(-100.0)  # 1 loss
        rm.record_exit(-50.0)  # 2 losses
        allowed, _ = rm.can_enter("TRADE_CALL")
        assert allowed

    def test_blocks_after_limit(self) -> None:
        rm = RiskManager(TradingBotConfig(max_consecutive_losses=3))
        rm.record_exit(-100.0)  # 1
        rm.record_exit(-50.0)  # 2
        rm.record_exit(-200.0)  # 3 — at limit
        allowed, reason = rm.can_enter("TRADE_CALL")
        assert not allowed
        assert "Circuit breaker" in reason

    def test_resets_on_win(self) -> None:
        rm = RiskManager(TradingBotConfig(max_consecutive_losses=2))
        rm.record_exit(-100.0)  # 1 loss
        rm.record_exit(-50.0)  # 2 losses — at limit
        rm.record_exit(200.0)  # Win resets to 0
        allowed, _ = rm.can_enter("TRADE_CALL")
        assert allowed

    def test_reset_daily_clears_counter(self) -> None:
        rm = RiskManager(TradingBotConfig(max_consecutive_losses=2))
        rm.record_exit(-100.0)
        rm.record_exit(-50.0)  # at limit
        rm.reset_daily()
        allowed, _ = rm.can_enter("TRADE_CALL")
        assert allowed
