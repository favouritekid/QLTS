# Admission Refactor — Staging Rehearsal Log

**Branch:** `feat/admission-full-cutover`
**Source spec:** `ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md` §7.1 (preflight) + §9.2 (rehearsal gate)
**Purpose:** ghi mỗi lần apply migration chain + backfill + smoke trên staging clone của production. Số liệu này dùng để estimate maintenance window cutover (RUNBOOK §7.2 timing).

**Pass criteria:** mỗi rehearsal phải PASS 2 lần trên staging clone (idempotency) trước khi Go production.

---

## Entry template (copy-paste khi thêm rehearsal mới)

```markdown
## Rehearsal N — YYYY-MM-DD HH:MM (timezone)

**Staging clone source:** prod dump SHA / date — `pg_dump -Fc` from prod ${DATE}
**Backend image:** `qlts-backend:<tag>` (commit SHA on feat branch)
**Migration baseline:** alembic head trước khi apply

### Migration chain apply

| ID | Migration | Started | Duration | Rows touched | Anomaly |
|---|---|---|---|---|---|
| M-P0a | phase0_add_selected_subject_group_id_to_profile | HH:MM:SS | Xs | N rows | none |
| M-P0b | phase0b_relax_applied_rules_immutability | HH:MM:SS | Xs | N rows | none |
| M-1-01 | phase1_01_add_degree_level_fk_to_major_program | HH:MM:SS | Xs | N rows | none |
| ... | ... | ... | ... | ... | ... |

**Total chain time:** Xm Ys
**Alembic head after:** <new revision>

### Backfill scripts

| Script | Duration | Rows processed | Exception count | Notes |
|---|---|---|---|---|
| status_history initial backfill | Xm | N profiles | 0 | per RUNBOOK §7.2 |
| selected_subject_group_id decision tree | Xm | N profiles | N edge cases | listed in `phase1_07b_create_backfill_exceptions_table` |
| GPA backfill từ academic_history JSON | Xm | N profiles | N | regex length-bounded |
| graduation_year backfill | Xm | N profiles | 0 |  |
| Casbin v3='allow' + seed deny rules accountant | Xm | N rules | 0 |  |

### Smoke (RUNBOOK §7.3 — 8 critical journeys)

| # | Journey | Result | Duration | Notes |
|---|---|---|---|---|
| 1 | Officer create lead + admission profile (Q11 auto-create) | PASS / FAIL | Xs |  |
| 2 | Officer claim → reviewing → publish-result → admitted/waitlisted/rejected | PASS / FAIL | Xs |  |
| 3 | Candidate magic link confirm → enrolled + Student row | PASS / FAIL | Xs |  |
| 4 | Casbin matrix: accountant 14 admission action → 403 | PASS / FAIL | Xs |  |
| 5 | Multi-NV (3 NV → 3 eligibility compute) | PASS / FAIL | Xs |  |
| 6 | Outbox worker: 100 profile bulk publish, backlog=0 sau 60s | PASS / FAIL | Xs |  |
| 7 | Lead pipeline projection: 14 status → consultation_status_id | PASS / FAIL | Xs |  |
| 8 | Frontend: 14 status badge + typed available_actions render | PASS / FAIL | Xs |  |

### Casbin matrix 4×14 (RUNBOOK §9.2)

| Result: PASS / FAIL — see attached matrix output |
| Errors: list any role × action combo that returned wrong code |

### Conclusion

- [ ] All migrations PASS, no rollback needed
- [ ] Backfill exception count within expected bounds
- [ ] 8/8 smoke critical PASS
- [ ] Casbin 4×14 PASS
- [ ] Idempotency check (this rehearsal vs prior) — diff = 0?

**Verdict:** GREEN / YELLOW / RED
**Action:** ready for next rehearsal / fix Y before retry / abort plan

**Total rehearsal duration (apply + backfill + smoke):** Xm Ys
**Estimated cutover window from this:** Xh (add 30% safety margin per RUNBOOK)
```

---

## Pre-rehearsal checklist (run BEFORE rehearsal 1)

- [ ] Staging environment ready (Postgres 16, Redis 7, same OS as prod)
- [ ] `pg_dump -Fc` from production fresh (< 24h old)
- [ ] Anonymized PII per company policy (if applicable)
- [ ] Backend image build successful from feat branch HEAD
- [ ] Alembic head trên feat branch verified (no missing migration)
- [ ] Task 0 prerequisites all shipped (T0-1, T0-2, T0-3, T0-4a/4b, T0-5 per RUNBOOK §3.5)
- [ ] Document expected backfill exception bounds (so unusual count flags issue)

---

## D12-D14 Pre-rehearsal Runbook (planning — 2026-05-04)

> **Status**: ⚠️ Runbook only — không phải evidence. Mọi PASS / duration / row count CHỈ ghi sau khi staging clone thật chạy.

**Wave 3 ONE-WAY ⚠ gate** — Q5 chốt 2026-05-03 yêu cầu D12-D14 staging clone ready BEFORE Wave 3 PR-3A ship.

### Migration chain plan — 17 active phase1 migrations (Wave 1 + Wave 2 + Wave 5)

