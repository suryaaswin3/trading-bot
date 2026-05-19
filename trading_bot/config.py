"""Trading bot configuration — simple dataclass, no framework deps."""

from __future__ import annotations

from dataclasses import Field, dataclass, fields
from typing import Any


def _parse_field(raw: str, field: Field[Any]) -> Any:
    """Parse a raw env string to the dataclass field's type.

    With ``from __future__ import annotations``, ``field.type`` is a string
    like ``"bool"`` rather than the ``bool`` class, so we compare against
    string names.
    """
    type_name = field.type if isinstance(field.type, str) else field.type.__name__
    if type_name == "bool":
        return raw.strip().lower() in ("1", "true", "yes")
    if type_name == "int":
        return int(raw)
    if type_name == "float":
        return float(raw)
    return raw


@dataclass(frozen=True)
class TradingBotConfig:
    """Flat config for the trading bot.

    All parameters live here — no hardcoded values in strategy or data modules.
    """

    # ── Safety ────────────────────────────────────────────────────────
    paper_mode: bool = True
    """True = simulated trades only."""

    debug_mode: bool = False
    """True = verbose logging of indicator values at each poll cycle."""

    # ── Zerodha API ───────────────────────────────────────────────────
    kite_api_key: str = ""
    kite_access_token: str = ""
    nifty_token: int = 256265

    # ── Trading limits ────────────────────────────────────────────────
    max_trades_per_day: int = 2
    cooldown_minutes: int = 30
    max_daily_loss: float = 5_000.0

    # ── Position sizing ───────────────────────────────────────────────
    position_size_lots: int = 1
    max_premium_per_trade: float = 15_000.0

    # ── Instrument constants ──────────────────────────────────────────
    nifty_symbol: str = "NIFTY"
    banknifty_symbol: str = "BANKNIFTY"
    nfo_exchange: str = "NFO"
    product: str = "MIS"
    variety: str = "regular"

    nifty_strike_interval: int = 50
    banknifty_strike_interval: int = 100
    nifty_lot_size: int = 50
    banknifty_lot_size: int = 25

    # ── VWAP Pullback ─────────────────────────────────────────────────
    vwap_pullback_distance_ticks: float = 0.3
    vwap_lookback_candles: int = 10
    vwap_max_extended_pct: float = 0.5
    """Skip trade if latest close is more than this % from VWAP."""

    vwap_pullback_start_hour: int = 11
    vwap_pullback_start_minute: int = 31
    vwap_pullback_end_hour: int = 14
    vwap_pullback_end_minute: int = 30

    # ── EMA filter ────────────────────────────────────────────────────
    ema_fast_period: int = 20
    ema_slow_period: int = 50
    ema_slope_threshold: float = 2.0
    """EMA slope (pts/period) below this is considered SIDEWAYS."""

    ema_slope_lookback: int = 3
    """Number of periods to compute EMA slope over."""

    # ── Candle strength ───────────────────────────────────────────────
    min_body_ratio: float = 0.3
    """Minimum body-to-range ratio for a candle to have a real body."""

    close_position_ratio: float = 0.33
    """Threshold for close-near-high / close-near-low checks."""

    # ── ORB (Opening Range Breakout) ──────────────────────────────────
    orb_breakout_buffer_ticks: float = 0.5
    orb_min_range: float = 0.0
    """Minimum ORB range in points; 0 = disabled."""

    orb_volume_threshold: float = 0.0
    """Minimum volume as fraction of average volume; 0 = disabled."""

    # ── Market condition ──────────────────────────────────────────────
    market_atr_period: int = 14
    market_atr_low_threshold: float = 50.0
    """ATR below this threshold means LOW_VOL regime."""

    market_ema_slope_threshold: float = 5.0
    """EMA slope above this threshold means TRENDING regime."""

    # ── Stop loss / target ────────────────────────────────────────────
    stop_loss_pct: float = 30.0
    target_multiplier: float = 2.0

    # ── Risk management ───────────────────────────────────────────────
    max_consecutive_losses: int = 3
    """Circuit breaker: stop trading after N consecutive losing trades."""

    # ── Data ──────────────────────────────────────────────────────────
    candle_interval_minutes: int = 5
    max_candle_buffer: int = 200
    data_stale_threshold_seconds: float = 5.0

    # ── Order execution ───────────────────────────────────────────────
    limit_order_buffer_ticks_nifty: float = 2.0
    limit_order_buffer_ticks_banknifty: float = 5.0
    order_fill_timeout_seconds: float = 30.0

    # ── Persistence ───────────────────────────────────────────────────
    state_file_path: str = "trading_bot_state.json"
    log_file: str = "trading_bot.log"

    # ── Timezone ──────────────────────────────────────────────────────
    timezone_str: str = "Asia/Kolkata"

    # ── Paper mode slippage sim ───────────────────────────────────────
    slippage_nifty_points: float = 3.0
    slippage_banknifty_points: float = 7.0

    # ── Heartbeat ─────────────────────────────────────────────────────
    heartbeat_interval_minutes: int = 0
    """Log a HEARTBEAT line every N minutes (0 = disabled)."""

    ops_api_url: str = ""
    """URL of the Ops API (e.g. http://localhost:8080). If set, heartbeats are POSTed here."""


def load_config_from_env() -> TradingBotConfig:
    """Load ALL config from environment / .env file.

    Env key pattern: TB_<UPPERCASE_FIELD_NAME>
    e.g., TB_VWAP_LOOKBACK_CANDLES=15

    Only vars set in the environment override dataclass defaults.
    """
    import os

    import dotenv

    dotenv.load_dotenv()

    prefix = "TB_"

    kwargs: dict[str, Any] = {}
    for f in fields(TradingBotConfig):
        env_key = prefix + f.name.upper()
        raw = os.environ.get(env_key)
        if raw is not None:
            kwargs[f.name] = _parse_field(raw, f)

    return TradingBotConfig(**kwargs)


__all__ = ["TradingBotConfig", "load_config_from_env"]
