# PHASE 2A Design Document - Admin Router Split

**Phase:** PHASE 2A (Week 3-4)
**Duration:** 20 hours
**Scope:** Design + users.py + roles.py + testing
**Date:** 2025-11-17
**Status:** 🎯 DESIGN COMPLETE - READY FOR IMPLEMENTATION

---

## 1. EXECUTIVE SUMMARY

PHASE 2A focuses on splitting the two most critical and complex admin routers:
- **admin/users.py** (15 endpoints, ~450 LOC)
- **admin/roles.py** (22 endpoints, ~650 LOC)

These routers handle the core functionality of user management and permission/role management, making them the highest priority for extraction.

---

## 2. ROUTER SPECIFICATIONS

### 2.1 admin/users.py

**Purpose:** User lifecycle management, sync, export, and monitoring

**Endpoints:** 15 (24-37 from mapping)

**Categories:**
- User CRUD (7 endpoints): create, read, update, delete, list, details, password reset
- User Export (2 endpoints): Excel export, CSV streaming export
- User Bulk Operations (1 endpoint): bulk enable/disable/delete
- Casbin Sync (2 endpoints): sync status, trigger sync
- Lead Management (2 endpoints): bulk assign, import from CSV
- Analytics (1 endpoint): user statistics

**Estimated LOC:** ~450 lines

**Key Dependencies:**
```python
# Services (from PHASE 1)
from app.services import user_service      # For sync_users()
from app.services import lead_service      # For import_leads_from_csv()
from app.services import activity_service  # For activity logging

# Utilities
from app.security import get_password_hash  # For password management
from app.core import deps                   # For auth/permission deps
from app.database import get_db             # For DB session

# External
import pandas as pd                         # For Excel export
from fastapi import StreamingResponse       # For CSV streaming
```

**Complexity:** MEDIUM
- Standard CRUD operations
- CSV/Excel export logic
- Integration with PHASE 1 services (user_service, lead_service)

**File Structure:**
```python
# app/routers/admin/users.py

# ============================================================================
# IMPORTS
# ============================================================================

# ============================================================================
# ROUTER DEFINITION
# ============================================================================
router = APIRouter(prefix="/users", tags=["Admin - Users"])

# ============================================================================
# USER CRUD OPERATIONS
# ============================================================================
@router.post("")  # POST /api/admin/users
async def create_new_user(...): ...

@router.get("")  # GET /api/admin/users
async def get_all_users(...): ...

@router.get("/{user_id}")  # GET /api/admin/users/{user_id}
async def get_user_details(...): ...

@router.put("/{user_id}")  # PUT /api/admin/users/{user_id}
async def update_existing_user(...): ...

@router.delete("/{user_id}")  # DELETE /api/admin/users/{user_id}
async def delete_existing_user(...): ...

@router.get("/list")  # GET /api/admin/users/list
async def list_users(...): ...  # Note: May be duplicate of get_all_users

@router.post("/{user_id}/password")  # POST /api/admin/users/{user_id}/password
async def admin_set_user_password(...): ...

# ============================================================================
# USER EXPORT OPERATIONS
# ============================================================================
@router.get("/export")  # GET /api/admin/users/export
async def export_all_users(...): ...  # Excel export

@router.get("/export/csv")  # GET /api/admin/users/export/csv
async def stream_export_users_csv(...): ...  # CSV streaming

# ============================================================================
# USER BULK OPERATIONS
# ============================================================================
@router.post("/bulk")  # POST /api/admin/users/bulk
async def bulk_user_action(...): ...

# ============================================================================
# CASBIN SYNC OPERATIONS
# ============================================================================
@router.get("/sync/status")  # GET /api/admin/sync/status (moved to /users prefix)
async def get_sync_status(...): ...

@router.post("/sync")  # POST /api/admin/sync/users (changed path)
async def sync_users(...): ...  # Uses user_service.sync_users_to_casbin()

# ============================================================================
# LEAD MANAGEMENT OPERATIONS
# ============================================================================
@router.post("/leads/bulk-assign")  # POST /api/admin/leads/bulk-assign (moved)
async def bulk_assign_leads(...): ...

@router.post("/leads/import")  # POST /api/admin/leads/import (moved)
async def import_leads_from_file(...): ...  # Uses lead_service.import_leads_from_csv()

# ============================================================================
# ANALYTICS & MONITORING
# ============================================================================
@router.get("/statistics")  # GET /api/admin/statistics/users (changed path)
async def get_user_statistics(...): ...

@router.get("/activity-logs")  # GET /api/admin/activity-logs (moved)
async def get_activity_logs(...): ...
```

