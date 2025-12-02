# 🔧 DETAILED IMPLEMENTATION PLAN - BUG FIX ROADMAP

**Project:** QLTS (Quản Lý Tuyển Sinh)
**Total Violations:** 100
**Estimated Effort:** 68 hours (1.5-2 months for 1 developer)
**Created:** 2025-12-02

---

## 📊 OVERVIEW

| Priority | Issues | Effort | Timeline |
|----------|--------|--------|----------|
| **Priority 0 (EMERGENCY)** | 3 | 35h | Week 1 |
| **Priority 1 (CRITICAL)** | 2 | 21h | Week 2-3 |
| **Priority 2 (HIGH)** | 3 | 12h | Week 4 |
| **Priority 3 (MEDIUM)** | 2 | 4h | Month 2 |
| **TOTAL** | **10** | **72h** | **2 months** |

---

# 🚨 PRIORITY 0: EMERGENCY (WEEK 1)

## Issue #1: IDOR Vulnerabilities - Applications Endpoints

**Severity:** 🔴 CRITICAL
**Effort:** 4 hours
**Files:** 2 (applications.py, deps.py)
**Impact:** Data breach, unauthorized access to all applications

### **Step 1.1: Create ApplicationAccessDep (1 hour)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/core/deps.py`

**Location:** Add after `get_lead_for_user` function (around line 330)

**Code to add:**

```python
# ============================================================================
# APPLICATION ACCESS DEPENDENCY (IDOR PREVENTION)
# ============================================================================

async def get_application_for_user(
    application_id: int = Path(..., description="ID of the Application"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
) -> models.Application:
    """
    Verify ownership and retrieve an application.

    Access Rules:
    - Admin: Can access all applications
    - Manager: Can access applications for leads in their managed units
    - Officer: Can access applications for their assigned leads only

    Raises:
        ResourceNotFoundError: If application doesn't exist
        PermissionDeniedError: If user doesn't have permission
    """
    from ..services import application_service

    # Get application with lead relationship
    try:
        application = await application_service.get_application_by_id(
            db,
            application_id,
            load_lead=True  # Ensure lead is loaded for ownership check
        )
    except ResourceNotFoundError:
        raise ResourceNotFoundError(
            detail=f"Application with id {application_id} not found"
        )

    # Verify application has associated lead
    if not application.lead:
        raise ResourceNotFoundError(
            detail=f"Application {application_id} has no associated lead"
        )

    lead = application.lead

    # ADMIN: Full access to all applications
    if current_user.role == "admin":
        log.debug(
            "Admin accessing application",
            application_id=application_id,
            admin_id=current_user.id
        )
        return application

    # MANAGER: Access to applications for leads in their managed units
    if current_user.role == "manager":
        managed_units = await get_user_managed_units(db, current_user.id)
        if lead.unit_id in managed_units:
            log.debug(
                "Manager accessing application in managed unit",
                application_id=application_id,
                manager_id=current_user.id,
                unit_id=lead.unit_id
            )
            return application

    # OFFICER: Access to applications for their assigned leads only
    if current_user.role == "officer":
        if lead.assigned_officer_id == current_user.id:
            log.debug(
                "Officer accessing application for assigned lead",
                application_id=application_id,
                officer_id=current_user.id,
                lead_id=lead.id
            )
            return application

    # ACCESS DENIED
    log.warning(
        "Unauthorized application access attempt",
        application_id=application_id,
        user_id=current_user.id,
        user_role=current_user.role,
        lead_officer_id=lead.assigned_officer_id,
        lead_unit_id=lead.unit_id
    )
    raise PermissionDeniedError(
        detail="You do not have permission to access this application."
    )
```

**Testing:**
```bash
# Run after adding function
pytest tests/test_deps.py::test_get_application_for_user -v
```

---

### **Step 1.2: Update application_service.py (30 mins)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/services/application_service.py`

**Find:** Function `get_application_by_id` (around line 126-159)

**Modify signature to support eager loading:**

```python
async def get_application_by_id(
    db: AsyncSession,
    application_id: int,
    load_lead: bool = False  # ← ADD THIS PARAMETER
) -> models.Application:
    """
    Retrieve application by ID.

    Args:
        db: Database session
        application_id: Application ID
        load_lead: If True, eager load the associated lead (for IDOR check)
    """
    query = select(models.Application).where(
        models.Application.id == application_id
    )

    # ✅ ADD: Eager load lead if requested
    if load_lead:
        query = query.options(
            selectinload(models.Application.lead).options(
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.unit)
            )
        )

    result = await db.execute(query)
    application = result.scalar_one_or_none()

    if not application:
        raise ResourceNotFoundError(
            detail=f"Application with id {application_id} not found"
        )

    return application
```

---

### **Step 1.3: Update applications.py - GET Endpoint (30 mins)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/routers/applications.py`

**Find:** GET endpoint (lines 97-129)

**BEFORE:**
```python
@router.get("/applications/{application_id}", response_model=schemas.Application)
async def get_application(
    application_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),  # ❌ Not enough!
):
    """Get application by ID."""
    application = await application_service.get_application_by_id(
        db, application_id
    )
    return application
```

**AFTER:**
```python
@router.get("/applications/{application_id}", response_model=schemas.Application)
async def get_application(
    application: models.Application = Depends(deps.get_application_for_user),  # ✅ IDOR check
):
    """
    Get application by ID.

    Access Control:
    - Admin: All applications
    - Manager: Applications in managed units
    - Officer: Applications for assigned leads
    """
    return application
```

**Changes:**
1. Remove `application_id` parameter (comes from dependency)
2. Remove `db` parameter (not needed anymore)
3. Remove `current_user` parameter (dependency handles it)
4. Add `application: models.Application = Depends(deps.get_application_for_user)`

