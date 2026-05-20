"""ScanMetrics tests — thread safety, counters, snapshot."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from ops_api.scan_metrics import ScanMetrics


class TestScanMetrics:
    def test_initial_state(self) -> None:
        m = ScanMetrics()
        snap = m.snapshot()
        assert snap["total_scans"] == 0
        assert snap["signals_found"] == 0
        assert snap["cache_hit_rate"] == 0.0

    def test_record_scan(self) -> None:
        m = ScanMetrics()
        with patch("time.monotonic", side_effect=[100.0, 101.0]):
            m.record_scan_start()
            m.record_scan_end()
        snap = m.snapshot()
        assert snap["total_scans"] == 1
        assert snap["last_scan_duration"] == 1.0

    def test_record_signal(self) -> None:
        m = ScanMetrics()
        m.record_signal("MOMENTUM")
        m.record_signal("RELATIVE_VOLUME")
        m.record_signal("MOMENTUM")
        snap = m.snapshot()
        assert snap["signals_found"] == 3
        assert snap["scanner_hits"] == {"MOMENTUM": 2, "RELATIVE_VOLUME": 1}

    def test_cache_hit_rate(self) -> None:
        m = ScanMetrics()
        m.record_cache_hit()
        m.record_cache_miss()
        assert m.cache_hit_rate == 0.5

    def test_avg_duration(self) -> None:
        m = ScanMetrics()
        with patch("time.monotonic", side_effect=[100.0, 102.0, 103.0, 105.0]):
            m.record_scan_start(); m.record_scan_end()
            m.record_scan_start(); m.record_scan_end()
        assert m.avg_scan_duration == 2.0

    def test_thread_safety(self) -> None:
        m = ScanMetrics()
        errors: list[Exception] = []
        def worker() -> None:
            try:
                for _ in range(100):
                    m.record_cache_hit()
                    m.record_signal("TEST")
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        snap = m.snapshot()
        assert snap["cache_hits"] == 400
        assert snap["scanner_hits"]["TEST"] == 400