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

## Running Tests (MANDATORY PROCEDURE)

Development runs inside Docker. The production image does NOT include test dependencies or test files.

### Before running tests -- install test deps (once per container lifecycle)

```bash
# Check if pytest is available, install if missing
docker compose exec backend python -c "import pytest" 2>/dev/null || \
  docker compose exec backend pip install -r requirements-dev.txt
```

**Why**: `Dockerfile` only installs `requirements.txt`. Test deps (`pytest`, `pytest-asyncio`, `httpx`, etc.) live in `requirements-dev.txt` and must be installed manually into the running container. They are **ephemeral** -- lost on container restart/recreate.

### Run tests

```bash
# All tests
docker compose exec backend pytest tests/ -v

# Specific file
docker compose exec backend pytest tests/api/test_leads.py -v

# By marker
docker compose exec backend pytest -m unit
docker compose exec backend pytest -m integration
docker compose exec backend pytest -m security

# Single test function
docker compose exec backend pytest tests/api/test_leads.py::test_create_lead -v
```

### Key facts
- `tests/` is in `.dockerignore` (excluded from image) but available in dev via bind mount (`./Backend_FastAPI:/app`)
- `pytest.ini` configures: `asyncio_mode = auto`, strict markers, `-v --tb=short`
- NEVER add test deps to `requirements.txt` -- production image must stay clean
- After `docker compose down && up`, reinstall test deps

---

## Admission Workflows (Source of Truth)

`AdmissionProfile` is the **sole source of truth** for admission/enrollment workflows.
The legacy `Application` model, router, service, and repository have been removed.

For admission tasks, ONLY use:
- `app/routers/admissions.py`
- `app/services/admission_service.py`
- `app/models/admission.py` (`AdmissionProfile`)

Event namespace `APPLICATION_*` and payload key `application_id` are retained
for backward compatibility — they refer to `AdmissionProfile.id`, not the removed model.
Do NOT rename these. See `APPLICATION_LEGACY_CLEANUP.md` for full context.

### Mutation response contract

Any service function that returns an `AdmissionProfile` destined for an API
response with computed fields **must** call `_populate_response_fields()`
after `await db.flush()` and before returning. This ensures `permissions`,
`available_actions`, `step_status`, `eligibility_status`, `validation_errors`,
`completion_percent`, `assigned_officer_name`, and `assigned_reviewer_name`
are populated and consistent with what a subsequent `GET` response would
return. Without this call, computed fields silently fall back to schema
defaults (`permissions={}`, `eligibility_status="pending"`, etc.) and any
client that trusts the mutation response will see broken state.

The helper handles `current_user=None` (system callbacks) by skipping
silently. For functions that delegate to `reload_profile_with_lead`, pass
`documents=profile.documents` to reuse the eager-loaded list and avoid a
redundant query. Mutation queries that return their own profile must use
the nested eager-load pattern:
```python
.options(
    selectinload(models.AdmissionProfile.lead)
    .selectinload(models.Lead.assigned_officer),
    selectinload(models.AdmissionProfile.assigned_reviewer),
)
```
Otherwise denormalized name fields will be silently `null`.

---

## Common Commands

```bash
# Migration
docker compose exec backend alembic revision --autogenerate -m "description"
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1

# Start server (dev mode -- auto-configured by docker-compose.override.yml)
docker compose up -d

# Logs
docker compose logs backend -f --tail=50

# Code formatting (inside container)
docker compose exec backend black .
docker compose exec backend isort .
docker compose exec backend flake8 .
```

