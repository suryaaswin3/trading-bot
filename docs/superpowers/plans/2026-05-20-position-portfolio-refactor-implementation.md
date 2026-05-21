# Phase 4 — Position + Portfolio State Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-position assumptions with true multi-position, multi-symbol portfolio state.

**Architecture:** PositionManager service owns all position lifecycle. One net position per symbol (partial unique index `WHERE status='open'`). Strategies express intent; ExecutionEngine + PositionManager own state mutation. Additive migration — old flow unchanged when `position_manager=None`.

**Tech Stack:** Python 3.14, SQLite (WAL), Pydantic BaseModel, threading.Lock, pytest

---

## Files Created/Modified

| File | Action |
|------|--------|
| `ops_api/models/position.py` | **Create** — PositionState, PortfolioSnapshot, PositionMutationResult |
| `ops_api/position_manager.py` | **Create** — PositionManager service class |
| `ops_api/db.py` | **Modify** — positions table schema + CRUD methods |
| `ops_api/risk_engine.py` | **Modify** — position-aware exposure + concentration checks |
| `ops_api/execution.py` | **Modify** — post-fill PositionManager integration, flatten() |
| `ops_api/strategy_engine.py` | **Modify** — real PortfolioSnapshot instead of empty dict |
| `ops_api/main.py` | **Modify** — PositionManager wiring, dashboard positions field |
| `trading-term/src/types/dashboard.ts` | **Modify** — add PositionState, PortfolioSnapshot types |
| `tests/ops_api/test_position_manager.py` | **Create** |
| `tests/ops_api/test_db.py` | **Modify** — add positions CRUD tests |
| `tests/ops_api/test_risk_engine.py` | **Modify** — add position-aware risk tests |

---

### Task 1: Position data models

**Files:**
- Create: `ops_api/models/position.py`
- No test file needed (plain data models)

**Models:**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PositionSide:
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


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
```

- [ ] **Step 1: Create `ops_api/models/position.py`** with the above models.

- [ ] **Step 2: Verify import works**

Run: `uv run python -c "from ops_api.models.position import PositionState, PortfolioSnapshot, PositionMutationResult; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ops_api/models/position.py
git commit -m "feat: add position data models (PositionState, PortfolioSnapshot, PositionMutationResult)"
```

---

### Task 2: DB positions schema + CRUD

**Files:**
- Modify: `ops_api/db.py`

**Schema (add to init_schema or _SCHEMA_SQL):**

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

Note: `init_schema()` calls `_SCHEMA_SQL` via `conn.executescript()` at line 250. Add the positions table DDL inside `_SCHEMA_SQL` string (before the view at line 207), OR add as a migration in init_schema() after the existing ALTER TABLE block at line 266. Choose the migration approach:

```python
# In init_schema(), after existing ALTER TABLE migrations (line 266):
conn.execute("""
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
    )
""")
conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_open_symbol ON positions(symbol) WHERE status = 'open'")
conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)")
```

**DB methods (add after position_snapshots section, around line 527):**

```python
import uuid

def upsert_open_position(self, symbol: str, side: str, quantity: int,
                         entry_price: float, strategy_id: str = "") -> dict:
    """UPSERT an open position. Returns the row as dict."""
    now = datetime.utcnow().isoformat()
    pos_id = str(uuid.uuid4())
    conn = self._connect()
    conn.execute("""
        INSERT INTO positions (id, symbol, side, quantity, entry_price,
            current_price, realized_pnl, unrealized_pnl, status,
            strategy_id, opened_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'open', ?, ?, ?)
        ON CONFLICT(symbol) WHERE status = 'open'
        DO UPDATE SET
            side = excluded.side,
            quantity = excluded.quantity,
            entry_price = excluded.entry_price,
            current_price = excluded.current_price,
            strategy_id = excluded.strategy_id,
            updated_at = excluded.updated_at
    """, (pos_id, symbol, side, quantity, entry_price,
          entry_price, strategy_id, now, now))
    conn.commit()
    return self.get_position_by_symbol(symbol)

def close_position(self, symbol: str, exit_price: float) -> dict:
    """Close an open position. Returns the updated row."""
    now = datetime.utcnow().isoformat()
    open_pos = self.get_position_by_symbol(symbol)
    if not open_pos:
        raise ValueError(f"No open position for {symbol}")
    # Compute realized PnL on close
    direction = 1 if open_pos["side"] == "LONG" else -1
    realized = (exit_price - open_pos["entry_price"]) * open_pos["quantity"] * direction
    conn = self._connect()
    conn.execute("""
        UPDATE positions SET
            status = 'closed',
            closed_at = ?,
            current_price = ?,
            realized_pnl = realized_pnl + ?,
            updated_at = ?
        WHERE id = ? AND status = 'open'
    """, (now, exit_price, realized, now, open_pos["id"]))
    conn.commit()
    # Fetch and return updated row
    return self._fetch_one("SELECT * FROM positions WHERE id = ?", (open_pos["id"],))

def reduce_position(self, symbol: str, reduce_qty: int,
                    exit_price: float) -> dict:
    """Reduce an open position by given qty. Returns updated row."""
    open_pos = self.get_position_by_symbol(symbol)
    if not open_pos:
        raise ValueError(f"No open position for {symbol}")
    if reduce_qty >= open_pos["quantity"]:
        raise ValueError("Use close_position() for full close")
    direction = 1 if open_pos["side"] == "LONG" else -1
    realized = (exit_price - open_pos["entry_price"]) * reduce_qty * direction
    new_qty = open_pos["quantity"] - reduce_qty
    now = datetime.utcnow().isoformat()
    conn = self._connect()
    conn.execute("""
        UPDATE positions SET
            quantity = ?,
            current_price = ?,
            realized_pnl = realized_pnl + ?,
            updated_at = ?
        WHERE id = ? AND status = 'open'
    """, (new_qty, exit_price, realized, now, open_pos["id"]))
    conn.commit()
    return self._fetch_one("SELECT * FROM positions WHERE id = ?", (open_pos["id"],))

