# Integration Test Failures Report

**Date**: 2026-01-07
**Test File**: [test_admission_state_transitions.py](../Backend_FastAPI/tests/integration/test_admission_state_transitions.py)
**Status**: ❌ 7 FAILED, 11 PASSED
**Severity**: 🔴 CRITICAL - Production Blockers Found

---

## Executive Summary

Integration tests đã phát hiện **7 critical bugs** trong admission state machine implementation:

1. 🔴 **CRITICAL**: Race condition - concurrent requests cùng thành công
2. 🔴 **CRITICAL**: Optimistic locking không hoạt động
3. 🔴 **CRITICAL**: `admission_repo` undefined causing NameError
4. ⚠️ **HIGH**: RBAC permission denied for officer reject
5. ⚠️ **MEDIUM**: Test setup issue (OrganizationUnit schema)

**Impact**: Application **KHÔNG AN TOÀN** cho production deployment.

---

## Test Results Summary

```
================================================================
7 failed, 11 passed, 1368 warnings in 107.90s (0:01:47)
================================================================
```

### Passed Tests ✅ (11)

- ✅ TestReplayAttack::test_approve_already_approved_profile
- ✅ TestReplayAttack::test_reject_already_rejected_profile
- ✅ TestIDORProtection::test_admin_can_access_any_profile
- ✅ TestTokenBasedConfirmation (all 6 tests passed)

### Failed Tests ❌ (7)

1. ❌ TestRaceCondition::test_concurrent_approve_reject
2. ❌ TestRaceCondition::test_concurrent_double_approve
3. ❌ TestVersionChecking::test_approve_with_stale_version
4. ❌ TestIDORProtection::test_manager_cannot_access_other_unit_profile
5. ❌ TestStateTransitionWorkflows::test_happy_path_normal_flow
6. ❌ TestStateTransitionWorkflows::test_rejection_recovery_flow
7. ❌ TestStateTransitionWorkflows::test_admin_override_flow

---

## Bug Analysis

### 🔴 BUG #1: Race Condition (CRITICAL)

**Test**: `test_concurrent_approve_reject`, `test_concurrent_double_approve`

**Failure**:
```python
FAILED - AssertionError: Concurrent request should fail with 400 or 409. Got: [200, 200]
FAILED - AssertionError: Only one approval should succeed. Got: [200, 200]
```

**What Happened**:
- 2 concurrent requests (approve + reject) to same profile
- **BOTH requests succeeded** with 200 OK
- Final state: Last request wins (data race)
- Version incremented TWICE (should be once)

**Root Cause**:
Service layer **KHÔNG KIỂM TRA** version field:

```python
# admission_service.py:960
async def approve_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    approver: models.User,
    data: Dict[str, Any],  # Has 'version' field
) -> tuple[models.AdmissionProfile, Any]:
    # ❌ NO VERSION CHECK HERE!

    # Validate transition
    validate_transition(
        current_status=profile.status,
        new_status="approved",
        role=approver.role,
    )

    # ❌ Direct update without version check
    profile.status = "approved"
    profile.version += 1  # Race condition here!
```

**Impact**:
- Data corruption possible
- Concurrent approvals both succeed
- Lost updates (last write wins)
- **Violates ACID properties**

**Expected Behavior**:
```python
# First request: version=1 → SUCCESS (version becomes 2)
# Second request: version=1 → FAIL 409 Conflict (stale version)
```

**Fix Required**:
```python
async def approve_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    approver: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    # ✅ ADD VERSION CHECK
    requested_version = data.get("version")
    if requested_version is not None:
        if profile.version != requested_version:
            raise ConflictError(
                f"Version mismatch: expected {profile.version}, got {requested_version}. "
                "Profile was modified by another user. Please refresh and try again."
            )

    # Rest of logic...
```

---

### 🔴 BUG #2: Optimistic Locking Not Working (CRITICAL)

**Test**: `test_approve_with_stale_version`

**Failure**:
```python
FAILED - AssertionError: Should return 409 for stale version
assert 200 == 409
```

**What Happened**:
- Request sent with `version: current_version - 1` (stale)
- **Request SUCCEEDED** with 200 OK (should fail with 409)
- Profile updated even though version was outdated

**Root Cause**:
Same as Bug #1 - no version validation in service layer.

