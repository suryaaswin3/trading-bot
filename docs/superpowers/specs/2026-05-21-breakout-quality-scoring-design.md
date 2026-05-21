# Phase 5A — Deterministic Breakout Quality Scoring

> **Runtime evolution:** portfolio orchestration → signal quality intelligence

**Goal:** Reject low-quality breakout signals before they reach `StrategyEngine.process()` using deterministic, stateless scoring criteria. Six dimensions: RVOL, candle strength, VWAP alignment, EMA trend alignment, range expansion, time-window filtering.

**Architecture:** New `ops_api/quality.py` module with pure functions following the `indicators.py` pattern. `QualityScore` dataclass with component scores (0.0–1.0), weighted total, and accept/reject gate. Integration in `_scan_tick()` before strategy engine dispatch. No changes to `strategy_engine.py` or `execution.py`.

**Tech Stack:** Python 3.14, dataclasses, no dependencies beyond standard library + existing ops_api modules.

---

## Design Decisions

### Module Structure
Standalone pure-function module (`ops_api/quality.py`). Each scoring dimension is an independent function returning `float`. A single aggregation function `score_breakout()` calls all six and returns a `QualityScore` dataclass.

### Scoring Model
Each dimension scores 0.0–1.0. Total is weighted average. `accepted = total >= min_quality` threshold. Rejected signals carry the score and reason for logging/metrics.

### Data Flow
```
Scanner emits signal → quality.score_breakout(bars, signal) → QualityScore
  → accepted=True  → StrategyEngine.process() (unchanged)
  → accepted=False → log reason + record in metrics → skip
```

### Weight Distribution
| Dimension | Weight | Rationale |
|-----------|--------|-----------|
| RVOL | 25% | Volume confirmation is primary breakout signal |
| Candle strength | 20% | Strong body = conviction |
| VWAP alignment | 20% | Price relative to fair value |
| EMA trend | 15% | Multi-timeframe trend context |
| Range expansion | 10% | Volatility expansion confirms breakout |
| Time window | 10% | Session-phase liquidity filter |

---

## Spec

### New Files

| File | Responsibility |
|------|---------------|
| `ops_api/quality.py` | QualityScore, QualityConfig, scoring functions, score_breakout() |
| `tests/ops_api/test_quality.py` | Tests for all scoring dimensions + aggregation + edge cases |

### Modified Files

| File | Changes |
|------|---------|
| `ops_api/main.py` | Import quality, call `score_breakout()` in `_scan_tick()`, gate on `accepted` |
| `ops_api/scan_metrics.py` | Add `record_quality()` method (optional, for rejected-signal tracking) |

### Data Model

```python
@dataclass
class QualityConfig:
    min_quality: float = 0.5
    rvol_threshold: float = 1.5
    min_candle_body_pct: float = 0.4
    range_multiple: float = 1.0
    enable_time_window: bool = True

@dataclass
class QualityScore:
    rvol: float
    candle_strength: float
    vwap_alignment: float
    ema_trend: float
    range_expansion: float
    time_quality: float
    total: float
    accepted: bool
    reason: str
```

### Scoring Functions

| Function | Input | Output | Logic |
|----------|-------|--------|-------|
| `score_rvol(bars, period=20)` | OHLCV bars | 0.0–1.0 | `clamp((vol/avg_vol - 1) / 2, 0, 1)` — 3x avg = 1.0 |
| `score_candle_strength(last_bar, side)` | single bar + signal side | 0.0–1.0 | body/range ratio * direction check |
| `score_vwap(bars, side)` | OHLCV bars + side | 0.0–1.0 | price distance from VWAP as % of ATR, linear decay |
| `score_ema_trend(bars)` | OHLCV bars | 0.0–1.0 | EMA20/50 slope + separation |
| `score_range_expansion(bars, period=14)` | OHLCV bars | 0.0–1.0 | current range / ATR(14), capped at 1.0 |
| `score_time_window(timestamp=None)` | optional timestamp | 0.0–1.0 | peak (1.0), midday (0.5), close (0.0) |

### Integration

In `ops_api/main.py`, inside `_scan_tick()`:

```python
if result.has_signal and result.signal is not None:
    qs = score_breakout(bars, result.signal)
    if metrics:
        metrics.record_quality(qs)
    if not qs.accepted:
        logger.info("Quality reject {} {}: {} (score={:.2f})", symbol, strategy_name, qs.reason, qs.total)
        continue
    # ... existing strategy_engine.process() path
```

### Testing

`tests/ops_api/test_quality.py` — ~15 tests:

- `test_rvol_high`: current vol >> avg → score near 1.0
- `test_rvol_low`: current vol ~ avg → score near 0.0
- `test_candle_strength_strong`: full body, close at extreme → score ~1.0
- `test_candle_strength_weak`: small body, close in middle → score < 0.5
- `test_vwap_alignment_above`: BUY above VWAP → positive score
- `test_vwap_alignment_below`: BUY below VWAP → low score
- `test_ema_trend_rising`: EMA20 > EMA50, both rising → high score
- `test_ema_trend_falling`: EMA20 < EMA50 → high score for SELL signal
- `test_range_expansion_wide`: current range >> ATR → score near 1.0
- `test_range_expansion_narrow`: current range < ATR → low score
- `test_time_quality_peak`: peak hours → 1.0
- `test_time_quality_close`: end of session → 0.0
- `test_score_breakout_accepted`: all good → accepted=True
- `test_score_breakout_rejected`: all bad → accepted=False, reason non-empty
- `test_empty_bars_safe`: empty bars → all zeros, no crash

### Rollback Safety
- Import error on `quality.py` start → scanner continues without quality gate
- Pure functions only — no state, no side effects
- `_scan_tick()` fallback: `try: qs = score_breakout(...) except Exception: continue` is safe