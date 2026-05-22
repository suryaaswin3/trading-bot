"""FastAPI application — webhook, controls, health, dashboard data API.

Run with:
    uv run uvicorn ops_api.main:app --host 0.0.0.0 --port 8080

Startup initialises SQLite schema. Graceful shutdown on SIGTERM.
"""

from __future__ import annotations

import signal
import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Any, Callable
from datetime import datetime
from uuid import uuid4

import dataclasses

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from ops_api.config import OpsApiConfig, load_ops_config
from ops_api.controls import handle_control_action
from ops_api.db import DatabaseManager
from ops_api.execution import ExecutionEngine
from ops_api.health import run_health_checks, write_heartbeat
from ops_api.models import (
    ApiError,
    WebhookResponse,
)
from ops_api.position_manager import PositionManager
from ops_api.notifier import TelegramNotifier, create_notifier
from ops_api.risk_engine import RiskEngine
from ops_api.market_data import OHLCVCache
from ops_api.scan_metrics import ScanMetrics
from ops_api.scanner import MomentumScanner, VolumeScanner
from ops_api.scheduler import ScanScheduler
from ops_api.strategies import DefaultStrategy, StrategyRegistry
from ops_api.strategy_engine import StrategyEngine
from ops_api.validation import ValidationPipeline
from ops_api.webhook import handle_tradingview_webhook
from ops_api.session import SessionManager
from ops_api.trade_plan import get_active_plan
from ops_api.ranking import rank_symbols, RankingConfig
from ops_api.timing import check_entry_timing, TimingConfig
from ops_api.trade_analytics import TradeAnalytics

# ── Globals (set during lifespan) ────────────────────────────────────────

config: OpsApiConfig | None = None
db: DatabaseManager | None = None
validator: ValidationPipeline | None = None
executor: ExecutionEngine | None = None
notifier: TelegramNotifier | None = None
strategy_engine: StrategyEngine | None = None
scanner_scheduler: ScanScheduler | None = None
scan_metrics: ScanMetrics | None = None
position_manager: PositionManager | None = None
session_manager: SessionManager | None = None
trade_analytics: TradeAnalytics | None = None
ranking_config: RankingConfig | None = None
timing_config: TimingConfig | None = None
_shutdown = False


def _handle_sigterm(signum: int, _frame) -> None:
    global _shutdown
    _shutdown = True
    logger.warning("Received SIGTERM — shutting down")


signal.signal(signal.SIGTERM, _handle_sigterm)


