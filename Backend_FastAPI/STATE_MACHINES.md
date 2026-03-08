# State Machines Reference

> Single source of truth for all stateful entities in QLTS.
> Verified against source code. Last updated: 2026-03-06.

---

## 1. Admission Profile

**Source**: `app/services/admission_state_machine.py` (ALLOWED_TRANSITIONS dict)

```
DRAFT --> SUBMITTED --> APPROVED --> CONFIRMED --> ENROLLED
                    \-> REJECTED --> RESUBMITTED -/
                                \-> DRAFT
                        APPROVED --> OVERRIDDEN --> ENROLLED
```

| From | Allowed To | Actor | Guard |
|------|-----------|-------|-------|
| `draft` | `submitted` | Officer | -- |
| `submitted` | `approved`, `rejected` | Manager | -- |
| `rejected` | `resubmitted`, `draft` | Officer | -- |
| `resubmitted` | `approved`, `rejected` | Manager | -- |
| `approved` | `confirmed`, `overridden` | Lead / Admin | -- |
| `confirmed` | `enrolled` | System | Creates Student + StudentDocument |
| `overridden` | `enrolled` | System | Creates Student + StudentDocument |
| `enrolled` | (none) | -- | **Terminal state** |

**Enforcement**: Explicit `ALLOWED_TRANSITIONS` dict + `validate_transition()` raises `ValueError`.

---

## 2. Lead Phase Lifecycle

**Source**: `app/services/phase_manager.py`

Phase is **derived** from `admission_profile.status`, NOT stored directly.

```
CONSULTATION --> ADMISSION --> FEE --> ENROLLED
```

| Phase | Derived When | Stages | Statuses |
|-------|-------------|--------|----------|
| `consultation` | No admission profile | stg01, stg02 | sts00, sts02-06 |
| `admission` | Profile: draft/submitted/rejected/resubmitted | stg03, stg04 | sts07-09, sts13, sts16-17 |
| `fee` | Profile: approved/confirmed/overridden | stg05 | sts10, sts14, sts18 |
| `enrolled` | Profile: enrolled | stg06, stg07 | sts11, sts12 |