**Path Changes:**
```
BEFORE: /api/admin/sync/status
AFTER:  /api/admin/users/sync/status

BEFORE: /api/admin/sync/users
AFTER:  /api/admin/users/sync

BEFORE: /api/admin/leads/bulk-assign
AFTER:  /api/admin/users/leads/bulk-assign

BEFORE: /api/admin/leads/import
AFTER:  /api/admin/users/leads/import

BEFORE: /api/admin/statistics/users
AFTER:  /api/admin/users/statistics

BEFORE: /api/admin/activity-logs
AFTER:  /api/admin/users/activity-logs
```

**⚠️ BREAKING CHANGES:** API paths will change! Frontend needs to update.

---

### 2.2 admin/roles.py

**Purpose:** Casbin policy and role management

**Endpoints:** 22 (1-22 from mapping)

**Categories:**
- Policy CRUD (3 endpoints): get, add, delete policies
- Role Assignment (5 endpoints): assign, revoke, get user roles, get role users, bulk revoke
- Grouping Policies (2 endpoints): add, delete role inheritance
- Role Management (3 endpoints): get all roles, delete role, user roles query
- Templates (2 endpoints): get templates, apply template
- Batch Operations (1 endpoint): batch add policies
- Validation (1 endpoint): validate policy
- Statistics & Analytics (2 endpoints): statistics, suggestions
- Advanced Features (3 endpoints): simulate, explain, who can access
- Feature Flags (2 endpoints): get features, toggle feature

**Estimated LOC:** ~650 lines

**Key Dependencies:**
```python
# Services (from PHASE 1)
from app.services import role_service      # For assign_role(), revoke_role()
from app.services import activity_service  # For activity logging

# Core
from app.core import deps                  # For get_enforcer(), check_permission()
from app.database import get_db            # For DB session
import casbin                              # For Casbin enforcer type hints

# Schemas
from app.schemas.permissions import (
    PolicyCreate,
    RoleAssignment,
    GroupingPolicyCreate,
    # ... other schemas
)
```

**Complexity:** HIGH ⚠️
- Complex Casbin integration
- Policy validation logic
- Atomic operations (delete role with all policies)
- Template system
- Permission simulation

