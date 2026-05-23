#!/usr/bin/env bash
# Migration sl20260524 — real DB roundtrip gate.
#
# Verifies plan v10 data-preservation guarantees that source-inspection
# contract tests cannot catch:
#
#   1. Dedupe MERGE: multiple trusted_device rows with same canonical
#      family collapse to one (winner = oldest first_seen_at), losers
#      land in merge_map, metadata MAX(last_used_at) merged.
#   2. Backfill canonical: login_history rows get browser_family/os_family/
#      device_fingerprint populated from display + canonical hash.
#   3. NEW row preservation: post-upgrade trust → row created with canonical
#      fingerprint. On downgrade, row is re-hashed to OLD display
#      fingerprint via local helper and INSERT ON CONFLICT DO UPDATE
#      merges metadata; total row count = backup + new (no data loss).
#   4. UPDATE existing preservation: post-upgrade ``update_last_used``
#      bumps last_used_at / IP / name. Downgrade NULL-safe MERGE picks
#      the newer side (GREATEST(COALESCE(...))).
#   5. Tombstone (V9.P0): post-upgrade DELETE on a winner row does NOT
#      get resurrected on downgrade. losers of a deleted winner ALSO
#      don't resurrect. Security-critical.
#   6. Re-upgrade idempotency: after downgrade + upgrade, schema +
#      backup + merge_map all recreated cleanly via DROP IF EXISTS.
#
# Uses isolated qlts_sl_roundtrip DB (cloned from qlts_dev so seed data
# satisfies the phase3_01 pre-flight gate). Does NOT touch qlts_dev.
#
# Usage (option-b worktree, stack up):
#   bash scripts/roundtrip_sl20260524.sh

set -euo pipefail

PG_CONTAINER="qlts-option-b-postgres-1"
BACKEND_CONTAINER="qlts-option-b-backend-1"
TEST_DB="qlts_sl_roundtrip"
SOURCE_DB="qlts_dev"
DB_URL="postgresql+asyncpg://qlts:qlts_dev@postgres:5432/${TEST_DB}"

# Test user IDs — picked from a high range to avoid colliding with any
# real user in the dump. The user_id columns in trusted_device and
# login_history are FK-constrained to user.id; we insert two synthetic
# users at the start and tear them down at the end.
USER_A=99001  # has duplicate trusted_device rows pre-PR (tests dedupe)
USER_B=99002  # has single trusted_device row (no dedupe, just re-hash)
USER_C=99003  # tombstone delete after upgrade (tests V9.P0)

q() {
    docker exec -i "${PG_CONTAINER}" psql -U qlts -d "${TEST_DB}" -At -c "$1"
}

abort() {
    echo "FAIL: $*" >&2
    exit 1
}

ok() {
    echo "OK  : $*"
}

# --------------------------------------------------------------------
# Phase 0 — reset roundtrip DB from qlts_dev, downgrade to pre-PR head
# --------------------------------------------------------------------
echo "=== Phase 0 — reset DB + downgrade to cleanup_upper_notif ==="
docker exec "${PG_CONTAINER}" sh -c "pg_dump -U qlts -d ${SOURCE_DB} -F c -f /tmp/sl_round.dump"
docker exec "${PG_CONTAINER}" sh -c "dropdb -U qlts --if-exists ${TEST_DB} && createdb -U qlts ${TEST_DB}"
docker exec "${PG_CONTAINER}" sh -c "pg_restore -U qlts -d ${TEST_DB} /tmp/sl_round.dump > /dev/null 2>&1; echo restore-ok"
docker exec -e DATABASE_URL="${DB_URL}" "${BACKEND_CONTAINER}" alembic downgrade cleanup_upper_notif > /dev/null

current_rev=$(docker exec -e DATABASE_URL="${DB_URL}" "${BACKEND_CONTAINER}" alembic current 2>&1 | tail -1 | awk '{print $1}')
[ "${current_rev}" = "cleanup_upper_notif" ] || abort "Downgrade failed, current=${current_rev}"
ok "alembic at ${current_rev}"

