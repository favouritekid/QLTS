# 📋 ADMISSION STATE MACHINE - PRE-IMPLEMENTATION VERIFICATION

> **Plan Reference:** ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md v3.0  
> **Date:** 2026-01-06  
> **Status:** PENDING APPROVAL  

---

# SECTION 1 — IMPLEMENTATION CHECKLIST (MANDATORY)

## 1.1 Router Layer Checklist

| # | Rule | Source | Verified |
|:-:|------|--------|:--------:|
| R1 | [ ] Router contains NO if/else for state validation | MASTER_ARCHITECTURE 0.2 | ⬜ |
| R2 | [ ] Router contains NO business logic | MASTER_ARCHITECTURE 1.1 | ⬜ |
| R3 | [ ] All dependencies injected via `Depends()` | Part 1.1 MANDATORY PATTERNS | ⬜ |
| R4 | [ ] Every endpoint has `response_model=Schema` | Part 1.1 MANDATORY PATTERNS | ⬜ |
| R5 | [ ] Router calls `await db.commit()` | Part 1.1 MANDATORY PATTERNS | ⬜ |
| R6 | [ ] Router calls `await callback()` after commit | Part 1.3 CALLBACK PATTERN | ⬜ |
| R7 | [ ] No direct SQL/DB access in router | FORBIDDEN ACTIONS | ⬜ |
| R8 | [ ] No `try/except` with business logic | FORBIDDEN ACTIONS | ⬜ |

## 1.2 Dependency Layer Checklist

| # | Rule | Source | Verified |
|:-:|------|--------|:--------:|
| D1 | [ ] `get_admission_for_manager` uses 404 (not 403) for IDOR | AUTH_GUIDELINES 4.2 | ⬜ |
| D2 | [ ] `get_admission_for_owner` checks `lead.user_id` | Plan Section 3.3.2 (FIXED) | ⬜ |
| D3 | [ ] All dependencies check `current_user.role` for bypass | Plan 0.4.3 | ⬜ |
| D4 | [ ] Admin bypass is explicit and audited | Plan 0.4.2 | ⬜ |
| D5 | [ ] No business logic in dependency (only auth/IDOR) | MASTER_ARCHITECTURE 1.2 | ⬜ |
| D6 | [ ] Uses `get_current_active_user` (not `get_current_user`) | AUTH_GUIDELINES 2.1 | ⬜ |

## 1.3 Service Layer Checklist

| # | Rule | Source | Verified |
|:-:|------|--------|:--------:|
| S1 | [ ] Service uses `ALLOWED_TRANSITIONS` map for validation | Plan Section 1.4 | ⬜ |
| S2 | [ ] Service raises `BusinessRuleViolation` for invalid transition | Part 2.2 | ⬜ |
| S3 | [ ] Service does NOT call `db.commit()` | MASTER_ARCHITECTURE 1.3 | ⬜ |
| S4 | [ ] Service returns `(result, callback)` tuple | MASTER_ARCHITECTURE 1.3 | ⬜ |
| S5 | [ ] Service does NOT import `HTTPException` | Part 1.3 RULES | ⬜ |
| S6 | [ ] Service does NOT import `Request` or `Response` | Part 1.3 RULES | ⬜ |
| S7 | [ ] Service checks `profile.version` for optimistic locking | Plan 0.4.4 | ⬜ |
| S8 | [ ] Service increments `profile.version` on write | Plan 0.4.4 | ⬜ |
| S9 | [ ] `override()` has full audit logging | Plan 0.4.2 | ⬜ |
| S10 | [ ] `reject()` requires reason field | Plan Section 2.1 | ⬜ |

## 1.4 Repository & Database Checklist

| # | Rule | Source | Verified |
|:-:|------|--------|:--------:|
| DB1 | [ ] Repository inherits `BaseRepository` | MASTER_ARCHITECTURE 1.4 | ⬜ |
| DB2 | [ ] Repository uses `selectinload` for relationships | Part C.1 | ⬜ |
| DB3 | [ ] Repository returns `None` (not exception) for not found | Part 1.4 RULES | ⬜ |
| DB4 | [ ] No direct status update allowed via SQL | Plan 0.4.1 | ⬜ |

## 1.5 Authorization & Casbin Checklist

| # | Rule | Source | Verified |
|:-:|------|--------|:--------:|
| C1 | [ ] `role:manager` has approve/reject policies | Plan Phase 1 | ⬜ |
| C2 | [ ] `role:officer` has resubmit policy | Plan Phase 2 | ⬜ |
| C3 | [ ] `role:user` has confirm policy | Plan Phase 3 | ⬜ |
| C4 | [ ] `role:admin` has override/finalize policies (explicit) | Plan Phase 4 | ⬜ |
| C5 | [ ] No wildcard for non-admin roles | Plan 0.4 Wildcard Clarification | ⬜ |

---

# SECTION 2 — EXPECTED FILE DIFF PLAN (MANDATORY)

## 2.1 Router Layer

### File: `app/routers/admissions.py`

**Will Change:**
- Add 6 new endpoints: approve, reject, resubmit, confirm, override, finalize
- Each endpoint follows dumb router pattern

