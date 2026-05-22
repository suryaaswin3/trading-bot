"""Trade analytics — per-trade tracking, MAE/MFE, win rate breakdowns.

Stores individual trade records and provides aggregation methods for
analysing execution quality across regimes, score buckets, symbols,
and session windows.

Usage::

    analytics = TradeAnalytics()
    analytics.record_trade(TradeRecord(...))
    wr_by_regime = analytics.win_rate_by_regime()
    wr_by_score = analytics.win_rate_by_score_bucket()
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


# ── Trade Record ────────────────────────────────────────────────────────────


@dataclass
class TradeRecord:
    """Immutable record of a single completed trade."""

    trade_id: str
    symbol: str
    side: str                             # "LONG" | "SHORT"
    entry_price: float
    exit_price: float
    quantity: int
    realized_pnl: float
    entry_time: str                       # ISO-8601
    exit_time: str                        # ISO-8601
    hold_bars: int                        # bars held
    strategy: str                         # strategy_id
    session_window: str                   # "peak" | "mid" | "close"

    # Micro-measurements
    max_adverse_excursion: float = 0.0    # max unfavourable move (in ATR units)
    max_favourable_excursion: float = 0.0  # max favourable move (in ATR units)
    entry_atr: float = 0.0                # ATR at entry time

    # Context
    regime: str = ""                      # regime at entry time
    quality_score: float = 0.0            # breakout quality score
    alignment_score: float = 0.0          # MTF alignment score
    rank_score: float = 0.0               # ranking score
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def is_winner(self) -> bool:
        return self.realized_pnl > 0

    @property
    def score_bucket(self) -> str:
        """Bucket quality score into low/medium/high."""
        if self.quality_score >= 0.7:
            return "high"
        elif self.quality_score >= 0.4:
            return "medium"
        return "low"


# ── Analytics ───────────────────────────────────────────────────────────────


@dataclass
class TradeAnalytics:
    """Thread-safe trade analytics accumulator.

    All methods are safe to call from multiple threads.
    """

    _trades: list[TradeRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_trade(self, record: TradeRecord) -> None:
        """Store a completed trade record."""
        with self._lock:
            self._trades.append(record)

    @property
    def total_trades(self) -> int:
        return len(self._trades)

    @property
    def winners(self) -> list[TradeRecord]:
        return [t for t in self._trades if t.is_winner]

    @property
    def losers(self) -> list[TradeRecord]:
        return [t for t in self._trades if not t.is_winner]

    @property
    def win_count(self) -> int:
        return len(self.winners)

    @property
    def loss_count(self) -> int:
        return len(self.losers)

    @property
    def total_pnl(self) -> float:
        return sum(t.realized_pnl for t in self._trades)

    # ── Win Rate Breakdowns ─────────────────────────────────────────────

    def win_rate_by_regime(self) -> dict[str, dict[str, float]]:
        """Win rate grouped by market regime at entry."""
        with self._lock:
            groups: dict[str, list[TradeRecord]] = {}
            for t in self._trades:
                reg = t.regime or "unknown"
                groups.setdefault(reg, []).append(t)

        result: dict[str, dict[str, float]] = {}
        for regime, trades in sorted(groups.items()):
            wins = sum(1 for t in trades if t.is_winner)
            result[regime] = {
                "trades": len(trades),
                "wins": wins,
                "losses": len(trades) - wins,
                "win_rate": round(wins / len(trades), 4) if trades else 0.0,
                "total_pnl": round(sum(t.realized_pnl for t in trades), 2),
            }
        return result

    def win_rate_by_score_bucket(self) -> dict[str, dict[str, float]]:
        """Win rate grouped by quality score bucket."""
        with self._lock:
            groups: dict[str, list[TradeRecord]] = {}
            for t in self._trades:
                bucket = t.score_bucket
                groups.setdefault(bucket, []).append(t)

        result: dict[str, dict[str, float]] = {}
        for bucket, trades in sorted(groups.items()):
            wins = sum(1 for t in trades if t.is_winner)
            result[bucket] = {
                "trades": len(trades),
                "wins": wins,
                "losses": len(trades) - wins,
                "win_rate": round(wins / len(trades), 4) if trades else 0.0,
                "total_pnl": round(sum(t.realized_pnl for t in trades), 2),
            }
        return result

    def win_rate_by_symbol(self) -> dict[str, dict[str, float]]:
        """Win rate grouped by symbol."""
        with self._lock:
            groups: dict[str, list[TradeRecord]] = {}
            for t in self._trades:
                groups.setdefault(t.symbol, []).append(t)

        result: dict[str, dict[str, float]] = {}
        for symbol, trades in sorted(groups.items()):
            wins = sum(1 for t in trades if t.is_winner)
            result[symbol] = {
                "trades": len(trades),
                "wins": wins,
                "losses": len(trades) - wins,
                "win_rate": round(wins / len(trades), 4) if trades else 0.0,
                "total_pnl": round(sum(t.realized_pnl for t in trades), 2),
            }
        return result

    def win_rate_by_session_window(self) -> dict[str, dict[str, float]]:
        """Win rate grouped by session time window."""
        with self._lock:
            groups: dict[str, list[TradeRecord]] = {}
            for t in self._trades:
                groups.setdefault(t.session_window, []).append(t)

        result: dict[str, dict[str, float]] = {}
        for window, trades in sorted(groups.items()):
            wins = sum(1 for t in trades if t.is_winner)
            result[window] = {
                "trades": len(trades),
                "wins": wins,
                "losses": len(trades) - wins,
                "win_rate": round(wins / len(trades), 4) if trades else 0.0,
                "total_pnl": round(sum(t.realized_pnl for t in trades), 2),
            }
        return result

    def win_rate_by_alignment_bucket(self) -> dict[str, dict[str, float]]:
        """Win rate grouped by MTF alignment score."""
        with self._lock:
            groups: dict[str, list[TradeRecord]] = {}
            for t in self._trades:
                if t.alignment_score >= 0.6:
                    bucket = "strong"
                elif t.alignment_score >= 0.35:
                    bucket = "moderate"
                else:
                    bucket = "weak"
                groups.setdefault(bucket, []).append(t)

        result: dict[str, dict[str, float]] = {}
        for bucket, trades in sorted(groups.items()):
            wins = sum(1 for t in trades if t.is_winner)
            result[bucket] = {
                "trades": len(trades),
                "wins": wins,
                "losses": len(trades) - wins,
                "win_rate": round(wins / len(trades), 4) if trades else 0.0,
                "total_pnl": round(sum(t.realized_pnl for t in trades), 2),
            }
        return result

    # ── MAE/MFE ─────────────────────────────────────────────────────────

    def avg_mae_mfe(self) -> dict[str, float]:
        """Average MAE and MFE across all trades (in ATR units)."""
        with self._lock:
            if not self._trades:
                return {"avg_mae": 0.0, "avg_mfe": 0.0, "mae_mfe_ratio": 0.0}

            avg_mae = sum(t.max_adverse_excursion for t in self._trades) / len(self._trades)
            avg_mfe = sum(t.max_favourable_excursion for t in self._trades) / len(self._trades)

        return {
            "avg_mae": round(avg_mae, 4),
            "avg_mfe": round(avg_mfe, 4),
            "mae_mfe_ratio": round(avg_mae / avg_mfe, 4) if avg_mfe > 0 else 0.0,
        }

    def best_symbols(self, top_n: int = 5) -> list[dict[str, Any]]:
        """Top N symbols by total PnL and win rate."""
        by_sym = self.win_rate_by_symbol()
        scored = sorted(
            by_sym.items(),
            key=lambda x: (x[1]["total_pnl"], x[1]["win_rate"]),
            reverse=True,
        )
        return [
            {"symbol": s, **metrics}
            for s, metrics in scored[:top_n]
        ]

    def best_session_windows(self) -> list[dict[str, Any]]:
        """Session windows ranked by win rate."""
        by_window = self.win_rate_by_session_window()
        scored = sorted(
            by_window.items(),
            key=lambda x: (x[1]["win_rate"], x[1]["total_pnl"]),
            reverse=True,
        )
        return [
            {"window": w, **metrics}
            for w, metrics in scored
        ]

    # ── Rejection Analytics ─────────────────────────────────────────────

    def rejection_summary(self, rejection_reasons: dict[str, int]) -> dict[str, Any]:
        """Aggregate rejection analytics from ScanMetrics data.

        Parameters
        ----------
        rejection_reasons:
            Dict mapping rejection reason strings to count, as recorded
            by ScanMetrics.rejection_reasons.

        Returns
        -------
        Dict with total rejections, top reasons, and breakdown.
        """
        total = sum(rejection_reasons.values())
        sorted_reasons = sorted(
            rejection_reasons.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return {
            "total_rejections": total,
            "top_reasons": [
                {"reason": r, "count": c, "pct": round(c / total, 4) if total > 0 else 0.0}
                for r, c in sorted_reasons[:10]
            ],
        }

    def summary(self) -> dict[str, Any]:
        """Overall analytics summary."""
        with self._lock:
            n = len(self._trades)
            if n == 0:
                return {"total_trades": 0}

            wins = self.win_count
            losses = self.loss_count

        result: dict[str, Any] = {
            "total_trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / n, 4) if n > 0 else 0.0,
            "total_pnl": round(self.total_pnl, 2),
            "avg_pnl": round(self.total_pnl / n, 2) if n > 0 else 0.0,
        }
        result["mae_mfe"] = self.avg_mae_mfe()
        result["by_regime"] = self.win_rate_by_regime()
        result["by_score"] = self.win_rate_by_score_bucket()
        result["by_symbol"] = self.win_rate_by_symbol()
        result["by_window"] = self.win_rate_by_session_window()
        result["by_alignment"] = self.win_rate_by_alignment_bucket()
        result["best_symbols"] = self.best_symbols()
        result["best_windows"] = self.best_session_windows()
        return result