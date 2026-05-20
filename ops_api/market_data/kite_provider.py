"""Kite Connect backed market data provider."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from ops_api.market_data.base import BarSnapshot


def _parse_kite_timestamp(date_val: str | datetime) -> float:
    if isinstance(date_val, datetime):
        return date_val.timestamp()
    dt = datetime.fromisoformat(date_val)
    return dt.timestamp()


class KiteConnectMarketData:
    """Market data provider wrapping Kite Connect historical_data()."""

    def __init__(self, kite_client: Any) -> None:
        self._kite = kite_client

    def fetch(self, symbol: str, interval: str = "60", count: int = 100) -> list[BarSnapshot]:
        try:
            to_date = datetime.now(timezone.utc) + timedelta(days=1)
            from_date = to_date - timedelta(days=count)
            raw = self._kite.historical_data(symbol, from_date, to_date, interval)
            if not raw:
                return []
            return [BarSnapshot(
                symbol=symbol.upper(), interval=interval,
                open=float(item.get("open", 0)), high=float(item.get("high", 0)),
                low=float(item.get("low", 0)), close=float(item.get("close", 0)),
                volume=float(item.get("volume", 0)),
                timestamp=_parse_kite_timestamp(item["date"]),
            ) for item in raw]
        except Exception as e:
            logger.error("Failed to fetch market data for {} ({}): {}", symbol, interval, e)
            return []