---

### **Step 1.4: Update applications.py - PUT Endpoint (30 mins)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/routers/applications.py`

**Find:** PUT endpoint (lines 137-172)

**BEFORE:**
```python
@router.put("/applications/{application_id}", response_model=schemas.Application)
async def update_application(
    application_id: int,  # ❌ No ownership check
    application_in: schemas.ApplicationUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Update an existing application."""
    result = await application_service.update_application(
        db=db,
        application_id=application_id,
        application_in=application_in,
        current_user=current_user,
    )
    await db.commit()
    return result
```

**AFTER:**
```python
@router.put("/applications/{application_id}", response_model=schemas.Application)
async def update_application(
    application_in: schemas.ApplicationUpdate,
    application: models.Application = Depends(deps.get_application_for_user),  # ✅ IDOR check
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Update an existing application.

    Access Control:
    - Admin: Can update all applications
    - Manager: Can update applications in managed units
    - Officer: Can update applications for assigned leads
    """
    result = await application_service.update_application(
        db=db,
        application_id=application.id,  # ✅ Use verified application ID
        application_in=application_in,
        current_user=current_user,
    )
    await db.commit()
    return result
```

---

### **Step 1.5: Update applications.py - DELETE Endpoint (30 mins)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/routers/applications.py`

**Find:** DELETE endpoint (lines 235-299)

**BEFORE:**
```python
@router.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    application_id: int,  # ❌ No ownership check
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Soft delete an application."""
    # ... logic
    await application_service.delete_application(db, application_id)
    await db.commit()
    return None
```

**AFTER:**
```python
@router.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    application: models.Application = Depends(deps.get_application_for_user),  # ✅ IDOR check
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Soft delete an application.

    Access Control:
    - Admin: Can delete all applications
    - Manager: Can delete applications in managed units
    - Officer: Can delete applications for assigned leads
    """
    await application_service.delete_application(db, application.id)  # ✅ Use verified ID
    await db.commit()

    log.info(
        "Application deleted",
        application_id=application.id,
        deleted_by=current_user.id,
        lead_id=application.lead_id
    )

    return None
```

---

### **Step 1.6: Add Integration Tests (1 hour)**

**File:** `/home/user/QLTS/Backend_FastAPI/tests/test_applications_idor.py` (CREATE NEW)

```python
"""
Integration tests for Application IDOR protection.
"""
import pytest
from fastapi import status
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestApplicationIDOR:
    """Test IDOR protection for application endpoints."""

    async def test_officer_cannot_access_other_officer_application(
        self,
        async_client: AsyncClient,
        officer_token: str,
        other_officer_application_id: int
    ):
        """Officer should NOT be able to access another officer's application."""
        response = await async_client.get(
            f"/applications/{other_officer_application_id}",
            headers={"Authorization": f"Bearer {officer_token}"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "permission" in response.json()["detail"].lower()

    async def test_officer_can_access_own_application(
        self,
        async_client: AsyncClient,
        officer_token: str,
        own_application_id: int
    ):
        """Officer should be able to access their own application."""
        response = await async_client.get(
            f"/applications/{own_application_id}",
            headers={"Authorization": f"Bearer {officer_token}"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == own_application_id

    async def test_admin_can_access_all_applications(
        self,
        async_client: AsyncClient,
        admin_token: str,
        any_application_id: int
    ):
        """Admin should be able to access all applications."""
        response = await async_client.get(
            f"/applications/{any_application_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == status.HTTP_200_OK

    async def test_manager_can_access_unit_application(
        self,
        async_client: AsyncClient,
        manager_token: str,
        managed_unit_application_id: int
    ):
        """Manager should be able to access applications in managed units."""
        response = await async_client.get(
            f"/applications/{managed_unit_application_id}",
            headers={"Authorization": f"Bearer {manager_token}"}
        )

        assert response.status_code == status.HTTP_200_OK

    async def test_manager_cannot_access_other_unit_application(
        self,
        async_client: AsyncClient,
        manager_token: str,
        other_unit_application_id: int
    ):
        """Manager should NOT access applications outside managed units."""
        response = await async_client.get(
            f"/applications/{other_unit_application_id}",
            headers={"Authorization": f"Bearer {manager_token}"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_officer_cannot_update_other_officer_application(
        self,
        async_client: AsyncClient,
        officer_token: str,
        other_officer_application_id: int
    ):
        """Officer should NOT be able to update another officer's application."""
        response = await async_client.put(
            f"/applications/{other_officer_application_id}",
            headers={"Authorization": f"Bearer {officer_token}"},
            json={"status": "approved"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_officer_cannot_delete_other_officer_application(
        self,
        async_client: AsyncClient,
        officer_token: str,
        other_officer_application_id: int
    ):
        """Officer should NOT be able to delete another officer's application."""
        response = await async_client.delete(
            f"/applications/{other_officer_application_id}",
            headers={"Authorization": f"Bearer {officer_token}"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
```

**Run tests:**
```bash
pytest tests/test_applications_idor.py -v
```

---

### **Step 1.7: Verify Fix (30 mins)**

**Checklist:**
- [ ] `get_application_for_user` added to deps.py
- [ ] `application_service.get_application_by_id` supports `load_lead` parameter
- [ ] GET /applications/{id} uses dependency
- [ ] PUT /applications/{id} uses dependency
- [ ] DELETE /applications/{id} uses dependency
- [ ] All tests pass
- [ ] Manual testing with Postman:
  - [ ] Officer A cannot access Officer B's application
  - [ ] Officer can access own application
  - [ ] Admin can access all applications
  - [ ] Manager can access managed unit applications

