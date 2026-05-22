---
name: trading-platform-status
description: Current operational status of the trading platform — verified systems, known issues, frontend migration state, and risks.
---

# Trading Platform — CURRENT STATUS

*Last updated: 2026-05-21*

## Operational Status

**Overall: RUNNING — PAPER MODE ONLY — VPS DEPLOYED**

| Component | Status | Notes |
|-----------|--------|-------|
| Ops API (FastAPI) | Running | VPS port 8080, 24/7, systemd-managed |
| Scanner process | Running | Standalone process, POST_MARKET phase, systemd-managed |
| SQLite DB | Operational | WAL mode, shared between API + scanner |
| Heartbeat system | Operational | Bot → API heartbeat flow verified |
| Kill switch | Operational | Activate/reset via API |
| Telegram notifier | Operational | Alerts on startup, shutdown, crash, live warning |
| Kite Connect | Connected (local) | User MMY806; VPS has no valid token yet |
| Streamlit dashboard | Replaced | Phase 2 frontend covers all dashboard needs |
| Next.js frontend (Phases 1-3) | COMPLETE | 6 panels, WebSocket streaming, analytics charts |
| Phase 5D — Scanner Selectivity | COMPLETE | Session lifecycle, trade plans, WebSocket, analytics |
| Phase 6 — VPS Deployment | COMPLETE | 3 systemd services, market clock, role separation |

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
- Systemd deployment (3 services: ops-api, scanner, dashboard — all running)
- VPS runtime behavior (graceful shutdown, restarts, log rotation, SIGTERM handling)
- Scanner process separation (OA_ROLE gating, standalone scanner_runner.py)
- Market clock (IST timezone, 6 phases, NSE holiday calendar)
- DB-based scanner heartbeat (status table updated per tick)
- Cooldown state persistence (survives process restarts)
- Trade plan persistence (read from DB on each scanner tick)
- Telegram alerts for production (live_warning, shutdown, crash, daily_summary)
- Memory health check (/proc/self/status VmRSS)
- Backup script (SQLite .backup + gzip, 30-day retention)
- Health check utility (API, services, log errors, disk, DB)
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
- **Phase 5C — Multi-timeframe confirmation module (6 dimensions + 2 hard gates)
- **Phase 5C — confirm_signal() with alignment, confidence, countertrend/exhaustion rejection
- **Phase 5C — 15m bar fetch + confirmation gate in _scan_tick()
- **Phase 5C — record_confirmation() in ScanMetrics for rejection analytics
- **Phase 5C — 346 tests passing (42 confirmation), zero regressions**

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

7. **Kite access token on VPS** — VPS .env has no valid Kite API credentials. Need TOTP-based daily token refresh or manual credentials.env setup. Scanner reports `kites_connect` warn on health endpoint.

8. **GitHub push pending** — Phase 5D + 6 code committed locally (ea26ece) but not pushed. No GitHub credentials configured. User needs to `git push origin main`.

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
| `tests/ops_api/` | Controls, DB, execution, health, notifier, validation, webhook, strategies, risk engine, scan metrics, scheduler, position manager, indicators, scanners, quality, regime, confirmation |
| `tests/trading_bot/` | Config, data, main loop, risk, state, strategies |

Run with: `uv run pytest tests/ops_api/ tests/trading_bot/`

**Phase 4 + 5A + 5B + 5C test count:** 346 total in tests/ops_api/ (135 added: 30 position manager, 14 DB CRUD, 7 risk engine position-aware, 32 quality, 6 scan_metrics tracking, 31 regime, 42 confirmation)

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
- **Phase 5C — Multi-timeframe confirmation (HTF EMA, VWAP agreement, candle structure, direction, countertrend, exhaustion)**
- **Phase 5C — confirm_signal() with alignment score, confidence, hard gates**
- **Phase 5C — Integration in _scan_tick() after regime, before StrategyEngine.process()**
- **Phase 5C — record_confirmation() in ScanMetrics for rejection analytics**
- **Phase 5C — 346 tests passing (42 confirmation), zero regressions**

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

### Phase 5C ✓ DONE (2026-05-21)
- [x] Multi-timeframe confirmation module — 6 confirmation dimensions
- [x] HTF EMA alignment — score by EMA separation and direction agreement with signal
- [x] VWAP agreement — both timeframes VWAP consistent with signal direction
- [x] HTF candle structure — body strength, wick ratio, close position
- [x] Direction agreement — LTF and HTF price slopes aligned
- [x] Countertrend hard gate — reject when HTF strongly opposes signal
- [x] Exhaustion detection — LTF bar range >> HTF avg range + tiny body → reject
- [x] ConfirmationState dataclass — accepted, confidence, alignment_score, reason, metrics
- [x] ConfirmationConfig — tunable weights (sum to 1.0), thresholds for all gates
- [x] Pure functions — no state, no side effects, no DB access
- [x] Integration in _scan_tick() — 15m bars fetch + confirmation after regime filter
- [x] Confirmation analytics — record_confirmation() in ScanMetrics
- [x] 42 confirmation tests + 346 total, zero regressions

### Phase 5D ✓ DONE (2026-05-21)
- [x] Autonomous session lifecycle — SessionManager with start/end/cleanup
- [x] Session state persistence — persist_state() saves to DB, recover_cooldown() on restart
- [x] Metadata persistence fix — start_session()/end_session() preserve state dict
- [x] Trade plan persistence — upsert/read from DB on each scanner tick
- [x] WebSocket streaming — replace polling with streaming for scanner data
- [x] Analytics charts — equity curve, PnL by strategy, rejection stats in frontend

### Phase 6 ✓ DONE (2026-05-21 VPS Deployment)
- [x] Market clock — ops_api/market_clock.py with IST, 6 phases, NSE holiday calendar
- [x] Config extensions — role, live_trading, log_dir, auto_market_detection fields
- [x] DB schema extensions — cooldown_state, trade_plans, scanner_status tables
- [x] Session recovery — SessionManager.persist_state(), recover_cooldown()
- [x] Notifier production alerts — alert_live_warning, shutdown, crash, daily_summary
- [x] Health check updates — scanner reads from DB, check_memory()
- [x] Scanner runner — standalone scanner_runner.py with market-aware scheduling
- [x] API role gating — OA_ROLE=all/api/scanner gates scanner init in main.py
- [x] 3 systemd services — ops-api.service, scanner.service, dashboard.service
- [x] Deployment artifacts — install.sh, update.sh, healthcheck.sh, backup.sh
- [x] Legacy cleanup — removed deploy.sh, vps_*.py, systemd/ directory
- [x] VPS deployment — both services running, health endpoint operational, boot-enabled

## Remaining After Deployment
- [ ] GitHub push — user needs to `git push origin main` from local
- [ ] Kite access token on VPS — set up TOTP daily refresh or manual credentials
- [ ] Morning verification — confirm scanner transitions POST_MARKET → PRE_MARKET → TRADING at 9:15 IST