**MUST NOT Change:**
- Existing CRUD endpoints logic
- No business logic added
- No state validation in router

**Expected Lines Added:** ~120 lines (6 endpoints × ~20 lines each)

---

## 2.2 Dependency Layer

### File: `app/core/deps.py`

**Will Change:**
- Add `get_admission_for_manager` dependency
- Add `get_admission_for_owner` dependency (SELF check with `lead.user_id`)

**MUST NOT Change:**
- Existing dependencies
- No business logic (only auth/IDOR)

**Expected Lines Added:** ~40 lines (2 dependencies × ~20 lines each)

---

## 2.3 Service Layer

### File: `app/services/admission_service.py`

**Will Change:**
- Add `approve_profile()` method
- Add `reject_profile()` method
- Add `resubmit_profile()` method
- Add `confirm_enrollment()` method
- Add `override_profile()` method (with audit)
- Add `finalize_profile()` method

**MUST NOT Change:**
- No `HTTPException` imports
- No `db.commit()` calls
- Existing methods remain unchanged

**Expected Lines Added:** ~200 lines (6 methods × ~30 lines each + helpers)

---

### File: `app/services/admission_state_machine.py` (NEW)

**Will Create:**
- `AdmissionStatus` enum
- `ALLOWED_TRANSITIONS` dict
- `can_transition()` function
- `get_allowed_transitions()` function

**MUST Comply:**
- Pure Python, no HTTP
- No side effects

**Expected Lines:** ~50 lines

---

## 2.4 Schema Layer

### File: `app/schemas/admission.py`

**Will Change:**
- Add `ApproveRequest` schema
- Add `RejectRequest` schema (reason required)
- Add `ResubmitRequest` schema
- Add `ConfirmRequest` schema
- Add `OverrideRequest` schema (reason required)

**MUST NOT Change:**
- Existing response schemas
- No breaking changes to existing API

**Expected Lines Added:** ~60 lines

---

## 2.5 Migration

### File: `alembic/versions/p6_add_admission_state_policies.py` (NEW)

**Will Create:**
- Add Casbin policies for approve, reject, resubmit, confirm, override, finalize

**MUST Comply:**
- Has safety checks (admin wildcard exists)
- Has downgrade function

**Expected Lines:** ~80 lines

---

## 2.6 Tests

### File: `tests/unit/services/test_admission_state_machine.py` (NEW)

**Will Create:**
- State transition tests
- Invalid transition tests
- Edge case tests

**Expected Lines:** ~100 lines

---

### File: `tests/integration/api/test_admission_workflow.py` (NEW)

**Will Create:**
- Full workflow integration tests
- Role-based access tests
- IDOR tests
- Replay attack tests
- Concurrency test

**Expected Lines:** ~300 lines

---

## 2.7 Summary

| Layer | Files | New | Modified | Lines Added |
|-------|:-----:|:---:|:--------:|:-----------:|
| Router | 1 | 0 | 1 | ~120 |
| Dependency | 1 | 0 | 1 | ~40 |
| Service | 2 | 1 | 1 | ~250 |
| Schema | 1 | 0 | 1 | ~60 |
| Migration | 1 | 1 | 0 | ~80 |
| Tests | 2 | 2 | 0 | ~400 |
| **TOTAL** | **8** | **4** | **4** | **~950** |

---

# SECTION 3 — TEST PLAN (MANDATORY)

## 3.1 State Transition Validity Tests

| Test ID | Scenario | From State | To State | Expected Result |
|:-------:|----------|------------|----------|-----------------|
| ST-01 | Valid: submit draft | DRAFT | SUBMITTED | ✅ Success |
| ST-02 | Valid: approve submitted | SUBMITTED | APPROVED | ✅ Success |
| ST-03 | Valid: reject submitted | SUBMITTED | REJECTED | ✅ Success |
| ST-04 | Valid: approve resubmitted | RESUBMITTED | APPROVED | ✅ Success |
| ST-05 | Valid: resubmit rejected | REJECTED | RESUBMITTED | ✅ Success |
| ST-06 | Valid: confirm approved | APPROVED | CONFIRMED | ✅ Success |
| ST-07 | Valid: override approved | APPROVED | OVERRIDDEN | ✅ Success |
| ST-08 | Valid: enroll confirmed | CONFIRMED | ENROLLED | ✅ Success |
| ST-09 | Valid: finalize overridden | OVERRIDDEN | ENROLLED | ✅ Success |
| ST-10 | Invalid: approve draft | DRAFT | APPROVED | ❌ BusinessRuleViolation |
| ST-11 | Invalid: confirm submitted | SUBMITTED | CONFIRMED | ❌ BusinessRuleViolation |
| ST-12 | Invalid: transition from enrolled | ENROLLED | * | ❌ BusinessRuleViolation |

## 3.2 Replay Attack Tests