**Manual Test Script:**
```bash
# 1. Login as Officer A
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"officer1","password":"pass"}' \
  -c cookies.txt

# 2. Try to access Officer B's application (should fail)
curl -X GET http://localhost:8000/api/applications/999 \
  -b cookies.txt

# Expected: 403 Forbidden

# 3. Access own application (should succeed)
curl -X GET http://localhost:8000/api/applications/1 \
  -b cookies.txt

# Expected: 200 OK with application data
```

---

## Issue #2: Transaction Management - Top 4 Services

**Severity:** 🔴 CRITICAL
**Effort:** 29 hours
**Files:** 4 services
**Impact:** Data consistency, atomicity

### **Issue #2.1: config_service.py - 18 Violations (10 hours)**

**Strategy:** Remove all `await db.commit()` and let routers handle commits

#### **Step 2.1.1: Audit All Functions (1 hour)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/services/config_service.py`

**Functions with violations (from audit):**
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
13. Line 946: Other config functions
14. Line 997: Other config functions
15. Line 1062: Other config functions

**Pattern to apply to ALL functions:**
```python
# ❌ BEFORE (Service commits)
async def create_something(db: AsyncSession, data: Schema):
    obj = Model(**data.dict())
    db.add(obj)
    await db.commit()  # ❌ Remove this
    await db.refresh(obj)

    # Post-commit actions
    await invalidate_cache()
    await emit_event()

    return obj

# ✅ AFTER (Router commits, service returns callback)
async def create_something(db: AsyncSession, data: Schema):
    """
    Create something.

    IMPORTANT: This function does NOT commit. Router must call db.commit().
    """
    obj = Model(**data.dict())
    db.add(obj)
    await db.flush()  # ✅ Flush to get ID without committing
    await db.refresh(obj)

    # Return callback for post-commit actions
    async def _post_commit():
        await invalidate_cache()
        await emit_event()

    return obj, _post_commit
```

#### **Step 2.1.2: Refactor update_assignment_config (Line 123) - Example (1 hour)**

**BEFORE:**
```python
async def update_assignment_config(
    db: AsyncSession,
    unit_id: int,
    config_in: schemas.AssignmentConfigUpdate
) -> models.ConfigAssignmentConfig:
    # ... validation logic ...

    config.params = params_dict
    db.add(config)

    # ❌ Service commits
    await db.commit()
    await db.refresh(config, attribute_names=["params"])

    # Post-commit cache invalidation
    try:
        await safe_redis_delete(cache_key)
    except Exception as e:
        log.error("Failed to invalidate cache", error=str(e))

    return config
```

**AFTER:**
```python
async def update_assignment_config(
    db: AsyncSession,
    unit_id: int,
    config_in: schemas.AssignmentConfigUpdate
) -> Tuple[models.ConfigAssignmentConfig, Callable]:
    """
    Update assignment configuration for a unit.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (config, post_commit_callback)
    """
    # ... validation logic (unchanged) ...

    config.params = params_dict
    db.add(config)

    # ✅ Flush instead of commit
    await db.flush()
    await db.refresh(config, attribute_names=["params"])

    # Create callback for post-commit actions
    cache_key = f"assignment_config:{unit_id}"

    async def _post_commit():
        """Execute after router commits the transaction."""
        try:
            deleted = await safe_redis_delete(cache_key)
            if deleted > 0:
                log.info("Invalidated assignment config cache", unit_id=unit_id)
        except Exception as e:
            log.error(
                "Failed to invalidate cache after config update",
                unit_id=unit_id,
                error=str(e)
            )

    return config, _post_commit
```

**Update Router:**

**File:** `/home/user/QLTS/Backend_FastAPI/app/routers/admin/config.py` (Line ~60)

**BEFORE:**
```python
@router.put("/assignment-config/{unit_id}")
async def update_assignment_config(
    unit_id: int,
    config_in: schemas.AssignmentConfigUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    params = await config_service.update_assignment_config(db, unit_id, config_in)
    # Service already committed
    return {"params": params}
```

**AFTER:**
```python
@router.put("/assignment-config/{unit_id}")
async def update_assignment_config(
    unit_id: int,
    config_in: schemas.AssignmentConfigUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """Update assignment configuration."""
    try:
        # Get config and post-commit callback
        config, post_commit = await config_service.update_assignment_config(
            db, unit_id, config_in
        )

        # ✅ Router commits the transaction
        await db.commit()

        # Execute post-commit actions (cache invalidation, events)
        await post_commit()

        return {"params": config.params}

    except Exception as e:
        await db.rollback()
        log.error("Failed to update assignment config", error=str(e))
        raise
```

#### **Step 2.1.3: Repeat Pattern for All 18 Functions (8 hours)**

**Apply same pattern to:**

**Degree Level Functions:**
- `create_degree_level()` - Line 177
- `update_degree_level()` - Line 204
- `delete_degree_level()` - Line 296

**Tuition Fee Functions:**
- `create_tuition_fee()` - Line 341
- `update_tuition_fee()` - Line 382
- `delete_tuition_fee()` - Line 386

**Consultation Status Functions:**
- `create_consultation_status()` - Line 469
- `update_consultation_status()` - Line 543
- `delete_consultation_status()` - Lines 584, 588

**Pipeline Stage Functions:**
- `create_pipeline_stage()` - Line 687
- `update_pipeline_stage()` - Line 736
- `delete_pipeline_stage()` - Lines 763, 767

**Other Config Functions:**
- Lines 946, 997, 1062

**For each function:**
1. Change return type to `Tuple[Model, Callable]`
2. Replace `await db.commit()` with `await db.flush()`
3. Move post-commit actions (cache, events) to callback
4. Return `(object, callback)`
5. Update corresponding router to commit and call callback

