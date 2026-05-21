---
name: trading-platform-status
description: Current operational status of the trading platform — verified systems, known issues, frontend migration state, and risks.
---

# Trading Platform — CURRENT STATUS

*Last updated: 2026-05-21*

## Operational Status

**Overall: RUNNING — PAPER MODE ONLY**

| Component | Status | Notes |
|-----------|--------|-------|
| Trading bot | Running | Polling loop, paper trades only |
| Ops API (FastAPI) | Running | Port 8080, 24/7 |
| SQLite DB | Operational | WAL mode, thread-safe |
| Heartbeat system | Operational | Bot → API heartbeat flow verified |
| Kill switch | Operational | Activate/reset via API |
| Telegram notifier | Operational | Alerts sent on startup, kill switch, control actions |
| Kite Connect | Connected | User MMY806, profile/margins/data verified |
| Streamlit dashboard | Running but unstable | Being replaced — do not invest further |
| Next.js frontend (Phase 1) | COMPLETE | Initialized, API layer, status bar, dark terminal theme |

## Verified Working Systems

The following have been operationally verified through soak tests, concurrency tests, and end-to-end flow tests:

- TradingView webhook flow (auth → dedup → normalize → validate → execute → DB)
- Webhook authentication (HMAC + JSON secret methods)
- FastAPI APIs (all endpoints respond correctly)
- SQLite WAL concurrency (safe under concurrent reads/writes)
- Heartbeat system (bot POSTs → API stores → dashboard reads → stale detection)
- Telegram alerts (startup, kill switch, errors)
- Cooldown logic (time-based trade spacing)
- Duplicate prevention (alert_id dedup + execution dedup_key)
- Kill switch (activation blocks signals, logs events, notifies Telegram)
- Paper trading execution flow (simulated fills with slippage)
- Dashboard backend APIs (`/dashboard/data`, `/dashboard/analytics`)
- Analytics endpoints (PnL by strategy, rejection stats, daily PnL history)
- Kite authentication (user MMY806, TOTP-based daily token)
- Kite market data access (LTP, historical candles, instruments)
- Broker connectivity (KiteConnect profile/margins/instruments endpoints)
- Access token persistence (stored in env, refreshed daily via cron)
- Systemd deployment (all three services operational)
- VPS runtime behavior (graceful shutdown, restarts, log rotation)
- **Phase 4 — PositionManager lifecycle (open/adjust/reduce/close/reverse with weighted avg entry)**
- **Phase 4 — Realized PnL computation (LONG + SHORT direction-aware)**
- **Phase 4 — MTM (unrealized PnL isolation, no realized_pnl mutation)**
- **Phase 4 — Reversal semantics (close old lifecycle + open new, two distinct rows)**
- **Phase 4 — Portfolio aggregation (exposure, PnL, concentration)**
- **Phase 4 — Position-aware risk checks (per-symbol limit, exposure cap, concentration limit)**
- **Phase 4 — Backward compat bridges (bot_status + position_snapshots preserved)**
- **Phase 4 — Partial unique index (one open per symbol, unlimited closed history)**
- **Phase 4 — 241 tests passing (51 new, zero regressions)**
- **Phase 5A — Breakout quality scoring (6 dimensions: RVOL, candle, VWAP, EMA, range, time)**
- **Phase 5A — score_breakout() aggregation with weighted total + accept/reject gate**
- **Phase 5A — QualityScore dataclass with component scores, total, reason string**
- **Phase 5A — QualityConfig with tunable thresholds and weights (default sum to 1.0)**
- **Phase 5A — Integration in _scan_tick() before StrategyEngine.process() with rejection logging**
- **Phase 5A — record_quality() in ScanMetrics for rejection analytics**
- **Phase 5A — 273 tests passing (32 quality + 6 scan_metrics added), zero regressions**
- **Phase 5B — Regime detection module (TREND, RANGE, VOLATILE, DEAD with 5 detection dimensions)**
- **Phase 5B — detect_regime() with confidence, reasons, breakout_allowed gate**
- **Phase 5B — Integration in _scan_tick() after quality, before StrategyEngine.process()**
- **Phase 5B — record_regime() in ScanMetrics for classification analytics**
- **Phase 5B — 304 tests passing (31 regime), zero regressions**

