"""Main trading bot loop — synchronous polling version with strategy dispatch."""

from __future__ import annotations

import signal
import time
from datetime import datetime, timedelta

import pytz
from loguru import logger

from trading_bot.config import TradingBotConfig, load_config_from_env
from trading_bot.data import build_candles, compute_vwap, get_orb_range
from trading_bot.kite_client import KiteClient
from trading_bot.options import InstrumentCache, select_option
from trading_bot.risk import RiskManager
from trading_bot.state import (
    close_position,
    in_position,
    open_position,
    should_exit,
    state,
)
from trading_bot.strategies import (
    market_condition_filter,
    orb_breakout_signal,
    select_strategy,
    vwap_pullback_signal,
)

_IST = pytz.timezone("Asia/Kolkata")

kite: KiteClient | None = None

# ── Graceful shutdown flag ──────────────────────────────────────────────

_shutdown = False
_last_entry_candle_time: datetime | None = None
_NIFTY_50_TOKEN: int = 256265
_orb_state_set: bool = False
_last_heartbeat: datetime | None = None
_consecutive_errors: int = 0
_SAFE_MODE_THRESHOLD = 3


def _handle_sigterm(signum: int, _frame) -> None:
    global _shutdown
    if _shutdown:
        return
    _shutdown = True
    sig_name = signal.Signals(signum).name
    logger.warning("Received {} — shutting down gracefully", sig_name)


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)

PAPER_ORDER_ID = 0


def _next_paper_order_id() -> str:
    global PAPER_ORDER_ID
    PAPER_ORDER_ID += 1
    return f"PAPER_{PAPER_ORDER_ID:06d}"


def _log_trade(action: str, **kwargs) -> None:
    logger.bind(
        action=action, **{k: v for k, v in kwargs.items() if v is not None}
    ).info(f"TRADE {action}")


def _paper_execute(
    side: str,
    symbol: str,
    qty: int,
    price: float,
    strategy: str,
    config: TradingBotConfig,
) -> str | None:
    order_id = _next_paper_order_id()

    slippage = (
        config.slippage_nifty_points
        if "NIFTY" in symbol
        else config.slippage_banknifty_points
    )

    fill_price = price + slippage if side == "BUY" else price - slippage

    logger.info(
        "[PAPER] {} {} x{} @ {} (slippage: {}) order_id={}",
        side,
        symbol,
        qty,
        fill_price,
        slippage,
        order_id,
    )

    _log_trade(
        "PAPER_ENTER",
        symbol=symbol,
        side=side,
        qty=qty,
        price=fill_price,
        strategy=strategy,
        order_id=order_id,
    )

    return order_id


def _paper_exit(symbol: str, qty: int, price: float) -> str | None:
    order_id = _next_paper_order_id()
    logger.info("[PAPER] EXIT {} x{} @ {} order_id={}", symbol, qty, price, order_id)
    return order_id


def _execute_entry_signal(
    signal: str,
    index: str,
    underlying_price: float,
    cache: InstrumentCache,
    config: TradingBotConfig,
    strategy_name: str,
    kite: KiteClient,
    entry_candle_time: datetime | None = None,
) -> bool:

    if in_position():
        logger.info(
            "Signal skipped — position already open ({} {})",
            state["symbol"],
            state["position_status"],
        )
        return False

    option_type = "CE" if signal == "TRADE_CALL" else "PE"
    side = "LONG" if signal == "TRADE_CALL" else "SHORT"

    contract = select_option(cache, index, option_type, underlying_price, config)
    if contract is None:
        logger.warning("No option contract found for {} {} ATM", index, option_type)
        return False

    lot_size = contract.lot_size
    qty = lot_size * config.position_size_lots

    ltp_data = kite.get_ltp([contract.instrument_token])

    if contract.instrument_token not in ltp_data:
        logger.warning("Could not fetch option LTP")
        return False

    option_price = float(ltp_data[contract.instrument_token])

    limit_price = option_price

    if config.paper_mode:
        order_id = _paper_execute(
            "BUY",
            contract.trading_symbol,
            qty,
            limit_price,
            strategy_name,
            config,
        )
    else:
        order_id = kite.place_order(
            exchange=config.nfo_exchange,
            tradingsymbol=contract.trading_symbol,
            transaction_type="BUY",
            quantity=qty,
            price=limit_price,
            order_type="LIMIT",
            product=config.product,
            variety=config.variety,
            tag=strategy_name,
        )
        _log_trade(
            "LIVE_ENTER",
            symbol=contract.trading_symbol,
            side="BUY",
            qty=qty,
            price=limit_price,
            strategy=strategy_name,
            order_id=order_id,
        )

    if order_id is None:
        return False

    open_position(
        side=side,
        symbol=contract.trading_symbol,
        token=contract.instrument_token,
        option_type=option_type,
        price=limit_price,
        qty=qty,
        order_id=order_id,
        strategy=strategy_name,
        entry_time=datetime.now(_IST),
        entry_candle_time=entry_candle_time,
    )

    global _last_entry_candle_time
    _last_entry_candle_time = entry_candle_time

    return True


