# Implementation Plan: Admission Authorization Audit Fixes

## Executive Summary

Fix 7 critical/high/medium issues identified in audit report. Estimated time: 6-8 hours including testing.

**Priority**: Critical 1.1-1.3 → High Risk 2.1-2.2 → Medium 3.1-3.2

---

## Critical Fixes (Session 1: 2-3 hours)

### 1.1 State Machine Violation in `enroll_student`

**File**: `Backend_FastAPI/app/services/admission_service.py:2434`

**Problem**: Allows APPROVED → ENROLLED, violating state machine (should be APPROVED → CONFIRMED → ENROLLED)

**Fix**: Add `validate_transition` before enrollment
```python
# Insert BEFORE line 2432
from .admission_state_machine import validate_transition

try:
    validate_transition(profile.status, "enrolled")
except ValueError as e:
    log.warning("Invalid state transition for enrollment",
                profile_id=profile.id, error=str(e))
    raise BadRequest(str(e))
```

**Test**:
- Valid: CONFIRMED/OVERRIDDEN → ENROLLED ✓
- Invalid: APPROVED → ENROLLED ✗ (should raise BadRequest)

---

### 1.2 Race Condition - Missing Row Locks

**Problem**: `update_profile`, `approve_profile`, `reject_profile`, `resubmit_profile` missing `with_for_update()` → Lost Update vulnerability

**Files**: `Backend_FastAPI/app/services/admission_service.py`

**Pattern to follow** (from `submit_and_evaluate:1705`):
```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload

stmt = (
    select(models.AdmissionProfile)
    .where(models.AdmissionProfile.id == profile_id)
    .options(selectinload(models.AdmissionProfile.lead))
    .with_for_update()  # ✅ CRITICAL: Acquire row lock
)
result = await db.execute(stmt)
profile = result.scalar_one_or_none()

if not profile:
    raise ResourceNotFoundError(...)

_check_admin_or_unit_access(profile, current_user)
```

**Changes**:

1. **`update_profile` (Line 1362)**
   - Replace existing profile fetch with locked query
   - Move IDOR check AFTER lock acquired

2. **`approve_profile` (Line 2620)**
   - Remove `profile` parameter
   - Add `profile_id: int` parameter
   - Fetch with lock at start of function
   - **Router update required**: `admissions.py:~750`

3. **`reject_profile` (Line 2701)**
   - Same pattern as approve_profile
   - **Router update required**: `admissions.py:~850`

4. **`resubmit_profile` (Line 2801)**
   - Same pattern as approve_profile
   - **Router update required**: `admissions.py:~950`

**Router signature changes**:
```python
# OLD
profile = await get_admission_for_manager(...)
result, callback = await admission_service.approve_profile(db, profile, ...)

# NEW
result, callback = await admission_service.approve_profile(db, profile_id, current_user, data)
```

**⚠️ CRITICAL: Dependency Injection** (per `AUTHORIZATION_GUIDELINES.md` Section 2.1):
```python
# ✅ CORRECT - Business APIs MUST use get_current_active_user
async def approve_profile(
    ...,
    current_user: models.User = Depends(deps.get_current_active_user)
):
    # Checks: token valid + user.status == 'active' + password_not_forced

# ❌ WRONG - Only for auth flows (logout, refresh)
async def approve_profile(
    ...,
    current_user: models.User = Depends(deps.get_current_user)
):
    # Security hole: allows locked/inactive users to operate
```

**Verify all endpoints use `get_current_active_user` (not `get_current_user`)**

**Test**: Concurrent approve/reject → second request should fail with ConflictError (409)

---

### 1.3 Missing `validate_transition` Calls

**Locations**:
- `update_profile:1389` - REJECTED → DRAFT
- `submit_and_evaluate:1897` - DRAFT → SUBMITTED

**Implementation**:

1. **State Machine Update** (`admission_state_machine.py:53`)
```python
ALLOWED_TRANSITIONS = {
    # ...
    AdmissionStatus.REJECTED: {
        AdmissionStatus.RESUBMITTED,
        AdmissionStatus.DRAFT  # ✅ ADD THIS
    },
    # ...
}
```

2. **Add validation calls**:
```python
# update_profile:1389
if profile.status == "rejected":
    try:
        validate_transition("rejected", "draft")
    except ValueError as e:
        raise BadRequest(str(e))
    profile.status = "draft"

# submit_and_evaluate:1897
try:
    validate_transition(profile.status, "submitted")
except ValueError as e:
    raise BadRequest(str(e))
profile.status = "submitted"
```

---

## High Risk Fixes (Session 2: 2-3 hours)

### 2.1 Extract Hard-coded Validation Logic

**File**: `Backend_FastAPI/app/services/admission_service.py`

**Problem**: `_compute_frontend_fields` (528 lines) contains hard-coded business rules

