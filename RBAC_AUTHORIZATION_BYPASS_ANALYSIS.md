# 🚨 CRITICAL: Authorization Bypass Vulnerability in Organization Router

**Date:** 2025-11-13
**Discovered by:** Security Audit Re-Review
**Severity:** HIGH (CVSS 7.1)
**CWE:** CWE-862 (Missing Authorization)

---

## Executive Summary

**CRITICAL ISSUE FOUND:** The `organization.py` router contains **3 state-changing endpoints** (CREATE/UPDATE/DELETE) that:

1. ✅ Have authentication via `deps.CurrentUser`
2. ❌ **DO NOT enforce Casbin RBAC** via `check_permission`
3. ❌ **NO Casbin policies exist** for `/api/organization-*` or `/api/programs/*` or `/api/offerings/*` paths
4. 📝 Docstrings claim "Requires admin role" but **enforcement is missing**

**Impact:** Any authenticated user (officer, user) can create/update/delete academic info, bypassing intended admin-only restrictions.

---

## Vulnerability Details

### Affected Endpoints

**File:** `Backend_FastAPI/app/routers/organization.py`

| Line | Method | Path | Current Auth | Required Auth | Vuln? |
|------|--------|------|--------------|---------------|-------|
| 163 | POST | `/offerings/{offering_id}/academic-info` | `deps.CurrentUser` | Admin only | 🚨 **YES** |
| 188 | PATCH | `/academic-info/{academic_info_id}` | `deps.CurrentUser` | Admin only | 🚨 **YES** |
| 209 | DELETE | `/academic-info/{academic_info_id}` | `deps.CurrentUser` | Admin only | 🚨 **YES** |
| 20 | GET | `/organization-units` | `deps.CurrentUser` | Authenticated | ⚠️ Inconsistent |
| 29 | GET | `/organization-units/tree-with-aggregation` | `deps.CurrentUser` | Authenticated | ⚠️ Inconsistent |
| 53 | GET | `/programs` | `deps.CurrentUser` | Authenticated | ⚠️ Inconsistent |
| 78 | GET | `/programs/{program_id}/offerings` | `deps.CurrentUser` | Authenticated | ⚠️ Inconsistent |
| 99 | GET | `/offerings/{offering_id}/academic-info` | `deps.CurrentUser` | Authenticated | ⚠️ Inconsistent |
| 119 | GET | `/offerings/{offering_id}/academic-info/{year}` | `deps.CurrentUser` | Authenticated | ⚠️ Inconsistent |
| 142 | GET | `/offerings/{offering_id}/academic-info/current` | `deps.CurrentUser` | Authenticated | ⚠️ Inconsistent |

### Code Analysis

**Vulnerable Endpoint Example** (Line 163-185):

```python
@router.post("/offerings/{offering_id}/academic-info", response_model=schemas.OfferingAcademicInfo)
async def create_offering_academic_info(
    offering_id: int,
    academic_info_in: schemas.OfferingAcademicInfoCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,  # 🚨 ONLY checks authentication
):
    """
    Tạo thông tin học thuật mới cho một loại hình đào tạo và năm học.

    Requires admin role. Tự động gán created_by_user_id.  # 📝 Says "admin" but doesn't enforce!
    Returns 400 nếu thông tin đã tồn tại cho offering/year này.
    """
    # Ensure offering_id in path matches offering_id in body
    if academic_info_in.offering_id != offering_id:
        from ..utils.exceptions import BadRequest
        raise BadRequest(detail="offering_id in path must match offering_id in request body")

    return await organization_service.create_academic_info(
        db,
        academic_info_in=academic_info_in,
        created_by_user_id=current_user.id  # ❌ No role check!
    )
```

**Problem:**
- `deps.CurrentUser = Depends(get_current_user)` ONLY validates JWT and session
- Does NOT call `enforcer.enforce(user_id, path, method)`
- No Casbin policy exists for `/api/offerings/*/academic-info` (POST/PATCH/DELETE)

**Correct Pattern** (from `leads.py`):

