#!/usr/bin/env bash
# Phase 3 pre-deploy DB snapshot script
# Trigger: 1h trước Wave B+0 deploy (target 2026-06-15)
# Plan ref: noble-launching-cocoa.md v0.3 + PHASE3_ROLLBACK_RUNBOOK.md Strategy C
#
# Usage:
#   ./scripts/phase3-pre-deploy-snapshot.sh
#
# Output: /backups/qlts_prod_pre_phase3_YYYYMMDD_HHMMSS.dump + verification log

set -euo pipefail

# Config (override via env if needed)
BACKUP_DIR="${BACKUP_DIR:-/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SNAPSHOT_NAME="qlts_prod_pre_phase3_${TIMESTAMP}.dump"
SNAPSHOT_PATH="${BACKUP_DIR}/${SNAPSHOT_NAME}"
LOG_FILE="${BACKUP_DIR}/${SNAPSHOT_NAME}.log"

# Verify backup dir exists + writable
if [[ ! -d "${BACKUP_DIR}" ]]; then
  echo "ERROR: Backup directory ${BACKUP_DIR} does not exist" >&2
  exit 1
fi

if [[ ! -w "${BACKUP_DIR}" ]]; then
  echo "ERROR: Backup directory ${BACKUP_DIR} not writable" >&2
  exit 1
fi

echo "==== Phase 3 pre-deploy snapshot ===="
echo "Started: $(date -u +%FT%TZ)"
echo "Target: ${SNAPSHOT_PATH}"
echo ""

# Step 1: Capture current alembic version (for restore verification)
echo "[1/4] Capturing alembic version..."
ALEMBIC_VERSION=$(docker compose exec -T postgres psql -U qlts -d qlts -t -c \
  "SELECT version_num FROM alembic_version" 2>&1 | tr -d ' \n' || echo "UNKNOWN")
echo "Alembic version: ${ALEMBIC_VERSION}" | tee -a "${LOG_FILE}"

# Expected: phase2_06 (Phase 2 PR-2D.1 v4a head)
if [[ "${ALEMBIC_VERSION}" != "phase2_06" ]]; then
  echo "WARNING: Expected alembic head 'phase2_06', got '${ALEMBIC_VERSION}'" | tee -a "${LOG_FILE}"
  echo "Continuing snapshot but verify post-restore manually." | tee -a "${LOG_FILE}"
fi

# Step 2: Capture row counts (for restore verification)
echo "[2/4] Capturing table row counts..."
docker compose exec -T postgres psql -U qlts -d qlts -c "
SELECT 'admission_profile' AS table, COUNT(*) FROM admission_profile
UNION ALL SELECT 'admission_path', COUNT(*) FROM admission_path
UNION ALL SELECT 'offering_admission_round', COUNT(*) FROM offering_admission_round
UNION ALL SELECT 'admission_confirmation_token', COUNT(*) FROM admission_confirmation_token
UNION ALL SELECT 'notification_outbox', COUNT(*) FROM notification_outbox
UNION ALL SELECT 'notification_rule', COUNT(*) FROM notification_rule;
" 2>&1 | tee -a "${LOG_FILE}"

# Step 3: pg_dump custom format
echo "[3/4] Running pg_dump (custom format)..."
docker compose exec -T postgres pg_dump -U qlts \
  --format=custom \
  --no-owner \
  --no-acl \
  --file=/tmp/snapshot.dump \
  qlts

docker compose cp postgres:/tmp/snapshot.dump "${SNAPSHOT_PATH}"
docker compose exec -T postgres rm /tmp/snapshot.dump

SNAPSHOT_SIZE=$(stat -c%s "${SNAPSHOT_PATH}" 2>/dev/null || stat -f%z "${SNAPSHOT_PATH}")
echo "Snapshot size: $(numfmt --to=iec ${SNAPSHOT_SIZE}) (${SNAPSHOT_SIZE} bytes)" | tee -a "${LOG_FILE}"

# Step 4: Verify integrity (pg_restore --list parse-only)
echo "[4/4] Verifying snapshot integrity..."
RESTORE_LIST=$(pg_restore --list "${SNAPSHOT_PATH}" 2>&1 | head -5)
if [[ -z "${RESTORE_LIST}" ]]; then
  echo "ERROR: pg_restore --list returned empty — snapshot may be corrupted" >&2
  exit 2
fi
echo "Integrity check PASS — first 5 entries:" | tee -a "${LOG_FILE}"
echo "${RESTORE_LIST}" | tee -a "${LOG_FILE}"

echo ""
echo "==== Snapshot complete ===="
echo "Path: ${SNAPSHOT_PATH}"
echo "Log: ${LOG_FILE}"
echo "Restore command:"
echo "  docker compose exec postgres pg_restore -U qlts -d qlts ${SNAPSHOT_PATH}"
echo ""

# MD5 checksum (final integrity stamp)
md5sum "${SNAPSHOT_PATH}" | tee -a "${LOG_FILE}"