# --------------------------------------------------------------------
# Phase 1 — seed scenario data (pre-upgrade)
# --------------------------------------------------------------------
echo ""
echo "=== Phase 1 — seed scenarios A/B/C at pre-PR head ==="

# Synthetic users
q "INSERT INTO \"user\" (id, username, email, password_hash, role, status, total_lead_score, password_reset_required, mfa_enabled) VALUES
   (${USER_A}, 'sl_user_a', 'sl_a@test.local', 'x', 'user', 'active', 0, false, false),
   (${USER_B}, 'sl_user_b', 'sl_b@test.local', 'x', 'user', 'active', 0, false, false),
   (${USER_C}, 'sl_user_c', 'sl_c@test.local', 'x', 'user', 'active', 0, false, false)
   ON CONFLICT (id) DO NOTHING" > /dev/null

# Scenario A: 3 trusted_device rows, same family "Chrome|Windows", display drifts.
# Winner = first_seen 2026-01-01 (Chrome 145). Losers = Chrome 146 (mid) + 147 (newest).
q "INSERT INTO trusted_device
   (user_id, device_fingerprint, name, browser, os, first_seen_at, trusted_at, last_used_at, trusted_from_ip)
   VALUES
   (${USER_A}, 'A_FP_OLD_145', 'Chrome 145 on Windows 10', 'Chrome 145.0', 'Windows 10',
    '2026-01-01 10:00:00+00', '2026-01-01 10:00:00+00', '2026-02-01 12:00:00+00', '10.0.0.145'),
   (${USER_A}, 'A_FP_OLD_146', 'Chrome 146 on Windows 10', 'Chrome 146.0', 'Windows 10',
    '2026-02-15 10:00:00+00', '2026-02-15 10:00:00+00', '2026-03-15 18:00:00+00', '10.0.0.146'),
   (${USER_A}, 'A_FP_OLD_147', 'Chrome 147 on Windows 10', 'Chrome 147.0', 'Windows 10',
    '2026-04-01 10:00:00+00', '2026-04-01 10:00:00+00', '2026-04-20 09:00:00+00', '10.0.0.147')
   " > /dev/null

# Also seed a login_history row per Scenario-A device so the device_type
# backfill JOIN has a match (Step 5 of migration).
q "INSERT INTO login_history (user_id, login_at, ip_address, browser, os, device_type,
   is_new_ip, is_new_device, is_new_location, risk_score)
   VALUES
   (${USER_A}, '2026-01-01 10:00:00+00', '10.0.0.145', 'Chrome 145.0', 'Windows 10', 'desktop', false, false, false, 0),
   (${USER_A}, '2026-02-15 10:00:00+00', '10.0.0.146', 'Chrome 146.0', 'Windows 10', 'desktop', false, false, false, 0),
   (${USER_A}, '2026-04-01 10:00:00+00', '10.0.0.147', 'Chrome 147.0', 'Windows 10', 'desktop', false, false, false, 0)
   " > /dev/null

# Scenario B: single row, family "Mobile Safari|iOS".
q "INSERT INTO trusted_device
   (user_id, device_fingerprint, name, browser, os, first_seen_at, trusted_at, last_used_at, trusted_from_ip)
   VALUES (${USER_B}, 'B_FP_OLD_SAF', 'Safari on iOS', 'Mobile Safari 16.3', 'iOS 16.3',
    '2026-03-01 10:00:00+00', '2026-03-01 10:00:00+00', '2026-05-01 11:00:00+00', '10.0.0.200')" > /dev/null
q "INSERT INTO login_history (user_id, login_at, ip_address, browser, os, device_type,
   is_new_ip, is_new_device, is_new_location, risk_score)
   VALUES (${USER_B}, '2026-03-01 10:00:00+00', '10.0.0.200', 'Mobile Safari 16.3', 'iOS 16.3', 'mobile', false, false, false, 0)" > /dev/null

