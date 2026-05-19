# Next Actions

**Date:** 2026-05-19
**Version:** v0.3.1 (Phase 2.7 — validation-order fix + state reporting fix)

---

## Immediate (Current Session)

- [x] Write CURRENT_STATUS.md with full operational snapshot
- [x] Write KNOWN_ISSUES.md with current and resolved issues
- [x] Write NEXT_ACTION.md (this file)
- [ ] Commit current working state to git
- [ ] Verify frontend rendering of new health/kite fields and execution feed

## Next Session

### 1. Operational Observation (Resume)
- Start both services (FastAPI + Next.js)
- Verify all 7 health checks return correct status
- Verify dashboard shows kite_connected=false (with reason)
- Verify execution result appears in webhook response
- Monitor frontend polling behavior for regressions
- Send test webhook to verify full pipeline end-to-end

### 2. VPS Paper Trading (Optional)
- Deploy current code to VPS
- Update systemd ops-api.service if needed
- Configure Nginx webhook reverse proxy
- Verify TradingView → VPS → Ops API pipeline end-to-end
- Run paper trading during NSE hours

### 3. Phase 3 Candidates (Future)
- WebSocket streaming for real-time position/order updates
- Enhanced execution feed with order status badges
- Historical PnL chart in PnLRiskPanel
- Advanced signal filtering in SignalFeed

## Current Deployment State

| Service | Status | Notes |
|---------|--------|-------|
| Ops API (FastAPI) | ✅ Running on 127.0.0.1:8080 | v0.3.1, paper mode, Kite disconnected |
| Frontend (Next.js) | ✅ Running on 0.0.0.0:3000 | v0.3.0, 6 panels operational |
| Kite Connect | ❌ Disconnected | Token expired (from May 14) |
| Telegram Notifier | ✅ Healthy | System startup alert sent |
| Trading Bot | ⛔ Not running | Only during NSE hours on VPS |
| SQLite | ✅ Healthy | WAL mode, ops_data.db |