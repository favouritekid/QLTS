# ADR-002: Semester Tuition Refactor

## Status

Proposed (2026-04-11) — PR 0 (spec-only, no runtime changes)

## Context

QLTS currently stores tuition as a single annual amount per academic program:
`OfferingAcademicInfo.tuition_fee_per_year` (see
`Backend_FastAPI/app/models/offering_academic_info.py:43`). The admission
workflow and all public/admin UI, KPI analytics, and the fee calculation
pipeline derive their numbers from this one scalar per year.

The real business process is **per semester**, not per year:

- Each major/program has a tuition table covering the full course duration,
  broken down per semester (HK1, HK2, HK3, ...).
- Semester 1 (HK1) is the financial object the admission flow cares about.
- The operational term *tạm thu* (provisional collection) collected at the
  time of enrollment is, in business reality, **HK1 tuition** — not a
  separate deposit concept.
- Partial payment of HK1 is valid and must still let the student cross the
  enrollment gate; the unpaid remainder stays as HK1 debt.
- Formal fee waivers (`đặc cách miễn`) clear HK1 for gate purposes without
  producing recognized revenue.
- HK2 and beyond are a post-admission finance flow, not an admission flow
  concern.

This ADR is spec-only. It does not change runtime code, schema, migrations,
or contracts. It locks the semantics and rollout rules that the subsequent
PRs (PR 1..PR 8 in the epic roadmap) must follow.

## Problem Statement

The current `tuition_fee_per_year` model is **wrong at the conceptual level**:

1. **Canonical unit mismatch.** The business unit is a semester; the model
   unit is a year. Every downstream piece (admission gate, discount,
   installment plan, KPI, public API) inherits this mismatch.

2. **Admission gate is too strict.** The gate at
   `Backend_FastAPI/app/services/admission_service.py:175` only accepts
   `fee.status in (paid, waived)`. `partial` is a legitimate `FeeStatusEnum`
   value (`fee.py:59`) but is rejected, even though the business says
   partial HK1 payment must pass the gate.

3. **Schema blocks multi-semester fees.** The constraint
   `uq_fee_profile_type_year` (`fee.py:79-82`) forbids more than one
   `tuition` row per (profile, academic_year). Even if we add `semester_no`
   to `Fee`, the current constraint would reject a second HK2 tuition row
   in the same year.

4. **Public/admin contracts expose `tuition_fee_per_year` directly**
   (`Backend_FastAPI/app/schemas/public_admissions.py:24,48-49,59-60`).
   Silently redefining this field to mean HK1 would break contract trust.

5. **KPI/analytics use annual tuition as a revenue proxy**
   (`Backend_FastAPI/app/repositories/officer_repository.py:447-539`,
   `Backend_FastAPI/app/services/organization_service.py:1699-1713`).
   Their meaning silently drifts if the underlying field is reinterpreted.

6. **Events already reference tuition milestones** in admission projections
   (`Backend_FastAPI/app/core/admission_event_mapping.py:184,200,215`:
   `tuition_fee_calculated`, `tuition_fee_paid`, `tuition_fee_refunded`).
   These currently carry no semester context and would pull HK2+ payments
   into the admission pipeline incorrectly after refactor.

## Business Semantics (Locked)

The following rules are the source of truth for all PRs in this epic:

1. The canonical tuition source is a **per-major, per-semester tuition
   table**, named `semester_tuition` at the technical level.
2. `HK1` (semester 1) is the financial object of the **admission** flow.
3. `tạm thu` is **not** a separate fee type; it is the operational state of
   an HK1 `semester_tuition` fee whose payment is in progress.
4. Students may settle HK1 via any of:
   - full payment,
   - payment equal to the `tạm thu` amount,
   - payment less than `tạm thu` (still valid),
   - formal waiver (`đặc cách miễn`).
