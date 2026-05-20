---
name: trading-platform-context
description: Architectural overview of the algorithmic trading platform — components, data flow, deployment, and design decisions. Reference for any AI session working on this project.
---

# Trading Platform — PROJECT CONTEXT

## Overview

This is a **Zerodha Nifty Options algorithmic trading platform** that runs on a VPS. It receives signals from TradingView webhooks, validates them against safety rules, executes paper (simulated) trades via Kite Connect, and exposes operational controls through a FastAPI backend. The frontend is being migrated from Streamlit to Next.js.

## Repository Structure

The repo `free-claude-code/` is two projects in one directory:

- **free-claude-code** (primary): Anthropic API proxy for Claude Code (NVIDIA NIM, OpenRouter, etc.)
- **Trading Platform** (sub-project): The algorithmic trading system

Trading-specific directories:

| Directory | Purpose |
|-----------|---------|
| `trading_bot/` | Polling-loop trading bot — strategy execution, Kite Connect client, state management |
| `ops_api/` | FastAPI backend — webhook ingestion, validation, execution, controls, health, DB |
| `dashboard/` | **OLD** Streamlit frontend (being abandoned) |
| `trading-term/` | **NEW** Next.js frontend (v0.6.0 — all 6 panels operational) |
| `systemd/` | systemd service unit files for VPS deployment |
| `deploy.sh` | One-time VPS setup script (deps, systemd, cron) |
| `start_bot.py` | Entry point: generates access token then launches trading loop |
| `generate_token.py` | Kite Connect access token generation |
| `credentials.env` | Kite Connect credentials (user/password/TOTP secret) |

## Architecture

### Data Flow

```
TradingView Alert
       |
       v
  POST /webhook/tradingview  ───→ ops_api/webhook.py
       |                            - HMAC/secret auth
       |                            - Rate limiting
       |                            - Payload validation
       |                            - Dedup (alert_id)
       v
  SQLite (WAL mode)          ───→ ops_api/db.py
       |                        (webhook_alerts, normalized_signals)
       v
  ValidationPipeline         ───→ ops_api/validation.py
       |                        11 checks: market open, strategy enabled,
       |                        bot mode, cooldown, max trades, max loss,
       |                        allowed symbols, position conflict,
       |                        price sanity, alert staleness, broker connectivity
       |                        (duplicate_alert removed — webhook layer owns dedup)
       v
  ExecutionEngine            ───→ ops_api/execution.py
       |                        PaperBroker (simulated fills w/ slippage)
       |                        OR KiteClient (live orders — currently unused)
       v
  PositionManager (post-fill) ───→ ops_api/position_manager.py
       |                         open_or_adjust() — lifecycle (same-side adjust,
       |                         opposite-side reduce/close/reverse)
       |                         Realized PnL computed on reduce/close
       |                         Backward compat: bot_status + position_snapshots
       v
  SQLite (positions, execution_orders, position_snapshots, risk_counters)

=== Parallel System ===

  Trading Bot (trading_bot/main.py)
       |  Polling loop (30s intervals)
       |  Connects via KiteClient → Kite Connect API
       |  Fetches Nifty 50 candle data
       |  Computes VWAP, EMA, ATR, ORB signals
       |  Manages position state (module-level dict)
       |
       v
  POST /heartbeat ───→ ops_api (bot_status, kite_connected)
```

### Component Map

