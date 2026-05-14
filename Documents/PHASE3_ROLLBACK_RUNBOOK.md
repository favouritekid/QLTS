# Phase 3 Rollback Runbook

**Plan ref**: `C:\Users\Admin\.claude\plans\noble-launching-cocoa.md` v0.3
**Memory**: `phase3-plan-locked`
**Author**: solo dev (memory `solo-developer` — no team escalation path)
**Date created**: 2026-05-12 Day 1 prep
**Status**: DRAFT — finalize Day 28 pre-Wave-B deploy

---

## Scope

Rollback procedure cho Phase 3 multi-NV deploy nếu phát sinh issue critical post-Wave B+0 ship (target 2026-06-15).

**3 strategies** theo severity:
- Strategy A — Freeze + FE read-only (UI bug, BE state OK, <1h recovery)
- Strategy B — Status remap controlled (engine decisions sai, candidates notified, 4-8h, 0 data loss audit kept)
- Strategy C — Full DB restore (data corruption cascading, 24h+, data loss từ snapshot point)

---

## Trigger conditions

| Severity | Strategy | Trigger condition | Recovery time | Data loss |
|---|---|---|---|---|
| UI bug, engine OK | **A** Freeze + read-only | FE crashes / wrong render, BE state intact | <1h | 0 |
| Engine sai, decisions đã fanout | **B** Status remap controlled | Wrong admit/waitlist decisions, candidates notified, < cascading data corruption | 4-8h | 0 (audit kept) |
| Data corruption cascading | **C** Full DB restore | Multiple invariants violated, status_history corrupted, cross-table FK violations | 24h+ | Data từ snapshot point (1-12h trước trigger) |

---

## Strategy A — Freeze + FE read-only

### When to trigger

- FE crash trên specific component (ChoiceListEditor, EligibilityResultViewer, etc.)
- Wrong render on candidate-facing UI but BE state correct
- Admin UI broken but candidate flow OK
- Drag-drop dnd-kit incompatibility post Next.js version bump

### Procedure (<1h)

```bash
# Step 1: Enable FE read-only mode via env var
# Production .env or docker-compose.yml
NEXT_PUBLIC_PHASE3_READONLY=true

# Step 2: Restart frontend container (preserve BE state)
ssh prod 'cd /opt/qlts && docker compose restart frontend'

# Step 3: Verify read-only mode active
curl -sf https://qlts.tnpc.edu.vn/api/v2/admin/system-config | jq '.feature_flags'

# Step 4: User-facing notice (banner)
# FE component reads NEXT_PUBLIC_PHASE3_READONLY → render banner
# "Hệ thống đang bảo trì, hỗ trợ xem nhưng không thể chỉnh sửa"

# Step 5: Hotfix branch + test + deploy
git checkout main && git pull
git checkout -b hotfix/phase3-fe-{issue-id}
# ... fix code ...
git push + gh pr merge --squash
# Deploy.yml auto-trigger
# After deploy + smoke PASS:
ssh prod 'sed -i "/NEXT_PUBLIC_PHASE3_READONLY/d" /opt/qlts/.env'
ssh prod 'cd /opt/qlts && docker compose restart frontend'
```

### Verification

- Browser smoke: candidate can view profile + choices, NO edit/save buttons
- Admin can view backfill queue, NO approve/reject buttons
- BE writes 0 trong period freeze (verify `SELECT MAX(updated_at) FROM admission_profile WHERE updated_at > NOW() - INTERVAL '1 hour'`)

### Implementation Day 28 prep

- [ ] FE component `<ReadOnlyBanner>` ship trong PR-3D-A (Wave A)
- [ ] `NEXT_PUBLIC_PHASE3_READONLY` env var documented
- [ ] Test toggle local dev: ENV=true → buttons disabled, banner shown

---

## Strategy B — Status remap controlled

### When to trigger

- Engine output wrong (vd: candidate đúng tiêu chí nhưng marked rejected)
- Decision fanout 12 events đã sent, candidates received Zalo/email
- Need rollback `result_published` profiles BACK to `submitted` state
- BUT data not corrupted, audit history clean

