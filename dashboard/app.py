"""Quant-terminal dashboard — dark industrial aesthetic, execution-first layout."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

st.set_page_config(
    page_title="Orbital Terminal", layout="wide", initial_sidebar_state="collapsed"
)
load_dotenv()

API_BASE = os.getenv("OA_API_URL", "http://localhost:8080")
API_KEY = os.getenv("OA_API_KEY", "")
DASH_USER = os.getenv("OA_DASHBOARD_USERNAME", "admin")
DASH_PASS = os.getenv("OA_DASHBOARD_PASSWORD", "")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {
  --bg-deep: #080c14;
  --bg-surface: #0d1320;
  --bg-card: #111827;
  --bg-hover: #1a2332;
  --border: #1e293b;
  --border-bright: #2e3a55;
  --text-primary: #e2e8f0;
  --text-secondary: #64748b;
  --text-muted: #475569;
  --accent-green: #22c55e;
  --accent-green-dim: #14532d;
  --accent-red: #ef4444;
  --accent-red-dim: #450a0a;
  --accent-blue: #38bdf8;
  --accent-yellow: #eab308;
  --accent-yellow-dim: #422006;
  --glow-green: 0 0 12px rgba(34,197,94,0.15);
  --glow-red: 0 0 12px rgba(239,68,68,0.15);
}

.stApp, body { background: var(--bg-deep); color: var(--text-primary); font-family: 'JetBrains Mono', 'Fira Code', monospace; }
.block-container { max-width: 100%; padding: 0.35rem 0.75rem; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 4px; gap: 0; padding: 0; }
.stTabs [data-baseweb="tab"] { font-size: 11px; color: var(--text-secondary); padding: 6px 16px; border-right: 1px solid var(--border); letter-spacing: 0.5px; }
.stTabs [aria-selected="true"] { color: var(--accent-blue) !important; background: var(--bg-card) !important; }

/* Cards / Metrics */
div[data-testid="stMetric"] { background: var(--bg-card); border: 1px solid var(--border); border-radius: 3px; padding: 6px 10px; }
div[data-testid="stMetric"] label { color: var(--text-secondary); font-size: 10px; text-transform: uppercase; letter-spacing: 1px; }
div[data-testid="stMetric"] div { color: var(--text-primary); font-size: 13px; font-weight: 600; }

/* Buttons */
.stButton button { font-size: 11px; font-family: 'JetBrains Mono', monospace; border-radius: 3px; height: 26px; border: 1px solid var(--border); background: var(--bg-card); color: var(--text-primary); transition: all 0.15s; }
.stButton button:hover { border-color: var(--border-bright); background: var(--bg-hover); box-shadow: inset 0 1px 0 rgba(255,255,255,0.05); }
.stButton button:active { transform: translateY(1px); }
.stButton button[kind="primary"] { background: var(--accent-red-dim); border-color: var(--accent-red); color: var(--accent-red); }
.stButton button[kind="primary"]:hover { background: #5a0a0a; }

/* DataFrames */
.stDataFrame { font-size: 11px; }
div[data-testid="stDataFrame"] td { font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 2px 8px !important; }
div[data-testid="stDataFrame"] th { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-secondary); background: var(--bg-surface); }
div[data-testid="stDataFrame"] tr:nth-child(even) { background: rgba(30,41,59,0.3); }

/* Expander */
.stExpander { border: 1px solid var(--border) !important; background: var(--bg-surface) !important; border-radius: 3px !important; }

/* Sidebar */
section[data-testid="stSidebar"] { background: var(--bg-surface); border-right: 1px solid var(--border); }
section[data-testid="stSidebar"] .stButton button { width: 100%; }
div[data-testid="stCheckbox"] label { font-size: 11px; color: var(--text-secondary); }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-deep); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-bright); }

/* Custom components */
.badge { display: inline-block; padding: 2px 8px; border-radius: 2px; font-size: 10px; font-weight: 600; letter-spacing: 0.5px; }
.badge-green { background: var(--accent-green-dim); color: var(--accent-green); border: 1px solid rgba(34,197,94,0.3); box-shadow: var(--glow-green); }
.badge-red { background: var(--accent-red-dim); color: var(--accent-red); border: 1px solid rgba(239,68,68,0.3); box-shadow: var(--glow-red); }
.badge-yellow { background: var(--accent-yellow-dim); color: var(--accent-yellow); border: 1px solid rgba(234,179,8,0.3); }
.badge-blue { background: rgba(56,189,248,0.1); color: var(--accent-blue); border: 1px solid rgba(56,189,248,0.2); }
.badge-gray { background: rgba(100,116,139,0.1); color: var(--text-secondary); border: 1px solid rgba(100,116,139,0.2); }

.section-label { color: var(--text-secondary); font-size: 9px; text-transform: uppercase; letter-spacing: 1.5px; margin: 10px 0 4px 0; border-bottom: 1px solid var(--border); padding-bottom: 3px; }
.section-title { color: var(--accent-blue); font-size: 10px; font-weight: 600; letter-spacing: 0.5px; margin: 4px 0; }

.exec-feed { max-height: 420px; overflow-y: auto; background: var(--bg-deep); border: 1px solid var(--border); border-radius: 3px; }
.trade-row { padding: 3px 8px; border-bottom: 1px solid rgba(30,41,59,0.5); font-size: 11px; display: flex; justify-content: space-between; align-items: center; transition: background 0.1s; }
.trade-row:hover { background: var(--bg-hover); }
.trade-row:last-child { border-bottom: none; }

.pnl-pos { color: var(--accent-green); }
.pnl-neg { color: var(--accent-red); }
.val-ok { color: var(--accent-green); }
.val-rej { color: var(--accent-yellow); }

.topbar-badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 3px; font-size: 10px; font-weight: 500; letter-spacing: 0.3px; }
.topbar-badge .dot { width: 6px; height: 6px; border-radius: 50%; }
.dot-green { background: var(--accent-green); box-shadow: var(--glow-green); }
.dot-red { background: var(--accent-red); box-shadow: var(--glow-red); }
.dot-yellow { background: var(--accent-yellow); }
.dot-blue { background: var(--accent-blue); }
.dot-gray { background: var(--text-muted); }

.control-group { background: var(--bg-card); border: 1px solid var(--border); border-radius: 3px; padding: 8px; margin-bottom: 6px; }
</style>
""",
    unsafe_allow_html=True,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _h():
    return {"X-API-Key": API_KEY} if API_KEY else {}


