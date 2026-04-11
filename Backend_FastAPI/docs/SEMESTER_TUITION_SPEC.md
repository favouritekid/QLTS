# Semester Tuition Spec

> **Status**: PR 0 spec-only draft (2026-04-11). Companion to
> `docs/adr/ADR-002-semester-tuition-refactor.md`. No runtime code, schema,
> or migration changes accompany this document.

This document is the canonical description of the semester tuition model
QLTS is moving to. It restates the business rules declaratively, draws the
boundary between admission and post-admission finance flows, and lists the
contract compatibility rules that every PR in the epic must respect.

The binding decisions live in ADR-002. This spec is **reference material
for implementers**: if the ADR and the spec disagree, the ADR wins and the
spec is wrong and must be fixed.

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| `semester_tuition` | The per-major, per-semester tuition catalog. One row per (program academic info, semester number). Canonical source of tuition. |
| `HK1` | Semester 1. The only semester the admission workflow cares about. |
| `semester_no` | Integer index of a semester within a program's full course duration. `1` for HK1. Non-nullable for `tuition` fees. |
| `tạm thu` | The operational state of an HK1 fee while payment is in progress. **Not** a fee type. **Not** a separate table or enum value. |
| `HK1 financial clearance` | The gate condition that lets a profile transition to `enrolled` under the new model. See §4.2. |
| `fee` (per the model) | One semester financial obligation. After refactor, a tuition fee row is always per-semester. |
| `invoice` (per the model) | One collection installment belonging to a fee. A fee may have many invoices. |
| `InstallmentPlan` | A reusable catalog of payment schedules. Attached per-fee. Not cross-semester. |
| `admission profile` | An enrollment attempt. Scopes which HK1 fee is in play. |
| `post-admission finance flow` | Everything related to HK2..HKn. Out of admission_service scope. |

---

## 2. Canonical Data Model (Conceptual)

```
                 +---------------------------+
                 |   offering_academic_info  |
                 |  (program / major / year) |
                 +-------------+-------------+
                               |
                               | 1 .. N  (one row per semester in the full course)
                               v
                 +---------------------------+
                 |   offering_semester_tuition|
                 |   (semester_no, amount)    |  <-- CANONICAL SOURCE
                 +---------------------------+

                 +---------------------------+
                 |     admission_profile     |
                 +-------------+-------------+
                               |
                               | 1 .. N
                               v
                 +---------------------------+
                 |            fee            |
                 | (fee_type, semester_no,   |
                 |  status, amounts,         |
                 |  installment_plan_id)     |
                 +-------------+-------------+
                               |
                               | 1 .. N
                               v
                 +---------------------------+
                 |          invoice          |
                 +---------------------------+
```

Key structural rules:

1. `offering_semester_tuition` is a new table introduced in PR 1. Its
   shape is declared there; this spec only fixes its role as the canonical
   source of tuition data.
2. `Fee` gains a `semester_no` column. For `fee_type='tuition'`, the value
   must be `>= 1`. For other fee types, PR 1 picks the shape (nullable vs
   sentinel) per ADR-002 Decision 3 / Gap A.
3. `Fee` retains the existing `installment_plan_id` FK. The
   `InstallmentPlan` catalog is unchanged; only the call site becomes
   per-semester.
4. `FeeAppliedDiscount` keys remain `(fee_id, policy_id)`. A discount on
   HK1 does **not** propagate to HK2.

---

## 3. Fee Uniqueness

Effective after PR 1 migration:

```sql
-- DROP: uq_fee_profile_type_year  (see fee.py:79-82)
-- ADD:
UNIQUE (admission_profile_id, fee_type, semester_no)
  -- partial or full per PR 1's choice for non-tuition rows
```

`academic_year` remains on `Fee` as a **non-unique metadata column**. Its
semantics during the transition:

