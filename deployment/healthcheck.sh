#!/usr/bin/env bash
# ── Health check utility ──────────────────────────────────────────────────
# Checks API health endpoint, service status, log errors, and disk usage.
#
#   bash deployment/healthcheck.sh
#
set -euo pipefail

API_URL="${1:-http://127.0.0.1:8080}"
PASS=0
FAIL=0
WARN=0

green() { echo -e "\033[32m✓ $1\033[0m"; ((PASS++)); }
red()   { echo -e "\033[31m✗ $1\033[0m"; ((FAIL++)); }
yellow(){ echo -e "\033[33m⚠ $1\033[0m"; ((WARN++)); }

echo "=========================================="
echo "  Trading Bot — Health Check"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=========================================="
echo ""

# ── 1. API health endpoint ────────────────────────────────────────────────
echo "--- API Health ---"
if health_json=$(curl -sS --fail "$API_URL/health" 2>&1); then
    status=$(echo "$health_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
    if [ "$status" = "pass" ]; then
        green "API health: $status"
    elif [ "$status" = "warn" ]; then
        yellow "API health: $status"
        echo "$health_json" | python3 -c "
import sys,json
data = json.load(sys.stdin)
for c in data.get('checks', []):
    if c.get('status') != 'pass':
        print(f'  {c[\"component\"]}: {c[\"status\"]} — {c[\"detail\"]}')
" 2>/dev/null || true
    else
        red "API health: $status"
    fi
else
    red "API endpoint unreachable: $API_URL/health"
fi

# ── 2. Service status ─────────────────────────────────────────────────────
echo ""
echo "--- Service Status ---"
for svc in ops-api scanner dashboard; do
    if systemctl is-active --quiet "$svc.service" 2>/dev/null; then
        green "$svc.service is running"
    else
        # Check if service file exists
        if [ -f "/etc/systemd/system/$svc.service" ]; then
            red "$svc.service is NOT running"
        else
            yellow "$svc.service not installed"
        fi
    fi
done

# ── 3. Log errors (last 5 min) ─────────────────────────────────────────────
echo ""
echo "--- Recent Log Errors (last 5 min) ---"
LOG_DIR="/var/log/trading-bot"
if [ -d "$LOG_DIR" ]; then
    found=0
    for logfile in "$LOG_DIR"/*.log; do
        [ -f "$logfile" ] || continue
        errors=$(grep -i "ERROR|CRITICAL|Traceback" "$logfile" 2>/dev/null | tail -5 || true)
        if [ -n "$errors" ]; then
            echo "  $logfile:"
            echo "$errors" | while IFS= read -r line; do
                echo "    $line"
            done
            found=1
        fi
    done
    if [ "$found" -eq 0 ]; then
        green "No recent errors"
    fi
else
    yellow "Log directory not found"
fi

# ── 4. Disk usage ─────────────────────────────────────────────────────────
echo ""
echo "--- Disk Usage ---"
df -h / | awk 'NR==2 {print "  Used: " $3 " / " $2 " (" $5 ")"}'

# ── 5. Database file ──────────────────────────────────────────────────────
echo ""
echo "--- Database ---"
DB_PATH="/opt/trading-bot/ops_data.db"
if [ -f "$DB_PATH" ]; then
    db_size=$(du -h "$DB_PATH" | cut -f1)
    green "Database: $DB_PATH ($db_size)"
    # Check WAL mode
    wal_mode=$(sqlite3 "$DB_PATH" "PRAGMA journal_mode;" 2>/dev/null || echo "unknown")
    echo "  Journal mode: $wal_mode"
else
    red "Database file not found: $DB_PATH"
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  Summary: $PASS passed, $WARN warnings, $FAIL failures"
echo "=========================================="

# Exit with failure if any check failed
[ "$FAIL" -eq 0 ] || exit 1