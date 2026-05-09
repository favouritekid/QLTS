# Phase 2 Rollback Playbook v8 — PR-2C v2 ⚠ ONE-WAY

**Created**: 2026-05-09 (post PR-2B v2 ship)
**Scope**: Manual rollback procedures cho PR-2C v2 swap (`phase2_02b_v2`)
**Audience**: Solo dev / on-call admin

---

## When to use

PR-2C v2 swap admission_path schema:
- `admission_round_id` NOT NULL
- 2-col UNIQUE → 3-col UNIQUE `(round, academic_info, method)`

After PR-2C v2 deploy, paths được phép có duplicate `(academic_info_id, admission_method_id)` nếu khác `admission_round_id` (e.g., DOT_1 + DOT_2 cùng major + method = 2 paths). Khi rollback cần restore 2-col UNIQUE, các duplicate này sẽ block downgrade.

**Use cases**:
- Critical regression post PR-2C v2 ship → cần rollback khẩn cấp
- Schema design pivot reversal (unlikely, đã 8 audit rounds)

---

## Pre-rollback decision tree

```
Q1: Có duplicate (academic_info_id, admission_method_id) NÀO không?
├─ NO  → alembic downgrade phase2_02_v2 chạy thẳng (auto sanity check pass)
└─ YES → Continue Q2

Q2: Duplicate xuất hiện do nguyên nhân nào?
├─ Distinct round contexts (DOT_1, DOT_2, DOT_3, BO_SUNG)
│   → ARCHIVE strategy (preserve audit trail)
└─ Accidental dupes (same round)
    → MERGE strategy (consolidate into canonical row)
```

---

## Audit duplicates

```sql
-- List all duplicate groups (academic_info_id, admission_method_id)
SELECT
  academic_info_id,
  admission_method_id,
  COUNT(*) AS dup_count,
  array_agg(id ORDER BY admission_round_id, id) AS path_ids,
  array_agg(admission_round_id ORDER BY admission_round_id, id) AS round_ids
FROM admission_path
GROUP BY 1, 2
HAVING COUNT(*) > 1
ORDER BY 1, 2;
```

Output ví dụ post Phase 2 multi-round:

```
 academic_info_id | admission_method_id | dup_count | path_ids        | round_ids
------------------+---------------------+-----------+-----------------+----------
              70  |                   1 |         4 | {106,201,310,420}| {1,2,3,4}
              70  |                   3 |         4 | {108,203,312,422}| {1,2,3,4}
              ...
```

→ 90 paths × 4 rounds = 360 paths tổng cộng. 90 duplicate groups.

---

## ARCHIVE strategy (recommended cho distinct round contexts)

Preserve all paths trong archive table; downgrade chỉ giữ canonical (oldest round).

### Step 1: Move non-canonical paths to archive

```sql
-- For each duplicate group, KEEP path với round_id MIN (typically DOT_1).
-- Move others to archive.
WITH duplicates AS (
    SELECT
      ap.id,
      ap.academic_info_id,
      ap.admission_method_id,
      ap.admission_round_id,
      ROW_NUMBER() OVER (
          PARTITION BY ap.academic_info_id, ap.admission_method_id
          ORDER BY ap.admission_round_id ASC, ap.id ASC
      ) AS rn
    FROM admission_path ap
)
INSERT INTO _archive_admission_path_dup
SELECT ap.*, NOW() AS archived_at,
       'PR-2C v2 rollback — preserve non-canonical round' AS archive_reason
FROM admission_path ap
JOIN duplicates d ON d.id = ap.id
WHERE d.rn > 1;

DELETE FROM admission_path
WHERE id IN (
    WITH duplicates AS (
        SELECT
          id,
          ROW_NUMBER() OVER (
              PARTITION BY academic_info_id, admission_method_id
              ORDER BY admission_round_id ASC, id ASC
          ) AS rn
        FROM admission_path
    )
    SELECT id FROM duplicates WHERE rn > 1
);
```

### Step 2: Verify 0 duplicates

```sql
SELECT COUNT(*) FROM (
    SELECT 1 FROM admission_path
    GROUP BY academic_info_id, admission_method_id
    HAVING COUNT(*) > 1
) dups;
-- Expected: 0
```

### Step 3: Run alembic downgrade

```bash
ssh prod 'cd /app/qlts && docker compose exec backend alembic downgrade phase2_02_v2'
```

Sanity check trong migration sẽ verify 0 duplicates → proceed downgrade.

### Step 4: Container restart + smoke

Containers tự reload sau migration. Verify `/health` 200 + admin UI list paths.

### Step 5 (post-recovery): Restore archived rows

Sau khi rollback xong + đã fix root cause + ready re-deploy PR-2C v2:

```sql
INSERT INTO admission_path
SELECT * FROM _archive_admission_path_dup
ON CONFLICT (academic_info_id, admission_method_id) DO NOTHING;
-- 2-col UNIQUE block re-insert; phải re-deploy PR-2C v2 trước.
```

