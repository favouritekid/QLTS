# 🔥 GITHUB ISSUES - CODE QUALITY FIXES

**Generated:** 2025-12-02
**Total Issues:** 10
**Total Effort:** 72 hours

**Instructions:**
1. Copy each issue below to GitHub manually, OR
2. Run the automated script: `bash .github/create_issues.sh`

---

## 🚨 PRIORITY 0: EMERGENCY (Week 1)

---

### Issue #1: [CRITICAL] Fix IDOR Vulnerabilities in Applications Endpoints

**Labels:** `security`, `critical`, `bug`, `P0`
**Milestone:** Week 1 - Emergency Fixes
**Effort:** 4 hours
**Assignee:** [Auto-assign or specify]

#### Description

**Severity:** 🔴 CRITICAL - Data Breach Risk

Three application endpoints are vulnerable to IDOR (Insecure Direct Object Reference) attacks, allowing any authenticated user to access, modify, or delete ANY application by ID enumeration.

**Vulnerable Endpoints:**
- `GET /applications/{application_id}` - Line 97-129
- `PUT /applications/{application_id}` - Line 137-172
- `DELETE /applications/{application_id}` - Line 235-299

**Attack Vector:**
```bash
# Officer A can access Officer B's applications:
GET /applications/1  → 200 OK (own)
GET /applications/2  → 200 OK (Officer B's) ← VULNERABILITY!
GET /applications/3  → 200 OK (Officer C's) ← VULNERABILITY!
```

**Impact:**
- **Data Exposure:** Any user can read all applications (GDPR violation)
- **Data Modification:** Any user can modify any application
- **Data Deletion:** Any user can delete any application
- **Compliance Risk:** HIGH

**Files Affected:**
- `Backend_FastAPI/app/routers/applications.py`
- `Backend_FastAPI/app/core/deps.py` (new dependency to add)
- `Backend_FastAPI/app/services/application_service.py` (minor update)

#### Tasks

- [ ] **Step 1:** Create `get_application_for_user()` dependency in `deps.py` (1h)
  - [ ] Implement ownership verification logic
  - [ ] Handle Admin/Manager/Officer roles correctly
  - [ ] Add logging for unauthorized access attempts
- [ ] **Step 2:** Update `application_service.py` to support eager loading (30m)
  - [ ] Add `load_lead` parameter to `get_application_by_id()`
  - [ ] Add `selectinload` for lead relationships
- [ ] **Step 3:** Fix GET endpoint in `applications.py` (30m)
  - [ ] Replace parameters with dependency
  - [ ] Update docstring with access control rules
- [ ] **Step 4:** Fix PUT endpoint in `applications.py` (30m)
  - [ ] Use verified application ID from dependency
  - [ ] Update docstring
- [ ] **Step 5:** Fix DELETE endpoint in `applications.py` (30m)
  - [ ] Use verified application ID from dependency
  - [ ] Add deletion audit log
- [ ] **Step 6:** Add integration tests (1h)
  - [ ] Test Officer cannot access other Officer's application (403)
  - [ ] Test Officer can access own application (200)
  - [ ] Test Admin can access all applications (200)
  - [ ] Test Manager can access managed unit applications (200)
  - [ ] Test Manager cannot access other unit applications (403)
- [ ] **Step 7:** Manual verification (30m)
  - [ ] Test with Postman/curl
  - [ ] Verify 403 responses for unauthorized access
  - [ ] Update security audit documentation

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #1, Steps 1.1-1.7)
- **Audit Report:** `COMPREHENSIVE_CODE_AUDIT_REPORT.md` (Section II.C)
- **Similar Pattern:** `app/routers/leads.py` (LeadAccessDep - correct implementation)

#### Acceptance Criteria

- [ ] All 3 endpoints use `get_application_for_user` dependency
- [ ] All IDOR tests pass (5+ test cases)
- [ ] Manual testing confirms 403 for unauthorized access
- [ ] Code review approved
- [ ] Deployed to staging and verified

---

### Issue #2: [CRITICAL] Fix Transaction Management in config_service.py (18 violations)