**Estimated time per function:** ~30 minutes × 18 = 9 hours

---

### **Issue #2.2: organization_service.py - 13 Violations (8 hours)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/services/organization_service.py`

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

**Same Pattern as config_service.py:**

```python
# Template for organization functions
async def create_organization_unit(
    db: AsyncSession,
    unit_in: schemas.OrganizationUnitCreate
) -> Tuple[models.OrganizationUnit, Callable]:
    """
    Create organization unit.

    IMPORTANT: Does NOT commit. Router must commit and execute callback.
    """
    # Validation
    await check_duplicate_unit_name(db, unit_in.name, unit_in.parent_id)

    # Create unit
    db_unit = models.OrganizationUnit(**unit_in.model_dump())
    db.add(db_unit)
    await db.flush()  # ✅ Get ID without commit
    await db.refresh(db_unit)

    # Post-commit callback
    async def _post_commit():
        await invalidate_org_cache()
        await emit_organization_updated(
            operation="create",
            resource_type="organization",
            resource_id=db_unit.id,
            resource_name=db_unit.name
        )

    return db_unit, _post_commit
```

**Router Update Example:**

**File:** `/home/user/QLTS/Backend_FastAPI/app/routers/admin/organization.py`

```python
@router.post("/organization-units", response_model=schemas.OrganizationUnit)
async def create_organization_unit(
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """Create new organization unit."""
    try:
        unit, post_commit = await organization_service.create_organization_unit(
            db, unit_in
        )

        await db.commit()  # ✅ Atomic boundary
        await post_commit()  # Cache + events

        return unit
    except Exception as e:
        await db.rollback()
        raise
```

**Estimated time:** 13 functions × 30 mins = 6.5 hours + testing 1.5h = 8h

---

### **Issue #2.3: user_service.py - 10 Violations (6 hours)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/services/user_service.py`

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

**Same pattern, with special handling for bulk operations:**

```python
async def import_users_from_csv(
    db: AsyncSession,
    file_content: bytes,  # ✅ Already fixed from Issue #3
    filename: str,
    current_user: models.User,
) -> Tuple[dict, Callable]:
    """
    Import users from CSV.

    Returns:
        Tuple of (result_dict, post_commit_callback)
    """
    # Parse CSV
    users_created = []

    for row in csv_rows:
        # Create user
        db_user = models.User(**user_data)
        db.add(db_user)
        users_created.append(db_user)

    # ✅ Flush all users
    await db.flush()

    # Post-commit actions
    async def _post_commit():
        # Send welcome emails
        for user in users_created:
            try:
                await email_service.send_welcome_email(user.email)
            except Exception as e:
                log.error("Failed to send welcome email", error=str(e))

        # Invalidate cache
        await safe_redis_delete("users:*")

    return {
        "created": len(users_created),
        "users": users_created
    }, _post_commit
```

**Estimated time:** 10 functions × 30 mins = 5 hours + testing 1h = 6h

---

### **Issue #2.4: pipeline_service.py - 8 Violations (5 hours)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/services/pipeline_service.py`

**Apply same pattern to all 8 functions**

**Estimated time:** 8 functions × 30 mins = 4 hours + testing 1h = 5h

---

### **Summary of Issue #2:**

| Service | Violations | Effort | Status |
|---------|------------|--------|--------|
| config_service.py | 18 | 10h | Week 1 |
| organization_service.py | 13 | 8h | Week 1 |
| user_service.py | 10 | 6h | Week 1 |
| pipeline_service.py | 8 | 5h | Week 1 |
| **TOTAL** | **49** | **29h** | **Week 1** |

**Completion:** After Week 1, you've fixed 71% of transaction violations (49/69)

---

## Issue #3: Service Layer Purity - UploadFile Import

**Severity:** 🟠 MEDIUM
**Effort:** 2 hours
**Files:** 2 (user_service.py, routers/admin/users.py)

### **Step 3.1: Refactor user_service.py (1 hour)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/services/user_service.py`

**Line 8 - Remove import:**
```python
# ❌ BEFORE
from fastapi import UploadFile

# ✅ AFTER
# Remove this line - use bytes instead
```

**Line ~1100 - Update function signature:**

**BEFORE:**
```python
async def import_users_from_csv(
    db: AsyncSession,
    file: UploadFile,  # ❌ FastAPI dependency
    current_user: models.User,
):
    content = await file.read()
    # ... processing
```

**AFTER:**
```python
async def import_users_from_csv(
    db: AsyncSession,
    file_content: bytes,  # ✅ Pure Python type
    filename: str,  # For logging/validation
    current_user: models.User,
) -> Tuple[dict, Callable]:  # ✅ Also return callback (Issue #2)
    """
    Import users from CSV file.

    Args:
        db: Database session
        file_content: Raw CSV file content (bytes)
        filename: Original filename (for validation/logging)
        current_user: User performing the import

    Returns:
        Tuple of (result_dict, post_commit_callback)

    IMPORTANT: Does NOT commit. Router must commit and execute callback.
    """
    # Validate filename extension
    if not filename.endswith('.csv'):
        raise BadRequest(detail="File must be a CSV file")

    # Decode content
    try:
        content_str = file_content.decode('utf-8')
    except UnicodeDecodeError:
        raise BadRequest(detail="Invalid CSV encoding. Please use UTF-8.")

    # Parse CSV
    csv_reader = csv.DictReader(io.StringIO(content_str))

    # ... rest of logic unchanged ...

    users_created = []

    for row in csv_reader:
        # Sanitize and create user
        sanitized_row = sanitize_csv_row(row)
        # ... create user logic ...
        db.add(db_user)
        users_created.append(db_user)

    # ✅ Flush instead of commit
    await db.flush()

    # Post-commit callback
    async def _post_commit():
        # Send welcome emails
        for user in users_created:
            try:
                await email_service.send_welcome_email(user.email)
            except Exception as e:
                log.error("Failed to send welcome email", error=str(e))

    return {
        "created": len(users_created),
        "failed": 0,
        "users": [u.id for u in users_created]
    }, _post_commit
```

