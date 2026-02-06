# Backend (FastAPI) Guidelines

## Core Documentation
- **Master Architecture**: `MASTER_ARCHITECTURE.md`
- **Authorization**: `AUTHORIZATION_GUIDELINES.md`

## 🚨 MANDATORY ARCHITECTURE RULES
1.  **Smart Dependency, Dumb Router**:
    - **Router**: Input/Output ONLY. No `if/else` logic. No `db.execute`.
    - **Dependencies**: ALL auth, permissions (RBAC), and IDOR checks in `app/core/deps.py`.
    - **Transaction**: Router calls `await db.commit()`.

2.  **Service Isolation**:
    - Services **NEVER** import `fastapi` (`Request`, `Response`, `HTTPException`).
    - Input: Pydantic models. Output: Tuple `(result, post_commit_callback)`.
    - Raises `DomainExceptions`, never `HTTPException`.

3.  **Security & Auth**:
    - **IDOR**: Use `get_[resource]_for_user` dependency. Raise **404** (not 403).
    - **RBAC**: Use `check_permission` or `require_admin/require_admin_or_manager`.
    - **Auth**: Use `get_current_active_user` for ALL business APIs.

4.  **Database**:
    - Use `selectinload` for relationships (Anti-N+1).
    - No direct SQL in Routers. Use Repository pattern.

---

## 📦 Quick Imports
```python
# Authentication & Authorization (deps.py)
from app.core.deps import (
    get_current_active_user,      # DEFAULT for business APIs
    get_current_user,             # Auth flows only (logout, refresh)
    check_permission,             # Casbin RBAC
    require_admin,                # Admin-only endpoints
    require_admin_or_manager,     # Admin/Manager endpoints
)

# Domain Exceptions (exceptions.py)
from app.utils.exceptions import (
    ResourceNotFoundError,        # 404 - missing or IDOR fail
    DuplicateResourceError,       # 409 - unique constraint
    BusinessRuleViolation,        # 400 - invalid state transition
    ValidationError,              # 400 - data validation
    ConflictError,                # 409 - optimistic locking
)
```

---

## � File Conventions
| Type | Location | Naming |
|------|----------|--------|
| Routers | `app/routers/` | `plural.py` (e.g., `leads.py`) |
| Services | `app/services/` | `singular_service.py` (e.g., `lead_service.py`) |
| Repos | `app/repositories/` | `singular_repository.py` |
| Schemas | `app/schemas/` | `module.py` (e.g., `lead.py`) |
| Models | `app/models/` | `singular.py` |

---

## ❌ NEVER DO (Anti-Patterns)
```python
# ❌ Logic in Router
@router.post("/leads")
async def create(lead_in, user = Depends(get_current_active_user)):
    if user.role != "admin":  # ❌ WRONG - move to deps.py
        raise HTTPException(403)

# ❌ HTTPException in Service
class LeadService:
    async def create(self, data):
        if exists:
            raise HTTPException(409)  # ❌ WRONG - use DuplicateResourceError

# ❌ Commit in Service
async def update_lead(self, db, lead):
    lead.status = "updated"
    await db.commit()  # ❌ WRONG - Router commits, Service flushes

# ❌ Return 403 for IDOR
async def get_lead_for_user(lead_id, user):
    if lead.owner_id != user.id:
        raise HTTPException(403)  # ❌ WRONG - should be 404
```

---

## �🛠️ Common Commands (WSL/Bash)
- **Run Tests**: `pytest tests/`
- **Run Single Test**: `pytest tests/path/to/test.py -v`
- **Migration (New)**: `alembic revision --autogenerate -m "message"`
- **Migration (Up)**: `alembic upgrade head`
- **Start Server**: `uvicorn app.main:app --reload`