def _monitor_and_exit(kite: KiteClient, config: TradingBotConfig) -> bool:
    if not in_position():
        return False

    token = state["instrument_token"]
    if token is None:
        logger.warning("Missing instrument token for open position")
        return False

    ltp_data = kite.get_ltp([token])

    if token not in ltp_data:
        logger.warning("Could not fetch exit LTP")
        return False

    current_price = float(ltp_data[token])

    exit_signal, reason, exit_price = should_exit(current_price, config)
    if not exit_signal:
        return False

    symbol = state["symbol"]
    qty = state["quantity"]

    pnl = close_position(exit_price)

    if config.paper_mode:
        _paper_exit(symbol, qty, exit_price)

    logger.info(
        "Position closed: {} {} @ {} P&L={:.2f} reason={}",
        symbol,
        qty,
        exit_price,
        pnl,
        reason,
    )

    return True


def _compute_orb_state(candles, config: TradingBotConfig) -> None:
    """Compute ORB high/low from the first candle(s) after market open."""
    global _orb_state_set
    if _orb_state_set or not candles:
        return

    # Find the first candle at or after 9:15 market open
    orb_idx = 0
    for i, c in enumerate(candles):
        if c.timestamp.hour > 9 or (c.timestamp.hour == 9 and c.timestamp.minute >= 15):
            orb_idx = i
            break

    orb_result = get_orb_range(candles[orb_idx:], num_candles=1)
    if orb_result:
        state["orb_high"], state["orb_low"] = orb_result
        _orb_state_set = True
        logger.debug(
            "ORB state set: high={}, low={}",
            state["orb_high"],
            state["orb_low"],
        )


def _log_heartbeat(config: TradingBotConfig, market_regime: str) -> None:
    global _last_heartbeat
    if config.heartbeat_interval_minutes <= 0:
        return

    now = datetime.now(_IST)
    if _last_heartbeat is None:
        _last_heartbeat = now
        return

    elapsed = (now - _last_heartbeat).total_seconds()
    if elapsed >= config.heartbeat_interval_minutes * 60:
        logger.info(
            "HEARTBEAT: running | trades={} | pnl={:.2f} | pos={} | regime={}",
            state.get("trades_today", 0),
            state.get("daily_pnl", 0.0),
            state.get("position_status"),
            market_regime,
        )
        _last_heartbeat = now
        _post_heartbeat(config)


def _post_heartbeat(config: TradingBotConfig) -> None:
    """POST heartbeat to ops API if configured."""
    if not config.ops_api_url:
        return
    import contextlib

    import httpx

    with contextlib.suppress(Exception):
        httpx.post(
            f"{config.ops_api_url}/heartbeat",
            json={
                "bot_status": "running",
                "bot_mode": "paper" if config.paper_mode else "live",
                "last_action": state.get("active_strategy") or "waiting",
                "trades_today": state.get("trades_today", 0),
                "daily_pnl": state.get("daily_pnl", 0.0),
                "kite_connected": kite and kite.is_connected() if kite else False,
            },
            timeout=5,
        )


