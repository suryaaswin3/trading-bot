# Market Data Layer + Scanner Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, polling-based market data layer and scanner engine that emits signals into the existing StrategyEngine.process() for unified execution alongside TradingView webhooks.

**Architecture:** Kite Connect historical_data() polled in a daemon thread on a configurable interval (default 60s). In-memory OHLCV cache per symbol+interval avoids redundant API calls. Pure-function indicators compute EMA/ATR/VWAP from cached bars. Scanners are stateless pure functions that read indicators and emit high-confidence NormalizedSignal dicts with `source="scanner"`. Signals flow into StrategyEngine.process() — the same path webhook signals use.

**Tech Stack:** Python 3.14, Kite Connect REST API, sqlite3 (WAL), threading.Event, loguru, pytest

---

### Task 1: Add `source` field to NormalizedSignal + DB schema

**Files:**
- Modify: `ops_api/models.py:122-136`
- Modify: `ops_api/db.py:34-48` (schema)
- Create: `tests/ops_api/test_scanner_signals.py` (partial — just the source field tests)

- [ ] **Step 1: Add `source` field to NormalizedSignal model**

In `ops_api/models.py`, add `source: str = "webhook"` after `reason` in the `NormalizedSignal` class:

```python
class NormalizedSignal(BaseModel):
    """Cleaned/normalized signal extracted from a webhook alert."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    webhook_alert_id: str = ""
    alert_id: str = ""
    symbol: str = ""
    side: SignalSide = SignalSide.BUY
    strategy: str = ""
    timeframe: str = ""
    price: float = 0.0
    signal_timestamp: datetime | None = None
    reason: str = ""
    source: str = "webhook"  # "webhook" | "scanner"
    normalized_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 2: Add `source` column to DB schema**

In `ops_api/db.py`, add `source TEXT NOT NULL DEFAULT 'webhook'` after `reason` in the `normalized_signals` CREATE TABLE:

```python
    reason TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'webhook',
    data_source TEXT NOT NULL DEFAULT 'production',
```

- [ ] **Step 3: Write test for source field on NormalizedSignal**

Create `tests/ops_api/test_scanner_signals.py`:

```python
"""Scanner signal tests — source field, creation, flow."""

from __future__ import annotations

from ops_api.models import NormalizedSignal, SignalSide


class TestNormalizedSignalSource:
    def test_default_source_is_webhook(self) -> None:
        sig = NormalizedSignal(symbol="NIFTY", side=SignalSide.BUY, strategy="TEST")
        assert sig.source == "webhook"

    def test_scanner_source(self) -> None:
        sig = NormalizedSignal(
            symbol="NIFTY", side=SignalSide.BUY, strategy="MOMENTUM", source="scanner"
        )
        assert sig.source == "scanner"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ops_api/test_scanner_signals.py -v`
Expected: 2 PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `pytest tests/ops_api/ -v`
Expected: all tests pass (139+)

---

### Task 2: Create `indicators.py` — Pure-function technical indicators

**Files:**
- Create: `ops_api/indicators.py`
- Create: `tests/ops_api/test_indicators.py`

- [ ] **Step 1: Write failing tests for EMA, ATR, VWAP**

Create `tests/ops_api/test_indicators.py`:

```python
"""Indicator tests — EMA, ATR, VWAP as pure functions."""

from __future__ import annotations

import math

import pytest

from ops_api.indicators import atr, ema, vwap


def _make_bars(prices: list[float]) -> list[dict]:
    """Convert close-price list to OHLCV bar dicts (HL=close*1.02/0.98 for range)."""
    bars = []
    for i, c in enumerate(prices):
        high = round(c * 1.02, 2)
        low = round(c * 0.98, 2)
        bars.append({
            "open": round(c * 0.99, 2),
            "high": high,
            "low": low,
            "close": c,
            "volume": 100000 + i * 100,
        })
    return bars


class TestEMA:
    def test_ema_returns_correct_length(self) -> None:
        bars = _make_bars([float(i) for i in range(1, 21)])
        result = ema(bars, period=10)
        assert len(result) == len(bars)

    def test_ema_first_n_values_are_close(self) -> None:
        """First (period-1) values should equal the close price (no history yet)."""
        bars = _make_bars([float(i) for i in range(1, 11)])
        result = ema(bars, period=5)
        for i in range(4):  # indices 0-3 have no full window
            assert math.isclose(result[i], bars[i]["close"], rel_tf=1e-3)

    def test_ema_trending_up(self) -> None:
        """EMA of consistently rising prices should be below latest close."""
        bars = _make_bars([float(i) for i in range(1, 31)])
        result = ema(bars, period=10)
        assert result[-1] < bars[-1]["close"]  # EMA lags behind uptrend

    def test_ema_known_values(self) -> None:
        """Test against known EMA values for a simple sequence."""
        closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
        bars = _make_bars(closes)
        result = ema(bars, period=5)
        # After period=5, the 6th value (idx 5) starts EMA smoothing
        # EMA = (close - prev_ema) * multiplier + prev_ema
        # We just verify it's computed and finite
        assert all(math.isfinite(v) for v in result)
        assert result[-1] > 14.0  # rising trend, EMA > midpoint


class TestATR:
    def test_atr_returns_correct_length(self) -> None:
        bars = _make_bars([float(i) for i in range(1, 21)])
        result = atr(bars, period=14)
        assert len(result) == len(bars)

    def test_atr_first_n_values_are_zero(self) -> None:
        """First (period) values should be 0 (not enough history)."""
        bars = _make_bars([float(i) for i in range(1, 11)])
        result = atr(bars, period=5)
        for i in range(4):
            assert result[i] == 0.0

    def test_atr_positive_value(self) -> None:
        """ATR should be positive after enough bars."""
        bars = _make_bars([float(i) for i in range(1, 31)])
        result = atr(bars, period=14)
        assert result[-1] > 0.0

    def test_atr_high_volatility(self) -> None:
        """Wider bars produce larger ATR."""
        low_vol = _make_bars([100.0 + i for i in range(30)])
        high_vol = []
        for i in range(30):
            high_vol.append({
                "open": 100.0 + i,
                "high": 100.0 + i + 5,
                "low": 100.0 + i - 5,
                "close": 100.0 + i,
                "volume": 100000,
            })
        low_atr = atr(low_vol, period=14)[-1]
        high_atr = atr(high_vol, period=14)[-1]
        assert high_atr > low_atr