def update_position_mtm(self, symbol: str, current_price: float) -> dict:
    """Update current_price and unrealized_pnl only. Never mutates realized_pnl."""
    open_pos = self.get_position_by_symbol(symbol)
    if not open_pos:
        raise ValueError(f"No open position for {symbol}")
    direction = 1 if open_pos["side"] == "LONG" else -1
    unrealized = (current_price - open_pos["entry_price"]) * open_pos["quantity"] * direction
    now = datetime.utcnow().isoformat()
    conn = self._connect()
    conn.execute("""
        UPDATE positions SET
            current_price = ?,
            unrealized_pnl = ?,
            updated_at = ?
        WHERE id = ? AND status = 'open'
    """, (current_price, unrealized, now, open_pos["id"]))
    conn.commit()
    return self._fetch_one("SELECT * FROM positions WHERE id = ?", (open_pos["id"],))

def get_position_by_symbol(self, symbol: str) -> dict | None:
    """Get open position for symbol, or None."""
    return self._fetch_one(
        "SELECT * FROM positions WHERE symbol = ? AND status = 'open'",
        (symbol,)
    )

def get_all_open_positions(self) -> list[dict]:
    """Get all currently open positions."""
    return self._fetch_all(
        "SELECT * FROM positions WHERE status = 'open' ORDER BY symbol"
    )

def get_closed_positions(self, limit: int = 50) -> list[dict]:
    """Get closed position history."""
    return self._fetch_all(
        "SELECT * FROM positions WHERE status = 'closed' ORDER BY closed_at DESC LIMIT ?",
        (limit,)
    )

def insert_position_snapshot_for_compat(self, symbol: str, side: str,
                                         quantity: int, entry_price: float,
                                         current_price: float,
                                         realized_pnl: float,
                                         unrealized_pnl: float) -> None:
    """Write a position_snapshot row for equity curve continuity (backward compat)."""
    conn = self._connect()
    conn.execute("""
        INSERT INTO position_snapshots
            (id, symbol, side, quantity, entry_price, current_price,
             unrealized_pnl, realized_pnl, trades_today, daily_pnl, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
    """, (str(uuid.uuid4()), symbol, side, quantity, entry_price,
          current_price, unrealized_pnl, realized_pnl,
          datetime.utcnow().isoformat()))
    conn.commit()

def update_bot_status_position_compat(self, symbol: str, side: str,
                                       quantity: int, entry_price: float) -> None:
    """Update bot_status singleton with primary position for legacy compat."""
    status = self.get_bot_status() or {}
    status["current_symbol"] = symbol
    status["position_side"] = side
    status["position_qty"] = quantity
    status["position_entry_price"] = entry_price
    self.upsert_bot_status(status)
```

**Note about `_fetch_one` and `_fetch_all`:** Check if these helper methods exist. If not, use the existing pattern:

```python
def _fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
    conn = self._connect()
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return dict(row)

def _fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
    conn = self._connect()
    return [dict(row) for row in conn.execute(sql, params).fetchall()]