### Pre-flight

```sql
-- Verify scope: count profiles trong 4 new states (Phase 1 M-1-11 CHECK)
SELECT status, COUNT(*) FROM admission_profile
WHERE status IN ('reviewing', 'result_published', 'admitted', 'waitlisted')
GROUP BY status;

-- Verify scope choice rows
SELECT decision, COUNT(*) FROM admission_profile_choice
WHERE decision != 'pending'
GROUP BY decision;
```

### Procedure (4-8h)

```sql
BEGIN;

-- Step 1: ASSERT scope (abort if > expected count)
DO $$
DECLARE affected_count INT;
BEGIN
    SELECT COUNT(*) INTO affected_count FROM admission_profile
    WHERE status = 'result_published' AND updated_at > :rollback_window_start;
    IF affected_count > 1000 THEN
        RAISE EXCEPTION 'Too many rows to remap (%) — manual review required', affected_count;
    END IF;
END $$;

-- Step 2: Backup decision snapshots to history (audit trail)
INSERT INTO admission_profile_status_history (
    admission_profile_id, from_status, to_status,
    transitioned_by_role, transitioned_at, reason, metadata
)
SELECT
    id, status, 'submitted',
    'system', NOW(),
    'Phase 3 engine rollback per runbook Strategy B',
    jsonb_build_object(
        'rollback_run_id', :run_id,
        'original_decision', (SELECT jsonb_agg(c.decision) FROM admission_profile_choice c WHERE c.admission_profile_id = admission_profile.id),
        'rollback_reason', :reason
    )
FROM admission_profile
WHERE status IN ('result_published', 'admitted', 'waitlisted')
  AND updated_at > :rollback_window_start;

-- Step 3: Reset profile status back to submitted
UPDATE admission_profile
SET status = 'submitted', updated_at = NOW()
WHERE status IN ('result_published', 'admitted', 'waitlisted')
  AND updated_at > :rollback_window_start;

-- Step 4: Reset choice decisions to pending
UPDATE admission_profile_choice
SET decision = 'pending', waitlist_rank = NULL, eligibility_check_result = NULL
WHERE admission_profile_id IN (
    SELECT id FROM admission_profile
    WHERE status = 'submitted' AND updated_at > NOW() - INTERVAL '1 minute'
);

-- Step 5: Verify remap clean
SELECT 'admission_profile' AS table, status, COUNT(*) FROM admission_profile GROUP BY status
UNION ALL
SELECT 'admission_profile_choice', decision, COUNT(*) FROM admission_profile_choice GROUP BY decision;

-- COMMIT only if verify clean, else ROLLBACK
COMMIT;
```

```python
# Step 6: Re-fanout notification "tạm hoãn"
# Backend script publish 1 NOTIFICATION_GENERAL với template "rollback_notice"
# to all profiles affected
python scripts/phase3-rollback-notify.py --run-id={run_id} --reason="{reason}"
```

### Dry-run prep on dev clone

```bash
# Day 28 dry-run
docker compose exec postgres pg_dump -U qlts qlts > /tmp/prod_clone.sql
docker compose exec postgres psql -U qlts -d qlts_dev < /tmp/prod_clone.sql
# Run remap SQL với rollback (BEGIN; ... ROLLBACK;) → verify scope OK
```

### Implementation Day 28 prep

- [ ] `scripts/phase3-status-remap.sql` parametrize: `:rollback_window_start`, `:run_id`, `:reason`
- [ ] `scripts/phase3-rollback-notify.py` template "rollback_notice"
- [ ] Dry-run trên dev DB clone với `BEGIN; ... ROLLBACK;`
- [ ] Verify expected scope count

---

## Strategy C — Full DB restore

### When to trigger

- Data corruption cascading (multiple FK violations)
- `status_history` corrupted, audit chain broken
- `notification_outbox` worker stuck + duplicate dispatch fanout
- Migration partial fail leaving schema inconsistent
- ANY trigger that Strategy A + B không cover

### Pre-flight DB snapshot

