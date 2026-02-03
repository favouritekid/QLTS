# Finance Module Schema Enhancements

**Version**: 2.0
**Date**: 2026-02-03
**Status**: ✅ Core Implementation Complete (P1, P2, P3 for main entities)

## Overview

This document tracks the schema enhancements for the Finance Module to support **Thin Client** architecture. The backend now returns explicit `can_*` permission flags.

---

## Priority Legend

- **P1**: Critical for Thin Client compliance (permission flags) - ✅ COMPLETE
- **P2**: Important for UX (denormalized display names) - ✅ COMPLETE
- **P3**: Nice to have (additional metadata) - ✅ PARTIAL (due_date added)

---

## 1. FeeResponse Enhancements ✅ COMPLETE

**File**: `app/schemas/finance.py` - `FeeResponse`
**Router**: `app/routers/fees.py` - `_build_fee_response()`

### P1 - Permission Flags ✅
```python
# Added to FeeResponse
can_waive: bool = False
can_cancel: bool = False
can_recalculate: bool = False
```

**Logic** (implemented in `_build_fee_response()`):
- `can_waive`: `status not in ['paid', 'cancelled', 'waived'] and remaining_amount > 0`
- `can_cancel`: `status not in ['paid', 'cancelled', 'waived'] and paid_amount == 0`
- `can_recalculate`: `status not in ['paid', 'cancelled', 'waived'] and paid_amount == 0`

### P3 - Additional Metadata ✅ (partial)
```python
# Added to FeeResponse
due_date: date | None = None  # First invoice due date for quick reference
```

---

## 2. InvoiceResponse Enhancements ✅ COMPLETE

**File**: `app/schemas/finance.py` - `InvoiceResponse`
**Router**: `app/routers/invoices.py` - `_build_invoice_response()`

### P1 - Permission Flags ✅
```python
# Added to InvoiceResponse
can_issue: bool = False
can_cancel: bool = False
can_record_payment: bool = False
can_apply_penalty: bool = False
```

**Logic** (implemented in `_build_invoice_response()`):
- `can_issue`: `status == 'draft'`
- `can_cancel`: `status not in ['paid', 'cancelled'] and paid_amount == 0`
- `can_record_payment`: `status == 'issued' and remaining_amount > 0`
- `can_apply_penalty`: `status == 'overdue'`

---

## 3. PaymentResponse Enhancements ✅ COMPLETE

**File**: `app/schemas/finance.py` - `PaymentResponse`
**Router**: `app/routers/payments.py` - `_build_payment_response()`

### P1 - Permission Flags (Maker-Checker) ✅
```python
# Added to PaymentResponse
can_verify: bool = False
can_reject: bool = False
```

**Logic** (implemented in `_build_payment_response()`):
- `can_verify`: `status == 'pending' and current_user_id != created_by_id`
- `can_reject`: `status == 'pending' and current_user_id != created_by_id`

**Maker-Checker Enforcement**:
- All Payment endpoints pass `current_user.id` to `_build_payment_response()`
- Permission flags are `False` if the current user created the payment
- This prevents self-approval at the API response level

### P2 - Denormalized Display Names ✅
```python
# Added to PaymentResponse
created_by_name: str | None = None
verified_by_name: str | None = None
```

**Implementation**:
- User relationships loaded via `get_by_id_with_relations()` in PaymentRepository
- Names extracted from `payment.created_by.full_name` and `payment.verified_by.full_name`
- Endpoints use repository method that includes `joinedload(Payment.created_by)`, `joinedload(Payment.verified_by)`

---

## 4. Remaining P3 Enhancements (Not Yet Implemented)

### InstallmentPlanResponse
```python
# TODO: Add to InstallmentPlanResponse
description: str | None = None
penalty_type: Literal["percentage", "fixed"] = "percentage"
grace_period_days: int = 0
```

### PaymentMethodResponse
```python
# TODO: Add to PaymentMethodResponse
description: str | None = None
```