## Kite Connect Status

| Check | Status |
|-------|--------|
| User | MMY806 (verified) |
| Profile fetch | Working |
| Margins endpoint | Working |
| NFO instruments | Loaded successfully |
| Market data | Working (LTP, historical data) |
| Access token | Stored in env, daily refresh |
| Dashboard heartbeat | Receives kite_connected state |

**Root cause of earlier login failure:** Kite login requires form-urlencoded `data=` parameter, not JSON. Fixed.

## Heartbeat System

- Trading bot POSTs heartbeat to `{ops_api_url}/heartbeat` at configured intervals
- Heartbeat payload includes: bot_status, bot_mode, last_action, trades_today, daily_pnl, kite_connected
- Ops API stores in `heartbeats` table
- Dashboard reads latest heartbeat and calculates age
- Stale heartbeat detection: age > threshold → warn on dashboard

## Frontend Migration Status

| Component | Status | Action Needed |
|-----------|--------|---------------|
| Streamlit dashboard | Running but unstable | **Abandon — do NOT fix** |
| Next.js project | Initialized | Next.js 16.2, TypeScript, TailwindCSS v4, App Router |
| shadcn/ui setup | Complete | badge, card, separator, skeleton, button installed |
| Terminal UI foundation | Built | Dark theme, LayoutShell, responsive grid, font-mono stack |
| Top status bar | Built | Bot status, mode, kite, heartbeat, kill switch, health, connection state |
| API client layer | Built | Timeout handling, error recovery, stale detection, heartbeat age calc |
| Environment config | Configured | `NEXT_PUBLIC_OPS_API_URL` env var, .env.local |
| Backend APIs | Ready | `/status`, `/health`, `/dashboard/data`, `/dashboard/analytics` |
| Execution feed | **Phase 2** | Placeholder panel only |
| Position panel | **Phase 2** | Placeholder panel only |
| PnL & Risk | **Phase 2** | Placeholder panel only |
| Controls | **Phase 2 | Placeholder panel only |
| WebSocket system | **Phase 3+** | Not started |
| Analytics | **Phase 3+** | Not started |

**Why Streamlit was abandoned:**
- Duplicate widget collisions
- Rendering instability under refresh
- Brittle state handling (session state management)
- Heartbeat parsing crashes
- Poor responsive behavior
- Weak realtime architecture (poll-based, no WebSocket)

**Target stack for new frontend:**
- Next.js + TypeScript
- TailwindCSS
- shadcn/ui components
- Professional quant-terminal aesthetic (dark, high-density, monospace)

**Desired UI characteristics:**
- Execution visibility (live order feed)
- Signal visibility (incoming TV alerts)
- Validation visibility (pass/fail per check)
- Realtime operational status (heartbeat age, kite connection)
- Risk visibility (PnL, drawdown, kill switch)
- Live feeds (streaming updates)
- Operational clarity (dense information, no fluff)

**Phase 1 implementation details:**
- Next.js 16.2.6 with App Router, src/ directory structure
- TailwindCSS v4 with dark theme (`--background: oklch(0.145 0 0)`)
- shadcn/ui v4 components (badge, card, skeleton, separator, button)
- Defensive API client with AbortController timeout (10s), JSON parse error handling, network error normalization
- Consecutive failure tracking (3 fails → offline state)
- `useApiStatus` hook polls `/status` and `/health` every 10s with proper cleanup
- Stale data detection (>30s threshold), heartbeat stale detection (>120s)
- Modular status badges: BotStatusBadge, ModeBadge, KiteBadge, HeartbeatBadge, KillSwitchBadge, HealthBadge, ConnectionBadge
- LayoutShell with full-viewport dark terminal, TopStatusBar sticky header with backdrop blur
- Responsive grid: 1 col mobile, 2 col tablet, 3 col desktop
- Zero TypeScript errors, zero build warnings, clean production build