**Labels:** `critical`, `refactoring`, `database`, `P0`
**Milestone:** Week 1 - Emergency Fixes
**Effort:** 10 hours
**Assignee:** [Auto-assign or specify]

#### Description

**Severity:** 🔴 CRITICAL - Data Consistency Risk

The `config_service.py` file has **18 violations** where services commit transactions internally instead of letting routers handle commits. This breaks atomicity when routers call multiple services in one request.

**Risk Scenario:**
```python
# Router calls multiple config updates
@router.post("/setup-pipeline")
async def setup_pipeline(...):
    await config_service.create_pipeline_stage(...)  # ✅ Commits
    await config_service.create_consultation_status(...)  # ✅ Commits
    await config_service.update_assignment_config(...)  # ❌ FAILS

    # Result: First 2 committed, last failed
    # → CANNOT ROLLBACK! (Partial success = data corruption)
```

**Violations (18 functions):**
1. Line 123: `update_assignment_config()`
2. Line 177: `create_degree_level()`
3. Line 204: `update_degree_level()`
4. Line 296: `delete_degree_level()`
5. Line 341: `create_tuition_fee()`
6. Line 382, 386: `delete_tuition_fee()`
7. Line 469: `create_consultation_status()`
8. Line 543: `update_consultation_status()`
9. Line 584, 588: `delete_consultation_status()`
10. Line 687: `create_pipeline_stage()`
11. Line 736: `update_pipeline_stage()`
12. Line 763, 767: `delete_pipeline_stage()`
13. Lines 946, 997, 1062: Other config functions

**Files Affected:**
- `Backend_FastAPI/app/services/config_service.py` (main file)
- `Backend_FastAPI/app/routers/admin/config.py` (router updates)

#### Tasks

**Phase 1: Audit & Plan (1h)**
- [ ] Document all 18 functions with violations
- [ ] Identify router endpoints for each function
- [ ] Create test cases for transaction rollback

**Phase 2: Refactor Services (6h)**

Apply this pattern to ALL 18 functions:

```python
# ❌ BEFORE (Service commits)
async def create_something(db, data):
    obj = Model(**data.dict())
    db.add(obj)
    await db.commit()  # ❌ Remove
    await invalidate_cache()
    return obj

# ✅ AFTER (Router commits)
async def create_something(db, data):
    """Does NOT commit. Router must commit and call callback."""
    obj = Model(**data.dict())
    db.add(obj)
    await db.flush()  # ✅ Get ID without committing

    async def _post_commit():
        await invalidate_cache()

    return obj, _post_commit
```

**Degree Level Functions:**
- [ ] Refactor `create_degree_level()` (30m)
- [ ] Refactor `update_degree_level()` (30m)
- [ ] Refactor `delete_degree_level()` (30m)

**Tuition Fee Functions:**
- [ ] Refactor `create_tuition_fee()` (30m)
- [ ] Refactor `update_tuition_fee()` (30m)
- [ ] Refactor `delete_tuition_fee()` (30m)

**Consultation Status Functions:**
- [ ] Refactor `create_consultation_status()` (30m)
- [ ] Refactor `update_consultation_status()` (30m)
- [ ] Refactor `delete_consultation_status()` (30m)

**Pipeline Stage Functions:**
- [ ] Refactor `create_pipeline_stage()` (30m)
- [ ] Refactor `update_pipeline_stage()` (30m)
- [ ] Refactor `delete_pipeline_stage()` (30m)

**Assignment Config & Others:**
- [ ] Refactor `update_assignment_config()` (30m)
- [ ] Refactor remaining 5 functions (2.5h)

**Phase 3: Update Routers (2h)**
- [ ] Update all router endpoints to commit and call callbacks
- [ ] Add try/except blocks with proper rollback
- [ ] Add transaction logging

**Phase 4: Testing (1h)**
- [ ] Unit tests for each refactored function
- [ ] Integration tests for transaction rollback
- [ ] Test multi-service endpoints
- [ ] Load testing to verify no performance regression

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #2.1, Steps 2.1.1-2.1.3)
- **Detailed Audit:** `TRANSACTION_AUDIT_REPORT.md` (config_service.py section)
- **Pattern:** See `lead_service.py` for correct `begin_nested()` pattern