**File Structure:**
```python
# app/routers/admin/roles.py

# ============================================================================
# IMPORTS
# ============================================================================

# ============================================================================
# ROUTER DEFINITION
# ============================================================================
router = APIRouter(prefix="/roles", tags=["Admin - Roles & Permissions"])

# ============================================================================
# POLICY CRUD OPERATIONS
# ============================================================================
@router.get("/policies")  # GET /api/admin/roles/policies
async def get_all_policies(...): ...

@router.post("/policies")  # POST /api/admin/roles/policies
async def add_new_policy(...): ...

@router.delete("/policies")  # DELETE /api/admin/roles/policies
async def delete_policy(...): ...

# ============================================================================
# ROLE ASSIGNMENT OPERATIONS (Uses role_service from PHASE 1!)
# ============================================================================
@router.post("/assign")  # POST /api/admin/roles/assign
async def assign_role_to_user(...):
    # Delegates to role_service.assign_role()
    ...

@router.delete("/revoke")  # DELETE /api/admin/roles/revoke
async def remove_role_from_user(...):
    # Delegates to role_service.revoke_role()
    ...

@router.get("/users/{user_id}/roles")  # GET /api/admin/roles/users/{user_id}/roles
async def get_user_roles(...): ...

@router.get("/{role_name}/users")  # GET /api/admin/roles/{role_name}/users
async def get_role_users(...): ...

@router.delete("/{role_name}/users")  # DELETE /api/admin/roles/{role_name}/users
async def remove_role_from_users(...): ...

# ============================================================================
# GROUPING POLICY OPERATIONS
# ============================================================================
@router.post("/grouping-policies")  # POST /api/admin/roles/grouping-policies
async def add_grouping_policy(...): ...

@router.delete("/grouping-policies")  # DELETE /api/admin/roles/grouping-policies
async def delete_grouping_policy(...): ...

# ============================================================================
# ROLE MANAGEMENT OPERATIONS
# ============================================================================
@router.get("")  # GET /api/admin/roles
async def get_all_roles_with_info(...): ...

@router.delete("/{role_name}")  # DELETE /api/admin/roles/{role_name}
async def delete_role_atomic(...): ...  # Atomic: delete role + all policies

# ============================================================================
# POLICY TEMPLATES
# ============================================================================
@router.get("/templates")  # GET /api/admin/roles/templates
async def get_policy_templates(...): ...

@router.post("/templates/apply")  # POST /api/admin/roles/templates/apply
async def apply_template_to_role(...): ...

# ============================================================================
# BATCH OPERATIONS
# ============================================================================
@router.post("/policies/batch")  # POST /api/admin/roles/policies/batch
async def add_policies_batch(...): ...

# ============================================================================
# VALIDATION & SIMULATION
# ============================================================================
@router.post("/policies/validate")  # POST /api/admin/roles/policies/validate
async def validate_policy_operation(...): ...

@router.post("/permissions/simulate")  # POST /api/admin/roles/permissions/simulate
async def simulate_permission(...): ...

# ============================================================================
# ANALYTICS & INSIGHTS
# ============================================================================
@router.get("/policies/statistics")  # GET /api/admin/roles/policies/statistics
async def get_policy_statistics(...): ...

@router.get("/policies/suggestions")  # GET /api/admin/roles/policies/suggestions
async def get_policy_suggestions(...): ...

@router.get("/{role_name}/permissions/explain")  # GET /api/admin/roles/{role_name}/permissions/explain
async def explain_role_permissions(...): ...

@router.post("/permissions/who-can-access")  # POST /api/admin/roles/permissions/who-can-access
async def who_can_access_resource(...): ...

# ============================================================================
# FEATURE FLAGS
# ============================================================================
@router.get("/{role_name}/features")  # GET /api/admin/roles/{role_name}/features
async def get_role_features(...): ...

@router.post("/{role_name}/features/{feature_name}/toggle")  # POST
async def toggle_role_feature(...): ...
```

**Path Changes:**
```
BEFORE: /api/admin/policies
AFTER:  /api/admin/roles/policies

BEFORE: /api/admin/roles/assign
AFTER:  /api/admin/roles/assign (no change)

BEFORE: /api/admin/grouping-policies
AFTER:  /api/admin/roles/grouping-policies

BEFORE: /api/admin/roles
AFTER:  /api/admin/roles (no change)

BEFORE: /api/admin/policy-templates
AFTER:  /api/admin/roles/templates

BEFORE: /api/admin/policies/batch
AFTER:  /api/admin/roles/policies/batch

BEFORE: /api/admin/policies/validate
AFTER:  /api/admin/roles/policies/validate

BEFORE: /api/admin/permissions/simulate
AFTER:  /api/admin/roles/permissions/simulate

... (and so on)
```

**⚠️ BREAKING CHANGES:** Many API paths will change! Frontend needs major update.

---

## 3. SHARED DEPENDENCIES

### 3.1 Common Imports for All Routers

