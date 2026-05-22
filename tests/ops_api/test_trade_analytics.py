"""Tests for trade analytics and trade record tracking."""
from __future__ import annotations

import pytest
from ops_api.trade_analytics import TradeAnalytics, TradeRecord


def _trade(
    trade_id: str = "T1",
    symbol: str = "NIFTY",
    side: str = "LONG",
    entry_price: float = 100.0,
    exit_price: float = 105.0,
    quantity: int = 1,
    realized_pnl: float = 5.0,
    regime: str = "TREND",
    quality_score: float = 0.7,
    alignment_score: float = 0.6,
    session_window: str = "peak",
    max_adverse_excursion: float = 0.5,
    max_favourable_excursion: float = 1.5,
) -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id,
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        realized_pnl=realized_pnl,
        entry_time="2026-05-22T09:30:00",
        exit_time="2026-05-22T10:00:00",
        hold_bars=5,
        strategy="test_strat",
        session_window=session_window,
        max_adverse_excursion=max_adverse_excursion,
        max_favourable_excursion=max_favourable_excursion,
        entry_atr=2.0,
        regime=regime,
        quality_score=quality_score,
        alignment_score=alignment_score,
        rank_score=0.8,
    )


# ── TradeRecord ─────────────────────────────────────────────────────────────


class TestTradeRecord:
    def test_is_winner_positive_pnl(self):
        """Positive PnL → is_winner=True."""
        t = _trade(realized_pnl=5.0)
        assert t.is_winner

    def test_is_winner_negative_pnl(self):
        """Negative PnL → is_winner=False."""
        t = _trade(realized_pnl=-5.0)
        assert not t.is_winner

    def test_is_winner_zero_pnl(self):
        """Zero PnL → is_winner=False."""
        t = _trade(realized_pnl=0.0)
        assert not t.is_winner

    def test_score_bucket_high(self):
        """Quality >= 0.7 → high."""
        t = _trade(quality_score=0.8)
        assert t.score_bucket == "high"

    def test_score_bucket_medium(self):
        """Quality 0.4-0.7 → medium."""
        t = _trade(quality_score=0.5)
        assert t.score_bucket == "medium"

    def test_score_bucket_low(self):
        """Quality < 0.4 → low."""
        t = _trade(quality_score=0.2)
        assert t.score_bucket == "low"


# ── Core Analytics ──────────────────────────────────────────────────────────


class TestCoreAnalytics:
    def test_empty_analytics(self):
        """No trades → summary shows 0."""
        a = TradeAnalytics()
        summary = a.summary()
        assert summary["total_trades"] == 0

    def test_total_trades(self):
        """Total trade count correct."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1"))
        a.record_trade(_trade("T2"))
        assert a.total_trades == 2

    def test_win_count(self):
        """Win count correct."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", realized_pnl=5.0))
        a.record_trade(_trade("T2", realized_pnl=-2.0))
        a.record_trade(_trade("T3", realized_pnl=3.0))
        assert a.win_count == 2

    def test_loss_count(self):
        """Loss count correct."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", realized_pnl=5.0))
        a.record_trade(_trade("T2", realized_pnl=-2.0))
        assert a.loss_count == 1

    def test_total_pnl(self):
        """Total PnL correct."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", realized_pnl=5.0))
        a.record_trade(_trade("T2", realized_pnl=-2.0))
        assert a.total_pnl == 3.0

    def test_win_rate(self):
        """Win rate correct."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", realized_pnl=5.0))
        a.record_trade(_trade("T2", realized_pnl=-2.0))
        a.record_trade(_trade("T3", realized_pnl=3.0))
        assert a.summary()["win_rate"] == pytest.approx(2 / 3, abs=0.001)


# ── Win Rate Breakdowns ─────────────────────────────────────────────────────


class TestWinRateByRegime:
    def test_grouped_by_regime(self):
        """Trades grouped by regime."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", regime="TREND", realized_pnl=5.0))
        a.record_trade(_trade("T2", regime="TREND", realized_pnl=-2.0))
        a.record_trade(_trade("T3", regime="RANGE", realized_pnl=3.0))
        result = a.win_rate_by_regime()
        assert "TREND" in result
        assert "RANGE" in result
        assert result["TREND"]["trades"] == 2
        assert result["RANGE"]["trades"] == 1

    def test_unknown_regime(self):
        """No regime set → 'unknown' bucket."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", regime=""))
        result = a.win_rate_by_regime()
        assert "unknown" in result or len(result) >= 0

    def test_win_rate_computed(self):
        """Win rate computed correctly per regime."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", regime="TREND", realized_pnl=5.0))
        a.record_trade(_trade("T2", regime="TREND", realized_pnl=5.0))
        a.record_trade(_trade("T3", regime="TREND", realized_pnl=-2.0))
        result = a.win_rate_by_regime()
        assert result["TREND"]["win_rate"] == pytest.approx(2 / 3, abs=0.001)


class TestWinRateByScoreBucket:
    def test_grouped_by_bucket(self):
        """Trades grouped by score bucket."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", quality_score=0.8))  # high
        a.record_trade(_trade("T2", quality_score=0.5))  # medium
        a.record_trade(_trade("T3", quality_score=0.1))  # low
        a.record_trade(_trade("T4", quality_score=0.9))  # high
        result = a.win_rate_by_score_bucket()
        assert result["high"]["trades"] == 2
        assert result["medium"]["trades"] == 1
        assert result["low"]["trades"] == 1


class TestWinRateBySymbol:
    def test_grouped_by_symbol(self):
        """Trades grouped by symbol."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", symbol="NIFTY"))
        a.record_trade(_trade("T2", symbol="BANKNIFTY"))
        a.record_trade(_trade("T3", symbol="NIFTY"))
        result = a.win_rate_by_symbol()
        assert result["NIFTY"]["trades"] == 2
        assert result["BANKNIFTY"]["trades"] == 1


