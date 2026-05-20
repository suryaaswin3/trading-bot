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
        assert callback.call_count >= 1

    def test_stop_without_start_no_error(self) -> None:
        ScanScheduler(callback_fn=lambda: None).stop()

    def test_double_start_no_error(self) -> None:
        scheduler = ScanScheduler(callback_fn=lambda: None, interval_seconds=60)
        scheduler.start()
        scheduler.start()
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
        assert call_count >= 2

    def test_tick_counter_increments(self) -> None:
        callback = MagicMock()
        s = ScanScheduler(callback_fn=callback, interval_seconds=0.05)
        s.start()
        time.sleep(0.15)
        s.stop()
        assert s.tick_counter >= 2

    def test_error_counter(self) -> None:
        def fail_once() -> None:
            raise RuntimeError("boom")
        s = ScanScheduler(callback_fn=fail_once, interval_seconds=0.05)
        s.start()
        time.sleep(0.12)
        s.stop()
        assert s.error_counter >= 2

    def test_uptime_property(self) -> None:
        callback = MagicMock()
        s = ScanScheduler(callback_fn=callback, interval_seconds=60)
        assert s.uptime == 0.0
        s.start()
        time.sleep(0.1)
        assert s.uptime >= 0.08
        s.stop()

    def test_metrics_snapshot_shape(self) -> None:
        callback = MagicMock()
        s = ScanScheduler(callback_fn=callback, interval_seconds=60)
        snap = s.metrics_snapshot()
        assert "running" in snap and "tick_counter" in snap and "uptime" in snap
        assert not snap["running"]