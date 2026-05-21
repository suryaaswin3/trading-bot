#!/usr/bin/env bash
# ── One-time VPS setup script ─────────────────────────────────────────────
# Run on the VPS after cloning the repository:
#
#   ssh root@168.144.127.242
#   cd /opt/trading-bot
#   bash deployment/install.sh
#
set -euo pipefail

REPO_DIR="/opt/trading-bot"
VENV_DIR="$REPO_DIR/.venv"
LOG_DIR="/var/log/trading-bot"

echo "==> Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    curl sqlite3 nginx ufw python3-full python3-pip

echo "==> Creating log directory..."
mkdir -p "$LOG_DIR"
chmod 755 "$LOG_DIR"

echo "==> Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    uv venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

echo "==> Installing Python dependencies..."
cd "$REPO_DIR"
uv sync

echo "==> Configuring firewall..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 8080/tcp
ufw allow 8501/tcp
ufw --force enable

echo "==> Installing systemd services..."
cp "$REPO_DIR/deployment/ops-api.service" /etc/systemd/system/
cp "$REPO_DIR/deployment/scanner.service" /etc/systemd/system/
cp "$REPO_DIR/deployment/dashboard.service" /etc/systemd/system/

systemctl daemon-reload

echo "==> Enabling services for auto-start on boot..."
systemctl enable ops-api.service
systemctl enable scanner.service
systemctl enable dashboard.service

echo "==> Setting up basic nginx reverse proxy..."
cat > /etc/nginx/sites-available/ops-api << 'NGINX'
server {
    listen 80;
    server_name _;

    location /webhook/tradingview {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /health {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }

    location /dashboard {
        proxy_pass http://127.0.0.1:8501;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX

ln -sf /etc/nginx/sites-available/ops-api /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo ""
echo "==> Installation complete!"
echo "    Next steps:"
echo "    1. Configure secrets: nano $REPO_DIR/.env"
echo "    2. Start services: systemctl start ops-api.service scanner.service"
echo "    3. Check health: bash $REPO_DIR/deployment/healthcheck.sh"
echo ""
echo "    IMPORTANT: OA_LIVE_TRADING defaults to false!"
echo "    Set OA_LIVE_TRADING=true only after paper testing."