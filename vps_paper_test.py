#!/usr/bin/env python3
"""Comprehensive paper trading flow test for Phase 5."""
import json, os, sys, time, uuid
from datetime import datetime, timezone

sys.path.insert(0, '/opt/trading-bot')
os.chdir('/opt/trading-bot')
os.environ['OA_WEBHOOK_SECRET'] = 'test-webhook-secret-2026'
os.environ['OA_API_KEY'] = 'dash-api-key-2026'
os.environ['OA_DASHBOARD_PASSWORD'] = 'dash-pass-2026'
os.environ['OA_TELEGRAM_BOT_TOKEN'] = '8300167290:AAFmszE1Y0Chh_ERrF7ZKU4WujtDaZUqxLg'
os.environ['OA_TELEGRAM_CHAT_ID'] = '5937301143'

from ops_api.db import DatabaseManager
from ops_api.config import OpsApiConfig
from ops_api.models import NormalizedSignal, SignalSide, CheckResult, ValidationResult
from ops_api.validation import ValidationPipeline
from ops_api.execution import ExecutionEngine
from ops_api.webhook import normalize_alert, handle_tradingview_webhook
from ops_api.health import run_health_checks

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f": {detail}"
        print(msg)

def section(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

# Initialize
config = OpsApiConfig(
    db_path="ops_data.db",
    webhook_secret="test-webhook-secret-2026",
    api_key="dash-api-key-2026",
    dashboard_password="dash-pass-2026",
    telegram_bot_token="8300167290:AAFmszE1Y0Chh_ERrF7ZKU4WujtDaZUqxLg",
    telegram_chat_id="5937301143",
    allowed_symbols=("NIFTY", "BANKNIFTY"),
)
db = DatabaseManager(config.db_path)
db.init_schema()
validator = ValidationPipeline(config, db)
engine = ExecutionEngine(config, db)

def make_validation(signal):
    """Create a ValidationResult with passed=True for execution tests."""
    return ValidationResult(
        id=str(uuid.uuid4()),
        signal_id=signal.get("id", ""),
        passed=True,
        checks=[CheckResult(check="manual", passed=True, detail="Test override")],
        rejection_reason="",
    )

def make_signal(alert_id, symbol="NIFTY", side="BUY", price=18500.0):
    return {
        "id": str(uuid.uuid4()),
        "alert_id": alert_id,
        "symbol": symbol,
        "side": side,
        "strategy": "test_strategy",
        "timeframe": "5min",
        "price": price,
        "reason": "test signal",
    }

section("1. TEST: BUY FLOW")
alert_id_buy = f"test-buy-{uuid.uuid4().hex[:8]}"
signal = make_signal(alert_id_buy, "NIFTY", "BUY", 18500.50)
check("BUY: Signal created", signal["side"] == "BUY")

validation = make_validation(signal)
result = engine.execute(signal, validation.model_dump(), mode="paper")
check("BUY: Execution succeeded", result.get("status") == "filled",
      result.get("error", ""))
check("BUY: Has order ID", bool(result.get("order_id")))

orders = db.get_recent_orders(limit=5)
check("BUY: Order persisted in DB", any(
    o.get("status") == "filled" and o.get("symbol") == "NIFTY" for o in orders))

section("2. TEST: SELL FLOW")
alert_id_sell = f"test-sell-{uuid.uuid4().hex[:8]}"
signal2 = make_signal(alert_id_sell, "BANKNIFTY", "SELL", 42000.75)
check("SELL: Signal created", signal2["side"] == "SELL")

validation2 = make_validation(signal2)
result2 = engine.execute(signal2, validation2.model_dump(), mode="paper")
check("SELL: Execution succeeded", result2.get("status") == "filled",
      result2.get("error", ""))

section("3. TEST: DUPLICATE PREVENTION")
# Same dedup_key should be caught
result_dup = engine.execute(signal, validation.model_dump(), mode="paper")
check("DUPLICATE: Dedup catches re-execution",
      result_dup.get("status") == "duplicate",
      result_dup.get("error", ""))

section("4. TEST: COOLDOWN BEHAVIOR")
db.upsert_bot_status({
    "status": "running", "mode": "paper",
    "last_order_at": datetime.now(timezone.utc).isoformat(),
})
cooldown_signal = make_signal(f"test-cd-{uuid.uuid4().hex[:8]}")
validation_cd = validator.validate(cooldown_signal)
cd_check = [c for c in validation_cd.checks if c.check == "cooldown"]
check("COOLDOWN: check present", len(cd_check) > 0)
if cd_check:
    check("COOLDOWN: active (recent order)", cd_check[0].passed == False,
          cd_check[0].detail[:100])

# Old timestamp → cooldown should pass
db.upsert_bot_status({
    "status": "running", "mode": "paper",
    "last_order_at": "2020-01-01T00:00:00",
})
no_cd_signal = make_signal(f"test-nocd-{uuid.uuid4().hex[:8]}")
validation_nocd = validator.validate(no_cd_signal)
ncd_check = [c for c in validation_nocd.checks if c.check == "cooldown"]
if ncd_check:
    check("COOLDOWN: old timestamp passes", ncd_check[0].passed == True)

section("5. TEST: MAX TRADE LIMITS")
db.upsert_bot_status({
    "status": "running", "mode": "paper",
    "trades_today": 2, "last_order_at": "2020-01-01T00:00:00",
})
max_trades_signal = make_signal(f"test-mt-{uuid.uuid4().hex[:8]}")
validation_mt = validator.validate(max_trades_signal)
check("MAX_TRADES: checks recorded", len(validation_mt.checks) > 0)
check("MAX_TRADES: max_trades_day check present",
      any(c.check == "max_trades_day" for c in validation_mt.checks))

section("6. TEST: PAUSED BOT BEHAVIOR")
db.upsert_bot_status({"status": "paused", "mode": "paper"})
paused_signal = make_signal(f"test-paused-{uuid.uuid4().hex[:8]}")
validation_paused = validator.validate(paused_signal)
check("PAUSED: Validation fails", not validation_paused.passed)
check("PAUSED: Mentions 'paused'",
      "paused" in validation_paused.rejection_reason.lower())

section("7. TEST: POSITION STATE UPDATE")
db.upsert_bot_status({
    "status": "running", "mode": "paper",
    "last_order_at": "2020-01-01T00:00:00",
})
db.insert_position_snapshot({
    "id": str(uuid.uuid4()),
    "symbol": "NIFTY", "side": "LONG", "quantity": 75,
    "entry_price": 18500.50, "current_price": 18550.00,
    "unrealized_pnl": 3712.50, "realized_pnl": 0.0,
    "trades_today": 1, "daily_pnl": 3712.50,
})
positions = db.get_recent_positions()
check("POSITION: Snapshot stored", len(positions) >= 1)
check("POSITION: Correct symbol", any(p["symbol"] == "NIFTY" for p in positions))
check("POSITION: PnL matches", any(p.get("unrealized_pnl") == 3712.50 for p in positions))

section("8. TEST: PnL UPDATE")
db.upsert_risk_counter({
    "id": str(uuid.uuid4()),
    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    "trades_today": 1, "daily_pnl": 3712.50,
    "consecutive_losses": 0, "max_drawdown": 0.0,
    "max_drawdown_pct": 0.0, "peak_pnl": 3712.50,
})
risk = db.get_todays_risk_counter()
check("PnL: Risk counter stored", risk is not None)
check("PnL: Daily PnL matches", risk and risk["daily_pnl"] == 3712.50)

section("9. TEST: WEBHOOK ENDPOINT RESILIENCE")
import asyncio

results = []
async def rapid_webhooks():
    for i in range(5):
        p = {
            "alert_id": f"rapid-{i}-{uuid.uuid4().hex[:8]}",
            "symbol": "NIFTY", "side": "BUY" if i % 2 == 0 else "SELL",
            "strategy": "test_strategy", "price": 18500 + i,
            "secret": "test-webhook-secret-2026",
        }
        r = await handle_tradingview_webhook(p, db, "test-webhook-secret-2026", "127.0.0.1")
        results.append(r["status"])

asyncio.run(rapid_webhooks())
check("WEBHOOK: 5 rapid calls", len(results) == 5)
check("WEBHOOK: All received", all(r == "received" for r in results))

# Duplicate
dup_id = f"dup-test-{uuid.uuid4().hex[:8]}"
dup_payload = {
    "alert_id": dup_id, "symbol": "NIFTY", "side": "BUY",
    "strategy": "test_strategy", "price": 18500,
    "secret": "test-webhook-secret-2026",
}
first = asyncio.run(handle_tradingview_webhook(
    dup_payload, db, "test-webhook-secret-2026", "127.0.0.1"))
dup_check = asyncio.run(handle_tradingview_webhook(
    dup_payload, db, "test-webhook-secret-2026", "127.0.0.1"))
check("WEBHOOK: First received", first["status"] == "received")
check("WEBHOOK: Duplicate rejected", dup_check["status"] == "duplicate")

section("10. TEST: HEALTH CHECK")
health_result = run_health_checks(db, config_loaded=True)
check("HEALTH: Returns checks", len(health_result) > 0)
check("HEALTH: API check passes",
      any(c.get("status") == "pass" and c.get("component") == "api_server"
          for c in health_result))
check("HEALTH: DB check passes",
      any(c.get("status") == "pass" and c.get("component") == "database"
          for c in health_result))
check("HEALTH: Config check passes",
      any(c.get("status") == "pass" and c.get("component") == "config_load"
          for c in health_result))
check("HEALTH: Kill switch check passes",
      any(c.get("status") == "pass" and c.get("component") == "kill_switch"
          for c in health_result))

section("FINAL SUMMARY")
print(f"\n  Total: {PASS + FAIL}  Passed: {PASS}  Failed: {FAIL}")
if FAIL > 0:
    print("  WARNING: Some tests FAILED — review above")
    sys.exit(1)
else:
    print("  ALL TESTS PASSED")