#### Acceptance Criteria

- [ ] Zero `await db.commit()` in `config_service.py`
- [ ] All 18 functions return `(object, callback)` tuple
- [ ] All routers commit and execute callbacks
- [ ] Transaction rollback tests pass
- [ ] No performance regression (benchmark tests)
- [ ] Code review approved

---

### Issue #3: [CRITICAL] Fix Transaction Management in organization_service.py (13 violations)

**Labels:** `critical`, `refactoring`, `database`, `P0`
**Milestone:** Week 1 - Emergency Fixes
**Effort:** 8 hours

#### Description

**Severity:** 🔴 CRITICAL - Data Consistency Risk

The `organization_service.py` file has **13 violations** where services commit transactions internally.

**Violations:**
1. Line 359: `create_organization_unit()`
2. Line 477: `update_organization_unit()`
3. Line 548: `delete_organization_unit()`
4. Line 628: `create_program()`
5. Line 669: `update_program()`
6. Line 721: `delete_program()`
7. Line 797: `create_offering()`
8. Line 850: `update_offering()`
9. Line 883: `delete_offering()`
10. Line 1005: `create_academic_info()`
11. Line 1069: `update_academic_info()`
12. Line 1129: `delete_academic_info()`
13. Line 1172: `bulk_update_programs()`

**Files Affected:**
- `Backend_FastAPI/app/services/organization_service.py`
- `Backend_FastAPI/app/routers/admin/organization.py`

#### Tasks

- [ ] **Phase 1:** Audit all 13 functions (30m)
- [ ] **Phase 2:** Refactor Organization Unit functions (2h)
  - [ ] `create_organization_unit()` (30m)
  - [ ] `update_organization_unit()` (30m)
  - [ ] `delete_organization_unit()` (30m)
  - [ ] Update routers (30m)
- [ ] **Phase 3:** Refactor Program functions (2h)
  - [ ] `create_program()` (30m)
  - [ ] `update_program()` (30m)
  - [ ] `delete_program()` (30m)
  - [ ] Update routers (30m)
- [ ] **Phase 4:** Refactor Offering functions (2h)
  - [ ] `create_offering()` (30m)
  - [ ] `update_offering()` (30m)
  - [ ] `delete_offering()` (30m)
  - [ ] Update routers (30m)
- [ ] **Phase 5:** Refactor Academic Info functions (2h)
  - [ ] `create_academic_info()` (30m)
  - [ ] `update_academic_info()` (30m)
  - [ ] `delete_academic_info()` (30m)
  - [ ] Update routers (30m)
- [ ] **Phase 6:** Refactor `bulk_update_programs()` (1h)
- [ ] **Phase 7:** Testing (30m)

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #2.2)
- **Audit Report:** `TRANSACTION_AUDIT_REPORT.md`

#### Acceptance Criteria

- [ ] Zero `await db.commit()` in `organization_service.py`
- [ ] All functions return callbacks
- [ ] Routers commit and execute callbacks
- [ ] Tests pass

---

### Issue #4: [CRITICAL] Fix Transaction Management in user_service.py (10 violations)

**Labels:** `critical`, `refactoring`, `database`, `P0`
**Milestone:** Week 1 - Emergency Fixes
**Effort:** 6 hours

#### Description

**Severity:** 🔴 CRITICAL - Data Consistency Risk

The `user_service.py` file has **10 violations** where services commit transactions internally.

**Violations:**
1. Line 328: `create_user()`
2. Line 428: `update_user()`
3. Line 716: `update_user_profile()`
4. Line 785: `change_password()`
5. Line 827: `reset_password()`
6. Line 919: `invalidate_all_sessions()`
7. Line 943: `assign_role()`
8. Line 982: `update_user_units()`
9. Line 1119: `import_users_from_csv()`
10. Line 1285: `bulk_update_users()`