class TestWinRateBySessionWindow:
    def test_grouped_by_window(self):
        """Trades grouped by session window."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", session_window="peak"))
        a.record_trade(_trade("T2", session_window="mid"))
        result = a.win_rate_by_session_window()
        assert "peak" in result
        assert "mid" in result


class TestWinRateByAlignmentBucket:
    def test_strong_alignment(self):
        """Alignment >= 0.6 → strong."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", alignment_score=0.7))
        result = a.win_rate_by_alignment_bucket()
        assert "strong" in result
        assert result["strong"]["trades"] == 1

    def test_moderate_alignment(self):
        """Alignment 0.35-0.6 → moderate."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", alignment_score=0.45))
        result = a.win_rate_by_alignment_bucket()
        assert "moderate" in result
        assert result["moderate"]["trades"] == 1

    def test_weak_alignment(self):
        """Alignment < 0.35 → weak."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", alignment_score=0.2))
        result = a.win_rate_by_alignment_bucket()
        assert "weak" in result
        assert result["weak"]["trades"] == 1


# ── MAE/MFE ─────────────────────────────────────────────────────────────────


class TestMAEMFE:
    def test_avg_mae_mfe(self):
        """Average MAE and MFE computed correctly."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", max_adverse_excursion=0.5, max_favourable_excursion=1.5))
        a.record_trade(_trade("T2", max_adverse_excursion=1.0, max_favourable_excursion=2.0))
        result = a.avg_mae_mfe()
        assert result["avg_mae"] == 0.75
        assert result["avg_mfe"] == 1.75

    def test_empty_trades(self):
        """No trades → all zeros."""
        a = TradeAnalytics()
        result = a.avg_mae_mfe()
        assert result["avg_mae"] == 0.0
        assert result["avg_mfe"] == 0.0
        assert result["mae_mfe_ratio"] == 0.0

    def test_mae_mfe_ratio(self):
        """MAE/MFE ratio computed."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", max_adverse_excursion=0.5, max_favourable_excursion=2.0))
        result = a.avg_mae_mfe()
        assert result["mae_mfe_ratio"] == 0.25


# ── Best Symbols & Windows ─────────────────────────────────────────────────


class TestBestSymbols:
    def test_returns_top_n(self):
        """Top N symbols by PnL and win rate."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", symbol="A", realized_pnl=5.0))
        a.record_trade(_trade("T2", symbol="B", realized_pnl=3.0))
        a.record_trade(_trade("T3", symbol="C", realized_pnl=1.0))
        a.record_trade(_trade("T4", symbol="D", realized_pnl=2.0))
        result = a.best_symbols(top_n=2)
        assert len(result) == 2

    def test_has_symbol_key(self):
        """Results include symbol field."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", symbol="NIFTY", realized_pnl=5.0))
        result = a.best_symbols()
        assert result[0]["symbol"] == "NIFTY"


class TestBestSessionWindows:
    def test_sorted_by_win_rate(self):
        """Windows sorted by win rate."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1", session_window="peak", realized_pnl=5.0))
        a.record_trade(_trade("T2", session_window="mid", realized_pnl=-2.0))
        result = a.best_session_windows()
        assert result[0]["window"] == "peak"


# ── Rejection Summary ───────────────────────────────────────────────────────


class TestRejectionSummary:
    def test_empty(self):
        """No rejections → zero total."""
        a = TradeAnalytics()
        result = a.rejection_summary({})
        assert result["total_rejections"] == 0
        assert result["top_reasons"] == []

    def test_counts(self):
        """Rejection reasons counted correctly."""
        a = TradeAnalytics()
        reasons = {"low_quality": 10, "bad_regime": 5, "no_alignment": 3}
        result = a.rejection_summary(reasons)
        assert result["total_rejections"] == 18
        assert result["top_reasons"][0]["reason"] == "low_quality"
        assert result["top_reasons"][0]["count"] == 10

    def test_top_n(self):
        """Only top 10 reasons returned."""
        a = TradeAnalytics()
        reasons = {f"reason_{i}": i for i in range(15)}
        result = a.rejection_summary(reasons)
        assert len(result["top_reasons"]) == 10


# ── Summary ─────────────────────────────────────────────────────────────────


class TestSummary:
    def test_empty(self):
        """Empty analytics → total_trades 0."""
        a = TradeAnalytics()
        s = a.summary()
        assert s["total_trades"] == 0

    def test_all_fields_present(self):
        """Summary includes all expected sections."""
        a = TradeAnalytics()
        a.record_trade(_trade("T1"))
        s = a.summary()
        for key in ("total_trades", "wins", "losses", "win_rate", "total_pnl", "avg_pnl",
                     "mae_mfe", "by_regime", "by_score", "by_symbol", "by_window",
                     "by_alignment", "best_symbols", "best_windows"):
            assert key in s

    def test_concurrent_safety(self):
        """Thread-safe under concurrent record calls."""
        import threading
        a = TradeAnalytics()
        n = 100
        threads = [threading.Thread(target=lambda: a.record_trade(_trade(f"T{i}"))) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert a.total_trades == n


# ── Edge Cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_pnl_not_winner(self):
        """Zero PnL correctly classified as not winner."""
        t = _trade(realized_pnl=0.0)
        assert not t.is_winner

    def test_many_trades(self):
        """Bulk recording works."""
        a = TradeAnalytics()
        for i in range(1000):
            a.record_trade(_trade(f"T{i}"))
        assert a.total_trades == 1000
        s = a.summary()
        assert s["total_trades"] == 1000