```python
# FastAPI
from fastapi import APIRouter, Depends, HTTPException, status, Request

# SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession

# Database
from app.database import get_db

# Dependencies
from app.core import deps

# Services
from app.services import activity_service

# Exceptions
from app.utils.exceptions import (
    ResourceNotFoundError,
    UserNotFoundError,
    PermissionDeniedError,
    DuplicateResourceError,
    ValidationError,
)

# Logging
import structlog
log = structlog.get_logger(__name__)
```

### 3.2 Router-Specific Dependencies

**users.py:**
```python
from app.services import user_service, lead_service
from app.security import get_password_hash
import pandas as pd
from fastapi import UploadFile, File
from fastapi.responses import StreamingResponse
```

**roles.py:**
```python
from app.services import role_service
from app.schemas.permissions import PolicyCreate, RoleAssignment, GroupingPolicyCreate
import casbin
from typing import List, Optional
```

### 3.3 Helper Functions

**Both routers need `log_admin_activity()` helper:**

```python
# app/routers/admin/users.py
# app/routers/admin/roles.py

async def log_admin_activity(
    db: AsyncSession,
    request: Request,
    action: str,
    resource_type: str,
    actor_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    resource_id: Optional[int] = None,
    description: Optional[str] = None,
    changes: Optional[dict] = None,
) -> models.UserActivityLog:
    """
    Helper function to log admin activities with IP/UA extracted from request.

    This is duplicated in both routers to maintain independence.
    Protocol-independent service (activity_service) handles actual logging.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    return await activity_service.log_activity(
        db=db,
        action=action,
        resource_type=resource_type,
        actor_id=actor_id,
        target_user_id=target_user_id,
        resource_id=resource_id,
        description=description,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
    )
```

**Decision:** Duplicate helper function in both routers (acceptable duplication for independence)

**Alternative:** Move to `app/routers/admin/utils.py` (adds coupling, not recommended)

---

## 4. INTEGRATION STRATEGY

### 4.1 Router Aggregation (admin/__init__.py)

**After PHASE 2A completion:**

```python
# app/routers/admin/__init__.py

from fastapi import APIRouter
from . import users, roles

# Create main admin router
router = APIRouter(prefix="/admin", tags=["Admin"])

# Include sub-routers
router.include_router(users.router)   # /api/admin/users/*
router.include_router(roles.router)   # /api/admin/roles/*

# After PHASE 2B, will add:
# from . import organization, config
# router.include_router(organization.router)
# router.include_router(config.router)

# After PHASE 2C, will add:
# from . import pipeline
# router.include_router(pipeline.router)
```

### 4.2 Main App Integration (main.py)

**Current:**
```python
# app/main.py
from app.routers import admin

app.include_router(admin.router, prefix="/api")
```

**After PHASE 2A:**
```python
# app/main.py
# Import old admin router for backwards compatibility during transition
from app.routers import admin as old_admin  # Keep temporarily

# Import new split routers
from app.routers.admin import router as admin_router

# PHASE 2A: Use both routers during transition
app.include_router(old_admin.router, prefix="/api", tags=["Admin (Legacy)"])
app.include_router(admin_router, prefix="/api")

# After testing complete, remove old_admin
```

**After all endpoints verified:**
```python
# app/main.py
from app.routers.admin import router as admin_router

app.include_router(admin_router, prefix="/api")
```

### 4.3 Gradual Migration Strategy

**Step 1:** Create new routers (users.py, roles.py) with new paths
**Step 2:** Keep old admin.py temporarily
**Step 3:** Test new routers work correctly
**Step 4:** Update frontend to use new paths
**Step 5:** Verify no traffic to old paths (check logs)
**Step 6:** Remove endpoints from old admin.py
**Step 7:** After PHASE 2C complete, delete admin.py entirely

**Benefits:**
- ✅ Zero downtime
- ✅ Gradual migration
- ✅ Can rollback easily
- ✅ A/B testing possible

---

## 5. TESTING STRATEGY

### 5.1 Unit Tests