5. The admission gate is **HK1 financial clearance**, not "HK1 fully paid".
6. Partial payment satisfies the gate; the remainder stays as HK1 debt.
7. Formal waiver satisfies the gate but **does not** book revenue.
8. Each semester is **one `Fee` row**.
9. A semester fee may have one or more invoices (collection installments).
10. The admission workflow only binds to HK1. HK2+ is post-admission.
11. Public-facing UI must surface HK1 prominently **and** a
    full-course-per-semester table.

## Canonical Data Model Direction

> Detailed shape lives in `docs/SEMESTER_TUITION_SPEC.md`. This ADR fixes
> only the decisions that gate PR 1 schema design.

The per-major, per-semester tuition table is a new `offering_semester_tuition`
(or equivalent name chosen in PR 1) row-per-semester model, keyed by
`(academic_info_id, semester_no)` with a monetary `amount` and active-window
metadata. It becomes the canonical tuition source.

`OfferingAcademicInfo.tuition_fee_per_year` remains in place throughout the
transition as a **deprecated compatibility field**, not the canonical source
of truth. Its value during transition is defined by Decision 5 below; it
must not be silently redefined to mean "HK1 amount".

`Fee` gains a `semester_no` dimension. See `Closed Decisions > Gap A` for
the exact uniqueness tuple and migration rules.

`InstallmentPlan` is unchanged structurally and remains a global catalog
attached per semester fee via `Fee.installment_plan_id`. See
`Closed Decisions > Decision 3`.

`FeeAppliedDiscount` remains keyed per fee. Multi-semester scholarship, if
needed later, must go through `TuitionDiscountPolicy.applicable_scope` with
an explicit `semesters` field — never via implicit carry-over. See
`Closed Decisions > Decision 4`.

## Admission vs Post-Admission Financial Boundary

**Admission flow (in scope for admission_service.py)**:
- Only HK1 fees exist as a precondition of the enrollment gate.
- Only HK1 fee events project into the admission pipeline.
- Only HK1 financial clearance gates the transition to `enrolled`.

**Post-admission flow (out of scope for admission_service.py)**:
- HK2..HKn fees, their invoices, payments, refunds, discounts.
- Per-semester scheduling, due dates, reminders, overdue handling.
- These may reuse `Fee`, `Invoice`, `InstallmentPlan`, and `PAYMENT_*`
  events, but **must not** fire admission projections.

**Concrete consequence**: the projections at
`admission_event_mapping.py:184,200,215` (`tuition_fee_calculated`,
`tuition_fee_paid`, `tuition_fee_refunded`) must be gated to
`semester_no == 1` once `Fee.semester_no` exists. This is explicitly
assigned to PR 5 in the roadmap; this ADR only locks the intent.

## Flags and Truth Table

Two orthogonal controls govern the admission finance gate during rollout:

| Flag | Role | Allowed values |
|---|---|---|
| `ENABLE_FEE_VERIFICATION` | Circuit breaker — does the gate run at all? | `true` / `false` (default `false`, see `config.py:376-377`, `.env.example:177`) |
| `ADMISSION_FEE_GATE_MODE` | Which gate semantics apply when the circuit breaker is on? | `legacy` / `semester_hk1` (default `legacy` during rollout) |

### Truth Table

| `ENABLE_FEE_VERIFICATION` | `ADMISSION_FEE_GATE_MODE` | Gate behavior | Notes |
|---|---|---|---|
| `false` | `legacy` | **Bypassed.** No finance check runs before `enrolled`. | Current production default. |
| `false` | `semester_hk1` | **Bypassed.** Mode is ignored when circuit breaker is off. | Safe to flip mode without enabling the gate. |
| `true` | `legacy` | Check: exactly one `tuition` fee per profile; accept only `status in (paid, waived)`. | Current `admission_service.py:175` logic. Partial rejected. |
| `true` | `semester_hk1` | Check: `HK1` fee exists (`fee_type='tuition'`, `semester_no=1`) **and** is cleared. Cleared means: `status in (paid, partial, waived)` **or** an explicit HK1 waiver marker, per the clearance definition in the spec. | New logic. Partial passes. Waiver passes without booking revenue. |