**Files Affected:**
- `Backend_FastAPI/app/services/user_service.py`
- `Backend_FastAPI/app/routers/admin/users.py`
- `Backend_FastAPI/app/routers/auth.py`

#### Tasks

- [ ] **Phase 1:** Refactor User CRUD (2h)
  - [ ] `create_user()` (30m)
  - [ ] `update_user()` (30m)
  - [ ] `update_user_profile()` (30m)
  - [ ] Update routers (30m)
- [ ] **Phase 2:** Refactor Password functions (1.5h)
  - [ ] `change_password()` (30m)
  - [ ] `reset_password()` (30m)
  - [ ] Update routers (30m)
- [ ] **Phase 3:** Refactor Session/Role functions (1.5h)
  - [ ] `invalidate_all_sessions()` (30m)
  - [ ] `assign_role()` (30m)
  - [ ] `update_user_units()` (30m)
- [ ] **Phase 4:** Refactor Bulk operations (1.5h)
  - [ ] `import_users_from_csv()` (45m)
  - [ ] `bulk_update_users()` (45m)
- [ ] **Phase 5:** Testing (30m)

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #2.3)

#### Acceptance Criteria

- [ ] Zero `await db.commit()` in `user_service.py`
- [ ] All functions return callbacks
- [ ] Tests pass

---

### Issue #5: [CRITICAL] Fix Transaction Management in pipeline_service.py (8 violations)

**Labels:** `critical`, `refactoring`, `database`, `P0`
**Milestone:** Week 1 - Emergency Fixes
**Effort:** 5 hours

#### Description

**Severity:** 🔴 CRITICAL - Data Consistency Risk

The `pipeline_service.py` file has **8 violations** where services commit transactions internally.

**Files Affected:**
- `Backend_FastAPI/app/services/pipeline_service.py`
- `Backend_FastAPI/app/routers/admin/pipeline.py`

#### Tasks

- [ ] Audit all 8 functions (30m)
- [ ] Refactor 8 functions (3.5h)
- [ ] Update routers (30m)
- [ ] Testing (30m)

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #2.4)

#### Acceptance Criteria

- [ ] Zero `await db.commit()` in `pipeline_service.py`
- [ ] Tests pass

---

### Issue #6: [MEDIUM] Remove FastAPI Dependencies from Service Layer

**Labels:** `refactoring`, `architecture`, `P0`
**Milestone:** Week 1 - Emergency Fixes
**Effort:** 2 hours

#### Description

**Severity:** 🟠 MEDIUM - Architecture Violation

Services are importing FastAPI-specific classes, violating the layered architecture principle.

**Violations:**
1. `user_service.py:8` - `from fastapi import UploadFile`
2. `session_service.py:10` - `from fastapi import status`

**Impact:**
- Service layer coupled to FastAPI framework
- Difficult to test (must mock FastAPI classes)
- Violates Dependency Inversion Principle

**Files Affected:**
- `Backend_FastAPI/app/services/user_service.py`
- `Backend_FastAPI/app/services/session_service.py`
- `Backend_FastAPI/app/routers/admin/users.py`

#### Tasks

**Fix #1: UploadFile in user_service.py (1h)**
- [ ] Remove `from fastapi import UploadFile` from line 8
- [ ] Update `import_users_from_csv()` signature to accept `bytes` instead
- [ ] Add `filename` parameter for validation
- [ ] Update router to extract bytes from UploadFile
- [ ] Add file size validation in router (10MB limit)
- [ ] Add content type validation in router
- [ ] Update tests

**Fix #2: status in session_service.py (30m)**
- [ ] Check if `status` is actually used
- [ ] If YES: Replace with `http.HTTPStatus` or custom enum
- [ ] If NO: Remove import
- [ ] Update tests

**Verification (30m)**
- [ ] Run `grep "from fastapi import" app/services/*.py`
- [ ] Should only find imports in routers
- [ ] All service tests pass
- [ ] Integration tests pass

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #3)
- **Audit Report:** `COMPREHENSIVE_CODE_AUDIT_REPORT.md` (Section II.B)

#### Acceptance Criteria