```

Add these helpers if they don't exist (search for `_fetch_one` and `_fetch_all` first).

This is the most detailed task. The subagent should read `ops_api/db.py` carefully, understand the _connect()/row-to-dict patterns, and match them exactly.

- [ ] **Step 1: Read `ops_api/db.py`** to understand _connect(), row-to-dict patterns, and where to add schema + methods.

- [ ] **Step 2: Add positions table** to init_schema() as a migration after existing ALTER TABLE statements.

- [ ] **Step 3: Add _fetch_one / _fetch_all helper methods** if they don't exist.

- [ ] **Step 4: Add DB CRUD methods** for positions (upsert, close, reduce, MTM, get, compat helpers).

- [ ] **Step 5: Write a quick smoke test**

Run: `uv run python -c "from ops_api.db import DatabaseManager; import tempfile; import os; p=tempfile.mktemp(suffix='.db'); db=DatabaseManager(p); db.init_schema(); db.upsert_open_position('NIFTY','LONG',50,24500); pos=db.get_position_by_symbol('NIFTY'); assert pos['side']=='LONG'; print('POSITIONS OK')"`
Expected: `POSITIONS OK`

- [ ] **Step 6: Commit**

```bash
git add ops_api/db.py
git commit -m "feat: add positions table schema and CRUD methods"
```

---

### Task 3: PositionManager service

**Files:**
- Create: `ops_api/position_manager.py`
- Reference: `ops_api/models/position.py`

**Implementation:**

```python
"""PositionManager — single source of truth for position lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ops_api.db import DatabaseManager
from ops_api.models.position import (
    MutationAction,
    PositionMutationResult,
    PortfolioSnapshot,
    PositionState,
)


def _row_to_state(row: dict[str, Any]) -> PositionState:
    return PositionState(
        id=row["id"],
        symbol=row["symbol"],
        side=row["side"],
        quantity=row["quantity"],
        entry_price=row["entry_price"],
        current_price=row["current_price"],
        realized_pnl=row["realized_pnl"],
        unrealized_pnl=row["unrealized_pnl"],
        status=row["status"],
        strategy_id=row.get("strategy_id", ""),
        opened_at=row["opened_at"],
        closed_at=row.get("closed_at"),
        updated_at=row["updated_at"],
    )


class PositionManager:
    """Single source of truth for position lifecycle.

    All position mutations flow through this class.
    Strategies express intent only — PositionManager owns state.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ── Lifecycle ──────────────────────────────────────────────────

    def open_or_adjust(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        strategy_id: str = "",
    ) -> PositionMutationResult:
        """Open, adjust, reduce, close, or reverse a position.

        Net-account semantics:
        - Same side as existing → adjust entry price (weighted average)
        - Opposite side, smaller qty → reduce position, realize PnL
        - Opposite side, equal qty → close position, realize PnL
        - Opposite side, larger qty → close + reverse, realize PnL on full close
        """
        existing = self._db.get_position_by_symbol(symbol)
        prev = _row_to_state(existing) if existing else None

        if existing is None:
            # No existing position — open new
            self._db.upsert_open_position(symbol, side, quantity, price, strategy_id)
            self._db.insert_position_snapshot_for_compat(symbol, side, quantity, price, price, 0.0, 0.0)
            self._db.update_bot_status_position_compat(symbol, side, quantity, price)
            new = _row_to_state(self._db.get_position_by_symbol(symbol))
            return PositionMutationResult(
                mutation_id=str(uuid.uuid4()),
                symbol=symbol,
                action=MutationAction.OPENED,
                previous_side="NONE",
                previous_quantity=0,
                new_side=side,
                new_quantity=quantity,
                price=price,
                realized_pnl_delta=0.0,
                previous_state=prev,
                new_state=new,
                timestamp=datetime.utcnow().isoformat(),
            )

        if existing["side"] == side:
            # Same side — adjust (weighted average entry price)
            total_qty = existing["quantity"] + quantity
            avg_entry = ((existing["entry_price"] * existing["quantity"]) + (price * quantity)) / total_qty
            self._db.upsert_open_position(symbol, side, total_qty, avg_entry, strategy_id)
            self._db.insert_position_snapshot_for_compat(symbol, side, total_qty, avg_entry, price, 0.0, 0.0)
            self._db.update_bot_status_position_compat(symbol, side, total_qty, avg_entry)
            new = _row_to_state(self._db.get_position_by_symbol(symbol))
            return PositionMutationResult(
                mutation_id=str(uuid.uuid4()),
                symbol=symbol,
                action=MutationAction.ADJUSTED,
                previous_side=existing["side"],
                previous_quantity=existing["quantity"],
                new_side=side,
                new_quantity=total_qty,
                price=price,
                realized_pnl_delta=0.0,
                previous_state=prev,
                new_state=new,
                timestamp=datetime.utcnow().isoformat(),
            )

        # Opposite side — reduce, close, or reverse
        direction = 1 if side == "SHORT" else -1  # selling to close LONG, buying to close SHORT
        # direction = 1 when closing LONG (selling): PnL = (exit_price - entry_price) * qty * 1
        # direction = -1 when closing SHORT (buying): PnL = (exit_price - entry_price) * qty * -1 = -(exit - entry) * qty
        # Simplify: for closing LONG, direction=1. For closing SHORT, direction=-1.
        # This matches: realized = (price - entry) * close_qty * (1 for LONG close, -1 for SHORT close)
        # Which simplifies to: realized = (price - entry) * close_qty * (side == "SHORT" ? -1 : 1)

        if quantity < existing["quantity"]:
            # Partial close (reduce)
            realized = (price - existing["entry_price"]) * quantity * direction
            self._db.reduce_position(symbol, quantity, price)
            self._db.insert_position_snapshot_for_compat(
                symbol, existing["side"], existing["quantity"] - quantity,
                existing["entry_price"], price, realized, 0.0
            )
            updated = self._db.get_position_by_symbol(symbol)
            self._db.update_bot_status_position_compat(symbol, updated["side"], updated["quantity"], updated["entry_price"])
            new = _row_to_state(updated)
            return PositionMutationResult(
                mutation_id=str(uuid.uuid4()),
                symbol=symbol,
                action=MutationAction.REDUCED,
                previous_side=existing["side"],
                previous_quantity=existing["quantity"],
                new_side=existing["side"],
                new_quantity=existing["quantity"] - quantity,
                price=price,
                realized_pnl_delta=realized,
                previous_state=prev,
                new_state=new,
                timestamp=datetime.utcnow().isoformat(),
            )

        # quantity >= existing["quantity"] — full close, possibly reverse
        realized = (price - existing["entry_price"]) * existing["quantity"] * direction
        self._db.close_position(symbol, price)
        self._db.insert_position_snapshot_for_compat(
            symbol, existing["side"], 0, existing["entry_price"], price, realized, 0.0
        )
        self._db.update_bot_status_position_compat(symbol, "NONE", 0, 0.0)

        reverse_qty = quantity - existing["quantity"]
        if reverse_qty > 0:
            # Reverse: close old → open new opposite
            new_side = "SHORT" if side == "SELL" else "LONG"
            self._db.upsert_open_position(symbol, new_side, reverse_qty, price, strategy_id)
            self._db.insert_position_snapshot_for_compat(symbol, new_side, reverse_qty, price, price, 0.0, 0.0)
            self._db.update_bot_status_position_compat(symbol, new_side, reverse_qty, price)
            new_state = _row_to_state(self._db.get_position_by_symbol(symbol))
            action = MutationAction.REVERSED
        else:
            new_state = None
            action = MutationAction.CLOSED

        return PositionMutationResult(
            mutation_id=str(uuid.uuid4()),
            symbol=symbol,
            action=action,
            previous_side=existing["side"],
            previous_quantity=existing["quantity"],
            new_side=new_state.side if new_state else "NONE",
            new_quantity=reverse_qty if new_state else 0,
            price=price,
            realized_pnl_delta=realized,
            previous_state=prev,
            new_state=new_state,
            timestamp=datetime.utcnow().isoformat(),
        )

    def close(self, symbol: str, exit_price: float) -> PositionMutationResult:
        """Force-close an open position. No reverse."""
        existing = self._db.get_position_by_symbol(symbol)
        if existing is None:
            raise ValueError(f"No open position for {symbol}")
        prev = _row_to_state(existing)
        direction = 1 if existing["side"] == "LONG" else -1
        realized = (exit_price - existing["entry_price"]) * existing["quantity"] * direction
        self._db.close_position(symbol, exit_price)
        self._db.insert_position_snapshot_for_compat(
            symbol, existing["side"], 0, existing["entry_price"], exit_price, realized, 0.0
        )
        self._db.update_bot_status_position_compat(symbol, "NONE", 0, 0.0)
        return PositionMutationResult(
            mutation_id=str(uuid.uuid4()),
            symbol=symbol,
            action=MutationAction.CLOSED,
            previous_side=existing["side"],
            previous_quantity=existing["quantity"],
            new_side="NONE",
            new_quantity=0,
            price=exit_price,
            realized_pnl_delta=realized,
            previous_state=prev,
            new_state=None,
            timestamp=datetime.utcnow().isoformat(),
        )

    # ── Read ───────────────────────────────────────────────────────

    def get_position(self, symbol: str) -> PositionState | None:
        row = self._db.get_position_by_symbol(symbol)
        return _row_to_state(row) if row else None

    def get_all_positions(self) -> list[PositionState]:
        rows = self._db.get_all_open_positions()
        return [_row_to_state(r) for r in rows]

    def get_closed_positions(self, limit: int = 50) -> list[PositionState]:
        rows = self._db.get_closed_positions(limit)
        return [_row_to_state(r) for r in rows]

    # ── MTM ────────────────────────────────────────────────────────

    def mark_to_market(self, symbol: str, current_price: float) -> PositionState:
        """Update current_price and unrealized_pnl only. Never mutates realized_pnl."""
        self._db.update_position_mtm(symbol, current_price)
        return _row_to_state(self._db.get_position_by_symbol(symbol))

    # ── Portfolio ──────────────────────────────────────────────────

    def get_portfolio(self) -> PortfolioSnapshot:
        positions = self.get_all_positions()
        total_exposure = sum(p.quantity * p.current_price for p in positions)
        total_unrealized = sum(p.unrealized_pnl for p in positions)
        total_realized = sum(p.realized_pnl for p in positions)
        position_count = len(positions)
        largest = max(positions, key=lambda p: p.quantity * p.current_price) if positions else None
        largest_pct = ((largest.quantity * largest.current_price) / total_exposure * 100) if largest and total_exposure > 0 else 0.0
        return PortfolioSnapshot(
            positions=positions,
            total_exposure=total_exposure,
            total_unrealized_pnl=total_unrealized,
            total_realized_pnl=total_realized,
            position_count=position_count,
            largest_position_symbol=largest.symbol if largest else "",
            largest_position_pct=largest_pct,
            updated_at=datetime.utcnow().isoformat(),
        )

    def flatten(self) -> list[PositionMutationResult]:
        """Close all open positions."""
        positions = self.get_all_positions()
        results = []
        for pos in positions:
            results.append(self.close(pos.symbol, pos.current_price))
        return results
