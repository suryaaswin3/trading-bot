#!/usr/bin/env bash
# ── Update script — git pull, uv sync, restart services ──────────────────
#
#   bash deployment/update.sh
#
set -euo pipefail

REPO_DIR="/opt/trading-bot"
VENV_DIR="$REPO_DIR/.venv"

echo "==> Pulling latest code..."
cd "$REPO_DIR"
git pull

echo "==> Updating dependencies..."
source "$VENV_DIR/bin/activate"
uv sync

echo "==> Copying systemd service files (in case of changes)..."
cp "$REPO_DIR/deployment/ops-api.service" /etc/systemd/system/
cp "$REPO_DIR/deployment/scanner.service" /etc/systemd/system/
cp "$REPO_DIR/deployment/dashboard.service" /etc/systemd/system/
systemctl daemon-reload

echo "==> Restarting services..."
systemctl restart ops-api.service
systemctl restart scanner.service
systemctl restart dashboard.service

echo "==> Checking service status..."
for svc in ops-api scanner dashboard; do
    if systemctl is-active --quiet "$svc.service"; then
        echo "  ✓ $svc.service is running"
    else
        echo "  ✗ $svc.service is NOT running"
    fi
done

echo ""
echo "==> Update complete."