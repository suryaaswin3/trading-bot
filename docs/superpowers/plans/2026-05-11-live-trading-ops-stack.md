# Live Trading Operations Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete live trading operations stack around the existing Zerodha trading bot — webhook ingestion, validation, execution engine, persistent storage, live dashboard, controls, health monitoring, and deployment updates.

**Architecture:** Separate FastAPI ops server runs alongside the existing bot, sharing an SQLite database (WAL mode). The bot polls a `bot_commands` table for control signals and writes status updates. No microservices, no Redis/Kafka/Docker. Streamlit dashboard reads from the FastAPI REST API.

**Tech Stack:** FastAPI, SQLite (stdlib), Uvicorn, Streamlit, Plotly, Pydantic v2

---

### Segment 1: Audit + Architecture (COMPLETE)

Repository has been audited. Architecture designed and approved. See conversation history for details.

**Key findings:**
- Bot uses module-level dict for state (in-memory, lost on restart)
- No persistent storage, no webhook, no dashboard, no health checks
- Hardcoded VPS password in `deploy.py:18`
- `credentials.env` contains live Kite credentials in tracked repo

**Architecture decision:** Separate FastAPI server process + shared SQLite DB with WAL mode

---

### Segment 2: Persistent Storage + Models

**Files:**
- Create: `ops_api/__init__.py`
- Create: `ops_api/config.py`
- Create: `ops_api/models.py`
- Create: `ops_api/db.py`

- [x] **Create `ops_api/__init__.py`** — package docstring
- [x] **Create `ops_api/config.py`** — `OpsApiConfig` frozen dataclass, loaded from `OA_*` env vars
- [x] **Create `ops_api/models.py`** — all Pydantic models (WebhookAlert, NormalizedSignal, ValidationResult, ExecutionOrder, ExecutionResult, PositionSnapshot, BotStatus, Heartbeat, HealthCheckResult, ControlEvent, BotCommand, RiskCounter, DashboardData, etc.)

- [ ] **Create `ops_api/db.py`** — DatabaseManager class with:
  - Full SQLite schema (12 tables: webhook_alerts, normalized_signals, validation_results, execution_orders, execution_results, position_snapshots, bot_status, bot_commands, health_checks, heartbeats, control_events, risk_counters)
  - WAL mode for concurrency safety
  - Thread-safe connection management
  - CRUD methods for all entities
  - Query methods for dashboard data aggregation

- [ ] **Verify imports** — `uv run python -c "from ops_api.db import DatabaseManager; print('OK')"`

### Segment 3: FastAPI Backend + TradingView Webhook

**Files:**
- Create: `ops_api/main.py`
- Create: `ops_api/webhook.py`
- Create: `ops_api/validation.py` (stub for Segment 4)

- [ ] **Create `ops_api/main.py`** — FastAPI app with:
  - `/health` — health check endpoint
  - `/status` — bot status endpoint
  - `/webhook/tradingview` — webhook ingestion endpoint
  - Startup/shutdown event handlers
  - Configured CORS (for dashboard)
  - Middleware for API key auth on control endpoints

- [ ] **Create `ops_api/webhook.py`** — Webhook handler with:
  - HMAC secret verification against `OA_WEBHOOK_SECRET`
  - Payload normalization to `NormalizedSignal`
  - Dedup by `alert_id` (idempotency)
  - Malformed payload rejection
  - Raw + normalized storage to DB
  - Pass validated signal to validation layer

- [ ] **Verify FastAPI app starts** — `uv run python -c "from ops_api.main import app; print('App loaded OK')"`

### Segment 4: Validation + Execution Engine

**Files:**
- Modify: `ops_api/validation.py`
- Create: `ops_api/execution.py`

- [ ] **Create `ops_api/validation.py`** — Validation pipeline:
  - market_open check
  - strategy_enabled check
  - bot_mode check (paper/live)
  - bot_paused check
  - duplicate_alert check (by alert_id)
  - cooldown check
  - max_trades_day check
  - max_daily_loss check
  - allowed_symbol check
  - position_conflict check
  - price_sanity check
  - alert_stale check (max 5 min age)
  - broker_connectivity check
  - Store full ValidationResult with per-check details
  - Return (passed, checks, rejection_reason)

- [ ] **Create `ops_api/execution.py`** — Execution engine:
  - `execute_signal(signal, validation, config)` — main entry point
  - Paper mode: simulate execution with slippage, store order + result
  - Live mode: call KiteClient.place_order, store order + result
  - Dedup key on every order (prevent double-submit on retry)
  - Full logging before/after execution
  - Store ExecutionOrder + ExecutionResult
  - Return success/failure with order details

- [ ] **Verify validation logic** — `uv run python -c "from ops_api.validation import ValidationPipeline; print('OK')"`