**Rollout sequence**:
1. Ship `ADMISSION_FEE_GATE_MODE` as a new setting, defaulting to `legacy`.
   No runtime behavior change.
2. After PR 3/PR 4 land, flip `ADMISSION_FEE_GATE_MODE=semester_hk1` in
   staging with `ENABLE_FEE_VERIFICATION=true` to validate.
3. Production rollout flips both flags per the operations runbook in the
   epic (out of scope for PR 0).

**Non-rule**: the two flags are never collapsed into a single boolean.
Circuit breaker and mode switch are independent concerns.

## Closed Decisions

### Decision 1 — Payment Event Parity is only partially blocked

`feat/finance-payment-event-parity` (the ember branch) is **not fully
blocked** by this epic.

**Ship before the semester refactor** (payment-event parity work, semester
model not required):
- `PAYMENT_REJECTED`
- `REFUND_PROCESSED`
- online callback parity for `PAYMENT_VERIFIED` (including the
  `verified_by_id=None` fix for `chk_payment_no_self_approval`)

**Defer until semester semantics are stable**:
- `FEE_FULLY_PAID`
- `INVOICE_ISSUED`
- `PAYMENT_OVERDUE`

The ember branch (`feat/finance-payment-event-parity`) has WIP event catalog
additions whose payloads already use opaque `fee_id` references, so the
semester refactor will not require rewriting their payloads. The branch may
ship the three ship-safe items above independently of this epic.

**Known follow-ups owned by PR 5** (not blocking ember merge):
- `sync_lead_tuition_refunded()` currently projects unconditionally into
  the admission pipeline. It must be gated to `semester_no == 1` once
  `Fee.semester_no` exists.
- `PAYMENT_VERIFIED` payload carries an `is_fully_paid` flag derived from
  `Fee.is_fully_paid` (`fee.py:266`). Under the per-semester model, this
  flag means "HK1 fully paid" and must be reinterpreted; ADR-001 already
  notes that `FeeFullyPaid` is only partially bridged via this flag.

**Compatibility constraint (from ADR-001)**: this decision does **not**
allow reintroducing `DomainEvent` / `emit_event()`. Any new notification
must use `SystemEvents` + `EventDefinition` + `notification_rule` seed.
See `Backend_FastAPI/docs/adr/ADR-001-remove-finance-events.md:104-106`.

### Decision 2 — Keep `ENABLE_FEE_VERIFICATION` as a circuit breaker

`ENABLE_FEE_VERIFICATION` is the on/off switch for the admission finance
gate and nothing else. The semester refactor introduces a **separate** mode
control `ADMISSION_FEE_GATE_MODE=legacy|semester_hk1`.

Rationale: the legacy gate means "tuition fee must be `paid` or `waived`"
and the new gate means "HK1 financial clearance". These are different
semantics; overloading one boolean makes rollout impossible to reason about.

The truth table above is part of this decision and must not be modified
without updating this ADR.

### Decision 3 — InstallmentPlan stays global, applies per semester fee

`InstallmentPlan` remains a shared catalog (`installment_plan.py:47`). Each
semester fee is a separate `Fee` row and attaches to a plan via
`Fee.installment_plan_id`. There is no cross-semester installment plan.

Semantic clarification:
- `fee` = one semester financial obligation.
- `invoice` = one or more collection installments belonging to that fee.
- `tạm thu` is **not** a distinct `fee_type`; it is the operational state
  of an HK1 `semester_tuition` fee with `status in (calculated, partial)`.

**Installment schedule calculation** must accept an explicit `anchor_date`
parameter instead of implicitly reading the fee creation date. The
existing `InstallmentPlan.get_installment_schedule()` signature
(`installment_plan.py:129-171`) is compatible with this change — it
already takes `total_amount` explicitly — but a new `anchor_date` parameter
is required so HK1 and HK2 fees using the same plan code can produce
consistent or intentionally different schedules. This is PR 3 work.

