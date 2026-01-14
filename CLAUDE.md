# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**QLTS** (Quản Lý Tuyển Sinh) is a comprehensive Educational Admission Management System for managing student admissions workflows in Vietnamese educational institutions. The system handles:

- **Lead Management**: Prospective student tracking through pipeline states
- **Admission Profiles**: Complete enrollment applications with document requirements and validation
- **Admission Paths**: Configurable pathways combining academic programs, admission methods, and document requirements
- **Notifications**: Dynamic rule-based notification system for applicants and officers
- **KPI Tracking**: Admission metrics and performance monitoring

---

## Technology Stack

### Backend
- **Framework**: FastAPI (Python 3.12)
- **Database**: PostgreSQL (production), SQLite (testing)
- **ORM**: SQLAlchemy 2.0 with asyncpg driver
- **Authentication**: JWT tokens with Redis-backed blacklist
- **Authorization**: Casbin RBAC with dynamic policy enforcement
- **Background Jobs**: Celery + Redis for async tasks
- **Migrations**: Alembic
- **Testing**: Pytest with asyncio support

### Frontend
- **Framework**: Next.js 16 with App Router
- **Language**: TypeScript
- **UI**: React 19 + Tailwind CSS + Radix UI
- **State Management**: React Query (server state), Zustand (UI state)
- **Validation**: Zod schemas mirroring backend Pydantic models
- **Real-time**: Socket.IO for live updates
- **Testing**: Vitest (unit), Playwright (E2E)

---

## Architecture Philosophy

### Core Principles

1. **Security by Design**: Architecture enforces security at the framework level, not by developer discipline
2. **Thin Client Philosophy**: Frontend is presentation-only; backend is source of truth for all business logic
3. **Layered Backend**: Smart Dependencies (security gateway), Dumb Routers (HTTP translation), Pure Services (business logic), Repositories (data access)
4. **Explicit Data Flow**: Data flows DOWN (Router → Service → Repository), Errors flow UP (Exceptions)

### Backend Architecture (V3.0)

```
ROUTER (Dumb HTTP Translator)
  ↓ (Dependency Injection)
SECURITY GATEWAY (Permissions, IDOR, Context)
  ↓ (Business Logic)
SERVICE (Pure Python Logic)
  ↓ (Data Access)
REPOSITORY (SQLAlchemy ORM)
```

**Key Rules**:
- **Smart Dependencies, Dumb Routers**: ALL auth, authorization, and IDOR checks in `Backend_FastAPI/app/core/deps.py`
- **Service Isolation**: Services never import FastAPI (`Request`, `HTTPException`, etc.) - they are pure Python
- **Transaction Responsibility**: Router commits (`await db.commit()`), Service only flushes
- **Post-Commit Callbacks**: Services return `(result, async_callback)` for side effects after transaction

**Detailed Documentation**: See `Backend_FastAPI/MASTER_ARCHITECTURE.md` and `Backend_FastAPI/CLAUDE.md`

### Frontend Architecture (V3.0)

**Thin Client Philosophy**:
- NO business logic in frontend (no eligibility calculations, scoring, workflow transitions)
- Display exactly what backend returns (trust `status`, `can_edit`, `available_actions`)
- Control visibility via API permission flags, NOT `user.role` checks
- Zod schemas strictly mirror Backend Pydantic models

**State Classification**:
- **Server State**: React Query (leads, profiles, configurations)
- **UI State**: Zustand (sidebar, modals) - NEVER cache server state here
- **URL State**: Next.js router (filters, pagination)
- **Form State**: React Hook Form (draft inputs)

**Detailed Documentation**: See `frontend/FRONTEND_ARCHITECTURE_V3.md` and `frontend/CLAUDE.md`

---

## Directory Structure

```
Backend_FastAPI/
├── app/
│   ├── core/              # deps.py (dependency injection), config, events
│   ├── routers/           # HTTP endpoints (dumb coordinators)
│   ├── services/          # Business logic (pure Python)
│   ├── repositories/      # Data access layer
│   ├── models/            # SQLAlchemy ORM models
│   ├── schemas/           # Pydantic validation models
│   ├── security/          # JWT, OAuth2, password hashing
│   ├── tasks/             # Celery async tasks
│   ├── middleware/        # Exception handlers, logging
│   └── casbin_config/     # RBAC policy templates
├── alembic/               # Database migrations
├── tests/                 # Pytest test suite
└── monitoring/            # Prometheus metrics

frontend/
├── src/
│   ├── app/               # Next.js App Router
│   │   ├── (auth)/        # Authentication routes
│   │   └── (dashboard)/   # Protected dashboard routes
│   ├── components/        # Reusable React components
│   ├── hooks/             # React Query + custom hooks
│   ├── lib/
│   │   ├── api/           # Axios-based API clients
│   │   ├── zod/           # Zod validation schemas
│   │   ├── stores/        # Zustand UI state stores
│   │   └── socket/        # Socket.IO real-time updates
│   └── types/             # TypeScript type definitions
└── tests/                 # Vitest + Playwright tests
```

