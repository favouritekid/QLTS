#!/usr/bin/env bash
# Backup local (backup-cron.sh) + đẩy bản mã hóa lên Google Drive
set -euo pipefail
cd /opt/qlts
bash scripts/backup-cron.sh
LATEST=$(ls -t backups/qlts_*.sql.gz | head -1)
if rclone listremotes | grep -q '^gdrive-crypt:'; then
  echo "[$(date)] Offsite: upload mã hóa $(basename "$LATEST") lên Google Drive..."
  rclone copy "$LATEST" gdrive-crypt:
  rclone delete gdrive-crypt: --min-age 14d 2>/dev/null || true
  echo "[$(date)] Offsite OK"
else
  echo "[$(date)] WARN: remote gdrive-crypt không có → bỏ qua offsite"
fi