```

- [ ] **Step 1: Write the failing test** (see Task 9 for full test suite — for now write a minimal smoke test)

- [ ] **Step 2: Create `ops_api/position_manager.py`** with the implementation above.

- [ ] **Step 3: Smoke test**

Run: `uv run python -c "from ops_api.position_manager import PositionManager; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Functional test**

Run: `uv run python -c "
import tempfile
from ops_api.db import DatabaseManager
from ops_api.position_manager import PositionManager
p=tempfile.mktemp(suffix='.db')
db=DatabaseManager(p); db.init_schema()
pm=PositionManager(db)
r=pm.open_or_adjust('NIFTY','LONG',50,24500)
assert r.action=='opened', r.action
r2=pm.open_or_adjust('NIFTY','SHORT',20,24600)
assert r2.action=='reduced', r2.action
r3=pm.close('NIFTY',24700)
assert r3.action=='closed', r3.action
pf=pm.get_portfolio()
assert pf.position_count==0
print('ALL POSITION MANAGER TESTS PASSED')
"`
Expected: `ALL POSITION MANAGER TESTS PASSED`

- [ ] **Step 5: Commit**

```bash
git add ops_api/position_manager.py
git commit -m "feat: add PositionManager service with lifecycle, MTM, and portfolio aggregation"
```

---

### Task 4: RiskEngine position-aware checks

**Files:**
- Modify: `ops_api/risk_engine.py`

**Implementation changes:**

```python
def __init__(self, db: DatabaseManager, position_manager: PositionManager | None = None) -> None:
    self._db = db
    self._position_manager = position_manager
```

Add to `check()` method, after existing kill-switch check and before trades-per-day check:

```python
# Position-aware checks
if self._position_manager is not None:
    portfolio = self._position_manager.get_portfolio()
    # Check if symbol already has position and signal conflicts
    existing = self._position_manager.get_position(signal.get("symbol", ""))
    if existing is not None:
        # Only warn if same symbol, different side — risk engine doesn't BLOCK
        # reversals (they're valid trading actions), but it can enforce limits
        pass  # Future: max_position_size check per symbol
```

Actually, let me think about what position-aware checks to add. The design spec says:
- Per-symbol position limit check (config: max_position_per_symbol)
- Total portfolio exposure cap (config: max_portfolio_exposure)
- Position concentration limit (config: max_position_pct_of_portfolio)

These need config values. The RiskEngine currently doesn't take config. Let me add config and position_manager optional params.

Let me write cleaner code:

