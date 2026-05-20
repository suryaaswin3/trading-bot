# Known Issues

| Issue | Status | Workaround |
|-------|--------|------------|
| Kite credentials expired | Token from May 14 | Run `generate_token.py` before next bot session |
| Kite access token expires daily | Must regenerate each day | Cron at 8:45 AM IST handles this in production |
| Kite client fails on startup | Expected — token expired | Ops API runs in paper-only mode; dashboard shows kite_connected=false correctly |
| No WebSocket streaming | Polling only (Phase 3) | Acceptable for current operational needs |
| Execution feed scroll stability | Unverified with real data | Needs >= 1 page of orders in DB |
| Node.js not in PATH (Windows) | Installed at `%LOCALAPPDATA%\nodejs` | Use full path or add to PATH |
| Single-position assumptions in dashboard | Phase 4 refactored backend to multi-position | Frontend PositionPanel still shows single legacy position via bot_status (positions array available) |

## Recently Resolved (2026-05-21 — Phase 4)

| Issue | Fix |
|-------|-----|
| **Single-position assumptions throughout runtime** | Replaced with PositionManager (one net position per symbol via partial unique index). BUY/SELL → LONG/SHORT mapping. Weighted average entry on adjust. Reversal lifecycle (close old + open new). |
| **Portfolio state was legacy bot_status fields only** | PositionManager owns all state mutations. PortfolioSnapshot dataclass with exposure, PnL, concentration. RiskEngine position-aware checks. |
| **No realized PnL tracking** | Realized PnL computed on reduce/close events using direction-aware formula. Stored as cumulative total on position rows. Individual trade PnL lives in executions/events. |
| **MTM mutated realized PnL** | mark_to_market() now only touches current_price and unrealized_pnl. realized_pnl is append-only via executions. Verified with test_mtm_does_not_touch_realized. |
| **DB positions lacked schema** | Added positions table with partial unique index (one open per symbol, unlimited closed). 9 CRUD methods. Backward compat bridges to bot_status and position_snapshots. |

## Recently Resolved (2026-05-19)

| Issue | Fix |
|-------|-----|
| **Validation pipeline duplicate_alert false rejection** | Removed `_check_staleness()` from validation layer. Alert-level dedup stays at webhook layer (by alert_id). Trade-level dedup stays at execution layer (by dedup_key). |
| **Webhook path never executed trades** | After validation passes, the webhook endpoint now calls `executor.execute(signal, validation, mode="paper")` via PaperBroker. Execution result returned in response and persisted to DB. |
| **Dashboard showed KITE CONNECTED despite expired token** | Dashboard endpoint computes staleness-aware kite_connected at query time based on heartbeat freshness. On startup, if Kite client fails, `bot_status.kite_connected` is reset to False via merge (not destructive upsert). |
| **Health check ignored heartbeat age** | `check_bot()` now reports `warn` if `last_heartbeat_at` > 300s stale. Added `check_kite()` component. Health endpoint runs 7 checks total. |
| **Heartbeat never refreshed on webhook execution** | After successful webhook execution fill, `write_heartbeat()` is called to refresh liveness tracking. |
| **upsert_bot_status destructive on partial data** | INSERT OR REPLACE on id=1 blanks unset fields. Now uses `merged = dict(existing); merged[key] = val; db.upsert_bot_status(merged)` pattern everywhere. |