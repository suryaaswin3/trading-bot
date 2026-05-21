"""Thread-safe in-memory registry of active strategies.

Strategies are registered once at application startup and can be
queried by ID or by matching against incoming signals.
"""

from __future__ import annotations

import threading
from typing import Any

from ops_api.strategies.base import BaseStrategy


class DuplicateStrategyError(KeyError):
    """Raised when registering a strategy with an already-registered ID."""


class StrategyRegistry:
    """Thread-safe registry mapping strategy IDs to BaseStrategy instances."""

    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}
        self._lock = threading.Lock()

    def register(self, strategy: BaseStrategy) -> None:
        sid = strategy.metadata.id
        if not sid:
            raise ValueError("Strategy must have a non-empty metadata.id")
        with self._lock:
            if sid in self._strategies:
                raise DuplicateStrategyError(f"Strategy '{sid}' is already registered")
            self._strategies[sid] = strategy

    def unregister(self, strategy_id: str) -> None:
        with self._lock:
            self._strategies.pop(strategy_id, None)

    def get(self, strategy_id: str) -> BaseStrategy | None:
        return self._strategies.get(strategy_id)

    def get_for_signal(self, signal: dict[str, Any]) -> BaseStrategy | None:
        for strategy in self._strategies.values():
            if strategy.matches(signal):
                return strategy
        return None

    def all(self) -> list[BaseStrategy]:
        return list(self._strategies.values())

    def clear(self) -> None:
        with self._lock:
            self._strategies.clear()