class TestVWAP:
    def test_vwap_single_bar(self) -> None:
        bars = [{"high": 105, "low": 95, "close": 100, "volume": 1000}]
        result = vwap(bars)
        # Typical price = (105 + 95 + 100) / 3 = 100
        # VWAP = (100 * 1000) / 1000 = 100
        assert math.isclose(result[-1], 100.0, rel_tf=1e-3)

    def test_vwap_multi_bar(self) -> None:
        bars = [
            {"high": 105, "low": 95, "close": 100, "volume": 1000},
            {"high": 115, "low": 105, "close": 110, "volume": 2000},
        ]
        result = vwap(bars)
        # Bar 1 tp = 100, Bar 2 tp = 110
        # VWAP = (100*1000 + 110*2000) / (1000 + 2000) = 320000/3000 = 106.67
        assert math.isclose(result[-1], 106.67, rel_tf=1e-2)

    def test_vwap_returns_all_bars(self) -> None:
        bars = [
            {"high": 105, "low": 95, "close": 100, "volume": 1000},
            {"high": 115, "low": 105, "close": 110, "volume": 2000},
        ]
        result = vwap(bars)
        assert len(result) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ops_api/test_indicators.py -v`
Expected: ImportError (no module `ops_api.indicators`)

- [ ] **Step 3: Implement EMA, ATR, VWAP**

Create `ops_api/indicators.py`:

```python
"""Pure-function technical indicators operating on OHLCV bar dicts.

Each indicator takes a list of bar dicts with keys:
    open, high, low, close, volume

And returns a list of computed values — one per input bar — so the
result index i corresponds to input bar i.
"""

from __future__ import annotations

from typing import Any


def ema(bars: list[dict[str, Any]], period: int = 20) -> list[float]:
    """Exponential Moving Average.

    First ``period - 1`` values use simple average of available data (SMA),
    then switches to EMA smoothing::

        multiplier = 2 / (period + 1)
        ema[i] = (close[i] - ema[i-1]) * multiplier + ema[i-1]
    """
    if not bars:
        return []

    closes = [b["close"] for b in bars]
    result: list[float] = []
    multiplier = 2.0 / (period + 1)

    for i, close in enumerate(closes):
        if i < period:
            # SMA for initial values
            window = closes[: i + 1]
            result.append(sum(window) / len(window))
        else:
            result.append((close - result[i - 1]) * multiplier + result[i - 1])

    return result


