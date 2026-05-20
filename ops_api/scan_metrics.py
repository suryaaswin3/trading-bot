"""Per-process scanner telemetry. Thread-safe, resets on restart."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class ScanMetrics:
    total_scans: int = 0
    signals_found: int = 0
    scanner_hits: dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0
    cache_misses: int = 0
    last_scan_duration: float = 0.0
    total_scan_duration: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _scan_start: float = 0.0

    def record_scan_start(self) -> None:
        self._scan_start = time.monotonic()

    def record_scan_end(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._scan_start
            self.total_scans += 1
            self.last_scan_duration = elapsed
            self.total_scan_duration += elapsed

    def record_signal(self, scanner_id: str) -> None:
        with self._lock:
            self.signals_found += 1
            self.scanner_hits[scanner_id] = self.scanner_hits.get(scanner_id, 0) + 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self.cache_misses += 1

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0

    @property
    def avg_scan_duration(self) -> float:
        return self.total_scan_duration / self.total_scans if self.total_scans else 0.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_scans": self.total_scans,
                "signals_found": self.signals_found,
                "scanner_hits": dict(self.scanner_hits),
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_hit_rate": round(self.cache_hit_rate, 4),
                "last_scan_duration": round(self.last_scan_duration, 4),
                "avg_scan_duration": round(self.avg_scan_duration, 4),
            }