"""State tracking tests — position management, trade gates, exit logic."""

from __future__ import annotations

from datetime import datetime

import pytz

from trading_bot.config import TradingBotConfig
from trading_bot.state import (
    can_trade,
    close_position,
    in_position,
    open_position,
    reset_state,
    should_exit,
    state,
)

_IST = pytz.timezone("Asia/Kolkata")


class TestOpenClosePosition:
    def test_open_position_sets_fields(self) -> None:
        ts = datetime.now(_IST)
        open_position(
            side="LONG",
            symbol="NIFTY24JUNFUT",
            token=12345,
            option_type="CE",
            price=150.0,
            qty=75,
            order_id="order_1",
            strategy="VWAP_PULLBACK",
            entry_time=ts,
        )
        assert state["position_status"] == "LONG"
        assert state["symbol"] == "NIFTY24JUNFUT"
        assert state["entry_price"] == 150.0
        assert state["quantity"] == 75

    def test_in_position_true(self) -> None:
        assert not in_position()
        open_position(
            side="LONG",
            symbol="X",
            token=1,
            option_type="CE",
            price=100,
            qty=75,
            order_id="o1",
            strategy="VWAP_PULLBACK",
        )
        assert in_position()

    def test_in_position_false_initially(self) -> None:
        assert not in_position()

    def test_close_position_long(self) -> None:
        open_position(
            side="LONG",
            symbol="X",
            token=1,
            option_type="CE",
            price=100,
            qty=10,
            order_id="o1",
            strategy="VWAP_PULLBACK",
        )
        pnl = close_position(110.0)
        assert pnl == 100.0  # (110-100)*10

    def test_close_position_short(self) -> None:
        open_position(
            side="SHORT",
            symbol="X",
            token=1,
            option_type="PE",
            price=100,
            qty=10,
            order_id="o1",
            strategy="VWAP_PULLBACK",
        )
        pnl = close_position(90.0)
        assert pnl == 100.0  # (100-90)*10

    def test_close_position_no_position(self) -> None:
        reset_state()
        assert close_position(100.0) == 0.0

    def test_reset_state_clears_everything(self) -> None:
        open_position(
            side="LONG",
            symbol="X",
            token=1,
            option_type="CE",
            price=100,
            qty=10,
            order_id="o1",
            strategy="VWAP_PULLBACK",
        )
        reset_state()
        assert state["position_status"] is None
        assert state["entry_candle_time"] is None


class TestCanTrade:
    def test_allows_when_clean(self) -> None:
        reset_state()
        allowed, reason = can_trade(TradingBotConfig())
        assert allowed
        assert reason == ""

    def test_blocks_when_in_position(self) -> None:
        open_position(
            side="LONG",
            symbol="X",
            token=1,
            option_type="CE",
            price=100,
            qty=10,
            order_id="o1",
            strategy="VWAP_PULLBACK",
        )
        allowed, reason = can_trade(TradingBotConfig())
        assert not allowed
        assert "Position" in reason

    def test_blocks_when_max_trades_reached(self) -> None:
        state["trades_today"] = 2
        allowed, reason = can_trade(TradingBotConfig(max_trades_per_day=2))
        assert not allowed
        assert "Max trades" in reason


class TestShouldExit:
    def test_no_position(self) -> None:
        reset_state()
        sig, reason, price = should_exit(100.0, TradingBotConfig())
        assert not sig

    def test_stop_loss_long(self) -> None:
        open_position(
            side="LONG",
            symbol="X",
            token=1,
            option_type="CE",
            price=100,
            qty=10,
            order_id="o1",
            strategy="VWAP_PULLBACK",
        )
        # SL = 100 * (1 - 0.3) = 70
        sig, reason, price = should_exit(69.0, TradingBotConfig(stop_loss_pct=30.0))
        assert sig
        assert "Stop loss" in reason

    def test_target_long(self) -> None:
        open_position(
            side="LONG",
            symbol="X",
            token=1,
            option_type="CE",
            price=100,
            qty=10,
            order_id="o1",
            strategy="VWAP_PULLBACK",
        )
        # SL amount = 30, Target = 100 + 30*2 = 160
        sig, reason, price = should_exit(
            161.0, TradingBotConfig(stop_loss_pct=30.0, target_multiplier=2.0)
        )
        assert sig
        assert "Target" in reason

    def test_hold_between_sl_and_target(self) -> None:
        open_position(
            side="LONG",
            symbol="X",
            token=1,
            option_type="CE",
            price=100,
            qty=10,
            order_id="o1",
            strategy="VWAP_PULLBACK",
        )
        sig, reason, price = should_exit(100.0, TradingBotConfig(stop_loss_pct=30.0))
        assert not sig
