# Casbin Authorization Audit Report

**Project:** QLTS Backend (FastAPI)
**Audit Date:** 2026-01-05
**Auditor:** Security Architecture Review

---

## Executive Summary

This project implements a **hybrid RBAC + ABAC authorization system** using Casbin. The architecture combines:
- **RBAC (Role-Based Access Control):** Role-to-permission mappings via Casbin policies
- **ABAC (Attribute-Based Access Control):** Ownership verification via FastAPI dependencies (IDOR prevention)

The implementation is generally well-structured with good separation of concerns, but there are several security concerns and inconsistencies that should be addressed.

---

## 1. Casbin Component Locations

### 1.1 Model Configuration
| File | Purpose |
|------|---------|
| `Backend_FastAPI/auth_model.conf` | Casbin model definition (RBAC with role inheritance) |

### 1.2 Policy Storage
| Location | Type |
|----------|------|
| Database table `casbin_rule` | SQLAlchemy async adapter (primary storage) |
| `app/casbin_config/policy_templates.py` | Policy templates for role creation |
| `alembic/versions/i4j5k6l7m8n9_*.py` | Default policies migration |
| `alembic/versions/g2h3i4j5k6l7_*.py` | Notification policies migration |
| Various `alembic/versions/*officer*.py` | Officer-specific policies |

### 1.3 Enforcer Initialization
| File | Line | Description |
|------|------|-------------|
| `app/main.py` | 150-158 | AsyncEnforcer initialization in lifespan startup |

### 1.4 Adapter
| Component | Implementation |
|-----------|----------------|
| Adapter Type | `casbin_async_sqlalchemy_adapter.Adapter` |
| Database Engine | SQLAlchemy async engine (`async_db_engine`) |

### 1.5 Middleware / Dependencies / Guards
| File | Dependencies |
|------|--------------|
| `app/core/deps.py` | `check_permission`, `require_admin`, `require_admin_or_manager`, `require_any_staff`, `require_roles`, `get_lead_for_user`, `get_application_for_user`, etc. |

### 1.6 Role Assignment Logic
| File | Purpose |
|------|---------|
| `app/services/role_service.py` | Role management operations (remove, delete) |
| `app/services/user_service.py` | User creation with Casbin sync, role assignment |
| `app/routers/admin/roles.py` | Admin API for policy/role management |

---

## 2. Authorization Model Analysis

### 2.1 Model Type
**RBAC with Simple Role Inheritance** (Flat, no hierarchy)

```conf
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub, obj, act

[role_definition]
g = _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub) && keyMatch4(r.obj, p.obj) && regexMatch(r.act, p.act)
```

### 2.2 Model Components Explained

| Component | Description |
|-----------|-------------|
| **sub** (Subject) | `user:{id}` (user identifier) or `role:{name}` (role identifier) |
| **obj** (Object) | URL path (e.g., `/api/leads`, `/api/admin/users/*`) |
| **act** (Action) | HTTP method (e.g., `GET`, `POST`, `DELETE`, `.*` for all) |
| **g** (Grouping) | Role inheritance: `user:5 -> role:manager` |
| **keyMatch4** | Path matching with parameter support (`{lead_id}` patterns) |
| **regexMatch** | Action matching (enables `.*` wildcard) |

### 2.3 Role Definitions

| Role | Description | Priority |
|------|-------------|----------|
| `role:admin` | Full system access | 4 (highest) |
| `role:manager` | User + lead management | 3 |
| `role:officer` | Lead operations (assigned) | 2 |
| `role:user` | Basic profile access | 1 (lowest) |

### 2.4 Role Assignment Mechanism

Users are assigned roles through **grouping policies** (g rules):
```
g, user:5, role:manager
```

**Dual Storage:**
1. **Casbin** (source of truth): Grouping policies in `casbin_rule` table
2. **Database** (cache): `user.role` column for fast access