def _build_scan_callback(
    kite_client: Any,
    config: OpsApiConfig,
    strategy_engine: StrategyEngine,
    db: DatabaseManager,
    cache: OHLCVCache,
    analytics: TradeAnalytics | None = None,
    rank_cfg: RankingConfig | None = None,
    timing_cfg: TimingConfig | None = None,
    metrics: ScanMetrics | None = None,
) -> Callable[[], None]:
    """Build the scanner callback closure for the scheduler tick."""
    from ops_api.market_data.kite_provider import KiteConnectMarketData

    provider = KiteConnectMarketData(kite_client) if kite_client else None
    momentum = MomentumScanner()
    volume = VolumeScanner()

    def _scan_tick() -> None:
        if metrics:
            metrics.record_scan_start()
        plan = get_active_plan()

        # ── Phase 7: Rank symbols, scan only top-N ──────────────────────
        bars_by_symbol: dict[str, list[Any]] = {}
        for symbol in config.scanner_symbols:
            bars = cache.get(symbol, "60")
            if bars is not None and len(bars) > 20:
                bars_by_symbol[symbol] = bars

        ranked = rank_symbols(bars_by_symbol, rank_cfg) if bars_by_symbol else []
        scan_symbols = [r.symbol for r in ranked] or config.scanner_symbols

        for symbol in scan_symbols:
            try:
                bars = cache.get(symbol, "60")
                if bars is not None:
                    if metrics: metrics.record_cache_hit()
                elif provider is not None:
                    if metrics: metrics.record_cache_miss()
                    bars = provider.fetch(symbol, interval="60", count=100)
                    if bars:
                        cache.set(symbol, "60", bars)
                if not bars:
                    continue

                for scanner, strategy_name in ((momentum, "MOMENTUM"), (volume, "RELATIVE_VOLUME")):
                    result = scanner.scan(bars, symbol=symbol, interval="60")
                    if result.has_signal and result.signal is not None:
                        if metrics:
                            metrics.record_signal(scanner.strategy_id)
                        from ops_api.quality import score_breakout
                        qs = score_breakout(bars, result.signal, min_quality_override=plan.min_quality)
                        if metrics:
                            metrics.record_quality(qs.accepted, qs.reason)
                        if not qs.accepted:
                            logger.info("Quality reject {} {}: score={:.2f} reason={}", symbol, strategy_name, qs.total, qs.reason)
                            continue
                        from ops_api.regime import detect_regime
                        rs = detect_regime(bars, allowed_regimes_override=plan.allowed_regimes)
                        if metrics:
                            metrics.record_regime(rs.regime, rs.breakout_allowed)
                        if not rs.breakout_allowed:
                            logger.info("Regime reject {} {}: regime={} conf={:.2f} reasons={}", symbol, strategy_name, rs.regime, rs.confidence, rs.reasons)
                            continue
                        from ops_api.confirmation import confirm_signal
                        conf_bars = cache.get(symbol, "15")
                        if conf_bars is None and provider is not None:
                            if metrics: metrics.record_cache_miss()
                            conf_bars = provider.fetch(symbol, interval="15", count=100)
                            if conf_bars:
                                cache.set(symbol, "15", conf_bars)
                        if conf_bars:
                            cs = confirm_signal(bars, conf_bars, result.signal, min_alignment_override=plan.min_alignment)
                            if metrics:
                                metrics.record_confirmation(cs.accepted, cs.reason)
                            if not cs.accepted:
                                logger.info("Confirmation reject {} {}: alignment={:.2f} reason={}", symbol, strategy_name, cs.alignment_score, cs.reason)
                                continue

                        # ── Phase 7: Entry timing refinement ─────────────────────
                        timing = check_entry_timing(bars, result.signal.side, timing_cfg)
                        if not timing.allowed:
                            logger.info("Timing reject {} {}: method={} reason={}", symbol, strategy_name, timing.method, timing.reason)
                            continue

                        signal_dict = result.signal.model_dump()
                        signal_dict["id"] = str(uuid4())
                        signal_dict["normalized_at"] = datetime.utcnow().isoformat()
                        signal_dict["session_id"] = session_manager.current_session().session_id if session_manager and session_manager.active else ""
                        db.insert_signal(signal_dict)
                        snap = session_manager.current_session().snapshot() if session_manager and session_manager.current_session() else None
                        session_metrics = {"trades": snap.trades, "final_pnl": snap.pnl} if snap else {}
                        exec_result = strategy_engine.process(
                            signal_dict, mode="paper", session_metrics=session_metrics,
                        )
                        logger.info("Scanner signal: symbol={} strategy={} result={}", symbol, strategy_name, exec_result.get("status"))
            except Exception:
                logger.exception("Scan tick error for symbol={}", symbol)
        if metrics:
            metrics.record_scan_end()

    return _scan_tick


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise DB, config, and services on startup."""
    global config, db, validator, executor, notifier, strategy_engine, scanner_scheduler, scan_metrics, position_manager, session_manager, trade_analytics, ranking_config, timing_config

    load_dotenv()
    config = load_ops_config()

    # ── Startup validation ──────────────────────────────────────────
    issues = config.validate()
    for issue in issues:
        if issue.startswith("[ERR]"):
            logger.error("Config: {}", issue)
        elif issue.startswith("[WARN]"):
            logger.warning("Config: {}", issue)

    if config.has_fatal_issues():
        logger.error("Fatal config issues — refusing to start")
        raise SystemExit(1)

    db = DatabaseManager(config.db_path)
    db.init_schema()

    # Run cleanup on startup to keep DB lean
    deleted = db.delete_old_data(days=config.retention_days)
    db.wal_checkpoint()
    total_deleted = sum(v for v in deleted.values() if v > 0)
    if total_deleted:
        logger.info("Startup cleanup removed {} old records", total_deleted)

    # ── Position Manager (Phase 4) ───────────────────────────
    position_manager = PositionManager(db)

    notifier = create_notifier(config, db)
    validator = ValidationPipeline(config, db)

    # Expose underlying KiteClient import for live execution
    kite_client = None
    try:
        from trading_bot.config import (
            load_config_from_env as load_bot_config,
        )
        from trading_bot.kite_client import KiteClient as _KiteClient

        bot_config = load_bot_config()
        if bot_config.kite_api_key and bot_config.kite_access_token:
            kite_client = _KiteClient(bot_config)
            try:
                kite_client.connect()
                logger.info("Kite client connected for ops execution engine")
            except Exception as e:
                logger.warning("Could not connect Kite client: {}", e)
                kite_client = None
    except ImportError:
        logger.info("Kite client not available, executor in paper-only mode")

    # Reset stale kite_connected so dashboard doesn't lie
    if kite_client is None:
        existing = db.get_bot_status()
        if existing and existing.get("kite_connected"):
            merged = dict(existing)
            merged["kite_connected"] = False
            db.upsert_bot_status(merged)

    executor = ExecutionEngine(config, db, kite_client=kite_client, position_manager=position_manager)

    # ── Phase 7: Trade analytics + ranking + timing config ───────────────
    trade_analytics = TradeAnalytics()
    ranking_config = RankingConfig()
    timing_config = TimingConfig()

    # ── Strategy Engine (Phase 1) ────────────────────────────────
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
    logger.info("Strategy engine initialised with {} strategy(ies)", len(_registry.all()))

    # ── Role-aware scanner init ────────────────────────────────────────
    should_run_scanner = config.role in ("all", "scanner") and config.scanner_enabled

    _market_cache = OHLCVCache(ttl_seconds=300)
    scan_metrics = ScanMetrics()

    if should_run_scanner:
        _scan_cb = _build_scan_callback(
            kite_client=kite_client,
            config=config,
            strategy_engine=strategy_engine,
            db=db,
            cache=_market_cache,
            analytics=trade_analytics,
            rank_cfg=ranking_config,
            timing_cfg=timing_config,
            metrics=scan_metrics,
        )
        scanner_scheduler = ScanScheduler(
            callback_fn=_scan_cb,
            interval_seconds=config.scanner_interval_seconds,
        )
        scanner_scheduler.start()
        logger.info("Scanner engine started: {} symbols, interval={}s (role={})", len(config.scanner_symbols), config.scanner_interval_seconds, config.role)
    else:
        logger.info("Scanner engine disabled (role={}, scanner_enabled={})", config.role, config.scanner_enabled)

    # ── Session Manager (Phase 5D) ──────────────────────────────
    session_manager = SessionManager(db)
    # Recover any incomplete session from a previous run
    recovered = session_manager.recover_incomplete()
    if recovered:
        logger.info("Recovered session {} from previous run", recovered.session_id)

    # Start a trading session for this run
    session_manager.start_session(mode="paper" if kite_client is None else "live")
    logger.info("Trading session started: {}", session_manager.current_session().session_id)

    # ── Live trading safety gate ───────────────────────────────────────
    if config.live_trading:
        logger.critical("LIVE TRADING IS ENABLED — real money execution active")
        notifier.alert_live_warning()
    else:
        logger.info("Live trading is DISABLED — paper mode only")

    # Notify on startup
    notifier.alert_system(
        "Ops API started",
        f"Role: {config.role}, Mode: {'live' if kite_client else 'paper'}, Port: {config.port}",
        "INFO",
    )

    logger.info(
        "Ops API started: role={} host={} port={} db={} telegram={} live={}",
        config.role,
        config.host,
        config.port,
        config.db_path,
        bool(notifier._enabled),
        config.live_trading,
    )

    yield

    logger.info("Ops API shutting down (role={})", config.role)
    if scanner_scheduler is not None:
        scanner_scheduler.stop()
        logger.info("Scanner scheduler stopped")
    if session_manager is not None:
        snap = session_manager.end_session()
        if snap:
            logger.info("Session ended: trades={} pnl={:.2f}", snap.trades, snap.pnl)
    await notifier.close()


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Trading Bot Ops API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth dependency ──────────────────────────────────────────────────────


def _verify_api_key(request: Request) -> None:
    """Verify API key for protected endpoints."""
    cfg = config
    if cfg is None:
        raise HTTPException(status_code=503, detail="Service not initialised")

    if not cfg.api_key:
        return  # No API key configured — allow all

    key = request.headers.get(cfg.api_key_header, "")
    if key != cfg.api_key:
        logger.warning(
            "Unauthorized API access attempt from {}",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


# ── Endpoints ────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check — returns aggregate status of all components."""
    if db is None:
        return {"status": "fail", "checks": []}
    tg_healthy = notifier.healthy if notifier else None
    sched_running = scanner_scheduler.running if scanner_scheduler is not None else None
    scanner_status = db.get_scanner_status() if db else None
    results = run_health_checks(
        db,
        config is not None,
        telegram_healthy=tg_healthy,
        scheduler_running=sched_running,
        scan_metrics=scan_metrics,
        scanner_status=scanner_status,
    )
    overall = "pass"
    for r in results:
        if r["status"] == "fail":
            overall = "fail"
            break
        if r["status"] == "warn" and overall == "pass":
            overall = "warn"
    return {"status": overall, "checks": results}