### **Step 3.2: Update Router (1 hour)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/routers/admin/users.py`

**Find import endpoint (search for "import" or "csv"):**

**BEFORE:**
```python
from fastapi import UploadFile, File

@router.post("/import-users")
async def import_users(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    result = await user_service.import_users_from_csv(
        db, file, current_admin
    )
    # Service already committed
    return result
```

**AFTER:**
```python
from fastapi import UploadFile, File  # ✅ Keep in router (correct layer)

@router.post("/import-users")
async def import_users(
    file: UploadFile = File(..., description="CSV file with user data"),  # ✅ Router handles HTTP
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    Import multiple users from CSV file.

    CSV Format:
    - Columns: username, email, full_name, role, unit_id
    - Max file size: 10MB
    """
    # Validate file size
    content = await file.read()

    if len(content) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 10MB."
        )

    # Validate content type
    if not file.content_type in ["text/csv", "application/csv"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Please upload a CSV file."
        )

    try:
        # Pass bytes to service (not UploadFile)
        result, post_commit = await user_service.import_users_from_csv(
            db=db,
            file_content=content,  # ✅ Pass bytes
            filename=file.filename,  # ✅ Pass metadata
            current_user=current_admin
        )

        # ✅ Router commits
        await db.commit()

        # Execute post-commit actions (welcome emails)
        await post_commit()

        log.info(
            "Users imported successfully",
            count=result["created"],
            imported_by=current_admin.id,
            filename=file.filename
        )

        return result

    except Exception as e:
        await db.rollback()
        log.error("User import failed", error=str(e))
        raise
```

### **Step 3.3: Test (30 mins)**

**Create test file:** `tests/test_user_import_refactored.py`

```python
import pytest
from io import BytesIO

pytestmark = pytest.mark.asyncio


async def test_import_users_csv(async_client, admin_token):
    """Test CSV import with refactored service."""
    csv_content = b"""username,email,full_name,role,unit_id
testuser1,test1@example.com,Test User 1,officer,1
testuser2,test2@example.com,Test User 2,officer,1"""

    files = {"file": ("users.csv", BytesIO(csv_content), "text/csv")}

    response = await async_client.post(
        "/admin/users/import",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files
    )

    assert response.status_code == 200
    assert response.json()["created"] == 2


async def test_import_users_invalid_format(async_client, admin_token):
    """Test CSV import with invalid file format."""
    files = {"file": ("users.txt", BytesIO(b"invalid"), "text/plain")}

    response = await async_client.post(
        "/admin/users/import",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files
    )

    assert response.status_code == 400


async def test_import_users_too_large(async_client, admin_token):
    """Test CSV import with file too large."""
    large_content = b"a" * (11 * 1024 * 1024)  # 11MB
    files = {"file": ("large.csv", BytesIO(large_content), "text/csv")}

    response = await async_client.post(
        "/admin/users/import",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files
    )

    assert response.status_code == 413
```

---

# 🔴 PRIORITY 1: CRITICAL (WEEK 2-3)

## Issue #4: Transaction Management - Remaining 20 Violations

**Severity:** 🔴 CRITICAL
**Effort:** 13 hours
**Files:** 10 services

**Services to fix:**
1. `notification_service.py` - 4 violations (2h)
2. `application_service.py` - 3 violations (1.5h)
3. `notification_preference_service.py` - 3 violations (1.5h)
4. `tuition_discount_service.py` - 3 violations (1.5h)
5. `lead_service.py` - 2 violations (1h)
6. `activity_service.py` - 1 violation (0.5h)
7. `notification_dispatcher.py` - 1 violation (0.5h)
8. `notification_workflow.py` - 1 violation (0.5h)
9. `officer_service.py` - 1 violation (0.5h)
10. `role_service.py` - 1 violation (0.5h)

**Total:** 20 violations × 30 mins average = 10h + 3h testing = 13h

**Apply same pattern from Issue #2**

---

## Issue #5: Rate Limiting - 190 Endpoints

**Severity:** 🟠 HIGH
**Effort:** 8 hours
**Files:** All routers

### **Step 5.1: Define Rate Limit Tiers (30 mins)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/core/rate_limits.py` (CREATE NEW)

```python
"""
Rate limiting configuration for API endpoints.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize limiter
limiter = Limiter(key_func=get_remote_address)

# Rate limit tiers
class RateLimits:
    """Standard rate limit tiers."""

    # Authentication endpoints (strict)
    AUTH_LOGIN = "5/minute"
    AUTH_REGISTER = "3/minute"
    AUTH_PASSWORD_RESET = "3/hour"
    AUTH_PASSWORD_CHANGE = "10/hour"

    # Admin endpoints (moderate)
    ADMIN_READ = "300/hour"      # GET operations
    ADMIN_WRITE = "100/hour"     # POST/PUT/DELETE
    ADMIN_BULK = "10/hour"       # Bulk operations

    # User data endpoints
    DATA_READ = "1000/hour"      # GET list/detail
    DATA_WRITE = "200/hour"      # POST/PUT/DELETE
    DATA_EXPORT = "20/hour"      # CSV/Excel exports

    # Public endpoints
    PUBLIC_READ = "100/hour"     # Reference data

    # Real-time endpoints
    REALTIME = "500/hour"        # Notifications, WebSocket
```

