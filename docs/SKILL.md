# Trading Platform AI Session Guide

Standard operating procedures for AI-assisted development on this trading platform.
Read this BEFORE making any code changes.

---

## 1. ALWAYS Start Here

Before any change:
1. Read `docs/PROJECT_CONTEXT.md` — understand the full architecture
2. Read `docs/CURRENT_STATUS.md` — understand what state things are in
3. Read `.env` and `.env.example` — understand configuration
4. Read `AGENTS.md` — understand CI/coding standards
5. Read the existing test file for the module you're changing

## 2. Safety Rules (NEVER Violate)

- **Never place live orders** unless explicitly asked. instructed. `paper_mode=True` must be the default.
- Preserve the **two-gate validation**: risk_manager.can_enter() → _execute_entry_signal()
- Preserve **webhook security**: HMAC auth, rate limiting, dedup, stale detection
- Preserve **kill switch behavior**: must block ALL trade signals when active
- Preserve **paper/live separation**: PaperBroker vs KiteClient dispatch
- Never remove or weaken **validation pipeline checks**
- Never expose **credentials** in logs or API responses (use `sensitive.py` utilities)

## 3. Coding Standards

- Python 3.14 (target-version in ruff config)
- Always use `uv run` to run files, not global `python`
- Run checks in order: `uv run ruff format` → `uv run ruff check` → `uv run ty check` → `uv run pytest`
- All 5 checks enforced in CI (tests.yml). Failing checks block merge.
- Do not add `# type: ignore` or `# ty: ignore` — fix underlying type issues
- Add tests for new changes including edge cases
- Loguru for logging throughout

## 4. Common Pitfalls to Avoid

### On the Trading Bot (`trading_bot/`)
- **State is module-level** (`state.py` dict) — not persisted across restarts. When adding state, consider the StateManager refactor.
- **Kite token expires** — `generate_token.py` runs daily at 8:45 AM via cron. If you need token during development, run it manually.
- **Market hours matter** — Strategies only activate during NSE hours (9:15-15:30 IST). Outside those hours, the bot polls and sleeps.
- **Candle dedup** — `_last_entry_candle_time` prevents duplicate entries on the same candle. Not persisted.
- **Paper order IDs reset** on bot restart (module-level counter).

### On the Ops API (`ops_api/`)
- **Cooldown is hardcoded** in `validation.py` (line ~77). If you change TradingBotConfig cooldown, update this too.
- **Config values duplicated** — OpsApiConfig and TradingBotConfig share some values (cooldown, max_trades, max_loss). Keep in sync.
- **DB timestamps are UTC strings** — all stored as ISO-8601 UTC. IST conversion done in application layer.
- **New connection per operation** — DatabaseManager opens/closes per call. Thread-safe but worth knowing.
- **WAL checkpoint on startup** — `db.wal_checkpoint()` runs in lifespan.

### On the Frontend (`trading-term/`)
- **Directory is empty** — full Next.js initialization needed
- **Backend is STABLE** — do not modify backend APIs to suit frontend preferences. The APIs are verified working.
- **Streamlit is abandoned** — do not fix Streamlit bugs. Do not add features to Streamlit.
- **Dashboard API endpoints are ready** — `/dashboard/data`, `/dashboard/analytics` exist and are tested.

### On the Free-Claude-Code Proxy
- The repo houses TWO projects. Be clear about which one you're modifying.
- `pyproject.toml` packages both. The `trading_bot`, `ops_api`, and `dashboard` packages are included in the wheel build.
- Tests for the proxy (`tests/api/`, `tests/providers/`, etc.) are separate from trading tests.

## 5. Testing Requirements

| Change Type | Required Tests |
|-------------|----------------|
| Bug fix in trading bot | Add test that exposes the bug, then fix |
| New strategy | Test signal generation, edge cases, market conditions |
| New validation check | Unit test for the check, integration in ValidationPipeline |
| DB schema change | Migration test, read/write test, backward compat |
| Control action | Test action execution, audit trail, error cases |
| Frontend component | Component test + integration with mocked API |

**Running trading-specific tests:**
```
uv run pytest tests/trading_bot/ -v
uv
uv run pytest tests/ops_api/ -v
```

## 6. Deployment Checklist

When deploying changes to the VPS:
1. Run full check suite: `uv run ruff format && uv run ruff check && uv run ty check && uv run pytest`
2. Verify paper mode still works: `uv run python vps_paper_test.py`
3. Upload via: `uv run python vps_upload.py`
4. The deploy script on VPS handles git commit + systemd restart

## 7. Key Environment Variables

Trading bot: `TB_*` prefix (e.g., `TB_PAPER_MODE`, `TB_KITE_API_KEY`, `TB_VWAP_LOOKBACK_CANDLES`)
Ops API: `OA_*` prefix (e.g., `OA_PORT`, `OA_WEBHOOK_SECRET`, `OA_API_KEY`, `OA_TELEGRAM_BOT_TOKEN`)
Kite: `KITE_*` (user/password/TOTP for token generation)

## 8. Emergency Procedures

- **Kill switch**: POST `/control/kill` with X-API-Key header
- **Reset kill switch**: POST `/control/reset_kill`
- **Flatten positions**: POST `/control/flatten`
- **Check health**: GET `/health`
- **Check status**: GET `/status`
- **View logs**: `journalctl -u ops-api.service`, `journalctl -u trading-bot.service`
- **Force bot shutdown from VPS**: `systemctl stop trading-bot.service`

## 9. Key File Quick Reference

| Task | File |
|------|------|
| Add new trading strategy | `trading_bot/strategies.py` + `trading_bot/main.py` dispatch |
| Add validation check | `ops_api/validation.py` + `ops_api/models.py` (add to ValidationCheck enum) |
| Add API endpoint | `ops_api/main.py` |
| Add DB query | `ops_api/db.py` |
| Add control action | `ops_api/controls.py` + `ops_api/models.py` (add to ControlAction enum) |
| Change trading config | `trading_bot/config.py` (add field) |
| Change ops API config | `ops_api/config.py` (add field + env mapping) |
| Add env var | Both config files + `.env` + `.env.example` |
| Update deployment | `deploy.sh` |
| Update systemd | `systemd/ops-api.service`, `systemd/dashboard.service` |
| Build frontend | `trading-term/` (create from scratch) |