- [ ] Zero FastAPI imports in service layer
- [ ] Services accept pure Python types (bytes, str, int, etc.)
- [ ] Routers handle HTTP-specific logic
- [ ] All tests pass

---

## 🔴 PRIORITY 1: CRITICAL (Week 2-3)

---

### Issue #7: [CRITICAL] Fix Transaction Management in Remaining 10 Services (20 violations)

**Labels:** `critical`, `refactoring`, `database`, `P1`
**Milestone:** Week 2-3 - Critical Fixes
**Effort:** 13 hours

#### Description

**Severity:** 🔴 CRITICAL - Data Consistency Risk

Complete the transaction management refactoring for the remaining 10 services.

**Services to fix:**
1. `notification_service.py` - 4 violations (2h)
2. `application_service.py` - 3 violations (1.5h)
3. `notification_preference_service.py` - 3 violations (1.5h)
4. `tuition_discount_service.py` - 3 violations (1.5h)
5. `lead_service.py` - 2 violations (1h)
6. `activity_service.py` - 1 violation (30m)
7. `notification_dispatcher.py` - 1 violation (30m)
8. `notification_workflow.py` - 1 violation (30m)
9. `officer_service.py` - 1 violation (30m)
10. `role_service.py` - 1 violation (30m)

**Total:** 20 violations

#### Tasks

- [ ] **notification_service.py** (2h)
  - [ ] Refactor 4 functions
  - [ ] Update routers
  - [ ] Test
- [ ] **application_service.py** (1.5h)
  - [ ] Refactor 3 functions
  - [ ] Update routers
  - [ ] Test
- [ ] **notification_preference_service.py** (1.5h)
  - [ ] Refactor 3 functions
  - [ ] Update routers
  - [ ] Test
- [ ] **tuition_discount_service.py** (1.5h)
  - [ ] Refactor 3 functions
  - [ ] Update routers
  - [ ] Test
- [ ] **lead_service.py** (1h)
  - [ ] Refactor 2 remaining functions
  - [ ] Update routers
  - [ ] Test
- [ ] **Single-violation services** (2.5h)
  - [ ] activity_service.py (30m)
  - [ ] notification_dispatcher.py (30m)
  - [ ] notification_workflow.py (30m)
  - [ ] officer_service.py (30m)
  - [ ] role_service.py (30m)
- [ ] **Final verification** (1h)
  - [ ] Run full test suite
  - [ ] Verify zero `await db.commit()` in ALL services
  - [ ] Load testing

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #4)
- **Audit Report:** `TRANSACTION_AUDIT_REPORT.md`

#### Acceptance Criteria

- [ ] Zero `await db.commit()` in ANY service file
- [ ] 100% transaction management compliance
- [ ] All 200+ tests pass
- [ ] No performance regression

---

### Issue #8: [HIGH] Implement Rate Limiting on All Endpoints (190 endpoints)

**Labels:** `security`, `enhancement`, `P1`
**Milestone:** Week 2-3 - Critical Fixes
**Effort:** 8 hours

#### Description

**Severity:** 🟠 HIGH - Security Risk (DoS)

Only 5 out of 195 endpoints (2.5%) have rate limiting. The remaining 190 endpoints are vulnerable to:
- **DoS attacks** (flood with requests)
- **Data scraping** (enumerate all leads/applications)
- **Brute force** (after bypassing auth rate limits)

**Current Coverage:**
- ✅ `POST /auth/login` - 5/minute
- ✅ `POST /auth/register` - 3/minute
- ✅ `POST /auth/forgot-password` - 3/hour
- ✅ `POST /auth/reset-password` - 10/hour
- ✅ `GET /notifications` - 100/hour

**Missing Coverage:**
- ❌ All `/admin/*` endpoints (110 endpoints)
- ❌ Lead management (17 endpoints)
- ❌ Applications (4 endpoints) ← Enables IDOR automation
- ❌ Organization APIs (12 endpoints)
- ❌ 57 other endpoints

**Files Affected:**
- Create: `Backend_FastAPI/app/core/rate_limits.py`
- Update: All 24 router files

