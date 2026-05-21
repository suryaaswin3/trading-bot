# Phase 4 — Position + Portfolio State Refactor

> **Runtime evolution:** signal execution → portfolio orchestration

**Goal:** Replace single-position assumptions with true multi-position, multi-symbol portfolio state. Introduce robust position lifecycle tracking, realized/unrealized PnL aggregation, and portfolio-aware orchestration.

**Architecture:** New `PositionManager` service owns all position state. One net position per symbol with partial unique index (`WHERE status = 'open'`). Strategies express intent; ExecutionEngine + PositionManager own state mutation. Additive migration — old flow untouched when `position_manager` is None.

**Tech Stack:** Python 3.14, SQLite (WAL), dataclasses, threading.Lock, loguru, pytest

---

## Design Decisions

### Position Identity
One net position per symbol (Option A). Strategy attribution is metadata on executions/events, not position ownership. Multiple strategies may contribute signals; the position represents net account exposure.

### Lifecycle Model
Two states:
- **OPEN** — status='open', qty>0, side LONG/SHORT
- **CLOSED** — status='closed', closed_at set

Reversals close the existing lifecycle and open a new one (e.g., LONG 50 → SELL 80 → CLOSE LONG 50 → OPEN SHORT 30).

### Data Model

```sql
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    entry_price REAL NOT NULL DEFAULT 0.0,
    current_price REAL NOT NULL DEFAULT 0.0,
    realized_pnl REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'open',
    strategy_id TEXT DEFAULT '',
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_open_symbol
    ON positions(symbol) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
```

- Open positions: UPSERT by symbol (partial unique index enforces one open per symbol)
- Closed positions: INSERT-only historical rows (immutable)
- Realized PnL stored as cumulative total; individual trade PnL lives in executions/events

### Typed Models (not raw dicts)

- `PositionState` — dataclass: id, symbol, side, quantity, entry_price, current_price, realized_pnl, unrealized_pnl, status, strategy_id, opened_at, closed_at, updated_at
- `PortfolioSnapshot` — dataclass: positions (list of open), total_exposure, total_unrealized_pnl, total_realized_pnl, position_count, largest_position_symbol, largest_position_pct, updated_at
- `PositionMutationResult` — dataclass: mutation_id, symbol, action (open/adjust/close/reverse), side, quantity, price, realized_pnl_delta, prev_state, new_state

## Architecture

### New Files

| File | Responsibility |
|------|---------------|
| `ops_api/models/position.py` | PositionState, PortfolioSnapshot, PositionMutationResult models |
| `ops_api/position_manager.py` | PositionManager service — lifecycle, PnL, MTM, portfolio |

### Modified Files

| File | Changes |
|------|---------|
| `ops_api/db.py` | CREATE TABLE positions, CRUD methods |
| `ops_api/execution.py` | Post-fill PositionManager call, flatten() real impl |
| `ops_api/risk_engine.py` | Position-aware exposure + concentration checks |
| `ops_api/strategy_engine.py` | Typed PortfolioSnapshot wiring |
| `ops_api/main.py` | PositionManager wiring, dashboard fields |
| `trading-term/src/types/dashboard.ts` | Multi-position types |

## Data Flow

```
Signal → StrategyEngine.process()
  → Validate (ValidationPipeline — unchanged)
  → RiskEngine.check()
     [new: position concentration/exposure checks]
  → strategy.compute_order(signal, portfolio)
     [real PortfolioSnapshot, not empty dict]
  → strategy.validate_signal(signal, market_state, portfolio)
     [real PortfolioSnapshot, not empty dict]
  → ExecutionEngine.execute()
     → [order fills]
     → PositionManager.open_or_adjust(symbol, side, qty, price, strategy_id)
        → UPSERT positions table (open adjust) / INSERT (close)
        → Compute realized PnL on reduce/close
        → Write position_snapshot for equity curve history
        → Update bot_status for legacy dashboard compat
     → StrategyEngine.on_execution_result() callback
```

**Ownership boundaries:**
- Strategies: express intent via validate_signal() + compute_order()
- RiskEngine: gate decisions via position-aware checks
- ExecutionEngine: execute orders, delegate to PositionManager post-fill
- PositionManager: own all position state mutations

## PnL Model

**Realized PnL** (on reduce/close):
```
realized_pnl = (exit_price - entry_price) * close_qty * direction
  where direction = 1 for LONG, -1 for SHORT
```

**Unrealized PnL** (on MTM):
```
unrealized_pnl = (current_price - entry_price) * remaining_qty * direction
```

**Cumulative realized PnL** stored on position row (updated on each reduce/close event). Individual trade PnL stored via executions/events (append-only).

## Integration

### RiskEngine Additions
- Per-symbol position limit check (config: `max_position_per_symbol`)
- Total portfolio exposure cap (config: `max_portfolio_exposure`)
- Position concentration limit (config: `max_position_pct_of_portfolio`)
- All checks: additive, config-driven, no change when unconfigured

### Dashboard
- New `"positions"` field: all open positions with per-position PnL
- `position_manager.get_portfolio()` returns typed `PortfolioSnapshot`
- Legacy `"current_position"` preserved from bot_status
- `"position_history"` includes closed position records

### Rollback Safety
- `PositionManager` instantiated in lifespan, injected into ExecutionEngine
- ExecutionEngine: `position_manager` parameter defaults to None → no-op mode
- Old webhook → validate → execute path preserved verbatim
- Config flag (optional) to gate position tracking

## Testing

All existing tests pass unchanged. New tests:

- `tests/ops_api/test_position_manager.py` — lifecycle, PnL, MTM, reversal, edge cases
- `tests/ops_api/test_risk_engine_positions.py` — exposure/concentration checks
- `tests/ops_api/test_db_positions.py` — positions CRUD, partial unique index, UPSERT semantics