"""Base types for the market data layer — BarSnapshot, OHLCVCache."""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BarSnapshot:
    """Immutable OHLCV bar with metadata."""

    symbol: str
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: float  # Unix epoch seconds


class OHLCVCache:
    """Thread-safe in-memory cache of OHLCV bars per (symbol, interval)."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._data: dict[tuple[str, str], tuple[list[BarSnapshot], float]] = {}

    def get(self, symbol: str, interval: str) -> list[BarSnapshot] | None:
        key = (symbol.upper(), interval)
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            bars, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._data[key]
                return None
            return bars

    def set(self, symbol: str, interval: str, bars: list[BarSnapshot]) -> None:
        key = (symbol.upper(), interval)
        with self._lock:
            self._data[key] = (bars, time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def keys(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._data.keys())