---

## Common Development Commands

### Backend (run from `Backend_FastAPI/` directory)

```bash
# Start development server
uvicorn app.main:app --reload

# Run all tests
pytest tests/

# Run specific test file
pytest tests/api/test_leads.py -v

# Run tests by marker
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
pytest -m security      # Security tests only

# Database migrations
alembic revision --autogenerate -m "description"  # Create migration
alembic upgrade head                               # Apply migrations
alembic downgrade -1                               # Rollback one migration

# Code formatting & linting
black .                 # Format code
isort .                 # Sort imports
flake8 .                # Lint code
```

### Frontend (run from `frontend/` directory)

```bash
# Start development server
npm run dev

# Build for production
npm run build

# Type checking
npm run type-check

# Linting & formatting
npm run lint            # Check linting
npm run lint:fix        # Fix linting issues
npm run format          # Format code with Prettier

# Testing
npm run test            # Run Vitest tests
npm run test:ui         # Run tests with UI
npm run test:coverage   # Generate coverage report
npm run test:watch      # Watch mode

# E2E Testing
npm run test:e2e        # Run Playwright tests
npm run test:e2e:ui     # Run with Playwright UI
npm run test:e2e:debug  # Debug mode
```

---

## Security & Authorization

### Authentication Flow

1. JWT tokens (15 min expiry, 30 day refresh)
2. Redis-backed logout blacklist
3. Active status check (`is_active` flag)
4. Trusted device tracking

### Authorization (Casbin RBAC)

**System Roles**: `admin`, `manager`, `officer`, `user`

**Policy Framework**:
- Templates defined in `Backend_FastAPI/app/casbin_config/policy_templates.py`
- Dynamic enforcement via Casbin adapter
- Policy versioning with drift detection
- Auto-sync in development mode

**Dependency Gates** (in `Backend_FastAPI/app/core/deps.py`):
- `get_current_active_user`: JWT + active check (DEFAULT for business APIs)
- `check_permission`: Casbin enforcement
- `require_admin`, `require_admin_or_manager`: Role-based static checks
- `get_[resource]_for_user`: IDOR protection (raises 404 on unauthorized, NOT 403)

### IDOR Protection

**CRITICAL**: When checking resource ownership, ALWAYS return 404 (not 403) to avoid leaking resource existence.

```python
# ✅ CORRECT
async def get_lead_for_user(lead_id: int, user: User):
    lead = await repo.get_lead_by_id_and_unit(lead_id, user.unit_id)
    if not lead:
        raise ResourceNotFoundError("Lead not found")  # Returns 404
    return lead

# ❌ WRONG
async def get_lead(lead_id: int, user: User):
    lead = await repo.get_lead_by_id(lead_id)
    if lead.owner_id != user.id:
        raise HTTPException(403, "Forbidden")  # Leaks existence!
    return lead
```

---

## Database & Migrations

### Database Setup

**Development**:
```bash
# Set DATABASE_URL in .env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/qlts

# Run migrations
cd Backend_FastAPI
alembic upgrade head
```

**Testing**: SQLite in-memory database (auto-configured)

### Creating Migrations

1. Modify SQLAlchemy models in `Backend_FastAPI/app/models/`
2. Generate migration: `alembic revision --autogenerate -m "description"`
3. Review generated migration in `Backend_FastAPI/alembic/versions/`
4. Apply: `alembic upgrade head`

### ORM Best Practices

- Use `selectinload()` or `joinedload()` to prevent N+1 queries
- Avoid lazy loading in async code
- Use explicit relationships with `back_populates`
- Set appropriate cascade rules

---

## Key Architectural Patterns

### Admission Workflow State Machine

States: `draft` → `submitted` → `approved`/`rejected` → `enrolled`

**Critical Rules**:
- Applied rules are snapshot at creation (immutable)
- IDOR protection via `lead.unit_id` checks
- Transaction atomicity with savepoints for multi-step operations
- State transitions controlled by backend service layer

### Notification System

- Rule-based triggering (event → template + recipients)
- Multiple channels (email, SMS, in-app notifications)
- Template variables for dynamic content
- User preference management (opt-out capability)

### Configuration as Code

- Policy templates in `Backend_FastAPI/app/casbin_config/policy_templates.py`
- Auto-seeding in dev/test on startup
- Drift detection with manual/auto-sync capability
- Version tracking for applied policies

### Post-Commit Callbacks

Services return `(result, callback)` to execute side effects AFTER transaction commits:

