"""Tests for multi-timeframe breakout confirmation."""
from __future__ import annotations

import pytest
from ops_api.confirmation import (
    ConfirmationConfig, ConfirmationState, confirm_signal,
    score_htf_ema_alignment, score_vwap_alignment,
    score_candle_structure, score_direction_agreement,
    check_countertrend, check_exhaustion,
)


def _bar(open, high, low, close, volume, timestamp=0.0):
    return {"open": open, "high": high, "low": low, "close": close, "volume": volume}


def _trend_bars(up: bool = True, strength: float = 0.5, count: int = 60):
    direction = 1.0 if up else -1.0
    closes = [100 + i * direction * strength for i in range(count)]
    return [_bar(c - 1, c + 2, c - 1.5, c, 1000) for c in closes]


def _flat_bars(center: float = 100, count: int = 60):
    return [_bar(center - 1, center + 1, center - 1, center, 500) for _ in range(count)]


# ── HTF EMA Alignment ───────────────────────────────────────────────────────


class TestHTFEMAAlignment:
    def test_bull_ema_buy_signal(self):
        """Bullish HTF EMAs + BUY signal → high score."""
        bars = _trend_bars(up=True, strength=0.3, count=60)
        assert score_htf_ema_alignment(bars, "BUY") > 0.5

    def test_bear_ema_sell_signal(self):
        """Bearish HTF EMAs + SELL signal → high score."""
        bars = _trend_bars(up=False, strength=0.3, count=60)
        assert score_htf_ema_alignment(bars, "SELL") > 0.5

    def test_bull_ema_sell_signal(self):
        """Bullish HTF EMAs + SELL signal → 0."""
        bars = _trend_bars(up=True, strength=0.5, count=60)
        assert score_htf_ema_alignment(bars, "SELL") == 0.0

    def test_bear_ema_buy_signal(self):
        """Bearish HTF EMAs + BUY signal → 0."""
        bars = _trend_bars(up=False, strength=0.5, count=60)
        assert score_htf_ema_alignment(bars, "BUY") == 0.0

    def test_flat_htf(self):
        """Flat HTF → neutral (0.5)."""
        bars = _flat_bars(count=60)
        score = score_htf_ema_alignment(bars, "BUY")
        assert score == 0.5

    def test_insufficient_bars(self):
        """Not enough bars → neutral."""
        bars = [_bar(100, 101, 99, 100, 1000) for _ in range(10)]
        assert score_htf_ema_alignment(bars, "BUY") == 0.5


# ── VWAP Alignment ──────────────────────────────────────────────────────────


class TestVWAPAlignment:
    def test_both_above_buy(self):
        """Both TFs above VWAP + BUY → 1.0."""
        ltf = [_bar(101, 103, 99, 102, 1000) for _ in range(30)]
        htf = [_bar(101, 103, 99, 102, 1000) for _ in range(30)]
        assert score_vwap_alignment(ltf, htf, "BUY") == 1.0

    def test_both_below_sell(self):
        """Both TFs below VWAP + SELL → 1.0."""
        ltf = [_bar(99, 101, 97, 98, 1000) for _ in range(30)]
        htf = [_bar(99, 101, 97, 98, 1000) for _ in range(30)]
        assert score_vwap_alignment(ltf, htf, "SELL") == 1.0

    def test_one_aligned(self):
        """One TF aligned → 0.5."""
        ltf = [_bar(99, 101, 97, 98, 1000) for _ in range(30)]  # below
        htf = [_bar(101, 103, 99, 102, 1000) for _ in range(30)]  # above
        assert score_vwap_alignment(ltf, htf, "BUY") == 0.5

    def test_none_aligned(self):
        """Both TFs against signal → 0.0."""
        ltf = [_bar(99, 101, 97, 98, 1000) for _ in range(30)]  # below
        htf = [_bar(99, 101, 97, 98, 1000) for _ in range(30)]  # below
        assert score_vwap_alignment(ltf, htf, "BUY") == 0.0

    def test_insufficient_bars(self):
        """Not enough bars → neutral."""
        assert score_vwap_alignment(
            [_bar(100, 101, 99, 100, 1000)],
            [_bar(100, 101, 99, 100, 1000)],
            "BUY",
        ) == 0.5


# ── Candle Structure ────────────────────────────────────────────────────────


class TestCandleStructure:
    def test_strong_buy_candle(self):
        """Full body, close at high, small wicks → high score."""
        # Last bar: 100→110, no wicks
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(5)]
        bars[-1] = _bar(100, 110, 100, 110, 2000)
        assert score_candle_structure(bars, "BUY") > 0.7

    def test_strong_sell_candle(self):
        """Full body, close at low → high score."""
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(5)]
        bars[-1] = _bar(110, 110, 100, 100, 2000)
        assert score_candle_structure(bars, "SELL") > 0.7

    def test_weak_candle(self):
        """Small body, close in middle → low score."""
        bars = [_bar(100, 102, 98, 101, 1000) for _ in range(5)]
        bars[-1] = _bar(100, 110, 90, 101, 1000)  # close at mid, body=1, wicks large
        assert score_candle_structure(bars, "BUY") < 0.4

    def test_insufficient_bars(self):
        """Not enough bars → neutral."""
        assert score_candle_structure([_bar(100, 101, 99, 100, 1000)], "BUY") == 0.5

    def test_flat_range(self):
        """No range → 0."""
        bars = [_bar(100, 100, 100, 100, 1000), _bar(100, 100, 100, 100, 1000)]
        assert score_candle_structure(bars, "BUY") == 0.0


