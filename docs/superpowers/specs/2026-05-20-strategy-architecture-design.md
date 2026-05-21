# Strategy Architecture — Modular Trading Engine

**Date:** 2026-05-20
**Version:** v0.4.0 (Phase 0 + Phase 1)
**Status:** Design Document

## 1. Motivation

The current trading terminal (v0.3.1) uses a flat, hardcoded pipeline: TradingView webhook → monolithic validation → single-position execution. Strategy is a passive string field on signals, not a first-class abstraction. This design introduces a lightweight strategy layer that creates clean extension points for future capabilities (multiple strategies, dynamic scanning, multi-symbol portfolio, autonomous market sessions) without destabilizing the working paper-trading system.

## 2. Design Constraints

1. **Minimal clean abstraction** — the strategy interface must be small and obvious
2. **Preserve current pipeline** — existing webhook → validation → execution flow continues working identically
3. **No overengineering** — no plugin framework, no async orchestration, no AI runtime dependency
4. **Backward compatibility** — `DefaultStrategy` reproduces existing behavior exactly
5. **Deterministic runtime** — no LLM calls in the execution path; all decisions are rule-based
6. **Token efficiency** — minimal runtime overhead; strategy state is in-memory + SQLite

## 3. Architecture

### 3.1 Phase 0 — Strategy Abstraction (Foundation)

New package: `ops_api/strategies/`

```
ops_api/strategies/
    __init__.py          # exports: BaseStrategy, StrategyRegistry, StrategyMetadata
    base.py              # BaseStrategy ABC, StrategyMetadata, RiskConfig, StrategyVerdict
    registry.py          # StrategyRegistry — thread-safe, in-memory registry
    default.py           # DefaultStrategy — migration bridge for existing behavior
```

#### 3.1.1 BaseStrategy

```python
class BaseStrategy(ABC):
    """Lightweight strategy interface. Each strategy is a stateless policy object."""

    metadata: StrategyMetadata  # set in __init__

    def matches(self, signal: NormalizedSignal) -> bool
        """Does this signal belong to this strategy? Default: signal.strategy == metadata.id"""

    def validate_signal(self, signal, market_state, portfolio) -> StrategyVerdict
        """Strategy-specific validation. Runs AFTER shared global validation.
           Override to add per-strategy rules (e.g., "only trade NIFTY on this strategy").
           Default: accept (return passed=True)."""

    def compute_order(self, signal, portfolio) -> OrderSpec | None
        """Compute order parameters. Override for per-strategy position sizing.
           None = don't trade (scout mode).
           Default: 1 lot (NIFTY=50, BANKNIFTY=25)."""

    def on_execution_result(self, result, portfolio) -> None
        """Lifecycle callback after fill/rejection. Override to update strategy state.
           Default: no-op."""
```

Key properties:
- **Stateless** — all mutable state lives in the registry or DB, not on the strategy instance
- **Single responsibility** — each method has one clear purpose
- **Sensible defaults** — new strategies override only what differs

#### 3.1.2 Supporting Types

```python
@dataclass(frozen=True)
class StrategyMetadata:
    id: str                  # unique key, e.g. "trend_following_5m"
    display_name: str        # human-readable
    description: str         # one-liner
    timeframes: tuple        # scanner subscription hint, e.g. ("5", "15")
    symbols: tuple | None    # None = scanner-managed
    risk_defaults: RiskConfig

@dataclass(frozen=True)
class RiskConfig:
    max_trades_per_day: int
    max_daily_loss: float
    cooldown_minutes: int
    max_consecutive_losses: int
    max_position_size: int

@dataclass
class StrategyVerdict:
    accepted: bool
    rejection_reason: str = ""
    overrides: dict | None = None  # e.g. {"quantity": 75, "slippage": 1.5}
```

#### 3.1.3 StrategyRegistry

```python
class StrategyRegistry:
    """Thread-safe, in-memory registry of all active strategies.
    
    Thread safety via threading.Lock.
    Strategies registered at startup (lifespan) or via control endpoint.
    """

    def register(self, strategy: BaseStrategy) -> None
        """Register by metadata.id. Raises DuplicateStrategyError on conflict."""

    def get(self, strategy_id: str) -> BaseStrategy | None
    def get_for_signal(self, signal: NormalizedSignal) -> BaseStrategy | None
    def all(self) -> list[BaseStrategy]
    def unregister(self, strategy_id: str) -> None
```

#### 3.1.4 DefaultStrategy (Migration Bridge)

```python
class DefaultStrategy(BaseStrategy):
    """Reproduces existing v0.3.1 behavior exactly.
    
    - Validation: delegates to existing ValidationPipeline (11 checks)
    - Execution: delegates to existing ExecutionEngine
    - Position sizing: fixed lots (NIFTY=50, BANKNIFTY=25)
    - Cooldown: 30 min, max_trades: 2, max_loss: 5000
    
    This strategy exists so existing signals continue working identically
    while the new abstraction proves itself. It is registered automatically
    on startup and acts as the fallback for any unmatched signal.
    """
```

### 3.2 Phase 1 — StrategyEngine (Pipeline Integration)

New file: `ops_api/strategy_engine.py`

```
ops_api/
    strategy_engine.py   # StrategyEngine — wraps existing validation + execution
    risk_engine.py       # RiskEngine — reads risk_counters, enforces limits
```

#### 3.2.1 StrategyEngine

```python
class StrategyEngine:
    """Routes signals through the strategy layer.
    
    WRAPS existing ValidationPipeline and ExecutionEngine.
    Does NOT replace them — the existing webhook → validator → executor
    path continues working independently.
    """
```

**Processing flow:**

