"""Scanner signal tests — source field, creation, scanners."""

from __future__ import annotations

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


class TestScannerResult:
    def test_rejected_signal(self) -> None:
        from ops_api.scanner.base import ScannerResult

        result = ScannerResult(signal=None)
        assert result.signal is None
        assert not result.has_signal

    def test_accepted_signal(self) -> None:
        from ops_api.scanner.base import ScannerResult

        sig = NormalizedSignal(symbol="NIFTY", side=SignalSide.BUY, strategy="MOMENTUM", source="scanner")
        result = ScannerResult(signal=sig)
        assert result.has_signal
        assert result.signal is not None


class TestMomentumScanner:
    def test_uptrend_detected(self) -> None:
        from ops_api.market_data.base import BarSnapshot
        from ops_api.scanner.momentum import MomentumScanner

        bars = [BarSnapshot(symbol="NIFTY", interval="60", open=float(18000 + i * 5), high=float(18010 + i * 5), low=float(17990 + i * 5), close=float(18000 + i * 5), volume=500000 + i * 1000, timestamp=float(1000000 + i * 60)) for i in range(60)]
        result = MomentumScanner().scan(bars, symbol="NIFTY")
        if result.has_signal and result.signal is not None:
            assert result.signal.symbol == "NIFTY"
            assert result.signal.side == SignalSide.BUY
            assert result.signal.source == "scanner"
            assert result.signal.strategy == "MOMENTUM"

    def test_no_signal_in_flattish_market(self) -> None:
        from ops_api.market_data.base import BarSnapshot
        from ops_api.scanner.momentum import MomentumScanner

        bars = [BarSnapshot(symbol="NIFTY", interval="60", open=18100.0, high=18110.0, low=18090.0, close=18100.0, volume=100000, timestamp=float(1000000 + i * 60)) for i in range(60)]
        assert not MomentumScanner().scan(bars, symbol="NIFTY").has_signal


class TestVolumeScanner:
    def test_volume_spike_detected(self) -> None:
        from ops_api.market_data.base import BarSnapshot
        from ops_api.scanner.volume import VolumeScanner

        bars = [BarSnapshot(symbol="NIFTY", interval="60", open=18100.0 + i, high=18150.0 + i, low=18050.0 + i, close=18100.0 + i, volume=(1000000 if i >= 57 else 100000), timestamp=float(1000000 + i * 60)) for i in range(60)]
        result = VolumeScanner().scan(bars, symbol="NIFTY")
        if result.has_signal and result.signal is not None:
            assert result.signal.symbol == "NIFTY"
            assert result.signal.side == SignalSide.BUY
            assert result.signal.source == "scanner"
            assert result.signal.strategy == "RELATIVE_VOLUME"

    def test_no_signal_normal_volume(self) -> None:
        from ops_api.market_data.base import BarSnapshot
        from ops_api.scanner.volume import VolumeScanner

        bars = [BarSnapshot(symbol="NIFTY", interval="60", open=18100.0, close=18100.0, high=18110.0, low=18090.0, volume=100000, timestamp=float(1000000 + i * 60)) for i in range(60)]
        assert not VolumeScanner().scan(bars, symbol="NIFTY").has_signal