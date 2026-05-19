# Deploy trading bot to VPS and run setup.
# PowerShell script — run from the project root.
#
# Usage:
#   .\deploy.ps1
#
# Requires: ssh.exe, scp.exe (both from OpenSSH or Git for Windows)
#           You will be prompted for the VPS password ONCE during SSH key setup.

$VPS_HOST = "168.144.127.242"
$VPS_USER = "root"
$VPS_PATH = "/opt/trading-bot"
$LOCAL_PATH = $(Get-Location).Path
$SSH_KEY = "$HOME\.ssh\id_rsa_trading_bot"

Write-Host "=== Deploying trading bot to ${VPS_USER}@${VPS_HOST} ===" -ForegroundColor Cyan

# ── 0. SSH key setup (one-time) ──────────────────────────────────────
if (-not (Test-Path "$SSH_KEY.pub")) {
    Write-Host "[0/4] Generating SSH key (no passphrase)..." -ForegroundColor Green
    ssh-keygen -t rsa -b 4096 -f "$SSH_KEY" -N "" -q

    Write-Host "Copying public key to VPS (enter VPS password when prompted)..." -ForegroundColor Yellow
    $pubKey = Get-Content "$SSH_KEY.pub"
    ssh -o StrictHostKeyChecking=no "${VPS_USER}@${VPS_HOST}" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pubKey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" 2>&1

    if ($LASTEXITCODE -ne 0) {
        Write-Error "SSH key copy failed. Check the password and try again."
        exit 1
    }
    Write-Host "SSH key installed successfully." -ForegroundColor Green
} else {
    Write-Host "[0/4] SSH key already exists." -ForegroundColor Gray
}

function Run-Remote {
    param([string]$Cmd)
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$SSH_KEY" "${VPS_USER}@${VPS_HOST}" "$Cmd" 2>&1
}

# ── 1. Create remote directory ───────────────────────────────────────
Write-Host "[1/4] Creating remote directory..." -ForegroundColor Green
Run-Remote "mkdir -p ${VPS_PATH}" | Out-Null

# ── 2. Copy files via SCP (exclude junk) ─────────────────────────────
Write-Host "[2/4] Copying project files..." -ForegroundColor Green

$items = @(
    "pyproject.toml",
    "uv.lock",
    "generate_token.py",
    "start_bot.py",
    "credentials.env",
    ".env",
    "requirements-token.txt",
    "trading_bot",
    "ops_api",
    "dashboard",
    "systemd",
    "deploy.sh"
)

foreach ($item in $items) {
    $src = Join-Path $LOCAL_PATH $item
    if (Test-Path $src) {
        scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$SSH_KEY" -r "$src" "${VPS_USER}@${VPS_HOST}:${VPS_PATH}/" 2>&1 | Out-Null
        Write-Host "  Copied: $item" -ForegroundColor Gray
    } else {
        Write-Warning "  Skipped (not found): $item"
    }
}

# ── 3. Run deploy.sh on VPS ──────────────────────────────────────────
Write-Host "[3/4] Running setup script on VPS..." -ForegroundColor Green
Run-Remote "chmod +x ${VPS_PATH}/deploy.sh && ${VPS_PATH}/deploy.sh"

# ── 4. Verify deployment ─────────────────────────────────────────────
Write-Host "[4/4] Verifying deployment..." -ForegroundColor Green

$tz = Run-Remote "timedatectl | grep 'Time zone'" | Select-Object -Last 1
Write-Host "Timezone: $tz" -ForegroundColor Gray

$cron = Run-Remote "cat /etc/cron.d/trading-bot 2>/dev/null || echo 'NO CRON FILE'"
Write-Host "Cron jobs:" -ForegroundColor Gray
Write-Host "$cron" -ForegroundColor Gray

Write-Host ""
Write-Host "=== Deployment complete ===" -ForegroundColor Cyan
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  SSH: ssh -i ~\.ssh\id_rsa_trading_bot root@${VPS_HOST}" -ForegroundColor Yellow
Write-Host "  Check cron: crontab -l" -ForegroundColor Yellow
Write-Host "  Test run: cd ${VPS_PATH} && .venv/bin/python start_bot.py" -ForegroundColor Yellow
Write-Host "  Token log: tail -f /var/log/trading-bot/token.log" -ForegroundColor Yellow
Write-Host "  Bot log:   tail -f /var/log/trading-bot/bot.log" -ForegroundColor Yellow