```python
from __future__ import annotations

from typing import Any

from loguru import logger

from ops_api.db import DatabaseManager
from ops_api.position_manager import PositionManager


class RiskEngine:
    """Pre-execution risk gates with position-aware checks."""

    def __init__(
        self,
        db: DatabaseManager,
        position_manager: PositionManager | None = None,
        max_position_per_symbol: int = 0,
        max_portfolio_exposure: float = 0.0,
        max_position_pct: float = 0.0,
    ) -> None:
        self._db = db
        self._position_manager = position_manager
        self._max_position_per_symbol = max_position_per_symbol
        self._max_portfolio_exposure = max_portfolio_exposure
        self._max_position_pct = max_position_pct

    def check(self, signal: dict[str, Any], strategy: BaseStrategy | None = None) -> bool:
        """Run all risk gates. Returns True if signal passes."""
        # 1. Kill switch
        ks = self._db.get_kill_switch_state()
        if ks.get("active", False):
            logger.warning("Risk block: kill switch active")
            return False

        # 2. Position-aware checks
        if self._position_manager is not None:
            symbol = signal.get("symbol", "")
            side = signal.get("side", "")
            qty = signal.get("quantity", 0)
            price = signal.get("price", 0.0)

            existing = self._position_manager.get_position(symbol)

            # Per-symbol position limit
            if self._max_position_per_symbol > 0:
                current_qty = existing.quantity if existing else 0
                if side == existing.side if existing else False:
                    new_qty = current_qty + qty
                elif existing and side != existing.side:
                    new_qty = abs(current_qty - qty)
                else:
                    new_qty = qty
                if new_qty > self._max_position_per_symbol:
                    logger.warning("Risk block: {} position {} exceeds limit {}", symbol, new_qty, self._max_position_per_symbol)
                    return False

            # Portfolio exposure cap
            if self._max_portfolio_exposure > 0:
                portfolio = self._position_manager.get_portfolio()
                new_exposure = portfolio.total_exposure + (qty * price)
                if new_exposure > self._max_portfolio_exposure:
                    logger.warning("Risk block: portfolio exposure {} exceeds cap {}", new_exposure, self._max_portfolio_exposure)
                    return False

            # Position concentration limit
            if self._max_position_pct > 0 and existing:
                portfolio = self._position_manager.get_portfolio()
                pos_value = existing.quantity * existing.current_price
                pct = (pos_value / portfolio.total_exposure * 100) if portfolio.total_exposure > 0 else 0
                if pct > self._max_position_pct:
                    logger.warning("Risk block: {} concentration {:.1f}% exceeds limit {}%", symbol, pct, self._max_position_pct)
                    return False

        # 3. Strategy-level checks
        if strategy is None:
            return True

        if strategy.risk_config is None:
            return True

        bot_status = self._db.get_bot_status() or {}

        # 4. Max trades per day
        max_trades = strategy.risk_config.get("max_trades_per_day", 0)
        if max_trades > 0:
            trades_today = bot_status.get("trades_today", 0)
            if trades_today >= max_trades:
                logger.warning("Risk block: trades today {} >= limit {}", trades_today, max_trades)
                return False

        # 5. Max daily loss
        max_loss = strategy.risk_config.get("max_daily_loss", 0.0)
        if max_loss < 0:
            daily_pnl = bot_status.get("daily_pnl", 0.0)
            if daily_pnl <= max_loss:
                logger.warning("Risk block: daily PnL {} exceeds loss limit {}", daily_pnl, max_loss)
                return False

        return True
```

This preserves the old `RiskEngine(db)` constructor (position_manager defaults to None), so existing code continues to work.

- [ ] **Step 1: Read `ops_api/risk_engine.py`** to understand current constructor + check() logic.

- [ ] **Step 2: Modify `ops_api/risk_engine.py`** with position-aware checks.

- [ ] **Step 3: Run existing risk engine tests**

Run: `uv run pytest tests/ops_api/test_risk_engine.py -v`
Expected: All existing tests pass (no regressions)

- [ ] **Step 4: Commit**

```bash
git add ops_api/risk_engine.py
git commit -m "feat: add position-aware risk checks (exposure, concentration, position limits)"
```

---

### Task 5: ExecutionEngine integration

**Files:**
- Modify: `ops_api/execution.py`

**Implementation changes:**

```python
# In __init__:
def __init__(self, config, db, kite_client=None, position_manager=None):
    ...
    self._position_manager = position_manager

# In execute(), after order fills (around line 215, after broker fills):
if self._position_manager is not None and result.get("status") == "filled":
    try:
        mutation = self._position_manager.open_or_adjust(
            symbol=result.get("symbol", signal.get("symbol", "")),
            side=result.get("side", signal.get("side", "")),
            quantity=result.get("filled_quantity", signal.get("quantity", 0)),
            price=result.get("filled_price", signal.get("price", 0.0)),
            strategy_id=signal.get("strategy", ""),
        )
        result["position_mutation"] = {
            "action": mutation.action,
            "realized_pnl_delta": mutation.realized_pnl_delta,
        }
    except Exception:
        logger.exception("Position mutation failed after fill for {}", signal.get("symbol"))

# flatten() — real implementation:
def flatten(self) -> dict[str, Any]:
    """Close all open positions (emergency flatten)."""
    logger.warning("FLATTEN command received — closing all positions")
    if self._position_manager is None:
        return {"status": "completed", "action": "flatten", "detail": "No position manager configured"}
    results = self._position_manager.flatten()
    return {
        "status": "completed",
        "action": "flatten",
        "detail": f"Closed {len(results)} position(s)",
        "closed_positions": [
            {"symbol": r.symbol, "realized_pnl": r.realized_pnl_delta} for r in results
        ],
    }
```

- [ ] **Step 1: Read `ops_api/execution.py`** to understand execute() flow, __init__(), flatten().

- [ ] **Step 2: Add position_manager parameter** to __init__().

- [ ] **Step 3: Add post-fill PositionManager call** in execute() after broker fill.

- [ ] **Step 4: Implement flatten()** with real close logic.

- [ ] **Step 5: Run execution tests**