### Segment 5: Live Dashboard

**Files:**
- Create: `dashboard/__init__.py`
- Create: `dashboard/app.py`

- [ ] **Create `dashboard/app.py`** — Streamlit dashboard with:
  - Authentication (password gate)
  - Bot status card (running/stopped/paused, paper/live, last heartbeat)
  - Market status indicator
  - Current position display
  - PnL summary (daily, cumulative, max drawdown)
  - Trade counters (total today, wins, losses)
  - Last alert + last validation result
  - Last order result
  - Recent errors list
  - Recent events timeline
  - Recent signals list
  - Charts: equity curve, intraday PnL, trade timeline, signal timeline
  - Auto-refresh (30s interval)
  - Control buttons (pause/resume/flatten/mode toggle) - with auth

- [ ] **Verify dashboard imports** — `uv run python -c "from dashboard.app import main; print('OK')"` (will need streamlit)

### Segment 6: Controls + Health + Heartbeat

**Files:**
- Create: `ops_api/controls.py`
- Create: `ops_api/health.py`
- Modify: `trading_bot/main.py` (minimal — add command polling)

- [ ] **Create `ops_api/controls.py`** — Control endpoints:
  - POST `/control/start` — mark bot as running
  - POST `/control/stop` — issue stop command
  - POST `/control/pause` — issue pause command
  - POST `/control/resume` — cancel pause
  - POST `/control/flatten` — issue flatten command
  - POST `/control/mode` — toggle paper/live mode
  - POST `/control/reload` — reload config command
  - All endpoints: write to `bot_commands` table, auth-protected
  - All endpoints: log to `control_events` table

- [ ] **Create `ops_api/health.py`** — Health check module:
  - `check_api()` — FastAPI responds
  - `check_database()` — SQLite read/write
  - `check_kite_connectivity()` — verify Kite token
  - `check_bot_process()` — bot status from DB
  - `check_config()` — config loaded OK
  - Write heartbeat to DB
  - Write heartbeat to `/tmp/trading-bot-heartbeat.txt`

- [ ] **Modify `trading_bot/main.py`** — Add command polling (minimal):
  - Once per cycle, check `bot_commands` table for pending commands
  - Handle: pause (skip trading but keep running), resume (re-enable), flatten (force exit position), stop (set _shutdown)
  - Mark commands as acked/completed
  - Write periodic status snapshot to `position_snapshots` and `heartbeats` tables

### Segment 7: Security Hardening

**Files:**
- Modify: `deploy.py` — remove hardcoded VPS password
- Modify: `credentials.env` — add warning, move to `.gitignore`

- [ ] **Fix `deploy.py`** — Remove hardcoded `VPS_PASS`. Read from env var or SSH key only
- [ ] **Verify `.gitignore`** — `credentials.env` and `.env` must be gitignored
- [ ] **Add ops API env vars** to `.env.example` documentation

### Segment 8: Deployment + Systemd

**Files:**
- Modify: `deploy.sh`
- Modify: `deploy.py`
- Modify: `deploy.ps1`
- Create: `systemd/ops-api.service`
- Create: `systemd/ops-api.socket` (optional)

- [ ] **Create systemd unit** for ops-api FastAPI server
- [ ] **Update deploy.sh** — install new deps, deploy FastAPI + dashboard services
- [ ] **Update deploy.py** — add ops_api/ and dashboard/ to file list, remove hardcoded password
- [ ] **Update deploy.ps1** — add new files/directories
- [ ] **Update pyproject.toml** — add new deps (streamlit, plotly) as extras

### Segment 9: Tests

**Files:**
- Create: `tests/ops_api/__init__.py`
- Create: `tests/ops_api/test_db.py`
- Create: `tests/ops_api/test_webhook.py`
- Create: `tests/ops_api/test_validation.py`
- Create: `tests/ops_api/test_execution.py`
- Create: `tests/ops_api/test_controls.py`
- Create: `tests/ops_api/test_health.py`

- [ ] **Create test directory** and test files
- [ ] **Run all tests** — `uv run pytest tests/ -v`
- [ ] **Fix failures**
- [ ] **Re-run** until stable

### Segment 10: Final Verification

- [ ] Run `uv run ruff format --check`
- [ ] Run `uv run ruff check`
- [ ] Run `uv run ty check ops_api/` (if applicable)
- [ ] Run `uv run pytest tests/ -v`
- [ ] Verify all imports work
- [ ] Summary report

---

## Execution Handoff

**"Plan complete and saved. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks inline with checkpoints

**Architecture Decision:** Separate FastAPI server + shared SQLite DB (WAL mode). The existing bot polls `bot_commands` table for control signals. No microservices. No Redis/Kafka/Docker.

**Security fixes needed:** Remove hardcoded VPS password from deploy.py, gitignore credentials.env.