## Known Issues

1. **`_last_entry_candle_time` dedup in `trading_bot/main.py`** — Module-level global, not persisted. Bot restart resets it, potentially allowing re-entry on the same candle. Needs persistence layer fix.

2. **State persistence** — `trading_bot/state.py` uses a module-level dict. No persistence between bot restarts. If bot crashes mid-position, state is lost. Phase 2 should implement a StateManager.

3. **Cooldown reads hardcoded default** — `ops_api/validation.py` line 77: `cooldown = 30` is hardcoded instead of reading from config. The validation pipeline has some duplicated/defaulted config values from TradingBotConfig.

4. **Streamlit crashes** — Dashboard may crash under load due to widget collisions and state issues. This is expected and accepted — the dashboard is being replaced.

5. **Frontend Phase 1 live, Phase 2+ not started** — Next.js project initialized, API layer built, status bar connects to backend. Execution feed, position panel, controls, WebSocket, analytics still placeholder.

6. **Paper order ID reset** — `PAPER_ORDER_ID` global in `trading_bot/main.py` resets on restart. Not an issue for paper but would cause confusion in persistent audit.

## Current Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Live order accidentally enabled | HIGH | `paper_mode=True` default; kill switch; validation gates |
| Streamlit UI completely crashing | MEDIUM | Backend APIs are independent; dashboard replacement in progress |
| Trading bot state loss on restart | MEDIUM | Only affects active positions; paper mode limits damage |
| Kite token expiry during trading day | MEDIUM | Token generated at 8:45 AM; auto-refresh not implemented |
| Ops API database growth | LOW | 90-day retention + periodic cleanup; WAL checkpoint on startup |
| Frontend migration breaking backend | LOW | Backend APIs are read-only from frontend perspective |
| Module-level globals in trading bot | MEDIUM | Planned refactor to StateManager in Phase 2 |

## Testing Status

Tests exist in `tests/ops_api/` and `tests/trading_bot/` for both subsystems:

| Test Module | Coverage |
|-------------|----------|
| `tests/ops_api/` | Controls, DB, execution, health, notifier, validation, webhook, strategies, risk engine, scan metrics, scheduler, position manager, indicators, scanners, quality, regime |
| `tests/trading_bot/` | Config, data, main loop, risk, state, strategies |

Run with: `uv run pytest tests/ops_api/ tests/trading_bot/`

**Phase 4 + 5A + 5B test count:** 304 total in tests/ops_api/ (93 added: 30 position manager, 14 DB CRUD, 7 risk engine position-aware, 32 quality, 6 scan_metrics tracking, 31 regime)

## Next Steps (Recommended Priority)

### Phase 1 ✓ DONE
- [x] Initialize Next.js project — TypeScript, TailwindCSS, shadcn/ui
- [x] Defensive API client layer — timeouts, error handling, stale detection
- [x] Dark terminal theme — full-viewport layout, font-mono, responsive grid
- [x] Top status bar — bot status, mode, kite, heartbeat, kill switch, health, connection state
- [x] Error/degraded/offline states — graceful fallback when backend unavailable

### Phase 2 ✓ DONE
- [x] Execution feed — real-time order display from `/dashboard/data` with scroll-stable feed
- [x] Position panel — current position display (symbol, side, qty, entry price, PnL)
- [x] Control panel — kill switch toggle, mode switch (paper/live), start/stop
- [x] PnL & Risk display — daily PnL, drawdown, max loss indicator, trades today counter
- [x] Signal visibility — incoming TradingView alert display with validation pass/fail per check