#### Gap A — Uniqueness tuple (closed)

The new uniqueness constraint on `fee` is:

```
UNIQUE (admission_profile_id, fee_type, semester_no)
```

`academic_year` is **removed from the uniqueness tuple** but **retained as
a non-unique metadata column** on `Fee`.

**Rationale**:
- A single `admission_profile_id` represents one enrollment attempt.
  Within that attempt, the (fee_type, semester_no) pair is naturally
  unique — a student does not pay tuition twice for HK1 of the same
  program instance.
- `academic_year` is ambiguous when a Vietnamese school year spans two
  calendar years (e.g. school year 2026-2027 contains HK1 in Fall 2026
  and HK2 in Spring 2027). Keeping it in uniqueness would force a
  policy decision about how the calendar split is stored, which is a
  reporting concern, not an integrity concern.
- Demoting `academic_year` to metadata means PR 1 can choose any
  interpretation (e.g. "the calendar year in which the semester begins"
  or "the school year label") without breaking schema migrations later.

**Migration rules for existing rows** (PR 1 scope):
- Every existing `tuition` row is logically an "annual tuition" today.
  Backfill `semester_no = 1` on those rows during PR 1 migration.
- Drop `uq_fee_profile_type_year` and create
  `uq_fee_profile_type_semester` in the same migration (constraint
  name reflects the new tuple — `academic_year` is not part of it).
- Preserve `academic_year` values as-is; they become metadata.
- Backfill is safe because the old uniqueness guarantees at most one
  `tuition` row per (profile, year) today, so the new tuple
  (profile, type, semester_no=1) is also unique.

**Non-`tuition` fee types** (`application`, `enrollment`, `insurance`,
`dormitory`, `other` — `fee.py:44-51`) do not have a meaningful semester
dimension. PR 1 must decide one of:
  1. allow `semester_no = NULL` for non-tuition rows and add a partial
     unique index that only applies when `semester_no IS NOT NULL`; or
  2. force `semester_no = 0` (or similar sentinel) for non-tuition rows
     and keep the constraint as above.
The ADR does not prescribe which — PR 1 chooses based on migration
ergonomics. The only rule is: whichever shape PR 1 picks, `tuition` rows
must always have `semester_no >= 1`.

#### Gap B — Fee creation strategy (closed)

The strategy is **hybrid**:

- **HK1 is created eagerly** at admission approval time by the existing
  fee calculation flow (`fee_calculation_service.py`). Its `anchor_date`
  is the admission approval timestamp. This preserves the current gate
  evaluation window: the HK1 fee always exists by the time the gate runs.
- **HK2..HKn are created lazily** by a post-admission service or
  scheduler, not by `admission_service.py`. Their `anchor_date` is the
  respective semester start date, sourced from the academic calendar.
  PR 0 does not pick the calendar source — see `Deferred Decisions`.

**Rationale**:
- The admission gate only needs HK1 to exist. Eager creation of HK2+ at
  approval time creates stale fees for students who drop out before HK2
  begins.
- Lazy creation of HK2+ matches the business spec that "HK2+ is a
  post-admission flow".
- The HK1 gate behavior is independent of the strategy choice, which
  isolates the admission flow from calendar concerns.

**Concrete consequence**: `admission_service.py` never creates HK2+ fees.
A later PR (roadmap position TBD, not PR 1..PR 8 scope) will introduce
the post-admission semester-fee service. PR 0 only locks the boundary.

### Decision 4 — Discounts are per semester fee, no auto carry-over

Discounts in `FeeAppliedDiscount` (`fee.py:280-363`) remain keyed per
`(fee_id, policy_id)`. No discount applied to HK1 auto-propagates to HK2+.