**Impact**:
- Optimistic locking **completely broken**
- Multiple users can overwrite each other's changes
- Lost update problem

**Fix Required**:
Same fix as Bug #1 - add version checking.

---

### 🔴 BUG #3: NameError - admission_repo Not Defined (CRITICAL)

**Test**: `test_happy_path_normal_flow`, `test_admin_override_flow`

**Failure**:
```python
NameError: name 'admission_repo' is not defined
```

**Location**: [admission_service.py](../Backend_FastAPI/app/services/admission_service.py)

**Root Cause**:
Service functions reference `admission_repo` but never initialize it:

```python
# Line 567 (submit_and_evaluate)
uploaded_docs = await admission_repo.get_uploaded_documents(profile.id)
# ❌ ERROR: admission_repo is not defined!
```

**Where It Happens**:
```python
# admission_service.py:123 - ✅ HAS IT
admission_repo = AdmissionRepository(db)

# admission_service.py:495 - ❌ MISSING
async def submit_and_evaluate(...):
    # admission_repo not initialized!
    uploaded_docs = await admission_repo.get_uploaded_documents(...)
```

**Impact**:
- **Application crashes** on submit_and_evaluate
- **Cannot submit profiles** for evaluation
- **Production blocker**

**Fix Required**:
```python
async def submit_and_evaluate(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> Dict[str, Any]:
    # ✅ ADD THIS
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Get profile with IDOR check
    profile = await get_profile(db, profile_id, current_user)

    # ... rest of logic
```

---

### ⚠️ BUG #4: Permission Denied on Reject (HIGH)

**Test**: `test_rejection_recovery_flow`

**Failure**:
```python
FAILED - AssertionError: Reject failed
{"detail":"You do not have permission for this action.","error_code":"PERMISSION_DENIED"}
assert 403 == 200
```

**What Happened**:
- Manager user tried to reject a profile
- **Got 403 Forbidden** (should be 200 OK)
- Manager has correct permissions per RBAC

**Root Cause**:
Likely Casbin policy misconfiguration or missing policy for `reject` action.

**Expected Policy**:
```python
# Manager can reject profiles in their unit
p, manager, admission_profile, reject, allow, UNIT
```

**Fix Required**:
Check and add Casbin policies for `reject` action.

---

### ⚠️ BUG #5: OrganizationUnit Schema Error (MEDIUM)

**Test**: `test_manager_cannot_access_other_unit_profile`

**Failure**:
```python
TypeError: 'code' is an invalid keyword argument for OrganizationUnit
```

**Root Cause**:
Test creates OrganizationUnit with `code` parameter:

```python
other_unit = models.OrganizationUnit(
    id=999,
    name="Other Unit",
    code="OTHER"  # ❌ OrganizationUnit doesn't have 'code' field
)
```

**Impact**:
- Test setup fails
- IDOR protection test cannot run
- Not a production bug (test-only issue)

**Fix Required**:
Update test to match actual OrganizationUnit schema (remove `code` parameter).

---

## Detailed Failure Logs

### Failure #1: Race Condition - Concurrent Approve/Reject

```
FAILED tests/integration/test_admission_state_transitions.py::TestRaceCondition::test_concurrent_approve_reject
AssertionError: Concurrent request should fail with 400 or 409. Got: [200, 200]
assert False
 +  where False = any(<generator...>)
```

**Test Code**:
```python
# Execute concurrently
results = await asyncio.gather(
    approve_request(),  # Result: 200 ❌ SUCCESS
    reject_request(),   # Result: 200 ❌ SUCCESS (should fail!)
    return_exceptions=True,
)
```

**Expected**: [200, 400] or [200, 409]
**Actual**: [200, 200] ❌

---

### Failure #2: Race Condition - Double Approve

```
FAILED tests/integration/test_admission_state_transitions.py::TestRaceCondition::test_concurrent_double_approve
AssertionError: Only one approval should succeed. Got: [200, 200]
assert 2 == 1
 +  where 2 = [200, 200].count(200)
```

**Test Code**:
```python
results = await asyncio.gather(
    approve(),  # Result: 200 ❌ SUCCESS
    approve(),  # Result: 200 ❌ SUCCESS (should fail!)
)
```