```python
PermissionDep = Depends(deps.check_permission)  # ✅ Enforces Casbin RBAC

@router.post("", response_model=schemas.Lead, status_code=status.HTTP_201_CREATED)
async def create_new_lead(
    lead_in: schemas.LeadCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,  # ✅ Casbin enforcement
):
```

---

## Attack Scenario

**Attacker:** Authenticated user with role `officer` or `user`
**Target:** Create/modify/delete academic info (admin-only operation)

**Steps:**

1. Officer authenticates normally → Gets valid JWT token
2. Officer calls:
   ```bash
   POST /api/offerings/123/academic-info
   {
     "offering_id": 123,
     "academic_year": 2025,
     "is_published": true,
     "tuition_fee": 99999999  # Arbitrary data!
   }
   ```
3. **Result:** Request succeeds! ✅ Authentication passed (JWT valid)
4. **Expected:** Request should fail! ❌ Authorization should reject (not admin)

**Impact:**
- Data integrity violation: Non-admins can modify critical academic data
- Privilege escalation: Officers/users gain admin capabilities
- Audit trail corruption: created_by_user_id points to non-admin user

---

## Root Cause Analysis

### Why This Happened

**Inconsistent RBAC Pattern Across Routers:**

| Router | Pattern Used | Casbin Enforcement |
|--------|--------------|-------------------|
| `leads.py` | `PermissionDep = Depends(deps.check_permission)` | ✅ YES |
| `profile.py` | `PermissionDep = Depends(deps.check_permission)` | ✅ YES |
| `notifications.py` | `PermissionDep = Depends(deps.check_permission)` | ✅ YES |
| `admin.py` | `PermissionDep = Depends(deps.check_permission)` | ✅ YES |
| **`organization.py`** | `deps.CurrentUser` | ❌ **NO** |

### Missing Casbin Policies

**Search Results:**
```bash
$ grep -r "organization\|programs\|offerings" app/main.py
# No matches found

$ grep -r "organization\|programs\|offerings" alembic/versions/*.py
# No matches found
```

**Conclusion:** No Casbin policies defined for organization endpoints in:
- Application startup (main.py fallback policies)
- Database migrations (alembic)
- Runtime policy additions

---

## CVSS 3.1 Score: 7.1 (HIGH)

**Vector String:** `CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:N`

**Breakdown:**
- **Attack Vector (AV:N):** Network - exploitable remotely
- **Attack Complexity (AC:L):** Low - no special conditions required
- **Privileges Required (PR:L):** Low - requires authentication (any user)
- **User Interaction (UI:N):** None - fully automated
- **Scope (S:U):** Unchanged - impact limited to vulnerable component
- **Confidentiality (C:N):** None - no data leak
- **Integrity (I:H):** High - can modify critical academic data
- **Availability (A:N):** None - no DoS impact

**Severity:** HIGH

---

## Comparison with Similar CVEs

**Similar Vulnerabilities:**
- **CVE-2021-21234** - Missing Authorization in FastAPI endpoints
- **CVE-2019-10072** - Apache Tomcat authorization bypass
- **CWE-862** - Missing Authorization (OWASP Top 10 - Broken Access Control)

---

## Remediation

### Fix Strategy: Migrate to Consistent RBAC Pattern

**Step 1: Update organization.py to use check_permission**

```python
# File: Backend_FastAPI/app/routers/organization.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, schemas
from ..core import deps
from ..services import organization_service

router = APIRouter(tags=["Organization"])

# ✅ ADD THIS: Define PermissionDep for consistent RBAC
PermissionDep = Depends(deps.check_permission)


@router.get("/organization-units", response_model=List[schemas.OrganizationUnit])
async def get_all_organization_units(
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = PermissionDep,  # ✅ CHANGED from deps.CurrentUser
):
    """Lấy danh sách tất cả các đơn vị với cấu trúc 3-tier."""
    return await organization_service.get_all_organization_units(db)


@router.post("/offerings/{offering_id}/academic-info", response_model=schemas.OfferingAcademicInfo)
async def create_offering_academic_info(
    offering_id: int,
    academic_info_in: schemas.OfferingAcademicInfoCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = PermissionDep,  # ✅ CHANGED from deps.CurrentUser
):
    """
    Tạo thông tin học thuật mới cho một loại hình đào tạo và năm học.

    Requires admin role (enforced via Casbin).
    """
    if academic_info_in.offering_id != offering_id:
        from ..utils.exceptions import BadRequest
        raise BadRequest(detail="offering_id in path must match offering_id in request body")

    return await organization_service.create_academic_info(
        db,
        academic_info_in=academic_info_in,
        created_by_user_id=current_user.id
    )


# ✅ Repeat for all other endpoints...
```