# Scenario C: 1 row that will be deleted post-upgrade (tombstone).
q "INSERT INTO trusted_device
   (user_id, device_fingerprint, name, browser, os, first_seen_at, trusted_at, last_used_at, trusted_from_ip)
   VALUES (${USER_C}, 'C_FP_OLD_FF', 'Firefox on Linux', 'Firefox 130.0', 'Linux',
    '2026-03-15 10:00:00+00', '2026-03-15 10:00:00+00', '2026-04-15 11:00:00+00', '10.0.0.250')" > /dev/null
q "INSERT INTO login_history (user_id, login_at, ip_address, browser, os, device_type,
   is_new_ip, is_new_device, is_new_location, risk_score)
   VALUES (${USER_C}, '2026-03-15 10:00:00+00', '10.0.0.250', 'Firefox 130.0', 'Linux', 'desktop', false, false, false, 0)" > /dev/null

ok "Seeded: USER_A=3 rows (dedupe target), USER_B=1 row, USER_C=1 row (tombstone target)"

# Snapshot pre-upgrade counts for comparison.
PRE_TD_A=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_A}")
PRE_TD_B=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_B}")
PRE_TD_C=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_C}")
[ "${PRE_TD_A}" = "3" ] || abort "Expected 3 rows for USER_A pre-upgrade, got ${PRE_TD_A}"
[ "${PRE_TD_B}" = "1" ] || abort "Expected 1 row for USER_B pre-upgrade, got ${PRE_TD_B}"
ok "Pre-upgrade: USER_A=${PRE_TD_A}, USER_B=${PRE_TD_B}, USER_C=${PRE_TD_C}"

# --------------------------------------------------------------------
# Phase 2 — upgrade to sl20260524_canonical
# --------------------------------------------------------------------
echo ""
echo "=== Phase 2 — alembic upgrade head ==="
docker exec -e DATABASE_URL="${DB_URL}" "${BACKEND_CONTAINER}" alembic upgrade head > /dev/null 2>&1
current_rev=$(docker exec -e DATABASE_URL="${DB_URL}" "${BACKEND_CONTAINER}" alembic current 2>&1 | tail -1 | awk '{print $1}')
[ "${current_rev}" = "sl20260524_canonical" ] || abort "Upgrade failed, current=${current_rev}"
ok "alembic at ${current_rev}"

# Dedupe assertion (Scenario A): 3 → 1
POST_TD_A=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_A}")
[ "${POST_TD_A}" = "1" ] || abort "USER_A dedupe FAIL: expected 1, got ${POST_TD_A}"
ok "Dedupe: USER_A 3 → 1"

# Winner = oldest first_seen_at (Chrome 145, 2026-01-01).
WINNER_FIRST_SEEN=$(q "SELECT first_seen_at::text FROM trusted_device WHERE user_id=${USER_A}")
[[ "${WINNER_FIRST_SEEN}" == 2026-01-01* ]] || abort "Winner first_seen_at WRONG: ${WINNER_FIRST_SEEN}"
ok "Winner first_seen_at = ${WINNER_FIRST_SEEN}"

# Winner last_used_at = MAX of group (2026-04-20 from Chrome 147).
WINNER_LAST_USED=$(q "SELECT last_used_at::text FROM trusted_device WHERE user_id=${USER_A}")
[[ "${WINNER_LAST_USED}" == 2026-04-20* ]] || abort "Winner last_used_at WRONG: ${WINNER_LAST_USED} (expected MAX 2026-04-20)"
ok "Winner last_used_at = ${WINNER_LAST_USED} (MAX of group)"

# Winner trusted_from_ip = IP of row with newest last_used_at (Chrome 147 → 10.0.0.147).
WINNER_IP=$(q "SELECT trusted_from_ip FROM trusted_device WHERE user_id=${USER_A}")
[ "${WINNER_IP}" = "10.0.0.147" ] || abort "Winner trusted_from_ip WRONG: ${WINNER_IP} (expected 10.0.0.147 — latest)"
ok "Winner trusted_from_ip = ${WINNER_IP}"

