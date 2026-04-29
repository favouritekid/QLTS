# AGENTS.md

This file provides guidance to Codex when working with this repository.

---

## Project Overview

**QLTS** (Quan Ly Tuyen Sinh) is a comprehensive Educational Admission Management System for managing student admissions workflows in Vietnamese educational institutions. The system handles:

- **Lead Management**: Prospective student tracking through pipeline states
- **Admission Profiles**: Complete enrollment applications with document requirements and validation
- **Admission Paths**: Configurable pathways combining academic programs, admission methods, and document requirements
- **Notifications**: Dynamic rule-based notification system for applicants and officers
- **Finance**: Tuition fees, invoices, payments, installment plans
- **KPI Tracking**: Admission metrics and performance monitoring

---

## Technology Stack

### Backend
- **Framework**: FastAPI (Python 3.12)
- **Database**: PostgreSQL 16 (production & development via Docker)
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

## Docker Infrastructure

All services run in Docker containers. **Never run backend/frontend directly on the host.**

### Services

| Service | Image/Build | Purpose |
|---------|-------------|---------|
| `backend` | `Backend_FastAPI/Dockerfile` | FastAPI + Gunicorn (prod) / Uvicorn --reload (dev) |
| `frontend` | `frontend/Dockerfile` | Next.js standalone (prod) / npm run dev (dev) |
| `postgres` | `postgres:16-alpine` | PostgreSQL database |
| `redis` | `redis:7-alpine` | Cache, rate limiting, Celery broker |
| `celery-worker` | Same as backend | Background task processing |
| `celery-beat` | Same as backend | Periodic task scheduler (singleton) |
| `nginx` | `nginx:1.27-alpine` | Reverse proxy + SSL (production profile only) |

### Dev vs Production

```bash
# Development (auto-loads docker-compose.override.yml)
# Step 1: Start services
docker compose up -d
# Step 2: Enable frontend HMR (separate terminal, runs foreground)
docker compose watch          # or just: dev.cmd
# - Backend: uvicorn --reload with bind mount (auto hot-reload)
# - Frontend: docker compose watch syncs src/ into container → Turbopack HMR
#   (Windows bind mounts don't propagate inotify → watch is required)
# - Ports exposed: backend:8000, frontend:3000, postgres:5433, redis:6380

# Production
docker compose --profile production up -d
# - Backend: gunicorn with workers
# - Frontend: Next.js standalone build
# - Nginx: SSL termination + reverse proxy
```

### Key Docker facts
- `Backend_FastAPI/Dockerfile` only installs `requirements.txt` (production deps)
- `tests/` is in `.dockerignore` -- excluded from image, available in dev via bind mount
- Test deps (`requirements-dev.txt`) must be installed manually into running container
- `docker-entrypoint.sh` runs `alembic upgrade head` on container start

---

## Environment Files

| File | Purpose | Used by |
|------|---------|---------|
| `.env` | Docker Compose vars (POSTGRES_USER, POSTGRES_PASSWORD) | `docker compose` |
| `.env.production` | Production backend config | Backend container (prod) |
| `Backend_FastAPI/.env` | Development backend config | Backend container (dev, via override) |
| `frontend/.env.local` | Frontend env vars | Frontend container |

**Important**: `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL` are constructed in `docker-compose.yml` from `POSTGRES_*` vars. Do NOT set them in `.env.production`.

### Redis DB Allocation

| DB | Purpose | Used by |
|----|---------|---------|
| 1 | Cache + Socket.IO | Backend, Celery |
| 2 | Celery broker | Celery worker/beat |
| 3 | Celery results | Celery worker |

---

## Directory Structure

```
Backend_FastAPI/
  app/
    core/              # deps.py (dependency injection), config, events
    routers/           # HTTP endpoints (dumb coordinators)
    services/          # Business logic (pure Python)
    repositories/      # Data access layer
    models/            # SQLAlchemy ORM models
    schemas/           # Pydantic validation models
    security/          # JWT, OAuth2, password hashing
    tasks/             # Celery async tasks
    middleware/        # Exception handlers, logging
    casbin_config/     # RBAC policy templates
  alembic/             # Database migrations
  tests/               # Pytest test suite
  requirements.txt     # Production dependencies
  requirements-dev.txt # Test/dev dependencies (extends requirements.txt)

frontend/
  src/
    app/               # Next.js App Router
      (auth)/          # Authentication routes
      (dashboard)/     # Protected dashboard routes
    components/        # Reusable React components
    hooks/             # React Query + custom hooks
    lib/
      api/             # Axios-based API clients
      zod/             # Zod validation schemas
      stores/          # Zustand UI state stores
      socket/          # Socket.IO real-time updates
    types/             # TypeScript type definitions
  tests/               # Vitest + Playwright tests
```

---

## Common Development Commands

All commands use `docker compose exec` to run inside containers.

### Backend Testing (IMPORTANT)

