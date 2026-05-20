"""Scan scheduler — daemon thread that runs the scan loop.

Uses threading.Event for clean shutdown — no polling, no busy-wait.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from loguru import logger


class ScanScheduler:
    """Daemon thread that calls callback_fn on a fixed interval.

    Start with start(), stop with stop(). The thread is a daemon
    so it won't block process exit.
    """

    def __init__(self, callback_fn: Callable[[], None], interval_seconds: int = 60, name: str = "scan-scheduler") -> None:
        self._callback = callback_fn
        self._interval = interval_seconds
        self._name = name
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.tick_counter: int = 0
        self.error_counter: int = 0
        self.last_tick_duration: float = 0.0
        self.min_tick_duration: float = float("inf")
        self.max_tick_duration: float = 0.0
        self.total_tick_duration: float = 0.0
        self.start_timestamp: float = 0.0
        self.last_tick_timestamp: float = 0.0
        self.missed_ticks: int = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def uptime(self) -> float:
        if self.start_timestamp == 0:
            return 0.0
        return time.monotonic() - self.start_timestamp

    @property
    def avg_tick_duration(self) -> float:
        if self.tick_counter == 0:
            return 0.0
        return self.total_tick_duration / self.tick_counter

    def metrics_snapshot(self) -> dict:
        return {
            "running": self.running,
            "tick_counter": self.tick_counter,
            "error_counter": self.error_counter,
            "last_tick_duration": round(self.last_tick_duration, 4),
            "min_tick_duration": round(self.min_tick_duration if self.min_tick_duration != float("inf") else 0.0, 4),
            "max_tick_duration": round(self.max_tick_duration, 4),
            "avg_tick_duration": round(self.avg_tick_duration, 4),
            "uptime": round(self.uptime, 2),
            "missed_ticks": self.missed_ticks,
        }

    def start(self) -> None:
        if self.running:
            logger.debug("ScanScheduler already running")
            return
        self._stop_event.clear()
        self.start_timestamp = time.monotonic()
        self._thread = threading.Thread(target=self._run_loop, name=self._name, daemon=True)
        self._thread.start()
        logger.info("ScanScheduler started (interval={}s)", self._interval)

    def stop(self) -> None:
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
        logger.debug("ScanScheduler loop started")
        while not self._stop_event.is_set():
            tick_start = time.monotonic()
            try:
                self._callback()
            except Exception:
                self.error_counter += 1
                logger.exception("ScanScheduler callback raised an error — continuing")
            elapsed = time.monotonic() - tick_start
            self.tick_counter += 1
            self.last_tick_duration = elapsed
            self.total_tick_duration += elapsed
            self.last_tick_timestamp = tick_start
            if elapsed < self.min_tick_duration:
                self.min_tick_duration = elapsed
            if elapsed > self.max_tick_duration:
                self.max_tick_duration = elapsed
            self._stop_event.wait(timeout=self._interval)