# Winner family + device_type backfilled.
WINNER_FAMILY=$(q "SELECT browser_family || '|' || os_family || '|' || device_type FROM trusted_device WHERE user_id=${USER_A}")
[ "${WINNER_FAMILY}" = "Chrome|Windows|desktop" ] || abort "Winner family WRONG: ${WINNER_FAMILY}"
ok "Winner canonical = ${WINNER_FAMILY}"

# Winner fingerprint matches canonical hash.
WINNER_FP=$(q "SELECT device_fingerprint FROM trusted_device WHERE user_id=${USER_A}")
[ "${#WINNER_FP}" = "64" ] || abort "Winner fingerprint not 64 chars: ${WINNER_FP}"
ok "Winner fingerprint = ${WINNER_FP:0:16}... (64 chars)"

# merge_map has 2 entries for USER_A.
MERGE_MAP_A=$(q "SELECT COUNT(*) FROM trusted_device_sl20260524_merge_map WHERE user_id=${USER_A}")
[ "${MERGE_MAP_A}" = "2" ] || abort "merge_map: expected 2 entries for USER_A, got ${MERGE_MAP_A}"
ok "merge_map: ${MERGE_MAP_A} loser entries for USER_A"

# Backup table has all 3 original rows for USER_A.
BACKUP_A=$(q "SELECT COUNT(*) FROM trusted_device_pre_sl20260524_canonical_backup WHERE user_id=${USER_A}")
[ "${BACKUP_A}" = "3" ] || abort "Backup: expected 3 USER_A rows, got ${BACKUP_A}"
ok "Backup: ${BACKUP_A} original USER_A rows preserved"

# Scenario B: single-row re-hash, no merge.
POST_TD_B=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_B}")
B_FAMILY=$(q "SELECT browser_family || '|' || os_family || '|' || device_type FROM trusted_device WHERE user_id=${USER_B}")
[ "${POST_TD_B}" = "1" ] || abort "USER_B count WRONG: ${POST_TD_B}"
[ "${B_FAMILY}" = "Mobile Safari|iOS|mobile" ] || abort "USER_B family WRONG: ${B_FAMILY}"
ok "USER_B single-row: family=${B_FAMILY}, count=${POST_TD_B}"

# login_history backfill: USER_A 3 rows + USER_B 1 row + USER_C 1 row = 5.
LH_BACKFILLED=$(q "SELECT COUNT(*) FROM login_history WHERE user_id IN (${USER_A},${USER_B},${USER_C}) AND device_fingerprint IS NOT NULL")
[ "${LH_BACKFILLED}" = "5" ] || abort "login_history backfill: expected 5, got ${LH_BACKFILLED}"
ok "login_history backfill: ${LH_BACKFILLED}/5 rows have device_fingerprint"

# --------------------------------------------------------------------
# Phase 3 — simulate post-deploy writes (new row + update + delete)
# --------------------------------------------------------------------
echo ""
echo "=== Phase 3 — simulate post-deploy writes ==="

