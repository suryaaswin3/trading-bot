---
name: trading-platform-status
description: Current operational status of the trading platform — verified systems, known issues, frontend migration state, and risks.
---

# Trading Platform — CURRENT STATUS

*Last updated: 2026-05-18*

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
| `tests/ops_api/` | Controls, DB, execution, health, notifier, validation, webhook |
| `tests/trading_bot/` | Config, data, main loop, risk, state, strategies |

Run with: `uv run pytest tests/ops_api/ tests/trading_bot/`

Note: Some tests may reference the `free-claude-code` proxy infrastructure. Trading-specific tests are isolated in the directories above.

## Next Steps (Recommended Priority)

### Phase 1 ✓ DONE
- [x] Initialize Next.js project — TypeScript, TailwindCSS, shadcn/ui
- [x] Defensive API client layer — timeouts, error handling, stale detection
- [x] Dark terminal theme — full-viewport layout, font-mono, responsive grid
- [x] Top status bar — bot status, mode, kite, heartbeat, kill switch, health, connection state
- [x] Error/degraded/offline states — graceful fallback when backend unavailable

### Phase 2 (Next)
1. **Execution feed** — real-time order display from `/dashboard/data` with streaming updates
2. **Position panel** — current position display (symbol, side, qty, entry price, PnL)
3. **Control panel** — kill switch toggle, mode switch (paper/live), start/stop
4. **PnL & Risk display** — daily PnL, drawdown, max loss indicator, trades today counter
5. **Signal visibility** — incoming TradingView alert display with validation pass/fail per check

### Phase 3+ (Future)
6. **WebSocket system** — replace polling with streaming updates
7. **Analytics** — equity curve, PnL by strategy, rejection stats charts
8. **QA pass** — full integration test against live backend
9. **Deploy new frontend** — switch systemd from Streamlit to Next.js