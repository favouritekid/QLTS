# Repository Pattern Guide

> **Created:** 2025-12-11  
> **Version:** 1.0  
> **Status:** Active

---

## 1. Overview

This guide establishes coding standards for Repository Pattern usage in the QLTS Backend.

### Why Repository Pattern?

| Without Repository | With Repository |
|--------------------|-----------------|
| Service imports `select`, `func` from SQLAlchemy | Service only imports Repository class |
| Query logic mixed with business logic | Clear separation of concerns |
| Hard to test (need real database) | Easy to mock repositories |
| Duplicate query patterns across services | Centralized, reusable queries |

---

## 2. Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│                       ROUTER LAYER                          │
│  - HTTP request/response handling                           │
│  - Dependency injection (PermissionDep, LeadAccessDep)      │
│  - Transaction commit: await db.commit()                    │
│  - Post-commit callbacks: await callback()                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      SERVICE LAYER                          │
│  - 100% business logic                                      │
│  - NO SQLAlchemy imports (select, func, etc.)               │
│  - NO db.commit() calls                                     │
│  - NO HTTPException imports                                 │
│  - Uses Repository for data access                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    REPOSITORY LAYER                         │
│  - All SQLAlchemy query logic                               │
│  - Eager loading (selectinload, joinedload)                 │
│  - Filtering, pagination, sorting                           │
│  - Uses db.flush() (NOT commit)                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       MODEL LAYER                           │
│  - SQLAlchemy ORM models                                    │
│  - Relationships, indexes, constraints                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Repository Structure

### 3.1 Base Repository

All repositories inherit from `BaseRepository` which provides:

```python
from app.repositories.base import BaseRepository

class LeadRepository(BaseRepository[models.Lead]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, models.Lead)
```

**Built-in methods:**

| Method | Description |
|--------|-------------|
| `get_by_id(id)` | Get by primary key |
| `get_all(skip, limit)` | Paginated list |
| `count(where_clause)` | Count with optional filter |
| `create(obj_in)` | Insert new record |
| `update(db_obj, obj_in)` | Update existing |
| `delete(db_obj)` | Hard delete |
| `soft_delete(db_obj)` | Set deleted_at timestamp |
| `get_with_relations(id, relations)` | Get with eager loading |

### 3.2 Custom Repository Methods

Add domain-specific methods:

```python
class LeadRepository(BaseRepository[models.Lead]):
    
    async def get_by_id_full(
        self, 
        lead_id: int,
        include_deleted: bool = False
    ) -> Optional[models.Lead]:
        """
        Get lead with ALL relationships for Detail/Timeline view.
        """
        query = (
            select(self.model)
            .options(
                selectinload(models.Lead.offering),
                selectinload(models.Lead.consultations),
                # ... all relations
            )
            .where(self.model.id == lead_id)
        )
        
        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))
        
        result = await self.db.execute(query)
        return result.scalars().first()
```

---

## 4. Usage Pattern

### ❌ WRONG (Service queries directly)

```python
# lead_service.py - WRONG!
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def get_lead_by_id(db: AsyncSession, lead_id: int):
    query = (
        select(models.Lead)
        .options(selectinload(models.Lead.offering))
        .where(models.Lead.id == lead_id)
    )
    result = await db.execute(query)  # ❌ Direct query
    return result.scalar_one_or_none()
```

### ✅ CORRECT (Service uses Repository)

```python
# lead_service.py - CORRECT!
from app.repositories import LeadRepository

async def get_lead_by_id(db: AsyncSession, lead_id: int):
    repo = LeadRepository(db)
    lead = await repo.get_by_id_full(lead_id)  # ✅ Via repository
    if not lead:
        raise ResourceNotFoundError(f"Lead {lead_id} not found")
    return lead
```

---

## 5. When to Create New Repository Methods

| Scenario | Action |
|----------|--------|
| Query used in multiple services | Create repository method |
| Complex query with 3+ joins | Create repository method |
| Query with business-specific filtering | Create repository method |
| Simple `get_by_id` | Use `BaseRepository.get_by_id()` |
| Need eager loading | Use `get_with_relations()` or create custom |

---

## 6. Naming Conventions

### Repository Method Names

| Pattern | Example | Use Case |
|---------|---------|----------|
| `get_by_{field}` | `get_by_email()` | Single field lookup |
| `get_{adjective}` | `get_filtered()` | List with filters |
| `get_{noun}_for_{context}` | `get_leads_for_officer()` | Context-specific query |
| `count_by_{field}` | `count_by_status()` | Aggregation |
| `search_{entity}` | `search_users()` | Full-text search |
| `get_{entity}_with_{relations}` | `get_by_id_full()` | Eager loading |

### File Structure

```
app/repositories/
├── __init__.py          # Export all repositories
├── base.py              # BaseRepository
├── lead_repository.py   # LeadRepository
├── user_repository.py   # UserRepository
└── organization_repository.py
```

---

## 7. Testing

### Mock Repository in Tests

```python
from unittest.mock import AsyncMock, MagicMock

async def test_get_lead():
    # Mock repository
    mock_repo = MagicMock()
    mock_repo.get_by_id_full = AsyncMock(return_value=fake_lead)
    
    # Inject mock (via dependency override or direct)
    with patch('app.services.lead_service.LeadRepository', return_value=mock_repo):
        result = await get_lead_by_id(db, 1)
        assert result == fake_lead
```

---

## 8. Migration Checklist

When refactoring service to use repository:

- [ ] Create repository method with proper eager loading
- [ ] Update service to import and use repository
- [ ] Remove `from sqlalchemy import select` from service
- [ ] Ensure service does NOT call `db.execute()` directly
- [ ] Update tests to use repository mocks
- [ ] Verify no performance regression (response time)

---

## 9. Quick Reference

### Imports

```python
# REPOSITORY (allowed)
from sqlalchemy import select, func, or_, case
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession

# SERVICE (NOT allowed - use repository instead)
# from sqlalchemy import select  ❌
# from sqlalchemy.orm import selectinload  ❌
```

### PR Review Checklist

```markdown
## Architecture Compliance
- [ ] Service does NOT import `select` from SQLAlchemy
- [ ] Service does NOT import `HTTPException`
- [ ] Service does NOT call `db.commit()`
- [ ] Service uses Repository for data access
- [ ] Repository uses `db.flush()` (not commit)
```

---

*Guide maintained by Architecture Team*