#### `ops_api/` — FastAPI Backend (port 8080, runs 24/7)

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI app, lifespan, CORS, all endpoint definitions |
| `config.py` | OpsApiConfig dataclass, loaded from `OA_*` env vars |
| env vars |
| `db.py` | DatabaseManager — SQLite WAL, all CRUD for all tables |
| `models.py` | Pydantic models: SignalSide, ValidationResult, ExecutionOrder, BotStatus, Heartbeat, etc. |
| `webhook.py` | TradingView webhook handler: auth, dedup, normalization |
| `validation.py` | ValidationPipeline: 11 pre-trade safety checks (dedup owned by webhook layer) |
| `execution.py` | ExecutionEngine + PaperBroker: order lifecycle with dedup |
| `controls.py` | Control action handler: start/stop/pause/kill/flatten/set_mode |
| `health.py` | Health check aggregation, heartbeat writing |
| `notifier.py` | TelegramNotifier — alert_system, alert_trade, alert_error |
| `sensitive.py` | Payload redaction/sanitization utilities |
| `position_models.py` | Phase 4 — PositionState, PortfolioSnapshot, PositionMutationResult dataclasses |
| `position_manager.py` | Phase 4 — lifecycle (open/adjust/reduce/close/reverse), PnL, MTM, portfolio, flatten |
| `risk_engine.py` | Phase 1+4 — kill switch + per-strategy limits + position-aware checks |
| `strategy_engine.py` | Phase 1 — Strategy registry routing + validation + risk + execution orchestration |
| `strategies/` | Phase 1 — BaseStrategy ABC, StrategyRegistry, DefaultStrategy |
| `indicators.py` | Phase 2 — Pure-function EMA, ATR, VWAP |
| `market_data/` | Phase 2 — OHLCVCache, KiteConnectMarketData provider |
| `scanner/` | Phase 2 — BaseScanner ABC, MomentumScanner, VolumeScanner |
| `scheduler.py` | Phase 2 — ScanScheduler daemon thread with heartbeat metrics |
| `scan_metrics.py` | Phase 3 — Thread-safe ScanMetrics singleton

Key endpoints:
- `GET /health` — Aggregate health checks
- `GET /status` — Bot status, heartbeat, kill switch state
- `POST /webhook/tradingview` — Signal ingestion
- `POST /control/{action}` — start/stop/pause/resume/flatten/set_mode/kill/reset_kill
- `GET /dashboard/data` — Aggregated dashboard payload
- `GET /dashboard/analytics` — Analytics data
- `POST /heartbeat` — Bot heartbeat ingestion

#### `trading_bot/` — Trading Bot (runs 9:15 AM-3:30 PM IST, triggered by systemd timer)

| File | Responsibility |
|------|---------------|
| `main.py` | Main loop: signal dispatch, exit monitoring, heartbeat posting |
| `config.py` | TradingBotConfig dataclass, loaded from `TB_*`env vars |
| `kite_client.py` | KiteClient — thin wrapper around KiteConnect with retry |
| `data.py` | Candle data structures, VWAP, EMA, ATR, ORB, market regime detection |
| `strategies.py` | Strategy implementations: VWAP pullback, ORB breakout, EMA filter |
| `state.py` | Module-level state dict for position tracking (Phase 1 — will be upgraded) |
| `risk.py` | RiskManager — consecutive-loss circuit breaker, gate checks |
| `options.py` | InstrumentCache, ATM strike selection, weekly expiry calculation |

### Database Schema (SQLite WAL mode)

**Tables:** webhook_alerts, normalized_signals, validation_results, execution_orders, positions, position_snapshots, bot_status, bot_commands, health_checks, heartbeats, control_events, risk_counters, kill_switch_events, notification_log

Key design:
- All timestamps stored as ISO-8601 UTC strings
- WAL mode enabled for concurrent reader/writer safety
- Per-operation connection (thread-safe)
- bot_status is singleton row (id=1)
- dedup_key unique constraint on execution_orders
- kill_switch columns live on bot_status table
- positions table has partial unique index: `ON positions(symbol) WHERE status = 'open'` — one open per symbol, unlimited closed history

### Deployment Architecture (VPS)

**Three systemd services:**

1. **ops-api.service** — Runs 24/7, FastAPI on port 8080
2. **dashboard.service** — Runs 24/7, Streamlit on port 8501 (being replaced)
3. **trading-bot.service** — Triggered by timer, Mon-Fri 9:00 AM IST

**Systemd timer:** `trading-bot.timer` — Mon-Fri 9:00 AM IST Asia/Kolkata

**Cron:** Generates fresh Kite access token at 8:45 AM IST weekdays

Bot path: `/opt/trading-bot/`
Log path: `/var/log/trading-bot/`

