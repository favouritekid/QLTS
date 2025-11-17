# PHASE 2A Testing Guide

**Status**: PHASE 2A Extraction Complete - Ready for Testing
**Date**: 2025-11-17
**Endpoints Extracted**: 39 (16 in users.py + 23 in roles.py)
**Branch**: `claude/refactoring-execution-plan-015j9PAMoSNW4qbrVgJhnpUc`

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Starting the Server](#starting-the-server)
3. [Accessing Swagger UI](#accessing-swagger-ui)
4. [Authentication Setup](#authentication-setup)
5. [Testing Strategy](#testing-strategy)
6. [Endpoint Test Scenarios](#endpoint-test-scenarios)
7. [PHASE 1 Integration Tests](#phase-1-integration-tests)
8. [Dual Router Verification](#dual-router-verification)
9. [Common Issues and Solutions](#common-issues-and-solutions)
10. [Test Checklist](#test-checklist)

---

## Prerequisites

### Required Dependencies
```bash
# Ensure all dependencies are installed
cd /home/user/QLTS/Backend_FastAPI
pip install -r requirements.txt
```

### Database Setup
```bash
# Ensure database is running and migrations are applied
alembic upgrade head
```

### Casbin Enforcer
Verify Casbin policy files exist:
- `Backend_FastAPI/rbac_model.conf`
- `Backend_FastAPI/rbac_policy.csv`

### Environment Variables
Ensure `.env` file is configured with:
```env
DATABASE_URL=postgresql+asyncpg://...
SECRET_KEY=...
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

---

## Starting the Server

```bash
# From the Backend_FastAPI directory
cd /home/user/QLTS/Backend_FastAPI

# Start server with reload enabled
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Expected output:
# INFO:     Uvicorn running on http://0.0.0.0:8000
# INFO:     Application startup complete.
```

### Verify Server Startup

Check console output for:
```
✅ Casbin Enforcer initialized successfully
✅ All routers loaded
```

If you see errors, check:
1. Database connection
2. Casbin policy files
3. Environment variables

---

## Accessing Swagger UI

Open your browser and navigate to:

**Swagger UI**: http://localhost:8000/docs
**ReDoc**: http://localhost:8000/redoc

### Expected Swagger UI Sections

You should see **THREE** admin sections in Swagger UI:

1. **Admin (Legacy)** - Old monolithic admin router (backward compatibility)
2. **Admin - Users** - New users.py router (16 endpoints)
3. **Admin - Roles & Permissions** - New roles.py router (23 endpoints)

If you see duplicate endpoints, this is **expected** - it's part of the dual router migration strategy.

---

## Authentication Setup

### Step 1: Create Test Admin User (if not exists)

```bash
# Option A: Use existing admin account
# Check your database for existing admin users

# Option B: Create via alembic seed script or direct SQL
```

### Step 2: Login via Swagger UI

1. Scroll to **Auth** section in Swagger UI
2. Expand `POST /api/auth/login`
3. Click **Try it out**
4. Enter credentials:
   ```json
   {
     "email": "admin@example.com",
     "password": "your_password"
   }
   ```
5. Click **Execute**
6. Copy the `access_token` from response

### Step 3: Authorize Swagger UI

1. Click **Authorize** button at top of Swagger UI
2. In "HTTPBearer (http, Bearer)" field, paste: `Bearer <your_token>`
3. Click **Authorize**
4. Click **Close**

**✅ You're now authenticated!** All subsequent requests will include the token.

---

## Testing Strategy

### Test Levels

1. **Smoke Tests** (5 min): Verify all endpoints are accessible
2. **Functional Tests** (20 min): Test core CRUD operations
3. **Integration Tests** (15 min): Verify PHASE 1 service integration
4. **Dual Router Tests** (10 min): Verify both old and new routers work

**Total Estimated Time**: ~50 minutes for comprehensive manual testing

### Test Priorities

- **HIGH**: Core CRUD operations (users, roles, policies)
- **MEDIUM**: Bulk operations, analytics
- **LOW**: Advanced features (templates, feature flags)

---

## Endpoint Test Scenarios

### 1. Admin - Users (users.py) - 16 Endpoints

#### 1.1 User CRUD Operations (HIGH Priority)

##### Test: Create New User
- **Endpoint**: `POST /api/admin/users`
- **Swagger Section**: Admin - Users
- **Request Body**:
  ```json
  {
    "email": "testuser@example.com",
    "full_name": "Test User",
    "password": "SecurePass123!",
    "role": "Advisor"
  }
  ```
- **Expected Response**: 201 Created
  ```json
  {
    "id": 123,
    "email": "testuser@example.com",
    "full_name": "Test User",
    "role": "Advisor",
    "is_active": true,
    "created_at": "2025-11-17T..."
  }
  ```
- **Verification**:
  - User created in database
  - Password hashed (not stored as plain text)
  - Activity log created

##### Test: Get All Users
- **Endpoint**: `GET /api/admin/users`
- **Query Params**:
  - `skip`: 0
  - `limit`: 10
- **Expected Response**: 200 OK with user list
- **Verification**:
  - Pagination works
  - User roles included
  - Password hash NOT exposed

##### Test: Get User Details
- **Endpoint**: `GET /api/admin/users/{user_id}`
- **Expected Response**: 200 OK with user details + roles
- **Verification**:
  - Includes Casbin roles
  - Shows user permissions

##### Test: Update User
- **Endpoint**: `PUT /api/admin/users/{user_id}`
- **Request Body**:
  ```json
  {
    "full_name": "Updated Name",
    "role": "Manager"
  }
  ```
- **Expected Response**: 200 OK
- **Verification**:
  - User updated in database
  - Activity log created with changes tracked

##### Test: Delete User
- **Endpoint**: `DELETE /api/admin/users/{user_id}`
- **Expected Response**: 200 OK
- **Verification**:
  - User deleted from database
  - All Casbin roles revoked
  - Activity log created

#### 1.2 Password Management (HIGH Priority)

##### Test: Admin Reset User Password
- **Endpoint**: `POST /api/admin/users/{user_id}/password`
- **Request Body**:
  ```json
  {
    "new_password": "NewSecurePass123!"
  }
  ```
- **Expected Response**: 200 OK
- **Verification**:
  - Password updated and hashed
  - User can login with new password
  - Activity log created

#### 1.3 User Export (MEDIUM Priority)

##### Test: Export Users to Excel
- **Endpoint**: `GET /api/admin/users/export`
- **Expected Response**: 200 OK with Excel file download
- **Content-Type**: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **Verification**:
  - Downloads .xlsx file
  - Contains all users
  - Password hash NOT included

##### Test: Export Users to CSV (Streaming)
- **Endpoint**: `GET /api/admin/users/export/csv`
- **Expected Response**: 200 OK with CSV stream
- **Content-Type**: `text/csv`
- **Verification**:
  - Downloads .csv file
  - Streaming works (doesn't load all into memory)

#### 1.4 Bulk Operations (MEDIUM Priority)

##### Test: Bulk Enable/Disable Users
- **Endpoint**: `POST /api/admin/users/bulk`
- **Request Body**:
  ```json
  {
    "user_ids": [1, 2, 3],
    "action": "disable"
  }
  ```
- **Expected Response**: 200 OK
  ```json
  {
    "success": [1, 2, 3],
    "failed": []
  }
  ```
- **Verification**:
  - Users disabled in database
  - Activity log created for each user

#### 1.5 Casbin Sync (HIGH Priority - PHASE 1 Integration)

##### Test: Get Sync Status
- **Endpoint**: `GET /api/admin/sync/status`
- **Expected Response**: 200 OK
  ```json
  {
    "users_in_db": 50,
    "users_in_casbin": 45,
    "sync_needed": true,
    "orphaned_users": []
  }
  ```

##### Test: Sync Users to Casbin
- **Endpoint**: `POST /api/admin/sync/users`
- **Expected Response**: 200 OK
- **Verification**:
  - **PHASE 1 Integration**: Calls `user_service.sync_users_to_casbin()`
  - All users synced to Casbin enforcer
  - Activity log created

#### 1.6 Lead Management (MEDIUM Priority - PHASE 1 Integration)

##### Test: Bulk Assign Leads
- **Endpoint**: `POST /api/admin/leads/bulk-assign`
- **Request Body**:
  ```json
  {
    "lead_ids": [1, 2, 3],
    "assigned_to": 10
  }
  ```
- **Expected Response**: 200 OK
- **Verification**:
  - Leads assigned to user
  - Activity log created

##### Test: Import Leads from CSV
- **Endpoint**: `POST /api/admin/leads/import`
- **Request**: Multipart form with CSV file
- **Expected Response**: 200 OK
- **Verification**:
  - **PHASE 1 Integration**: Calls `lead_service.import_leads_from_csv()`
  - Leads created in database
  - Activity log created

#### 1.7 Analytics (LOW Priority)

##### Test: Get User Statistics
- **Endpoint**: `GET /api/admin/statistics/users`
- **Expected Response**: 200 OK
  ```json
  {
    "total_users": 50,
    "active_users": 45,
    "inactive_users": 5,
    "by_role": {
      "Admin": 2,
      "Manager": 5,
      "Advisor": 43
    }
  }
  ```

##### Test: Get Activity Logs
- **Endpoint**: `GET /api/admin/activity-logs`
- **Query Params**:
  - `skip`: 0
  - `limit`: 20
  - `action`: "user_created" (optional)
- **Expected Response**: 200 OK with activity log list
- **Verification**:
  - Pagination works
  - Filters work

---

### 2. Admin - Roles & Permissions (roles.py) - 23 Endpoints

#### 2.1 Policy CRUD (HIGH Priority)

##### Test: Get All Policies
- **Endpoint**: `GET /api/admin/policies`
- **Expected Response**: 200 OK
  ```json
  [
    ["Admin", "/api/admin/*", "GET"],
    ["Admin", "/api/admin/*", "POST"],
    ...
  ]
  ```
- **Verification**:
  - Returns all Casbin policies
  - Format: [subject, object, action]

##### Test: Add New Policy
- **Endpoint**: `POST /api/admin/policies`
- **Request Body**:
  ```json
  {
    "subject": "Advisor",
    "object": "/api/leads/*",
    "action": "GET"
  }
  ```
- **Expected Response**: 201 Created
- **Verification**:
  - Policy added to Casbin enforcer
  - Policy persisted to `rbac_policy.csv`
  - Activity log created

##### Test: Delete Policy
- **Endpoint**: `DELETE /api/admin/policies`
- **Request Body**:
  ```json
  {
    "subject": "Advisor",
    "object": "/api/leads/*",
    "action": "GET"
  }
  ```
- **Expected Response**: 200 OK
- **Verification**:
  - Policy removed from Casbin enforcer
  - Activity log created

#### 2.2 Role Assignment (HIGH Priority - PHASE 1 Integration)

##### Test: Assign Role to User
- **Endpoint**: `POST /api/admin/roles/assign`
- **Request Body**:
  ```json
  {
    "user_id": 123,
    "role_name": "Manager"
  }
  ```
- **Expected Response**: 201 Created
- **Verification**:
  - **PHASE 1 Integration**: Calls `role_service.assign_role()`
  - Role assigned in Casbin
  - Activity log created

##### Test: Remove Role from User
- **Endpoint**: `DELETE /api/admin/roles/revoke`
- **Request Body**:
  ```json
  {
    "user_id": 123,
    "role_name": "Manager"
  }
  ```
- **Expected Response**: 200 OK
- **Verification**:
  - **PHASE 1 Integration**: Calls `role_service.revoke_role()`
  - Role removed from Casbin
  - Activity log created

##### Test: Get User Roles
- **Endpoint**: `GET /api/admin/users/{user_id}/roles`
- **Expected Response**: 200 OK
  ```json
  {
    "user_id": 123,
    "roles": ["Advisor", "Manager"]
  }
  ```

##### Test: Get Role Users
- **Endpoint**: `GET /api/admin/roles/{role_name}/users`
- **Expected Response**: 200 OK with list of users having that role

##### Test: Remove Role from All Users
- **Endpoint**: `DELETE /api/admin/roles/{role_name}/users`
- **Expected Response**: 200 OK
- **Verification**:
  - All users with that role have it revoked
  - Activity logs created for each user

#### 2.3 Grouping Policies (MEDIUM Priority)

##### Test: Add Grouping Policy (Role Inheritance)
- **Endpoint**: `POST /api/admin/grouping-policies`
- **Request Body**:
  ```json
  {
    "subject": "Manager",
    "role": "Advisor"
  }
  ```
- **Expected Response**: 201 Created
- **Verification**:
  - Manager role now inherits Advisor permissions
  - Policy added to Casbin

##### Test: Delete Grouping Policy
- **Endpoint**: `DELETE /api/admin/grouping-policies`
- **Request Body**: Same as above
- **Expected Response**: 200 OK

#### 2.4 Role Management (HIGH Priority)

##### Test: Get All Roles with Info
- **Endpoint**: `GET /api/admin/roles`
- **Expected Response**: 200 OK
  ```json
  [
    {
      "role_name": "Admin",
      "user_count": 2,
      "policy_count": 15
    },
    {
      "role_name": "Manager",
      "user_count": 5,
      "policy_count": 8
    }
  ]
  ```

##### Test: Delete Role (Atomic)
- **Endpoint**: `DELETE /api/admin/roles/{role_name}`
- **Expected Response**: 200 OK
- **Verification**:
  - Role deleted
  - All policies for that role deleted
  - All grouping policies deleted
  - All user assignments removed
  - **Atomic**: Either all succeed or all fail

#### 2.5 Policy Templates (LOW Priority)

##### Test: Get Policy Templates
- **Endpoint**: `GET /api/admin/policy-templates`
- **Expected Response**: 200 OK with available templates

##### Test: Apply Template to Role
- **Endpoint**: `POST /api/admin/policies/apply-template`
- **Request Body**:
  ```json
  {
    "role_name": "NewRole",
    "template_name": "advisor_template"
  }
  ```
- **Expected Response**: 200 OK

#### 2.6 Batch Operations (MEDIUM Priority)

##### Test: Batch Add Policies
- **Endpoint**: `POST /api/admin/policies/batch`
- **Request Body**:
  ```json
  {
    "policies": [
      {"subject": "Role1", "object": "/api/resource1", "action": "GET"},
      {"subject": "Role1", "object": "/api/resource1", "action": "POST"}
    ]
  }
  ```
- **Expected Response**: 200 OK

#### 2.7 Validation & Simulation (MEDIUM Priority)

##### Test: Validate Policy
- **Endpoint**: `POST /api/admin/policies/validate`
- **Request Body**:
  ```json
  {
    "subject": "Advisor",
    "object": "/api/admin/users",
    "action": "DELETE"
  }
  ```
- **Expected Response**: 200 OK
  ```json
  {
    "valid": false,
    "reason": "Advisors cannot delete users"
  }
  ```

##### Test: Simulate Permission
- **Endpoint**: `POST /api/admin/permissions/simulate`
- **Request Body**:
  ```json
  {
    "user_id": 123,
    "resource": "/api/leads/456",
    "action": "GET"
  }
  ```
- **Expected Response**: 200 OK
  ```json
  {
    "allowed": true,
    "reason": "User has Advisor role with GET permission on /api/leads/*"
  }
  ```

#### 2.8 Analytics & Insights (LOW Priority)

##### Test: Get Policy Statistics
- **Endpoint**: `GET /api/admin/policies/statistics`
- **Expected Response**: 200 OK with policy usage stats

##### Test: Get Policy Suggestions
- **Endpoint**: `GET /api/admin/policies/suggestions`
- **Expected Response**: 200 OK with suggested policies based on patterns

##### Test: Explain Role Permissions
- **Endpoint**: `GET /api/admin/roles/{role_name}/permissions/explain`
- **Expected Response**: 200 OK with explanation of why role has certain permissions

##### Test: Who Can Access Resource
- **Endpoint**: `POST /api/admin/permissions/who-can-access`
- **Request Body**:
  ```json
  {
    "resource": "/api/admin/users",
    "action": "DELETE"
  }
  ```
- **Expected Response**: 200 OK
  ```json
  {
    "users": [
      {"user_id": 1, "email": "admin@example.com", "reason": "Has Admin role"}
    ]
  }
  ```

#### 2.9 Feature Flags (LOW Priority)

##### Test: Get Role Features
- **Endpoint**: `GET /api/admin/roles/{role_name}/features`
- **Expected Response**: 200 OK with feature flags

##### Test: Toggle Role Feature
- **Endpoint**: `POST /api/admin/roles/{role_name}/features/{feature_name}/toggle`
- **Expected Response**: 200 OK

---

## PHASE 1 Integration Tests

### Critical Integration Points

These endpoints MUST call PHASE 1 service layer functions:

#### 1. User Service Integration

**Endpoint**: `POST /api/admin/sync/users`
**Expected Behavior**:
- Calls `user_service.sync_users_to_casbin(db, enforcer)`
- Returns sync results
- Creates activity log

**Verification**:
```python
# Check app/routers/admin/users.py line ~250
result = await user_service.sync_users_to_casbin(db=db, enforcer=enforcer)
```

#### 2. Role Service Integration

**Endpoint**: `POST /api/admin/roles/assign`
**Expected Behavior**:
- Calls `role_service.assign_role(db, enforcer, user_id, role_name)`
- Returns success
- Creates activity log

**Verification**:
```python
# Check app/routers/admin/roles.py line ~80
await role_service.assign_role(db=db, enforcer=enforcer, ...)
```

**Endpoint**: `DELETE /api/admin/roles/revoke`
**Expected Behavior**:
- Calls `role_service.revoke_role(db, enforcer, user_id, role_name)`

#### 3. Lead Service Integration

**Endpoint**: `POST /api/admin/leads/import`
**Expected Behavior**:
- Calls `lead_service.import_leads_from_csv(db, file, ...)`
- Returns import results

**Verification**:
```python
# Check app/routers/admin/users.py line ~520
result = await lead_service.import_leads_from_csv(...)
```

#### 4. Activity Service Integration

**All Admin Endpoints**
**Expected Behavior**:
- Every state-changing endpoint calls `activity_service.log_activity()`
- Activity logs created with IP address and user agent

**Verification**:
```python
# Check log_admin_activity helper function in both routers
await activity_service.log_activity(
    db=db,
    action=action,
    resource_type=resource_type,
    ...
)
```

---

## Dual Router Verification

### Purpose
Verify both old monolithic router and new split routers work simultaneously for zero-downtime migration.

### Test Scenarios

#### Scenario 1: Old Router Still Works

1. Test an endpoint from **Admin (Legacy)** section in Swagger
2. Example: `GET /api/admin/users` from legacy router
3. **Expected**: Works correctly, returns user list
4. **Purpose**: Ensures backward compatibility

#### Scenario 2: New Router Works

1. Test same endpoint from **Admin - Users** section
2. Example: `GET /api/admin/users` from new router
3. **Expected**: Works correctly, returns same user list
4. **Purpose**: Ensures new router functions

#### Scenario 3: Both Return Same Data

1. Call same endpoint on both routers
2. Compare responses
3. **Expected**: Identical data
4. **Purpose**: Ensures consistency

#### Scenario 4: Swagger UI Organization

1. Open Swagger UI
2. Verify sections:
   - ✅ "Admin (Legacy)" - old router
   - ✅ "Admin - Users" - users.py
   - ✅ "Admin - Roles & Permissions" - roles.py
3. **Expected**: Clear separation, no confusion

#### Scenario 5: Activity Logs from Both Routers

1. Create user via old router
2. Create user via new router
3. Check activity logs
4. **Expected**: Both create activity logs correctly

### Migration Path

After frontend migration:
1. Frontend stops using `/api/admin/*` paths (legacy)
2. Frontend uses new paths:
   - `/api/admin/users/*`
   - `/api/admin/roles/*`
3. Monitor traffic to legacy router (should decrease to zero)
4. After 2 weeks with zero traffic, remove legacy router from main.py

---

## Common Issues and Solutions

### Issue 1: 401 Unauthorized on All Endpoints

**Symptoms**: All admin endpoints return 401
**Cause**: Missing or invalid authentication token
**Solution**:
1. Re-login via `/api/auth/login`
2. Copy new token
3. Click "Authorize" in Swagger and update token

### Issue 2: 403 Forbidden on Admin Endpoints

**Symptoms**: Endpoints return 403 even with valid token
**Cause**: User doesn't have Admin role
**Solution**:
1. Check user roles: `GET /api/admin/users/{user_id}`
2. Assign Admin role if needed (requires existing admin)
3. Or directly update `rbac_policy.csv` and restart server

### Issue 3: Casbin Enforcer Not Loading Policies

**Symptoms**: All permission checks fail
**Cause**: Casbin policy file missing or corrupted
**Solution**:
```bash
# Check files exist
ls -la Backend_FastAPI/rbac_model.conf
ls -la Backend_FastAPI/rbac_policy.csv

# Restart server to reload policies
# Check console for Casbin errors
```

### Issue 4: Import Errors on Server Start

**Symptoms**: `ModuleNotFoundError: No module named 'app.routers.admin'`
**Cause**: Missing `__init__.py` files
**Solution**:
```bash
# Verify files exist
ls -la Backend_FastAPI/app/routers/admin/__init__.py
ls -la Backend_FastAPI/app/routers/admin/users.py
ls -la Backend_FastAPI/app/routers/admin/roles.py

# Restart server
```

### Issue 5: Duplicate Endpoints in Swagger

**Symptoms**: Same endpoint appears multiple times
**Cause**: This is **expected** during dual router migration
**Solution**: No action needed - this is intentional for zero-downtime migration

### Issue 6: PHASE 1 Service Not Found

**Symptoms**: `AttributeError: module 'app.services.user_service' has no attribute 'sync_users_to_casbin'`
**Cause**: PHASE 1 services not properly committed/merged
**Solution**:
```bash
# Verify PHASE 1 services exist
ls -la Backend_FastAPI/app/services/user_service.py
ls -la Backend_FastAPI/app/services/role_service.py
ls -la Backend_FastAPI/app/services/lead_service.py

# Check git log for PHASE 1 commits
git log --oneline | grep -i "phase 1"
```

---

## Test Checklist

### Pre-Testing Setup ✅
- [ ] Database running and migrations applied
- [ ] Casbin policy files exist
- [ ] Environment variables configured
- [ ] Dependencies installed
- [ ] Server starts without errors

### Smoke Tests (5 min) ✅
- [ ] Server starts successfully
- [ ] Swagger UI loads
- [ ] Three admin sections visible
- [ ] Authentication works
- [ ] Legacy router accessible
- [ ] New routers accessible

### Admin - Users Testing (20 min) ✅
- [ ] Create user (POST /api/admin/users)
- [ ] Get all users (GET /api/admin/users)
- [ ] Get user details (GET /api/admin/users/{id})
- [ ] Update user (PUT /api/admin/users/{id})
- [ ] Delete user (DELETE /api/admin/users/{id})
- [ ] Reset password (POST /api/admin/users/{id}/password)
- [ ] Export Excel (GET /api/admin/users/export)
- [ ] Export CSV (GET /api/admin/users/export/csv)
- [ ] Bulk operations (POST /api/admin/users/bulk)
- [ ] Get sync status (GET /api/admin/sync/status)
- [ ] Sync users (POST /api/admin/sync/users) **[PHASE 1]**
- [ ] Bulk assign leads (POST /api/admin/leads/bulk-assign)
- [ ] Import leads (POST /api/admin/leads/import) **[PHASE 1]**
- [ ] User statistics (GET /api/admin/statistics/users)
- [ ] Activity logs (GET /api/admin/activity-logs)

### Admin - Roles Testing (20 min) ✅
- [ ] Get all policies (GET /api/admin/policies)
- [ ] Add policy (POST /api/admin/policies)
- [ ] Delete policy (DELETE /api/admin/policies)
- [ ] Assign role (POST /api/admin/roles/assign) **[PHASE 1]**
- [ ] Revoke role (DELETE /api/admin/roles/revoke) **[PHASE 1]**
- [ ] Get user roles (GET /api/admin/users/{id}/roles)
- [ ] Get role users (GET /api/admin/roles/{name}/users)
- [ ] Remove role from all (DELETE /api/admin/roles/{name}/users)
- [ ] Add grouping policy (POST /api/admin/grouping-policies)
- [ ] Delete grouping policy (DELETE /api/admin/grouping-policies)
- [ ] Get all roles (GET /api/admin/roles)
- [ ] Delete role atomic (DELETE /api/admin/roles/{name})
- [ ] Get templates (GET /api/admin/policy-templates)
- [ ] Batch add policies (POST /api/admin/policies/batch)
- [ ] Validate policy (POST /api/admin/policies/validate)
- [ ] Apply template (POST /api/admin/policies/apply-template)
- [ ] Policy statistics (GET /api/admin/policies/statistics)
- [ ] Policy suggestions (GET /api/admin/policies/suggestions)
- [ ] Simulate permission (POST /api/admin/permissions/simulate)
- [ ] Explain permissions (GET /api/admin/roles/{name}/permissions/explain)
- [ ] Who can access (POST /api/admin/permissions/who-can-access)
- [ ] Get role features (GET /api/admin/roles/{name}/features)
- [ ] Toggle feature (POST /api/admin/roles/{name}/features/{feature}/toggle)

### PHASE 1 Integration (15 min) ✅
- [ ] User service integration verified (sync_users_to_casbin)
- [ ] Role service integration verified (assign_role, revoke_role)
- [ ] Lead service integration verified (import_leads_from_csv)
- [ ] Activity service integration verified (all endpoints log activity)

### Dual Router Verification (10 min) ✅
- [ ] Legacy router works
- [ ] New routers work
- [ ] Both return same data
- [ ] Swagger sections properly organized
- [ ] Activity logs from both routers

### Error Handling ✅
- [ ] Invalid input returns 400
- [ ] Missing authentication returns 401
- [ ] Insufficient permissions returns 403
- [ ] Non-existent resource returns 404
- [ ] Server errors return 500 with proper logging

### Performance ✅
- [ ] Pagination works for large datasets
- [ ] CSV streaming doesn't load all into memory
- [ ] Bulk operations handle 100+ items

---

## Next Steps After Testing

### If All Tests Pass ✅

1. **Document Test Results**
   - Create test report with screenshots
   - Note any minor issues or warnings
   - Confirm all PHASE 1 integrations work

2. **Notify Frontend Team**
   - Share breaking API path changes
   - Provide migration timeline
   - Offer support for frontend migration

3. **Monitor Production**
   - Track traffic to old vs new routers
   - Monitor error rates
   - Check activity logs

4. **Proceed to PHASE 2B**
   - Extract organization.py (12 endpoints)
   - Extract config.py (20 endpoints)
   - Follow same testing process

### If Tests Fail ❌

1. **Document Failures**
   - Note exact endpoint and request that failed
   - Copy error message and stack trace
   - Check server console logs

2. **Debug and Fix**
   - Review router code
   - Check PHASE 1 service integration
   - Verify database state

3. **Re-test**
   - After fixes, run full test suite again
   - Don't proceed to PHASE 2B until all tests pass

---

## Summary

**PHASE 2A Testing Goals**:
1. ✅ Verify all 39 endpoints work correctly
2. ✅ Confirm PHASE 1 service integration
3. ✅ Validate dual router strategy
4. ✅ Ensure zero breaking changes for existing API consumers

**Estimated Testing Time**: ~50 minutes for comprehensive manual testing

**Success Criteria**:
- All endpoints return expected responses
- PHASE 1 services called correctly
- Both old and new routers functional
- Activity logs created for all state changes
- No errors in server console

**Ready to Begin**: Start server and open Swagger UI! 🚀