**Role Sync Flow:**
- On user creation: Casbin grouping added, DB role set
- On role update: Casbin grouping modified, DB role synced
- On login: DB role auto-synced from Casbin (if mismatch detected)

### 2.5 Role Inheritance
**Status:** Supported but minimally used

The model supports role inheritance via `g, role:child, role:parent`, but the codebase primarily uses **flat role assignment** where each role has explicit policies rather than inheriting from parent roles.

---

## 3. Runtime Permission Enforcement

### 3.1 Enforcement Layers

The system uses a **three-layer authorization architecture:**

```
Layer 1: Authentication (get_current_user)
    ↓
Layer 2: RBAC Authorization (check_permission / CasbinAuth)
    ↓
Layer 3: IDOR Prevention (get_lead_for_user, get_application_for_user, etc.)
```

### 3.2 Layer 1: Authentication

**File:** `app/core/deps.py:71-288`

| Check | Description |
|-------|-------------|
| Token validation | JWT decode, expiry, type check |
| Access JTI blacklist | Token revocation check |
| User blacklist | Account-level blacklist |
| Session validity | Refresh JTI validation |
| Auto-sync | DB role synced from Casbin |

### 3.3 Layer 2: RBAC Authorization

**File:** `app/core/deps.py:362-394`

```python
async def check_permission(request, current_user):
    enforcer = request.app.state.enforcer
    subject = f"user:{current_user.id}"
    object_path = request.url.path
    action = request.method

    if not enforcer.enforce(subject, object_path, action):
        raise PermissionDeniedError()
    return current_user
```

**Request → Casbin Mapping:**
| Request Data | Casbin Parameter |
|--------------|------------------|
| `current_user.id` | `sub = "user:{id}"` |
| `request.url.path` | `obj = "/api/leads/123"` |
| `request.method` | `act = "GET"` |

**Enforcement Points (via `CasbinAuth` dependency):**
- 23 router files use Casbin-based authorization
- All admin endpoints use `CasbinAuth`
- Most user-facing endpoints use `CasbinAuth`

### 3.4 Layer 3: IDOR Prevention (Ownership)

**Purpose:** Prevent users from accessing resources they don't own

| Dependency | Resource | Logic |
|------------|----------|-------|
| `get_lead_for_user` | Lead | Admin/Manager: all; Officer: assigned only |
| `get_application_for_user` | Application | Admin: all; Manager: unit; Officer: assigned |
| `get_distribution_rule_for_user` | Distribution Rule | Admin: all; Manager: managed units |
| `get_organizational_unit_for_user` | Org Unit | Admin: all; Manager: managed |
| `verify_user_management_permission` | User | Admin: all; Manager: managed units |
| `get_officer_dashboard_scope` | Dashboard Data | Role-based scope enforcement |
| `get_lead_list_filter` | Lead List | Forces role-based query filters |

### 3.5 Alternative Role Checks

Some endpoints use role-based checks instead of Casbin:

| Dependency | Allowed Roles |
|------------|---------------|
| `require_admin` | admin only |
| `require_admin_or_manager` | admin, manager |
| `require_any_staff` | admin, manager, officer |
| `require_roles(["x", "y"])` | custom list |

---

## 4. Permission Matrix

### 4.1 Admin Role (`role:admin`)

| Resource Pattern | Actions | Source |
|------------------|---------|--------|
| `/*` | `.*` (all) | CRITICAL_POLICIES |
| `/api/*` | `.*` | Fallback policies |
| `/api/admin/*` | `.*` | Fallback policies |

**Note:** Admin has **wildcard access** to everything via `(role:admin, /*, .*)`.

### 4.2 Manager Role (`role:manager`)

| Resource Pattern | Actions | Source |
|------------------|---------|--------|
| `/api/admin/users` | `.*` | Default policies |
| `/api/leads/*` | `.*` | Default policies |
| `/api/leads` | `GET` | Default policies |
| `/api/profile` | `GET`, `PUT` | Default policies |
| All officer permissions | Inherited | MANAGER_TEMPLATE |