Ordered by alembic chain (apply trên prod-cloned staging). Wave 5 (5 migrations) appended 2026-05-05 post-Wave-5 closure (memory `184-phase1-schema-wave-plan` line 51-61).

| Order | Migration ID | Type | Expected impact | Smoke check |
|---|---|---|---|---|
| 1 | `phase1_19a_create_notification_outbox` | DDL — table create | New empty table | `\dt notification_outbox` |
| 2 | `phase1_19b_backfill_casbin_eft_and_seed_deny_rules` | Data backfill — Casbin v3 + 6 deny rule | All existing policies set v3='allow'; +6 deny rule rows accountant | `SELECT COUNT(*) FROM casbin_rule WHERE v3='deny'` = 6 |
| 3 | `phase1_01_add_degree_level_fk_to_major_program` | DDL + 20-row backfill | major_program.degree_level_id FK + index | `SELECT COUNT(*) FROM major_program WHERE degree_level_id IS NULL` = 0 (post-backfill) |
| 4 | `phase1_02_add_bonus_rule_to_method_and_path` | DDL — 2 JSONB cols | NULL on existing rows (default) | `\d admission_method`, `\d admission_path` shows new cols |
| 5 | `phase1_03_add_applicable_to_method_quota_to_path` | DDL + GIN | admission_audience ENUM + 2 cols + GIN index | `\d admission_path` + `EXPLAIN ANALYZE` audience filter Bitmap Index Scan |
| 6 | `phase1_05_add_subject_kind_and_score_bounds` | DDL + 6-row seed | subject_kind ENUM + 3 cols + 6 virtual subjects | `SELECT COUNT(*) FROM subject WHERE code IN ('TB_HK1_L12'...)` = 6 |
| 7 | `phase1_06_add_path_id_to_document_group` | DDL — FK + partial index | New nullable FK column | `\di document_group*` shows ix_doc_group_path partial |
| 8 | `phase1_07b_create_backfill_exceptions_table` | DDL — table create | New empty table | `\dt _admission_backfill_exceptions` |
| 9 | `phase1_08_add_uses_choice_engine_flag_to_profile` | DDL + server default | All profiles get uses_choice_engine=false | `SELECT COUNT(*) FROM admission_profile WHERE uses_choice_engine IS NULL` = 0 |
| 10 | `phase1_13_create_system_config_table` | DDL + 1-row seed | system_config table + current_intake_year=2026 | `SELECT value FROM system_config WHERE key='current_intake_year'` |
| 11 | `phase1_09a_add_eligibility_scalars_and_backfill` | DDL + 2-field backfill | 4 nullable cols + gpa/grad_year backfill from JSON | exception count `INVALID_GPA_VALUE`/`MISSING_GPA_OVERALL`/`INVALID_GRADUATION_YEAR`/`MISSING_GRADUATION_YEAR` |
| 12 | `phase1_10_create_status_history_table_and_backfill` | DDL + 6 backfill blocks | New table + 1 row/profile + 5 scattered audit migrate | `SELECT COUNT(*) FROM admission_profile_status_history` = profile count + scattered rows |
| 13 | `phase1_19c_seed_event_catalog_db_rows` (Wave 5-A PR #213 squash `9af7510b`) | Data seed — 12 ADMISSION_* events | 12 NotificationRule + 12 NotificationTemplate + 29 NotificationAction (per-channel routing 2×7+3×5) | `SELECT COUNT(*) FROM notification_rule WHERE event LIKE 'ADMISSION_%'` = 12; `SELECT COUNT(*) FROM notification_template WHERE template_code LIKE 'TPL_ADMISSION_%'` = 12; `SELECT COUNT(*) FROM notification_action a JOIN notification_rule r ON a.rule_id=r.id WHERE r.event LIKE 'ADMISSION_%'` = 29 |
| 14 | `phase1_16_create_archived_admission_profile_table` (Wave 5-D PR #214 squash `1989bd03`) | DDL — empty archive table | New `_archived_admission_profile` (64 col mirror + archived_at) + `ix_archived_profile_lead_year` | `\dt _archived_admission_profile` + `\di ix_archived_profile_lead_year` |
| 15 | `phase1_17_create_archived_outbox_table` (Wave 5-E PR #215 squash `0b17f394`) | DDL — empty archive table | New `_archived_notification_outbox` (10 col mirror + archived_at) + `ix_archived_outbox_archived_at` | `\dt _archived_notification_outbox` + `\di ix_archived_outbox_archived_at` |
| 16 | `phase1_19d_register_celery_beat_archive_task` (Wave 5-B PR #216 squash `ef6a8b6d`) | B-i marker (paired Celery code) | NO DB change. Paired: `app/celery_app.py` adds `archive-outbox-dispatched` beat entry crontab Sunday 02:00 VN; `app/tasks/notification_outbox_tasks.py` adds `archive_outbox_dispatched_task` body | `python -c "from app.celery_app import celery_app; assert 'archive-outbox-dispatched' in celery_app.conf.beat_schedule"` + verify Celery beat container picked up entry post-deploy via `docker compose logs celery-beat \| grep archive-outbox` |
| 17 | `phase1_19e_seed_notification_rules` (Wave 5-C PR #217 squash `3f902f5b`) | Marker (seed scope absorbed by phase1_19c) | NO DB change. Terminal Phase 1 #19 chain revision | `alembic current` shows `phase1_19e (head)` |

**Estimated migration chain duration** (rough, dev DB extrapolated):
- DDL-only (8 migrations: phase1_02/06/07b/08/16/17 + 2 markers 19d/19e): ~8-20s combined.
- Backfill-heavy (M-1-01 + M-1-09a + M-1-10): ~30s-2min depending on profile count.
- Casbin backfill (phase1_19b): ~5s for typical policy rows.
- Wave 5-A event_catalog seed (phase1_19c): ~2-5s for 53 INSERT statements (12+12+29).
- Wave 5-B/5-C markers: ~0s (body=pass).
- **Total estimate**: 2-5 min trên staging clone với prod data volume. **Add 30% safety margin** → maintenance window estimate **3-7 min** for migrations alone (per RUNBOOK §7.2). Wave 5 additions không tăng đáng kể tổng thời gian — phần lớn DDL/marker.

### Backfill exception bounds (expected — TO VERIFY POST-REHEARSAL)

| Exception type | Source migration | Expected bound | Rule for over-bound |
|---|---|---|---|
| `INVALID_GPA_VALUE` | phase1_09a | < 1% profile count | Audit data quality issue |
| `MISSING_GPA_OVERALL` | phase1_09a | < 5% submitted+ profiles | Investigate JSON shape |
| `INVALID_GRADUATION_YEAR` | phase1_09a | < 1% | Same |
| `MISSING_GRADUATION_YEAR` | phase1_09a | < 10% (graduation_type set + year_to malformed) | Most legacy profiles không set graduation_type |
| Status history initial backfill | phase1_10 | exactly profile count | Mismatch = bug |
| Status history scattered audit | phase1_10 | sum of `*_at NOT NULL` columns | `actor_fallback=true` rows = legacy `*_by_id IS NULL` count |
| Wave 5 backfill exceptions | phase1_19c/16/17/19d/19e | 0 rows (DDL/seed/marker only — no backfill exception sinks) | Any non-zero = bug |

### Smoke checks (RUNBOOK §7.3 — 8 critical journeys)

Reuse existing template above; staging rehearsal MUST verify all 8 + Casbin matrix 4×14 before issuing GREEN verdict.

### Idempotency contract

Per RUNBOOK §9.2: each rehearsal must run upgrade → downgrade → re-upgrade roundtrip clean. Pass criteria:
- (a) `alembic upgrade phase1_19e` clean ALL 17 migrations (phase1_19a → phase1_19b → phase1_01 → phase1_02 → phase1_03 → phase1_05 → phase1_06 → phase1_07b → phase1_08 → phase1_13 → phase1_09a → phase1_10 → phase1_19c → phase1_16 → phase1_17 → phase1_19d → phase1_19e).
- (b) `alembic downgrade phase0br01` reverse the full 17-migration chain back to the pre-Wave-1 baseline. **Note**: `phase1_19a` itself has `down_revision="phase0br01"` ([alembic/versions/phase1_19a_create_notification_outbox.py:54](../Backend_FastAPI/alembic/versions/phase1_19a_create_notification_outbox.py#L54)), so `phase0br01` is the correct target — `alembic downgrade phase1_19a` would STOP AT phase1_19a (still applied), leaving partial state.
- (c) Re-run `alembic upgrade phase1_19e` — no DuplicateColumnError / DuplicateObject anywhere.
- (d) Backfill exception rows: `INSERT ... ON CONFLICT DO NOTHING` semantic verified — re-run shows 0 new exception rows when input data unchanged.
- (e) Wave 5 idempotent guards verified: `phase1_19c` rule/template/action seed re-runs no-op via `WHERE NOT EXISTS` + `ON CONFLICT (template_code) DO NOTHING`; `phase1_16/17` table create skipped via `inspector.get_table_names()` guard; `phase1_19d/19e` markers no-op by construction.

### Wave 3 ONE-WAY ⚠ note

**This runbook covers Wave 1 + Wave 2 + Wave 5 (17 migrations).** Wave 3 ONE-WAY migrations (phase1_11/12/15a/18) ship trong PR-3A bundle — NOT included here. Wave 3 rehearsal needs separate D15+ clone with Wave 3 chain applied on top of Wave 1+2+5 baseline.

### Sign-off requirements (per RUNBOOK §10)

Before issuing GREEN verdict on rehearsal:
- [ ] Engineering Owner sign-off
- [ ] DBA sign-off (data integrity + backfill exception count review)
- [ ] Ops Lead sign-off (timing fits maintenance window budget)
- [ ] QA Lead sign-off (8/8 smoke + 4×14 Casbin)

---

## Rehearsal entries

(Append below as rehearsals happen. Newest first.)

---

_(no rehearsals yet — placeholder for first entry; runbook above is planning-only, not evidence)_
