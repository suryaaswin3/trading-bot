"""Per-process scanner telemetry. Thread-safe, resets on restart."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class ScanMetrics:
    total_scans: int = 0
    signals_found: int = 0
    signals_accepted: int = 0
    signals_rejected: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    regime_classifications: dict[str, int] = field(default_factory=dict)
    regime_rejected: int = 0
    confirmation_accepted: int = 0
    confirmation_rejected: int = 0
    confirmation_reasons: dict[str, int] = field(default_factory=dict)
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

    def record_regime(self, regime: str, breakout_allowed: bool) -> None:
        with self._lock:
            self.regime_classifications[regime] = self.regime_classifications.get(regime, 0) + 1
            if not breakout_allowed:
                self.regime_rejected += 1

    def record_confirmation(self, accepted: bool, reason: str) -> None:
        with self._lock:
            if accepted:
                self.confirmation_accepted += 1
            else:
                self.confirmation_rejected += 1
                self.confirmation_reasons[reason] = self.confirmation_reasons.get(reason, 0) + 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def record_quality(self, accepted: bool, reason: str) -> None:
        with self._lock:
            if accepted:
                self.signals_accepted += 1
            else:
                self.signals_rejected += 1
                self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1

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
                "signals_accepted": self.signals_accepted,
                "signals_rejected": self.signals_rejected,
                "rejection_reasons": dict(self.rejection_reasons),
                "regime_classifications": dict(self.regime_classifications),
                "regime_rejected": self.regime_rejected,
                "confirmation_accepted": self.confirmation_accepted,
                "confirmation_rejected": self.confirmation_rejected,
                "confirmation_reasons": dict(self.confirmation_reasons),
                "scanner_hits": dict(self.scanner_hits),
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_hit_rate": round(self.cache_hit_rate, 4),
                "last_scan_duration": round(self.last_scan_duration, 4),
                "avg_scan_duration": round(self.avg_scan_duration, 4),
            }