# CURRENT STATUS — Trading Terminal

**Version:** v0.5.0 (Phase 2 — Market Data Layer + Scanner Engine)

**Date:** 2026-05-20

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

## Migration Status — Strategy Architecture (Phase 0 + Phase 1)

| Component | Status | Notes |
|-----------|--------|-------|
| BaseStrategy ABC | ✅ IMPLEMENTED | `ops_api/strategies/base.py` — 4 hooks with sensible defaults |
| StrategyRegistry | ✅ IMPLEMENTED | `ops_api/strategies/registry.py` — thread-safe, in-memory |
| DefaultStrategy | ✅ IMPLEMENTED | `ops_api/strategies/default.py` — reproduces v0.3.1 behavior exactly |
| RiskEngine | ✅ IMPLEMENTED | `ops_api/risk_engine.py` — kill switch + per-strategy limits |
| StrategyEngine | ✅ IMPLEMENTED | `ops_api/strategy_engine.py` — wraps validator + executor |
| Config flag | ✅ IMPLEMENTED | `OA_USE_STRATEGY_ENGINE` (default: True) — set False for rollback |
| Pipeline wiring | ✅ IMPLEMENTED | Active when `config.use_strategy_engine=True` (default) |
| Existing flow | ✅ UNCHANGED | `webhook.py`, `validation.py`, `execution.py`, `db.py` untouched |

**Rollback:** Set `OA_USE_STRATEGY_ENGINE=false` in `.env` — the original validator -> executor path activates immediately.

## Migration Status — Market Data & Scanner Engine (Phase 2)

| Component | Status | Notes |
|-----------|--------|-------|
| Pure-function indicators | ✅ IMPLEMENTED | `ops_api/indicators.py` — EMA, ATR, VWAP (172 tests) |
| OHLCV Cache | ✅ IMPLEMENTED | `ops_api/market_data/base.py` — thread-safe, TTL-based |
| Kite Connect provider | ✅ IMPLEMENTED | `ops_api/market_data/kite_provider.py` — wraps historical_data() |
| BaseScanner ABC | ✅ IMPLEMENTED | `ops_api/scanner/base.py` — stateless, deterministic |
| MomentumScanner | ✅ IMPLEMENTED | `ops_api/scanner/momentum.py` — EMA20/50 + VWAP + ROC |
| VolumeScanner | ✅ IMPLEMENTED | `ops_api/scanner/volume.py` — 2.5x volume spike detection |
| ScanScheduler | ✅ IMPLEMENTED | `ops_api/scheduler.py` — daemon thread, Event shutdown |
| Config options | ✅ IMPLEMENTED | `OA_SCANNER_ENABLED`, `OA_SCANNER_INTERVAL_SECONDS`, `OA_SCANNER_SYMBOLS` |
| main.py wiring | ✅ IMPLEMENTED | Scheduler start/stop in lifespan, scan callback with cache |
| source field | ✅ IMPLEMENTED | `NormalizedSignal.source` — "webhook" / "scanner" attribution |

## Startup Commands

```bash
# Terminal 1: FastAPI backend
cd /c/Users/surya/free-claude-code && uv run uvicorn ops_api.main:app --host 127.0.0.1 --port 8080

# Terminal 2: Terminal 2: Next.js frontend
cd /c/Users/surya/free-claude-code/trading-term && npx next dev -p 3000 --hostname 0.0.0.0
```

## Recent Changes (2026-05-20)

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

### Phase 0+1: Strategy Abstraction Architecture (2026-05-20)

- **New module:** `ops_api/strategies/` with `BaseStrategy` ABC, `StrategyRegistry`, `DefaultStrategy`
- **New module:** `ops_api/strategy_engine.py` — routes signals through strategy layer
- **New module:** `ops_api/risk_engine.py` — pre-execution risk gates with per-strategy limits
- **Config:** Added `OA_USE_STRATEGY_ENGINE` flag (default: True) for instant rollback
- **Pipeline:** StrategyEngine wraps existing ValidationPipeline + ExecutionEngine; existing path preserved via config flag
- **Files NOT modified:** `webhook.py`, `validation.py`, `execution.py`, `db.py`, `health.py`, `notifier.py`

### Phase 2: Market Data Layer + Scanner Engine (2026-05-20)

- **New module:** `ops_api/indicators.py` — pure-function EMA, ATR, VWAP (no state, no API calls)
- **New package:** `ops_api/market_data/` — `BarSnapshot`, `OHLCVCache` (thread-safe, TTL-based), `KiteConnectMarketData` (wraps `historical_data()`)
- **New package:** `ops_api/scanner/` — `BaseScanner` ABC, `MomentumScanner` (EMA20/50 crossovers + VWAP + ROC), `VolumeScanner` (2.5x volume spike + price direction)
- **New module:** `ops_api/scheduler.py` — `ScanScheduler` daemon thread with `threading.Event` shutdown
- **Config:** Added `OA_SCANNER_ENABLED`, `OA_SCANNER_INTERVAL_SECONDS`, `OA_SCANNER_SYMBOLS`
- **Pipeline:** Scanner signals flow into `StrategyEngine.process()` — same unified path as webhook signals
- **Signals:** Added `source` field to `NormalizedSignal` (`"webhook"` | `"scanner"`) for pipeline attribution
- **Design constraints met:** No async, no websocket, no event bus, no AI runtime, polling-only, in-memory OHLCV cache, high-confidence signals only, config-driven NIFTY 50 universe

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

## Signal Flow (Current)

```
WEBHOOK PATH:
TradingView POST → Auth (secret match) → Rate limit → Payload validation
→ Webhook dedup (alert_id) → Store raw alert → Normalize → Store signal
→ Validation (11 checks) → Strategy Engine → Risk Engine → Execution (PaperBroker)
→ Write heartbeat → Telegram notification

SCANNER PATH:
Scheduler tick (60s) → Check OHLCV cache → [miss] Kite historical_data() → Cache bars
→ MomentumScanner / VolumeScanner → [signal] Normalize → Store signal
→ Strategy Engine → Validation → Risk Engine → Execution (PaperBroker)

Both paths converge at StrategyEngine.process() — unified execution pipeline.
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
