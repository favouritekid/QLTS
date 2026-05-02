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

## Rehearsal entries

(Append below as rehearsals happen. Newest first.)

---

_(no rehearsals yet — placeholder for first entry)_
