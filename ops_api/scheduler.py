"""Scan scheduler — daemon thread that runs the scan loop.

Uses threading.Event for clean shutdown — no polling, no busy-wait.
"""

from __future__ import annotations

import threading
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

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            logger.debug("ScanScheduler already running")
            return
        self._stop_event.clear()
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
            try:
                self._callback()
            except Exception:
                logger.exception("ScanScheduler callback raised an error — continuing")
            self._stop_event.wait(timeout=self._interval)