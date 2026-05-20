"""Momentum scanner — detects price vs EMA crossovers and rate of change."""

from __future__ import annotations

from ops_api.indicators import ema as compute_ema
from ops_api.market_data.base import BarSnapshot
from ops_api.models import NormalizedSignal, SignalSide
from ops_api.scanner.base import BaseScanner, ScannerResult


class MomentumScanner(BaseScanner):
    """Detects momentum signals based on EMA relationships and price action.

    BUY: price > EMA20 > EMA50, price > VWAP, ROC > 0.5%
    SELL: price < EMA20 < EMA50, price < VWAP, ROC < -0.5%
    """

    def __init__(self) -> None:
        super().__init__(strategy_id="MOMENTUM")

    def scan(self, bars: list[BarSnapshot], symbol: str = "", interval: str = "") -> ScannerResult:
        closes = [b.close for b in bars]
        if len(closes) < 50:
            return ScannerResult()

        ema20 = compute_ema([{"close": c} for c in closes], period=20)[-1]
        ema50 = compute_ema([{"close": c} for c in closes], period=50)[-1]
        last_price = closes[-1]

        cum_pv, cum_vol = 0.0, 0.0
        for b in bars:
            tp = (b.high + b.low + b.close) / 3.0
            cum_pv += tp * b.volume; cum_vol += b.volume
        vwap_val = cum_pv / cum_vol if cum_vol > 0 else last_price

        roc_3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0.0

        if last_price > ema20 > ema50 and last_price > vwap_val and roc_3 > 0.5:
            return ScannerResult(signal=NormalizedSignal(
                symbol=symbol.upper(), side=SignalSide.BUY, strategy=self.strategy_id,
                timeframe=interval, price=last_price, source="scanner",
                reason=f"Price({last_price:.1f}) > EMA20({ema20:.1f}) > EMA50({ema50:.1f}), ROC={roc_3:.1f}%"))

        if last_price < ema20 < ema50 and last_price < vwap_val and roc_3 < -0.5:
            return ScannerResult(signal=NormalizedSignal(
                symbol=symbol.upper(), side=SignalSide.SELL, strategy=self.strategy_id,
                timeframe=interval, price=last_price, source="scanner",
                reason=f"Price({last_price:.1f}) < EMA20({ema20:.1f}) < EMA50({ema50:.1f}), ROC={roc_3:.1f}%"))

        return ScannerResult()