def fetch(path: str) -> dict[str, Any] | None:
    try:
        r = httpx.get(f"{API_BASE}{path}", headers=_h(), timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def post_control(action: str, params: dict | None = None) -> bool:
    try:
        body: dict = {"triggered_by": "dashboard"}
        if params:
            body["params"] = params
        r = httpx.post(
            f"{API_BASE}/control/{action}", headers=_h(), json=body, timeout=10
        )
        return r.status_code == 200
    except Exception:
        return False


def age_s(ts_str: str | None) -> str:
    if not ts_str or ts_str == "N/A":
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        s = int(datetime.now(UTC).timestamp() - dt.timestamp())
        if s < 60:
            return f"{s}s"
        return f"{s // 60}m{s % 60}s"
    except Exception:
        return "N/A"


def dot_color(status: str) -> str:
    return {"running": "green", "paused": "yellow", "stopped": "red"}.get(
        status, "gray"
    )


def fmt_pnl(v: float) -> str:
    cls = "pnl-pos" if v >= 0 else "pnl-neg"
    sign = "+" if v >= 0 else ""
    return f'<span class="{cls}">{sign}₹{v:,.2f}</span>'


# ── Auth ─────────────────────────────────────────────────────────────────


def check_password() -> bool:
    if not DASH_PASS:
        return True
    if st.session_state.get("dash_auth"):
        return True
    _, c, _ = st.columns([1, 2, 1])
    with c:
        st.markdown(
            '<div style="margin-top:80px;text-align:center;color:#64748b;font-size:10px;letter-spacing:2px">ORBITAL TERMINAL</div>'
        )
        st.markdown(
            '<div style="text-align:center;font-size:22px;font-weight:700;margin:4px 0 20px 0">login</div>'
        )
        u = st.text_input("Username", value=DASH_USER, key="login_user")
        p = st.text_input("Password", type="password", key="login_pass")
        if st.button(
            "Authenticate", type="primary", use_container_width=True, key="login_btn"
        ):
            if u == DASH_USER and p == DASH_PASS:
                st.session_state.dash_auth = True
                st.rerun()
            else:
                st.error("Invalid credentials")
    return False


# ── Render sections ──────────────────────────────────────────────────────


def render_topbar(d: dict[str, Any]) -> None:
    bs = d.get("bot_status", "stopped")
    bm = d.get("bot_mode", "paper")
    kc = d.get("kite_connected", False)
    ks = d.get("kill_switch", {}).get("active", False)
    hb = d.get("last_heartbeat", {})
    hb_age = age_s(hb.get("timestamp"))
    strategy = (
        d.get("bot_status", {}).get("active_strategy")
        if isinstance(d.get("bot_status"), dict)
        else "—"
    )
    dpnl = d.get("daily_pnl", 0.0)
    bt = d.get("trades_today", 0)

    html = '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">'
    items = [
        ("bot", bs.upper(), dot_color(bs)),
        ("mkt", "OPEN", "green"),
        ("mode", bm.upper(), "blue" if bm == "paper" else "red"),
        ("kite", "CONN" if kc else "DOWN", "green" if kc else "red"),
        (
            "hb",
            hb_age,
            "green"
            if hb_age != "N/A" and "s" in hb_age and int(hb_age.rstrip("sm")) < 300
            else "yellow",
        ),
        ("ks", "ARMED" if ks else "SAFE", "red" if ks else "gray"),
        (strategy[:8], strategy[:8] or "—", "blue"),
        ("trd", str(bt), "green"),
        ("pnl", f"{dpnl:+.0f}", "green" if dpnl >= 0 else "red"),
    ]
    for label, val, clr in items:
        d_clr = {
            "green": "dot-green",
            "red": "dot-red",
            "yellow": "dot-yellow",
            "blue": "dot-blue",
            "gray": "dot-gray",
        }.get(clr, "dot-gray")
        html += f'<div class="topbar-badge"><span class="dot {d_clr}"></span>{label.upper()}<span style="color:var(--accent-{clr})">{val}</span></div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_controls() -> None:
    ks = st.session_state.get("ks", False)
    dis = ks

    st.sidebar.markdown(
        '<div class="section-label">Terminal</div>', unsafe_allow_html=True
    )
    st.sidebar.markdown('<div class="control-group">', unsafe_allow_html=True)
    c1, c2 = st.sidebar.columns(2)
    if c1.button(
        "▶ Start", use_container_width=True, disabled=dis, key="ctrl_start"
    ) and post_control("start"):
        st.rerun()
    if c2.button(
        "■ Stop", use_container_width=True, disabled=dis, key="ctrl_stop"
    ) and post_control("stop"):
        st.rerun()
    if c1.button(
        "❚❚ Pause", use_container_width=True, disabled=dis, key="ctrl_pause"
    ) and post_control("pause"):
        st.rerun()
    if c2.button(
        "▶ Resume", use_container_width=True, disabled=dis, key="ctrl_resume"
    ) and post_control("resume"):
        st.rerun()
    st.sidebar.markdown("</div>", unsafe_allow_html=True)

    st.sidebar.markdown('<div class="section-label">Risk</div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="control-group">', unsafe_allow_html=True)
    if st.sidebar.button(
        "⛳ Flatten",
        type="primary",
        use_container_width=True,
        disabled=dis,
        key="ctrl_flatten",
    ) and post_control("flatten"):
        st.rerun()
    st.sidebar.markdown("</div>", unsafe_allow_html=True)

    st.sidebar.markdown('<div class="section-label">Mode</div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="control-group">', unsafe_allow_html=True)
    c3, c4 = st.sidebar.columns(2)
    if c3.button(
        "Paper", use_container_width=True, disabled=dis, key="ctrl_paper"
    ) and post_control("set_mode", {"mode": "paper"}):
        st.rerun()
    if c4.button("Live", use_container_width=True, disabled=dis, key="ctrl_live"):
        pass
    if st.sidebar.checkbox("☑ Confirm switch to Live", key="ctrl_confirm_live"):
        if post_control("set_mode", {"mode": "live"}):
            st.rerun()
    st.sidebar.markdown("</div>", unsafe_allow_html=True)

    st.sidebar.markdown(
        '<div class="section-label">Safety</div>', unsafe_allow_html=True
    )
    st.sidebar.markdown('<div class="control-group">', unsafe_allow_html=True)
    if st.sidebar.button(
        "☠ KILL", type="primary", use_container_width=True, disabled=ks, key="ctrl_kill"
    ) and post_control("kill", {"reason": "dashboard"}):
        st.rerun()
    if st.sidebar.button(
        "Reset KS", use_container_width=True, disabled=not ks, key="ctrl_reset_ks"
    ) and post_control("reset_kill", {"reason": "dashboard"}):
        st.rerun()
    st.sidebar.markdown("</div>", unsafe_allow_html=True)

    st.sidebar.markdown("---")
    st.sidebar.caption(f"API: {API_BASE}")


def render_execution_feed(events: list[dict]) -> None:
    st.markdown(
        '<div class="section-title">EXECUTION FEED</div>', unsafe_allow_html=True
    )
    if not events:
        st.caption("No execution events yet")
        return
    html = '<div class="exec-feed">'
    for e in events[:50]:
        ts = (e.get("created_at") or "")[11:19]
        sym = (e.get("symbol") or "?")[:12]
        side = e.get("side", "?")
        qty = e.get("quantity", 0)
        status = e.get("status", "?")
        price = e.get("price", 0.0)
        v = e.get("validation_passed")
        val_tag = (
            '<span class="val-ok">✓</span>'
            if v
            else ('<span class="val-rej">✗</span>' if v is not None else "")
        )
        status_cls = (
            ""
            if status in ("filled", "complete")
            else ("pnl-neg" if status in ("rejected", "failed") else "")
        )
        html += f'<div class="trade-row"><span>{ts} <b>{sym}</b> {side} x{qty} @ ₹{price:.1f}</span><span class="{status_cls}">{val_tag} {status}</span></div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_right_panel(a: dict[str, Any] | None) -> None:
    st.markdown('<div class="section-label">Rejections</div>', unsafe_allow_html=True)
    if a and a.get("rejection_stats"):
        for r in a["rejection_stats"][:5]:
            reason = r.get("rejection_reason", "?")[:50]
            count = r.get("count", 0)
            st.markdown(
                f'<div style="font-size:10px;color:var(--accent-yellow);padding:1px 0">✗ {reason} <span style="color:var(--text-muted)">x{count}</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("None")
    st.markdown('<div class="section-label">Broker</div>', unsafe_allow_html=True)
    st.caption("Kite: see top bar badge")


def render_trades_table(d: dict[str, Any]) -> None:
    orders = d.get("recent_orders", [])
    if not orders:
        return
    rows = [
        {
            "T": (o.get("created_at", "")[11:19]),
            "Sym": (o.get("symbol", "")[:10]),
            "S": o.get("side", "")[0],
            "Qty": o.get("quantity", 0),
            "Price": f"₹{o.get('price', 0.0):.1f}",
            "Status": o.get("status", ""),
            "Strategy": (o.get("strategy", "")[:8]),
        }
        for o in orders[:30]
    ]
    st.markdown('<div class="section-title">ORDERS</div>', unsafe_allow_html=True)
    st.dataframe(
        rows, use_container_width=True, hide_index=True, height=150, key="tbl_orders"
    )


def render_charts(d: dict[str, Any], a: dict[str, Any] | None) -> None:
    eq = d.get("equity_curve", [])
    if eq and len(eq) > 1:
        cum = 0.0
        pts = []
        for pt in eq:
            cum += pt.get("daily_pnl", 0.0) or 0.0
            try:
                ts = datetime.fromisoformat(
                    pt.get("timestamp", "").replace("Z", "+00:00")
                )
            except Exception:
                ts = None
            pts.append({"t": ts or "", "e": cum})
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=[p["t"] for p in pts],
                y=[p["e"] for p in pts],
                mode="lines",
                line={"color": "#22c55e", "width": 1.5},
                fill="tozeroy",
                fillcolor="rgba(34,197,94,0.05)",
            )
        )
        fig.update_layout(
            template="plotly_dark",
            margin={"l": 0, "r": 0, "t": 4, "b": 0},
            height=110,
            paper_bgcolor="#0d1320",
            plot_bgcolor="#0d1320",
            showlegend=False,
            xaxis={"visible": False, "showgrid": False},
            yaxis={"visible": False, "showgrid": False, "fixedrange": True},
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
            key="chart_equity",
        )
    else:
        st.caption("Insufficient data for equity curve")

    if a and a.get("daily_pnl_history") and len(a["daily_pnl_history"]) > 1:
        dph = list(reversed(a["daily_pnl_history"]))
        fig2 = go.Figure()
        colors = ["#22c55e" if p["daily_pnl"] >= 0 else "#ef4444" for p in dph]
        fig2.add_trace(
            go.Bar(
                x=[p["date"][-5:] for p in dph],
                y=[p["daily_pnl"] for p in dph],
                marker_color=colors,
                marker_line_width=0,
            )
        )
        fig2.update_layout(
            template="plotly_dark",
            margin={"l": 0, "r": 0, "t": 4, "b": 0},
            height=90,
            paper_bgcolor="#0d1320",
            plot_bgcolor="#0d1320",
            showlegend=False,
            xaxis={"visible": False, "showgrid": False},
            yaxis={"visible": False, "showgrid": False, "fixedrange": True},
            bargap=0.2,
        )
        st.plotly_chart(
            fig2,
            use_container_width=True,
            config={"displayModeBar": False},
            key="chart_daily_pnl",
        )
    else:
        st.caption("Insufficient data for daily PnL")


