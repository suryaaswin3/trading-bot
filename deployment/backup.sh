#!/usr/bin/env bash
# ── Backup script — DB snapshot + log archive ─────────────────────────────
# Creates timestamped backups in /opt/trading-bot/backups/ with 30-day
# retention for backups and 7-day retention for log archives.
#
#   bash deployment/backup.sh
#   bash deployment/backup.sh /custom/backup/path
#
# Recommended cron: daily at 02:00 IST (20:30 UTC previous day)
#   30 20 * * * /opt/trading-bot/deployment/backup.sh
#
set -euo pipefail

REPO_DIR="/opt/trading-bot"
BACKUP_DIR="${1:-$REPO_DIR/backups}"
LOG_DIR="/var/log/trading-bot"
TIMESTAMP=$(date -u '+%Y%m%d_%H%M%S')
RETENTION_DAYS=30
LOG_RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

echo "==> Backup started: $TIMESTAMP"

# ── 1. Database backup (SQLite .backup — safe with WAL mode) ─────────────
DB_PATH="$REPO_DIR/ops_data.db"
if [ -f "$DB_PATH" ]; then
    DB_BACKUP="$BACKUP_DIR/ops_data_$TIMESTAMP.db"
    sqlite3 "$DB_PATH" ".backup '$DB_BACKUP'"
    gzip "$DB_BACKUP"
    db_size=$(du -h "$DB_PATH" | cut -f1)
    echo "  ✓ Database backed up ($db_size → ${DB_BACKUP}.gz)"
else
    echo "  ⚠ Database file not found, skipping"
fi

# ── 2. Log archive ────────────────────────────────────────────────────────
if [ -d "$LOG_DIR" ] && [ "$(ls -A "$LOG_DIR" 2>/dev/null)" ]; then
    LOG_ARCHIVE="$BACKUP_DIR/logs_$TIMESTAMP.tar.gz"
    tar -czf "$LOG_ARCHIVE" -C "$LOG_DIR" .
    echo "  ✓ Logs archived: $LOG_ARCHIVE"
else
    echo "  ⚠ Log directory empty or not found, skipping"
fi

# ── 3. Cleanup old backups (30 days) ──────────────────────────────────────
echo "  → Cleaning backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "ops_data_*.db.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "logs_*.tar.gz" -mtime +$LOG_RETENTION_DAYS -delete 2>/dev/null || true

# ── 4. Summary ────────────────────────────────────────────────────────────
echo "==> Backup complete: $BACKUP_DIR"
echo ""
echo "Backup directory contents:"
ls -lh "$BACKUP_DIR" | tail -10