**Expected**: One 200, one 400/409
**Actual**: Both 200 ❌

---

### Failure #3: Version Checking Broken

```
FAILED tests/integration/test_admission_state_transitions.py::TestVersionChecking::test_approve_with_stale_version
AssertionError: Should return 409 for stale version
assert 200 == 409
 +  where 200 = <Response [200 OK]>.status_code
```

**Test Code**:
```python
# Request with stale version
response = await client.post(
    f"/api/admissions/{profile.id}/approve",
    json={"notes": "Approval", "version": current_version - 1},  # Stale!
)
```

**Expected**: 409 Conflict
**Actual**: 200 OK ❌ (profile updated with stale version)

---

### Failure #4: NameError in Service

```
FAILED tests/integration/test_admission_state_transitions.py::TestStateTransitionWorkflows::test_happy_path_normal_flow
NameError: name 'admission_repo' is not defined
```

**Stack Trace**:
```
File "app/services/admission_service.py", line 567
    uploaded_docs = await admission_repo.get_uploaded_documents(profile.id)
NameError: name 'admission_repo' is not defined
```

---

### Failure #5: RBAC Permission Denied

```
FAILED tests/integration/test_admission_state_transitions.py::TestStateTransitionWorkflows::test_rejection_recovery_flow
AssertionError: Reject failed: {"detail":"You do not have permission for this action.","error_code":"PERMISSION_DENIED"}
assert 403 == 200
```

**Request**:
```python
# Manager tries to reject
response = await client.post(
    f"/api/admissions/{profile.id}/reject",
    json={"reason": "Missing documents"},
    headers=manager_headers,
)
# Result: 403 Forbidden ❌
```

---

## Impact Assessment

### 🔴 Critical (Production Blockers)

**Bug #1 & #2: Race Condition + No Optimistic Locking**
- **Risk**: Data corruption in production
- **Scenario**: Two managers approve/reject simultaneously → both succeed
- **Impact**: Invalid state, lost updates, audit trail broken
- **Priority**: **FIX IMMEDIATELY**

**Bug #3: NameError**
- **Risk**: Application crashes on profile submission
- **Scenario**: User submits profile → 500 Internal Server Error
- **Impact**: **Cannot use admission system**
- **Priority**: **FIX IMMEDIATELY**

### ⚠️ High Priority

**Bug #4: RBAC Permission Denied**
- **Risk**: Managers cannot reject profiles
- **Scenario**: Workflow blocked at rejection step
- **Impact**: Manual workaround needed
- **Priority**: Fix before deployment

### ⚠️ Medium Priority

**Bug #5: Test Setup Issue**
- **Risk**: None (test-only)
- **Impact**: Cannot run IDOR protection test
- **Priority**: Fix for test coverage

---

## Fix Priority & Effort

| Bug | Severity | Fix Effort | Priority |
|-----|----------|------------|----------|
| #1 Race Condition | 🔴 CRITICAL | 2 hours | P0 |
| #2 Version Check | 🔴 CRITICAL | 1 hour | P0 |
| #3 NameError | 🔴 CRITICAL | 15 mins | P0 |
| #4 RBAC Permission | ⚠️ HIGH | 30 mins | P1 |
| #5 Test Setup | ⚠️ MEDIUM | 10 mins | P2 |

**Total Estimated Effort**: 4 hours

---

## Recommended Fixes

### Fix #1 & #2: Add Version Checking (2 hours)

**File**: [admission_service.py](../Backend_FastAPI/app/services/admission_service.py)

**Functions to Update**:
1. `approve_profile()`
2. `reject_profile()`
3. `confirm_profile()`
4. `finalize_profile()`
5. `override_profile()`

**Implementation**:
```python
def _validate_version(profile: models.AdmissionProfile, requested_version: Optional[int]):
    """
    Validate version for optimistic locking.

    Raises:
        ConflictError: If version mismatch detected
    """
    if requested_version is None:
        # Version not required (backwards compatibility)
        return

    if profile.version != requested_version:
        raise ConflictError(
            f"Version mismatch: profile has been modified by another user. "
            f"Expected version {requested_version}, current version is {profile.version}. "
            "Please refresh and try again."
        )

# Then in each state transition function:
async def approve_profile(db, profile, approver, data):
    # ✅ ADD THIS FIRST
    _validate_version(profile, data.get("version"))

    # Rest of logic...
    validate_transition(...)
    profile.status = "approved"
    profile.version += 1
    await db.flush()
```

