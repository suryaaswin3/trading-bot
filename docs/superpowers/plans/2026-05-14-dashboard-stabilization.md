# Dashboard Stabilization + Quant Terminal Redesign

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix operational state accuracy, plumb real data from bot to dashboard, tag test/soak data, rebuild UI as professional quant terminal.

**Architecture:** Bot pushes heartbeats + snapshots to ops API via HTTP. Ops API serves real data. Dashboard reads real state, shows execution feed + real analytics.

**Tech Stack:** FastAPI, SQLite, Streamlit, Plotly, httpx, loguru

---

### Task 1: Plumb heartbeat POST from bot to ops API

**Files:**
- Modify: `trading_bot/main.py` (add HTTP heartbeat POST)
- Modify: `trading_bot/config.py` (add ops_api_url field)

- [ ] **Add `ops_api_url` to TradingBotConfig**

In `trading_bot/config.py`, add field:
```python
ops_api_url: str = ""
```

- [ ] **Add heartbeat POST to main loop**

In `trading_bot/main.py`, after `_log_heartbeat()`, add HTTP POST with httpx:
```python
def _post_heartbeat(config):
    if not config.ops_api_url:
        return
    try:
        import httpx
        httpx.post(
            f"{config.ops_api_url}/heartbeat",
            json={
                "bot_status": "running",
                "bot_mode": "paper" if config.paper_mode else "live",
                "last_action": state.get("active_strategy") or "waiting",
                "trades_today": state.get("trades_today", 0),
                "daily_pnl": state.get("daily_pnl", 0.0),
                "kite_connected": kite and kite.is_connected() if kite else False,
            },
            timeout=5,
        )
    except Exception:
        pass
```

Call `_post_heartbeat(config)` inside the main loop after `_log_heartbeat`.

### Task 2: Add data_source column for test/soak filtering

**Files:**
- Modify: `ops_api/db.py` (add data_source columns to signals, orders, alerts)
- Modify: `ops_api/webhook.py` (pass data_source)
- Add: dashboard filter queries

- [ ] **Add data_source DEFAULT 'production' to normalized_signals and execution_orders**

In `ops_api/db.py`, `_SCHEMA_SQL`, add to `normalized_signals`:
```sql
data_source TEXT NOT NULL DEFAULT 'production'
```
Add to `execution_orders`:
```sql
data_source TEXT NOT NULL DEFAULT 'production'
```

Also ALTER TABLE migration in `init_schema()`:
```python
for col in ("data_source TEXT NOT NULL DEFAULT 'production'",):
    try:
        conn.execute(f"ALTER TABLE normalized_signals ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(f"ALTER TABLE execution_orders ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass
```

### Task 3: Add analytics query endpoints to ops API

**Files:**
- Modify: `ops_api/db.py` (add analytics queries)
- Modify: `ops_api/main.py` (add `/dashboard/analytics` endpoint)

- [ ] **Add analytics query methods to DatabaseManager**

```python
def get_execution_latency(self, limit=100):
    conn = self._connect()
    try:
        rows = conn.execute(
            """SELECT created_at, updated_at, 
               (julianday(updated_at) - julianday(created_at)) * 86400 AS latency_seconds
               FROM execution_orders WHERE updated_at IS NOT NULL
               ORDER BY created_at DESC LIMIT ?""", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_pnl_by_strategy(self, limit=500):
    conn = self._connect()
    try:
        rows = conn.execute(
            """SELECT strategy, SUM(CASE WHEN status='filled' THEN 1 ELSE 0 END) as trades,
               AVG(CASE WHEN status='filled' THEN price ELSE NULL END) as avg_price
               FROM execution_orders GROUP BY strategy LIMIT ?""", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_rejection_stats(self, limit=100):
    conn = self._connect()
    try:
        rows = conn.execute(
            """SELECT rejection_reason, COUNT(*) as count FROM validation_results
               WHERE passed=0 GROUP BY rejection_reason ORDER BY count DESC LIMIT ?""", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

### Task 4: Rewrite dashboard as quant terminal

**Files:**
- Rewrite: `dashboard/app.py`

Single file, complete rewrite. Dark terminal theme, compact layout. All CSS inline via st.markdown.

Layout:
- Top bar: status badges (bot, market, mode, kite, heartbeat age, kill switch, strategy)
- Left sidebar: controls (pause/resume, flatten, live toggle, kill switch)
- Center: execution feed (chronological, PnL-colored rows, expandable)
- Right sidebar: rejection reasons, cooldown, risk state, broker status
- Bottom: trades table + notifications + errors
- Charts: cumulative PnL, drawdown, daily PnL bars, profit factor — shown only if data exists

No scatter timelines. No floating dots. "Insufficient data" for empty analytics.