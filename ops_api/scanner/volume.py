"""Volume scanner — detects relative volume spikes vs 20-period average."""

from __future__ import annotations

from ops_api.market_data.base import BarSnapshot
from ops_api.models import NormalizedSignal, SignalSide
from ops_api.scanner.base import BaseScanner, ScannerResult


class VolumeScanner(BaseScanner):
    """Detects unusual volume activity. Requires 2.5x avg volume + price direction."""

    def __init__(self) -> None:
        super().__init__(strategy_id="RELATIVE_VOLUME")

    def scan(self, bars: list[BarSnapshot], symbol: str = "", interval: str = "") -> ScannerResult:
        if len(bars) < 21:
            return ScannerResult()

        volumes = [b.volume for b in bars]
        closes = [b.close for b in bars]
        current_vol = volumes[-1]
        avg_vol = sum(volumes[-21:-1]) / 20.0

        if avg_vol <= 0 or current_vol / avg_vol < 2.5:
            return ScannerResult()

        price_change = closes[-1] - closes[-4] if len(closes) >= 4 else closes[-1] - closes[-2]

        if price_change > 0:
            return ScannerResult(signal=NormalizedSignal(
                symbol=symbol.upper(), side=SignalSide.BUY, strategy=self.strategy_id,
                timeframe=interval, price=closes[-1], source="scanner",
                reason=f"Volume spike: {current_vol/avg_vol:.1f}x avg ({current_vol:.0f} vs {avg_vol:.0f})"))

        if price_change < 0:
            return ScannerResult(signal=NormalizedSignal(
                symbol=symbol.upper(), side=SignalSide.SELL, strategy=self.strategy_id,
                timeframe=interval, price=closes[-1], source="scanner",
                reason=f"Volume spike: {current_vol/avg_vol:.1f}x avg ({current_vol:.0f} vs {avg_vol:.0f})"))

        return ScannerResult()