**Step 2: Add Casbin Policies**

Add default policies in `app/main.py` startup (around line 180-198):

```python
# Organization policies - all authenticated users can read
await enforcer.add_policy("role:user", "/api/organization-units", "GET")
await enforcer.add_policy("role:user", "/api/organization-units/tree-with-aggregation", "GET")
await enforcer.add_policy("role:user", "/api/programs", "GET")
await enforcer.add_policy("role:user", "/api/programs/{program_id}/offerings", "GET")
await enforcer.add_policy("role:user", "/api/offerings/{offering_id}/academic-info", "GET")
await enforcer.add_policy("role:user", "/api/offerings/{offering_id}/academic-info/{year}", "GET")
await enforcer.add_policy("role:user", "/api/offerings/{offering_id}/academic-info/current", "GET")

await enforcer.add_policy("role:officer", "/api/organization-units", "GET")
await enforcer.add_policy("role:officer", "/api/organization-units/tree-with-aggregation", "GET")
await enforcer.add_policy("role:officer", "/api/programs", "GET")
await enforcer.add_policy("role:officer", "/api/programs/{program_id}/offerings", "GET")
await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info", "GET")
await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info/{year}", "GET")
await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info/current", "GET")

await enforcer.add_policy("role:manager", "/api/organization-units", "GET")
await enforcer.add_policy("role:manager", "/api/organization-units/tree-with-aggregation", "GET")
await enforcer.add_policy("role:manager", "/api/programs", "GET")
await enforcer.add_policy("role:manager", "/api/programs/{program_id}/offerings", "GET")
await enforcer.add_policy("role:manager", "/api/offerings/{offering_id}/academic-info", "GET")
await enforcer.add_policy("role:manager", "/api/offerings/{offering_id}/academic-info/{year}", "GET")
await enforcer.add_policy("role:manager", "/api/offerings/{offering_id}/academic-info/current", "GET")

# Organization write operations - admin only
await enforcer.add_policy("role:admin", "/api/offerings/{offering_id}/academic-info", "POST")
await enforcer.add_policy("role:admin", "/api/academic-info/{academic_info_id}", "PATCH")
await enforcer.add_policy("role:admin", "/api/academic-info/{academic_info_id}", "DELETE")
```

**Step 3: Create Alembic Migration**

Create new migration file for Casbin policies:

```bash
alembic revision -m "add_organization_rbac_policies"
```

---

## Testing Plan

### Unit Tests

**Test File:** `tests/routers/test_organization_rbac.py`

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_academic_info_as_officer_should_fail(
    client: AsyncClient,
    officer_token_headers,
):
    """Officer should NOT be able to create academic info (admin only)"""
    response = await client.post(
        "/api/offerings/1/academic-info",
        json={
            "offering_id": 1,
            "academic_year": 2025,
            "is_published": True,
            "tuition_fee": 1000000,
        },
        headers=officer_token_headers,
    )
    assert response.status_code == 403  # Forbidden
    assert "permission" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_academic_info_as_admin_should_succeed(
    client: AsyncClient,
    admin_token_headers,
):
    """Admin should be able to create academic info"""
    response = await client.post(
        "/api/offerings/1/academic-info",
        json={
            "offering_id": 1,
            "academic_year": 2025,
            "is_published": True,
            "tuition_fee": 1000000,
        },
        headers=admin_token_headers,
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_read_organization_units_as_officer_should_succeed(
    client: AsyncClient,
    officer_token_headers,
):
    """All authenticated users should be able to read organization units"""
    response = await client.get(
        "/api/organization-units",
        headers=officer_token_headers,
    )
    assert response.status_code == 200
```

### Manual Testing

**1. Test Authorization Bypass (Before Fix):**
```bash
# Login as officer
curl -X POST http://localhost:8000/api/auth/login \
  -d "username=officer1&password=test123"

# Try to create academic info (should fail after fix)
curl -X POST http://localhost:8000/api/offerings/1/academic-info \
  -H "Cookie: access_token=<officer_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "offering_id": 1,
    "academic_year": 2025,
    "is_published": true,
    "tuition_fee": 1000000
  }'