**Universal statuses** (allowed in ALL phases, don't change stage):
- `sts01` (NO_ANSWER), `sts15` (NO_REPLY_MESSAGE), `sts19` (CANCELLED)

**System-only statuses** (cannot be selected by users):
- `sts10`, `sts11`, `sts12`, `sts13`, `sts18`

**Role-based statuses** (Manager/Admin only):
- `sts09`, `sts16`

**Enforcement**: `fsm_engine.py` applies 7-step validation (phase guard, stage guard, trigger guard, etc.)

---

## 3. Lead Consultation Status (FSM Engine)

**Source**: `app/services/fsm_engine.py`

Transitions are **data-driven** via `allowed_transition` DB table, not hardcoded.

**Rules**:
1. Next statuses come from `allowed_transition` table WHERE `from_status_id = current`
2. Phase acts as GUARD only (doesn't generate status list)
3. User/role: cannot cross phases. System/event: can cross if declared in table
4. System statuses (`selectable_mode = system`) hidden from UI
5. Universal statuses appended to every status list (don't go through transition table)
6. NULL status (new lead) can ONLY go to `sts00` (NOT_CONTACTED)

**Enforcement**: `is_transition_allowed()` is the single validation function. `execute_system_transition()` adds idempotency checks (won't re-enter a status the lead has been in before).

---

## 4. Lead Validity

**Source**: `app/models/lead.py` (`LeadValidityEnum`)

```
raw --> valid --> qualified
    \-> invalid
    \-> duplicate
```

| From | To | Actor |
|------|----|-------|
| `raw` | `valid` | Staff confirms lead is legitimate |
| `raw` | `invalid` | Staff marks bad data |
| `raw` | `duplicate` | Staff marks as duplicate |
| `valid` | `qualified` | Staff confirms meets consultation criteria |

**Terminal**: `qualified`, `invalid`, `duplicate`

**Enforcement**: Service layer only. No explicit transition map in code.

---

## 5. Lead Assignment Status

**Source**: `app/models/lead.py` (`assignment_status` field)

```
pending --> assigned --> reassign_pending --> assigned
        \-> failed                       \-> failed

failed --> pending (retry)
```

| From | To | Actor |
|------|----|-------|
| `pending` | `assigned` | Auto-assign or manual assign |
| `pending` | `failed` | No suitable officer found |
| `assigned` | `reassign_pending` | Manager requests reassignment |
| `reassign_pending` | `assigned` | Reassignment successful |
| `reassign_pending` | `failed` | No new officer found |
| `failed` | `pending` | Retry assignment |

**Note**: This is a **cyclic** state machine (no terminal state).

**Enforcement**: `assignment_service.py`. No explicit transition map.

---

## 6. Collaborator (CTV)

**Source**: `app/models/collaborator.py` (`CollaboratorStatusEnum`), `app/services/collaborator_service.py`

```
pending --> active --> suspended --> active (reactivate)
                  \-> inactive      \-> inactive
```

| From | To | Method | Guard |
|------|----|--------|-------|
| (new, non-admin) | `pending` | `create_collaborator()` | -- |
| (new, admin) | `active` | `create_collaborator()` | Admin auto-approves |
| `pending` | `active` | `approve_collaborator()` | Must be pending. Auto-creates User account if self-registered |
| `active` | `suspended` | `suspend_collaborator()` | Must be active |
| `suspended` | `active` | `reactivate_collaborator()` | Must be suspended |
| `active` | `inactive` | -- | Not yet implemented in service |
| `suspended` | `inactive` | -- | Not yet implemented in service |

**Terminal**: `inactive`

**Side effects**:
- Approve: creates User + UserUnitAssignment + Casbin role sync
- Suspend: cancels pending commissions for this CTV

**Enforcement**: Service layer guards (status checks before transition). No explicit map.

---

## 7. Lead Claim

**Source**: `app/models/collaborator.py` (`LeadClaimStatusEnum`)

```
pending --> approved (creates Lead + sets referrer)
        \-> rejected
```

| From | To | Actor |
|------|----|-------|
| `pending` | `approved` | Staff approves claim |
| `pending` | `rejected` | Staff rejects claim |

**Terminal**: `approved`, `rejected`

**Constraint**: `uq_claim_collaborator_lead` -- one CTV can only claim one lead once.

---

## 8. Commission Record

**Source**: `app/models/commission.py` (`CommissionRecordStatus`), `app/services/commission_service.py`

```
pending --> approved --> paid
        \-> rejected
        \-> cancelled

approved --> cancelled (post-approval cancellation)
```

| From | To | Method | Guard |
|------|----|--------|-------|
| (auto-created) | `pending` | `check_and_create_commission()` | Lead validity in (valid, qualified), CTV active, policy matches |
| `pending` | `approved` | `approve_commission()` | Must be pending |
| `pending` | `rejected` | `reject_commission()` | Must be pending, reason required |
| `approved` | `paid` | `pay_commission()` | Must be approved |
| `pending`/`approved` | `cancelled` | `cancel_commissions_for_lead()` | Lead regresses from trigger status |
| `pending` | `cancelled` | `cancel_commissions_for_collaborator()` | CTV suspended |

**Terminal**: `paid`, `rejected`, `cancelled`

**Constraint**: `uq_commission_lead_policy` -- one commission per (lead, policy) pair.

---

## 9. Fee

**Source**: `app/models/finance/fee.py` (`FeeStatusEnum`), `app/services/fee_calculation_service.py`, `app/services/payment_service.py`

```
pending --> calculated --> invoiced --> partial --> paid
                      \-> waived       \-> overdue --> partial
                      \-> cancelled                \-> paid
                                       invoiced --> overdue
                                       invoiced --> cancelled
```

| From | To | Trigger | Guard |
|------|----|---------|-------|
| `pending` | `calculated` | `calculate_fee()` | -- |
| `calculated` | `invoiced` | Invoice(s) generated | -- |
| `calculated` | `waived` | Admin waives fee | -- |
| `calculated` | `cancelled` | `cancel_fee()` | `paid_amount = 0` |
| `invoiced` | `partial` | Payment verified (partial) | -- |
| `invoiced` | `paid` | Payment verified (full) or waive remainder | -- |
| `invoiced` | `overdue` | Scheduled job / due date passed | -- |
| `invoiced` | `cancelled` | `cancel_fee()` | `paid_amount = 0` |
| `partial` | `paid` | Payment verified (remainder) or waive remainder | -- |
| `partial` | `overdue` | Due date passed | -- |
| `overdue` | `partial` | Payment verified (partial) | -- |
| `overdue` | `paid` | Payment verified (full) | -- |

**Terminal**: `paid`, `waived`, `cancelled`

**Key rules**:
- M10: Cannot recalculate if `paid_amount > 0`
- H5: Waive amount cannot exceed remaining balance
- Cannot cancel if `paid_amount > 0`

**Side effects** (tuition fees only):
- `calculated` -> Lead synced to sts14
- `paid` -> Lead synced to sts10
- Refund processed -> Lead synced to sts18

**Enforcement**: CHECK constraint `chk_fee_status_valid`. Service layer guards. No explicit transition map.

---

## 10. Invoice

**Source**: `app/models/finance/invoice.py` (`InvoiceStatusEnum`), `app/services/invoice_service.py`, `app/services/payment_service.py`

```
draft --> issued --> partial --> paid
      \-> cancelled  \-> overdue --> partial
                     issued --> overdue --> paid
                     issued --> cancelled
                     overdue --> cancelled
```

| From | To | Trigger | Guard |
|------|----|---------|-------|
| (new) | `draft` | `generate_invoices_for_fee()` | Fee status in (calculated, invoiced, partial) [H8] |
| `draft` | `issued` | `issue_invoice()` or auto-issue | Must be draft |
| `draft` | `cancelled` | `cancel_invoice()` | `paid_amount = 0` |
| `issued` | `partial` | Payment verified (partial amount) | -- |
| `issued` | `paid` | Payment verified (full amount) | -- |
| `issued` | `overdue` | `mark_overdue_invoices()` scheduled job | `due_date < today` |
| `issued` | `cancelled` | `cancel_invoice()` | `paid_amount = 0` |
| `partial` | `paid` | Payment verified (remainder) | -- |
| `partial` | `overdue` | `mark_overdue_invoices()` | `due_date < today` |
| `overdue` | `partial` | Payment verified (partial) | -- |
| `overdue` | `paid` | Payment verified (full) | -- |
| `overdue` | `cancelled` | `cancel_invoice()` | `paid_amount = 0` |

**Terminal**: `paid`, `cancelled`

**Enforcement**: CHECK constraint `chk_invoice_status_valid`. Service layer guards. No explicit transition map.

---

## 11. Payment

**Source**: `app/models/finance/payment.py` (`PaymentStatusEnum`), `app/services/payment_service.py`

```
          [manual]     pending --> verified --> refunded
          [online]     (auto) verified --> refunded
                       pending --> rejected
```

| From | To | Method | Guard |
|------|----|--------|-------|
| (manual) | `pending` | `record_manual_payment()` | -- |
| (online) | `verified` | Auto via PaymentIntent callback | -- |
| `pending` | `verified` | `verify_payment()` | Must be pending, verifier != creator (C3) |
| `pending` | `rejected` | `reject_payment()` | Must be pending, reason required |
| `verified` | `refunded` | Via RefundRequest workflow | -- |

**Terminal**: `verified` (operational end), `rejected`, `refunded`

**Constraint**: `chk_payment_no_self_approval` -- `verified_by_id != created_by_id`

**Cascading effects when verified**:
1. `invoice.paid_amount += payment.amount` -> invoice status updated (partial/paid)
2. `fee.paid_amount += payment.amount` -> fee status updated (partial/paid)
3. If tuition fee fully paid -> Lead status synced

---

## 12. Payment Intent

**Source**: `app/models/finance/payment_intent.py` (`PaymentIntentStatusEnum`), `app/services/payment_intent_service.py`

```
created --> pending --> completed (creates Payment record)
        \-> expired    \-> failed
        \-> cancelled  \-> expired
                       \-> cancelled
```

| From | To | Method | Guard |
|------|----|--------|-------|
| (new) | `created` | `create_intent()` | -- |
| `created` | `pending` | `create_intent()` | Gateway adapter returns pay_url |
| `created` | `expired` | `expire_intent()` / auto-expire on read | `is_expired = True` |
| `created` | `cancelled` | `cancel_intent()` | NOT `is_terminal` |
| `pending` | `completed` | `process_callback()` | Gateway status = success, amount matches (C1) |
| `pending` | `failed` | `process_callback()` | Gateway status = failed/expired |
| `pending` | `expired` | `expire_intent()` / auto-expire | `is_expired = True` |
| `pending` | `cancelled` | `cancel_intent()` | NOT `is_terminal` |

**Terminal**: `completed`, `failed`, `expired`, `cancelled` (`is_terminal` property)

**Security**:
- C1: Verify gateway signature + amount match on callback
- Auto-expire on read: if intent.is_expired and status in (created, pending), set expired

**Side effect**: `completed` -> auto-creates Payment record with status `verified`

---

## 13. Refund Request

**Source**: `app/models/finance/refund.py` (`RefundStatusEnum`), `app/services/payment_service.py`

```
pending --> approved --> refunded
        \-> rejected
```

| From | To | Method | Guard |
|------|----|--------|-------|
| (new) | `pending` | `request_refund()` | Payment must be `verified` |
| `pending` | `approved` | `approve_refund()` | Must be pending |
| `pending` | `rejected` | `reject_refund()` | Must be pending, reason required |
| `approved` | `refunded` | `process_approved_refund()` | Must be approved |

**Terminal**: `refunded`, `rejected`

**Rules**:
- Refund amount cannot exceed `payment.amount - already_refunded`
- Sets `payment.status = refunded` when refund processed

**Cascading effects when refunded**:
1. `invoice.paid_amount -= refund.amount` -> invoice status reverts (partial/invoiced)
2. `fee.paid_amount -= refund.amount` -> fee status reverts (partial/invoiced)
3. If tuition fee refund -> Lead synced to sts18

---

## 14. Overpayment

**Source**: `app/models/finance/overpayment.py` (`OverpaymentStatusEnum`)

```
pending --> applied   (apply to another invoice)
        \-> refunded  (issue refund to student)
        \-> cancelled (write-off)
```

| From | To | Resolution Type | Guard |
|------|----|----------------|-------|
| (auto-created) | `pending` | -- | `payment.amount > invoice.remaining_amount` |
| `pending` | `applied` | `apply_to_next` | Select target invoice |
| `pending` | `refunded` | `refund` | Creates RefundRequest |
| `pending` | `cancelled` | `write_off` | Small amounts, manager approval |

**Terminal**: `applied`, `refunded`, `cancelled`

---

## Quick Reference: Cascade Chain

When a **Payment is verified**, the following cascade occurs:

```
Payment.verified
  -> Invoice.paid_amount += X
     -> Invoice.status = partial | paid
  -> Fee.paid_amount += X
     -> Fee.status = partial | paid
  -> If tuition fee fully paid:
     -> Lead.consultation_status = sts10 (system transition)
  -> If payment > invoice remaining:
     -> OverpaymentRecord created (pending)
```

When a **Refund is processed**:

```
RefundRequest.refunded
  -> Payment.status = refunded
  -> Invoice.paid_amount -= X
     -> Invoice.status = partial | issued
  -> Fee.paid_amount -= X
     -> Fee.status = partial | invoiced
  -> If tuition fee:
     -> Lead.consultation_status = sts18 (system transition)
```

---

## Architecture Notes

### Entities WITH explicit transition enforcement:
| Entity | Mechanism | File |
|--------|-----------|------|
| Admission Profile | `ALLOWED_TRANSITIONS` dict + `validate_transition()` | `admission_state_machine.py` |
| Lead Consultation Status | `allowed_transition` DB table + FSM Engine | `fsm_engine.py` |

### Entities with service-layer-only enforcement:
All finance entities (Fee, Invoice, Payment, PaymentIntent, Refund, Overpayment), Commission, Collaborator, Lead Validity, Lead Assignment.

These rely on:
1. Status CHECK constraints in DB (reject invalid enum values)
2. Service methods checking current status before updating
3. No centralized transition map -- transitions are implicit in service logic

### Recommendation for new features:
When adding transitions to finance/commission entities, verify against:
1. The enum values in the model (DB CHECK constraint)
2. The service method guards (current status checks)
3. The cascade effects documented above
