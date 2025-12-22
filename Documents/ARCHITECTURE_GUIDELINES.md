# Architecture Guidelines

> **BẮT BUỘC** - Tất cả module mới phải tuân thủ 100% các quy tắc trong document này.

---

## Tổng quan kiến trúc

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Router    │ ──▶ │   Service   │ ──▶ │  Repository  │ ──▶ │   Models    │
│ (FastAPI)   │     │ (Business)  │     │   (Data)     │     │ (SQLAlchemy)│
└─────────────┘     └─────────────┘     └──────────────┘     └─────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
   HTTP/JSON          Domain Logic         SQL Queries
   Validation         Exceptions           DB Access
   Auth/RBAC          No HTTP deps         CRUD ops
```

---

## A. Router Rules

### ✅ Router PHẢI

```python
# ✅ ĐÚNG: Router chỉ điều phối, không có logic nghiệp vụ
@router.post("/users", response_model=schemas.User)
async def create_user(
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_admin)
):
    # 1. Gọi service
    user, post_commit = await user_service.create_user(db, user_in)
    
    # 2. Router commit transaction
    await db.commit()
    
    # 3. Execute post-commit callback
    await post_commit()
    
    # 4. Return response
    return user
```

### ❌ Router KHÔNG ĐƯỢC

```python
# ❌ SAI: Logic nghiệp vụ trong router
@router.post("/users")
async def create_user(user_in: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    # ❌ Logic check trong router
    if await db.scalar(select(User).where(User.email == user_in.email)):
        raise HTTPException(400, "Email exists")
    
    # ❌ Tạo object trong router
    user = models.User(**user_in.model_dump())
    db.add(user)
    await db.commit()
    return user
```

### Checklist Router

- [ ] Sử dụng `response_model`
- [ ] Chỉ gọi service functions
- [ ] Tự commit transaction (`await db.commit()`)
- [ ] Gọi post-commit callback nếu có
- [ ] Convert domain exceptions → HTTP responses

---

## B. Service Rules

### ✅ Service PHẢI

```python
# ✅ ĐÚNG: Service pattern chuẩn
from typing import Tuple, Callable
from app.repositories import UserRepository
from app.utils.exceptions import ResourceNotFoundError, DuplicateResourceError

async def create_user(
    db: AsyncSession,
    user_in: schemas.UserCreate
) -> Tuple[models.User, Callable]:
    """
    Create a new user.
    
    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    
    Returns:
        Tuple of (user, post_commit_callback)
        
    Raises:
        DuplicateResourceError: If email already exists
    """
    repo = UserRepository(db)
    
    # Check duplicate via repository
    if await repo.get_by_email(user_in.email):
        raise DuplicateResourceError(detail=f"Email {user_in.email} already exists")
    
    # Create via repository
    user = await repo.create(user_in)
    
    # Flush (NOT commit)
    await db.flush()
    await db.refresh(user)
    
    # Post-commit callback for side effects
    async def _post_commit():
        log.info("User created", user_id=user.id)
        # Send welcome email, invalidate cache, etc.
    
    return user, _post_commit
```

### ❌ Service KHÔNG ĐƯỢC

```python
# ❌ SAI: Các vi phạm phổ biến

from fastapi import HTTPException  # ❌ KHÔNG import HTTPException

async def create_user(db: AsyncSession, user_in: schemas.UserCreate):
    # ❌ Query trực tiếp thay vì dùng Repository
    existing = await db.scalar(select(User).where(User.email == user_in.email))
    
    # ❌ Raise HTTPException trong service
    if existing:
        raise HTTPException(status_code=400, detail="Email exists")
    
    user = models.User(**user_in.model_dump())
    db.add(user)
    
    # ❌ Commit trong service
    await db.commit()
    
    return user
```

### Checklist Service

- [ ] KHÔNG import `HTTPException`
- [ ] KHÔNG gọi `await db.commit()`
- [ ] Dùng Repository cho tất cả DB queries
- [ ] Raise domain exceptions (`ResourceNotFoundError`, `DuplicateResourceError`, etc.)
- [ ] Return `Tuple[result, post_commit_callback]` cho write operations
- [ ] Docstring ghi rõ "Router must call db.commit()"

---

## C. Repository Rules

### ✅ Repository Pattern

```python
# app/repositories/user_repository.py

from app.repositories.base import BaseRepository
from app import models

class UserRepository(BaseRepository[models.User]):
    """Repository for User entity."""
    
    model = models.User
    
    async def get_by_email(self, email: str) -> Optional[models.User]:
        """Get user by email."""
        result = await self.db.execute(
            select(self.model).where(self.model.email == email)
        )
        return result.scalar_one_or_none()
    
    async def get_active_officers(self, unit_id: int) -> List[models.User]:
        """Get active officers for a unit."""
        result = await self.db.execute(
            select(self.model)
            .where(
                self.model.organization_unit_id == unit_id,
                self.model.is_active == True,
                self.model.role.in_(["officer", "manager"])
            )
            .options(selectinload(self.model.skills))  # Eager load
        )
        return list(result.scalars().all())
```

### Checklist Repository

- [ ] Inherit từ `BaseRepository`
- [ ] Mỗi method làm 1 việc rõ ràng
- [ ] Dùng `selectinload`/`joinedload` cho relationships
- [ ] Return models hoặc None, không raise exceptions
- [ ] Naming: `get_*`, `list_*`, `create_*`, `update_*`, `delete_*`

---

## D. Exception Handling

### Domain Exceptions (Service layer)

```python
# app/utils/exceptions.py

class ResourceNotFoundError(Exception):
    """Resource not found in database."""
    def __init__(self, detail: str = "Resource not found"):
        self.detail = detail

class DuplicateResourceError(Exception):
    """Duplicate resource violation."""
    def __init__(self, detail: str = "Resource already exists"):
        self.detail = detail

class AuthorizationError(Exception):
    """User not authorized for this action."""
    def __init__(self, detail: str = "Not authorized"):
        self.detail = detail

class BadRequest(Exception):
    """Invalid request data."""
    def __init__(self, detail: str = "Bad request"):
        self.detail = detail
```

### Exception Mapping (Router layer)

```python
# Router converts domain exceptions to HTTP
@router.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    try:
        user = await user_service.get_user(db, user_id)
        return user
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.detail)
    except AuthorizationError as e:
        raise HTTPException(status_code=403, detail=e.detail)