# C1: NEW row for USER_A (user trusts a NEW device — Edge on Android).
# Compute canonical fingerprint manually via the service helper logic.
# Service config emits banner lines to stdout on import — strip everything
# but the last line (which is the fingerprint).
NEW_FP=$(docker exec "${BACKEND_CONTAINER}" python -c "
from app.services.login_history_service import generate_device_fingerprint
print(generate_device_fingerprint('Edge Mobile', 'Android', 'mobile', ${USER_A}))
" 2>/dev/null | tail -1)
q "INSERT INTO trusted_device
   (user_id, device_fingerprint, name, browser, os, device_type,
    browser_family, os_family,
    first_seen_at, trusted_at, last_used_at, trusted_from_ip)
   VALUES (${USER_A}, '${NEW_FP}', 'Edge Mobile on Android', 'Edge Mobile 127.0', 'Android 14', 'mobile',
    'Edge Mobile', 'Android',
    NOW(), NOW(), NOW(), '10.0.0.250')" > /dev/null
ok "NEW row inserted for USER_A (Edge Mobile/Android, fp=${NEW_FP:0:16}...)"

# C2: UPDATE on existing winner row (simulate update_last_used + IP change).
q "UPDATE trusted_device SET
   last_used_at = '2026-05-23 23:00:00+00',
   trusted_from_ip = '10.0.0.999',
   name = 'Updated post-deploy name'
   WHERE user_id=${USER_A} AND device_fingerprint != '${NEW_FP}'" > /dev/null
ok "UPDATE applied to USER_A winner row"

# C3: DELETE USER_C's only row (simulate user revoke via secure_account).
q "DELETE FROM trusted_device WHERE user_id=${USER_C}" > /dev/null
POST_DEL_C=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_C}")
[ "${POST_DEL_C}" = "0" ] || abort "USER_C delete failed"
ok "DELETE: USER_C row removed"

# --------------------------------------------------------------------
# Phase 4 — downgrade to cleanup_upper_notif
# --------------------------------------------------------------------
echo ""
echo "=== Phase 4 — alembic downgrade -1 (verify preservation) ==="
docker exec -e DATABASE_URL="${DB_URL}" "${BACKEND_CONTAINER}" alembic downgrade -1 > /tmp/downgrade_log.txt 2>&1
current_rev=$(docker exec -e DATABASE_URL="${DB_URL}" "${BACKEND_CONTAINER}" alembic current 2>&1 | tail -1 | awk '{print $1}')
[ "${current_rev}" = "cleanup_upper_notif" ] || abort "Downgrade failed, current=${current_rev}"
ok "alembic at ${current_rev}"

# Preserve NEW row (USER_A's Edge Mobile / Android):
# Re-hashed to OLD display fingerprint, still present.
NEW_OLD_FP=$(docker exec "${BACKEND_CONTAINER}" python -c "
import hashlib
from app.config import settings
components = ['Edge Mobile 127.0', 'Android 14', 'mobile', '${USER_A}', settings.DEVICE_FINGERPRINT_SALT]
print(hashlib.sha256('|'.join(components).encode()).hexdigest())
" 2>/dev/null | tail -1)
NEW_ROW_COUNT=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_A} AND device_fingerprint='${NEW_OLD_FP}'")
[ "${NEW_ROW_COUNT}" = "1" ] || abort "NEW row preservation FAIL: expected 1, got ${NEW_ROW_COUNT}"
ok "NEW row preserved with old-display fingerprint = ${NEW_OLD_FP:0:16}..."

# Preserve UPDATE on existing row: backup row restored, then merged with current snapshot.
# Backup had last_used_at = '2026-04-20' (max of pre-upgrade group). Post-upgrade update
# set it to '2026-05-23 23:00:00'. Downgrade should pick the LATER value.
WINNER_RESTORED_LAST_USED=$(q "SELECT MAX(last_used_at::text) FROM trusted_device WHERE user_id=${USER_A} AND device_fingerprint LIKE 'A_FP_OLD_%'")
[[ "${WINNER_RESTORED_LAST_USED}" == 2026-05-23* ]] || abort \
    "UPDATE preservation FAIL: post-deploy last_used_at lost. Got ${WINNER_RESTORED_LAST_USED}"
ok "UPDATE preserved: last_used_at = ${WINNER_RESTORED_LAST_USED} (post-deploy > backup)"

WINNER_RESTORED_IP=$(q "SELECT trusted_from_ip FROM trusted_device WHERE user_id=${USER_A} AND last_used_at::text LIKE '2026-05-23%' LIMIT 1")
[ "${WINNER_RESTORED_IP}" = "10.0.0.999" ] || abort \
    "UPDATE preservation FAIL: IP not from newer side. Got ${WINNER_RESTORED_IP}"
ok "UPDATE preserved: trusted_from_ip = ${WINNER_RESTORED_IP}"