**Testing**:
```bash
# After fix, run:
pytest tests/integration/test_admission_state_transitions.py::TestRaceCondition -v
pytest tests/integration/test_admission_state_transitions.py::TestVersionChecking -v
# Should PASS ✅
```

---

### Fix #3: Initialize admission_repo (15 minutes)

**File**: [admission_service.py](../Backend_FastAPI/app/services/admission_service.py)

**Functions to Fix**:
1. `submit_and_evaluate()` - line 495
2. Any other function using `admission_repo` without initializing

**Implementation**:
```python
async def submit_and_evaluate(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> Dict[str, Any]:
    # ✅ ADD THIS AT THE TOP
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Get profile with IDOR check
    profile = await get_profile(db, profile_id, current_user)

    # ... rest of logic (now admission_repo is defined)
    uploaded_docs = await admission_repo.get_uploaded_documents(profile.id)
```

---

### Fix #4: Add RBAC Policy for Reject (30 minutes)

**File**: Migration or seed script for Casbin policies

**Missing Policy**:
```python
# Allow managers to reject profiles in their unit
p, manager, admission_profile, reject, allow, UNIT
```

**Verification**:
```bash
# Check current policies
SELECT * FROM casbin_rule WHERE v1 = 'admission_profile' AND v2 = 'reject';
```

---

### Fix #5: Update Test Setup (10 minutes)

**File**: [test_admission_state_transitions.py](../Backend_FastAPI/tests/integration/test_admission_state_transitions.py)

**Line**: 458-465

**Fix**:
```python
# Before (broken):
other_unit = models.OrganizationUnit(
    id=999,
    name="Other Unit",
    code="OTHER"  # ❌ Invalid field
)

# After (fixed):
other_unit = models.OrganizationUnit(
    id=999,
    name="Other Unit"
    # ✅ Remove 'code' parameter
)
```

---

## Deployment Blocker Status

❌ **CANNOT DEPLOY TO PRODUCTION** until Critical bugs (#1, #2, #3) are fixed.

**Reason**:
- Race conditions will cause data corruption
- NameError will crash application
- Optimistic locking is broken

**Required Before Deployment**:
1. ✅ Fix version checking in all state transition functions
2. ✅ Add `admission_repo` initialization
3. ✅ Add missing RBAC policy for reject
4. ✅ Re-run integration tests (all must pass)

---

## Test Coverage Analysis

### What's Working ✅ (11 tests passed)

1. **Replay Attack Prevention**: ✅
   - Cannot approve already-approved profile
   - Cannot reject already-rejected profile
   - Cannot reuse confirmation tokens

2. **Token-Based Confirmation**: ✅
   - Valid tokens accepted
   - Invalid tokens rejected (404)
   - Expired tokens rejected
   - Wrong CCCD fails
   - Token locking after 5 attempts
   - Resend invalidates old token

3. **Admin Override**: ✅
   - Admins can access all profiles (no IDOR restrictions)

### What's Broken ❌ (7 tests failed)

1. **Race Condition Protection**: ❌
2. **Optimistic Locking**: ❌
3. **Service Layer Bugs**: ❌ (NameError)
4. **RBAC Completeness**: ❌ (missing reject policy)
5. **Test Setup**: ❌ (schema mismatch)

---

## Conclusion

✅ **Good News**: Token-based confirmation flow works perfectly
❌ **Bad News**: Core state machine has critical race condition bugs
⚠️ **Risk**: Production deployment will cause data corruption

**Next Steps**:
1. Fix optimistic locking (P0 - 2 hours)
2. Fix NameError (P0 - 15 minutes)
3. Fix RBAC policy (P1 - 30 minutes)
4. Re-run all integration tests
5. Verify all 18 tests pass before deployment

---

**Report Date**: 2026-01-07
**Total Test Time**: 107.90s
**Pass Rate**: 61% (11/18)
**Target**: 100% before production deployment

**Critical Bugs Found**: 3
**High Priority Bugs**: 1
**Medium Priority Bugs**: 1

**Status**: ❌ NOT READY FOR PRODUCTION
