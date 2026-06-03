# Phase 3 PR-3A Post-Deploy Smoke Checklist

**Deploy run**: `25708398296`
**Main HEAD**: `1cd2f184`
**Migration**: `phase3_01_create_admission_profile_choice_and_score`
**Date**: 2026-05-12

Run sau khi GH Actions deploy job complete + backend container healthy.

## 1. Migration applied

```bash
ssh prod
cd /opt/qlts
docker compose -f docker-compose.yml --profile production --env-file .env.production exec postgres \
  psql -U qlts -d qlts_production -c "SELECT version_num FROM alembic_version;"
# Expected: phase3_01
```

## 2. New tables schema verify

```sql
-- admission_profile_choice
\d admission_profile_choice
-- Expected:
--   10 columns: id, admission_profile_id, admission_path_id,
--     path_subject_group_config_id, display_order, decision,
--     waitlist_rank, eligibility_check_result, bonus_rule_snapshot,
--     created_at, updated_at
--   UNIQUE: (admission_profile_id, admission_path_id, path_subject_group_config_id)
--   UNIQUE: (admission_profile_id, display_order)
--   CHECK: display_order BETWEEN 1 AND 10
--   CHECK: decision IN ('pending','admitted','waitlisted','rejected','skip')
--   FK: admission_profile_id → admission_profile.id ON DELETE CASCADE
--   FK: admission_path_id → admission_path.id ON DELETE RESTRICT
--   FK: path_subject_group_config_id → path_subject_group_config.id ON DELETE RESTRICT

-- profile_choice_score
\d profile_choice_score
-- Expected:
--   6 columns: id, admission_profile_choice_id, subject_id, score,
--     max_score_snapshot, min_possible_score_snapshot, weight_snapshot
--   UNIQUE: (admission_profile_choice_id, subject_id)
--   CHECK: score >= 0
--   FK: admission_profile_choice_id → admission_profile_choice.id ON DELETE CASCADE
--   FK: subject_id → subject.id ON DELETE RESTRICT
```

## 3. ALTER columns present

```sql
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'offering_admission_round'
  AND column_name IN ('allow_multi_nv', 'confirm_expiry_hours');
-- Expected:
--   allow_multi_nv | boolean | false | NO
--   confirm_expiry_hours | integer | 168 | NO

SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'notification_rule'
  AND column_name = 'bypass_consent';
-- Expected:
--   bypass_consent | boolean | false | NO
```

## 4. Seed verify

```sql
-- Q-P3-01 system_config
SELECT key, value FROM system_config WHERE key = 'max_choices_per_profile';
-- Expected: max_choices_per_profile | 5

-- Q-P3-07 bypass_consent 5 events flipped
SELECT event, bypass_consent FROM notification_rule
WHERE bypass_consent = true
ORDER BY event;
-- Expected 5 rows:
--   ADMISSION_DECISION_ADMITTED      | t
--   ADMISSION_DECISION_REJECTED       | t
--   ADMISSION_DECISION_WAITLISTED     | t
--   ADMISSION_ENROLLED                | t
--   ADMISSION_RESULT_PUBLISHED        | t
```

## 5. Regression — Phase 1/2 unaffected

```sql
-- Row counts unchanged
SELECT 'admission_profile' AS tbl, COUNT(*) FROM admission_profile
UNION ALL SELECT 'admission_path', COUNT(*) FROM admission_path
UNION ALL SELECT 'offering_admission_round', COUNT(*) FROM offering_admission_round
UNION ALL SELECT 'path_subject_group_config', COUNT(*) FROM path_subject_group_config
UNION ALL SELECT 'notification_rule', COUNT(*) FROM notification_rule;
-- Expected: counts match pre-deploy snapshot (Step 5 pg_dump comparison)

-- Tier 2 chain still works (Phase 2 PR-2F invariant)
SELECT COUNT(*) FROM admission_path WHERE admission_round_id IS NULL;
-- Expected: 0 (Phase 2 PR-2C one-way NOT NULL)
```