```
StrategyEngine.process(signal)
    │
    ├─ 1. Resolve strategy via registry
    │     registry.get_for_signal(signal) ?? fallback to DefaultStrategy
    │
    ├─ 2. Shared validation (existing 11 checks, unchanged)
    │     validator.validate(signal) → ValidationResult
    │
    ├─ 3. Strategy-specific validation
    │     strategy.validate_signal(signal, market_state, portfolio) → StrategyVerdict
    │
    ├─ 4. Risk check
    │     risk_engine.check(signal, strategy) → bool
    │
    ├─ 5. Compute order
    │     strategy.compute_order(signal, portfolio) → OrderSpec | None
    │
    ├─ 6. Execute
    │     executor.execute(signal, order, mode) → ExecutionResult
    │
    ├─ 7. Lifecycle callback
    │     strategy.on_execution_result(result, portfolio)
    │
    └─ 8. Return result
```

#### 3.2.2 Webhook Handler Changes (main.py)

Minimal change. The existing handler gains a branch:

```python
# Current (unchanged):
if validation.passed and executor is not None:
    exec_result = executor.execute(signal, validation_dict, mode="paper")

# New (added alongside, path chosen by config flag):
if use_strategy_engine and strategy_engine is not None:
    result = strategy_engine.process(signal)
    exec_result = result.execution_result
```

The flag `use_strategy_engine` defaults to `True` in Phase 1. Set to `False` = old path, for rollback safety.

#### 3.2.3 RiskEngine

```python
class RiskEngine:
    """Pre-execution risk gates. Reads risk_counters from DB.
    
    Checks:
    - Daily trade count (per-strategy + global)
    - Daily loss limit breached (per-strategy + global)
    - Consecutive losses exceed threshold
    - Position concentration (single-symbol exposure)
    - Kill switch active
    """
```

Initial implementation is minimal — basically the same checks as existing validation but with per-strategy limits from `RiskConfig`. The risk engine exists as a separate module so it can grow without bloating validation.

### 3.3 Data Flow (Phase 1)

```
TradingView POST
    │
    ▼
webhook.py (auth, rate-limit, dedup, normalize)
    │
    ▼
store raw alert + normalized signal
    │
    ▼
[Strategy Engine ON?]
    │
    ├── YES ──► strategy_engine.process(signal)
    │               │
    │               ├── resolve strategy ─────────► DefaultStrategy / matched strategy
    │               ├── validator.validate(signal) ► existing 11 checks
    │               ├── strategy.validate_signal() ► per-strategy rules
    │               ├── risk_engine.check()        ► risk gates
    │               ├── strategy.compute_order()   ► position sizing
    │               ├── executor.execute()         ► paper/live broker
    │               └── strategy.on_execution()    ► lifecycle callback
    │
    └── NO  ──► existing path (validator.validate → executor.execute)
                │
                ▼
        write heartbeat + telegram notification + response
```

## 4. Files Changed

### Phase 0 (No pipeline changes)
| Action | Path | Purpose |
|--------|------|---------|
| Create | `ops_api/strategies/__init__.py` | Package exports |
| Create | `ops_api/strategies/base.py` | BaseStrategy ABC + data types |
| Create | `ops_api/strategies/registry.py` | StrategyRegistry |
| Create | `ops_api/strategies/default.py` | DefaultStrategy bridge |

### Phase 1 (Pipeline integration)
| Action | Path | Purpose |
|--------|------|---------|
| Create | `ops_api/strategy_engine.py` | StrategyEngine |
| Create | `ops_api/risk_engine.py` | RiskEngine (minimal) |
| Modify | `ops_api/main.py` | Wire strategy engine into webhook handler |
| Modify | `ops_api/config.py` | Add `use_strategy_engine` flag |
| Modify | `ops_api/models.py` | Add `OrderSpec`, `StrategyVerdict` types if not in base.py |

### Unchanged (separated concerns stay separate)
| Path | Reason |
|------|--------|
| `ops_api/webhook.py` | Signal receipt, auth, dedup — no strategy awareness needed |
| `ops_api/execution.py` | Broker abstraction — no strategy awareness needed |
| `ops_api/validation.py` | Shared 11 checks — extended by, not replaced by, strategy layer |
| `ops_api/db.py` | Data access — no strategy awareness needed |
| `ops_api/health.py` | Health checks — no strategy awareness needed |
| `ops_api/notifier.py` | Notifications — no strategy awareness needed |

## 5. Extension Points (Future)

These require NO changes to BaseStrategy — they use existing interfaces:

| Capability | How it plugs in |
|------------|----------------|
| **Multiple strategies** | Register more `BaseStrategy` subclasses in registry |
| **Scanner engine** | Scanner generates `NormalizedSignal` → feeds `StrategyEngine.process()` |
| **Multi-symbol orchestration** | Strategies track per-symbol state in `on_execution_result()` |
| **Autonomous market session** | Scheduler calls `strategy.matches()` with session-aware context |
| **Strategy-specific scanner** | Strategy declares `metadata.symbols` / `metadata.timeframes` |

## 6. Rollback

- `use_strategy_engine=False` in config restores the original pipeline
- DefaultStrategy produces IDENTICAL behavior to existing code
- No DB schema changes in Phase 0 or Phase 1
- No new external dependencies

## 7. Self-Review Notes

- No TBD/TODO placeholders remain
- Internal consistency: architecture matches feature descriptions
- Scope: Phase 0+1 is focused enough for a single implementation plan
- Ambiguity: `StrategyVerdict.accepted` vs `ValidationResult.passed` — verdict is additive; validation runs first regardless. Clear in the data flow.