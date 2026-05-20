"""Base scanner abstraction — stateless, deterministic, pure."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ops_api.market_data.base import BarSnapshot
from ops_api.models import NormalizedSignal


@dataclass
class ScannerResult:
    """Result of a single scanner run. If signal is None, no actionable signal."""
    signal: NormalizedSignal | None = None

    @property
    def has_signal(self) -> bool:
        return self.signal is not None


class BaseScanner(ABC):
    """Abstract scanner that inspects indicator values and emits signals.

    Scanners are stateless and deterministic: given the same bars,
    they always produce the same result.
    """

    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = strategy_id

    @abstractmethod
    def scan(self, bars: list[BarSnapshot], symbol: str = "", interval: str = "") -> ScannerResult:
        """Analyse bars and return a signal if conditions are met."""
        ...