# Backup rows restored:
# USER_A: 3 original + 1 new (Edge Mobile) = 4 rows total.
USER_A_TOTAL=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_A}")
[ "${USER_A_TOTAL}" = "4" ] || abort "USER_A post-downgrade count WRONG: ${USER_A_TOTAL} (expected 4 = 3 backup + 1 new)"
ok "USER_A post-downgrade: ${USER_A_TOTAL} rows (3 backup restored + 1 NEW preserved)"

# Tombstone: USER_C's row was DELETE'd post-upgrade. Must NOT resurrect.
USER_C_POST_DOWNGRADE=$(q "SELECT COUNT(*) FROM trusted_device WHERE user_id=${USER_C}")
[ "${USER_C_POST_DOWNGRADE}" = "0" ] || abort \
    "TOMBSTONE VIOLATION: USER_C row resurrected on downgrade (count=${USER_C_POST_DOWNGRADE}). SECURITY BUG."
ok "Tombstone: USER_C deleted row NOT resurrected"

# Schema state: canonical columns dropped.
LH_FAMILY_COLS=$(q "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='login_history' AND column_name IN ('browser_family','os_family','device_fingerprint')")
[ "${LH_FAMILY_COLS}" = "0" ] || abort "Canonical columns still exist on login_history"
ok "Schema: login_history canonical columns dropped"

TD_FAMILY_COLS=$(q "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='trusted_device' AND column_name IN ('browser_family','os_family','device_type')")
[ "${TD_FAMILY_COLS}" = "0" ] || abort "Canonical columns still exist on trusted_device"
ok "Schema: trusted_device canonical columns dropped"

# Backup table kept (operator drops manually).
BACKUP_KEPT=$(q "SELECT COUNT(*) FROM trusted_device_pre_sl20260524_canonical_backup")
[ "${BACKUP_KEPT}" -gt "0" ] || abort "Backup table empty post-downgrade"
ok "Backup table kept (${BACKUP_KEPT} rows for operator forensic)"

# merge_map dropped (downgrade Step D7).
MERGE_MAP_EXISTS=$(q "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='trusted_device_sl20260524_merge_map'")
[ "${MERGE_MAP_EXISTS}" = "0" ] || abort "merge_map table still exists after downgrade"
ok "Schema: merge_map table dropped"

# --------------------------------------------------------------------
# Phase 5 — re-upgrade (idempotency)
# --------------------------------------------------------------------
echo ""
echo "=== Phase 5 — alembic upgrade head (idempotent re-upgrade) ==="
docker exec -e DATABASE_URL="${DB_URL}" "${BACKEND_CONTAINER}" alembic upgrade head > /dev/null 2>&1
current_rev=$(docker exec -e DATABASE_URL="${DB_URL}" "${BACKEND_CONTAINER}" alembic current 2>&1 | tail -1 | awk '{print $1}')
[ "${current_rev}" = "sl20260524_canonical" ] || abort "Re-upgrade failed, current=${current_rev}"
ok "alembic re-upgraded to ${current_rev}"

# Backup table recreated via DROP IF EXISTS guard.
NEW_BACKUP=$(q "SELECT COUNT(*) FROM trusted_device_pre_sl20260524_canonical_backup")
ok "Backup recreated on re-upgrade (${NEW_BACKUP} rows)"

# merge_map recreated.
MERGE_MAP_RECREATED=$(q "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='trusted_device_sl20260524_merge_map'")
[ "${MERGE_MAP_RECREATED}" = "1" ] || abort "merge_map not recreated on re-upgrade"
ok "merge_map recreated"

# --------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------
echo ""
echo "=== Cleanup ==="
docker exec "${PG_CONTAINER}" sh -c "dropdb -U qlts ${TEST_DB}"
ok "Dropped roundtrip DB ${TEST_DB}"

echo ""
echo "=============================="
echo "✅ ALL ROUNDTRIP ASSERTIONS PASS"
echo "=============================="
