---
trigger: always_on
---

# QLTS BACKEND ARCHITECTURE (V3.0)
> **STATUS: MANDATORY CORE RULES.**

## 1. META-RULES
*   **Security First**: Architecture enforces security, not developers.
*   **Dumb Router**: No logic, no auth checks.
*   **Smart Dependency**: Gatekeeper for Auth, RBAC, IDOR.
*   **Service Isolation**: Pure logic. No HTTP imports.
*   **Explicit Flow**: Router -> Service -> Repository.
*   **Transactions**: Router commits. Service flushes.

## 2. LAYERS

### 2.1. Router (Presentation)
**Forbidden**:
*   Logic (`if x > y`), Auth (`if user.role`), DB (`db.exec`).
*   Manual Repo instantiation.
*   `try...except` logic (except mapping).
*   Generic `except Exception` (BANNED).
*   Swallowing Domain Exceptions.

**Mandatory**:
*   Inject ALL deps (`Depends`).
*   `response_model` required.
*   Call `await db.commit()`.

**Example**:
```python
@router.post("/items", response_model=ItemRes)
async def create(in: ItemCreate, user: User=Depends(get_active_user), db: Sess=Depends(get_db)):
    item, callback = await service.create(db, in, user)
    await db.commit()
    await callback()
    return item
```

### 2.2. Dependency (Security Gateway)
**4-Stage Defense**:
1.  **Identity**: Validate JWT, Check Blacklist, Check `is_active`.
2.  **Gatekeeping**: `require_roles('admin')`.
3.  **Resource Access (IDOR)**: Fetch resource + Check Owner. **RAISE 404** (not 403) on fail.
4.  **Context Filter**: Sanitize `active_only` based on role.

**IDOR Code**:
```python
async def get_lead(id: int, user: User=Depends(get_user), db=Depends(get_db)):
    lead = await repo.get(id)
    if not lead or (user.role != 'admin' and lead.owner != user.id):
        raise ResourceNotFoundError() # FAKE 404
    return lead
```

### 2.3. Service (Logic)
**Rules**:
*   **Input**: Pydantic/Domain Object. **NEVER** `Request`/`Header`.
*   **Output**: Model/Tuple.
*   **DB**: Via Repo only. **NEVER** `db.commit()`. Use `flush`.
*   **Side Effects**: Return `async def callback()`.

**Pattern**:
```python
async def update(db, lead, status):
    if lead.status == 'closed': raise BusinessError()
    lead.status = status
    await db.flush()
    async def cb(): await email.send()
    return lead, cb
```

### 2.4. Repository (Data)
**Rules**:
*   Inherit `BaseRepository`.
*   **Session Slave**: Use provided session. NEVER open/close.
*   **Strict Eager Load**: `selectinload` MANDATORY.
*   **No Logic**: Return Data or `None` (No Exceptions).

## 3. STANDARDS

### 3.1. Naming
*   `routers/users.py`, `services/user_service.py`, `repos/user_repo.py`.

### 3.2. Exceptions (Service -> HTTP)
| Service | HTTP |
|---|---|
| `ResourceNotFoundError` | 404 |
| `DuplicateResourceError` | 409 |
| `BusinessRuleViolation` | 400 |
| `PermissionDeniedError` | 403 |
| `AuthenticationError` | 401 |

### 3.3. Typing
**Strict**: `def func(arg: Type) -> RetType:`

## 4. COMPLIANCE CHECKLISTS

### Router
[ ] `response_model`?
[ ] All deps via `Depends`?
[ ] Zero logic/SQL?
[ ] Calls `db.commit()`?
[ ] No generic `except`?

### Service
[ ] No `HTTPException`?
[ ] No `db.commit()`?
[ ] Returns callback?
[ ] Domain Exceptions only?

### Security
[ ] IDOR: Dependency checks ownership?
[ ] Leak: Raise 404 for forbidden?
[ ] Filter: Dependency sanitizes params?

## 5. ADDENDUM: STRICT RULES

### A. Transactions
*   **Default**: 1 Router -> 1 Service -> 1 Commit.
*   **Orchestration**: Orchestrator (Flow) calls Services (Logic). Router commits.
*   **Callback**: OK (Email, Log). banned (DB Write, Service Call).

### B. Taxonomy
*   **Domain Service**: 1 Entity, Rules.
*   **Orchestrator**: Flow only. No Rules.

### C. Anti-N+1 (Repo)
*   **List**: `selectinload` required.
*   **Count**: `func.count()`.
*   **Exists**: `exists()`.
*   **Raw SQL**: Repo only. >100k rows/Analytics only.

### D. Threat Model
*   **IDOR**: Dependency prevents increment guessing.
*   **Inference**: Always 404 prevents ID mapping.
*   **Escalation**: Context Filter prevents param tampering.

### E. Agent Hard Rules (YAML)
```yaml
ALWAYS:
  - Inject deps (User, DB, Repo) in Router.
  - Check perms in `deps.py`.
  - Raise Domain Exceptions in Service.
  - Call `db.commit()` in Router.
NEVER:
  - `if user.role == ...` in Router.
  - `db.commit()` in Service.
  - `HTTPException` in Service/Repo.
  - Return ORM Models without Schema.
  - Catch generic `Exception` in Router.
  - Import `Request` in Service.
```

## 6. ENFORCEMENT
*   **Code Review**: Reject non-compliant code.
*   **Static Analysis**: CI checks.
*   **Motto**: "It runs" is not an excuse.

---
**END OF RULES**
