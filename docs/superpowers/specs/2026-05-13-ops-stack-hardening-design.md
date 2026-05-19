# Ops Stack Hardening Design

## Architecture: Secure Reverse Proxy Setup

- FastAPI binds to **127.0.0.1:8080** (localhost-only)
- Streamlit binds to **127.0.0.1:8501** (localhost-only)
- **Nginx reverse proxy** exposes only `/webhook/tradingview` externally
- All control/health/internal endpoints remain localhost-only
- UFW firewall for defense-in-depth

## Security Hardening

1. **Log redaction** — strip `secret`, `password`, `token`, `api_key` from logged dicts
2. **DB payload sanitization** — remove `secret` from `raw_payload` before storing
3. **File permissions** — `chmod 600 .env credentials.env`
4. **Firewall** — ufw: allow SSH + nginx only

## Webhook Rate Limiting

- In-memory token bucket: 10 req/min per IP, burst 3
- Exempt localhost/internal requests
- Log rate-limit violations without spamming (once per 60s per IP)

## Performance/Stability

- DB WAL checkpoint with `PRAGMA wal_checkpoint(TRUNCATE)`
- Configurable retention cleanup for old alerts/events/health rows (env var)
- Startup validation: check DB writable, required vars, telegram config
- Notification spam protection: per-type rate limit (30s dedup per event_type)

## Dashboard Polish

- Clearer status indicators (paper/live badge, heartbeat age)
- Kill switch banner with activation details
- Last webhook time display
- Error display with count badge

## Safe Defaults

- `localhost` binding default (not `0.0.0.0`)
- Strict config validation with clear errors
- Heartbeat file writing implemented properly
- Lightweight log rotation (deploy.sh logrotate config)
