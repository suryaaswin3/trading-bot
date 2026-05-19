#!/usr/bin/env bash
# One-time setup script for the VPS trading bot deployment.
# Installs deps, sets up git, installs systemd timer for 9 AM IST start.
# Run as root on the VPS after copying the project files to /opt/trading-bot/.
set -euo pipefail

BOT_DIR="/opt/trading-bot"
LOG_DIR="/var/log/trading-bot"

echo "=== Trading bot VPS setup ==="

# ── 1. System dependencies ────────────────────────────────────────────
echo "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv curl git nginx 2>&1 | tail -1

# Install uv (fast Python package installer)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# ── 2. Timezone → Asia/Kolkata ────────────────────────────────────────
echo "[2/8] Setting timezone to Asia/Kolkata..."
timedatectl set-timezone Asia/Kolkata 2>/dev/null || \
    ln -sf /usr/share/zoneinfo/Asia/Kolkata /etc/localtime

# ── 3. Verify project files exist ─────────────────────────────────────
echo "[3/8] Verifying project files..."
cd "$BOT_DIR"

for f in pyproject.toml generate_token.py start_bot.py credentials.env .env requirements-token.txt; do
    if [ ! -f "$f" ]; then
        echo "ERROR: Missing required file: $f"
        exit 1
    fi
done

if [ ! -d "trading_bot" ]; then
    echo "ERROR: Missing trading_bot/ directory"
    exit 1
fi

# ── 4. Python virtual environment & dependencies ──────────────────────
echo "[4/8] Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

pip install --quiet --upgrade pip

echo "Installing main project dependencies..."
pip install --quiet -r requirements-token.txt

echo "Installing trading bot dependencies..."
pip install --quiet kiteconnect pytz loguru

echo "Installing ops API dependencies..."
pip install --quiet streamlit plotly httpx uvicorn fastapi

# ── 5. Create log directory ──────────────────────────────────────────
echo "[5/8] Creating log directory..."
mkdir -p "$LOG_DIR"
chmod 755 "$LOG_DIR"

# ── 6. Initialize git (for future pull-based updates) ──────────────────
echo "[6/8] Initializing git repository..."
cd "$BOT_DIR"

if [ ! -d ".git" ]; then
    git init
    git add -A
    git config user.email "deploy@trading-bot"
    git config user.name "Deploy"
    git commit -m "Initial deployment" --allow-empty
    echo "  Git repository initialized with initial commit."
else
    # Add any new untracked files
    git add -A
    if ! git diff --cached --quiet; then
        git commit -m "Update deployment $(date +%Y-%m-%d_%H:%M:%S)"
        echo "  New changes committed."
    else
        echo "  Git repository already up to date."
    fi
fi

# ── 7. Set up systemd service + timer ──────────────────────────────────
echo "[7/8] Setting up systemd service and timer..."

# Systemd service unit
cat > /etc/systemd/system/trading-bot.service << 'UNITEOF'
[Unit]
Description=Trading Bot — Zerodha Nifty Options
Documentation=https://github.com/your-repo
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=root
WorkingDirectory=/opt/trading-bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/trading-bot/.venv/bin/python /opt/trading-bot/start_bot.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/var/log/trading-bot/bot.log
StandardError=append:/var/log/trading-bot/bot.log

[Install]
WantedBy=multi-user.target
UNITEOF

# Systemd timer — Mon-Fri 9:00 AM IST
cat > /etc/systemd/system/trading-bot.timer << 'TIMEREOF'
[Unit]
Description=Start trading bot at 9:00 AM IST weekdays

[Timer]
OnCalendar=Mon..Fri *-*-* 09:00:00 Asia/Kolkata
Persistent=false

[Install]
WantedBy=timers.target
TIMEREOF

# ── 7b. Ops API service (runs 24/7) ──────────────────────────────────────
cat > /etc/systemd/system/ops-api.service << 'OPSEOF'
[Unit]
Description=Trading Bot Ops API — FastAPI webhook/control/health server
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=root
WorkingDirectory=/opt/trading-bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/trading-bot/.venv/bin/python -m uvicorn ops_api.main:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5
StandardOutput=append:/var/log/trading-bot/ops-api.log
StandardError=append:/var/log/trading-bot/ops-api.log