@app.get("/status")
async def status_endpoint() -> dict[str, Any]:
    """Bot status summary including kill switch state."""
    if db is None:
        raise HTTPException(status_code=503, detail="Service not initialised")
    bot_status = db.get_bot_status()
    latest_hb = db.get_latest_heartbeat()
    kill_switch = db.get_kill_switch_state()
    return {
        "bot_status": bot_status or {},
        "latest_heartbeat": latest_hb or {},
        "kill_switch": kill_switch,
    }


@app.post("/webhook/tradingview")
async def webhook_tradingview(request: Request) -> WebhookResponse | dict[str, Any]:
    """Receive a TradingView alert webhook.

    Accepts JSON body with TradingView payload.
    Requires ``OA_WEBHOOK_SECRET`` for production use.
    """
    if db is None or config is None:
        raise HTTPException(status_code=503, detail="Service not initialised")

    # When behind Nginx reverse proxy, prefer X-Real-IP for original client address
    source_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )

    try:
        raw_body = await request.body()
        payload = await request.json()
    except Exception:
        return {
            "status": "rejected",
            "alert_id": "",
            "signal_id": "",
            "message": "Invalid JSON",
        }

    sig_header = request.headers.get("X-Signature", "")

    _sid = session_manager.current_session().session_id if session_manager and session_manager.active else ""
    result = await handle_tradingview_webhook(
        payload=payload,
        db=db,
        webhook_secret=config.webhook_secret,
        source_ip=source_ip,
        signature_header=sig_header,
        raw_body=raw_body,
        session_id=_sid,
    )

    # If received, run validation then execute if passed
    if result.get("status") == "received" and validator is not None:
        signal_id = result.get("signal_id", "")
        # Fetch signal from DB
        signals = db.get_recent_signals(limit=1)
        signal = next((s for s in signals if s["id"] == signal_id), None)

        if signal:
            if config.use_strategy_engine and strategy_engine is not None:
                # New path: StrategyEngine wraps shared validation + execution
                snap = session_manager.current_session().snapshot() if session_manager and session_manager.current_session() else None
                sess_metrics = {"trades": snap.trades, "final_pnl": snap.pnl} if snap else {}
                exec_result = strategy_engine.process(signal, mode="paper", session_metrics=sess_metrics)
                result["validation_passed"] = exec_result.get("validation_passed", False)
                result["strategy_id"] = exec_result.get("strategy_id", "default")
                result["execution"] = exec_result
            else:
                # Original path: direct validator to executor
                validation = validator.validate(signal)
                validation_dict = validation.model_dump()
                validation_dict["checks"] = [c.model_dump() for c in validation.checks]
                result["validation_passed"] = validation.passed

                if validation.passed and executor is not None:
                    exec_result = executor.execute(
                        signal, validation_dict, mode="paper"
                    )
                    result["execution"] = exec_result
                else:
                    exec_result = None

            # Write heartbeat + Telegram notification (common to both paths)
            if exec_result and exec_result.get("status") == "filled":
                write_heartbeat(
                    db=db,
                    bot_status="running",
                    bot_mode="paper",
                    kite_connected=False,
                )

                if notifier is not None:
                    notifier.alert_trade(
                        event=f"Paper trade: {signal.get('strategy', 'unknown')}",
                        symbol=signal.get("symbol", ""),
                        side=signal.get("side", ""),
                        price=exec_result.get("filled_price", 0.0),
                        qty=exec_result.get("filled_quantity", 0),
                        mode="paper",
                        order_id=exec_result.get("external_order_id", ""),
                    )

    return WebhookResponse(**result)