# ── Direction Agreement ──────────────────────────────────────────────────────


class TestDirectionAgreement:
    def test_both_up_buy(self):
        """Both TFs rising + BUY → 1.0."""
        ltf = _trend_bars(up=True, strength=0.3, count=30)
        htf = _trend_bars(up=True, strength=0.2, count=30)
        assert score_direction_agreement(ltf, htf, "BUY") == 1.0

    def test_both_down_sell(self):
        """Both TFs falling + SELL → 1.0."""
        ltf = _trend_bars(up=False, strength=0.3, count=30)
        htf = _trend_bars(up=False, strength=0.2, count=30)
        assert score_direction_agreement(ltf, htf, "SELL") == 1.0

    def test_ltf_flat(self):
        """LTF flat → 0 (LTF doesn't support signal)."""
        ltf = _flat_bars(count=30)
        htf = _trend_bars(up=True, strength=0.3, count=30)
        assert score_direction_agreement(ltf, htf, "BUY") == 0.0

    def test_opposing_directions(self):
        """LTF up, HTF down, BUY signal → partial."""
        ltf = _trend_bars(up=True, strength=0.3, count=30)
        htf = _trend_bars(up=False, strength=0.2, count=30)
        assert score_direction_agreement(ltf, htf, "BUY") == 0.3

    def test_insufficient_bars(self):
        """Not enough bars → neutral."""
        assert score_direction_agreement(
            [_bar(100, 101, 99, 100, 1000) for _ in range(3)],
            [_bar(100, 101, 99, 100, 1000) for _ in range(3)],
            "BUY",
        ) == 0.5


# ── Countertrend ────────────────────────────────────────────────────────────


class TestCountertrend:
    def test_bull_htf_buy_signal(self):
        """Bull HTF + BUY → 1.0 (not countertrend)."""
        bars = _trend_bars(up=True, strength=0.5, count=60)
        assert check_countertrend(bars, "BUY", ConfirmationConfig()) == 1.0

    def test_bull_htf_sell_signal(self):
        """Bull HTF + SELL → 0.0 (countertrend)."""
        bars = _trend_bars(up=True, strength=0.5, count=60)
        assert check_countertrend(bars, "SELL", ConfirmationConfig()) == 0.0

    def test_bear_htf_buy_signal(self):
        """Bear HTF + BUY → 0.0 (countertrend)."""
        bars = _trend_bars(up=False, strength=0.5, count=60)
        assert check_countertrend(bars, "BUY", ConfirmationConfig()) == 0.0

    def test_flat_htf(self):
        """Flat HTF → 1.0 (no strong trend against)."""
        bars = _flat_bars(count=60)
        assert check_countertrend(bars, "BUY", ConfirmationConfig()) == 1.0

    def test_insufficient_sep(self):
        """Small EMA sep → 1.0 (below countertrend threshold)."""
        # 40 bars with tiny drift — EMA separation stays below threshold
        bars = _trend_bars(up=True, strength=0.03, count=40)
        assert check_countertrend(bars, "SELL", ConfirmationConfig()) == 1.0


# ── Exhaustion ─────────────────────────────────────────────────────────────


class TestExhaustion:
    def test_healthy(self):
        """Normal LTF range → 1.0."""
        ltf = [_bar(100, 102, 98, 101, 1000) for _ in range(30)]
        htf = [_bar(100, 105, 95, 100, 1000) for _ in range(20)]
        assert check_exhaustion(ltf, htf, ConfirmationConfig()) == 1.0

    def test_exhausted_wide_range_tiny_body(self):
        """Wide LTF range + tiny body → 0.0 (exhausted)."""
        # HTF has normal range ~10, LTF last bar has range 30+ with tiny body
        htf = [_bar(100, 105, 95, 100, 1000) for _ in range(20)]
        ltf = [_bar(100, 102, 98, 101, 1000) for _ in range(29)]
        ltf.append(_bar(105, 135, 100, 108, 5000))  # range=35, body=3, body/rng=0.086
        assert check_exhaustion(ltf, htf, ConfirmationConfig()) == 0.0

    def test_wide_range_good_body(self):
        """Wide LTF range + decent body → 0.3 (caution)."""
        htf = [_bar(100, 105, 95, 100, 1000) for _ in range(20)]
        ltf = [_bar(100, 102, 98, 101, 1000) for _ in range(29)]
        ltf.append(_bar(100, 135, 100, 125, 5000))  # range=35, body=25, body/rng=0.71
        score = check_exhaustion(ltf, htf, ConfirmationConfig())
        assert score == 0.3

    def test_insufficient_bars(self):
        """Not enough HTF bars → 1.0."""
        assert check_exhaustion(
            [_bar(100, 101, 99, 100, 1000) for _ in range(5)],
            [_bar(100, 101, 99, 100, 1000) for _ in range(3)],
            ConfirmationConfig(),
        ) == 1.0


