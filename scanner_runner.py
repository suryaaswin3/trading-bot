"""Standalone scanner process — market-aware, crash-resilient, systemd-ready.

Runs the full scan pipeline (momentum + volume scanners, quality gate, regime
filter, confirmation gate) as an independent process. Shares the SQLite database
with the ops-api process via WAL mode.

Usage:
    uv run python scanner_runner.py           # normal run
    uv run python scanner_runner.py --dry-run  # one scan tick then exit

Environment: OA_ROLE=scanner is implied; all OA_* vars apply.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import traceback
import uuid
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


# ── Imports that may fail in dry-run ────────────────────────────────────────

def _import_or_exit(module: str, name: str = ""):
    try:
        return __import__(module, fromlist=[name])
    except ImportError as e:
        logger.error("Failed to import {} — is the project installed? {}", module, e)
        sys.exit(1)


ops_config = _import_or_exit("ops_api.config")
_OpsApiConfig = ops_config.OpsApiConfig
_load_ops_config = ops_config.load_ops_config

_ops_db = _import_or_exit("ops_api.db")
_DatabaseManager = _ops_db.DatabaseManager

_ops_market_clock = _import_or_exit("ops_api.market_clock")
_is_market_open = _ops_market_clock.is_market_open
_session_phase = _ops_market_clock.session_phase
_seconds_until_market_open = _ops_market_clock.seconds_until_market_open

_notifier_mod = _import_or_exit("ops_api.notifier")
_TelegramNotifier = _notifier_mod.TelegramNotifier
_create_notifier = _notifier_mod.create_notifier

_scanner_mod = _import_or_exit("ops_api.scanner")
_MomentumScanner = _scanner_mod.MomentumScanner
_VolumeScanner = _scanner_mod.VolumeScanner

_cache_mod = _import_or_exit("ops_api.market_data.base")
_OHLCVCache = _cache_mod.OHLCVCache

_session_mod = _import_or_exit("ops_api.session")
_SessionManager = _session_mod.SessionManager

_trade_plan_mod = _import_or_exit("ops_api.trade_plan")
_get_active_plan = _trade_plan_mod.get_active_plan

_scan_metrics_mod = _import_or_exit("ops_api.scan_metrics")
_ScanMetrics = _scan_metrics_mod.ScanMetrics

_kite_mod = None
try:
    _kite_mod = __import__("trading_bot.kite_client", fromlist=["KiteClient"])
except ImportError:
    logger.info("Kite client not available — scanner in cache-only mode")


# ── Globals for signal handler ─────────────────────────────────────────────

_scanner_config: _OpsApiConfig | None = None  # type: ignore[name-defined]
_scanner_db: Any = None
_scanner_notifier: _TelegramNotifier | None = None  # type: ignore[name-defined]
_shutdown_requested = False
_start_time = time.time()


def _handle_sigterm(signum: int, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logger.warning("Scanner received SIGTERM — shutting down")


def _handle_sigint(signum: int, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Scanner received SIGINT — shutting down")


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigint)


# ── Scan tick ───────────────────────────────────────────────────────────────


def _run_scan_tick(
    config: _OpsApiConfig,  # type: ignore[name-defined]
    db: Any,
    cache: Any,
    metrics: Any,
    momentum: Any,
    volume: Any,
    provider: Any,
    session_manager: _SessionManager,  # type: ignore[name-defined]
    strategy_engine: Any,
) -> None:
    """One iteration of the scan loop. Mirrors ``_build_scan_callback`` logic."""
    plan = _get_active_plan()
    metrics.record_scan_start()
    for symbol in config.scanner_symbols:
        try:
            bars = cache.get(symbol, "60")
            if bars is not None:
                metrics.record_cache_hit()
            elif provider is not None:
                metrics.record_cache_miss()
                bars = provider.fetch(symbol, interval="60", count=100)
                if bars:
                    cache.set(symbol, "60", bars)
            if not bars:
                continue

            for scanner, strategy_name in ((momentum, "MOMENTUM"), (volume, "RELATIVE_VOLUME")):
                result = scanner.scan(bars, symbol=symbol, interval="60")
                if result.has_signal and result.signal is not None:
                    metrics.record_signal(scanner.strategy_id)

                    from ops_api.quality import score_breakout
                    qs = score_breakout(bars, result.signal, min_quality_override=plan.min_quality)
                    metrics.record_quality(qs.accepted, qs.reason)
                    if not qs.accepted:
                        logger.info("Quality reject {} {}: score={:.2f} reason={}", symbol, strategy_name, qs.total, qs.reason)
                        continue

                    from ops_api.regime import detect_regime
                    rs = detect_regime(bars, allowed_regimes_override=plan.allowed_regimes)
                    metrics.record_regime(rs.regime, rs.breakout_allowed)
                    if not rs.breakout_allowed:
                        logger.info(
                            "Regime reject {} {}: regime={} conf={:.2f} reasons={}",
                            symbol, strategy_name, rs.regime, rs.confidence, rs.reasons,
                        )
                        continue

                    from ops_api.confirmation import confirm_signal
                    conf_bars = cache.get(symbol, "15")
                    if conf_bars is None and provider is not None:
                        metrics.record_cache_miss()
                        conf_bars = provider.fetch(symbol, interval="15", count=100)
                        if conf_bars:
                            cache.set(symbol, "15", conf_bars)
                    if conf_bars:
                        cs = confirm_signal(bars, conf_bars, result.signal, min_alignment_override=plan.min_alignment)
                        metrics.record_confirmation(cs.accepted, cs.reason)
                        if not cs.accepted:
                            logger.info(
                                "Confirmation reject {} {}: alignment={:.2f} reason={}",
                                symbol, strategy_name, cs.alignment_score, cs.reason,
                            )
                            continue

                    signal_dict = result.signal.model_dump()
                    signal_dict["id"] = str(uuid.uuid4())
                    signal_dict["normalized_at"] = datetime.utcnow().isoformat()
                    signal_dict["session_id"] = session_manager.current_session().session_id if session_manager.active else ""
                    db.insert_signal(signal_dict)

                    snap = session_manager.current_session().snapshot() if session_manager.current_session() else None
                    sess_metrics = {"trades": snap.trades, "final_pnl": snap.pnl} if snap else {}
                    exec_result = strategy_engine.process(
                        signal_dict, mode="paper", session_metrics=sess_metrics,
                    )
                    logger.info("Scanner signal: symbol={} strategy={} result={}", symbol, strategy_name, exec_result.get("status"))
        except Exception:
            logger.exception("Scan tick error for symbol={}", symbol)
    metrics.record_scan_end()


def _write_scanner_status(
    db: Any,
    status: str,
    tick_count: int = 0,
    error_count: int = 0,
    market_phase: str = "",
) -> None:
    """Write scanner heartbeat to the shared ``scanner_status`` DB table."""
    now = datetime.utcnow().isoformat()
    db.upsert_scanner_status({
        "process_id": f"scanner-{os.getpid()}",
        "pid": os.getpid(),
        "status": status,
        "last_tick_at": now if status == "running" else "",
        "tick_count": tick_count,
        "error_count": error_count,
        "market_phase": market_phase,
        "uptime_seconds": time.time() - _start_time,
        "started_at": datetime.fromtimestamp(_start_time).isoformat(),
        "updated_at": now,
    })


# ── Main loop ───────────────────────────────────────────────────────────────


def run_scanner(config: _OpsApiConfig) -> None:  # type: ignore[name-defined]
    """Main scanner loop — market-aware, crash-reporting, infinitely looped."""
    global _scanner_config, _scanner_db, _scanner_notifier

    _scanner_config = config
    pid = os.getpid()

    # ── Initialize services ───────────────────────────────────────────
    db = _DatabaseManager(config.db_path)
    db.init_schema()
    _scanner_db = db

    notifier = _create_notifier(config, db)
    _scanner_notifier = notifier

    cache = _OHLCVCache(ttl_seconds=300)
    metrics = _ScanMetrics()
    momentum = _MomentumScanner()
    volume = _VolumeScanner()

    # Kite client (optional — scanner can run in cache-only mode)
    kite_client = None
    provider = None
    try:
        from trading_bot.config import load_config_from_env as load_bot_config
        bot_config = load_bot_config()
        if bot_config.kite_api_key and bot_config.kite_access_token:
            kite_client = _kite_mod.KiteClient(bot_config) if _kite_mod else None
            if kite_client:
                kite_client.connect()
                logger.info("Scanner Kite client connected")
                from ops_api.market_data.kite_provider import KiteConnectMarketData
                provider = KiteConnectMarketData(kite_client)
    except Exception:
        logger.warning("Scanner Kite client unavailable — cache-only mode")

    # ── Strategy Engine ───────────────────────────────────────────────
    from ops_api.strategies import DefaultStrategy, StrategyRegistry
    from ops_api.strategy_engine import StrategyEngine
    from ops_api.risk_engine import RiskEngine
    from ops_api.position_manager import PositionManager
    from ops_api.validation import ValidationPipeline
    from ops_api.execution import ExecutionEngine

    position_manager = PositionManager(db)
    validator = ValidationPipeline(config, db)
    executor = ExecutionEngine(config, db, kite_client=kite_client, position_manager=position_manager)

    _registry = StrategyRegistry()
    _registry.register(DefaultStrategy())
    _risk_engine = RiskEngine(db, position_manager=position_manager)
    strategy_engine = StrategyEngine(
        registry=_registry,
        validator=validator,
        executor=executor,
        risk_engine=_risk_engine,
        db=db,
        position_manager=position_manager,
    )
    logger.info("Scanner strategy engine initialised")

    # ── Session Manager ───────────────────────────────────────────────
    session_manager = _SessionManager(db)
    recovered = session_manager.recover_incomplete()
    if recovered:
        logger.info("Scanner recovered session {}", recovered.session_id)
    session_manager.start_session(mode="paper" if kite_client is None else "live")

    # Write initial heartbeat to DB
    _write_scanner_status(db, "running", market_phase=_session_phase())
    logger.info("Scanner process started (pid={})", pid)
    logger.info("Scanner symbols={} interval={}s", config.scanner_symbols, config.scanner_interval_seconds)

    # Notify on startup
    notifier.alert_system(
        "Scanner process started",
        f"PID={pid} symbols={config.scanner_symbols} mode={'live' if kite_client else 'paper'}",
        "INFO",
    )

    # Live trading safety gate
    if config.live_trading:
        notifier.alert_live_warning()
        logger.critical("LIVE TRADING IS ENABLED in scanner process")

    # ── Main loop ─────────────────────────────────────────────────────
    tick_count = 0
    error_count = 0
    last_phase = ""

    try:
        while not _shutdown_requested:
            phase = _session_phase()

            # Log phase transitions
            if phase != last_phase:
                logger.info("Market phase transition: {} → {}", last_phase or "START", phase)
                last_phase = phase

            if phase == "TRADING":
                _run_scan_tick(
                    config=config,
                    db=db,
                    cache=cache,
                    metrics=metrics,
                    momentum=momentum,
                    volume=volume,
                    provider=provider,
                    session_manager=session_manager,
                    strategy_engine=strategy_engine,
                )
                tick_count += 1
                _write_scanner_status(db, "running", tick_count, error_count, phase)
                m = metrics.snapshot()
                logger.info(
                    "Scan tick {} complete: signals={} cache_hit={:.0%} uptime={:.0f}s",
                    tick_count, m["signals_found"], m["cache_hit_rate"], time.time() - _start_time,
                )

            elif phase in ("PRE_MARKET", "CLOSED"):
                # Sleep and check periodically — don't spam the DB
                logger.debug("Market {} — waiting", phase)
                _write_scanner_status(db, "running", tick_count, error_count, phase)
                time.sleep(min(60, config.scanner_interval_seconds))

            elif phase in ("POST_MARKET", "WEEKEND", "HOLIDAY"):
                # Market is closed for the day — sleep longer
                _write_scanner_status(db, "running", tick_count, error_count, phase)
                next_open = _seconds_until_market_open()
                logger.info("Market {} — next open in {}s", phase, next_open)
                wait = min(next_open, 600)  # max 10 min between checks
                time.sleep(wait)

            # Brief sleep even in TRADING phase to respect interval
            if phase == "TRADING" and not _shutdown_requested:
                time.sleep(config.scanner_interval_seconds)

    except Exception:
        error_count += 1
        tb = traceback.format_exc()
        logger.exception("Scanner main loop crashed")
        _write_scanner_status(db, "error", tick_count, error_count, _session_phase())
        notifier.alert_crash(error=str(sys.exc_info()[1]), traceback=tb)

    # ── Graceful shutdown ─────────────────────────────────────────────
    logger.info("Scanner process shutting down (pid={}, ticks={})", pid, tick_count)
    _write_scanner_status(db, "stopped", tick_count, error_count, _session_phase())

    notifier.alert_shutdown(reason=f"scanner process stop (ticks={tick_count})")

    session_manager.end_session()
    db.wal_checkpoint()
    logger.info("Scanner shutdown complete")


# ── Entry point ─────────────────────────────────────────────────────────────


def main() -> None:
    """Parse args and launch scanner."""
    parser = argparse.ArgumentParser(description="Standalone scanner process")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run one scan tick then exit (for testing)",
    )
    args = parser.parse_args()

    config = _load_ops_config()
    logger.add(
        os.path.join(config.log_dir, "scanner.log"),
        rotation="1 day",
        retention="30 days",
        level=config.log_level.upper(),
        enqueue=True,
    )

    issues = config.validate()
    for issue in issues:
        if issue.startswith("[ERR]"):
            logger.error("Config: {}", issue)
        elif issue.startswith("[WARN]"):
            logger.warning("Config: {}", issue)

    if config.has_fatal_issues():
        logger.error("Fatal config issues — refusing to start")
        sys.exit(1)

    if args.dry_run:
        # One-shot: run a single scan tick then exit
        logger.info("DRY RUN — one scan tick only")
        _run_single_scan(config)
        logger.info("Dry run complete")
        return

    run_scanner(config)


def _run_single_scan(config: _OpsApiConfig) -> None:  # type: ignore[name-defined]
    """Execute a single scan tick for dry-run testing."""
    db = _DatabaseManager(config.db_path)
    db.init_schema()

    cache = _OHLCVCache(ttl_seconds=300)
    metrics = _ScanMetrics()
    momentum = _MomentumScanner()
    volume = _VolumeScanner()

    kite_client = None
    provider = None
    try:
        from trading_bot.config import load_config_from_env as load_bot_config
        from ops_api.market_data.kite_provider import KiteConnectMarketData
        bot_config = load_bot_config()
        if bot_config.kite_api_key and bot_config.kite_access_token:
            kite_client = _kite_mod.KiteClient(bot_config) if _kite_mod else None
            if kite_client:
                kite_client.connect()
                provider = KiteConnectMarketData(kite_client)
    except Exception:
        logger.warning("Dry-run Kite unavailable")

    from ops_api.position_manager import PositionManager
    from ops_api.validation import ValidationPipeline
    from ops_api.execution import ExecutionEngine
    from ops_api.strategies import DefaultStrategy, StrategyRegistry
    from ops_api.strategy_engine import StrategyEngine
    from ops_api.risk_engine import RiskEngine

    position_manager = PositionManager(db)
    validator = ValidationPipeline(config, db)
    executor = ExecutionEngine(config, db, kite_client=kite_client, position_manager=position_manager)
    _registry = StrategyRegistry()
    _registry.register(DefaultStrategy())
    _risk_engine = RiskEngine(db, position_manager=position_manager)
    strategy_engine = StrategyEngine(
        registry=_registry,
        validator=validator,
        executor=executor,
        risk_engine=_risk_engine,
        db=db,
        position_manager=position_manager,
    )
    session_manager = _SessionManager(db)
    session_manager.start_session(mode="paper")

    _run_scan_tick(
        config=config,
        db=db,
        cache=cache,
        metrics=metrics,
        momentum=momentum,
        volume=volume,
        provider=provider,
        session_manager=session_manager,
        strategy_engine=strategy_engine,
    )


if __name__ == "__main__":
    main()