```python
async def create_lead(db, data, user):
    lead = Lead(**data)
    db.add(lead)
    await db.flush()

    # Define side effect (email, notification, etc.)
    async def post_commit():
        await send_welcome_email(lead)

    return lead, post_commit

# Router commits and executes callback
lead, callback = await service.create_lead(db, data, user)
await db.commit()
await callback()
```

---

## Error Handling

### Backend Domain Exceptions

Defined in `Backend_FastAPI/app/utils/exceptions.py`:

- `ResourceNotFoundError` → HTTP 404
- `DuplicateResourceError` → HTTP 409
- `BusinessRuleViolation` → HTTP 400
- `ValidationError` → HTTP 400
- `ConflictError` → HTTP 409

**NEVER** raise `HTTPException` in services - use domain exceptions only.

### Frontend Error Handling

- API errors handled by React Query error boundaries
- Toast notifications for user-facing errors
- Error states rendered conditionally
- Retry logic for transient failures

---

## Testing Strategy

### Backend Tests

**Test Markers**:
- `@pytest.mark.unit`: Fast, isolated tests
- `@pytest.mark.integration`: Database interactions
- `@pytest.mark.security`: Authorization & IDOR tests
- `@pytest.mark.e2e`: Full workflow tests

**Running Specific Tests**:
```bash
pytest tests/api/test_leads.py::test_create_lead -v
pytest -m "security and not slow"
```

### Frontend Tests

**Unit Tests**: Component logic with Vitest
```bash
npm run test -- src/components/LeadCard.test.tsx
```

**E2E Tests**: User workflows with Playwright
```bash
npm run test:e2e -- tests/admission-flow.spec.ts
```

---

## Background Jobs (Celery)

### Task Categories

Located in `Backend_FastAPI/app/tasks/`:

- **Email Tasks**: Transactional emails, bulk notifications
- **Notification Tasks**: Rule-based notification processing
- **Cache Tasks**: Redis cache synchronization
- **Assignment Tasks**: Lead auto-assignment based on rules
- **Scheduled Tasks**: KPI updates, consultation reminders, cleanup

### Running Celery Worker

```bash
cd Backend_FastAPI
celery -A app.celery_app worker --loglevel=info

# With beat scheduler for periodic tasks
celery -A app.celery_app worker --beat --loglevel=info
```

---

## Critical Anti-Patterns

### Backend ❌ NEVER DO

```python
# ❌ Logic in Router
@router.post("/leads")
async def create(data, user = Depends(get_current_active_user)):
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

### Frontend ❌ NEVER DO

```tsx
// ❌ Calculate eligibility locally
const isEligible = gpa >= minGpa && docs >= requiredDocs; // WRONG

// ✅ Read from API
const { eligibility_status } = profile;
<Button disabled={eligibility_status !== "eligible"}>Submit</Button>

// ❌ Check role string
{user.role === "admin" && <ApproveButton />} // WRONG

// ✅ Check permission flag
{profile.can_approve && <ApproveButton />}

// ❌ Infer state
const isPending = status === "submitted" && !approved_at; // WRONG

// ✅ Use exact backend status
<Badge>{STATUS_CONFIG[status]?.label ?? status}</Badge>
```

---

## Performance Considerations

- **Backend**: Use `selectinload()`/`joinedload()` to prevent N+1 queries
- **Frontend**: React Query caching with staleTime/cacheTime tuning
- **Database**: Connection pooling (pool_size=20, max_overflow=40)
- **Redis**: Circuit breaker for fault tolerance
- **Statement Timeout**: 30s for long-running queries

---

## Real-time Features

### Socket.IO Integration

**Backend**: `Backend_FastAPI/app/socket_manager.py`
**Frontend**: `frontend/src/lib/socket/`

**Events**:
- Lead updates (assignment, status changes)
- Notification broadcasts
- KPI metric updates
- Admission status changes

**Connection Management**:
- JWT-based authentication for socket connections
- Room-based broadcasts (per unit/organization)
- Automatic reconnection on disconnect

---

## Environment Configuration

### Backend `.env` (in `Backend_FastAPI/`)

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/qlts
JWT_SECRET_KEY=your-secret-key
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
```

### Frontend `.env.local` (in `frontend/`)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SOCKET_URL=http://localhost:8000
```

---

## Additional Resources

- **Backend Architecture**: `Backend_FastAPI/MASTER_ARCHITECTURE.md`
- **Backend Guidelines**: `Backend_FastAPI/CLAUDE.md`
- **Frontend Architecture**: `frontend/FRONTEND_ARCHITECTURE_V3.md`
- **Frontend Guidelines**: `frontend/CLAUDE.md`
- **Authorization Guide**: `Backend_FastAPI/AUTHORIZATION_GUIDELINES.md`