## 6. Backend health + smoke

```bash
# Health endpoint
curl -sf https://qlts.tnpc.edu.vn/health
# Expected: {"status":"healthy", ...}

# Backend logs no exceptions post-deploy
docker compose -f docker-compose.yml --profile production logs backend --tail=100 | grep -iE "error|exception|traceback" | head -10
# Expected: empty OR only startup warnings (no traceback)

# Celery worker + beat healthy
docker compose -f docker-compose.yml --profile production ps celery-worker celery-beat
# Expected: both Up (healthy)
```

## 7. Phase 3 endpoints stay 404 (router chưa wire)

```bash
# PR-3A KHÔNG ship router → endpoints stay 404
curl -sI -X POST https://qlts.tnpc.edu.vn/api/v2/admissions/1/choices \
  -H "Authorization: Bearer <admin_token>"
# Expected: HTTP/2 404 (route not registered, dormant code path)

# Phase 1/2 admission routes still work
curl -sf https://qlts.tnpc.edu.vn/api/v2/admissions/health
# Expected: 200 OK
```

## 8. Backup integrity

```bash
ls -lh /opt/qlts/backups/pre_deploy_*.sql | tail -3
# Expected: pre_deploy_<TIMESTAMP>.sql từ Step 5 (size > 1MB typical prod DB)

# Verify backup readable
head -50 /opt/qlts/backups/pre_deploy_<TIMESTAMP>.sql
# Expected: PostgreSQL pg_dump header
```

## Post-smoke actions

Sau khi 8/8 smoke PASS:

1. Save memory `project_phase3_pr_3a_shipped.md` với squash SHA `1cd2f184` + deploy timestamp + run ID
2. Update memory `phase3-plan-locked` description (mark PR-3A done, next PR-3B)
3. Update `Documents/ADMISSION_DAILY_LOG.md` — append "Deploy verified, all smoke PASS" entry
4. Kickoff PR-3B branch: `git checkout main && git pull && git checkout -b feat/admission-phase3-02-state-machine`

## Failure paths

| Smoke fail | Recovery |
|---|---|
| 1. alembic_version != phase3_01 | Re-check deploy logs; likely Step 6 hit auto-rollback (backup restored) → investigate fail cause from CI logs |
| 2/3. Schema artifact missing | Migration partial fail. Manual `alembic upgrade head` trong backend container OR `alembic downgrade -1` để revert + restore từ pg_dump backup |
| 4. Seed missing | Re-run UPDATE/INSERT manually qua psql; reference `phase3_01.py:upgrade()` for exact SQL |
| 5. Row count drift | INVESTIGATE before rollback — may be normal write activity during deploy window |
| 6. Backend unhealthy | `docker compose logs backend --tail=200`, check entrypoint gate flags, rollback Step 5 backup nếu critical |
| 7. Phase 3 endpoints 200 OK | Code drift — router accidentally wired. Investigate immediately, NOT expected for PR-3A |
| 8. Backup missing | Bad — disable auto-rollback. Manual snapshot ASAP before next deploy |

## Reference

- Plan: `C:\Users\Admin\.claude\plans\noble-launching-cocoa.md` v0.6
- Migration: `Backend_FastAPI/alembic/versions/phase3_01_create_admission_profile_choice_and_score.py`
- Anchor tests: `Backend_FastAPI/tests/unit/test_phase3_pr3a_choice_and_score.py`
- Memory `deploy-mechanics-canonical` — 8-step deploy.sh + entrypoint gates
- Memory `migration-predicate-safety` — pre-flight check pattern (C1)
- Rollback runbook: `Documents/PHASE3_ROLLBACK_RUNBOOK.md` (Strategy A/B/C cho Wave B+0, KHÔNG cần cho PR-3A DDL-only)