### **Step 5.2: Apply to Admin Routers (3 hours)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/routers/admin/users.py`

```python
from ..core.rate_limits import limiter, RateLimits

# Apply to all endpoints
@router.get("/users", response_model=List[schemas.User])
@limiter.limit(RateLimits.ADMIN_READ)  # ✅ Add rate limit
async def get_users(...):
    """Get all users."""
    ...

@router.post("/users", response_model=schemas.User)
@limiter.limit(RateLimits.ADMIN_WRITE)  # ✅ Add rate limit
async def create_user(...):
    """Create new user."""
    ...

@router.delete("/users/{user_id}")
@limiter.limit(RateLimits.ADMIN_WRITE)  # ✅ Add rate limit
async def delete_user(...):
    """Delete user."""
    ...

@router.post("/users/import")
@limiter.limit(RateLimits.ADMIN_BULK)  # ✅ Stricter for bulk ops
async def import_users(...):
    """Import users from CSV."""
    ...
```

**Repeat for all admin routers:**
- admin/users.py - 25 endpoints
- admin/config.py - 22 endpoints
- admin/organization.py - 16 endpoints
- admin/pipeline.py - 15 endpoints
- admin/roles.py - 20 endpoints
- admin/cache.py - 9 endpoints
- admin/system.py - 3 endpoints
- admin/tuition_discount.py - 10 endpoints

**Total:** 120 admin endpoints × 1 min each = 2 hours

### **Step 5.3: Apply to Feature Routers (3 hours)**

**File:** `/home/user/QLTS/Backend_FastAPI/app/routers/leads.py`

```python
from ..core.rate_limits import limiter, RateLimits

@router.get("/leads", response_model=schemas.LeadsPage)
@limiter.limit(RateLimits.DATA_READ)  # ✅ 1000/hour
async def get_leads(...):
    """Get paginated leads."""
    ...

@router.post("/leads", response_model=schemas.Lead)
@limiter.limit(RateLimits.DATA_WRITE)  # ✅ 200/hour
async def create_lead(...):
    """Create new lead."""
    ...

@router.put("/leads/{lead_id}", response_model=schemas.Lead)
@limiter.limit(RateLimits.DATA_WRITE)  # ✅ 200/hour
async def update_lead(...):
    """Update lead."""
    ...
```

**Repeat for:**
- leads.py - 17 endpoints
- applications.py - 4 endpoints
- notifications.py - 4 endpoints
- organization.py - 12 endpoints
- pipeline.py - 3 endpoints
- etc.

**Total:** 70 feature endpoints × 1 min each = 1.5 hours

### **Step 5.4: Update main.py (30 mins)**

**File:** `/home/user/QLTS/Backend_FastAPI/main.py`

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limits import limiter

# Add limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add middleware for rate limit headers
@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next):
    response = await call_next(request)

    # Add rate limit info to response headers
    if hasattr(request.state, "view_rate_limit"):
        response.headers["X-RateLimit-Limit"] = str(request.state.view_rate_limit.limit)
        response.headers["X-RateLimit-Remaining"] = str(request.state.view_rate_limit.remaining)
        response.headers["X-RateLimit-Reset"] = str(request.state.view_rate_limit.reset)

    return response
```

### **Step 5.5: Test Rate Limiting (1 hour)**

**File:** `tests/test_rate_limiting.py` (CREATE NEW)

```python
import pytest
import time
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_login_rate_limit(async_client: AsyncClient):
    """Test login endpoint rate limit (5 per minute)."""
    # Make 5 requests (should succeed)
    for i in range(5):
        response = await async_client.post(
            "/auth/login",
            json={"username": "test", "password": "wrong"}
        )
        assert response.status_code in [200, 401]  # Login may fail but not rate limited

    # 6th request should be rate limited
    response = await async_client.post(
        "/auth/login",
        json={"username": "test", "password": "wrong"}
    )
    assert response.status_code == 429  # Too Many Requests
    assert "rate limit" in response.json()["detail"].lower()