```bash
# scripts/phase3-pre-deploy-snapshot.sh
# Run 1h trước Wave B+0 deploy (2026-06-15)
PGHOST=prod-db PGUSER=qlts pg_dump --format=custom \
  --file=/backups/qlts_prod_pre_phase3_$(date +%Y%m%d_%H%M%S).dump \
  qlts

# Verify integrity
pg_restore --list /backups/qlts_prod_pre_phase3_*.dump | head -50
```

### Procedure (24h+)

```bash
# Step 1: Maintenance mode ON
ssh prod 'cd /opt/qlts && docker compose stop backend frontend celery-worker celery-beat'

# Step 2: Drop current DB (CONFIRM USER 2-step)
docker compose exec postgres dropdb -U qlts qlts
docker compose exec postgres createdb -U qlts qlts

# Step 3: Restore from snapshot
docker compose exec postgres pg_restore -U qlts -d qlts \
  /backups/qlts_prod_pre_phase3_<timestamp>.dump

# Step 4: Verify post-restore state
docker compose exec postgres psql -U qlts -d qlts -c "SELECT version_num FROM alembic_version;"
# Expected: phase2_06 (pre-Phase-3 snapshot)

# Step 5: Re-deploy old image tag (revert to pre-Phase-3 build)
ssh prod 'cd /opt/qlts && docker compose pull && docker compose up -d'
# Use deploy.yml workflow_dispatch với revision <pre-phase3 SHA>

# Step 6: User-facing communication
# Email template "system_restore_notice" to all leads
# Manual via admin/notifications screen
```

### Communication template (post-restore)

```
Kính gửi Quý phụ huynh và Thí sinh,

Hệ thống tuyển sinh đã phục hồi về trạng thái lúc {snapshot_time}.

Mọi thay đổi sau {snapshot_time} đã bị mất bao gồm:
- Hồ sơ nộp mới
- Cập nhật điểm
- Kết quả xét tuyển

Quý vị vui lòng nộp lại hồ sơ qua đường dẫn cũ.

Xin lỗi vì sự bất tiện này.
```

### Implementation Day 28 prep

- [ ] `scripts/phase3-pre-deploy-snapshot.sh` automated 1h pre Wave B+0
- [ ] Verify snapshot integrity script: `pg_restore --list`
- [ ] Email template "system_restore_notice" Vietnamese
- [ ] Test restore on dev DB clone → verify alembic head + row counts match snapshot

---

## Decision matrix Day 28 (pre-Wave B deploy 2026-06-15)

Final sign-off gate trước Wave B+0 ship:

- [ ] **Strategy A**: FE read-only mode toggle tested ENV var trên dev + smoke PASS
- [ ] **Strategy B**: remap SQL script written + dry-run trên dev clone PASS với expected scope
- [ ] **Strategy C**: DB snapshot script tested + integrity verified + restore on dev clone PASS
- [ ] All 3 strategies documented above với explicit step-by-step
- [ ] Communication templates approved (rollback_notice + system_restore_notice)
- [ ] Solo dev sign-off (memory `solo-developer` — no team escalation, dev tự responsible)

---

## Escalation path (solo dev)

Không có team escalation path. Single-point-of-failure mitigation:

1. **Pre-flight**: 3 strategies tested Day 28 → KHÔNG ship Wave B+0 nếu strategy nào FAIL dry-run
2. **During incident**: solo dev triage → pick strategy theo severity table → execute với SQL/script ready
3. **Communication**: solo dev tự draft + send email/Zalo qua admin/notifications screen
4. **Post-incident**: post-mortem trong DAILY_LOG entry + memory update nếu lesson worth saving

---

## Reference

- Memory `phase3-plan-locked` — plan v0.3 + 13 risks
- Memory `solo-developer` — no team escalation, mandatory weekend reset
- Memory `audit-before-fix` — verify scope trước action
- `Documents/PHASE1_ROLLBACK_PLAYBOOK.md` — Phase 1 cutover precedent (3 strategies similar pattern)
- Plan file `C:\Users\Admin\.claude\plans\noble-launching-cocoa.md` v0.3