**Solution**: Extract to reusable validation methods

**New methods to create** (insert BEFORE `_compute_frontend_fields`):

```python
def _validate_scores(
    profile: models.AdmissionProfile,
    applied_rules: dict,
) -> tuple[bool, list[str]]:
    """Validate score requirements. Returns (is_valid, errors)."""
    # Extract lines 185-243 from _compute_frontend_fields
    # ...

def _validate_documents(
    profile: models.AdmissionProfile,
    documents: list,
    applied_rules: dict,
) -> tuple[bool, list[str], set[str]]:
    """Validate document requirements. Returns (is_valid, errors, missing_codes)."""
    # Extract lines 248-265 from _compute_frontend_fields
    # ...

def _validate_personal_info(
    profile: models.AdmissionProfile,
) -> tuple[bool, list[str], list[str]]:
    """Validate mandatory personal fields. Returns (is_valid, errors, missing_labels)."""
    # Extract lines 268-339 from _compute_frontend_fields
    # ...
```

**Then update `_compute_frontend_fields` to use them**:
```python
def _compute_frontend_fields(...):
    # Permissions logic (lines 102-156) - keep as is

    # Use extracted validators
    scores_valid, score_errors = _validate_scores(profile, applied_rules)
    docs_valid, doc_errors, missing_codes = _validate_documents(profile, documents, applied_rules)
    personal_valid, personal_errors, missing = _validate_personal_info(profile)

    validation_errors = score_errors + doc_errors + personal_errors
    # ... rest
```

**Benefits**:
- Testable in isolation
- Reusable in `submit_and_evaluate`
- Easier to maintain when rules change

**Test**: Unit tests for each validator + integration test ensuring output matches current behavior

---

### 2.2 Add IntegrityError Handling to `update_profile`

**File**: `Backend_FastAPI/app/services/admission_service.py:1529`

**Problem**: IntegrityError (unique constraint violation) not caught → 500 error instead of 409

**Fix**: Wrap flush in try/except
```python
try:
    await db.flush()
except IntegrityError as e:
    error_msg = str(e.orig)
    log.error("Update failed due to integrity error",
              profile_id=profile.id, error=error_msg)

    if "citizen_id" in error_msg.lower():
        raise ConflictError(f"CCCD {profile.citizen_id} đã tồn tại")
    elif "unique constraint" in error_msg.lower():
        raise ConflictError("Dữ liệu trùng lặp")
    else:
        raise ConflictError(f"Vi phạm ràng buộc dữ liệu: {error_msg}")
```

**Test**: Concurrent citizen_id updates → 409 ConflictError (not 500)

---

## Medium Fixes (Session 3: 2 hours)

### 3.1 Remove Frontend Logic from `AdminCard.tsx`

**Problem**: Frontend calculates document counts (violates Thin Client)

**Backend Changes**:

1. **Add stats to `_compute_frontend_fields`** (`admission_service.py`)
```python
# At end of function, before return
if documents is not None:
    mandatory_docs = [doc for doc in documents if doc.is_mandatory]
    profile.document_stats = {
        "submitted_count": len([d for d in mandatory_docs
                               if d.status in ["uploaded", "verified", "paper_submitted"]]),
        "verified_count": len([d for d in mandatory_docs if d.status == "verified"]),
        "mandatory_count": len(mandatory_docs),
        "missing_count": len([d for d in mandatory_docs if d.status == "missing"]),
    }
```

2. **Update Pydantic schema** (`Backend_FastAPI/app/schemas/admission.py`)
```python
# In AdmissionProfileResponse
document_stats: Optional[Dict[str, int]] = Field(
    None,
    description="Document stats (submitted/verified/mandatory/missing counts)"
)
```

3. **Update Zod schema** (`frontend/src/lib/zod/admissions.ts`)
```typescript
document_stats: z.object({
  submitted_count: z.number(),
  verified_count: z.number(),
  mandatory_count: z.number(),
  missing_count: z.number(),
}).nullable().optional(),
```

**Frontend Changes** (`AdminCard.tsx:36-43`):
```tsx
// Replace calculation with backend data
const stats = profile.document_stats ?? {
  submitted_count: 0,
  verified_count: 0,
  mandatory_count: 0,
  missing_count: 0,
}

const { submitted_count, verified_count, mandatory_count, missing_count } = stats
```

**Test**: Verify stats match old calculation, handle null gracefully

---

### 3.2 Legacy Fallback Code

**File**: `Backend_FastAPI/app/services/admission_service.py:1776-1796`

**Options**:
1. **Remove** if no legacy profiles exist (check DB first)
2. **Add expiry comment** "Remove after 2026-03-01"
3. **Create migration** to backfill `allowed_subject_codes`

**Recommendation**: Check production first
```sql
SELECT COUNT(*)
FROM admission_profile
WHERE applied_rules->>'allowed_subject_codes' IS NULL
  AND status != 'draft'
```