[Install]
WantedBy=multi-user.target
OPSEOF

# ── 7c. Dashboard service (runs 24/7) ─────────────────────────────────────
cat > /etc/systemd/system/dashboard.service << 'DASHEOF'
[Unit]
Description=Trading Bot Dashboard — Streamlit UI
After=network-online.target ops-api.service
Wants=network-online.target

[Service]
Type=exec
User=root
WorkingDirectory=/opt/trading-bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/trading-bot/.venv/bin/python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true
Restart=always
RestartSec=10
StandardOutput=append:/var/log/trading-bot/dashboard.log
StandardError=append:/var/log/trading-bot/dashboard.log

[Install]
WantedBy=multi-user.target
DASHEOF

# Reload systemd + enable timer and services
systemctl daemon-reload
systemctl enable trading-bot.timer
systemctl start trading-bot.timer
systemctl enable ops-api.service
systemctl start ops-api.service
systemctl enable dashboard.service
systemctl start dashboard.service

# ── 7e. Nginx reverse proxy for TradingView webhooks ──────────────────────
echo "[8/9] Configuring Nginx reverse proxy..."

# Copy Nginx config
cp "$BOT_DIR/ops_api/nginx-tradingview.conf" /etc/nginx/sites-available/tradingview-webhook

# Enable site
ln -sf /etc/nginx/sites-available/tradingview-webhook /etc/nginx/sites-enabled/

# Remove default nginx site if it exists (it binds port 80)
rm -f /etc/nginx/sites-enabled/default

# Test config
nginx -t

# Reload to apply
systemctl reload nginx || systemctl restart nginx

echo "[8/9] Nginx configured: port 80 → 127.0.0.1:8080/webhook/tradingview"

# ── Update cron (token gen only, no start_bot.py) ───────────────────────
echo "[7d/9] Updating cron for token generation..."

CRON_FILE="/etc/cron.d/trading-bot"

cat > "$CRON_FILE" << 'CRONEOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/trading-bot/.venv/bin

# Generate fresh access token at 8:45 AM IST (weekdays)
45 8 * * 1-5 root cd /opt/trading-bot && .venv/bin/python generate_token.py >> /var/log/trading-bot/token.log 2>&1
CRONEOF

chmod 644 "$CRON_FILE"

# ── 8. Test-run token generation ─────────────────────────────────────
echo "[9/9] Testing token generation..."
cd "$BOT_DIR"
.venv/bin/python generate_token.py || {
    echo "WARNING: Token generation test failed."
    echo "This is expected outside market hours or if credentials need review."
    echo "The cron job will retry at 8:45 AM IST."
}

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo "=== Setup complete ==="
echo "Timezone: $(timedatectl | grep 'Time zone')"
echo ""
echo "Systemd timer (next run):"
systemctl list-timers trading-bot.timer --no-pager 2>/dev/null || echo "  (timer not found)"
echo ""
echo "Systemd service status:"
systemctl status trading-bot.service --no-pager 2>/dev/null | head -5
echo ""
echo "Cron (token gen only):"
cat "$CRON_FILE"
echo ""
echo "To verify manually:"
echo "  systemctl list-timers trading-bot.timer"
echo "  systemctl status trading-bot.service"
echo "  cd /opt/trading-bot && .venv/bin/python generate_token.py"
echo ""
echo "To test graceful shutdown (after timer fires or manual start):"
echo "  systemctl start trading-bot.service"
echo "  sleep 5"
echo "  systemctl stop trading-bot.service"
echo "  journalctl -u trading-bot.service --no-pager -n 20"
echo ""
echo "Logs:"
echo "  Token: tail -f /var/log/trading-bot/token.log"
echo "  Bot:   tail -f /var/log/trading-bot/bot.log"
