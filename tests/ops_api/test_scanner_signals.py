"""Scanner signal tests — source field, creation, scanners."""

from __future__ import annotations

from ops_api.models import NormalizedSignal, SignalSide


class TestNormalizedSignalSource:
    def test_default_source_is_webhook(self) -> None:
        sig = NormalizedSignal(symbol="NIFTY", side=SignalSide.BUY, strategy="TEST")
        assert sig.source == "webhook"

    def test_scanner_source(self) -> None:
        sig = NormalizedSignal(
            symbol="NIFTY", side=SignalSide.BUY, strategy="MOMENTUM", source="scanner"
        )
        assert sig.source == "scanner"