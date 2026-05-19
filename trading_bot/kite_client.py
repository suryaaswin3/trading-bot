"""Thin wrapper around Zerodha Kite Connect API."""

from __future__ import annotations

import time
from functools import wraps
from typing import Any

from kiteconnect.exceptions import InputException, TokenException
from loguru import logger

from trading_bot.config import TradingBotConfig

_RETRY_COUNT = 3
_RETRY_DELAY = 2  # seconds


# ========================
# RETRY DECORATOR
# ========================
def _api_retry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        last_error = None

        for attempt in range(_RETRY_COUNT):
            try:
                return func(*args, **kwargs)

            except (TokenException, InputException) as e:
                # ❌ DO NOT RETRY AUTH / INPUT ERRORS
                logger.error(f"API fatal error: {e}")
                raise e

            except Exception as e:
                last_error = e
                logger.warning(
                    "API call failed (attempt {}/{}): {}",
                    attempt + 1,
                    _RETRY_COUNT,
                    e,
                )

                if attempt < _RETRY_COUNT - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))

        raise last_error

    return wrapper


# ========================
# CLIENT
# ========================
class KiteClient:
    def __init__(self, config: TradingBotConfig) -> None:
        self.config = config

        self.kite: Any = None
        self._connected = False

    def connect(self) -> None:
        from kiteconnect import KiteConnect

        if not self.config.kite_api_key or not self.config.kite_access_token:
            raise RuntimeError("Missing API key or access token")

        self.kite = KiteConnect(api_key=self.config.kite_api_key)
        self.kite.set_access_token(self.config.kite_access_token)

        # 🔥 VERIFY CONNECTION
        try:
            self.kite.profile()
            self._connected = True
            logger.info("Kite client connected and verified")

        except Exception as e:
            self._connected = False
            logger.error(f"Kite auth failed: {e}")
            raise e

    def is_connected(self) -> bool:
        return self._connected and self.kite is not None

    # ========================
    # INSTRUMENTS
    # ========================
    @_api_retry
    def get_instruments(self, exchange: str = "NFO") -> list[dict[str, Any]]:
        if not self.kite:
            raise RuntimeError("Kite not connected")
        return self.kite.instruments(exchange)

    # ========================
    # MARKET DATA
    # ========================
    @_api_retry
    def get_ltp(self, instrument_tokens: list[int]) -> dict[int, float]:
        if not self.kite:
            raise RuntimeError("Kite not connected")

        data = self.kite.ltp(instrument_tokens)

        result = {}
        for k, v in data.items():
            try:
                token = int(k.split(":")[-1])
            except Exception:
                continue  # skip non-numeric keys safely

            result[token] = float(v.get("last_price", 0))

        return result

    @_api_retry
    def get_quote(self, instrument_tokens: list[int]) -> dict[int, dict[str, Any]]:
        if not self.kite:
            raise RuntimeError("Kite not connected")

        data = self.kite.quote(instrument_tokens)

        result = {}
        for k, v in data.items():
            try:
                token = int(k.split(":")[-1])
            except Exception:
                continue

            result[token] = v

        return result

    @_api_retry
    def get_historical_data(
        self,
        instrument_token: int,
        interval: str = "5minute",
        from_date=None,
        to_date=None,
    ) -> list[dict[str, Any]]:
        if not self.kite:
            raise RuntimeError("Kite not connected")

        return self.kite.historical_data(
            instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )

    # ========================
    # ORDERS
    # ========================
    @_api_retry
    def place_order(
        self,
        exchange: str,
        tradingsymbol: str,
        transaction_type: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
        product: str = "MIS",
        variety: str = "regular",
        tag: str = "",
    ) -> str:
        if not self.kite:
            raise RuntimeError("Kite not connected")

        result = self.kite.place_order(
            exchange=exchange,
            tradingsymbol=tradingsymbol,
            transaction_type=transaction_type,
            quantity=quantity,
            price=price,
            order_type=order_type,
            product=product,
            variety=variety,
            validity="DAY",
            tag=tag,
        )

        logger.info(
            "Order placed: {} {} x{} @ {}",
            transaction_type,
            tradingsymbol,
            quantity,
            price,
        )

        return str(result)

    @_api_retry
    def modify_order(
        self,
        order_id: str,
        price: float | None = None,
        quantity: int | None = None,
        order_type: str | None = None,
    ) -> str:
        if not self.kite:
            raise RuntimeError("Kite not connected")

        return str(
            self.kite.modify_order(
                variety=self.config.variety,
                order_id=order_id,
                price=price,
                quantity=quantity,
                order_type=order_type,
            )
        )

    @_api_retry
    def cancel_order(self, order_id: str) -> str:
        if not self.kite:
            raise RuntimeError("Kite not connected")

        return str(
            self.kite.cancel_order(
                variety=self.config.variety,
                order_id=order_id,
            )
        )

    @_api_retry
    def get_positions(self) -> list[dict[str, Any]]:
        if not self.kite:
            raise RuntimeError("Kite not connected")

        return self.kite.positions()