# ── Aggregation ─────────────────────────────────────────────────────────────


class TestConfirmSignal:
    def test_accepted(self):
        """All dimensions aligned → accepted."""
        ltf = _trend_bars(up=True, strength=0.3, count=30)
        htf = _trend_bars(up=True, strength=0.2, count=60)
        result = confirm_signal(ltf, htf, {"side": "BUY"})
        assert result.accepted
        assert result.alignment_score >= 0.35

    def test_accepted_sell(self):
        """Sell signal with bearish HTF → accepted."""
        ltf = _trend_bars(up=False, strength=0.3, count=30)
        htf = _trend_bars(up=False, strength=0.2, count=60)
        result = confirm_signal(ltf, htf, {"side": "SELL"})
        assert result.accepted
        assert result.alignment_score >= 0.35

    def test_countertrend_rejects(self):
        """Countertrend signal → rejected."""
        ltf = _trend_bars(up=True, strength=0.3, count=30)
        htf = _trend_bars(up=False, strength=0.5, count=60)  # bearish HTF
        result = confirm_signal(ltf, htf, {"side": "BUY"})
        assert not result.accepted
        assert result.reason != "all_aligned"

    def test_exhaustion_penalizes(self):
        """Exhausted LTF + good HTF → may still pass but with lower confidence."""
        htf = _trend_bars(up=True, strength=0.2, count=60)
        ltf = _trend_bars(up=True, strength=0.1, count=29)
        ltf.append(_bar(105, 135, 100, 125, 5000))  # exhaustion candle
        result = confirm_signal(ltf, htf, {"side": "BUY"})
        # Exhaustion reduces confidence but doesn't hard-reject
        assert result.confidence < result.alignment_score

    def test_flat_market(self):
        """Flat LTF + flat HTF → neutral, may still pass with low confidence."""
        ltf = _flat_bars(count=30)
        htf = _flat_bars(count=60)
        result = confirm_signal(ltf, htf, {"side": "BUY"})
        assert isinstance(result.accepted, bool)

    def test_empty_bars(self):
        """Empty bars → no crash."""
        result = confirm_signal([], [], {"side": "BUY"})
        assert not result.accepted
        assert "insufficient_data" in result.reason

    def test_insufficient_bars(self):
        """Too few bars → rejected."""
        ltf = [_bar(100, 101, 99, 100, 1000) for _ in range(5)]
        htf = [_bar(100, 101, 99, 100, 1000) for _ in range(5)]
        result = confirm_signal(ltf, htf, {"side": "BUY"})
        assert not result.accepted

    def test_barsnapshot_input(self):
        """BarSnapshot-like objects accepted."""
        from types import SimpleNamespace
        ltf = [SimpleNamespace(open=100 + i * 0.3, high=102 + i * 0.3, low=98 + i * 0.3, close=101 + i * 0.3, volume=1000) for i in range(30)]
        htf = [SimpleNamespace(open=100 + i * 0.2, high=102 + i * 0.2, low=98 + i * 0.2, close=101 + i * 0.2, volume=1000) for i in range(60)]
        result = confirm_signal(ltf, htf, {"side": "BUY"})
        assert isinstance(result.accepted, bool)

    def test_custom_config(self):
        """Custom config overrides defaults."""
        ltf = _flat_bars(count=30)
        htf = _flat_bars(count=60)
        config = ConfirmationConfig(min_alignment=0.1)  # very low bar
        result = confirm_signal(ltf, htf, {"side": "BUY"}, config=config)
        assert isinstance(result, ConfirmationState)

    def test_result_type(self):
        """Returns ConfirmationState dataclass."""
        result = confirm_signal([], [], {"side": "BUY"})
        assert isinstance(result, ConfirmationState)

    def test_metrics_have_all_keys(self):
        """Metrics contains all expected keys."""
        ltf = _trend_bars(up=True, strength=0.3, count=30)
        htf = _trend_bars(up=True, strength=0.2, count=60)
        result = confirm_signal(ltf, htf, {"side": "BUY"})
        for key in ("ema_alignment", "vwap_alignment", "candle_structure", "direction_agreement", "countertrend", "exhaustion", "alignment"):
            assert key in result.metrics


# ── Config defaults ─────────────────────────────────────────────────────────


class TestConfirmationConfig:
    def test_weights_sum_to_one(self):
        """Default weights sum to 1.0."""
        c = ConfirmationConfig()
        total = c.weight_ema_alignment + c.weight_vwap_alignment + c.weight_candle_structure + c.weight_direction_agreement
        assert abs(total - 1.0) < 0.001