#### Tasks

**Phase 1: Setup Rate Limit Infrastructure (30m)**
- [ ] Create `app/core/rate_limits.py`
- [ ] Define rate limit tiers:
  - [ ] `AUTH_LOGIN = "5/minute"`
  - [ ] `AUTH_REGISTER = "3/minute"`
  - [ ] `ADMIN_READ = "300/hour"`
  - [ ] `ADMIN_WRITE = "100/hour"`
  - [ ] `ADMIN_BULK = "10/hour"`
  - [ ] `DATA_READ = "1000/hour"`
  - [ ] `DATA_WRITE = "200/hour"`
  - [ ] `DATA_EXPORT = "20/hour"`
  - [ ] `REALTIME = "500/hour"`
- [ ] Initialize `slowapi` limiter
- [ ] Update `main.py` with rate limit middleware
- [ ] Add rate limit headers to responses

**Phase 2: Apply to Admin Routers (3h)**
- [ ] admin/users.py - 25 endpoints
- [ ] admin/config.py - 22 endpoints
- [ ] admin/organization.py - 16 endpoints
- [ ] admin/pipeline.py - 15 endpoints
- [ ] admin/roles.py - 20 endpoints
- [ ] admin/cache.py - 9 endpoints
- [ ] admin/system.py - 3 endpoints
- [ ] admin/tuition_discount.py - 10 endpoints

**Phase 3: Apply to Feature Routers (3h)**
- [ ] leads.py - 17 endpoints
- [ ] applications.py - 4 endpoints
- [ ] notifications.py - 4 endpoints
- [ ] organization.py - 12 endpoints
- [ ] pipeline.py - 3 endpoints
- [ ] officer.py - 2 endpoints
- [ ] sessions.py - 3 endpoints
- [ ] profile.py - 2 endpoints
- [ ] notification_rules.py - 7 endpoints
- [ ] notification_templates.py - 5 endpoints
- [ ] notification_preferences.py - 5 endpoints

**Phase 4: Testing (1h)**
- [ ] Test auth endpoints hit 429 after limit
- [ ] Test admin endpoints rate limits
- [ ] Test data endpoints rate limits
- [ ] Verify rate limit headers in responses
- [ ] Load testing to verify limits work under pressure

**Phase 5: Monitoring (30m)**
- [ ] Add rate limit metrics to monitoring
- [ ] Set up alerts for excessive 429 responses
- [ ] Document rate limits in API docs

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #5)
- **Audit Report:** `COMPREHENSIVE_CODE_AUDIT_REPORT.md` (Section II.G1)

#### Acceptance Criteria

- [ ] 100% endpoint coverage (195/195 endpoints)
- [ ] Rate limit tests pass
- [ ] 429 responses include retry-after header
- [ ] Rate limit headers present in all responses
- [ ] Documentation updated
- [ ] No performance regression

---

## 🟠 PRIORITY 2: HIGH (Week 4)

---

### Issue #9: [HIGH] Add Error Boundaries to Frontend Routes (10+ files)

**Labels:** `frontend`, `UX`, `enhancement`, `P2`
**Milestone:** Week 4 - UX Improvements
**Effort:** 4 hours

#### Description

**Severity:** 🟠 HIGH - Poor UX

The frontend has **ZERO** error boundary files. When errors occur, users see a white screen with no recovery option.

**Current State:**
- ❌ No `error.tsx` files in `/app` directory
- ❌ Errors bubble to root (white screen)
- ❌ No user-friendly error messages
- ❌ No error recovery mechanism

**Expected:**
- ✅ 10+ `error.tsx` files (one per major route)
- ✅ User-friendly error messages
- ✅ "Try again" / "Go to Dashboard" buttons
- ✅ Error logging to monitoring service