**Create test files:**
```
tests/routers/admin/
├── __init__.py
├── test_users.py           # Test all 15 user endpoints
└── test_roles.py           # Test all 22 role endpoints
```

**Test Coverage:**
- All endpoints return correct status codes
- Authentication/authorization works
- Request/response schemas validated
- Error handling (404, 403, 400, 500)
- Edge cases (empty lists, missing data, etc.)

### 5.2 Integration Tests

**Test scenarios:**
```python
# tests/integration/test_admin_phase2a.py

async def test_create_user_and_assign_role():
    """Test creating user then assigning role (crosses routers)"""
    # 1. Create user via users.py router
    # 2. Assign role via roles.py router
    # 3. Verify user has role
    # 4. Cleanup

async def test_role_deletion_removes_from_users():
    """Test atomic role deletion"""
    # 1. Create user and assign role
    # 2. Delete role atomically
    # 3. Verify role removed from user
    # 4. Verify all policies deleted
```

### 5.3 Endpoint Verification Checklist

**For each endpoint:**
```
[ ] Endpoint accessible at new path
[ ] Returns correct status code (200, 201, 204)
[ ] Request validation works (422 for invalid data)
[ ] Response schema matches expected format
[ ] Authentication required (401 if no token)
[ ] Permission check works (403 if insufficient permissions)
[ ] Database changes persisted correctly
[ ] Activity log created
[ ] Error handling works (try to break it!)
```

**Total tests needed:**
- users.py: ~60 test cases (4 per endpoint average)
- roles.py: ~88 test cases (4 per endpoint average)
- integration: ~10 test scenarios
- **Total: ~158 test cases**

### 5.4 Performance Testing

**Benchmark endpoints:**
```bash
# Before split (baseline)
ab -n 1000 -c 10 http://localhost:8000/api/admin/users

# After split (compare)
ab -n 1000 -c 10 http://localhost:8000/api/admin/users
```

**Expected:** No significant performance degradation (< 5% slower acceptable)

---

## 6. ROLLBACK PLAN

### 6.1 Backup Strategy

```bash
# Before starting PHASE 2A
git checkout -b backup/admin-pre-phase2a
git push -u origin backup/admin-pre-phase2a

# Keep old admin.py
cp app/routers/admin.py app/routers/admin.py.backup
```

### 6.2 Rollback Procedure

**If issues found during testing:**

```bash
# 1. Stop using new routers in main.py
# Comment out: from app.routers.admin import router as admin_router
# Keep: from app.routers import admin

# 2. Remove new router files (optional - can keep for later)
# rm -rf app/routers/admin/

# 3. Revert to backup branch if needed
git checkout backup/admin-pre-phase2a

# 4. Investigate issues, fix, retry
```

### 6.3 Rollback Criteria

**Rollback if:**
- ❌ > 10% of tests fail
- ❌ Critical endpoint not working
- ❌ Performance degradation > 20%
- ❌ Data corruption detected
- ❌ Cannot fix issues within 4 hours

**Continue if:**
- ✅ < 5% tests fail with known issues
- ✅ No data corruption
- ✅ Performance acceptable
- ✅ Issues fixable within timeline

---

## 7. PHASE 2A CHECKLIST

### 7.1 Design Phase (3h) ✅

```
✅ Create endpoint mapping CSV (85 endpoints)
✅ Identify shared dependencies
✅ Design router structure (users.py, roles.py)
✅ Plan __init__.py aggregation
✅ Create migration checklist
✅ Write design document (THIS DOCUMENT)
```

### 7.2 Implementation Phase

