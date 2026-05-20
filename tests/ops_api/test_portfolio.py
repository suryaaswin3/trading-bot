"""Portfolio and strategy performance tests."""

from __future__ import annotations

import tempfile

import pytest

from ops_api.db import DatabaseManager


@pytest.fixture
def db() -> DatabaseManager:
    tmp = tempfile.mktemp(suffix=".db")
    mgr = DatabaseManager(tmp)
    mgr.init_schema()
    return mgr


class TestStrategyPerformance:
    def test_empty_db_returns_empty_list(self, db: DatabaseManager) -> None:
        assert db.get_strategy_performance() == []

    def test_aggregates_by_strategy(self, db: DatabaseManager) -> None:
        db.insert_order({
            "id": "o1", "signal_id": "s1", "validation_id": "v1",
            "symbol": "NIFTY", "side": "BUY", "quantity": 50, "price": 18100.0,
            "status": "filled", "strategy": "MOMENTUM",
            "dedup_key": "k1", "created_at": "2026-05-20T10:00:00",
            "data_source": "production",
        })
        db.insert_order({
            "id": "o2", "signal_id": "s2", "validation_id": "v2",
            "symbol": "NIFTY", "side": "SELL", "quantity": 50, "price": 18250.0,
            "status": "filled", "strategy": "MOMENTUM",
            "dedup_key": "k2", "created_at": "2026-05-20T11:00:00",
            "data_source": "production",
        })
        perf = db.get_strategy_performance()
        assert len(perf) == 1
        p = perf[0]
        assert p["strategy"] == "MOMENTUM"
        assert p["trade_count"] == 2
        assert p["net_pnl"] > 0
        assert p["buy_count"] == 1
        assert p["sell_count"] == 1

    def test_excludes_non_filled(self, db: DatabaseManager) -> None:
        db.insert_order({
            "id": "o3", "signal_id": "s3", "validation_id": "v3",
            "symbol": "NIFTY", "side": "BUY", "quantity": 50, "price": 18100.0,
            "status": "rejected", "strategy": "MOMENTUM",
            "dedup_key": "k3", "created_at": "2026-05-20T10:00:00",
            "data_source": "production",
        })
        assert db.get_strategy_performance() == []


class TestCurrentPositions:
    def test_empty_db_returns_empty_list(self, db: DatabaseManager) -> None:
        assert db.get_current_positions() == []

    def test_latest_per_symbol(self, db: DatabaseManager) -> None:
        db.insert_position_snapshot({
            "id": "p1", "symbol": "NIFTY", "side": "LONG",
            "quantity": 50, "entry_price": 18100, "current_price": 18200,
            "unrealized_pnl": 5000.0, "realized_pnl": 0.0,
            "trades_today": 1, "daily_pnl": 5000.0, "timestamp": "2026-05-20T10:00:00",
        })
        db.insert_position_snapshot({
            "id": "p2", "symbol": "NIFTY", "side": "NONE",
            "quantity": 0, "entry_price": 0, "current_price": 0,
            "unrealized_pnl": 0.0, "realized_pnl": 5000.0,
            "trades_today": 1, "daily_pnl": 5000.0, "timestamp": "2026-05-20T11:00:00",
        })
        positions = db.get_current_positions()
        assert len(positions) == 0  # latest has qty=0

    def test_multiple_symbols(self, db: DatabaseManager) -> None:
        db.insert_position_snapshot({
            "id": "p3", "symbol": "NIFTY", "side": "LONG",
            "quantity": 50, "entry_price": 18100, "current_price": 18200,
            "unrealized_pnl": 5000.0, "realized_pnl": 0.0,
            "trades_today": 1, "daily_pnl": 5000.0, "timestamp": "2026-05-20T10:00:00",
        })
        db.insert_position_snapshot({
            "id": "p4", "symbol": "BANKNIFTY", "side": "LONG",
            "quantity": 25, "entry_price": 42000, "current_price": 42200,
            "unrealized_pnl": 5000.0, "realized_pnl": 0.0,
            "trades_today": 1, "daily_pnl": 5000.0, "timestamp": "2026-05-20T10:00:00",
        })
        assert len(db.get_current_positions()) == 2


class TestPortfolioSummary:
    def test_exposure_calculation(self, db: DatabaseManager) -> None:
        db.insert_position_snapshot({
            "id": "p5", "symbol": "NIFTY", "side": "LONG",
            "quantity": 50, "entry_price": 18100, "current_price": 18200,
            "unrealized_pnl": 5000.0, "realized_pnl": 0.0,
            "trades_today": 1, "daily_pnl": 5000.0, "timestamp": "2026-05-20T10:00:00",
        })
        summary = db.get_portfolio_summary()
        assert summary["total_exposure"] == 50 * 18200
        assert summary["total_unrealized_pnl"] == 5000.0
        assert summary["position_count"] == 1

    def test_empty_db_returns_defaults(self, db: DatabaseManager) -> None:
        summary = db.get_portfolio_summary()
        assert summary["positions"] == []
        assert summary["total_exposure"] == 0.0
        assert summary["position_count"] == 0