**Routes Needing Error Boundaries:**
1. `/app/error.tsx` (root)
2. `/app/(dashboard)/error.tsx`
3. `/app/(dashboard)/leads/error.tsx`
4. `/app/(dashboard)/leads/[id]/error.tsx`
5. `/app/(dashboard)/admin/error.tsx`
6. `/app/(dashboard)/admin/users/error.tsx`
7. `/app/(dashboard)/admin/organization/error.tsx`
8. `/app/(dashboard)/profile/error.tsx`
9. `/app/(dashboard)/notifications/error.tsx`
10. `/app/(dashboard)/settings/error.tsx`
11. `/app/(auth)/error.tsx`

#### Tasks

**Phase 1: Create Reusable Error Components (1h)**
- [ ] Design error UI with Shadcn components
- [ ] Create base `ErrorBoundary` component
- [ ] Add error logging integration (Sentry/etc)
- [ ] Create different error types (404, 403, 500, etc)

**Phase 2: Add Error Boundaries to Routes (2h)**
- [ ] Root error boundary (30m)
- [ ] Dashboard error boundary (20m)
- [ ] Leads error boundary (20m)
- [ ] Admin error boundary (20m)
- [ ] Auth error boundary (10m)
- [ ] Other routes (40m)

**Phase 3: Testing (30m)**
- [ ] Create `<ErrorTrigger />` test component
- [ ] Test error catching works
- [ ] Test "Try again" button works
- [ ] Test "Go to Dashboard" button works
- [ ] Test error logging works

**Phase 4: Documentation (30m)**
- [ ] Document error boundary pattern
- [ ] Add to frontend development guidelines
- [ ] Create PR checklist item for new routes

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #6)
- **Audit Report:** `COMPREHENSIVE_CODE_AUDIT_REPORT.md` (Section III.C1)

#### Acceptance Criteria

- [ ] 10+ error.tsx files added
- [ ] No white screens on errors
- [ ] Error recovery buttons work
- [ ] Errors logged to monitoring
- [ ] User testing confirms better UX

---

### Issue #10: [HIGH] Add Loading States to Frontend Routes (10+ files)

**Labels:** `frontend`, `UX`, `enhancement`, `P2`
**Milestone:** Week 4 - UX Improvements
**Effort:** 4 hours

#### Description

**Severity:** 🟠 HIGH - Poor UX

The frontend has **ZERO** loading state files. During data fetching, users see a white screen with no feedback.

**Current State:**
- ❌ No `loading.tsx` files in `/app` directory
- ❌ White screen during data fetch
- ❌ No loading skeletons
- ❌ Poor perceived performance

**Expected:**
- ✅ 10+ `loading.tsx` files (one per major route)
- ✅ Skeleton loading states
- ✅ Smooth transition to real content
- ✅ Better perceived performance

**Routes Needing Loading States:**
1. `/app/(dashboard)/loading.tsx`
2. `/app/(dashboard)/leads/loading.tsx`
3. `/app/(dashboard)/leads/[id]/loading.tsx`
4. `/app/(dashboard)/admin/loading.tsx`
5. `/app/(dashboard)/admin/users/loading.tsx`
6. `/app/(dashboard)/admin/organization/loading.tsx`
7. `/app/(dashboard)/profile/loading.tsx`
8. `/app/(dashboard)/notifications/loading.tsx`
9. `/app/(dashboard)/settings/loading.tsx`
10. `/app/(auth)/loading.tsx`

#### Tasks

**Phase 1: Create Reusable Skeleton Components (1h)**
- [ ] Create `DashboardSkeleton` component
- [ ] Create `TableSkeleton` component
- [ ] Create `FormSkeleton` component
- [ ] Create `LeadCardSkeleton` component
- [ ] Create `ChartSkeleton` component

**Phase 2: Add Loading States to Routes (2h)**
- [ ] Dashboard loading (20m)
- [ ] Leads loading (20m)
- [ ] Lead detail loading (20m)
- [ ] Admin loading (20m)
- [ ] Other routes (40m)

**Phase 3: Testing (30m)**
- [ ] Test with Chrome DevTools "Slow 3G"
- [ ] Verify skeletons appear
- [ ] Verify smooth transition to content
- [ ] Test with React DevTools Profiler
- [ ] Verify no layout shift (CLS)

