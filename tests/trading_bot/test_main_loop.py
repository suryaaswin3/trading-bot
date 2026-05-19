"""Main loop simulation tests — mock market conditions, verify loop behavior.

KEY RULE: main.py imports everything with ``from X import Y``, so all
monkeypatch paths must target ``trading_bot.main.<name>``, NOT
``trading_bot.<module>.<name>``.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
import pytz

from trading_bot.config import TradingBotConfig
from trading_bot.state import reset_state, state

_IST = pytz.timezone("Asia/Kolkata")

# Fixed expiry used for mock instruments and get_weekly_expiry patch
_MOCK_EXPIRY_DT = datetime(2025, 6, 19, 15, 30, 0, tzinfo=_IST)


def _make_instrument_dict(
    token: int,
    name: str,
    inst_type: str,
    strike: float,
    lot_size: int = 50,
) -> dict:
    """Create a mock NFO instrument dict for InstrumentCache.load()."""
    return {
        "instrument_token": token,
        "tradingsymbol": f"{name}2425{inst_type}{int(strike)}",
        "name": name,
        "instrument_type": inst_type,
        "strike": strike,
        "lot_size": lot_size,
        "expiry": "2025-06-19T15:30:00+05:30",
        "exchange": "NFO",
    }


def _make_mock_nifty_instruments() -> list[dict]:
    """CE + PE NIFTY instruments around strike 18150 (matches candle close)."""
    return [
        _make_instrument_dict(99999, "NIFTY", "CE", 18150),
        _make_instrument_dict(99998, "NIFTY", "PE", 18150),
    ]


def _sleep_and_shutdown(*args, **kwargs):
    """Replace time.sleep in main.py: fire shutdown on first sleep."""
    import trading_bot.main as m

    m._shutdown = True


def _make_candle_dict(
    o: float = 18100,
    h: float = 18150,
    l: float = 18080,
    c: float = 18120,
    v: int = 50000,
    ts: str = "2025-06-15T10:00:00+05:30",
) -> dict:
    return {
        "date": ts,
        "open": str(o),
        "high": str(h),
        "low": str(l),
        "close": str(c),
        "volume": str(v),
    }


def _make_candle_dicts(
    count: int = 3, start_ts: str = "2025-06-15T09:15:00+05:30"
) -> list[dict]:
    """Generate enough candle dicts for indicators that need 55+ candles."""
    from datetime import timedelta

    ts = datetime.fromisoformat(start_ts)
    results: list[dict] = []
    base_open = 18100
    for i in range(count):
        results.append(
            _make_candle_dict(
                o=base_open + i * 2,
                h=base_open + i * 2 + 50,
                l=base_open + i * 2 - 30,
                c=base_open + i * 2 + 20,
                ts=(ts + timedelta(minutes=5 * i)).isoformat(),
            )
        )
    return results


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level state before each main_loop test."""
    import trading_bot.main as m

    m._shutdown = False
    m._last_entry_candle_time = None
    m._orb_state_set = False
    m._last_heartbeat = None
    m._consecutive_errors = 0
    reset_state()
    yield
    m._shutdown = False
    m._last_entry_candle_time = None
    m._orb_state_set = False
    m._last_heartbeat = None
    m._consecutive_errors = 0
    reset_state()


def _setup_main_loop_test(
    monkeypatch,
    select_strategy_result=None,
    signal_result="WAIT",
):
    """Shared setup: patch time.sleep, KiteClient, select_strategy, signals.

    Also patches market_condition_filter so it does not need real candle data.
    """
    import trading_bot.main as m

    monkeypatch.setattr("trading_bot.main.time.sleep", _sleep_and_shutdown)

    # Patch market_condition_filter to avoid needing 55+ candles for ATR/EMA
    monkeypatch.setattr(
        "trading_bot.main.market_condition_filter",
        lambda candles, config: "RANGING",
    )

    mock_kite = MagicMock()
    mock_kite.is_connected.return_value = True
    mock_kite.get_instruments.return_value = []
    mock_kite.get_historical_data.return_value = _make_candle_dicts(3)
    mock_kite.get_ltp.return_value = {99999: 150.0}
    monkeypatch.setattr("trading_bot.main.KiteClient", lambda cfg: mock_kite)

    if select_strategy_result is not None:
        monkeypatch.setattr(
            "trading_bot.main.select_strategy",
            lambda now, config: select_strategy_result,
        )
    if signal_result != "WAIT":
        monkeypatch.setattr(
            "trading_bot.main.vwap_pullback_signal",
            lambda candles, vwap, config: signal_result,
        )

    return m, mock_kite