If count = 0, remove fallback code. Otherwise, add TODO with expiry date.

---

## Testing Strategy

### Critical Tests

**File**: `tests/integration/test_admission_state_transitions.py`

```python
@pytest.mark.integration
async def test_concurrent_approve_reject_race_condition(client, manager_user):
    """Fix 1.2: Concurrent approve/reject should fail with ConflictError."""
    profile = await create_profile(status="submitted")
    headers = await get_auth_headers(client, manager_user)

    # Launch concurrent requests
    responses = await asyncio.gather(
        client.post(f"/api/admissions/{profile.id}/approve",
                   json={"version": 1}, headers=headers),
        client.post(f"/api/admissions/{profile.id}/reject",
                   json={"version": 1, "reason": "Test"}, headers=headers),
        return_exceptions=True
    )

    # One succeeds (200), one fails (409)
    assert sorted([r.status_code for r in responses]) == [200, 409]

@pytest.mark.integration
async def test_state_machine_validation_enroll(client, admin_user):
    """Fix 1.1: APPROVED → ENROLLED should fail."""
    profile = await create_profile(status="approved")
    headers = await get_auth_headers(client, admin_user)

    res = await client.post(f"/api/admissions/{profile.id}/enroll", headers=headers)

    assert res.status_code == 400
    assert "Invalid transition" in res.json()["detail"]
```

### Unit Tests

**File**: `tests/unit/test_admission_validation.py` (new file)

```python
@pytest.mark.unit
def test_validate_scores_combined_method():
    """Fix 2.1: Test extracted validation function."""
    profile = Mock(average_score=5.0, total_score=18.0, admission_scores={"subject_scores": {}})
    rules = {"method_type": "combined", "min_gpa": 6.0, "min_score": 20.0}

    is_valid, errors = _validate_scores(profile, rules)

    assert not is_valid
    assert len(errors) == 2  # Both GPA and total score failed
```

---

## Verification Checklist

**Pre-Deployment**:
1. ✅ All state machine tests pass: `pytest tests/unit/test_admission_state_machine.py -v`
2. ✅ Concurrency tests pass: `pytest tests/integration/test_admission_state_transitions.py -v`
3. ✅ Frontend type check: `cd frontend && npm run type-check`
4. ✅ Integration smoke test: End-to-end workflow (create → submit → approve → enroll)

**Post-Deployment Monitoring**:
1. Monitor 409 ConflictError rate (expected to increase slightly from concurrent operations)
2. Alert if 500 IntegrityError appears (should be caught now)
3. Log search for "Invalid transition" errors (should only appear for invalid user actions)
4. Monitor query duration for locked operations (alert if > 5s)

---

## Rollback Plan

### Emergency Rollback (if locks cause deadlocks)

```bash
# Backend
cd Backend_FastAPI
git revert <commit-hash-locks>
pytest tests/integration/ -v

# Or hot-patch: Comment out .with_for_update() temporarily
# Then investigate deadlock cause
```

### Per-Fix Rollback

| Fix | Complexity | Rollback Command |
|-----|-----------|------------------|
| 1.1 | Easy | `git revert <hash>` |
| 1.2 | Moderate | Revert service + router changes |
| 1.3 | Easy | `git revert <hash>` + revert state machine |
| 2.1 | Moderate | Revert extracted functions |
| 2.2 | Easy | `git revert <hash>` |
| 3.1 | Complex | Revert backend + frontend + schemas |
| 3.2 | Easy | Restore fallback code |

---

## Critical Files

1. `Backend_FastAPI/app/services/admission_service.py` - All 7 fixes (lines 84-3100)
2. `Backend_FastAPI/app/services/admission_state_machine.py` - Add REJECTED → DRAFT (line 53)
3. `Backend_FastAPI/app/routers/admissions.py` - Signature updates for locks (lines 750, 850, 950)
4. `Backend_FastAPI/app/schemas/admission.py` - Add document_stats field
5. `frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/executive-summary/AdminCard.tsx` - Remove logic (lines 36-43)

---

## Implementation Order

**Must be sequential** (dependencies exist):

```
Session 1: Critical (Sequential)
├─ 1.3a: Add REJECTED → DRAFT to state machine
├─ 1.1: Add validate_transition to enroll_student
├─ 1.2a: Add lock to update_profile
├─ 1.2b: Add lock + signature change to approve_profile + router
├─ 1.2c: Add lock + signature change to reject_profile + router
└─ 1.2d: Add lock + signature change to resubmit_profile + router

Session 2: High Risk (Can parallelize)
├─ 2.1: Extract validation methods
└─ 2.2: Add IntegrityError handling

Session 3: Cleanup (Can parallelize)
├─ 3.1: Add document_stats (backend → schemas → frontend)
└─ 3.2: Handle legacy fallback
```