**Phase 4: Documentation (30m)**
- [ ] Document skeleton patterns
- [ ] Add to frontend development guidelines
- [ ] Create PR checklist item

#### References

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #7)
- **Audit Report:** `COMPREHENSIVE_CODE_AUDIT_REPORT.md` (Section III.C2)

#### Acceptance Criteria

- [ ] 10+ loading.tsx files added
- [ ] No white screens during loading
- [ ] Skeletons match final content layout
- [ ] Smooth transitions (no jarring jumps)
- [ ] User testing confirms better UX

---

## 🟡 PRIORITY 3: MEDIUM (Month 2)

---

### Issue #11: [MEDIUM] Add Suspense Boundaries to Async Components (~20 components)

**Labels:** `frontend`, `performance`, `enhancement`, `P3`
**Milestone:** Month 2 - Final Polish
**Effort:** 2 hours

#### Description

**Severity:** 🟡 MEDIUM - Performance Optimization

Only 9 Suspense boundaries exist. Adding more will improve streaming and perceived performance.

**Current:** 9 instances in 2 files
**Expected:** 20-30 instances across major async components

#### Tasks

- [ ] Identify async components (1h)
- [ ] Wrap in Suspense with fallbacks (1h)
- [ ] Test streaming performance

#### Acceptance Criteria

- [ ] 20+ Suspense boundaries
- [ ] Improved streaming metrics

---

### Issue #12: [MEDIUM] Fix IDOR in Admin Config Unit Endpoints (Manager access)

**Labels:** `security`, `enhancement`, `P3`
**Milestone:** Month 2 - Final Polish
**Effort:** 2 hours

#### Description

**Severity:** 🟡 MEDIUM - Manager Access Control

Admin config endpoints don't verify that managers can only access their managed units.

**Endpoints:**
- `GET /admin/assignment-config/{unit_id}`
- `PUT /admin/assignment-config/{unit_id}`

**Current:** Relies only on Casbin admin-only check
**Expected:** Verify `unit_id` is in manager's managed units

#### Tasks

- [ ] Create `get_config_for_user()` dependency (1h)
- [ ] Update endpoints to use dependency (30m)
- [ ] Add tests (30m)

#### Acceptance Criteria

- [ ] Manager can only access managed unit configs
- [ ] Tests pass

---

# 📊 SUMMARY

**Total Issues:** 12
**Total Effort:** 72 hours (2 months for 1 developer)

**By Priority:**
- **P0 (Emergency):** 6 issues, 35 hours (Week 1)
- **P1 (Critical):** 2 issues, 21 hours (Week 2-3)
- **P2 (High):** 2 issues, 12 hours (Week 4)
- **P3 (Medium):** 2 issues, 4 hours (Month 2)

**By Category:**
- **Security:** 5 issues (IDOR, Rate Limiting)
- **Database:** 5 issues (Transaction Management)
- **Frontend UX:** 3 issues (Error/Loading/Suspense)
- **Architecture:** 1 issue (Service Layer Purity)

**Milestones:**
- Week 1: Emergency Fixes (72% of critical issues)
- Week 2-3: Critical Fixes (95% of critical issues)
- Week 4: UX Improvements (100% of high-priority)
- Month 2: Final Polish (100% compliance)

---

# 🚀 HOW TO USE

## Option 1: Manual Creation (Recommended for Review)

1. Go to https://github.com/favouritekid/QLTS/issues
2. Click "New Issue"
3. Copy-paste each issue above
4. Set labels, milestone, assignee
5. Click "Submit new issue"

## Option 2: Automated Creation (Fast)

Use the script in `.github/create_issues.sh`:

```bash
cd /home/user/QLTS
bash .github/create_issues.sh
```

## Option 3: GitHub CLI (If Available)

```bash
# Create all issues at once
gh issue create --title "[CRITICAL] Fix IDOR Vulnerabilities..." \
  --body-file .github/issues/issue-01.md \
  --label "security,critical,bug,P0" \
  --milestone "Week 1"

# Repeat for all 12 issues
```

---

**READY TO TRACK PROGRESS** ✅