Run: `uv run pytest tests/ops_api/test_execution.py -v`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add ops_api/execution.py
git commit -m "feat: integrate PositionManager into ExecutionEngine (post-fill mutation, flatten)"
```

---

### Task 6: StrategyEngine portfolio wiring

**Files:**
- Modify: `ops_api/strategy_engine.py`

**Implementation changes:**

```python
# In __init__, add optional position_manager param:
def __init__(self, registry, validator, executor, risk_engine, db, position_manager=None):
    ...
    self._position_manager = position_manager

# In process(), replace:
#   portfolio: dict[str, Any] = {}
# with:
if self._position_manager is not None:
    portfolio = self._position_manager.get_portfolio()
else:
    portfolio = PortfolioSnapshot()  # from ops_api.models.position
```

Also need to import PortfolioSnapshot. And since the `process()` signature returns dict (not typed), enrich the result dict with portfolio info.

- [ ] **Step 1: Read `ops_api/strategy_engine.py`** to understand process() flow.

- [ ] **Step 2: Add position_manager parameter** to __init__().

- [ ] **Step 3: Replace empty portfolio** with real PortfolioSnapshot.

- [ ] **Step 4: Run strategy engine tests**

Run: `uv run pytest tests/ops_api/test_strategy_engine.py -v`
Expected: All existing tests pass

- [ ] **Step 5: Commit**

```bash
git add ops_api/strategy_engine.py
git commit -m "feat: wire real PortfolioSnapshot into StrategyEngine instead of empty dict"
```

---

### Task 7: main.py wiring

**Files:**
- Modify: `ops_api/main.py`

**Changes:**

1. Import PositionManager:
```python
from ops_api.position_manager import PositionManager
```

2. Add global variable:
```python
position_manager: PositionManager | None = None
```

3. In lifespan, after `db` is initialized and before `executor`:
```python
position_manager = PositionManager(db)
```

4. Pass `position_manager` to RiskEngine, StrategyEngine, ExecutionEngine:
```python
_risk_engine = RiskEngine(db, position_manager=position_manager)
strategy_engine = StrategyEngine(
    registry=_registry,
    validator=validator,
    executor=executor,
    risk_engine=_risk_engine,
    db=db,
    position_manager=position_manager,
)
executor = ExecutionEngine(config, db, kite_client=kite_client, position_manager=position_manager)
```

5. Add to dashboard/data:
```python
"positions": position_manager.get_all_positions() if position_manager is not None else [],
"portfolio_snapshot": position_manager.get_portfolio() if position_manager is not None else {},
```

Import PositionState and PortfolioSnapshot for serialization. Since these are dataclasses, they may need custom serialization for FastAPI (which uses jsonable_encoder). Actually, FastAPI handles dataclasses just fine with `response_model` or via `jsonable_encoder`. But the existing pattern returns raw dicts. Let me use dataclasses.asdict() to convert:

```python
import dataclasses
...
"positions": [dataclasses.asdict(p) for p in position_manager.get_all_positions()] if position_manager is not None else [],
"portfolio_snapshot": dataclasses.asdict(position_manager.get_portfolio()) if position_manager is not None else {},
```

6. Add to dashboard/analytics:
```python
"closed_positions": position_manager.get_closed_positions(limit=50) if position_manager is not None else [],
```

- [ ] **Step 1: Read `ops_api/main.py`** to find exact integration points.

- [ ] **Step 2: Wire PositionManager** into imports, globals, lifespan.

- [ ] **Step 3: Add dashboard fields** for positions and portfolio_snapshot.

- [ ] **Step 4: Run import check**

Run: `uv run python -c "from ops_api.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ops_api/main.py
git commit -m "feat: wire PositionManager, RiskEngine, StrategyEngine, dashboard fields"
```

---

### Task 8: Dashboard Types (TypeScript)

**Files:**
- Modify: `trading-term/src/types/dashboard.ts`

**Changes (add after CurrentPosition):**

```typescript
export interface PositionState {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  realized_pnl: number;
  unrealized_pnl: number;
  status: string;
  strategy_id: string;
  opened_at: string;
  closed_at: string | null;
  updated_at: string;
}

export interface PortfolioSnapshot {
  positions: PositionState[];
  total_exposure: number;
  total_unrealized_pnl: number;
  total_realized_pnl: number;
  position_count: number;
  largest_position_symbol: string;
  largest_position_pct: number;
  updated_at: string;
}
```

Also update DashboardData interface to include optional positions and portfolio_snapshot fields.

- [ ] **Step 1: Read `trading-term/src/types/dashboard.ts`** to understand current interfaces.

- [ ] **Step 2: Add new interfaces.**

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd trading-term && npx tsc --noEmit 2>&1 || echo "TypeScript check skipped if tsc not available"`
Expected: No errors (or skip if no tsc)

- [ ] **Step 4: Commit**

```bash
git add trading-term/src/types/dashboard.ts
git commit -m "feat: add PositionState and PortfolioSnapshot TypeScript types"
```

---

### Task 9: PositionManager tests

**Files:**
- Create: `tests/ops_api/test_position_manager.py`

**Test structure (use existing test patterns from test_portfolio.py):**