# ========================================================================
# OUTSIDE HOURS
# ========================================================================
class TestMainLoopOutsideHours:
    """When select_strategy returns None, the loop should sleep and skip trading."""

    def test_outside_hours_skips_trading(self, monkeypatch):
        m, _ = _setup_main_loop_test(monkeypatch, select_strategy_result=None)
        m.main_loop(TradingBotConfig())
        assert state["position_status"] is None


# ========================================================================
# VWAP PULLBACK LOOP
# ========================================================================
class TestVWAPPullbackLoop:
    """When market is open, the loop should fetch data and check signals."""

    def test_no_signal_does_not_trade(self, monkeypatch):
        import trading_bot.main as m

        monkeypatch.setattr("trading_bot.main.time.sleep", _sleep_and_shutdown)
        monkeypatch.setattr(
            "trading_bot.main.market_condition_filter",
            lambda candles, config: "RANGING",
        )

        mock_kite = MagicMock()
        mock_kite.is_connected.return_value = True
        mock_kite.get_instruments.return_value = []
        mock_kite.get_historical_data.return_value = _make_candle_dicts(3)
        monkeypatch.setattr("trading_bot.main.KiteClient", lambda cfg: mock_kite)

        monkeypatch.setattr(
            "trading_bot.main.select_strategy", lambda now, config: "VWAP_PULLBACK"
        )

        m.main_loop(TradingBotConfig())
        assert state["position_status"] is None

    def test_signal_triggers_entry(self, monkeypatch):
        import trading_bot.main as m

        monkeypatch.setattr("trading_bot.main.time.sleep", _sleep_and_shutdown)
        monkeypatch.setattr(
            "trading_bot.main.market_condition_filter",
            lambda candles, config: "RANGING",
        )

        mock_kite = MagicMock()
        mock_kite.is_connected.return_value = True
        mock_kite.get_instruments.return_value = _make_mock_nifty_instruments()
        mock_kite.get_historical_data.return_value = _make_candle_dicts(3)
        mock_kite.get_ltp.return_value = {99999: 150.0}
        mock_kite.place_order.return_value = "PAPER_000001"
        monkeypatch.setattr("trading_bot.main.KiteClient", lambda cfg: mock_kite)

        monkeypatch.setattr(
            "trading_bot.main.select_strategy", lambda now, config: "VWAP_PULLBACK"
        )
        monkeypatch.setattr(
            "trading_bot.main.vwap_pullback_signal",
            lambda candles, vwap, config: "TRADE_CALL",
        )

        # Patch get_weekly_expiry so select_option finds the ATM contract
        monkeypatch.setattr(
            "trading_bot.options.get_weekly_expiry", lambda ref=None: _MOCK_EXPIRY_DT
        )

        cfg = TradingBotConfig(paper_mode=True, max_trades_per_day=5)
        m.main_loop(cfg)
        assert state["position_status"] is not None

    def test_signal_dedup_skips_reentry(self, monkeypatch):
        """Same candle timestamp => entry is skipped."""
        import trading_bot.main as m

        monkeypatch.setattr("trading_bot.main.time.sleep", _sleep_and_shutdown)
        monkeypatch.setattr(
            "trading_bot.main.market_condition_filter",
            lambda candles, config: "RANGING",
        )

        m._last_entry_candle_time = datetime.fromisoformat("2025-06-15T09:25:00+05:30")

        mock_kite = MagicMock()
        mock_kite.is_connected.return_value = True
        mock_kite.get_instruments.return_value = _make_mock_nifty_instruments()
        mock_kite.get_historical_data.return_value = _make_candle_dicts(3)
        mock_kite.get_ltp.return_value = {99999: 150.0}
        monkeypatch.setattr("trading_bot.main.KiteClient", lambda cfg: mock_kite)

        monkeypatch.setattr(
            "trading_bot.main.select_strategy", lambda now, config: "VWAP_PULLBACK"
        )
        monkeypatch.setattr(
            "trading_bot.main.vwap_pullback_signal",
            lambda candles, vwap, config: "TRADE_CALL",
        )

        m.main_loop(TradingBotConfig())
        assert state["position_status"] is None