def render_notifications(d: dict[str, Any]) -> None:
    notifs = d.get("recent_notifications", [])
    if not notifs:
        return
    rows = [
        {
            "T": n.get("created_at", "")[11:19],
            "Evt": n.get("event_type", ""),
            "Msg": (n.get("message", "")[:60]),
        }
        for n in notifs[:15]
    ]
    st.markdown(
        '<div class="section-title">NOTIFICATIONS</div>', unsafe_allow_html=True
    )
    st.dataframe(
        rows, use_container_width=True, hide_index=True, key="tbl_notifications"
    )


# ── Main ─────────────────────────────────────────────────────────────────


def main() -> None:
    if not check_password():
        return

    render_controls()

    ar = st.sidebar.checkbox("Auto-refresh 30s", value=True, key="chk_autorefresh")
    if "lr" not in st.session_state:
        st.session_state.lr = time.time()
    if ar:
        el = time.time() - st.session_state.lr
        st.sidebar.caption(f"Next refresh in {max(0, 30 - int(el))}s")
        if el >= 30:
            st.session_state.lr = time.time()
            st.rerun()
    if st.sidebar.button("↻ Refresh", use_container_width=True, key="btn_refresh"):
        st.session_state.lr = time.time()
        st.rerun()

    d = fetch("/dashboard/data")
    a = fetch("/dashboard/analytics")
    if d is None:
        st.error(f"Cannot connect to {API_BASE}")
        return

    ks = d.get("kill_switch", {})
    st.session_state.ks = ks.get("active", False)
    if ks.get("active"):
        st.markdown(
            f'<div style="background:#450a0a;border:1px solid #ef4444;color:#ef4444;padding:6px 12px;border-radius:3px;font-size:12px;margin-bottom:8px">⚠ KILL SWITCH ACTIVE — {ks.get("triggered_by", "?")}: {ks.get("reason", "?")}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:#052e16;border:1px solid #22c55e;color:#22c55e;padding:6px 12px;border-radius:3px;font-size:11px;margin-bottom:8px">● Kill switch: inactive</div>',
            unsafe_allow_html=True,
        )

    render_topbar(d)

    col_l, col_c, col_r = st.columns([1.2, 3, 1.2], gap="small")
    with col_l:
        st.markdown('<div class="section-label">Position</div>', unsafe_allow_html=True)
        pos = d.get("current_position", {})
        if pos.get("side") and pos["side"] != "NONE":
            sc = "pnl-pos" if pos["side"] == "LONG" else "pnl-neg"
            st.markdown(
                f'<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:3px;padding:8px"><span class="{sc}" style="font-weight:700">{pos["side"]}</span> {pos.get("symbol", "?")} x{pos.get("quantity", 0)}<br><span style="color:var(--text-secondary);font-size:10px">entry @ ₹{pos.get("entry_price", 0):.2f}</span></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:3px;padding:8px;color:var(--text-muted);font-size:11px">No open position</div>',
                unsafe_allow_html=True,
            )
        st.markdown('<div class="section-label">P&L</div>', unsafe_allow_html=True)
        dpnl = d.get("daily_pnl", 0.0)
        cpnl = d.get("cumulative_pnl", 0.0)
        st.markdown(
            f'<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:3px;padding:8px;font-size:12px"><span style="color:var(--text-secondary)">Daily</span> {fmt_pnl(dpnl)}<br><span style="color:var(--text-secondary)">Cum</span> {fmt_pnl(cpnl)}<br><span style="color:var(--text-secondary);font-size:10px">W/L {d.get("wins_today", 0)}/{d.get("losses_today", 0)} · DD ₹{d.get("max_drawdown_today", 0):,.0f}</span></div>',
            unsafe_allow_html=True,
        )

    with col_c:
        events = a.get("execution_events", []) if a else []
        render_execution_feed(events)

    with col_r:
        render_right_panel(a)

    render_charts(d, a)

    tabs = st.tabs(["Orders", "Notifications", "Errors"])
    with tabs[0]:
        render_trades_table(d)
    with tabs[1]:
        render_notifications(d)
    with tabs[2]:
        errs = d.get("recent_errors", [])
        if errs:
            for e in errs[:10]:
                st.caption(f"• {e}")
        else:
            st.caption("No errors")


if __name__ == "__main__":
    main()