### ProfileFinanceSummary
```python
# TODO: Add to ProfileFinanceSummary
has_fee: bool = False
fee_status: FeeStatus | None = None
overdue_amount: Decimal = Decimal("0")
last_payment_date: date | None = None
```

### PaymentIntentResponse
```python
# TODO: Add to PaymentIntentResponse
updated_at: datetime
completed_at: datetime | None = None
callback_received_at: datetime | None = None
callback_data: dict | None = None
gateway_response: dict | None = None
idempotency_key: str
```

---

## 5. Overpayment/Refund Permission Flags (P1 - Future)

**Status**: Blocked - Backend routers not yet implemented

```python
# Add to OverpaymentRecordResponse (when router implemented)
can_resolve: bool = False

# Add to RefundRequestResponse (when router implemented)
can_approve: bool = False
can_reject: bool = False
can_process: bool = False

# Add to AccountingPeriodResponse
can_close: bool = False
```

---

## 6. FinanceDashboardResponse (P1 - Future)

**Status**: Blocked - Dashboard endpoint not yet implemented

```python
class FinanceDashboardResponse(BaseModel):
    pending_fees_count: int = 0
    pending_fees_amount: Decimal = Decimal("0")
    pending_payments_count: int = 0
    overdue_invoices_count: int = 0
    overdue_amount: Decimal = Decimal("0")
    today_collections: Decimal = Decimal("0")
    monthly_collections: Decimal = Decimal("0")
    pending_overpayments_count: int = 0
    pending_refunds_count: int = 0
```

---

## Implementation Summary

| Entity | P1 Permission Flags | P2 Denormalized Names | P3 Metadata |
|--------|--------------------|-----------------------|-------------|
| FeeResponse | ✅ can_waive, can_cancel, can_recalculate | N/A | ✅ due_date |
| InvoiceResponse | ✅ can_issue, can_cancel, can_record_payment, can_apply_penalty | N/A | - |
| PaymentResponse | ✅ can_verify, can_reject (with Maker-Checker) | ✅ created_by_name, verified_by_name | - |
| OverpaymentRecordResponse | - | - | - |
| RefundRequestResponse | - | - | - |
| AccountingPeriodResponse | - | - | - |

---

## Testing Checklist

After implementing each enhancement:

- [ ] Unit tests for permission flag computation
- [ ] Integration tests for Maker-Checker logic
- [ ] API response validation tests
- [ ] Frontend contract tests (types match)

---

## Related Files

**Backend**:
- `Backend_FastAPI/app/schemas/finance.py` - Pydantic schemas
- `Backend_FastAPI/app/routers/fees.py` - Fee router with `_build_fee_response()`
- `Backend_FastAPI/app/routers/invoices.py` - Invoice router with `_build_invoice_response()`
- `Backend_FastAPI/app/routers/payments.py` - Payment router with `_build_payment_response()`
- `Backend_FastAPI/app/repositories/payment_repository.py` - Repository with eager loading

**Frontend**:
- `frontend/src/types/finance.types.ts` - TypeScript types
- `frontend/src/lib/zod/finance.ts` - Zod validation schemas
- `frontend/src/hooks/finance/usePaymentViewModel.ts` - ViewModel with temporary workarounds (can be updated now)

---

## Notes

1. All `can_*` flags are computed in the router helper functions (`_build_*_response()`), NOT in the schema's computed properties, to allow proper authorization context.

2. For Maker-Checker, the backend passes `current_user.id` to `_build_payment_response()` to compute `can_verify` and `can_reject`. This ensures a user cannot verify/reject their own payment.

3. Denormalized names (`created_by_name`, `verified_by_name`) are populated via JOIN in the repository layer using `joinedload()` to avoid N+1 queries.

4. The frontend ViewModel hooks (`useFeeViewModel.ts`, `useInvoiceViewModel.ts`, `usePaymentViewModel.ts`) contain `derivePermissionFlags()` helpers as temporary workarounds. These can now be updated to use the backend-provided `can_*` flags.
