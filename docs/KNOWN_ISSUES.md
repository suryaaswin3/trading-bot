# Known Issues

| Issue | Status | Workaround |
|-------|--------|------------|
| Kite credentials expired | Token from May 14 | Run `generate_token.py` before next bot session |
| Kite access token expires daily | Must regenerate each day | Cron at 8:45 AM IST handles this in production |
| Kite client fails on startup | Expected — token expired | Ops API runs in paper-only mode; dashboard shows kite_connected=false correctly |
| No WebSocket streaming | Polling only (Phase 3) | Acceptable for current operational needs |
| Execution feed scroll stability | Unverified with real data | Needs >= 1 page of orders in DB |
| Node.js not in PATH (Windows) | Installed at `%LOCALAPPDATA%\nodejs` | Use full path or add to PATH |

## Recently Resolved (2026-05-19)

| Issue | Fix |
|-------|-----|
| **Validation pipeline duplicate_alert false rejection** | Removed `_check_staleness()` from validation layer. Alert-level dedup stays at webhook layer (by alert_id). Trade-level dedup stays at execution layer (by dedup_key). |
| **Webhook path never executed trades** | After validation passes, the webhook endpoint now calls `executor.execute(signal, validation, mode="paper")` via PaperBroker. Execution result returned in response and persisted to DB. |
| **Dashboard showed KITE CONNECTED despite expired token** | Dashboard endpoint computes staleness-aware kite_connected at query time based on heartbeat freshness. On startup, if Kite client fails, `bot_status.kite_connected` is reset to False via merge (not destructive upsert). |
| **Health check ignored heartbeat age** | `check_bot()` now reports `warn` if `last_heartbeat_at` > 300s stale. Added `check_kite()` component. Health endpoint runs 7 checks total. |
| **Heartbeat never refreshed on webhook execution** | After successful webhook execution fill, `write_heartbeat()` is called to refresh liveness tracking. |
| **upsert_bot_status destructive on partial data** | INSERT OR REPLACE on id=1 blanks unset fields. Now uses `merged = dict(existing); merged[key] = val; db.upsert_bot_status(merged)` pattern everywhere. |