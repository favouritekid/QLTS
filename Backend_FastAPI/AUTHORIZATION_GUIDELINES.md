# AUTHORIZATION GUIDELINES (Universal Standard)

> **Version:** 1.0
> **Status:** MANDATORY
> **Scope:** All FastAPI Backend Projects
>
> TL;DR: *Authorization = 3 layers. No inline checks. No bypass. No guessing.*

---

## 1. THE 3-LAYER MODEL

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: AUTHENTICATION (WHO are you?)                 │
│  → JWT validation, session check, active status         │
├─────────────────────────────────────────────────────────┤
│  Layer 2: AUTHORIZATION (WHAT can you do?)              │
│  → RBAC/Casbin check, role validation                   │
├─────────────────────────────────────────────────────────┤
│  Layer 3: RESOURCE ACCESS (WHAT can you touch?)         │
│  → IDOR protection, ownership verification              │
└─────────────────────────────────────────────────────────┘
```

**Rule:** Every endpoint MUST pass through required layers. Missing = security bug.

---

## 2. AUTHENTICATION LAYER

### 2.1 Standard Dependencies

| Dependency | Allows Inactive? | Use Case |
|------------|------------------|----------|
| `get_current_user` | Yes | Logout, refresh, security settings |
| `get_current_active_user` | No | **DEFAULT for 90% business APIs** |
| `require_password_not_forced` | No | Sensitive ops (change email, reset) |

### 2.2 Code Pattern

```python
# Default for business endpoints
current_user: models.User = Depends(get_current_active_user)

# Special cases (auth flows)
current_user: models.User = Depends(get_current_user)
```

### 2.3 Anti-Patterns

- Using `get_current_user` for business APIs
- Manual `if user.is_active` check in router

---

## 3. AUTHORIZATION LAYER

### 3.1 Two Strategies

#### A. Casbin RBAC (Dynamic) - DEFAULT

```python
check_permission  # Checks (user, path, method)
```

Use for: Admin panels, pipelines, profiles, notifications, monitoring.

#### B. Role-Based (Static) - When Needed

```python
require_admin               # role == "admin"
require_admin_or_manager    # role in ["admin", "manager"]
require_any_staff           # role in ["admin", "manager", "officer"]
```

Use for: Simple internal APIs, KPI config, system settings.

### 3.2 Anti-Patterns

- `if user.role == "admin"` in router body
- Bypassing Casbin with if/else
- Creating local role check functions

---

## 4. RESOURCE ACCESS LAYER (IDOR)

### 4.1 Pattern

```python
# Dependency fetches + validates ownership
lead: models.Lead = Depends(get_lead_for_user)
profile: models.AdmissionProfile = Depends(get_admission_for_manager)
```

### 4.2 Rules

- Resource fetch = MUST use dependency
- Return 404 for unauthorized (not 403)
- Validation logic in `deps.py`, not router

### 4.3 Anti-Patterns

- `db.get(Model, id)` in router
- Manual ownership check in router
- Returning 403 for missing/unauthorized resource

---

## 5. CONTEXT FILTERING

When query params need role-based sanitization:

```python
# Officer requests `?active_only=false` → Dependency forces `true`
scope: ScopeParams = Depends(get_dashboard_scope)
filters: FilterParams = Depends(get_lead_list_filter)
```

Use for: List endpoints with role-dependent visibility.

---

## 6. STANDARD COMPOSITIONS

| Use Case | Dependencies |
|----------|--------------|
| Business API | `get_current_active_user` + `check_permission` |
| Admin-only | `get_current_active_user` + `require_admin` |
| With IDOR | `get_current_active_user` + `check_permission` + `get_{resource}_for_user` |
| Auth flows | `get_current_user` only |
| Scoped lists | `get_current_active_user` + `check_permission` + `get_{scope}_filter` |

---

## 7. NAMING CONVENTION

| Prefix | Meaning | Example |
|--------|---------|---------|
| `get_` | Fetch + validate | `get_lead_for_user` |
| `require_` | Condition check | `require_admin` |
| `check_` | Complex validator | `check_permission` |

Do NOT create: `*Required`, `*Dep` local aliases in routers.

---

## 8. BACKGROUND JOBS & INTERNAL SERVICES

Jobs bypass HTTP layer → No deps.py.

Instead:
- Service validates input params
- Repository enforces data isolation
- Logging includes context (user_id, job_id)
- Use `auto_commit=True` flag sparingly

---

## 9. HARD RULES (YAML)

```yaml
ALWAYS:
  - Use get_current_active_user for business APIs
  - Use check_permission or require_* for authorization
  - Use get_{resource}_for_user for IDOR protection
  - Return 404 for unauthorized resources

NEVER:
  - Write role checks in router body
  - Use get_current_user for business APIs
  - Fetch resources with db.get() in router
  - Return 403 for missing/unauthorized resources
  - Create local auth dependencies in routers
```

---

## 10. PR REVIEW CHECKLIST

Before approving any PR:

- [ ] Uses `get_current_active_user` (not `get_current_user`)?
- [ ] Has authorization layer (`check_permission` or `require_*`)?
- [ ] No Casbin bypass with if/else?
- [ ] No IDOR risk (uses resource access dependency)?
- [ ] No inline role check in router?

**Missing any = REJECT PR.**

---

## 11. DEPENDENCY QUICK REFERENCE

```python
# ============ AUTHENTICATION ============
from app.core.deps import (
    get_current_user,           # Special cases only
    get_current_active_user,    # DEFAULT
    require_password_not_forced, # Sensitive ops
)

# ============ AUTHORIZATION ============
from app.core.deps import (
    check_permission,           # Casbin RBAC
    require_admin,              # Admin only
    require_admin_or_manager,   # Admin/Manager
)

# ============ RESOURCE ACCESS ============
from app.core.deps import (
    get_lead_for_user,
    get_notification_template_for_admin,
    get_notification_rule_for_admin,
    get_officer_dashboard_scope,
)
```

---

**END OF GUIDELINES**

> *Authorization is not about making code work.*
> *It's about sleeping well, passing audits, and not burning production.*