Multi-semester scholarships, when needed, must be encoded explicitly
through `TuitionDiscountPolicy.applicable_scope` with a new convention
(e.g. `applicable_scope.semesters = [1, 2, 3, 4]`). This convention is
proposed but not yet implemented and is out of scope for PR 0.

**Required follow-up for PR 2/PR 3**: the invalidation hook at
`organization_service.py:1370-1374` currently only fires on
`tuition_fee_per_year` edits. A mirror path must be added for
`semester_tuition` CRUD so discount recalculation triggers correctly when
the underlying per-semester amount changes.

### Decision 5 — Public API rollout is additive and non-breaking

Public and frontend contracts migrate in an additive, non-breaking way
first. The canonical switchover happens only after UI has consumed the new
fields.

**New fields to add** (exact names chosen in PR 6):
- `semester_tuitions[]` — per-semester tuition rows for the full course.
- `semester_1_tuition` — the HK1 amount, surfaced directly for admission
  contexts.
- `semester_1_tuition_min` / `semester_1_tuition_max` — aggregates at
  program and degree-level group level, parallel to the existing
  `tuition_min`/`tuition_max`.

**Existing `tuition_fee_per_year` is NOT redefined**. It is treated as a
**deprecated compatibility field**, not canonical. Its transition value is:

> During the rollout window, `tuition_fee_per_year` continues to return
> the value stored in `OfferingAcademicInfo.tuition_fee_per_year`
> unchanged. It is not derived from semester tuition data. It is not
> silently overwritten. Whether and when the column is dropped is a
> separate PR after frontend/admin/public consumers have migrated.

**Aggregate fields are in scope** for this decision as well, not only the
scalar:
- `tuition_min` / `tuition_max` on `PublicAdmissionsProgramSummary`
  (`public_admissions.py:48-49`) and `PublicAdmissionsDegreeLevelGroup`
  (`public_admissions.py:59-60`).
- `avg_tuition_fee`, `min_tuition_fee`, `max_tuition_fee` on the
  organization summary (`organization_service.py:1699-1713`).
- Lost-revenue proxies in `officer_repository.py:447-539`.

All of these remain as legacy contract fields during the rollout. Their
relabeling is deferred to PR 7 — see `Deferred Decisions`.

## Deferred Decisions / Later PR Ownership

| # | Item | Owner |
|---|---|---|
| D1 | Concrete DB column name, type, and index for `offering_semester_tuition` | PR 1 |
| D2 | `semester_no` nullable-vs-sentinel shape for non-tuition fee types | PR 1 |
| D3 | Backfill migration for existing `tuition` rows to `semester_no=1` | PR 1 |
| D4 | Admin config UI for per-semester tuition input (replaces single annual input) | PR 2 |
| D5 | Mirror invalidation hook for `semester_tuition` CRUD (Decision 4 follow-up) | PR 2 or PR 3 |
| D6 | `Fee.semester_no` column + adjusted `fee_calculation_service.py` | PR 3 |
| D7 | `anchor_date` parameter on `InstallmentPlan.get_installment_schedule()` | PR 3 |
| D8 | New gate logic for `ADMISSION_FEE_GATE_MODE=semester_hk1`, including the clearance definition (what counts as `cleared`) and the explicit waiver marker | PR 4 |
| D9 | Gating `sync_lead_tuition_refunded` to `semester_no == 1` | PR 5 |
| D10 | Reinterpreting `PAYMENT_VERIFIED.is_fully_paid` under per-semester model | PR 5 |
| D11 | Additive public API fields + frontend contract changes | PR 6 |
| D12 | KPI/analytics relabeling (revenue proxies, aggregates) | PR 7 |
| D13 | Post-admission HK2+ lazy fee creation service + academic calendar source | Later PR, out of PR 1..PR 8 scope |
| D14 | `FEE_FULLY_PAID`, `INVOICE_ISSUED`, `PAYMENT_OVERDUE` events with semester context | PR 8 |
| D15 | Rewrite of `cached-imagining-ember` plan under the new model | PR 8 |