#### users.py (6h)
```
[ ] Create app/routers/admin/ directory
[ ] Create app/routers/admin/__init__.py
[ ] Create app/routers/admin/users.py with imports
[ ] Extract 15 user endpoints from admin.py
    [ ] create_new_user
    [ ] get_all_users
    [ ] export_all_users
    [ ] stream_export_users_csv
    [ ] get_user_details
    [ ] update_existing_user
    [ ] delete_existing_user
    [ ] admin_set_user_password
    [ ] bulk_user_action
    [ ] get_sync_status
    [ ] sync_users (uses user_service from PHASE 1)
    [ ] list_users
    [ ] bulk_assign_leads
    [ ] import_leads_from_file (uses lead_service from PHASE 1)
    [ ] get_user_statistics
    [ ] get_activity_logs
[ ] Add log_admin_activity helper
[ ] Run linter (black, isort, flake8)
[ ] Test manually in Swagger
[ ] Create tests/routers/admin/test_users.py
[ ] Write 60 test cases
[ ] All tests pass
```

#### roles.py (8h)
```
[ ] Create app/routers/admin/roles.py with imports
[ ] Extract 22 role/policy endpoints from admin.py
    [ ] get_all_policies
    [ ] add_new_policy
    [ ] delete_policy
    [ ] assign_role_to_user (uses role_service from PHASE 1)
    [ ] remove_role_from_user (uses role_service from PHASE 1)
    [ ] get_user_roles
    [ ] get_role_users
    [ ] remove_role_from_users
    [ ] add_grouping_policy
    [ ] delete_grouping_policy
    [ ] get_all_roles_with_info
    [ ] delete_role_atomic
    [ ] get_policy_templates
    [ ] add_policies_batch
    [ ] validate_policy_operation
    [ ] apply_template_to_role
    [ ] get_policy_statistics
    [ ] get_policy_suggestions
    [ ] simulate_permission
    [ ] get_role_features
    [ ] toggle_role_feature
    [ ] explain_role_permissions
    [ ] who_can_access_resource
[ ] Add log_admin_activity helper
[ ] Ensure Casbin enforcer dependency injection works
[ ] Run linter (black, isort, flake8)
[ ] Test manually in Swagger
[ ] Create tests/routers/admin/test_roles.py
[ ] Write 88 test cases
[ ] All tests pass
```

### 7.3 Integration Phase (3h)
```
[ ] Update admin/__init__.py to include both routers
[ ] Update main.py to use new admin router
[ ] Keep old admin.py temporarily for comparison
[ ] Test all endpoints accessible
[ ] Run full test suite
[ ] Check Swagger docs generated correctly
[ ] Performance benchmark (compare to baseline)
[ ] Create tests/integration/test_admin_phase2a.py
[ ] Write 10 integration test scenarios
[ ] All integration tests pass
```

### 7.4 Verification Phase (1h)
```
[ ] Verify all 37 PHASE 2A endpoints work
[ ] Check authentication/authorization
[ ] Verify activity logging works
[ ] Test error handling (404, 403, 400, 500)
[ ] Check database transactions
[ ] Verify Casbin integration (roles.py)
[ ] Test PHASE 1 service integration (user_service, role_service, lead_service)
[ ] Load testing (optional)
[ ] Documentation updated
[ ] Frontend notified of path changes
```

---

## 8. SUCCESS CRITERIA

### 8.1 Functional Requirements

**MUST HAVE:**
- ✅ All 15 user endpoints work correctly
- ✅ All 22 role endpoints work correctly
- ✅ No regression in existing functionality
- ✅ All tests pass (>95% pass rate)
- ✅ Authentication/authorization enforced
- ✅ Activity logging works
- ✅ Casbin integration intact

**SHOULD HAVE:**
- ✅ Performance within 5% of baseline
- ✅ Code coverage > 80%
- ✅ Swagger docs correct
- ✅ Error messages helpful

**NICE TO HAVE:**
- Frontend updated to use new paths
- Load testing completed
- Performance optimizations

### 8.2 Quality Requirements

**Code Quality:**
- ✅ All code passes linter (black, isort, flake8)
- ✅ No security vulnerabilities
- ✅ Clear docstrings on all endpoints
- ✅ Type hints used

**Test Quality:**
- ✅ > 95% test pass rate
- ✅ Edge cases covered
- ✅ Error cases tested
- ✅ Integration scenarios validated

### 8.3 Documentation Requirements