Sau khi PR-2C v2 re-applied (3-col UNIQUE active):

```sql
INSERT INTO admission_path
SELECT id, academic_info_id, admission_method_id, criteria_id, status,
       display_name, display_order, visibility, application_fee,
       allow_unverified_submission, minor_correction_allowed_fields,
       applicable_to, method_quota, bonus_rule_override,
       activated_at, activated_by, created_at, updated_at,
       admission_round_id, round_quota, admit_quota, submission_count
FROM _archive_admission_path_dup
ON CONFLICT (admission_round_id, academic_info_id, admission_method_id) DO NOTHING;
```

---

## MERGE strategy (cho accidental dupes — same round)

Hiếm gặp post Phase 2 (3-col UNIQUE block in production). Use case: dev DB bị seed sai.

### Step 1: Identify canonical

```sql
-- Pick path với most submissions / FK references
SELECT
  academic_info_id, admission_method_id,
  array_agg(id ORDER BY submission_count DESC, id ASC) AS prioritized_ids
FROM admission_path
GROUP BY 1, 2
HAVING COUNT(*) > 1;
```

→ First ID trong array = canonical.

### Step 2: Update FK references on admission_profile

```sql
-- Wrap trong DISABLE/ENABLE trigger (applied_rules immutable per
-- enforce_applied_rules_immutability)
ALTER TABLE admission_profile
  DISABLE TRIGGER enforce_applied_rules_immutability;

UPDATE admission_profile p
SET applied_rules = jsonb_set(
    p.applied_rules,
    '{admission_path_id}',
    to_jsonb(:canonical_id::int)
)
WHERE (p.applied_rules->>'admission_path_id')::int IN (
    -- non-canonical IDs to redirect
    :duplicate_ids
);

ALTER TABLE admission_profile
  ENABLE TRIGGER enforce_applied_rules_immutability;
```

### Step 3: Update FK references on other tables

```sql
-- Tier 3 PathSubjectGroupConfig (PR-2D) — defer if not yet shipped
-- Other FKs: criteria_id linkage already 1:1 ADM-003 (no change needed)
```

### Step 4: Sum submission_count + delete non-canonical

```sql
WITH dups AS (
    SELECT
      academic_info_id,
      admission_method_id,
      MIN(id) AS canonical_id,
      array_agg(id) FILTER (WHERE id != MIN(id)) AS dup_ids,
      SUM(submission_count) AS total_count
    FROM admission_path
    GROUP BY 1, 2
    HAVING COUNT(*) > 1
)
UPDATE admission_path ap
SET submission_count = d.total_count
FROM dups d
WHERE ap.id = d.canonical_id;

DELETE FROM admission_path
WHERE id IN (
    SELECT unnest(dup_ids) FROM dups
);
```

### Step 5: Run alembic downgrade

Same as ARCHIVE strategy Step 3.

---

## Differs from PR-2A v2 / PR-2B v2 rollback

| Action | PR-2A v2 | PR-2B v2 | PR-2C v2 ⚠ |
|---|---|---|---|
| `alembic downgrade` safe? | ✅ DROP TABLE | ✅ DROP COLUMNS | ❌ requires manual prep |
| Data destruction risk | LOW (1 row) | MEDIUM (52 path cols + 9 profile JSONB) | HIGH (potential N×M paths) |
| Backup required pre-deploy | OPTIONAL | OPTIONAL | **MANDATORY** |
| Manual playbook required | NO | NO | **YES (this doc)** |

---

## Pre-deploy checklist

Trước khi merge PR-2C v2 trên prod:

- [ ] Backup prod DB ngay trước cutover (separate từ pre-Phase-2 backup)
- [ ] Verify 0 NULL admission_round_id trên prod (`SELECT COUNT(*) FROM admission_path WHERE admission_round_id IS NULL` = 0)
- [ ] Verify 0 missing applied_rules.admission_round_id (parity check)
- [ ] Verify trigger `enforce_applied_rules_immutability` enabled (`tgenabled='O'`)
- [ ] Soak ≥24h post PR-2B v2 ship
- [ ] Rollback playbook (this doc) reviewed by solo dev
- [ ] Have 30-min window scheduled cho potential rollback execution

---

## Reference precedent

- `Documents/PHASE1_ROLLBACK_PLAYBOOK.md` — Phase 1 cutover lessons
- Memory `admission-cutover-shipped-2026-05-07` — 5-hotfix arc lessons
- Memory `phase2-plan-locked` v8.2 — 13 critical risks (#11-13)
- Memory `phase2-pr-2b-v2-shipped` — current path state (52 paths, all admission_round_id=1)

---

## Versioning

- v1.0 (2026-05-09): initial draft pre PR-2C v2 merge
- Updates required after each Phase 2 schema change post PR-2C v2