## Consequences

### Positive

- One canonical tuition unit matches business reality; downstream
  inconsistencies disappear by construction.
- Admission gate becomes correct for partial payment and waiver cases
  without special-casing in service code.
- Event semantics stop lying about HK1/HK2+ boundaries.
- `ENABLE_FEE_VERIFICATION` stays a clean circuit breaker; rollout is
  reversible with a flag flip.
- ADR-001's rule (no `DomainEvent` revival) is reinforced.

### Negative

- Medium-size schema change (`Fee.semester_no` + constraint swap) with a
  destructive migration path for the old unique constraint.
- Two flags to coordinate during rollout instead of one.
- Compatibility maintenance for `tuition_fee_per_year` and all its
  aggregates until PR 7 lands — the field lingers as deprecated for
  multiple PRs.
- KPI/analytics fields silently continue using annual semantics until
  PR 7. Dashboards must not be treated as authoritative during the
  transition window.

### Neutral

- `InstallmentPlan` model is unchanged; only the calling convention
  (`anchor_date`) evolves.
- `FeeAppliedDiscount` model is unchanged; only the policy scope
  convention evolves.

## Non-goals

This ADR and PR 0 explicitly do not cover:

1. Any runtime code change, migration, or test.
2. The HK2..HKn post-admission finance workflow. That is a later epic.
3. Academic calendar modeling. PR 0 does not pick the source of semester
   start dates.
4. Deleting `tuition_fee_per_year`. The column remains during the epic.
5. KPI/analytics relabeling. All proxy-based revenue calculations keep
   their current semantics until PR 7.
6. Public API versioning. The rollout is additive; there is no v1/v2
   split.
7. Reintroducing `DomainEvent` / `emit_event()`. ADR-001 still governs.
8. Changing `InstallmentPlan` catalog shape.
9. Choosing the column name of the new per-semester tuition table (PR 1).
10. Re-scoping the ember branch beyond the three ship-safe items listed
    in Decision 1.

## References

- `Backend_FastAPI/docs/SEMESTER_TUITION_SPEC.md` — canonical model, flows,
  contract compatibility, migration roadmap.
- `Backend_FastAPI/docs/adr/ADR-001-remove-finance-events.md` — no
  `DomainEvent` reintroduction rule.
- `Backend_FastAPI/app/models/finance/fee.py:79-82` — current unique
  constraint that Decision 3 / Gap A replaces.
- `Backend_FastAPI/app/models/finance/fee.py:44-51` — `FeeTypeEnum`.
- `Backend_FastAPI/app/models/finance/fee.py:54-63` — `FeeStatusEnum`
  (including the existing `partial` value).
- `Backend_FastAPI/app/models/finance/installment_plan.py:129-171` —
  `get_installment_schedule()` to gain `anchor_date`.
- `Backend_FastAPI/app/services/admission_service.py:125-196` — current
  fee gate logic.
- `Backend_FastAPI/app/services/admission_service.py:3153` — the
  `ENABLE_FEE_VERIFICATION` gate site.
- `Backend_FastAPI/app/config.py:376-377` — current flag default.
- `Backend_FastAPI/app/core/admission_event_mapping.py:184,200,215` —
  `tuition_fee_calculated/paid/refunded` projections to gate.
- `Backend_FastAPI/app/schemas/public_admissions.py:24,48-49,59-60` —
  public contract surface.
- `Backend_FastAPI/app/services/organization_service.py:1370-1374` —
  discount invalidation hook.
- `Backend_FastAPI/app/services/organization_service.py:1699-1713` —
  KPI aggregates on annual tuition.
- `Backend_FastAPI/app/repositories/officer_repository.py:447-539` —
  lost-revenue proxy on annual tuition.
- `feat/finance-payment-event-parity` branch — in-flight payment event
  parity work; partially unblocked by Decision 1 (ship three items
  independently of this epic).