@app.post("/control/{action}")
async def control_action(
    action: str,
    request: Request,
    _auth: None = Depends(_verify_api_key),
) -> dict[str, Any]:
    """Execute a control action.

    Supported actions: ``start``, ``stop``, ``pause``, ``resume``,
    ``flatten``, ``set_mode``, ``reload_config``.

    For ``set_mode``, send JSON body: ``{"params": {"mode": "paper|live"}}``
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Service not initialised")

    body: dict[str, Any] = {}
    with suppress(Exception):
        body = await request.json()

    params = body.get("params", {})
    triggered_by = body.get("triggered_by", "")

    result = handle_control_action(
        action=action,
        db=db,
        triggered_by=triggered_by,
        source="web",
        params=params,
    )

    if result.get("status") == "error":
        raise HTTPException(
            status_code=400, detail=result.get("message", "Unknown error")
        )

    # Send Telegram alerts for critical control actions
    if action in ("kill", "reset_kill") and notifier is not None:
        severity = "CRITICAL" if action == "kill" else "WARNING"
        notifier.alert_system(
            f"Kill switch {action}", result.get("message", ""), severity
        )

    return result


# ── Shared dashboard data ────────────────────────────────────────────────


def _get_dashboard_data() -> dict[str, Any]:
    """Aggregated dashboard payload used by both REST and WebSocket endpoints."""
    assert db is not None, "_get_dashboard_data called before db initialised"
    bot_status = db.get_bot_status() or {}
    latest_hb = db.get_latest_heartbeat() or {}
    recent_orders = db.get_recent_orders(limit=10)
    recent_alerts = db.get_recent_alerts(limit=10)
    recent_signals = db.get_recent_signals(limit=20)
    recent_validations = db.get_recent_validations(limit=10)
    recent_events = db.get_recent_events(limit=20)
    recent_errors = db.get_recent_errors(limit=10)
    position_history = db.get_position_history(limit=500)
    equity_curve = db.get_equity_curve(limit=500)
    kill_switch = db.get_kill_switch_state()
    kill_switch_history = db.get_kill_switch_history(limit=10)
    recent_notifications = db.get_recent_notifications(limit=10)

    _stale_hb_seconds = 300
    _hb_ts = latest_hb.get("timestamp", "") if latest_hb else ""
    _hb_stale = True
    if _hb_ts:
        try:
            _hb_dt = datetime.fromisoformat(_hb_ts)
            _hb_stale = (datetime.utcnow() - _hb_dt).total_seconds() > _stale_hb_seconds
        except (ValueError, TypeError):
            pass
    _kite_ok = bool(bot_status.get("kite_connected", False)) and not _hb_stale

    return {
        "bot_status": bot_status.get("status", "stopped"),
        "bot_mode": bot_status.get("mode", "paper"),
        "last_heartbeat": latest_hb,
        "current_position": {
            "symbol": bot_status.get("current_symbol"),
            "side": bot_status.get("position_side"),
            "quantity": bot_status.get("position_qty", 0),
            "entry_price": bot_status.get("position_entry_price", 0.0),
        },
        "daily_pnl": bot_status.get("daily_pnl", 0.0),
        "cumulative_pnl": bot_status.get("cumulative_pnl", 0.0),
        "trades_today": bot_status.get("trades_today", 0),
        "wins_today": bot_status.get("wins_today", 0),
        "losses_today": bot_status.get("losses_today", 0),
        "max_drawdown_today": bot_status.get("max_drawdown_today", 0.0),
        "kite_connected": _kite_ok,
        "last_order": recent_orders[0] if recent_orders else None,
        "last_alert": recent_alerts[0] if recent_alerts else None,
        "last_validation": recent_validations[0] if recent_validations else None,
        "recent_alerts": recent_alerts,
        "recent_signals": recent_signals,
        "recent_orders": recent_orders,
        "recent_events": recent_events,
        "recent_errors": recent_errors,
        "position_history": position_history,
        "equity_curve": equity_curve,
        "kill_switch": kill_switch,
        "kill_switch_history": kill_switch_history,
        "telegram_healthy": notifier.healthy if notifier and notifier.healthy else None,
        "recent_notifications": recent_notifications,
        "scanner_metrics": scan_metrics.snapshot() if scan_metrics is not None else {},
        "portfolio": db.get_portfolio_summary(),
        "positions": [dataclasses.asdict(p) for p in position_manager.get_all_positions()] if position_manager is not None else [],
        "portfolio_snapshot": dataclasses.asdict(position_manager.get_portfolio()) if position_manager is not None else {},
        # Analytics fields for charts
        "pnl_by_strategy": db.get_pnl_by_strategy(limit=1000),
        "rejection_stats": db.get_rejection_stats(limit=100),
        "daily_pnl_history": db.get_daily_pnl_history(limit=30),
        # Phase 7 analytics
        "trade_analytics": trade_analytics.summary() if trade_analytics is not None else {},
    }


@app.get("/dashboard/data")
async def dashboard_data() -> dict[str, Any]:
    """Aggregated data payload for the dashboard (REST fallback)."""
    if db is None:
        raise HTTPException(status_code=503, detail="Service not initialised")
    return _get_dashboard_data()


@app.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time dashboard updates.

    On connect: sends full dashboard snapshot.
    Then: heartbeats every 15s; disconnected clients are cleaned up.
    """
    if db is None:
        await websocket.close(code=1011, reason="Service not initialised")
        return

    await websocket.accept()

    # Send full snapshot on connect
    try:
        data = _get_dashboard_data()
        await websocket.send_json({"type": "snapshot", "data": data})
    except Exception:
        logger.exception("Failed to send initial dashboard snapshot")
        await websocket.close(code=1011)
        return

    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
                # Client sent something — currently unused, but reserved for
                # future control messages (e.g. refresh request)
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send heartbeat to detect stale connections
                await websocket.send_json({
                    "type": "heartbeat",
                    "data": {"timestamp": datetime.utcnow().isoformat()},
                })
    except WebSocketDisconnect:
        logger.debug("Dashboard WebSocket disconnected")
    except Exception:
        logger.exception("Dashboard WebSocket error")