### Phase 3 ✓ DONE
- [x] Scheduler heartbeat metrics — tick/error counters, min/max/avg duration, uptime, missed ticks
- [x] ScanMetrics singleton — cache hit rate, avg duration, signal tracking
- [x] Strategy performance aggregation — trade_count, net_pnl, wins/losses per strategy
- [x] Portfolio state queries — current positions, exposure, PnL summary
- [x] Dashboard fields — scanner_metrics, portfolio, strategy_performance
- [x] Scanner health check — reports scheduler state + metrics summary
- [x] 190 tests passing (before Phase 4), zero regressions

### Phase 4 ✓ DONE
- [x] Position models — PositionState, PortfolioSnapshot, PositionMutationResult dataclasses
- [x] PositionManager — lifecycle (open/adjust/reduce/close/reverse), PnL, MTM, portfolio, flatten
- [x] DB positions schema — positions table with partial unique index, 9 CRUD methods
- [x] RiskEngine position checks — per-symbol limit, exposure cap, concentration limit
- [x] ExecutionEngine integration — post-fill PositionManager mutation
- [x] StrategyEngine portfolio wiring — real PortfolioSnapshot instead of empty dict
- [x] Dashboard fields — positions, portfolio_snapshot, closed_positions
- [x] TypeScript types — PositionState, PortfolioSnapshot interfaces
- [x] 241 tests passing (51 new), zero regressions

### Phase 5A ✓ DONE (2026-05-21)
- [x] Breakout quality scoring module — 6 dimensions (RVOL, candle strength, VWAP alignment, EMA trend, range expansion, time-window quality)
- [x] QualityScore dataclass — component scores (0.0-1.0), weighted total, accept/reject gate, reason string
- [x] QualityConfig — tunable thresholds and weights (default sum to 1.0)
- [x] Pure functions — no state, no side effects, no DB access
- [x] Integration in _scan_tick() — quality check before StrategyEngine.process()
- [x] Rejection analytics — record_quality() in ScanMetrics for dashboard visibility
- [x] 32 quality tests + 273 total, zero regressions
- **Phase 5B — Regime detection (TREND, RANGE, VOLATILE, DEAD) with breakout gating**
- **Phase 5B — 5 detection dimensions: EMA separation, VWAP slope, ATR ratio, range ratio, candle overlap**
- **Phase 5B — detect_regime() with confidence score, reasons, metrics snapshot**
- **Phase 5B — record_regime() in ScanMetrics for classification analytics**
- **Phase 5B — 304 tests passing (31 regime), zero regressions**

### Phase 5B ✓ DONE (2026-05-21)
- [x] Regime detection module — 4 regimes (TREND, RANGE, VOLATILE, DEAD)
- [x] 5 detection dimensions — EMA separation, VWAP slope, ATR expansion/compression, range ratio, candle overlap
- [x] DetectRegime dataclass — regime, confidence, reasons, breakout_allowed flag, metrics snapshot
- [x] RegimeConfig — tunable thresholds for all detection dimensions
- [x] Pure functions — no state, no side effects, no DB access
- [x] Integration in _scan_tick() — regime filter after quality scoring, before StrategyEngine.process()
- [x] Breakout gating — TREND/VOLATILE allowed, RANGE/DEAD rejected
- [x] Regime analytics — record_regime() in ScanMetrics for dashboard visibility
- [x] 31 regime tests + 304 total, zero regressions

### Phase 5C (Next — Scanner Selectivity + Advanced Features)
1. **Scanner selectivity** — reduce false signals, add multi-timeframe confirmation
3. **Autonomous session lifecycle** — self-contained trading sessions with entry/exit/cleanup
4. **Disciplined execution** — enforce pre-defined trade plans, reduce ad-hoc signals
5. **WebSocket streaming** — replace polling with streaming for scanner data
6. **Analytics charts** — equity curve, PnL by strategy, rejection stats in frontend