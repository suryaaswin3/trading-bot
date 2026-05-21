"""Strategy abstraction layer — pluggable trading strategies with lifecycle hooks.

This package provides:
  - BaseStrategy ABC for defining strategy behavior
  - StrategyRegistry for runtime strategy management
  - DefaultStrategy as a migration bridge for existing behavior
"""

from ops_api.strategies.base import (
    BaseStrategy,
    OrderSpec,
    RiskConfig,
    StrategyMetadata,
    StrategyVerdict,
)
from ops_api.strategies.default import DefaultStrategy
from ops_api.strategies.registry import StrategyRegistry

__all__ = [
    "BaseStrategy",
    "DefaultStrategy",
    "OrderSpec",
    "RiskConfig",
    "StrategyMetadata",
    "StrategyRegistry",
    "StrategyVerdict",
]