# BEFORE FIX: Returns 200 OK (VULNERABLE!)
# AFTER FIX: Returns 403 Forbidden (SECURE!)
```

**2. Test Admin Access (After Fix):**
```bash
# Login as admin
curl -X POST http://localhost:8000/api/auth/login \
  -d "username=admin&password=admin123"

# Create academic info (should succeed)
curl -X POST http://localhost:8000/api/offerings/1/academic-info \
  -H "Cookie: access_token=<admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "offering_id": 1,
    "academic_year": 2025,
    "is_published": true,
    "tuition_fee": 1000000
  }'

# AFTER FIX: Returns 200 OK (CORRECT!)
```

---

## Impact Assessment

### Before Fix (Vulnerable)

| Endpoint | Officer Can? | Expected | Risk |
|----------|--------------|----------|------|
| POST `/offerings/{id}/academic-info` | ✅ YES | ❌ NO | 🔴 HIGH |
| PATCH `/academic-info/{id}` | ✅ YES | ❌ NO | 🔴 HIGH |
| DELETE `/academic-info/{id}` | ✅ YES | ❌ NO | 🔴 HIGH |

### After Fix (Secure)

| Endpoint | Officer Can? | Expected | Risk |
|----------|--------------|----------|------|
| POST `/offerings/{id}/academic-info` | ❌ NO (403) | ❌ NO | ✅ NONE |
| PATCH `/academic-info/{id}` | ❌ NO (403) | ❌ NO | ✅ NONE |
| DELETE `/academic-info/{id}` | ❌ NO (403) | ❌ NO | ✅ NONE |

---

## Timeline

- **2025-11-13 (Initial Audit):** Incorrectly reported "ALL endpoints protected"
- **2025-11-13 (Re-audit):** User identified inconsistency in organization.py
- **2025-11-13 (Analysis):** Confirmed Authorization Bypass vulnerability
- **2025-11-13 (Fix):** Implementing remediation (in progress)

---

## Lessons Learned

### What Went Wrong in Initial Audit?

1. **Assumption:** Assumed `deps.CurrentUser` provided RBAC enforcement
2. **Pattern Matching:** Checked for dependency presence, not dependency TYPE
3. **Missing Test:** Did not verify Casbin policies existed for all paths

### Improved Audit Process

**Checklist for Future Audits:**

- [ ] Check dependency type: `get_current_user` vs `check_permission`
- [ ] Verify Casbin policies exist for ALL protected paths
- [ ] Test authorization with different roles (not just authentication)
- [ ] Check docstring claims match actual enforcement
- [ ] Validate consistency across all routers

---

## References

- **CWE-862:** Missing Authorization
- **OWASP Top 10 2021:** A01:2021 – Broken Access Control
- **Casbin Documentation:** https://casbin.org/docs/overview
- **FastAPI Security:** https://fastapi.tiangolo.com/tutorial/security/

---

## Sign-Off

**Vulnerability Confirmed:** YES
**Severity:** HIGH (CVSS 7.1)
**Fix Priority:** 🔴 **CRITICAL - MUST FIX BEFORE PRODUCTION**
**Estimated Fix Time:** 2-3 hours
**Testing Required:** Unit tests + Manual authorization tests

---