def main_loop(config: TradingBotConfig) -> None:
    logger.info("Starting trading bot (paper_mode={})", config.paper_mode)

    risk_manager = RiskManager(config)
    cache = InstrumentCache()

    global \
        _orb_state_set, \
        _last_entry_candle_time, \
        _last_heartbeat, \
        _consecutive_errors, \
        kite
    _orb_state_set = False
    _last_entry_candle_time = None
    _last_heartbeat = None
    _consecutive_errors = 0

    kite = KiteClient(config)
    for attempt in range(3):
        try:
            kite.connect()
            instruments = kite.get_instruments("NFO")
            cache.load(instruments)
            logger.info("Loaded {} instruments", len(cache.get_all()))
            break
        except Exception:
            logger.exception("Kite connection failed (attempt {}/3)", attempt + 1)
            if attempt < 2:
                time.sleep(10 * (attempt + 1))

    poll_interval = 30

    while not _shutdown:
        try:
            now = datetime.now(_IST)
            if config.debug_mode:
                logger.debug(
                    "DEBUG: poll_cycle | time={} | in_position={} | "
                    "trades_today={} | daily_pnl={:.2f} | kite_connected={} | "
                    "consecutive_errors={}",
                    now.isoformat(),
                    in_position(),
                    state.get("trades_today", 0),
                    state.get("daily_pnl", 0.0),
                    kite and kite.is_connected(),
                    _consecutive_errors,
                )

            strategy_name = select_strategy(now, config)

            if _shutdown:
                break

            if not strategy_name:
                logger.info("Outside trading hours — sleeping...")
                for _ in range(poll_interval):
                    if _shutdown:
                        break
                    time.sleep(1)
                continue

            # ---- EXIT MONITORING ----
            if in_position():
                if kite and kite.is_connected():
                    _monitor_and_exit(kite, config)
                else:
                    logger.warning("Kite not connected during exit check")

                for _ in range(poll_interval):
                    if _shutdown:
                        break
                    time.sleep(1)
                continue

            if kite and kite.is_connected():
                market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)

                if now < market_start:
                    from_date = (now - timedelta(days=1)).replace(hour=9, minute=15)
                else:
                    from_date = market_start

                to_date = now

                candles_raw = kite.get_historical_data(
                    _NIFTY_50_TOKEN,
                    interval="5minute",
                    from_date=from_date,
                    to_date=to_date,
                )

                candles = build_candles(candles_raw)

                if not candles:
                    for _ in range(poll_interval):
                        if _shutdown:
                            break
                        time.sleep(1)
                    continue

                vwap = compute_vwap(candles)
                if config.debug_mode and vwap is not None:
                    last_candle = candles[-1]
                    logger.debug(
                        "DEBUG: VWAP={:.2f} | Candle O={:.2f} H={:.2f} L={:.2f} "
                        "C={:.2f} V={} | candles={} | last_ts={}",
                        vwap,
                        last_candle.open,
                        last_candle.high,
                        last_candle.low,
                        last_candle.close,
                        last_candle.volume,
                        len(candles),
                        last_candle.timestamp.isoformat(),
                    )

                # ---- Market regime detection ----
                market_regime = market_condition_filter(candles, config)

                # ---- ORB state tracking ----
                _compute_orb_state(candles, config)

                # ---- Heartbeat ----
                _log_heartbeat(config, market_regime)

                # ---- Strategy dispatch ----
                signal = "WAIT"

                if strategy_name == "VWAP_PULLBACK":
                    if vwap is not None:
                        # In LOW_VOL regime, reduce VWAP pullback activity
                        if market_regime == "LOW_VOL":
                            logger.info(
                                "LOW_VOL regime — reducing VWAP pullback activity"
                            )

                        signal = vwap_pullback_signal(candles, vwap, config)

                elif strategy_name == "ORB":
                    signal = orb_breakout_signal(
                        candles,
                        candles[-1].close,
                        config,
                        state.get("orb_high"),
                        state.get("orb_low"),
                    )

                if config.debug_mode:
                    logger.debug(
                        "DEBUG: signal={} | vwap={:.2f} | strategy={} | regime={}",
                        signal,
                        vwap,
                        strategy_name,
                        market_regime,
                    )

                if signal not in ("TRADE_CALL", "TRADE_PUT"):
                    if signal != "WAIT":
                        logger.info(f"[SIGNAL] {strategy_name}: {signal}")
                else:
                    logger.info(f"[SIGNAL] {strategy_name}: {signal}")

                    allowed, reason = risk_manager.can_enter(signal)
                    if config.debug_mode:
                        logger.debug(
                            "DEBUG: risk_manager.can_enter({}) -> "
                            "allowed={}, reason={}",
                            signal,
                            allowed,
                            reason,
                        )
                    if not allowed:
                        logger.info(f"Risk gate blocked trade: {reason}")
                    else:
                        entry_candle_time = candles[-1].timestamp
                        if config.debug_mode:
                            logger.debug(
                                "DEBUG: entry_candle_time={} | "
                                "last_entry_candle_time={} | is_duplicate={}",
                                entry_candle_time,
                                _last_entry_candle_time,
                                entry_candle_time == _last_entry_candle_time,
                            )
                        if entry_candle_time == _last_entry_candle_time:
                            logger.info(
                                "[DEDUP] Candle {} already used for entry — skipping",
                                entry_candle_time,
                            )
                        else:
                            _execute_entry_signal(
                                signal,
                                "NIFTY",
                                candles[-1].close,
                                cache,
                                config,
                                strategy_name,
                                kite,
                                entry_candle_time=entry_candle_time,
                            )

            # Reset consecutive errors on successful cycle
            _consecutive_errors = 0

            for _ in range(poll_interval):
                if _shutdown:
                    break
                time.sleep(1)

        except Exception:
            _consecutive_errors += 1
            logger.exception(
                "Main loop error (consecutive_errors={}/{})",
                _consecutive_errors,
                _SAFE_MODE_THRESHOLD,
            )

            safe_delay = 60 if _consecutive_errors >= _SAFE_MODE_THRESHOLD else 1
            for _ in range(safe_delay):
                if _shutdown:
                    break
                time.sleep(1)

    if in_position():
        logger.warning(
            "Shutting down with open position — {} {} entry={}",
            state.get("symbol"),
            state.get("position_status"),
            state.get("entry_price"),
        )
    logger.info("Trading bot shut down cleanly")


def main():
    config = load_config_from_env()
    main_loop(config)


if __name__ == "__main__":
    main()