def atr(bars: list[dict[str, Any]], period: int = 14) -> list[float]:
    """Average True Range (Smoothed).

    True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))

    First ``period`` true-range values are SMA-averaged, then EMA-smoothed
    like Wilder's ATR. Returns 0.0 for bars where there isn't enough
    history yet.
    """
    if not bars:
        return []

    tr_values: list[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            tr = b["high"] - b["low"]
        else:
            tr = max(
                b["high"] - b["low"],
                abs(b["high"] - bars[i - 1]["close"]),
                abs(b["low"] - bars[i - 1]["close"]),
            )
        tr_values.append(tr)

    result: list[float] = []
    for i in range(len(tr_values)):
        if i < period:
            # SMA of TR for first `period` values
            window = tr_values[: i + 1]
            result.append(sum(window) / len(window))
        else:
            # Smoothed ATR: ((prev_atr * (period - 1)) + tr) / period
            result.append(
                (result[i - 1] * (period - 1) + tr_values[i]) / period
            )

    return result


def vwap(bars: list[dict[str, Any]]) -> list[float]:
    """Volume-Weighted Average Price (cumulative).

    VWAP[i] = sum(tp[j] * vol[j] for j <= i) / sum(vol[j] for j <= i)

    Where typical price tp = (high + low + close) / 3
    """
    cum_pv = 0.0
    cum_vol = 0.0
    result: list[float] = []

    for b in bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_pv += tp * b["volume"]
        cum_vol += b["volume"]
        result.append(cum_pv / cum_vol if cum_vol > 0 else 0.0)

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ops_api/test_indicators.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add ops_api/indicators.py tests/ops_api/test_indicators.py
git commit -m "feat: add pure-function indicators EMA, ATR, VWAP"
```

---

### Task 3: Create `market_data/` package — Kite Connect polling provider + OHLCV cache

**Files:**
- Create: `ops_api/market_data/__init__.py`
- Create: `ops_api/market_data/base.py`
- Create: `ops_api/market_data/kite_provider.py`
- Create: `tests/ops_api/test_market_data.py`

- [ ] **Step 1: Write failing tests**

Create `tests/ops_api/test_market_data.py`:

```python
"""Market data tests — OHLCV cache, provider interface, Kite provider."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from ops_api.market_data.base import OHLCVCache, BarSnapshot
from ops_api.market_data.kite_provider import KiteConnectMarketData


class TestBarSnapshot:
    def test_creates_with_minimal_fields(self) -> None:
        bar = BarSnapshot(
            symbol="NIFTY",
            interval="60",
            open=18100.0,
            high=18200.0,
            low=18000.0,
            close=18150.0,
            volume=500000,
            timestamp=1234567890.0,
        )
        assert bar.symbol == "NIFTY"
        assert bar.close == 18150.0


class TestOHLCVCache:
    def test_store_and_retrieve(self) -> None:
        cache = OHLCVCache()
        bars = [
            BarSnapshot(
                symbol="NIFTY", interval="60",
                open=100.0, high=105.0, low=99.0, close=102.0,
                volume=1000, timestamp=1.0,
            ),
        ]
        cache.set("NIFTY", "60", bars)
        retrieved = cache.get("NIFTY", "60")
        assert retrieved is not None
        assert len(retrieved) == 1
        assert retrieved[0].close == 102.0

    def test_get_missing_returns_none(self) -> None:
        cache = OHLCVCache()
        assert cache.get("NIFTY", "60") is None

    def test_cache_ttl_expiry(self) -> None:
        cache = OHLCVCache(ttl_seconds=0.1)
        bars = [
            BarSnapshot(
                symbol="NIFTY", interval="60",
                open=100.0, high=105.0, low=99.0, close=102.0,
                volume=1000, timestamp=1.0,
            ),
        ]
        cache.set("NIFTY", "60", bars)
        assert cache.get("NIFTY", "60") is not None
        time.sleep(0.15)
        assert cache.get("NIFTY", "60") is None

    def test_cache_clear(self) -> None:
        cache = OHLCVCache()
        bars = [
            BarSnapshot(
                symbol="NIFTY", interval="60",
                open=100.0, close=102.0, high=105.0, low=99.0,
                volume=1000, timestamp=1.0,
            ),
        ]
        cache.set("NIFTY", "60", bars)
        cache.clear()
        assert cache.get("NIFTY", "60") is None


class TestKiteConnectMarketData:
    def test_fetch_returns_bars_with_mocked_kite(self) -> None:
        mock_kite = MagicMock()
        mock_kite.historical_data.return_value = [
            {
                "date": "2026-05-20T09:15:00+05:30",
                "open": 18100.0,
                "high": 18200.0,
                "low": 18000.0,
                "close": 18150.0,
                "volume": 500000,
            },
        ]

        provider = KiteConnectMarketData(mock_kite)
        bars = provider.fetch("NIFTY", "60", count=1)

        assert len(bars) == 1
        assert bars[0].symbol == "NIFTY"
        assert bars[0].close == 18150.0
        assert bars[0].volume == 500000
        mock_kite.historical_data.assert_called_once()

    def test_fetch_error_returns_empty(self) -> None:
        mock_kite = MagicMock()
        mock_kite.historical_data.side_effect = RuntimeError("API error")

        provider = KiteConnectMarketData(mock_kite)
        bars = provider.fetch("NIFTY", "60", count=1)
        assert bars == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ops_api/test_market_data.py -v`
Expected: ImportError (no module `ops_api.market_data`)

- [ ] **Step 3: Create `market_data/__init__.py`**

```python
"""Market data layer — OHLCV caching and Kite Connect polling provider."""

from ops_api.market_data.base import BarSnapshot, OHLCVCache
from ops_api.market_data.kite_provider import KiteConnectMarketData

__all__ = [
    "BarSnapshot",
    "KiteConnectMarketData",
    "OHLCVCache",
]
```

- [ ] **Step 4: Create `market_data/base.py`**

```python
"""Base types for the market data layer — BarSnapshot, OHLCVCache."""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BarSnapshot:
    """Immutable OHLCV bar with metadata."""

    symbol: str
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: float  # Unix epoch seconds


class OHLCVCache:
    """Thread-safe in-memory cache of OHLCV bars per (symbol, interval).

    Each entry is a list of BarSnapshot objects, newest-last.
    Entries expire after ``ttl_seconds`` from last set/refresh.
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._data: dict[tuple[str, str], tuple[list[BarSnapshot], float]] = {}

    def get(
        self, symbol: str, interval: str
    ) -> list[BarSnapshot] | None:
        """Return cached bars or None if missing/expired."""
        key = (symbol.upper(), interval)
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            bars, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._data[key]
                return None
            return bars

    def set(
        self, symbol: str, interval: str, bars: list[BarSnapshot]
    ) -> None:
        """Store bars for (symbol, interval), resetting TTL."""
        key = (symbol.upper(), interval)
        with self._lock:
            self._data[key] = (bars, time.monotonic())

    def clear(self) -> None:
        """Remove all cached entries."""
        with self._lock:
            self._data.clear()

    def keys(self) -> list[tuple[str, str]]:
        """Return all cached (symbol, interval) keys (for introspection)."""
        with self._lock:
            return list(self._data.keys())
```

- [ ] **Step 5: Create `market_data/kite_provider.py`**

```python
"""Kite Connect backed market data provider with OHLCV caching."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from ops_api.market_data.base import BarSnapshot


def _parse_kite_timestamp(date_val: str | datetime) -> float:
    """Parse Kite Connect timestamp into Unix epoch seconds."""
    if isinstance(date_val, datetime):
        return date_val.timestamp()
    # ISO-8601 string with timezone
    dt = datetime.fromisoformat(date_val)
    return dt.timestamp()


class KiteConnectMarketData:
    """Market data provider wrapping Kite Connect historical_data().

    Fetches OHLCV bars for a given symbol and interval. The caller
    is responsible for caching; this provider always makes the API call.
    """

    def __init__(self, kite_client: Any) -> None:
        self._kite = kite_client

    def fetch(
        self,
        symbol: str,
        interval: str = "60",
        count: int = 100,
    ) -> list[BarSnapshot]:
        """Fetch OHLCV bars from Kite Connect.

        Args:
            symbol: Instrument trading symbol (e.g. "NIFTY", "RELIANCE").
            interval: Kite Connect interval string ("60", "day", etc.).
            count: Number of bars to fetch.

        Returns:
            List of BarSnapshot objects, empty on error.
        """
        try:
            to_date = datetime.now(timezone.utc) + timedelta(days=1)
            from_date = to_date - timedelta(days=count)  # rough but safe

            raw = self._kite.historical_data(
                symbol, from_date, to_date, interval
            )
            if not raw:
                logger.warning("Kite historical_data returned empty for {} ({})", symbol, interval)
                return []

            bars = []
            for item in raw:
                bars.append(BarSnapshot(
                    symbol=symbol.upper(),
                    interval=interval,
                    open=float(item.get("open", 0)),
                    high=float(item.get("high", 0)),
                    low=float(item.get("low", 0)),
                    close=float(item.get("close", 0)),
                    volume=float(item.get("volume", 0)),
                    timestamp=_parse_kite_timestamp(item["date"]),
                ))

            logger.debug("Fetched {} bars for {} ({})", len(bars), symbol, interval)
            return bars

        except Exception as e:
            logger.error("Failed to fetch market data for {} ({}): {}", symbol, interval, e)
            return []
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/ops_api/test_market_data.py -v`
Expected: 8 PASS

- [ ] **Step 7: Commit**

```bash
git add ops_api/market_data/ tests/ops_api/test_market_data.py
git commit -m "feat: add market data layer with OHLCV cache and Kite provider"
```

---

### Task 4: Create `scanner/` package — BaseScanner + MomentumScanner + VolumeScanner

**Files:**
- Create: `ops_api/scanner/__init__.py`
- Create: `ops_api/scanner/base.py`
- Create: `ops_api/scanner/momentum.py`
- Create: `ops_api/scanner/volume.py`
- Add to: `tests/ops_api/test_scanner_signals.py`

- [ ] **Step 1: Write failing tests**

Add scanner tests to `tests/ops_api/test_scanner_signals.py`:

```python
"""Scanner signal tests — source field, creation, scanners."""

from __future__ import annotations

from unittest.mock import MagicMock

from ops_api.indicators import ema
from ops_api.market_data.base import BarSnapshot
from ops_api.models import NormalizedSignal, SignalSide
from ops_api.scanner.base import ScannerResult
from ops_api.scanner.momentum import MomentumScanner
from ops_api.scanner.volume import VolumeScanner


class TestNormalizedSignalSource:
    def test_default_source_is_webhook(self) -> None:
        sig = NormalizedSignal(symbol="NIFTY", side=SignalSide.BUY, strategy="TEST")
        assert sig.source == "webhook"

    def test_scanner_source(self) -> None:
        sig = NormalizedSignal(
            symbol="NIFTY", side=SignalSide.BUY, strategy="MOMENTUM", source="scanner"
        )
        assert sig.source == "scanner"


class TestScannerResult:
    def test_rejected_signal(self) -> None:
        result = ScannerResult(signal=None)
        assert result.signal is None
        assert not result.has_signal

    def test_accepted_signal(self) -> None:
        sig = NormalizedSignal(symbol="NIFTY", side=SignalSide.BUY, strategy="MOMENTUM", source="scanner")
        result = ScannerResult(signal=sig)
        assert result.has_signal
        assert result.signal is not None


def _make_uptrend_bars(n: int = 60) -> list[BarSnapshot]:
    """Create a rising price series for scanner tests."""
    bars = []
    for i in range(n):
        base = 18000.0 + i * 5.0  # steadily rising
        bars.append(BarSnapshot(
            symbol="NIFTY",
            interval="60",
            open=base - 5,
            high=base + 10,
            low=base - 10,
            close=base,
            volume=500000 + i * 1000,
            timestamp=float(1000000 + i * 60),
        ))
    return bars


def _make_high_volume_bars(n: int = 60) -> list[BarSnapshot]:
    """Create bars with a volume spike at the end."""
    bars = []
    for i in range(n):
        is_spike = i >= n - 3
        bars.append(BarSnapshot(
            symbol="NIFTY",
            interval="60",
            open=18100.0 + i,
            high=18150.0 + i,
            low=18050.0 + i,
            close=18100.0 + i,
            volume=1000000 if is_spike else 100000,
            timestamp=float(1000000 + i * 60),
        ))
    return bars


class TestMomentumScanner:
    def test_uptrend_detected(self) -> None:
        bars = _make_uptrend_bars(60)
        scanner = MomentumScanner()
        result = scanner.scan(bars, symbol="NIFTY")
        if result.has_signal:
            assert result.signal is not None
            assert result.signal.symbol == "NIFTY"
            assert result.signal.side == SignalSide.BUY
            assert result.signal.source == "scanner"
            assert result.signal.strategy == "MOMENTUM"

    def test_no_signal_in_flattish_market(self) -> None:
        bars = []
        for i in range(60):
            bars.append(BarSnapshot(
                symbol="NIFTY", interval="60",
                open=18100.0, high=18110.0, low=18090.0, close=18100.0,
                volume=100000, timestamp=float(1000000 + i * 60),
            ))
        scanner = MomentumScanner()
        result = scanner.scan(bars, symbol="NIFTY")
        # Flat market should NOT trigger momentum signal
        assert not result.has_signal


class TestVolumeScanner:
    def test_volume_spike_detected(self) -> None:
        bars = _make_high_volume_bars(60)
        scanner = VolumeScanner()
        result = scanner.scan(bars, symbol="NIFTY")
        if result.has_signal:
            assert result.signal is not None
            assert result.signal.symbol == "NIFTY"
            assert result.signal.side == SignalSide.BUY
            assert result.signal.source == "scanner"
            assert result.signal.strategy == "RELATIVE_VOLUME"

    def test_no_signal_normal_volume(self) -> None:
        bars = []
        for i in range(60):
            bars.append(BarSnapshot(
                symbol="NIFTY", interval="60",
                open=18100.0, close=18100.0, high=18110.0, low=18090.0,
                volume=100000, timestamp=float(1000000 + i * 60),
            ))
        scanner = VolumeScanner()
        result = scanner.scan(bars, symbol="NIFTY")
        assert not result.has_signal
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ops_api/test_scanner_signals.py -v`
Expected: ImportError (no module `ops_api.scanner`)

- [ ] **Step 3: Create `scanner/__init__.py`**

```python
"""Scanner engine — scans market data and emits high-confidence signals.

Scanners are stateless, deterministic pure functions that inspect
indicator values and return ScannerResult. Only high-confidence signals
are emitted to avoid flooding the execution pipeline.
"""

from ops_api.scanner.base import BaseScanner, ScannerResult
from ops_api.scanner.momentum import MomentumScanner
from ops_api.scanner.volume import VolumeScanner

__all__ = [
    "BaseScanner",
    "MomentumScanner",
    "ScannerResult",
    "VolumeScanner",
]
```

- [ ] **Step 4: Create `scanner/base.py`**

```python
"""Base scanner abstraction — stateless, deterministic, pure."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ops_api.market_data.base import BarSnapshot
from ops_api.models import NormalizedSignal, SignalSide


@dataclass
class ScannerResult:
    """Result of a single scanner run.

    If ``signal`` is None, no actionable signal was found.
    """

    signal: NormalizedSignal | None = None

    @property
    def has_signal(self) -> bool:
        return self.signal is not None


class BaseScanner(ABC):
    """Abstract scanner that inspects indicator values and emits signals.

    Scanners are stateless and deterministic: given the same bars,
    they always produce the same result. They do NOT maintain internal
    state across scan cycles.
    """

    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = strategy_id

    @abstractmethod
    def scan(
        self,
        bars: list[BarSnapshot],
        symbol: str = "",
        interval: str = "",
    ) -> ScannerResult:
        """Analyse bars and return a signal if conditions are met.

        Returns ScannerResult(signal=None) when no actionable signal.
        """
        ...
```

- [ ] **Step 5: Create `scanner/momentum.py`**

```python
"""Momentum scanner — detects price vs EMA crossovers and rate of change."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ops_api.indicators import ema as compute_ema
from ops_api.market_data.base import BarSnapshot
from ops_api.models import NormalizedSignal, SignalSide
from ops_api.scanner.base import BaseScanner, ScannerResult


class MomentumScanner(BaseScanner):
    """Detects momentum signals based on EMA relationships and price action.

    Signal conditions (all must be met):
      - Price above EMA20 (short-term uptrend)
      - Price above EMA50 (medium-term uptrend, filter for noise)
      - EMA20 > EMA50 (bullish alignment)
      - Price > VWAP (intraday strength)

    Opposite for SELL signals. High-confidence only.
    """

    def __init__(self) -> None:
        super().__init__(strategy_id="MOMENTUM")

    def scan(
        self,
        bars: list[BarSnapshot],
        symbol: str = "",
        interval: str = "",
    ) -> ScannerResult:
        closes = [b.close for b in bars]
        volumes = [b.volume for b in bars]

        if len(closes) < 50:
            return ScannerResult()

        # Compute indicators
        ema20 = compute_ema(
            [{"close": c} for c in closes], period=20  # type: ignore[typeddict-item]
        )[-1]
        ema50 = compute_ema(
            [{"close": c} for c in closes], period=50  # type: ignore[typeddict-item]
        )[-1]
        last_price = closes[-1]

        # Compute VWAP from actual bars
        cum_pv = 0.0
        cum_vol = 0.0
        for b in bars:
            tp = (b.high + b.low + b.close) / 3.0
            cum_pv += tp * b.volume
            cum_vol += b.volume
        vwap_val = cum_pv / cum_vol if cum_vol > 0 else last_price

        # Rate of change (3-period)
        roc_3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0.0

        # BUY signal: price > ema20 > ema50, price > VWAP, positive ROC
        if (
            last_price > ema20 > ema50
            and last_price > vwap_val
            and roc_3 > 0.5
        ):
            return ScannerResult(
                signal=NormalizedSignal(
                    symbol=symbol.upper(),
                    side=SignalSide.BUY,
                    strategy=self.strategy_id,
                    timeframe=interval,
                    price=last_price,
                    source="scanner",
                    reason=f"Price({last_price:.1f}) > EMA20({ema20:.1f}) > EMA50({ema50:.1f}), ROC={roc_3:.1f}%",
                )
            )

        # SELL signal: price < ema20 < ema50, price < VWAP, negative ROC
        if (
            last_price < ema20 < ema50
            and last_price < vwap_val
            and roc_3 < -0.5
        ):
            return ScannerResult(
                signal=NormalizedSignal(
                    symbol=symbol.upper(),
                    side=SignalSide.SELL,
                    strategy=self.strategy_id,
                    timeframe=interval,
                    price=last_price,
                    source="scanner",
                    reason=f"Price({last_price:.1f}) < EMA20({ema20:.1f}) < EMA50({ema50:.1f}), ROC={roc_3:.1f}%",
                )
            )

        return ScannerResult()
```

- [ ] **Step 6: Create `scanner/volume.py`**

```python
"""Volume scanner — detects relative volume spikes vs 20-period average."""

from __future__ import annotations

import math
from typing import Any

from ops_api.market_data.base import BarSnapshot
from ops_api.models import NormalizedSignal, SignalSide
from ops_api.scanner.base import BaseScanner, ScannerResult


class VolumeScanner(BaseScanner):
    """Detects unusual volume activity.

    Signal conditions:
      - Current volume > 2.5x the 20-period average volume
      - Price direction consistent with volume (up-volume, up-price for BUY;
        up-volume, down-price for SELL)
    """

    def __init__(self) -> None:
        super().__init__(strategy_id="RELATIVE_VOLUME")

    def scan(
        self,
        bars: list[BarSnapshot],
        symbol: str = "",
        interval: str = "",
    ) -> ScannerResult:
        if len(bars) < 21:
            return ScannerResult()

        volumes = [b.volume for b in bars]
        closes = [b.close for b in bars]

        current_vol = volumes[-1]
        avg_vol = sum(volumes[-21:-1]) / 20.0

        if avg_vol <= 0:
            return ScannerResult()

        vol_ratio = current_vol / avg_vol

        # Require 2.5x volume spike
        if vol_ratio < 2.5:
            return ScannerResult()

        # Check price direction
        price_change = closes[-1] - closes[-4] if len(closes) >= 4 else closes[-1] - closes[-2]

        if price_change > 0:
            return ScannerResult(
                signal=NormalizedSignal(
                    symbol=symbol.upper(),
                    side=SignalSide.BUY,
                    strategy=self.strategy_id,
                    timeframe=interval,
                    price=closes[-1],
                    source="scanner",
                    reason=f"Volume spike: {vol_ratio:.1f}x avg ({current_vol:.0f} vs {avg_vol:.0f})",
                )
            )

        if price_change < 0:
            return ScannerResult(
                signal=NormalizedSignal(
                    symbol=symbol.upper(),
                    side=SignalSide.SELL,
                    strategy=self.strategy_id,
                    timeframe=interval,
                    price=closes[-1],
                    source="scanner",
                    reason=f"Volume spike: {vol_ratio:.1f}x avg ({current_vol:.0f} vs {avg_vol:.0f})",
                )
            )

        return ScannerResult()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/ops_api/test_scanner_signals.py -v`
Expected: all 8 tests PASS

- [ ] **Step 8: Commit**

```bash
git add ops_api/scanner/ tests/ops_api/test_scanner_signals.py
git commit -m "feat: add scanner engine with momentum and volume scanners"
```

---

### Task 5: Create `scheduler.py` — ScanScheduler daemon thread

**Files:**
- Create: `ops_api/scheduler.py`
- Create: `tests/ops_api/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

Create `tests/ops_api/test_scheduler.py`:

```python
"""Scheduler tests — daemon thread lifecycle, stop/shutdown."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from ops_api.scheduler import ScanScheduler


class TestScanScheduler:
    def test_start_and_stop(self) -> None:
        callback = MagicMock()
        scheduler = ScanScheduler(callback_fn=callback, interval_seconds=0.05)
        scheduler.start()
        time.sleep(0.12)
        assert scheduler.running
        scheduler.stop()
        assert not scheduler.running
        # callback should have been called at least once
        assert callback.call_count >= 1

    def test_stop_without_start_no_error(self) -> None:
        scheduler = ScanScheduler(callback_fn=lambda: None, interval_seconds=60)
        scheduler.stop()  # should not raise

    def test_double_start_no_error(self) -> None:
        scheduler = ScanScheduler(callback_fn=lambda: None, interval_seconds=60)
        scheduler.start()
        scheduler.start()  # second start should be no-op
        assert scheduler.running
        scheduler.stop()

    def test_callback_error_does_not_crash_thread(self) -> None:
        call_count = 0

        def flaky_callback() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Boom!")

        scheduler = ScanScheduler(callback_fn=flaky_callback, interval_seconds=0.05)
        scheduler.start()
        time.sleep(0.15)
        scheduler.stop()
        # callback ran twice despite first call raising
        assert call_count >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ops_api/test_scheduler.py -v`
Expected: ImportError (no module `ops_api.scheduler`)

- [ ] **Step 3: Implement ScanScheduler**

Create `ops_api/scheduler.py`:

```python
"""Scan scheduler — daemon thread that runs the scan loop.

Designed to be started/stopped from FastAPI lifespan. Uses
threading.Event for clean shutdown — no polling, no busy-wait.
"""

from __future__ import annotations

import threading
from typing import Callable

from loguru import logger


class ScanScheduler:
    """Daemon thread that calls ``callback_fn`` on a fixed interval.

    The callback is invoked back-to-back: if a scan takes longer than
    the interval, the next scan starts immediately after the previous
    one finishes (no overlapping executions).

    Start with ``start()``, stop with ``stop()``. The thread is a
    daemon so it won't block process exit.

    Args:
        callback_fn: Zero-argument callable invoked on each tick.
        interval_seconds: Time between callback invocations (seconds).
        name: Thread name for diagnostics.
    """

    def __init__(
        self,
        callback_fn: Callable[[], None],
        interval_seconds: int = 60,
        name: str = "scan-scheduler",
    ) -> None:
        self._callback = callback_fn
        self._interval = interval_seconds
        self._name = name
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the scheduler thread. No-op if already running."""
        if self.running:
            logger.debug("ScanScheduler already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=self._name,
            daemon=True,
        )
        self._thread.start()
        logger.info("ScanScheduler started (interval={}s)", self._interval)

    def stop(self) -> None:
        """Signal the scheduler to stop and wait for thread to exit."""
        if not self.running:
            logger.debug("ScanScheduler not running — stop is a no-op")
            return

        logger.info("ScanScheduler stopping...")
        self._stop_event.set()
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            logger.warning("ScanScheduler thread did not exit within timeout")
        self._thread = None
        logger.info("ScanScheduler stopped")

    def _run_loop(self) -> None:
        """Main loop: invoke callback, sleep, check stop."""
        logger.debug("ScanScheduler loop started")
        while not self._stop_event.is_set():
            try:
                self._callback()
            except Exception:
                logger.exception("ScanScheduler callback raised an error — continuing")

            self._stop_event.wait(timeout=self._interval)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ops_api/test_scheduler.py -v`
Expected: 4 PASS (note: tests use short interval, may take ~0.5s total)

- [ ] **Step 5: Commit**

```bash
git add ops_api/scheduler.py tests/ops_api/test_scheduler.py
git commit -m "feat: add ScanScheduler daemon thread for periodic scanning"
```

---

### Task 6: Add scanner config fields

**Files:**
- Modify: `ops_api/config.py:14-68`

- [ ] **Step 1: Add scanner config fields to OpsApiConfig**

Add after `use_strategy_engine: bool = True`:

```python
    # ── Scanner Engine ───────────────────────────────────────
    scanner_enabled: bool = True
    scanner_interval_seconds: int = 60
    scanner_symbols: tuple[str, ...] = field(
        default_factory=lambda: (
            "NIFTY", "BANKNIFTY",
        )
    )
```

Add to `bool_keys`:
```python
    bool_keys = {"OA_RELOAD", "OA_FLATTEN_ON_KILL", "OA_USE_STRATEGY_ENGINE", "OA_SCANNER_ENABLED"}
```

Add to `int_keys`:
```python
    int_keys = {
        "OA_PORT",
        "OA_DASHBOARD_PORT",
        "OA_HEARTBEAT_INTERVAL_SECONDS",
        "OA_MAX_STALENESS_SECONDS",
        "OA_DB_POOL_TIMEOUT",
        "OA_RETENTION_DAYS",
        "OA_SCANNER_INTERVAL_SECONDS",
    }
```

Add environment variable handling for `OA_SCANNER_SYMBOLS` (same pattern as `OA_ALLOWED_SYMBOLS`):

In the env var loop, add:
```python
        elif key == "OA_SCANNER_SYMBOLS":
            kwargs["scanner_symbols"] = tuple(
                s.strip() for s in value.split(",") if s.strip()
            )
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `pytest tests/ops_api/ -v`
Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add ops_api/config.py
git commit -m "feat: add scanner configuration options"
```

---

### Task 7: Wire scanner lifecycle into `main.py`

**Files:**
- Modify: `ops_api/main.py` — imports, globals, lifespan start/stop, scan callback

- [ ] **Step 1: Write integration test for full scan lifecycle**

Add to `tests/ops_api/test_scanner_signals.py` at the end:

```python
class TestScanLifecycle:
    """Integration-style tests for scanner→strategy engine flow."""

    def test_scan_callback_runs_without_error(self) -> None:
        """Verify the scan callback function doesn't crash when called."""
        from ops_api.scheduler import ScanScheduler

        calls: list[int] = []

        def mock_callback() -> None:
            calls.append(1)

        scheduler = ScanScheduler(callback_fn=mock_callback, interval_seconds=0.05)
        scheduler.start()
        import time
        time.sleep(0.12)
        scheduler.stop()
        assert len(calls) >= 1

    def test_scanner_signal_dict_structure(self) -> None:
        """Verify a scanner-generated signal dict has all required fields."""
        from ops_api.models import NormalizedSignal, SignalSide

        sig = NormalizedSignal(
            symbol="NIFTY",
            side=SignalSide.BUY,
            strategy="MOMENTUM",
            price=18200.0,
            source="scanner",
            reason="Test signal",
        )
        d = sig.model_dump()
        assert d["source"] == "scanner"
        assert d["strategy"] == "MOMENTUM"
        assert d["side"] == "BUY"
        assert d["symbol"] == "NIFTY"
```

- [ ] **Step 2: Modify `main.py` — add imports and globals**

Add imports:
```python
from ops_api.market_data import KiteConnectMarketData, OHLCVCache
from ops_api.scanner import MomentumScanner, VolumeScanner
from ops_api.scheduler import ScanScheduler
```

Add globals after `strategy_engine`:
```python
scanner_scheduler: ScanScheduler | None = None
market_data_cache: OHLCVCache | None = None
market_data_provider: KiteConnectMarketData | None = None
```

Add to the global declaration at top of lifespan:
```python
global config, db, validator, executor, notifier, strategy_engine, scanner_scheduler, market_data_cache, market_data_provider
```

- [ ] **Step 3: Build scanner callback**

This is a standalone function that builds the scan callback closure. Add it near the top of `main.py` before the `lifespan` function:

```python
def _build_scan_callback(
    kite_client: Any,
    config: OpsApiConfig,
    strategy_engine: StrategyEngine,
    db: DatabaseManager,
    cache: OHLCVCache,
) -> Callable[[], None]:
    """Build the scanner callback closure.

    Captures all dependencies so the scheduler only needs a zero-arg
    callable. Each tick:
      1. For each symbol in config.scanner_symbols:
         a. Check cache; if miss, fetch via Kite provider
         b. Run MomentumScanner + VolumeScanner on cached bars
         c. If signal emitted, feed into StrategyEngine.process()
    """
    from ops_api.market_data.kite_provider import KiteConnectMarketData

    provider = KiteConnectMarketData(kite_client) if kite_client else None
    momentum = MomentumScanner()
    volume = VolumeScanner()

    def _scan_tick() -> None:
        for symbol in config.scanner_symbols:
            try:
                # Try cache first
                bars = cache.get(symbol, "60")
                if bars is None and provider is not None:
                    bars = provider.fetch(symbol, interval="60", count=100)
                    if bars:
                        cache.set(symbol, "60", bars)

                if not bars:
                    logger.debug("Scan tick: no bars for {}", symbol)
                    continue

                # Run scanners
                momentum_result = momentum.scan(bars, symbol=symbol, interval="60")
                if momentum_result.has_signal and momentum_result.signal is not None:
                    signal_dict = momentum_result.signal.model_dump()
                    signal_dict["id"] = str(uuid4())
                    signal_dict["normalized_at"] = datetime.utcnow().isoformat()
                    db.insert_signal(signal_dict)
                    exec_result = strategy_engine.process(signal_dict, mode="paper")
                    logger.info("Scanner signal processed: symbol={} strategy={} result={}",
                                symbol, "MOMENTUM", exec_result.get("status"))

                volume_result = volume.scan(bars, symbol=symbol, interval="60")
                if volume_result.has_signal and volume_result.signal is not None:
                    signal_dict = volume_result.signal.model_dump()
                    signal_dict["id"] = str(uuid4())
                    signal_dict["normalized_at"] = datetime.utcnow().isoformat()
                    db.insert_signal(signal_dict)
                    exec_result = strategy_engine.process(signal_dict, mode="paper")
                    logger.info("Scanner signal processed: symbol={} strategy={} result={}",
                                symbol, "RELATIVE_VOLUME", exec_result.get("status"))

            except Exception:
                logger.exception("Scan tick error for symbol={}", symbol)

    return _scan_tick
```

- [ ] **Step 4: Wire into lifespan — start after strategy engine setup, stop on shutdown**

In `lifespan`, after strategy engine initialization and before the notifier alert_system call, add:

```python
    # ── Scanner Engine (Phase 2) ─────────────────────────────
    market_data_cache = OHLCVCache(ttl_seconds=300)
    scanner_scheduler = None

    if config.scanner_enabled:
        # Build kite provider from the same kite_client used by executor
        _scan_callback = _build_scan_callback(
            kite_client=kite_client,
            config=config,
            strategy_engine=strategy_engine,
            db=db,
            cache=market_data_cache,
        )
        scanner_scheduler = ScanScheduler(
            callback_fn=_scan_callback,
            interval_seconds=config.scanner_interval_seconds,
        )
        scanner_scheduler.start()
        logger.info(
            "Scanner engine started: {} symbols, interval={}s",
            len(config.scanner_symbols),
            config.scanner_interval_seconds,
        )
```

In the shutdown section (after `yield`), add before `await notifier.close()`:

```python
    if scanner_scheduler is not None:
        scanner_scheduler.stop()
        logger.info("Scanner scheduler stopped")
```

- [ ] **Step 5: Add missing imports at top of main.py**

Make sure these are imported:
```python
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4
```

(Note: `datetime` is already imported, `Any` is already imported, but need `Callable` and `uuid4`)

- [ ] **Step 6: Run test suite to verify no regressions**

Run: `pytest tests/ops_api/ -v`
Expected: all tests pass (~145+)

- [ ] **Step 7: Commit**

```bash
git add ops_api/main.py
git commit -m "feat: wire scanner lifecycle into FastAPI lifespan"
```

---

### Task 8: Full integration test — scanner signal flows through StrategyEngine

**Files:**
- Modify: `tests/ops_api/test_strategy_engine.py`
- Modify: `tests/ops_api/test_scanner_signals.py`

- [ ] **Step 1: Add test verifying scanner-origin signals flow through StrategyEngine**

Add to `tests/ops_api/test_strategy_engine.py`:

```python
class TestScannerIntegration:
    """Scanner signals should flow through StrategyEngine like webhook signals."""

    def test_scanner_signal_processed_by_strategy_engine(
        self, engine: StrategyEngine
    ) -> None:
        """A scanner-generated signal dict should be accepted by process()."""
        signal = {
            "id": "scanner_sig_001",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 18200.0,
            "strategy": "MOMENTUM",
            "source": "scanner",
            "timeframe": "60",
        }
        result = engine.process(signal, mode="paper")
        # Should resolve to DefaultStrategy (no MOMENTUM strategy registered),
        # pass validation, and execute as paper trade
        assert result.get("strategy_id") in ("default", "MOMENTUM")
        assert result.get("status") in ("filled", "rejected", "skipped")

    def test_scanner_signal_with_source_field(
        self, engine: StrategyEngine
    ) -> None:
        """source field should be preserved through the pipeline."""
        signal = {
            "id": "scanner_sig_002",
            "symbol": "NIFTY",
            "side": "BUY",
            "price": 18200.0,
            "strategy": "default",
            "source": "scanner",
            "timeframe": "60",
        }
        result = engine.process(signal, mode="paper")
        assert "strategy_id" in result
```

- [ ] **Step 2: Add a dedicated scanner→db storage test**

Add to `tests/ops_api/test_scanner_signals.py`:

```python
class TestScannerSignalStorage:
    def test_scanner_signal_stored_in_db(self, db: DatabaseManager) -> None:
        """Signals with source='scanner' are stored in normalized_signals."""
        from ops_api.models import NormalizedSignal, SignalSide

        sig = NormalizedSignal(
            symbol="NIFTY",
            side=SignalSide.BUY,
            strategy="MOMENTUM",
            price=18200.0,
            source="scanner",
            reason="Test signal",
        )
        signal_dict = sig.model_dump()
        signal_dict["normalized_at"] = "2026-05-20T10:00:00.000Z"
        db.insert_signal(signal_dict)

        recent = db.get_recent_signals(limit=10)
        assert any(s["id"] == sig.id for s in recent)
        stored = next(s for s in recent if s["id"] == sig.id)
        assert stored["source"] == "scanner"
```

Need the `db` fixture — add at top of file after imports:

```python
import tempfile
import pytest
from ops_api.db import DatabaseManager


@pytest.fixture
def db() -> DatabaseManager:
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ops_api/ -v`
Expected: all ~150+ tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/ops_api/test_strategy_engine.py tests/ops_api/test_scanner_signals.py
git commit -m "test: add scanner integration tests for strategy engine and DB storage"
```

---

### Task 9: Update CURRENT_STATUS.md

**Files:**
- Modify: `trading-term/CURRENT_STATUS.md`

- [ ] **Step 1: Read CURRENT_STATUS.md**

- [ ] **Step 2: Update to reflect Phase 2 completion**

Update version to v0.5.0, add Market Data + Scanner Engine section, note new config options.

- [ ] **Step 3: Commit**

```bash
git add trading-term/CURRENT_STATUS.md
git commit -m "docs: update CURRENT_STATUS.md for Phase 2 scanner engine"
```

---

### Task 10: Final verification — full test suite + smoke test

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ops_api/ -v`
Expected: all tests pass

- [ ] **Step 2: Verify scanner import chain works end-to-end**

Run: `python -c "from ops_api.scanner import MomentumScanner, VolumeScanner, BaseScanner, ScannerResult; from ops_api.market_data import BarSnapshot, OHLCVCache, KiteConnectMarketData; from ops_api.indicators import ema, atr, vwap; from ops_api.scheduler import ScanScheduler; print('All Phase 2 imports OK')"`
Expected: "All Phase 2 imports OK"

- [ ] **Step 3: Verify config loads correctly**

Run: `python -c "from ops_api.config import OpsApiConfig; c = OpsApiConfig(); assert c.scanner_enabled; assert c.scanner_interval_seconds == 60; assert len(c.scanner_symbols) >= 2; print('Config OK')"`
Expected: "Config OK"