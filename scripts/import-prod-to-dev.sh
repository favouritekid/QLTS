#!/bin/bash
# ==============================================================================
# import-prod-to-dev.sh — Solo dev cutover rehearsal helper
# ==============================================================================
#
# Imports production data selectively into the local dev PostgreSQL container so
# the next migration (Wave 3 ⚠ ONE-WAY) can be rehearsed against realistic data
# before the maintenance-window cutover.
#
# Memory ref: feedback_solo_cutover_simple_data_import.md
#
# Usage:
#   1. Set env vars VPS_HOST + VPS_USER (or edit defaults below).
#   2. ./scripts/import-prod-to-dev.sh
#
# What this does:
#   * Step 1 — pg_dump prod selectively (state/ref tables, skip logs/sessions).
#   * Step 2 — wipe local dev postgres volume.
#   * Step 3 — restore dump into fresh local postgres.
#   * Step 4 — alembic upgrade head (dev image picks up Wave 1+2+5 chain).
#   * Step 5 — quick smoke counts.
#
# What this does NOT do:
#   * Run Wave 3 migrations (those are still being authored).
#   * Anonymize PII (acceptable for solo dev controlled env).
#   * Touch prod (read-only pg_dump).
#
# Hard rules:
#   * The dump file lives in ./local_backup/ which is in .gitignore.
#   * Dump filename includes timestamp so the latest is always findable.
#   * Wipe step requires manual confirmation (typed "yes"), not just defaulted.
# ==============================================================================
set -euo pipefail

VPS_HOST="${VPS_HOST:-vps}"
VPS_USER="${VPS_USER:-$(whoami)}"
PROD_DB_NAME="${PROD_DB_NAME:-qlts}"
PROD_DB_USER="${PROD_DB_USER:-qlts}"
DEV_DB_NAME="${DEV_DB_NAME:-qlts_dev}"
DEV_DB_USER="${DEV_DB_USER:-qlts}"

# Tables to import — state machines + reference data + RBAC + finance + admission
# rules. Order does not matter for pg_dump; restore handles FK ordering.
INCLUDE_TABLES=(
    # Identity / RBAC
    "user"
    "casbin_rule"
    "organization_unit"
    # Admission core
    "lead"
    "admission_profile"
    "admission_path"
    "admission_method"
    "admission_criteria"
    "admission_confirmation_token"
    # Academic / program
    "subject"
    "subject_group"
    "subject_group_subject"
    "criteria_subject_group"
    "path_subject_group_config"
    "path_subject_group_item"
    "major_program"
    "degree_level"
    "offering_academic_info"
    "offering_admission_round"
    "offering_admission_config"
    "program_offering"
    # Documents
    "document_group"
    "config_document_type"
    "profile_document"
    # Consultation
    "lead_consultation_status"
    "consultation_status_history"
    # Post-enrollment
    "student"
    "student_document"
    # Finance
    "fee"
    "tuition_fee"
    "tuition_discount_policy"
    "payment"
    "installment_plan"
    # Notification (DB-seeded by Wave 5-A)
    "notification_rule"
    "notification_template"
    "notification_action"
    # System
    "system_config"
    # Zalo
    "staff_zalo_bot_link"
)

# Tables intentionally SKIPPED — transient logs / sessions / queue / heavy audit
# trails. Recreated empty post-migration.
EXCLUDE_TABLES=(
    "notification"
    "notification_outbox"
    "notification_delivery"
    "notification_quota"
    "user_session"
    "user_activity_log"
    "entity_audit_log"
    "_admission_backfill_exceptions"
)

mkdir -p ./local_backup

DUMP_FILE="./local_backup/prod_$(date +%Y%m%d_%H%M%S).sql"

echo "================================================================"
echo "Step 1: pg_dump prod (selective) → $DUMP_FILE"
echo "================================================================"
TABLE_FLAGS=""
for tbl in "${INCLUDE_TABLES[@]}"; do
    TABLE_FLAGS="$TABLE_FLAGS --table=public.$tbl"
done

ssh "${VPS_USER}@${VPS_HOST}" \
    "docker compose exec -T postgres pg_dump -U ${PROD_DB_USER} ${PROD_DB_NAME} \
        --data-only --column-inserts --disable-triggers $TABLE_FLAGS" \
    > "$DUMP_FILE"

DUMP_SIZE=$(du -h "$DUMP_FILE" | awk '{print $1}')
echo "✅ Dump size: $DUMP_SIZE"
echo ""

echo "================================================================"
echo "Step 2: Wipe local dev postgres volume"
echo "================================================================"
echo "⚠️  This will DELETE all data in your local dev DB."
read -r -p "Type 'yes' to confirm: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted by user."
    exit 1
fi

docker compose down postgres
docker volume rm qlts_postgres_data || echo "(volume already gone)"
docker compose up -d postgres
echo "Waiting for postgres healthy..."
until docker compose exec -T postgres pg_isready -U "${DEV_DB_USER}" >/dev/null 2>&1; do
    sleep 2
done
echo "✅ Fresh postgres ready"
echo ""

echo "================================================================"
echo "Step 3: Run base alembic migrations on empty dev DB"
echo "================================================================"
# Bring schema to phase1_19e (Wave 5 head) BEFORE restoring data so the data
# fits the current schema. Wave 3 migrations are NOT in the chain yet — they
# will be applied AFTER rehearsal in step 5 once authored.
docker compose up -d backend
docker compose exec -T backend alembic upgrade head
echo "✅ Schema at alembic head (phase1_19e)"
echo ""

echo "================================================================"
echo "Step 4: Restore prod data into dev DB"
echo "================================================================"
docker compose exec -T postgres psql -U "${DEV_DB_USER}" -d "${DEV_DB_NAME}" < "$DUMP_FILE"
echo "✅ Data restored"
echo ""

echo "================================================================"
echo "Step 5: Smoke counts"
echo "================================================================"
docker compose exec -T postgres psql -U "${DEV_DB_USER}" -d "${DEV_DB_NAME}" -c "
    SELECT 'lead' AS table, COUNT(*) FROM lead
    UNION ALL SELECT 'admission_profile', COUNT(*) FROM admission_profile
    UNION ALL SELECT 'user', COUNT(*) FROM \"user\"
    UNION ALL SELECT 'admission_path', COUNT(*) FROM admission_path
    UNION ALL SELECT 'casbin_rule', COUNT(*) FROM casbin_rule
    UNION ALL SELECT 'notification_rule', COUNT(*) FROM notification_rule
    UNION ALL SELECT 'system_config', COUNT(*) FROM system_config
    ORDER BY 1;
"

echo ""
echo "================================================================"
echo "✅ Dev DB rehearsal-ready with prod data."
echo "================================================================"
echo ""
echo "Next step: implement Wave 3 ⚠ ONE-WAY migrations (phase1_11/12/15a/18)"
echo "and run 'docker compose exec backend alembic upgrade head' to rehearse"
echo "the full chain end-to-end against this prod-data baseline."
echo ""
echo "Backup file kept at: $DUMP_FILE"
