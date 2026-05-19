#!/usr/bin/env python3
"""Soak test: continuous webhook flows + resource monitoring for 15 minutes."""
import asyncio, json, os, sys, time, uuid
from datetime import datetime

sys.path.insert(0, '/opt/trading-bot')
os.chdir('/opt/trading-bot')
os.environ['OA_WEBHOOK_SECRET'] = 'test-webhook-secret-2026'

from ops_api.db import DatabaseManager
from ops_api.config import OpsApiConfig
from ops_api.webhook import handle_tradingview_webhook

config = OpsApiConfig(
    db_path="ops_data.db",
    webhook_secret="test-webhook-secret-2026",
    allowed_symbols=("NIFTY", "BANKNIFTY"),
)
db = DatabaseManager(config.db_path)

START = time.time()
DURATION = 900  # 15 minutes
CHECK_INTERVAL = 30  # check stats every 30s
WEBHOOK_INTERVAL = 2  # send webhook every 2 seconds
total_sent = 0
total_errors = 0

def elapsed():
    return int(time.time() - START)

def timestamp():
    return datetime.utcnow().strftime('%H:%M:%S')

def get_resource_usage():
    """Get CPU/memory/disk stats."""
    try:
        mem = open('/proc/meminfo').read().split('\n')
        mem_total = int([l for l in mem if 'MemTotal' in l][0].split()[1])
        mem_avail = int([l for l in mem if 'MemAvailable' in l][0].split()[1])
        mem_used_pct = round((1 - mem_avail / mem_total) * 100, 1)
    except:
        mem_used_pct = 0

    try:
        cpu = open('/proc/loadavg').read().strip().split()[:3]
    except:
        cpu = ['N/A', 'N/A', 'N/A']

    try:
        db_size = os.path.getsize('ops_data.db') / 1024  # KB
    except:
        db_size = 0

    try:
        disk = os.statvfs('/')
        disk_used_pct = round((1 - disk.f_bfree / disk.f_blocks) * 100, 1)
    except:
        disk_used_pct = 0

    return {
        'mem_used_pct': mem_used_pct,
        'cpu_load': f'{cpu[0]}/{cpu[1]}/{cpu[2]}',
        'db_size_kb': db_size,
        'disk_used_pct': disk_used_pct,
        'uptime_sec': elapsed(),
    }

async def send_webhook():
    """Send a webhook request."""
    global total_sent, total_errors
    try:
        payload = {
            "alert_id": f"soak-{uuid.uuid4().hex[:12]}",
            "symbol": "NIFTY" if total_sent % 2 == 0 else "BANKNIFTY",
            "side": "BUY" if total_sent % 2 == 0 else "SELL",
            "strategy": "soak_test",
            "price": 18500.0 + (total_sent % 100),
            "secret": "test-webhook-secret-2026",
        }
        result = await handle_tradingview_webhook(
            payload, db, "test-webhook-secret-2026", "127.0.0.1"
        )
        total_sent += 1
        if result.get("status") != "received" and result.get("status") != "duplicate":
            total_errors += 1
            return f"UNEXPECTED: {result.get('status')}"
        return None
    except Exception as e:
        total_errors += 1
        return str(e)

async def soak_loop():
    global total_sent, total_errors
    print(f"{timestamp()} Starting 15-min soak test...")
    print(f"{'─'*60}")

    last_check = time.time()

    while time.time() - START < DURATION:
        # Send a webhook
        err = await send_webhook()

        # Check resources every 30s
        now = time.time()
        if now - last_check >= CHECK_INTERVAL:
            last_check = now
            usage = get_resource_usage()
            print(f"{timestamp()} | Sent: {total_sent} | "
                  f"Err: {total_errors} | "
                  f"Mem: {usage['mem_used_pct']}% | "
                  f"CPU: {usage['cpu_load']} | "
                  f"DB: {usage['db_size_kb']:.0f}KB | "
                  f"Disk: {usage['disk_used_pct']}%")

            # Check DB integrity
            try:
                orders = db.get_recent_orders(limit=3)
                alerts = db.get_recent_alerts(limit=3)
                print(f"       Orders: {len(orders)} recent, "
                      f"Alerts: {len(alerts)} recent")
            except Exception as e:
                print(f"       DB ERROR: {e}")

            # Check if services are still up
            import subprocess
            try:
                result = subprocess.run(
                    ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
                     'http://localhost:8080/health'],
                    capture_output=True, text=True, timeout=5
                )
                api_status = result.stdout.strip()
            except:
                api_status = "DOWN"

            if api_status != "200":
                print(f"       ⚠️  API STATUS: {api_status}")

            print(f"{'─'*40}")

        # Wait before next webhook
        await asyncio.sleep(WEBHOOK_INTERVAL)  # seconds between webhooks

    # Final report
    duration = elapsed()
    usage = get_resource_usage()
    print(f"\n{'='*60}")
    print(f"  SOAK TEST COMPLETE")
    print(f"{'='*60}")
    print(f"  Duration: {duration}s")
    print(f"  Total webhooks sent: {total_sent}")
    print(f"  Total errors: {total_errors}")
    print(f"  Error rate: {round(total_errors/total_sent*100, 2) if total_sent else 0}%")
    print(f"  Final memory usage: {usage['mem_used_pct']}%")
    print(f"  Final CPU load: {usage['cpu_load']}")
    print(f"  DB size: {usage['db_size_kb']:.0f} KB")
    print(f"  Disk usage: {usage['disk_used_pct']}%")

asyncio.run(soak_loop())