## Key Design Decisions

### Safety-First Architecture
- **Paper mode is default** — `paper_mode=True` in config, no real orders unless explicitly enabled
- **Kill switch** — Activatable via API, stops all trading, logs event
- **Two-gate pipeline** — Signal → Auth → Rate Limit → Dedup → Validate → Execute
- **Validation runs ALL checks** — no short-circuiting; full audit trail
- **Dedup at multiple levels** — webhook alert_id, execution dedup_key

### Paper/Live Separation
- Paper mode uses `PaperBroker` with configurable slippage
- Live mode uses `KiteClient.place_order()` — only when paper_mode=False
- Execution engine checks mode before broker dispatch
- Separate config flags for paper vs live behavior

### Kite Connect Integration
- Access token generated daily via `generate_token.py` (TOTP-based login)
- Token stored in env, read by trading botconfig
- KiteClient verifies connection with `profile()` call on init
- Retry decorator with 3 attempts for API calls
- TokenException/InputException are NOT retried (fatal auth errors)

### Frontend Migration Status
- **Streamlit dashboard** (`dashboard/app.py`) — functional but unstable, being abandoned
- **New Next.js frontend** (`trading-term/`) — v0.6.0, operational
  - 6 panels: TopStatusBar, ExecutionFeed, PositionPanel, PnLRiskPanel, SignalFeed, ControlsPanel
  - 3 polling hooks: `useDashboardData` (7s), `useExecutionFeed` (3s), `useApiStatus` (10s)
  - Same-origin API proxy via Next.js `rewrites()`: `/api/backend/*` → `http://127.0.0.1:8080/*`
  - Stale/offline detection with visual indicators
  - Scroll-stable execution feed via `useLayoutEffect`
  - TailwindCSS v4, dark theme trading terminal aesthetic
- **Decision made:** abandon Streamlit, build professional quant-terminal in Next.js

### URL Routing
- **Frontend APIs:** Browser → `/api/backend/*` → Next.js rewrite → `http://127.0.0.1:8080/*`
- **Webhook:** TradingView → port 80 (Nginx) → `127.0.0.1:8080/webhook/tradingview`
- **Direct backend:** Internal only at `http://127.0.0.1:8080/*` (not publicly exposed)

### Deployment Changes (2026-05-18)
- **Nginx** — Reverse proxy on port 80 for TradingView webhooks (`ops_api/nginx-tradingview.conf`)
- **FastAPI binding** — Changed from `0.0.0.0` to `127.0.0.1` in `systemd/ops-api.service`
- **Source IP** — Backend reads `X-Real-IP` header when behind proxy (fallback: `X-Forwarded-For`, then `request.client.host`)

### Position Management (Phase 4 — 2026-05-21)
- **One net position per symbol** — Partial unique index `WHERE status = 'open'` enforces this at DB level
- **BUY/SELL → LONG/SHORT mapping** — Trading actions (from signals) map to position sides internally
- **Weighted average entry** — Same-side adjust computes `(old_price * old_qty + new_price * new_qty) / total_qty`
- **PnL direction** — LONG close: `(exit - entry) * qty * 1`, SHORT close: `(exit - entry) * qty * -1`
- **Reversal semantics** — Opposite-side larger qty first CLOSEs existing lifecycle, then OPENS new one (two distinct rows)
- **MTM purity** — `mark_to_market()` only touches current_price and unrealized_pnl (never realized_pnl)
- **Additive migration** — PositionManager=None is valid no-op everywhere (RiskEngine, ExecutionEngine, StrategyEngine)
- **Backward compat** — `update_bot_status_position_compat()` + `insert_position_snapshot_for_compat()` bridge legacy consumers

## Important Safety Rules

1. **NEVER place live orders** unless explicitly instructed
2. Preserve paper/live separation
3. Preserve kill switch behavior
4. Preserve validation safeguards
5. Preserve webhook security (HMAC, rate limiting)
6. Avoid overengineering
7. Keep stack VPS-friendly
8. Preserve backend stability — backend is verified working, do not break it