@app.get("/dashboard/analytics")
async def dashboard_analytics() -> dict[str, Any]:
    """Real analytics computed from DB data."""
    if db is None:
        raise HTTPException(status_code=503, detail="Service not initialised")
    return {
        "execution_events": db.get_execution_events(limit=200),
        "pnl_by_strategy": db.get_pnl_by_strategy(limit=1000),
        "rejection_stats": db.get_rejection_stats(limit=100),
        "daily_pnl_history": db.get_daily_pnl_history(limit=30),
        "strategy_performance": db.get_strategy_performance(),
        "closed_positions": [dataclasses.asdict(p) for p in position_manager.get_closed_positions(limit=50)] if position_manager is not None else [],
    }


@app.post("/heartbeat")
async def heartbeat_endpoint(
    request: Request,
    _auth: None = Depends(_verify_api_key),
) -> dict[str, Any]:
    """Accept heartbeat pings from the trading bot."""
    if db is None or config is None:
        raise HTTPException(status_code=503, detail="Service not initialised")

    body: dict[str, Any] = {}
    with suppress(Exception):
        body = await request.json()

    write_heartbeat(
        db=db,
        bot_status=body.get("bot_status", "running"),
        bot_mode=body.get("bot_mode", "paper"),
        last_action=body.get("last_action", ""),
        trades_today=body.get("trades_today", 0),
        daily_pnl=body.get("daily_pnl", 0.0),
        kite_connected=body.get("kite_connected", False),
    )

    return {"status": "ok"}