### 4.3 Officer Role (`role:officer`)

| Resource Pattern | Actions | Source |
|------------------|---------|--------|
| `/api/leads` | `GET` | Default policies |
| `/api/leads/{lead_id}` | `GET` | Default policies |
| `/api/leads/{lead_id}/consultations` | `POST` | Default policies |
| `/api/leads/{lead_id}/action` | `POST` | Default policies |
| `/api/pipeline/stages` | `GET` | OFFICER_TEMPLATE |
| `/api/pipeline/all` | `GET` | OFFICER_TEMPLATE |
| `/api/pipeline/allowed-next-statuses` | `GET` | OFFICER_TEMPLATE |
| `/api/officer/stats` | `GET` | OFFICER_TEMPLATE |
| `/api/officer/dashboard` | `GET` | OFFICER_TEMPLATE |
| `/api/officer/leaderboard` | `GET` | OFFICER_TEMPLATE |
| `/api/officer/team-stats` | `GET` | OFFICER_TEMPLATE |
| `/api/officer/upcoming-activities` | `GET` | OFFICER_TEMPLATE |
| `/api/officer/availability` | `POST` | OFFICER_TEMPLATE |
| `/api/officer/recommendations` | `GET` | OFFICER_TEMPLATE |
| `/api/admissions` | `GET`, `POST` | OFFICER_TEMPLATE |
| `/api/admissions/{profile_id}` | `GET`, `PUT` | OFFICER_TEMPLATE |
| `/api/admissions/{profile_id}/submit` | `POST` | OFFICER_TEMPLATE |
| `/api/admissions/{profile_id}/enroll` | `POST` | OFFICER_TEMPLATE |
| `/api/admissions/{profile_id}/documents/{doc_code}/upload` | `POST` | OFFICER_TEMPLATE |
| `/api/profile` | `GET`, `PUT` | Default policies |
| `/api/notifications` | `GET` | Notification policies |
| `/api/notifications/mark-as-read` | `POST` | Notification policies |
| `/api/notifications/mark-all-as-read` | `POST` | Notification policies |
| `/api/notifications/{notification_id}` | `DELETE` | Notification policies |

### 4.4 User Role (`role:user`)

| Resource Pattern | Actions | Source |
|------------------|---------|--------|
| `/api/profile` | `GET`, `PUT` | Default policies |
| `/api/notifications` | `GET` | Notification policies |
| `/api/notifications/mark-as-read` | `POST` | Notification policies |
| `/api/notifications/mark-all-as-read` | `POST` | Notification policies |
| `/api/notifications/{notification_id}` | `DELETE` | Notification policies |

### 4.5 Public Endpoints (No Auth Required)

| Endpoint | Purpose |
|----------|---------|
| `/api/auth/login` | Login |
| `/api/auth/register` | Registration |
| `/api/auth/refresh` | Token refresh |
| `/api/auth/forgot-password` | Password reset request |
| `/api/auth/reset-password` | Password reset |
| `/health` | Health check |
| `/health/detailed` | Detailed health |
| `/metrics` | Prometheus metrics |

---

## 5. Findings and Security Concerns

### 5.1 Critical Issues

#### C1: Inconsistent Authorization Patterns
**Severity:** HIGH
**Location:** Multiple router files

**Finding:** The codebase uses multiple authorization mechanisms inconsistently:
1. `CasbinAuth` (Casbin-based)
2. `require_admin` (role string comparison)
3. `require_admin_or_manager` (role string comparison)
4. `require_any_staff` (role string comparison)

**Risk:** Role-based checks bypass Casbin entirely, making policy changes ineffective for those endpoints.

**Example:**
```python
# Some endpoints use Casbin
current_user: models.User = CasbinAuth

# Other endpoints use direct role checks
current_user: models.User = Depends(require_admin)
```

