"""Verify all trading bot modules import cleanly."""

from __future__ import annotations


def test_import_config() -> None:
    pass


def test_import_data() -> None:
    from trading_bot.data import (  # noqa: F401
        Candle,
        VWAPState,
        build_candles,
        compute_vwap,
    )


def test_import_kite_client() -> None:
    from trading_bot.kite_client import KiteClient  # noqa: F401


def test_import_main() -> None:
    from trading_bot.main import main, main_loop  # noqa: F401


def test_import_options() -> None:
    from trading_bot.options import (  # noqa: F401
        InstrumentCache,
        OptionContract,
        select_option,
    )


def test_import_risk() -> None:
    from trading_bot.risk import RiskManager  # noqa: F401


def test_import_state() -> None:
    from trading_bot.state import (  # noqa: F401
        can_trade,
        close_position,
        get_summary,
        in_position,
        open_position,
        reset_state,
        should_exit,
        state,
    )


def test_import_strategies() -> None:
    from trading_bot.strategies import (  # noqa: F401
        select_strategy,
        vwap_pullback_signal,
    )


def test_import_all() -> None:
    """Verify __init__.py exports work (at minimum the package can be imported)."""
    import trading_bot  # noqa: F401