```python
"""Tests for PositionManager lifecycle, PnL, MTM, reversal."""

from __future__ import annotations

import json
import tempfile
from unittest.mock import patch

import pytest

from ops_api.db import DatabaseManager
from ops_api.models.position import MutationAction, PositionState
from ops_api.position_manager import PositionManager


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = DatabaseManager(path)
    db.init_schema()
    yield db


@pytest.fixture
def pm(db):
    return PositionManager(db)


class TestOpenAdjust:
    def test_open_new_position(self, pm):
        r = pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0, strategy_id="momentum")
        assert r.action == MutationAction.OPENED
        assert r.symbol == "NIFTY"
        assert r.new_side == "LONG"
        assert r.new_quantity == 50
        assert r.realized_pnl_delta == 0.0
        pos = pm.get_position("NIFTY")
        assert pos is not None
        assert pos.side == "LONG"
        assert pos.quantity == 50
        assert pos.entry_price == 24500.0

    def test_adjust_same_side(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        r = pm.open_or_adjust("NIFTY", "LONG", 50, 24600.0)
        assert r.action == MutationAction.ADJUSTED
        assert r.new_quantity == 100
        # Weighted average: (50*24500 + 50*24600) / 100 = 24550
        assert r.new_state.entry_price == 24550.0

    def test_reduce_opposite_side_smaller(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        r = pm.open_or_adjust("NIFTY", "SHORT", 20, 24700.0)
        assert r.action == MutationAction.REDUCED
        assert r.realized_pnl_delta == pytest.approx((24700 - 24500) * 20 * 1)  # 4000
        pos = pm.get_position("NIFTY")
        assert pos.quantity == 30  # 50 - 20

    def test_close_opposite_side_equal(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        r = pm.open_or_adjust("NIFTY", "SHORT", 50, 24700.0)
        assert r.action == MutationAction.CLOSED
        assert r.realized_pnl_delta == pytest.approx((24700 - 24500) * 50 * 1)
        pos = pm.get_position("NIFTY")
        assert pos is None

    def test_reverse_opposite_side_larger(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        r = pm.open_or_adjust("NIFTY", "SHORT", 80, 24700.0)
        assert r.action == MutationAction.REVERSED
        # Realized on 50: (24700-24500)*50 = 10000
        assert r.realized_pnl_delta == pytest.approx(10000.0)
        pos = pm.get_position("NIFTY")
        assert pos is not None
        assert pos.side == "SHORT"
        assert pos.quantity == 30  # 80 - 50

    def test_force_close(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        r = pm.close("NIFTY", 24700.0)
        assert r.action == MutationAction.CLOSED
        assert r.realized_pnl_delta == pytest.approx(10000.0)
        pos = pm.get_position("NIFTY")
        assert pos is None

    def test_close_nonexistent_raises(self, pm):
        with pytest.raises(ValueError, match="No open position"):
            pm.close("NIFTY", 24700.0)


class TestMTM:
    def test_mark_to_market(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        pos = pm.mark_to_market("NIFTY", 25000.0)
        assert pos.current_price == 25000.0
        assert pos.unrealized_pnl == pytest.approx((25000 - 24500) * 50 * 1)  # 25000
        assert pos.realized_pnl == 0.0  # Never mutates realized

    def test_mtm_never_mutates_realized(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        pm.open_or_adjust("NIFTY", "SHORT", 20, 24700.0)  # reduce, creates realized
        realized_before = pm.get_position("NIFTY").realized_pnl
        pm.mark_to_market("NIFTY", 25000.0)  # MTM
        realized_after = pm.get_position("NIFTY").realized_pnl
        assert realized_after == realized_before  # Unchanged


class TestPortfolio:
    def test_empty_portfolio(self, pm):
        pf = pm.get_portfolio()
        assert pf.position_count == 0
        assert pf.total_exposure == 0.0

    def test_portfolio_with_positions(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0, strategy_id="mom")
        pm.open_or_adjust("BANKNIFTY", "SHORT", 30, 52000.0, strategy_id="vol")
        pf = pm.get_portfolio()
        assert pf.position_count == 2
        assert pf.total_exposure == pytest.approx(50 * 24500 + 30 * 52000)
        assert pf.largest_position_symbol == "BANKNIFTY"

    def test_portfolio_pnl_aggregation(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        pm.mark_to_market("NIFTY", 25000.0)
        pf = pm.get_portfolio()
        assert pf.total_unrealized_pnl == pytest.approx(25000.0)

    def test_get_all_positions(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        pm.open_or_adjust("BANKNIFTY", "SHORT", 30, 52000.0)
        all_pos = pm.get_all_positions()
        assert len(all_pos) == 2

    def test_get_closed_positions(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        pm.close("NIFTY", 25000.0)
        closed = pm.get_closed_positions()
        assert len(closed) == 1
        assert closed[0].status == "closed"

    def test_flatten(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        pm.open_or_adjust("BANKNIFTY", "SHORT", 30, 52000.0)
        results = pm.flatten()
        assert len(results) == 2
        assert all(r.action == MutationAction.CLOSED for r in results)
        assert pm.get_portfolio().position_count == 0


class TestReversalSemantics:
    def test_reversal_closes_and_opens(self, pm):
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        r = pm.open_or_adjust("NIFTY", "SHORT", 80, 24700.0)
        assert r.action == MutationAction.REVERSED
        assert r.previous_side == "LONG"
        assert r.new_side == "SHORT"
        assert r.new_quantity == 30
        # Verify closed position in history
        closed = pm.get_closed_positions()
        assert len(closed) == 1
        assert closed[0].side == "LONG"
        assert closed[0].status == "closed"
        # Verify new open position
        open_pos = pm.get_position("NIFTY")
        assert open_pos.side == "SHORT"
        assert open_pos.quantity == 30
```