- For legacy rows migrated from the year-based model: preserved as-is.
- For new per-semester rows: PR 1 picks the interpretation (e.g. "the
  calendar year in which the semester begins") and documents it in the
  migration message. The choice does not affect uniqueness.

---

## 4. Admission Flow

### 4.1 Lifecycle

```
draft -> submitted -> approved -> [HK1 fee created] -> confirmed -> enrolled
                                  ^                    ^            ^
                                  |                    |            |
                         HK1 semester_tuition    HK1 gate passes   state change
                         lookup + Fee insert     (see 4.2)
```

HK1 fee creation stays in the existing `fee_calculation_service` call site
triggered by profile approval. The only change is that the amount source
switches from `OfferingAcademicInfo.tuition_fee_per_year` to
`offering_semester_tuition` for `semester_no = 1`, and the resulting `Fee`
row carries `semester_no = 1`.

### 4.2 HK1 Financial Clearance

A profile is cleared for enrollment when its HK1 fee satisfies **all** of:

1. The fee exists: `fee_type='tuition' AND semester_no=1 AND
   admission_profile_id=<profile>`.
2. The fee is in a cleared state. Cleared means **any** of:
   - **Full payment** — `status = paid`. Entire HK1 amount settled.
   - **Any non-zero HK1 payment** — one or more valid payments have been
     recorded against the HK1 fee with total paid amount `> 0`. This
     covers all three business cases explicitly allowed by the spec:
     paying the full amount, paying exactly the operational `tạm thu`
     amount, and paying **less than `tạm thu`**. All three pass the gate.
     Any unpaid remainder stays as HK1 debt and does **not** block
     enrollment. Expected fee `status` is `partial` (or `paid` if the
     payment fully settles the amount).
   - **Formal waiver** — `status = waived`, backed by an explicit HK1
     waiver marker. A waiver clears the gate without booking revenue.

**Locked business decision**: there is no minimum payment threshold for
passing the HK1 gate. A non-zero payment is sufficient. If the business
ever wants a minimum threshold, it must be added by updating this spec
and ADR-002 first — not by silently rejecting low-amount partial
payments in the gate logic.

The exact `FeeStatusEnum` set to accept in code and the concrete
mechanism for recording "waiver without revenue" (e.g. `waived_amount`
column usage, explicit waiver record, audit trail shape) are implemented
in PR 4 (see ADR-002 Deferred Decision D8). This spec fixes only the
intent: any non-zero payment **or** a valid waiver clears the gate.

### 4.3 Events

Three existing projections at
`Backend_FastAPI/app/core/admission_event_mapping.py:184,200,215`
(`tuition_fee_calculated`, `tuition_fee_paid`, `tuition_fee_refunded`)
must be gated to `semester_no == 1` in PR 5. This spec fixes the intent:

- `tuition_fee_calculated`: fires only for the HK1 fee created at
  approval time. HK2+ fee creation events must not project here.
- `tuition_fee_paid`: fires only when the HK1 fee reaches a cleared state
  for the first time. HK2+ payments must not touch the admission pipeline.
- `tuition_fee_refunded`: fires only on an HK1 refund. HK2+ refunds are a
  post-admission concern.

---

## 5. Post-Admission Flow (HK2..HKn)

Out of admission_service scope. HK2+ fees are created lazily by a later
service not yet built (ADR-002 D13). Their relationship to `Fee`,
`Invoice`, and `InstallmentPlan` reuses the same tables but none of them
project into the admission pipeline.

Rules this spec fixes for HK2+:

1. HK2+ fees must set `semester_no >= 2`.
2. HK2+ payment events (`PAYMENT_VERIFIED`, `PAYMENT_REJECTED`,
   `REFUND_PROCESSED`, etc.) may fire normally; they stay in the finance
   notification surface. They must not trigger admission projections.
3. HK2+ fee anchor date is the respective semester start date. The source
   of this date (calendar table, program metadata, manual admin input) is
   decided later.
4. HK2+ discount application is independent from HK1 by default (ADR-002
   Decision 4).

---

## 6. Installment Plan Usage

The catalog is unchanged. Every fee may optionally attach a plan:

```
Fee.installment_plan_id  -> InstallmentPlan.id
```

Plans stay global and reusable. There is no per-semester plan variant and
no cross-semester plan.

The invoice generation call site must provide an explicit `anchor_date`
to `InstallmentPlan.get_installment_schedule()` (new PR 3 parameter). The
anchor date is:

- For HK1: the admission approval timestamp.
- For HK2+: the semester start date (see §5 rule 3).

Invoice count per fee is `1..N` depending on the plan. The current
`schedule` JSON model (`installment_plan.py:32-45`) already supports this
shape; no model change needed.

---

## 7. Discounts

`FeeAppliedDiscount` remains per-fee. The unique constraint
`uq_fee_applied_discount_fee_policy` (`fee.py:294-297`) stays.

Rule: applying a discount policy to the HK1 fee of a profile does **not**
cause automatic application of the same policy to HK2+ fees of the same
profile.

Multi-semester scholarship encoding (when business asks for it later):

- New convention on `TuitionDiscountPolicy.applicable_scope` JSON:
  `{"semesters": [1, 2, 3, 4]}`.
- The discount application service (PR 3 scope) must honor this field
  when creating per-semester fees. Absent the field, default behavior is
  "single fee only".

ADR-002 Decision 4 follow-up: the discount invalidation hook at
`Backend_FastAPI/app/services/organization_service.py:1370-1374` must
gain a mirror for `semester_tuition` CRUD in PR 2 or PR 3.

---

## 8. Public / Admin Contract Compatibility

### 8.1 Current surface (frozen as legacy)

| Field | Location | Status during epic |
|---|---|---|
| `tuition_fee_per_year` | `public_admissions.py:24`, `AcademicInfoPanel.tsx:58`, `OfferingAcademicInfoDialog.tsx:59` | Deprecated compatibility. Value unchanged during transition. Not canonical. |
| `tuition_min` / `tuition_max` | `public_admissions.py:48-49,59-60` | Deprecated compatibility. Same rule. |
| `avg_tuition_fee`, `min_tuition_fee`, `max_tuition_fee` | `organization_service.py:1699-1713` | Deprecated compatibility. Labels will be realigned in PR 7. |
| lost-revenue proxies | `officer_repository.py:447-539` | Deprecated compatibility. Formula realigned in PR 7. |

Rule: none of these fields is silently redefined to mean "HK1 amount".
They continue to return the value they return today until they are
removed or renamed in a later PR.

### 8.2 New additive surface (PR 6 scope)

| Field | Shape | Purpose |
|---|---|---|
| `semester_tuitions[]` | Array of `{semester_no, amount}` | Full-course tuition table. |
| `semester_1_tuition` | Scalar amount | HK1 amount, directly surfaced for admission contexts. |
| `semester_1_tuition_min` / `semester_1_tuition_max` | Aggregate scalars | HK1 range per program / degree-level group. |

All new fields are additive. No existing field is removed until frontend
and public consumers have migrated to the new ones.

### 8.3 Frontend wording

Frontend display text must make clear which fields are per-semester and
which are legacy annual values. Example:

- HK1 prominent card: labeled "Học phí HK1" — sourced from
  `semester_1_tuition`.
- Full-course table: labeled "Bảng học phí toàn khóa theo từng học kỳ" —
  sourced from `semester_tuitions[]`.
- Legacy annual value (if still displayed): must be labeled
  "Học phí năm (giá trị cũ)" or similar and must not be presented as the
  canonical tuition number. Preferred: remove from UI in PR 6.

---

## 9. Flags

Two controls govern the admission gate during rollout. See ADR-002
§"Flags and Truth Table" for the binding table. In summary:

- `ENABLE_FEE_VERIFICATION` — circuit breaker. When `false`, gate is
  bypassed regardless of mode.
- `ADMISSION_FEE_GATE_MODE` — mode switch, `legacy` (current logic) or
  `semester_hk1` (new logic). Default `legacy` during rollout.

---

## 10. Non-goals (Spec scope)

Same as ADR-002 non-goals. In particular, this spec does **not**:

- Name the exact DB columns or migration SQL for `offering_semester_tuition`
  (PR 1).
- Define the academic calendar source for HK2+ semester start dates
  (later PR, ADR-002 D13).
- Prescribe KPI label wording (PR 7).
- Specify the API schema version bumping strategy (not bumped; rollout is
  additive).
- Describe the operations runbook for flipping the two flags in prod.

---

## 11. Open-but-closed items (hardened wording to prevent drift)

The following items have been asked about repeatedly and are **closed**.
If a future PR disagrees, it must update ADR-002 first.

1. **`tạm thu` is not a fee type**. It is an operational state of an HK1
   fee whose payment is in progress. Anyone introducing a new fee_type
   for it is wrong.
2. **`tuition_fee_per_year` is not redefined**. It is not "the same as
   HK1". It is a deprecated compatibility field with its current value.
3. **Admission flow binds only to HK1**. HK2..HKn do not affect
   `admission_service`, `admission_event_mapping`, or lead pipeline
   projections.
4. **Partial HK1 payment passes the gate**. Anyone rejecting partial in
   the new gate logic is wrong.
5. **Formal HK1 waiver passes the gate without booking revenue**.
   Booking revenue for a waiver is wrong.
6. **`ENABLE_FEE_VERIFICATION` is a circuit breaker, not a semantics
   switch**. Using it to flip legacy vs semester_hk1 is wrong.
7. **InstallmentPlan stays global**. Nobody should create a
   per-semester-variant catalog.
8. **Discounts do not auto carry-over between semesters**. Silent
   propagation is wrong.
9. **No `DomainEvent` / `emit_event()` revival** (ADR-001 rule,
   reinforced here).
10. **Ember branch ships three events ahead of this epic**:
    `PAYMENT_REJECTED`, `REFUND_PROCESSED`, `PAYMENT_VERIFIED` online
    callback parity. `FEE_FULLY_PAID`, `INVOICE_ISSUED`, `PAYMENT_OVERDUE`
    are deferred to PR 8.
