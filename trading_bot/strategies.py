"""Strategy implementations: VWAP pullback, ORB breakout, market condition filter."""

from __future__ import annotations

from datetime import datetime, time

import pytz

from trading_bot.config import TradingBotConfig
from trading_bot.data import Candle, compute_ema, compute_ema_slope

_IST = pytz.timezone("Asia/Kolkata")


# ========================
# CANDLE HELPERS
# ========================
def _candle_has_body(candle: Candle, min_body_ratio: float) -> bool:
    body = abs(candle.close - candle.open)
    range_ = candle.high - candle.low

    if range_ == 0:
        return False

    return body / range_ >= min_body_ratio


def _close_near_high(candle: Candle, threshold: float = 0.33) -> bool:
    range_ = candle.high - candle.low

    if range_ == 0:
        return True

    return candle.close >= candle.high - range_ * threshold


def _close_near_low(candle: Candle, threshold: float = 0.33) -> bool:
    range_ = candle.high - candle.low

    if range_ == 0:
        return True

    return candle.close <= candle.low + range_ * threshold


# ========================
# STRATEGY SELECTOR
# ========================
def select_strategy(
    current_time: datetime | None = None,
    config: TradingBotConfig = TradingBotConfig(),
) -> str | None:
    """Return strategy name based on current time window.

    - **Market open to pullback start** (9:15 - 11:31): returns ``"ORB"``.
    - **Pullback window** (11:31 - 14:30): returns ``"VWAP_PULLBACK"``.
    - **After hours** (14:30+): returns ``None``.
    """
    if current_time is None:
        current_time = datetime.now(_IST)

    t = current_time.time()

    market_open = time(9, 15)
    pullback_start = time(
        config.vwap_pullback_start_hour, config.vwap_pullback_start_minute
    )
    pullback_end = time(config.vwap_pullback_end_hour, config.vwap_pullback_end_minute)

    if pullback_start <= t <= pullback_end:
        return "VWAP_PULLBACK"

    if market_open <= t < pullback_start:
        return "ORB"

    return None


# ========================
# EMA FILTER
# ========================
def _ema_filter(
    candles: list[Candle],
    config: TradingBotConfig,
) -> tuple[bool, str, float]:
    """Enhanced EMA filter: bull/bear regime + slope + sideways detection.

    Returns
        ``(is_valid, regime, slope)``

    - *is_valid*: ``True`` when enough candles exist for both EMAs.
    - *regime*: ``"BULLISH"``, ``"BEARISH"``, or ``"SIDEWAYS"``.
    - *slope*: EMA slope in pts/period.
    """
    if len(candles) < config.ema_slow_period:
        return False, "SIDEWAYS", 0.0

    closes = [c.close for c in candles]

    ema_fast = compute_ema(closes, config.ema_fast_period)
    ema_slow = compute_ema(closes, config.ema_slow_period)
    slope = compute_ema_slope(closes, config.ema_fast_period, config.ema_slope_lookback)

    if ema_fast is None or ema_slow is None:
        return False, "SIDEWAYS", 0.0

    if slope is not None and abs(slope) <= config.ema_slope_threshold:
        return True, "SIDEWAYS", slope

    if ema_fast > ema_slow:
        return True, "BULLISH", slope or 0.0

    return True, "BEARISH", slope or 0.0