| Test ID | Scenario | Expected Result |
|:-------:|----------|-----------------|
| RA-01 | Call approve twice on same profile | 1st: 200 OK, 2nd: 400 (already approved) |
| RA-02 | Call reject twice on same profile | 1st: 200 OK, 2nd: 400 (already rejected) |
| RA-03 | Approve then reject same profile | 1st: 200 OK, 2nd: 400 (wrong state) |
| RA-04 | Confirm twice | 1st: 200 OK, 2nd: 400 (already confirmed) |

## 3.3 IDOR Tests

| Test ID | Scenario | Role | Expected Result |
|:-------:|----------|------|-----------------|
| IDOR-01 | Manager approves profile in own unit | Manager | ✅ 200 OK |
| IDOR-02 | Manager approves profile in OTHER unit | Manager | ❌ **404 Not Found** |
| IDOR-03 | Officer resubmits profile in own unit | Officer | ✅ 200 OK |
| IDOR-04 | Officer resubmits profile in OTHER unit | Officer | ❌ **404 Not Found** |
| IDOR-05 | User confirms OWN profile | User | ✅ 200 OK |
| IDOR-06 | User confirms SOMEONE ELSE's profile | User | ❌ **404 Not Found** |
| IDOR-07 | Admin accesses any profile | Admin | ✅ 200 OK (bypass) |

> ⚠️ **CRITICAL:** All IDOR failures MUST return 404 (not 403) per AUTH_GUIDELINES 4.2

## 3.4 Role-Based Access Tests

| Test ID | Endpoint | User | Officer | Manager | Admin |
|:-------:|----------|:----:|:-------:|:-------:|:-----:|
| RBAC-01 | POST /approve | ❌ 403 | ❌ 403 | ✅ 200 | ✅ 200 |
| RBAC-02 | POST /reject | ❌ 403 | ❌ 403 | ✅ 200 | ✅ 200 |
| RBAC-03 | POST /resubmit | ❌ 403 | ✅ 200 | ✅ 200 | ✅ 200 |
| RBAC-04 | POST /confirm | ✅ 200* | ❌ 403 | ❌ 403 | ✅ 200 |
| RBAC-05 | POST /override | ❌ 403 | ❌ 403 | ❌ 403 | ✅ 200 |
| RBAC-06 | POST /finalize | ❌ 403 | ❌ 403 | ❌ 403 | ✅ 200 |

> *User can only confirm OWN profile (SELF check)

## 3.5 Concurrency (Race Condition) Test

| Test ID | Scenario | Expected Behavior |
|:-------:|----------|-------------------|
| RACE-01 | 2 managers approve same profile simultaneously | One succeeds, one fails with `ConcurrentModificationError` |
| RACE-02 | Manager approves while another rejects | One succeeds, one fails |
| RACE-03 | Version mismatch on write | Return 409 Conflict |

## 3.6 Audit Logging Tests

| Test ID | Scenario | Expected Audit |
|:-------:|----------|----------------|
| AUDIT-01 | Override action | Full log: actor, profile, reason, timestamp |
| AUDIT-02 | Override without reason | ❌ 400 Bad Request (reason required) |

---

# SECTION 4 — SELF-REVIEW CONTRACT (MANDATORY)

## 4.1 Architecture Compliance Declaration

Upon completion of implementation, I will verify:

### Router Layer
- [ ] **"No business logic exists in routers"**
- [ ] **"No if/else statements for state validation in routers"**
- [ ] **"All dependencies are injected via Depends()"**
- [ ] **"Every endpoint has response_model"**
- [ ] **"Router calls db.commit() and callback()"**

### Dependency Layer
- [ ] **"All IDOR checks return 404, not 403"**
- [ ] **"get_admission_for_owner uses lead.user_id (not assigned_officer_id)"**
- [ ] **"No business logic in dependencies"**

### Service Layer
- [ ] **"All state transitions are validated through ALLOWED_TRANSITIONS map"**
- [ ] **"No HTTPException imported in service"**
- [ ] **"No db.commit() in service"**
- [ ] **"All methods return (result, callback) tuple"**
- [ ] **"Version check is mandatory for ALL write operations"**

### Authorization
- [ ] **"No unauthorized state change is possible"**
- [ ] **"Casbin policies match role-action matrix"**
- [ ] **"Admin-only endpoints use require_admin or explicit policies"**

### Data Integrity
- [ ] **"Optimistic locking prevents race conditions"**
- [ ] **"Override has full audit trail"**
- [ ] **"Reject requires reason field"**

---

## 4.2 Deviation Declaration

After implementation, I will explicitly state ONE of the following:

**Option A:**
> ✅ "I confirm there are NO deviations from the plan."

**Option B:**
> ⚠️ "I list ALL deviations below."
> - [Deviation 1]: [Reason]
> - [Deviation 2]: [Reason]
> - ...

---

## 4.3 Pre-Merge Checklist

Before requesting merge/approval:

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] No linting errors
- [ ] Code review by human (if required)
- [ ] Migration tested on dev database
- [ ] Casbin policies verified in database

---

# APPROVAL REQUEST

> **This document contains all 4 mandatory sections required before implementation.**
> 
> **Awaiting approval to proceed with code implementation.**

---

**END OF PRE-IMPLEMENTATION VERIFICATION**
