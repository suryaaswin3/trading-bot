"""IST market hours utility — timezone-aware NSE trading calendar.

Provides phase detection (pre-market / trading / post-market / weekend / holiday),
market-open timers for scheduler autonomy, and a static NSE holiday calendar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, time as dtime
from typing import ClassVar

import pytz

_IST = pytz.timezone("Asia/Kolkata")

# Static NSE holiday calendar (2026 — update annually)
_NSE_HOLIDAYS: frozenset[str] = frozenset({
    "2026-01-26",  # Republic Day
    "2026-03-25",  # Holi
    "2026-04-02",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-04-18",  # Ram Navami
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-08-27",  # Ganesh Chaturthi
    "2026-10-02",  # Gandhi Jayanti
    "2026-11-03",  # Diwali
    "2026-11-05",  # Diwali Balipratipada
    "2026-11-12",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
})


# ── Public API ─────────────────────────────────────────────────────────────


def is_market_open(dt: datetime | None = None) -> bool:
    """True if *dt* (default: now) falls within NSE trading hours on a
    trading day: Mon–Fri, 9:15–15:30 IST, not a holiday."""
    return session_phase(dt) == "TRADING"


def is_pre_market(dt: datetime | None = None) -> bool:
    """True during pre-market window 9:00–9:15 IST."""
    return session_phase(dt) == "PRE_MARKET"


def is_post_market(dt: datetime | None = None) -> bool:
    """True after market close (15:30–23:59 IST) on a trading day."""
    return session_phase(dt) == "POST_MARKET"


def session_phase(dt: datetime | None = None) -> str:
    """Classify *dt* into one of the trading session phases.

    Returns
        "PRE_MARKET"  — weekday 9:00–9:14:59 IST
        "TRADING"     — weekday 9:15–15:29:59 IST
        "POST_MARKET" — weekday 15:30–23:59:59 IST
        "WEEKEND"     — Saturday or Sunday
        "HOLIDAY"     — NSE holiday
        "CLOSED"      — before 9:00 on a trading day
    """
    if dt is None:
        dt = datetime.now(_IST)
    elif dt.tzinfo is None:
        dt = _IST.localize(dt)

    if dt.weekday() >= 5:
        return "WEEKEND"
    if dt.strftime("%Y-%m-%d") in _NSE_HOLIDAYS:
        return "HOLIDAY"

    t = dt.time()
    _OPEN = dtime(9, 15)
    _CLOSE = dtime(15, 30)
    _PRE_START = dtime(9, 0)

    if t < _PRE_START:
        return "CLOSED"
    if t < _OPEN:
        return "PRE_MARKET"
    if t < _CLOSE:
        return "TRADING"
    return "POST_MARKET"


def next_market_open(dt: datetime | None = None) -> datetime:
    """Earliest future datetime that falls within TRADING phase."""
    if dt is None:
        dt = datetime.now(_IST)
    elif dt.tzinfo is None:
        dt = _IST.localize(dt)

    candidate = dt.replace(hour=9, minute=15, second=0, microsecond=0)
    if candidate <= dt:
        candidate += timedelta(days=1)

    for _ in range(14):  # at most 2 weeks forward
        if candidate.weekday() < 5 and candidate.strftime("%Y-%m-%d") not in _NSE_HOLIDAYS:
            return candidate
        candidate += timedelta(days=1)

    return candidate  # fallback (should not reach here)


def next_market_close(dt: datetime | None = None) -> datetime:
    """Today's market close (15:30 IST). If after close, returns next open day."""
    if dt is None:
        dt = datetime.now(_IST)
    elif dt.tzinfo is None:
        dt = _IST.localize(dt)

    close = dt.replace(hour=15, minute=30, second=0, microsecond=0)
    if dt >= close:
        return next_market_open(dt)
    return close


def seconds_until_market_open(dt: datetime | None = None) -> int:
    """Seconds from *dt* (default: now) until the next TRADING phase."""
    if dt is None:
        dt = datetime.now(_IST)
    elif dt.tzinfo is None:
        dt = _IST.localize(dt)
    nxt = next_market_open(dt)
    return max(0, int((nxt - dt).total_seconds()))


def seconds_until_market_close(dt: datetime | None = None) -> int:
    """Seconds until today's market close (0 if already closed)."""
    if dt is None:
        dt = datetime.now(_IST)
    elif dt.tzinfo is None:
        dt = _IST.localize(dt)
    close = next_market_close(dt)
    return max(0, int((close - dt).total_seconds()))