- [ ] **Step 1: Create `tests/ops_api/test_position_manager.py`** with the test classes above.

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/ops_api/test_position_manager.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/ops_api/test_position_manager.py
git commit -m "test: add PositionManager lifecycle, MTM, portfolio, and reversal tests"
```

---

### Task 10: DB positions CRUD tests

**Files:**
- Modify: `tests/ops_api/test_db.py`

Add a new test class `TestPositionsCRUD` after existing position_snapshots tests:

```python
class TestPositionsCRUD:
    """Tests for positions table CRUD operations."""

    def test_upsert_open_position(self, db_with_schema):
        db_with_schema.upsert_open_position("NIFTY", "LONG", 50, 24500.0)
        pos = db_with_schema.get_position_by_symbol("NIFTY")
        assert pos is not None
        assert pos["side"] == "LONG"
        assert pos["quantity"] == 50

    def test_upsert_replaces_open(self, db_with_schema):
        db_with_schema.upsert_open_position("NIFTY", "LONG", 50, 24500.0)
        db_with_schema.upsert_open_position("NIFTY", "LONG", 100, 24550.0)
        pos = db_with_schema.get_position_by_symbol("NIFTY")
        assert pos["quantity"] == 100

    def test_partial_unique_index_allows_multiple_closed(self, db_with_schema):
        db_with_schema.upsert_open_position("NIFTY", "LONG", 50, 24500.0)
        db_with_schema.close_position("NIFTY", 25000.0)
        db_with_schema.upsert_open_position("NIFTY", "LONG", 30, 24600.0)
        db_with_schema.close_position("NIFTY", 24800.0)
        closed = db_with_schema.get_closed_positions()
        assert len(closed) == 2
        open_pos = db_with_schema.get_position_by_symbol("NIFTY")
        assert open_pos is None

    def test_reduce_position(self, db_with_schema):
        db_with_schema.upsert_open_position("NIFTY", "LONG", 50, 24500.0)
        db_with_schema.reduce_position("NIFTY", 20, 24700.0)
        pos = db_with_schema.get_position_by_symbol("NIFTY")
        assert pos["quantity"] == 30

    def test_update_mtm(self, db_with_schema):
        db_with_schema.upsert_open_position("NIFTY", "LONG", 50, 24500.0)
        db_with_schema.update_position_mtm("NIFTY", 25000.0)
        pos = db_with_schema.get_position_by_symbol("NIFTY")
        assert pos["current_price"] == 25000.0
        assert pos["unrealized_pnl"] == pytest.approx(25000.0)

    def test_get_all_open_positions(self, db_with_schema):
        db_with_schema.upsert_open_position("NIFTY", "LONG", 50, 24500.0)
        db_with_schema.upsert_open_position("BANKNIFTY", "SHORT", 30, 52000.0)
        all_pos = db_with_schema.get_all_open_positions()
        assert len(all_pos) == 2

    def test_get_position_by_symbol_none(self, db_with_schema):
        pos = db_with_schema.get_position_by_symbol("NONEXISTENT")
        assert pos is None
```

Note: The `db_with_schema` fixture needs to be checked for existence — many DB tests use a fixture that creates a temp DB and calls init_schema().

- [ ] **Step 1: Read `tests/ops_api/test_db.py`** to find the existing fixture pattern.

- [ ] **Step 2: Add TestPositionsCRUD class** with the tests above.

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/ops_api/test_db.py::TestPositionsCRUD -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/ops_api/test_db.py
git commit -m "test: add positions table CRUD tests"
```

---

### Task 11: RiskEngine position-aware tests

**Files:**
- Modify: `tests/ops_api/test_risk_engine.py`

Add new test class after existing tests. These test the position-aware checks.

```python
class TestRiskEnginePositionAware:
    """Tests for position-aware risk checks."""

    def test_passes_without_position_manager(self, db):
        """Without position_manager, all position checks are no-ops."""
        engine = RiskEngine(db)
        assert engine.check({"symbol": "NIFTY"})  # No position checks without position_manager

    def test_passes_with_no_position(self, db, pm):
        engine = RiskEngine(db, position_manager=pm)
        assert engine.check({"symbol": "NIFTY", "side": "LONG", "quantity": 50, "price": 24500.0})

    def test_blocks_excessive_position(self, db, pm):
        engine = RiskEngine(db, position_manager=pm, max_position_per_symbol=100)
        pm.open_or_adjust("NIFTY", "LONG", 80, 24500.0)
        # Adding 30 more would exceed 100 limit
        assert not engine.check({"symbol": "NIFTY", "side": "LONG", "quantity": 30, "price": 24600.0})

    def test_allows_position_under_limit(self, db, pm):
        engine = RiskEngine(db, position_manager=pm, max_position_per_symbol=100)
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        assert engine.check({"symbol": "NIFTY", "side": "LONG", "quantity": 30, "price": 24600.0})

    def test_blocks_excessive_portfolio_exposure(self, db, pm):
        engine = RiskEngine(db, position_manager=pm, max_portfolio_exposure=2_000_000)
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)  # 1,225,000 exposure
        # Adding BANKNIFTY 30 @ 52000 = 1,560,000 → total 2,785,000 > 2,000,000
        assert not engine.check({"symbol": "BANKNIFTY", "side": "LONG", "quantity": 30, "price": 52000.0})

    def test_passes_with_ok_exposure(self, db, pm):
        engine = RiskEngine(db, position_manager=pm, max_portfolio_exposure=5_000_000)
        pm.open_or_adjust("NIFTY", "LONG", 50, 24500.0)
        assert engine.check({"symbol": "BANKNIFTY", "side": "LONG", "quantity": 30, "price": 52000.0})
```

Need to add a `pm` fixture. Check the existing fixtures in test_risk_engine.py.

- [ ] **Step 1: Read `tests/ops_api/test_risk_engine.py`** to understand existing fixtures and test patterns.

- [ ] **Step 2: Add TestRiskEnginePositionAware class.**

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/ops_api/test_risk_engine.py -v`
Expected: All tests pass (new + existing)

- [ ] **Step 4: Commit**

```bash
git add tests/ops_api/test_risk_engine.py
git commit -m "test: add position-aware risk engine tests"
```

---

## Self-Review

After writing, check:
1. **Spec coverage:** Does every requirement in the design doc have at least one task?
2. **Placeholder scan:** Any "TBD", "TODO", "implement later"?
3. **Type consistency:** Do type names used across tasks match?

---

## Execution Handoff

Plan complete. Two execution options:
1. **Subagent-Driven (recommended)** — dispatch fresh subagent per task, two-stage review
2. **Inline Execution** — execute tasks in this session with checkpoints