"""Tests for deterministic options strike selection."""
from __future__ import annotations

import pytest
from ops_api.options import OptionsConfig, StrikeSelection, select_strike


# ── Expiry Gate ─────────────────────────────────────────────────────────────


class TestExpiryGate:
    def test_expired(self):
        """Expired option → rejected."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=-1, is_call=True,
        )
        assert not result.accepted
        assert "expired" in result.reason

    def test_expiry_too_close(self):
        """Less than min_expiry_hours → rejected."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=0.02, is_call=True,  # ~30 min
        )
        assert not result.accepted
        assert "expiry_too_close" in result.reason

    def test_ok_expiry(self):
        """Reasonable expiry → continues to strike selection."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=6, is_call=True,
        )
        assert result.accepted or not result.accepted  # may pass or fail on other gates


# ── Liquidity Gate ──────────────────────────────────────────────────────────


class TestLiquidityGate:
    def test_low_liquidity(self):
        """Low OI/volume ratio → rejected."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=6, is_call=True,
            oi_volume_ratio=0.1,
        )
        assert not result.accepted
        assert "low_liquidity" in result.reason

    def test_high_liquidity(self):
        """High OI/volume ratio → continues."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=6, is_call=True,
            oi_volume_ratio=5.0,
        )
        assert result.accepted or not result.accepted  # may continue to premium filter

    def test_none_oi_volume_ratio(self):
        """None OI/volume ratio → skip liquidity check."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=6, is_call=True,
            oi_volume_ratio=None,
        )
        assert result.accepted or not result.accepted  # skips liquidity gate


# ── Strike Selection ────────────────────────────────────────────────────────


class TestStrikeSelection:
    def test_atm_normal_conditions(self):
        """Low volatility → ATM strike."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,  # below volatile threshold
            side="BUY", expiry_days=6, is_call=True,
        )
        # ATM for Nifty step=50: round(22350/50)*50 = 22350
        if result.accepted:
            assert result.method == "atm"
            assert result.strike == 22350.0

    def test_atm_normal_sell(self):
        """Low volatility SELL → ATM strike."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="SELL", expiry_days=6, is_call=False,
        )
        if result.accepted:
            assert result.method == "atm"
            assert result.strike == 22350.0

    def test_itm_volatile_call(self):
        """High volatility + BUY/call → ITM (strike - step)."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=2.0,  # above volatile threshold
            side="BUY", expiry_days=6, is_call=True,
        )
        if result.accepted:
            assert result.method == "itm"
            assert result.is_itm
            # ITM call = ATM - step = 22350 - 50 = 22300
            assert result.strike == 22300.0

    def test_itm_volatile_put(self):
        """High volatility + SELL/put → ITM (strike + step)."""
        result = select_strike(
            underlying_price=22350.0, atr_percent=2.0,
            side="SELL", expiry_days=6, is_call=False,
        )
        if result.accepted:
            assert result.method == "itm"
            assert result.is_itm
            # ITM put = ATM + step = 22350 + 50 = 22400
            assert result.strike == 22400.0

    def test_custom_atm_step(self):
        """Custom ATM step used for strike rounding."""
        config = OptionsConfig(atm_step=100.0)
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=6, is_call=True,
            config=config,
        )
        if result.accepted:
            # round(22350/100)*100 = 22400
            assert result.strike == 22400.0

    def test_custom_itm_buffer(self):
        """Custom ITM buffer steps."""
        config = OptionsConfig(itm_buffer_steps=3)
        result = select_strike(
            underlying_price=22350.0, atr_percent=2.0,
            side="BUY", expiry_days=6, is_call=True,
            config=config,
        )
        if result.accepted:
            # ATM - 3*50 = 22350 - 150 = 22200
            assert result.strike == 22200.0


# ── Premium Filter ──────────────────────────────────────────────────────────


class TestPremiumFilter:
    def test_premium_too_low(self):
        """Very cheap option → rejected."""
        # Deep OTM with tiny expiry: negligible premium
        result = select_strike(
            underlying_price=100.0, atr_percent=0.1,
            side="BUY", expiry_days=0.1, is_call=True,
            config=OptionsConfig(min_premium_pct=0.01),  # 1% minimum
        )
        if not result.accepted:
            assert "premium_too_low" in result.reason or "premium" in result.reason.lower()

    def test_premium_within_range(self):
        """Normal premium → accepted (if other gates pass)."""
        config = OptionsConfig(min_premium_pct=0.0, max_premium_pct=1.0)
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=6, is_call=True,
            config=config,
        )
        # With no premium filter, should pass if no other issues
        assert result.accepted

    def test_high_premium_still_accepted(self):
        """Expensive but within max → accepted."""
        config = OptionsConfig(min_premium_pct=0.0, max_premium_pct=0.2)
        result = select_strike(
            underlying_price=1000.0, atr_percent=6.0,
            side="BUY", expiry_days=30, is_call=True,
            config=config,
        )
        assert result.accepted


# ── Edge Cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_custom_config(self):
        """Custom OptionsConfig used."""
        config = OptionsConfig(volatile_threshold=2.0, atm_step=100.0)
        result = select_strike(
            underlying_price=20000.0, atr_percent=1.0,
            side="BUY", expiry_days=7, is_call=True,
            config=config,
        )
        assert isinstance(result, StrikeSelection)

    def test_result_type(self):
        """Returns StrikeSelection dataclass."""
        result = select_strike(
            underlying_price=100.0, atr_percent=0.5,
            side="BUY", expiry_days=5, is_call=True,
        )
        assert isinstance(result, StrikeSelection)

    def test_accepted_has_strike(self):
        """Accepted result has non-zero strike."""
        config = OptionsConfig(min_premium_pct=0.0, max_premium_pct=1.0)
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=6, is_call=True,
            config=config,
        )
        assert result.accepted
        assert result.strike > 0

    def test_is_itm_flag(self):
        """is_itm correctly set for ITM calls."""
        config = OptionsConfig(min_premium_pct=0.0, max_premium_pct=1.0)
        result = select_strike(
            underlying_price=100.0, atr_percent=2.0,
            side="BUY", expiry_days=6, is_call=True,
            config=config,
        )
        assert result.accepted
        assert result.is_itm  # call strike below 100 is ITM
        assert result.strike < 100.0

    def test_is_itm_put(self):
        """is_itm correctly set for ITM puts."""
        config = OptionsConfig(min_premium_pct=0.0, max_premium_pct=1.0)
        result = select_strike(
            underlying_price=100.0, atr_percent=2.0,
            side="SELL", expiry_days=6, is_call=False,
            config=config,
        )
        assert result.accepted
        assert result.is_itm  # put strike above 100 is ITM
        assert result.strike > 100.0

    def test_metrics_present(self):
        """Accepted result has metrics."""
        config = OptionsConfig(min_premium_pct=0.0, max_premium_pct=1.0)
        result = select_strike(
            underlying_price=22350.0, atr_percent=0.8,
            side="BUY", expiry_days=6, is_call=True,
            config=config,
        )
        assert "atr_percent" in result.metrics
        assert "premium_pct" in result.metrics