# ========================
# VWAP PULLBACK STRATEGY
# ========================
def vwap_pullback_signal(
    candles: list[Candle],
    vwap: float | None,
    config: TradingBotConfig,
) -> str:
    """VWAP pullback signal with config-driven parameters and improved filters.

    Returns ``"TRADE_CALL"``, ``"TRADE_PUT"``, ``"WAIT"``, or ``"NO_TRADE"``.
    """
    if not candles or vwap is None:
        return "NO_TRADE"

    if len(candles) < 3:
        return "WAIT"

    is_valid, regime, _slope = _ema_filter(candles, config)

    if not is_valid:
        return "WAIT"

    # Skip in sideways regime — no directional conviction
    if regime == "SIDEWAYS":
        return "NO_TRADE"

    # Skip if price is too extended from VWAP (chasing)
    latest_close = candles[-1].close
    extended_pct = abs(latest_close - vwap) / vwap * 100
    if extended_pct > config.vwap_max_extended_pct:
        return "NO_TRADE"

    lookback = min(config.vwap_lookback_candles, len(candles) - 1)
    recent = candles[-(lookback + 1) : -1]
    latest = candles[-1]

    # Candle strength check
    if not _candle_has_body(latest, config.min_body_ratio):
        return "WAIT"

    all_above = all(c.low > vwap for c in recent)
    all_below = all(c.high < vwap for c in recent)

    # ---- LONG (bullish) ----
    ema_bullish = regime == "BULLISH"

    if ema_bullish and all_above:
        touches_vwap = abs(
            latest.low - vwap
        ) <= config.vwap_pullback_distance_ticks or (latest.low <= vwap <= latest.high)

        if (
            touches_vwap
            and latest.close > vwap
            and _close_near_high(latest, config.close_position_ratio)
        ):
            return "TRADE_CALL"

    # ---- SHORT (bearish) ----
    if not ema_bullish and all_below:
        touches_vwap = abs(
            latest.high - vwap
        ) <= config.vwap_pullback_distance_ticks or (latest.low <= vwap <= latest.high)

        if (
            touches_vwap
            and latest.close < vwap
            and _close_near_low(latest, config.close_position_ratio)
        ):
            return "TRADE_PUT"

    # Conflict: candles are on one side of VWAP but EMA says opposite
    if (all_above and not ema_bullish) or (all_below and ema_bullish):
        return "NO_TRADE"

    return "WAIT"


# ========================
# ORB BREAKOUT STRATEGY
# ========================
def orb_breakout_signal(
    candles: list[Candle],
    current_price: float,
    config: TradingBotConfig,
    orb_high: float | None,
    orb_low: float | None,
) -> str:
    """ORB breakout signal.

    Returns ``"TRADE_CALL"`` (breakout above ORB high), ``"TRADE_PUT"``
    (breakout below ORB low), ``"WAIT"`` (inside range), or
    ``"NO_TRADE"`` (invalid data / filters failed).

    Filters
    1. Volatility: skip if ORB range < ``orb_min_range``.
    2. Volume confirmation: skip if ORB candle volume < threshold × avg volume.
    3. Fake breakout: require close beyond level, not just a wick.
    """
    if orb_high is None or orb_low is None:
        return "NO_TRADE"

    orb_range = orb_high - orb_low
    if config.orb_min_range > 0 and orb_range < config.orb_min_range:
        return "NO_TRADE"

    # Volume confirmation
    if config.orb_volume_threshold > 0 and len(candles) >= 1:
        orb_candle = candles[0]
        avg_vol = sum(c.volume for c in candles) / max(len(candles), 1)
        if orb_candle.volume < config.orb_volume_threshold * avg_vol:
            return "NO_TRADE"

    latest = candles[-1] if candles else None
    if latest is None:
        return "NO_TRADE"

    # Breakout above ORB high — require close above, not just wick
    if current_price > orb_high + config.orb_breakout_buffer_ticks:
        if latest.close > orb_high + config.orb_breakout_buffer_ticks:
            return "TRADE_CALL"
        return "WAIT"  # wick-only breakout, fake

    # Breakout below ORB low — require close below, not just wick
    if current_price < orb_low - config.orb_breakout_buffer_ticks:
        if latest.close < orb_low - config.orb_breakout_buffer_ticks:
            return "TRADE_PUT"
        return "WAIT"  # wick-only breakdown, fake

    return "WAIT"


# ========================
# MARKET CONDITION FILTER
# ========================
def market_condition_filter(
    candles: list[Candle],
    config: TradingBotConfig,
) -> str:
    """Determine market condition for strategy selection.

    Returns ``"TRENDING"``, ``"RANGING"``, or ``"LOW_VOL"``.

    Uses EMA slope to detect trending vs ranging, ATR to detect low volatility.
    Delegates to ``trading_bot.data.detect_market_regime``.
    """
    from trading_bot.data import detect_market_regime as _detect

    return _detect(
        candles,
        ema_slope_threshold=config.market_ema_slope_threshold,
        atr_threshold=config.market_atr_low_threshold,
        ema_fast_period=config.ema_fast_period,
        ema_slow_period=config.ema_slow_period,
    )


__all__ = [
    "market_condition_filter",
    "orb_breakout_signal",
    "select_strategy",
    "vwap_pullback_signal",
]
