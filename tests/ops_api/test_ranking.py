"""Tests for deterministic symbol ranking."""
from __future__ import annotations

import pytest
from ops_api.ranking import (
    RankingConfig, SymbolRank, rank_symbols,
    score_rvol, score_atr_expansion, score_trend_strength,
    score_breakout_quality, score_liquidity, score_directional_efficiency,
)


def _bar(open, high, low, close, volume, timestamp=0.0):
    return {"open": open, "high": high, "low": low, "close": close, "volume": volume}


def _trend_bars(up: bool = True, strength: float = 0.5, count: int = 60, vol: float = 1000):
    direction = 1.0 if up else -1.0
    closes = [100 + i * direction * strength for i in range(count)]
    return [_bar(c - 1, c + 1, c - 1, c, vol) for c in closes]


# ── RVOL ────────────────────────────────────────────────────────────────────


class TestScoreRVOL:
    def test_high_volume(self):
        """Current vol >> avg → score near 1.0."""
        bars = [_bar(100, 105, 95, 102, v) for v in [100] * 20 + [300]]
        assert score_rvol(bars) >= 0.8

    def test_average_volume(self):
        """Current vol ≈ avg → score near 0."""
        bars = [_bar(100, 105, 95, 102, v) for v in [100] * 21]
        assert score_rvol(bars) < 0.1

    def test_low_volume(self):
        """Current vol below avg → score 0."""
        bars = [_bar(100, 105, 95, 102, v) for v in [100] * 20 + [50]]
        assert score_rvol(bars) == 0.0

    def test_insufficient_bars(self):
        """Not enough bars → score 0."""
        assert score_rvol([_bar(100, 105, 95, 102, 100) for _ in range(5)]) == 0.0

    def test_zero_avg_volume(self):
        """All zero volume → 0, no crash."""
        bars = [_bar(100, 105, 95, 102, 0) for _ in range(21)]
        assert score_rvol(bars) == 0.0


# ── ATR Expansion ────────────────────────────────────────────────────────────


class TestScoreATRExpansion:
    def test_expanding_atr(self):
        """Recent range expanding → high score."""
        # Needs 28+ bars (period + period). First 14 flat, last 14 wide.
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(16)]
        bars += [_bar(100, 115, 85, 105, 2000) for _ in range(14)]
        assert score_atr_expansion(bars) > 0.5

    def test_compressing_atr(self):
        """Recent range compressing → low score."""
        bars = [_bar(100, 115, 85, 105, 1000) for _ in range(16)]
        bars += [_bar(100, 102, 98, 100, 1000) for _ in range(14)]
        assert score_atr_expansion(bars) < 0.5

    def test_flat_atr(self):
        """Stable ATR → neutral score."""
        bars = [_bar(100, 102, 98, 100, 1000) for _ in range(30)]
        score = score_atr_expansion(bars)
        assert 0.3 <= score <= 0.7

    def test_insufficient_bars(self):
        """Not enough bars → 0."""
        bars = [_bar(100, 102, 98, 100, 1000) for _ in range(5)]
        assert score_atr_expansion(bars) == 0.0


# ── Trend Strength ──────────────────────────────────────────────────────────


class TestScoreTrendStrength:
    def test_strong_uptrend(self):
        """Strong upward trend → high score."""
        bars = _trend_bars(up=True, strength=0.5, count=60)
        assert score_trend_strength(bars) > 0.5

    def test_strong_downtrend(self):
        """Strong downward trend → high score."""
        bars = _trend_bars(up=False, strength=0.5, count=60)
        assert score_trend_strength(bars) > 0.5

    def test_flat_market(self):
        """Flat market → low score."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(60)]
        assert score_trend_strength(bars) < 0.5

    def test_insufficient_bars(self):
        """Not enough bars → 0."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(5)]
        assert score_trend_strength(bars) == 0.0


# ── Breakout Quality ────────────────────────────────────────────────────────


class TestScoreBreakoutQuality:
    def test_strong_breakout(self):
        """Wide range + strong close → high score."""
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(20)]
        bars[-1] = _bar(100, 115, 95, 112, 5000)
        assert score_breakout_quality(bars) > 0.5

    def test_weak_breakout(self):
        """Narrow range + weak close → low score."""
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(20)]
        bars[-3] = _bar(100, 108, 92, 104, 2000)  # wider earlier bar
        bars[-2] = _bar(104, 106, 102, 105, 1500)  # narrower
        bars[-1] = _bar(105, 106, 104, 105.5, 500)  # narrower still, mid close
        assert score_breakout_quality(bars) < 0.5

    def test_flat_bar(self):
        """No range → 0."""
        bars = [_bar(100, 100, 100, 100, 1000) for _ in range(20)]
        assert score_breakout_quality(bars) == 0.0

    def test_insufficient_bars(self):
        """Not enough bars → 0."""
        bars = [_bar(100, 102, 98, 100, 1000) for _ in range(5)]
        assert score_breakout_quality(bars) == 0.0


# ── Liquidity ───────────────────────────────────────────────────────────────