- ✅ This design document complete
- ✅ Migration checklist created
- ✅ Endpoint mapping documented
- ✅ Path changes documented
- ✅ Breaking changes noted

---

## 9. RISK MITIGATION

### 9.1 Identified Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Casbin enforcer injection fails | LOW | HIGH | Test early, use existing patterns from admin.py |
| PHASE 1 service integration issues | LOW | MEDIUM | Services already tested in PHASE 1 |
| Path changes break frontend | HIGH | HIGH | Document changes, keep old paths temporarily |
| Missing endpoints after migration | LOW | HIGH | Use endpoint checklist, automated verification |
| Performance degradation | LOW | MEDIUM | Benchmark before/after |

### 9.2 Mitigation Strategies

**1. Early Testing:**
- Test Casbin integration immediately after creating roles.py
- Test PHASE 1 service calls (user_service, role_service, lead_service)

**2. Gradual Migration:**
- Keep old admin.py during transition
- Both routers available simultaneously
- Can rollback easily

**3. Comprehensive Testing:**
- 158 test cases planned
- Integration tests for cross-router scenarios
- Manual testing in Swagger

**4. Documentation:**
- Path changes documented
- Frontend team notified
- Migration guide created

---

## 10. NEXT STEPS

### After PHASE 2A Completion:

**Immediate (Week 5-6):**
```
PHASE 2B: organization.py + config.py
- 12 organization endpoints
- 20 config endpoints
- Estimated: 13 hours
```

**Future (Week 7):**
```
PHASE 2C: pipeline.py + frontend + polish
- 14 pipeline endpoints
- Frontend hooks audit
- Final testing
- Estimated: 10 hours
```

**Final:**
```
- Delete old admin.py
- Update all documentation
- Frontend fully migrated
- PHASE 2 COMPLETE
```

---

## 11. APPENDICES

### Appendix A: File Locations

```
Backend_FastAPI/
├── app/
│   └── routers/
│       ├── admin.py                          # OLD - keep temporarily
│       └── admin/                            # NEW
│           ├── __init__.py                   # Router aggregator
│           ├── users.py                      # 15 endpoints (~450 LOC)
│           └── roles.py                      # 22 endpoints (~650 LOC)
├── tests/
│   ├── routers/
│   │   └── admin/
│   │       ├── __init__.py
│   │       ├── test_users.py                 # ~60 test cases
│   │       └── test_roles.py                 # ~88 test cases
│   └── integration/
│       └── test_admin_phase2a.py             # ~10 integration tests
└── docs/
    ├── PHASE2A_DESIGN_DOCUMENT.md            # THIS FILE
    ├── PHASE2A_ENDPOINT_MAPPING.csv          # Endpoint inventory
    └── PHASE2A_MIGRATION_CHECKLIST.md        # Step-by-step checklist
```

### Appendix B: Estimated Timeline

```
Day 1 (3h):    Design phase (complete)
Day 2-3 (6h):  Extract users.py + tests
Day 4-6 (8h):  Extract roles.py + tests
Day 7 (3h):    Integration + testing
Total: 20 hours across 7 days
```

### Appendix C: Import Examples

**users.py imports:**
```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import pandas as pd
import structlog

from app.database import get_db
from app.core import deps
from app.services import user_service, lead_service, activity_service
from app.security import get_password_hash
from app.utils.exceptions import UserNotFoundError, PermissionDeniedError
```

**roles.py imports:**
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import casbin
import structlog

from app.database import get_db
from app.core import deps
from app.services import role_service, activity_service
from app.schemas.permissions import (
    PolicyCreate,
    RoleAssignment,
    GroupingPolicyCreate,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    PermissionDeniedError,
    DuplicateResourceError,
)
```

---

**Document Status:** ✅ COMPLETE
**Ready for Implementation:** ✅ YES
**Review Required:** Team should review path changes (breaking changes!)
**Estimated Completion:** Day 7 from start

---

**END OF DESIGN DOCUMENT**