async def test_admin_read_rate_limit(async_client: AsyncClient, admin_token: str):
    """Test admin GET endpoints rate limit (300 per hour)."""
    # Make multiple requests
    success_count = 0

    for i in range(350):
        response = await async_client.get(
            "/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        if response.status_code == 200:
            success_count += 1
        elif response.status_code == 429:
            break

    # Should have ~300 successful requests
    assert 290 <= success_count <= 310
```

---

# 🟠 PRIORITY 2: HIGH (WEEK 4)

## Issue #6: Error Boundaries - Frontend

**Severity:** 🟠 HIGH
**Effort:** 4 hours
**Files:** 10+ error.tsx files

### **Step 6.1: Create Root Error Boundary (1 hour)**

**File:** `/home/user/QLTS/frontend/src/app/error.tsx` (CREATE NEW)

```typescript
'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { AlertCircle } from 'lucide-react'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Log error to monitoring service
    console.error('Application error:', error)

    // TODO: Send to error tracking service (Sentry, etc.)
    // trackError(error)
  }, [error])

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="max-w-md w-full space-y-6 text-center">
        <AlertCircle className="h-16 w-16 text-destructive mx-auto" />

        <div className="space-y-2">
          <h1 className="text-2xl font-bold">Something went wrong!</h1>
          <p className="text-muted-foreground">
            {error.message || 'An unexpected error occurred'}
          </p>
          {error.digest && (
            <p className="text-xs text-muted-foreground">
              Error ID: {error.digest}
            </p>
          )}
        </div>

        <div className="flex gap-4 justify-center">
          <Button
            onClick={() => reset()}
            variant="default"
          >
            Try again
          </Button>
          <Button
            onClick={() => window.location.href = '/dashboard'}
            variant="outline"
          >
            Go to Dashboard
          </Button>
        </div>
      </div>
    </div>
  )
}
```

### **Step 6.2: Add Error Boundaries to Major Routes (2 hours)**

**Create error.tsx for each major route:**

1. **Dashboard Error Boundary**

**File:** `/home/user/QLTS/frontend/src/app/(dashboard)/error.tsx`

```typescript
'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertTriangle } from 'lucide-react'

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Dashboard error:', error)
  }, [error])

  return (
    <div className="container mx-auto p-6">
      <Card className="max-w-2xl mx-auto">
        <CardHeader>
          <div className="flex items-center gap-4">
            <AlertTriangle className="h-10 w-10 text-destructive" />
            <CardTitle>Dashboard Error</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground">
            Failed to load dashboard data. This might be a temporary issue.
          </p>

          <div className="bg-muted p-3 rounded-md">
            <code className="text-sm">{error.message}</code>
          </div>

          <div className="flex gap-3">
            <Button onClick={() => reset()}>
              Retry
            </Button>
            <Button variant="outline" onClick={() => window.location.reload()}>
              Refresh Page
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

2. **Leads Error Boundary**

**File:** `/home/user/QLTS/frontend/src/app/(dashboard)/leads/error.tsx`

```typescript
'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { AlertCircle } from 'lucide-react'

export default function LeadsError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Leads error:', error)
  }, [error])

  return (
    <div className="container mx-auto p-6">
      <div className="max-w-lg mx-auto text-center space-y-6">
        <AlertCircle className="h-16 w-16 text-destructive mx-auto" />
        <h2 className="text-2xl font-bold">Failed to Load Leads</h2>
        <p className="text-muted-foreground">
          {error.message || 'Could not fetch lead data'}
        </p>
        <div className="flex gap-3 justify-center">
          <Button onClick={() => reset()}>Try Again</Button>
          <Button variant="outline" onClick={() => window.location.href = '/dashboard'}>
            Back to Dashboard
          </Button>
        </div>
      </div>
    </div>
  )
}
```

3. **Admin Error Boundary**

**File:** `/home/user/QLTS/frontend/src/app/(dashboard)/admin/error.tsx`

```typescript
'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Shield } from 'lucide-react'

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Admin error:', error)
  }, [error])

  return (
    <div className="container mx-auto p-6">
      <div className="max-w-lg mx-auto text-center space-y-6">
        <Shield className="h-16 w-16 text-destructive mx-auto" />
        <h2 className="text-2xl font-bold">Admin Panel Error</h2>
        <p className="text-muted-foreground">
          Failed to load admin resources. Please contact system administrator if this persists.
        </p>
        <Button onClick={() => reset()}>Retry</Button>
      </div>
    </div>
  )
}
```

**Create similar files for:**
- `/app/(dashboard)/profile/error.tsx`
- `/app/(dashboard)/notifications/error.tsx`
- `/app/(dashboard)/settings/error.tsx`
- `/app/(auth)/error.tsx`

**Time:** 10 error.tsx files × 10 mins = 1.5 hours

### **Step 6.3: Test Error Boundaries (30 mins)**

**Create test component to trigger errors:**

**File:** `/home/user/QLTS/frontend/src/components/test/ErrorTrigger.tsx`

```typescript
'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'

export function ErrorTrigger() {
  const [shouldError, setShouldError] = useState(false)

  if (shouldError) {
    throw new Error('Test error triggered!')
  }

  return (
    <Button onClick={() => setShouldError(true)}>
      Trigger Test Error
    </Button>
  )
}
```

**Manual Testing:**
1. Add `<ErrorTrigger />` to a page
2. Click button
3. Verify error boundary catches error
4. Verify "Try again" button works
5. Remove test component

---

## Issue #7: Loading States - Frontend

**Severity:** 🟠 HIGH
**Effort:** 4 hours
**Files:** 10+ loading.tsx files

### **Step 7.1: Create Reusable Skeleton Components (1 hour)**

**File:** `/home/user/QLTS/frontend/src/components/ui/skeletons.tsx` (CREATE NEW)

```typescript
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent, CardHeader } from '@/components/ui/card'

export function DashboardSkeleton() {
  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Chart */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-64 w-full" />
        </CardContent>
      </Card>
    </div>
  )
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {/* Table Header */}
      <div className="flex gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-4 flex-1" />
        ))}
      </div>

      {/* Table Rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4">
          {[1, 2, 3, 4].map((j) => (
            <Skeleton key={j} className="h-8 flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}

export function FormSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-10 w-full" />
        </div>
      ))}
      <Skeleton className="h-10 w-32" />
    </div>
  )
}

export function LeadCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <Skeleton className="h-12 w-12 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-48" />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-3/4" />
      </CardContent>
    </Card>
  )
}
```

### **Step 7.2: Add Loading States to Major Routes (2 hours)**

1. **Dashboard Loading**

**File:** `/home/user/QLTS/frontend/src/app/(dashboard)/loading.tsx`

```typescript
import { DashboardSkeleton } from '@/components/ui/skeletons'

export default function DashboardLoading() {
  return <DashboardSkeleton />
}
```

2. **Leads Loading**

**File:** `/home/user/QLTS/frontend/src/app/(dashboard)/leads/loading.tsx`

```typescript
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { TableSkeleton } from '@/components/ui/skeletons'

export default function LeadsLoading() {
  return (
    <div className="container mx-auto p-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-10 w-28" />
          </div>
        </CardHeader>
        <CardContent>
          <TableSkeleton rows={10} />
        </CardContent>
      </Card>
    </div>
  )
}
```

3. **Lead Detail Loading**

**File:** `/home/user/QLTS/frontend/src/app/(dashboard)/leads/[id]/loading.tsx`

```typescript
import { LeadCardSkeleton } from '@/components/ui/skeletons'

export default function LeadDetailLoading() {
  return (
    <div className="container mx-auto p-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 space-y-6">
          <LeadCardSkeleton />
          <LeadCardSkeleton />
        </div>
        <div className="space-y-6">
          <LeadCardSkeleton />
        </div>
      </div>
    </div>
  )
}
```

**Create similar files for:**
- `/app/(dashboard)/admin/loading.tsx`
- `/app/(dashboard)/admin/users/loading.tsx`
- `/app/(dashboard)/admin/organization/loading.tsx`
- `/app/(dashboard)/profile/loading.tsx`
- `/app/(dashboard)/notifications/loading.tsx`
- `/app/(dashboard)/settings/loading.tsx`

**Time:** 10 loading.tsx files × 10 mins = 1.5 hours

### **Step 7.3: Test Loading States (30 mins)**

**Simulate slow network:**
```typescript
// Add to next.config.js (development only)
async rewrites() {
  return {
    beforeFiles: [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
        // Add artificial delay in dev
        has: [{ type: 'header', key: 'x-slow-network' }],
      },
    ],
  }
}
```

**Chrome DevTools:**
1. Open DevTools > Network tab
2. Set throttling to "Slow 3G"
3. Navigate to different pages
4. Verify loading skeletons appear
5. Verify smooth transition to real content

---

## Issue #8: IDOR - Notification Templates/Rules

**Severity:** 🟡 MEDIUM
**Effort:** 4 hours
**Files:** 2 (notification_templates.py, notification_rules.py)

**Apply same pattern as Issue #1 (Applications IDOR fix)**

**Create dependencies:**
- `get_notification_template_for_admin()`
- `get_notification_rule_for_admin()`

**Update routers to use dependencies**

**Time:** 4 hours (similar to Issue #1)

---

# 🟢 PRIORITY 3: MEDIUM (MONTH 2)

## Issue #9: Suspense Boundaries - Frontend

**Severity:** 🟡 MEDIUM
**Effort:** 2 hours

**Wrap async components in Suspense:**

```typescript
import { Suspense } from 'react'
import { LeadCardSkeleton } from '@/components/ui/skeletons'

export default async function LeadsPage() {
  return (
    <div className="container mx-auto p-6">
      <Suspense fallback={<LeadCardSkeleton />}>
        <LeadsList />
      </Suspense>
    </div>
  )
}
```

**Apply to ~20-30 components**

---

## Issue #10: Admin Config Unit IDOR

**Severity:** 🟡 MEDIUM
**Effort:** 2 hours

**Add unit ownership check for managers**

---

# 📊 PROGRESS TRACKING

## Weekly Milestones

### Week 1 (35 hours)
- [ ] IDOR - Applications (4h)
- [ ] Transaction - config_service.py (10h)
- [ ] Transaction - organization_service.py (8h)
- [ ] Transaction - user_service.py (6h)
- [ ] Transaction - pipeline_service.py (5h)
- [ ] Service Layer - UploadFile (2h)

**Deliverable:** 72% of critical issues fixed

### Week 2-3 (21 hours)
- [ ] Transaction - Remaining 10 services (13h)
- [ ] Rate Limiting - All endpoints (8h)

**Deliverable:** 95% of critical issues fixed

### Week 4 (12 hours)
- [ ] Error Boundaries - Frontend (4h)
- [ ] Loading States - Frontend (4h)
- [ ] IDOR - Notifications (4h)

**Deliverable:** 100% of high-priority issues fixed

### Month 2 (4 hours)
- [ ] Suspense Boundaries (2h)
- [ ] Admin Config IDOR (2h)

**Deliverable:** 100% compliance

---

# ✅ VERIFICATION CHECKLIST

After completing all fixes:

## Backend Verification
- [ ] No `await db.commit()` in any service file
- [ ] All services return callbacks for post-commit actions
- [ ] All routers call `db.commit()` and execute callbacks
- [ ] IDOR dependencies protect all ID-based endpoints
- [ ] Rate limiters on all POST/PUT/DELETE endpoints
- [ ] No FastAPI imports in service layer
- [ ] Integration tests pass (200+ tests)
- [ ] Load tests show no performance degradation

## Frontend Verification
- [ ] Error boundaries on all major routes (10+ files)
- [ ] Loading states on all major routes (10+ files)
- [ ] Suspense boundaries on async components (20+ instances)
- [ ] No console errors during navigation
- [ ] Smooth UX during slow network conditions
- [ ] Error recovery works (reset buttons)

## Security Verification
- [ ] IDOR attack tests fail (403 Forbidden)
- [ ] Rate limit tests trigger 429 responses
- [ ] Transaction rollback tests succeed
- [ ] Penetration testing results clean

---

# 🚀 DEPLOYMENT STRATEGY

## Phase 1: Hot-fix Critical Issues (Week 1)
- Deploy IDOR fix immediately (Monday)
- Deploy transaction fixes incrementally (Tuesday-Friday)
- Monitor error rates closely

## Phase 2: Security Hardening (Week 2-3)
- Deploy rate limiting (staged rollout)
- Monitor rate limit triggers
- Adjust limits based on usage patterns

## Phase 3: UX Improvements (Week 4)
- Deploy error/loading states
- Gather user feedback
- Iterate on skeleton designs

## Phase 4: Final Polish (Month 2)
- Deploy remaining optimizations
- Performance testing
- Security audit sign-off

---

**PLAN COMPLETE - READY FOR EXECUTION** ✅

**Total Effort:** 72 hours
**Timeline:** 2 months
**Risk:** Low (incremental deployment)
**Impact:** High (100% compliance)