#### C2: Missing `role:user` in Constants
**Severity:** MEDIUM
**Location:** `app/core/constants.py`

**Finding:** The `UserRole` enum only includes ADMIN, MANAGER, OFFICER but not USER:
```python
class UserRole(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    OFFICER = "officer"
    # Missing: USER = "user"
```

**Risk:** Code using `UserRole` enum cannot properly check for basic users.

#### C3: Implicit Deny-All Not Enforced
**Severity:** MEDIUM
**Location:** Policy model

**Finding:** The system relies on explicit policies without a default deny. New endpoints without policies are blocked by Casbin check, BUT:
- If `CasbinAuth` is not added to a new endpoint, it's completely unprotected
- Admin wildcard `(role:admin, /*, .*)` grants access to ALL paths including future ones

**Risk:** New endpoints may be accidentally exposed without authorization.

### 5.2 High Priority Issues

#### H1: Manager Has Wildcard Lead Access
**Severity:** HIGH
**Location:** Default policies

**Finding:** Manager role has `(/api/leads/*, .*)` which grants ALL operations on ALL leads.

**Problem:** While IDOR prevention exists, if an endpoint doesn't use ownership dependencies, managers can access any lead.

#### H2: Rate Limiting Bypass via Different Auth Dependencies
**Severity:** MEDIUM
**Location:** Various routers

**Finding:** Rate limits are defined per endpoint, but authorization is applied via different dependencies. A misconfigured endpoint could have rate limiting without proper auth.

#### H3: Password Reset Flag Can Be Bypassed
**Severity:** MEDIUM
**Location:** `app/core/deps.py:314-355`

**Finding:** `require_password_not_forced` is a separate dependency that must be explicitly added. Endpoints using only `CasbinAuth` won't check `password_reset_required`.

### 5.3 Medium Priority Issues

#### M1: Policy Duplication Across Migrations and Fallback
**Severity:** MEDIUM
**Location:** `main.py` + Alembic migrations

**Finding:** Default policies are defined in:
1. Alembic migrations (production)
2. `main.py` lifespan (fallback)
3. `policy_templates.py` (templates)

**Risk:** Inconsistency between sources could lead to unexpected behavior.

#### M2: Role Sync Has Race Condition Window
**Severity:** MEDIUM
**Location:** `deps.py:248-278`

**Finding:** DB role is synced from Casbin during `get_current_user`. Between Casbin update and next login, the user operates with old DB role.

#### M3: Hardcoded System Roles
**Severity:** LOW
**Location:** `role_service.py:202`

**Finding:** System roles are hardcoded:
```python
SYSTEM_ROLES = {"role:admin", "role:manager", "role:officer", "role:user"}
```

This is duplicated in `policy_templates.py`. Single source of truth should be established.

### 5.4 Low Priority Issues

#### L1: Verbose Policy Definitions
**Severity:** LOW
**Location:** Multiple migrations

**Finding:** Same permissions are duplicated for each role (e.g., notifications for user, officer, manager). Could use role inheritance instead.

#### L2: Inconsistent Resource Naming
**Severity:** LOW
**Location:** Policy patterns

**Finding:** Some patterns use `{lead_id}`, others use `*`. Naming convention should be standardized.

#### L3: No Domain/Tenant Support
**Severity:** INFO
**Location:** Model configuration

**Finding:** The model uses simple `(sub, obj, act)` without domain. Multi-tenancy would require model changes.

---

## 6. Summary Tables

### 6.1 Role × Resource × Action Matrix

