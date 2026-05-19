# CURRENT STATUS — Trading Terminal

**Version:** v0.3.1 (Phase 2.7 — validation-order fix + state reporting fix)

**Date:** 2026-05-19

---

## Service Status

| Service | Status | Port | Notes |
|---------|--------|------|-------|
| FastAPI backend | ✅ RUNNING | 127.0.0.1:8080 | Uvicorn, localhost-only |
| Next.js frontend | ✅ RUNNING | 0.0.0.0:3000 | Dev server, LAN accessible |
| Nginx (VPS) | ⚠️ N/A | — | VPS deployment only |
| Trading bot | ⚠️ NOT RUNNING | — | Only during NSE hours on VPS |
| Kite Connect | ❌ DISCONNECTED | — | Token expired (from May 14) |
| Telegram | ✅ HEALTHY | — | Notifier operational |
| SQLite (WAL) | ✅ HEALTHY | — | ops_data.db |

## Startup Commands

```bash
# Terminal 1: FastAPI backend
cd /c/Users/surya/free-claude-code && uv run uvicorn ops_api.main:app --host 127.0.0.1 --port 8080

# Terminal 2: Terminal 2: Next.js frontend
cd /c/Users/surya/free-claude-code/trading-term && npx next dev -p 3000 --hostname 0.0.0.0
```

## Recent Changes (2026-05-19)

### Fix 1: Validation pipeline duplicate_alert false rejection
- **Root cause:** `_check_staleness` in `validation.py` queried `get_alert_by_alert_id()` which always found the raw alert row the webhook handler just inserted moments earlier
- **Fix:** Removed `_check_staleness` from validation pipeline. Alert-level dedup remains at webhook layer (by alert_id). Trade-level dedup remains at execution layer (by dedup_key). The validation layer no longer runs a redundant check that always fails.
- **Files:** `ops_api/validation.py`, `ops_api/main.py`, `ops_api/models.py`

### Fix 2: Webhook path now calls executor
- **Root cause:** The webhook endpoint never called `executor.execute()` — execution was only available through the trading bot path
- **Fix:** After validation passes, the webhook endpoint now calls `executor.execute(signal, validation)` via PaperBroker. Execution result is returned in the webhook response and persisted to DB.
- **File:** `ops_api/main.py`

### Fix 3: Health check staleness detection
- **Root cause:** `check_bot()` only checked the status string ("running"/"paused"/"stopped") without checking heartbeat timestamp
- **Fix:** Added heartbeat staleness):** Added `_heartbeat_age_seconds()` to compute heartbeat age. `check_bot()` now returns `warn` if `last_heartbeat_at` > 300s stale. Added `check_kite()` to report kite status with staleness awareness.
- **File:** `ops_api/health.py`

### Fix 4: Dashboard kite_connected no longer lies
- **Root cause:** `dashboard/data` returned `kite_connected` directly from the stale `bot_status` table row without checking freshness
- **Fix:** On startup, if Kite client fails to connect, `bot_status.kite_connected` is reset to False (with all other fields preserved via merge). Dashboard endpoint computes staleness-aware kite_connected based on heartbeat freshness at query time.
- **Fix:** After webhook execution, a heartbeat is written to refresh liveness tracking.
- **Files:** `ops_api/main.py`

## URL Routing

| Request | Route | Target |
|---------|-------|--------|
| Browser → http://localhost:3000/ | Next.js dev server | Frontend HTML/JS |
| Browser → /api/backend/* | Next.js rewrites() → http://127.0.0.1:8080/* | FastAPI (dashboard, status, controls) |
| TradingView → http://<vps>:80/webhook/tradingview | Nginx → 127.0.0.1:8080 | FastAPI (webhook ingestion) |
| Internal → http://127.0.0.1:8080/* | Direct | FastAPI (dev access) |

## Frontend Panel Status

| Panel | Status | Data Source | Poll Interval |
|-------|--------|-------------|---------------|
| TopStatusBar | ✅ OK | useApiStatus → /api/backend/status + /health | 10s |
| ExecutionFeed | ✅ OK | useExecutionFeed → /api/backend/dashboard/analytics | 3s |
| PositionPanel | ✅ OK | useDashboardData → /api/backend/dashboard/data | 7s |
| PnLRiskPanel | ✅ OK | useDashboardData (shared) | 7s |
| SignalFeed |SignalFeed | ✅ OK | useDashboardData (shared) | 7s |
| ControlsPanel | ✅ OK | useDashboardData + API key gate | 7s |

## Endpoint Verification

| Endpoint | Status | Notes |
|----------|--------|-------|
| GET /health | ✅ 200 | 7 checks including kite_connect staleness |
| GET /status | ✅ 200 | Returns bot_status + latest_heartbeat + kill_switch |
| POST /webhook/tradingview | ✅ 200 | Full pipeline: ingest → validate → execute → respond |
| GET /dashboard/data | ✅ 200 | All 15+ fields present, kite_connected staleness-aware |
| GET /dashboard/analytics | ✅ 200 | execution_events, pnl_by_strategy, etc. |
| GET /api/backend/health (rewrite) | ✅ 200 | Via Next.js same-origin proxy |

## Webhook Flow (Current)

```
TradingView POST → Auth (secret match) → Rate limit → Payload validation
→ Webhook dedup (alert_id) → Store raw alert → Normalize → Store signal
→ Validation (11 checks, no short-circuit) → [if passed] Execution (PaperBroker)
→ Write heartbeat → Telegram notification → Response with execution result
```

## Execution Status

| Metric | Value |
|--------|-------|
| Bot mode | paper |
| Active position | None |
| Trades today | 0 |
| Daily PnL | 0.0 |
| Cumulative PnL | 0.0 |
| Kill switch | Inactive |
| Service errors | 0 |