# ========================================================================
# SHUTDOWN & DISCONNECT
# ========================================================================
class TestShutdownAndDisconnect:
    def test_shutdown_graceful(self, monkeypatch):
        """Setting _shutdown = True before entering main_loop causes immediate exit."""
        import trading_bot.main as m

        m._shutdown = True
        monkeypatch.setattr("trading_bot.main.time.sleep", _sleep_and_shutdown)
        monkeypatch.setattr("trading_bot.main.KiteClient", lambda cfg: MagicMock())
        monkeypatch.setattr(
            "trading_bot.main.select_strategy", lambda now, config: None
        )

        m.main_loop(TradingBotConfig())
        assert state["position_status"] is None

    def test_kite_disconnected_no_crash(self, monkeypatch):
        import trading_bot.main as m

        monkeypatch.setattr("trading_bot.main.time.sleep", _sleep_and_shutdown)

        mock_kite = MagicMock()
        mock_kite.is_connected.return_value = False
        monkeypatch.setattr("trading_bot.main.KiteClient", lambda cfg: mock_kite)

        monkeypatch.setattr(
            "trading_bot.main.select_strategy", lambda now, config: "VWAP_PULLBACK"
        )

        m.main_loop(TradingBotConfig())


# ========================================================================
# PAPER EXECUTION
# ========================================================================
class TestPaperExecute:
    def test_paper_execute_order_id_format(self):
        from trading_bot.main import _paper_execute

        oid = _paper_execute(
            "BUY", "NIFTY24JUNFUT", 75, 150.0, "VWAP_PULLBACK", TradingBotConfig()
        )
        assert oid is not None
        assert oid.startswith("PAPER_")
        assert len(oid) > 5

    def test_paper_exit_returns_order_id(self):
        from trading_bot.main import _paper_exit

        oid = _paper_exit("NIFTY24JUNFUT", 75, 150.0)
        assert oid is not None


# ========================================================================
# EXECUTE ENTRY SIGNAL
# ========================================================================
class TestExecuteEntrySignal:
    """Direct _execute_entry_signal tests (no loop simulation).

    Since the function was imported with ``from X import Y``, we must patch
    ``trading_bot.main.<name>``.
    """

    def test_no_contract_logs_warning(self, monkeypatch, caplog):
        from trading_bot.main import _execute_entry_signal

        monkeypatch.setattr("trading_bot.main.select_option", lambda *a, **kw: None)

        mock_kite = MagicMock()
        result = _execute_entry_signal(
            "TRADE_CALL",
            "NIFTY",
            18000.0,
            MagicMock(),
            TradingBotConfig(),
            "VWAP_PULLBACK",
            mock_kite,
        )
        assert result is False
        assert "No option contract" in caplog.text

    def test_ltp_fail_logs_warning(self, monkeypatch, caplog):
        from trading_bot.main import _execute_entry_signal

        mock_contract = MagicMock()
        mock_contract.instrument_token = 99999
        mock_contract.lot_size = 75
        monkeypatch.setattr(
            "trading_bot.main.select_option", lambda *a, **kw: mock_contract
        )

        mock_kite = MagicMock()
        mock_kite.get_ltp.return_value = {}

        result = _execute_entry_signal(
            "TRADE_CALL",
            "NIFTY",
            18000.0,
            MagicMock(),
            TradingBotConfig(),
            "VWAP_PULLBACK",
            mock_kite,
        )
        assert result is False
        assert "Could not fetch option LTP" in caplog.text