| Resource | admin | manager | officer | user |
|----------|-------|---------|---------|------|
| /api/admin/* | FULL | - | - | - |
| /api/admin/users | FULL | FULL | - | - |
| /api/leads (list) | READ | READ | READ* | - |
| /api/leads/{id} (detail) | FULL | FULL | READ* | - |
| /api/leads/{id}/consultations | FULL | FULL | CREATE* | - |
| /api/leads/{id}/action | FULL | FULL | CREATE* | - |
| /api/officer/* | FULL | - | READ/CREATE | - |
| /api/admissions/* | FULL | - | FULL* | - |
| /api/profile | FULL | READ/UPDATE | READ/UPDATE | READ/UPDATE |
| /api/notifications | FULL | FULL | FULL | FULL |
| /api/pipeline/* | FULL | - | READ | - |
| /api/organization-units | FULL | READ | READ | READ |
| /api/programs | FULL | READ | READ | READ |

**Legend:**
- FULL = All CRUD operations
- READ = GET only
- CREATE = POST only
- READ/UPDATE = GET and PUT
- \* = Subject to IDOR ownership checks

### 6.2 Security Control Summary

| Control | Status | Notes |
|---------|--------|-------|
| Authentication | IMPLEMENTED | JWT with httpOnly cookies |
| Role-Based Access Control | IMPLEMENTED | Casbin RBAC |
| Ownership Verification (IDOR) | IMPLEMENTED | FastAPI dependencies |
| Rate Limiting | IMPLEMENTED | SlowAPI |
| Session Management | IMPLEMENTED | Redis + DB |
| Token Blacklisting | IMPLEMENTED | Redis |
| Audit Logging | IMPLEMENTED | UserActivityLog |
| Password Policies | PARTIAL | Basic validation |
| MFA | NOT IMPLEMENTED | - |

---

## 7. Recommendations

### 7.1 Immediate Actions (Security)

1. **Standardize Authorization Pattern**
   - Choose either Casbin-only OR role-based dependencies
   - If using both, ensure Casbin always runs first

2. **Add `USER` to UserRole Enum**
   ```python
   class UserRole(StrEnum):
       ADMIN = "admin"
       MANAGER = "manager"
       OFFICER = "officer"
       USER = "user"  # Add this
   ```

3. **Audit All Endpoints Without CasbinAuth**
   - Ensure intentional public endpoints are documented
   - Add authorization to any missing endpoints

### 7.2 Short-Term Improvements

4. **Consolidate Policy Sources**
   - Single source of truth for default policies
   - Remove fallback in `main.py` after confirming migrations run

5. **Use Role Inheritance**
   - Define base permissions on `role:user`
   - Have officer, manager inherit from user
   - Reduces policy duplication

6. **Add Integration Tests for Authorization**
   - Test each endpoint with all roles
   - Verify expected 403 responses

### 7.3 Long-Term Considerations

7. **Consider Domain-Based Policies**
   - For multi-tenant support
   - Requires model change to `(sub, dom, obj, act)`

8. **Implement Policy Versioning**
   - Track policy changes over time
   - Enable rollback capability

9. **Add MFA Support**
   - For admin users at minimum
   - Consider risk-based MFA triggers

---

## Appendix A: File Reference

| Purpose | File Path |
|---------|-----------|
| Casbin Model | `Backend_FastAPI/auth_model.conf` |
| Policy Templates | `Backend_FastAPI/app/casbin_config/policy_templates.py` |
| Casbin Service | `Backend_FastAPI/app/services/casbin_service.py` |
| Role Service | `Backend_FastAPI/app/services/role_service.py` |
| User Service | `Backend_FastAPI/app/services/user_service.py` |
| Auth Dependencies | `Backend_FastAPI/app/core/deps.py` |
| App Startup | `Backend_FastAPI/app/main.py` |
| Admin Roles Router | `Backend_FastAPI/app/routers/admin/roles.py` |
| Default Policies Migration | `Backend_FastAPI/alembic/versions/i4j5k6l7m8n9_*.py` |

## Appendix B: Critical Policy

The following policy MUST NOT be removed:

```
(role:admin, /*, .*)
```

Removing this policy will lock all administrators out of the system. The codebase includes protection against this via `CRITICAL_POLICIES` in `policy_templates.py`.

---

*End of Audit Report*