```bash
# Step 1: Install test deps (required once per container lifecycle, lost on restart)
docker compose exec backend pip install -r requirements-dev.txt

# Step 2: Run tests
docker compose exec backend pytest tests/ -v                          # All tests
docker compose exec backend pytest tests/api/test_leads.py -v         # Specific file
docker compose exec backend pytest tests/api/test_leads.py::test_fn -v  # Single test
docker compose exec backend pytest -m unit                             # By marker
docker compose exec backend pytest -m security
```

### Backend Other

```bash
# Migrations
docker compose exec backend alembic revision --autogenerate -m "description"
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1

# Code quality
docker compose exec backend black .
docker compose exec backend isort .
docker compose exec backend flake8 .

# Logs
docker compose logs backend -f --tail=50
docker compose logs celery-worker -f --tail=50
```

### Frontend

**Use `scripts/fe-check.sh` (or `scripts\fe-check.cmd` on Windows)** for
type-check / test / lint / build. The wrapper runs each command in a
throw-away `docker compose run --rm --no-deps frontend ...` container
so it cannot OOM-kill the live Next.js dev server (running `tsc` /
`vitest` via `exec` has crashed PID 1 in the dev container, producing
`err_empty_response` in the browser).

```bash
./scripts/fe-check.sh type-check    # TypeScript (preferred)
./scripts/fe-check.sh test          # Vitest
./scripts/fe-check.sh test:coverage # Coverage
./scripts/fe-check.sh lint          # ESLint
./scripts/fe-check.sh build         # Production build
```

Avoid `docker compose exec frontend npm run type-check` (and `test`,
`build`) on a live dev container. `exec` is fine for one-off, low-RAM
commands such as `npm install <pkg>`.

---

## Architecture (Summary)

### Backend Architecture (V3.0)

```
ROUTER (Dumb HTTP Translator)
  | Dependency Injection
SECURITY GATEWAY (deps.py: Auth, RBAC, IDOR)
  | Business Logic
SERVICE (Pure Python, no FastAPI imports)
  | Data Access
REPOSITORY (SQLAlchemy ORM)
```

**Key Rules**:
- ALL auth/authorization/IDOR checks in `app/core/deps.py`
- Services never import FastAPI -- raise domain exceptions, not HTTPException
- Router commits (`await db.commit()`), Service only flushes
- Services return `(result, post_commit_callback)` for side effects

**Detailed docs**: `Backend_FastAPI/MASTER_ARCHITECTURE.md`, `Backend_FastAPI/AGENTS.md`

### Frontend Architecture (V3.0)

**Thin Client Philosophy**: Frontend is presentation-only. Backend is source of truth.
- NO business logic (no eligibility calculations, scoring, workflow transitions)
- Display exactly what backend returns (trust `status`, `can_edit`, `available_actions`)
- Control visibility via API permission flags, NOT `user.role` checks

**Detailed docs**: `frontend/FRONTEND_ARCHITECTURE_V3.md`, `frontend/AGENTS.md`

---

## Security & Authorization

### Authentication
- JWT tokens (15 min access, 30 day refresh)
- Redis-backed logout blacklist
- Active status + trusted device tracking

### Authorization (Casbin RBAC)
- **Roles**: `admin`, `manager`, `officer`, `accountant`, `user`
- **Diamond inheritance**: admin > (manager + accountant) > officer > user
- Templates: `Backend_FastAPI/app/casbin_config/policy_templates.py`
- Dependency gates in `deps.py`: `get_current_active_user`, `check_permission`, `require_admin`

### IDOR Protection
- **3-tier**: Admin (all) > Manager (unit scope) > Officer (assigned + unit scope)
- ALWAYS return 404 (not 403) to avoid leaking resource existence
- Detailed guide: `Backend_FastAPI/AUTHORIZATION_GUIDELINES.md`

---

## Key Workflows

### Admission Profile State Machine

```
draft -> submitted -> approved -> confirmed -> enrolled
                   -> rejected -> resubmitted -> (re-evaluation)
                   -> overridden (manager/admin override)
```

### Claim/Unclaim (Soft Review Assignment)
- Manager/Admin can claim a profile for review (soft bookmark, doesn't block others)
- Tracked via `assigned_reviewer_id` + `assigned_at` on AdmissionProfile

### Background Jobs (Celery)
- Celery worker and beat run as separate Docker services (auto-started)
- Tasks in `Backend_FastAPI/app/tasks/`: email, notifications, cache sync, KPI updates
- Monitor: `docker compose logs celery-worker -f`

---

## Error Handling

### Backend Domain Exceptions (`app/utils/exceptions.py`)
- `ResourceNotFoundError` -> 404
- `DuplicateResourceError` -> 409
- `BusinessRuleViolation` -> 400
- `ValidationError` -> 400
- `ConflictError` -> 409

**NEVER** raise `HTTPException` in services.

---

## Additional Resources

- **Backend Architecture**: `Backend_FastAPI/MASTER_ARCHITECTURE.md`
- **Backend Guidelines**: `Backend_FastAPI/AGENTS.md`
- **Frontend Architecture**: `frontend/FRONTEND_ARCHITECTURE_V3.md`
- **Frontend Guidelines**: `frontend/AGENTS.md`
- **Authorization Guide**: `Backend_FastAPI/AUTHORIZATION_GUIDELINES.md`