@app.get("/plan/current")
async def plan_current() -> dict[str, Any]:
    """Return the current active trade plan."""
    from ops_api.trade_plan import get_active_plan
    return {"plan": get_active_plan().to_dict()}


@app.post("/plan/load")
async def plan_load(request: Request, _auth: None = Depends(_verify_api_key)) -> dict[str, Any]:
    """Load a new trade plan from JSON body."""
    from ops_api.trade_plan import TradePlan, set_active_plan
    body: dict[str, Any] = {}
    with suppress(Exception):
        body = await request.json()
    plan = TradePlan.from_dict(body)
    set_active_plan(plan)
    logger.info("Trade plan loaded: {}", plan.plan_id)
    return {"status": "ok", "plan": plan.to_dict()}


@app.post("/plan/reset")
async def plan_reset(_auth: None = Depends(_verify_api_key)) -> dict[str, Any]:
    """Reset trade plan to defaults."""
    from ops_api.trade_plan import reset_plan
    reset_plan()
    logger.info("Trade plan reset to defaults")
    return {"status": "ok"}


@app.post("/maintenance/cleanup")
async def maintenance_cleanup(
    _auth: None = Depends(_verify_api_key),
) -> dict[str, Any]:
    """Run data retention cleanup manually. Auth-protected."""
    if db is None or config is None:
        raise HTTPException(status_code=503, detail="Service not initialised")

    counts = db.delete_old_data(days=config.retention_days)
    db.wal_checkpoint()

    logger.info("Maintenance cleanup: deleted={}", counts)

    notifier_safe = notifier
    if notifier_safe:
        notifier_safe.alert_system(
            "Maintenance cleanup completed",
            f"Deleted: {counts}",
            "INFO",
        )

    return {"status": "ok", "deleted": counts}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all error handler."""
    logger.exception("Unhandled exception on {} {}", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ApiError(error="Internal server error", detail=str(exc)).model_dump(),
    )


# ── Entry point ─────────────────────────────────────────────────────────


def main() -> None:
    """Run the ops API server via uvicorn."""
    import uvicorn

    cfg = load_ops_config()
    uvicorn.run(
        "ops_api.main:app",
        host=cfg.host,
        port=cfg.port,
        reload=cfg.reload,
        log_level=cfg.log_level,
    )


if __name__ == "__main__":
    main()
