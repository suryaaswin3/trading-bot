from __future__ import annotations

from dataclasses import dataclass, field


class PositionSide:
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus:
    OPEN = "open"
    CLOSED = "closed"


class MutationAction:
    OPENED = "opened"
    ADJUSTED = "adjusted"
    REDUCED = "reduced"
    CLOSED = "closed"
    REVERSED = "reversed"


@dataclass
class PositionState:
    id: str
    symbol: str
    side: str  # LONG | SHORT
    quantity: int
    entry_price: float
    current_price: float
    realized_pnl: float
    unrealized_pnl: float
    status: str  # open | closed
    strategy_id: str
    opened_at: str
    closed_at: str | None
    updated_at: str


@dataclass
class PositionMutationResult:
    mutation_id: str
    symbol: str
    action: str  # opened | adjusted | reduced | closed | reversed
    previous_side: str
    previous_quantity: int
    new_side: str
    new_quantity: int
    price: float
    realized_pnl_delta: float
    previous_state: PositionState | None
    new_state: PositionState | None
    timestamp: str


@dataclass
class PortfolioSnapshot:
    positions: list[PositionState] = field(default_factory=list)
    total_exposure: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    position_count: int = 0
    largest_position_symbol: str = ""
    largest_position_pct: float = 0.0
    updated_at: str = ""