class TestScoreLiquidity:
    def test_high_volume(self):
        """Very high volume → 1.0."""
        bars = [_bar(100, 101, 99, 100, 500_000) for _ in range(20)]
        assert score_liquidity(bars) >= 0.9

    def test_low_volume(self):
        """Very low volume → near 0."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(20)]
        assert score_liquidity(bars) < 0.3

    def test_medium_volume(self):
        """Medium volume → intermediate score."""
        bars = [_bar(100, 101, 99, 100, 250_000) for _ in range(20)]
        score = score_liquidity(bars)
        assert 0.3 <= score <= 0.9

    def test_insufficient_bars(self):
        """Not enough bars → 0."""
        assert score_liquidity([_bar(100, 101, 99, 100, 1000) for _ in range(3)]) == 0.0


# ── Directional Efficiency ──────────────────────────────────────────────────


class TestScoreDirectionalEfficiency:
    def test_strong_directional_move(self):
        """Price moves consistently one direction → high score."""
        # Tight range bars that strongly trend: net move >> total range
        bars = [_bar(100, 100.5, 99.5, 100.2, 1000) for _ in range(4)]
        bars += [_bar(106, 106.5, 105.5, 106.2, 1000)]  # big jump near end
        assert score_directional_efficiency(bars) > 0.5

    def test_chop(self):
        """Price goes nowhere → low score."""
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(5)]
        assert score_directional_efficiency(bars) < 0.3

    def test_insufficient_bars(self):
        """Not enough bars → 0."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(2)]
        assert score_directional_efficiency(bars) == 0.0

    def test_zero_range(self):
        """All bars flat → 0."""
        bars = [_bar(100, 100, 100, 100, 1000) for _ in range(5)]
        assert score_directional_efficiency(bars) == 0.0


# ── Aggregation ─────────────────────────────────────────────────────────────


class TestRankSymbols:
    def test_single_symbol(self):
        """Single symbol returns ranked list of one."""
        bars_by_symbol = {
            "SYMBOL1": _trend_bars(up=True, strength=0.5, count=60),
        }
        result = rank_symbols(bars_by_symbol)
        assert len(result) == 1
        assert result[0].symbol == "SYMBOL1"
        assert 0.0 <= result[0].total <= 1.0

    def test_multiple_symbols(self):
        """Multiple symbols sorted by rank descending."""
        bars_by_symbol = {
            "WEAK": [_bar(100, 101, 99, 100, 100) for _ in range(60)],
            "STRONG": _trend_bars(up=True, strength=0.5, count=60, vol=500_000),
        }
        result = rank_symbols(bars_by_symbol)
        # WEAK might not pass min_score filter → only STRONG returned
        assert len(result) >= 1
        if len(result) > 1:
            assert result[0].symbol == "STRONG"

    def test_top_n_filter(self):
        """Only top N symbols returned."""
        bars = _trend_bars(up=True, strength=0.5, count=60, vol=1000)
        bars_by_symbol = {f"SYM{i}": bars for i in range(10)}
        config = RankingConfig(top_n=3)
        result = rank_symbols(bars_by_symbol, config=config)
        assert len(result) == 3

    def test_min_score_filter(self):
        """Symbols below min_score excluded."""
        bars = [_bar(100, 101, 99, 100, 100) for _ in range(60)]
        bars_by_symbol = {"LOW": bars}
        config = RankingConfig(min_score=0.5)
        result = rank_symbols(bars_by_symbol, config=config)
        assert len(result) == 0

    def test_empty_input(self):
        """No symbols → empty list."""
        assert rank_symbols({}) == []

    def test_barsnapshot_input(self):
        """BarSnapshot-like objects accepted."""
        from types import SimpleNamespace

        bars = [SimpleNamespace(open=100 + i, high=102 + i, low=98 + i, close=101 + i, volume=1000) for i in range(60)]
        result = rank_symbols({"SYM": bars})
        assert len(result) == 1
        assert isinstance(result[0], SymbolRank)

    def test_custom_config(self):
        """Custom config overrides defaults."""
        bars = _trend_bars(up=True, strength=0.5, count=60, vol=500_000)
        config = RankingConfig(top_n=10, min_score=0.0)
        result = rank_symbols({"SYM": bars}, config=config)
        assert isinstance(result[0], SymbolRank)

    def test_result_type(self):
        """Returns list of SymbolRank."""
        result = rank_symbols({})
        assert isinstance(result, list)

    def test_scores_in_range(self):
        """All component scores are 0.0-1.0."""
        bars = _trend_bars(up=True, strength=0.5, count=60, vol=500_000)
        result = rank_symbols({"SYM": bars})
        r = result[0]
        for attr in ("rvol", "atr_expansion", "trend_strength", "breakout_quality", "liquidity", "directional_efficiency"):
            assert 0.0 <= getattr(r, attr) <= 1.0, f"{attr} = {getattr(r, attr)}"

    def test_total_is_weighted(self):
        """Total is weighted combination of component scores."""
        bars = _trend_bars(up=True, strength=0.5, count=60, vol=500_000)
        config = RankingConfig(
            weight_rvol=0.2, weight_atr_expansion=0.2, weight_trend_strength=0.2,
            weight_breakout_quality=0.2, weight_liquidity=0.1, weight_directional_efficiency=0.1,
        )
        result = rank_symbols({"SYM": bars}, config=config)
        r = result[0]
        expected = (
            r.rvol * 0.2 + r.atr_expansion * 0.2 + r.trend_strength * 0.2
            + r.breakout_quality * 0.2 + r.liquidity * 0.1 + r.directional_efficiency * 0.1
        )
        assert abs(r.total - expected) < 0.001


# ── Config defaults ─────────────────────────────────────────────────────────


class TestRankingConfig:
    def test_weights_sum_to_one(self):
        """Default weights sum to 1.0."""
        c = RankingConfig()
        total = c.weight_rvol + c.weight_atr_expansion + c.weight_trend_strength \
            + c.weight_breakout_quality + c.weight_liquidity + c.weight_directional_efficiency
        assert abs(total - 1.0) < 0.001