```

---

## E. Transaction Pattern

### Standard Write Operation

```python
# Router
@router.post("/items", response_model=schemas.Item)
async def create_item(item_in: schemas.ItemCreate, db: AsyncSession = Depends(get_db)):
    # 1. Service returns (result, callback)
    item, post_commit = await item_service.create_item(db, item_in)
    
    # 2. Router commits
    await db.commit()
    
    # 3. Execute callback (cache invalidation, notifications, etc.)
    await post_commit()
    
    return item

# Service
async def create_item(db: AsyncSession, item_in: schemas.ItemCreate) -> Tuple[models.Item, Callable]:
    repo = ItemRepository(db)
    item = await repo.create(item_in)
    
    await db.flush()  # Write without commit
    await db.refresh(item)
    
    async def _post_commit():
        await invalidate_cache(f"items:{item.id}")
        log.info("Item created", item_id=item.id)
    
    return item, _post_commit
```

### Read-Only Operation

```python
# Không cần post_commit callback
async def get_items(db: AsyncSession, filters: dict) -> List[models.Item]:
    repo = ItemRepository(db)
    return await repo.list_with_filters(filters)
```

---

## F. Security Rules

### RBAC với Casbin

```python
# Router với permission check
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    _: bool = Depends(require_permission("users", "delete"))  # Casbin check
):
    ...
```

### IDOR Protection

```python
# Service phải verify ownership
async def update_lead(
    db: AsyncSession,
    lead_id: int,
    lead_in: schemas.LeadUpdate,
    current_user: models.User  # Pass current user to service
) -> Tuple[models.Lead, Callable]:
    repo = LeadRepository(db)
    lead = await repo.get(lead_id)
    
    if not lead:
        raise ResourceNotFoundError(f"Lead {lead_id} not found")
    
    # IDOR check: verify user has access to this lead
    if not await can_access_lead(current_user, lead):
        raise AuthorizationError("You don't have access to this lead")
    
    # Proceed with update
    ...
```

---

## G. File Structure cho Module Mới

```
app/
├── routers/
│   └── new_feature.py          # HTTP endpoints
├── services/
│   └── new_feature_service.py  # Business logic
├── repositories/
│   └── new_feature_repository.py  # Data access
├── models/
│   └── new_feature.py          # SQLAlchemy models
└── schemas/
    └── new_feature.py          # Pydantic schemas
```

---

## H. Checklist cho Code Review

### Router Review
- [ ] Không có `select()`, `db.execute()`, `db.scalar()` trực tiếp
- [ ] Có `response_model`
- [ ] Gọi `await db.commit()` sau service call
- [ ] Gọi `await post_commit()` nếu có

### Service Review
- [ ] Không import `HTTPException`
- [ ] Không gọi `db.commit()`
- [ ] Dùng Repository cho queries
- [ ] Raise domain exceptions
- [ ] Return tuple cho write operations
- [ ] Có docstring với "Router must call db.commit()"

### Repository Review
- [ ] Inherit `BaseRepository`
- [ ] Eager loading với `selectinload`/`joinedload`
- [ ] Không raise exceptions (return None)

---

## I. Exceptions (Ngoại lệ được chấp nhận)

Các trường hợp sau được phép vi phạm Pattern A:

| Exception | File | Lý do |
|-----------|------|-------|
| Monitoring endpoints | `monitoring.py` | Cần query trực tiếp cho health checks |
| Celery background jobs | `*_tasks.py` | Không có router, job tự commit |
| Internal utilities | `status_helper.py` | Quá đơn giản để tách repository |

---

## J. Migration Path cho Code Cũ

Khi touch code cũ không tuân thủ:

1. **Bug fix nhỏ** → Không cần refactor toàn bộ
2. **Feature mới trong module cũ** → Refactor phần liên quan
3. **Major rewrite** → Refactor theo Pattern A

---

*Last updated: 2025-12-21*

## K. Notification Module Compliance

Các module notification sau đã được migrate sang Pattern A:

| Repository | Service | Status |
|------------|---------|--------|
| `NotificationRepository` | `notification_service.py` | ✅ Done |
| `NotificationRuleRepository` | `notification_rule_crud_service.py` | ✅ Done |
| `NotificationTemplateRepository` | `notification_template_service.py` | ✅ Done |
| `NotificationPreferenceRepository` | `notification_preference_service.py` | ✅ Done |

Chạy test:
wsl bash -c "cd /mnt/d/QLTS/Backend_FastAPI && source venv/bin/activate && pytest tests/integration/api/auth/ -v --tb=short 2>&1 | tail -50"