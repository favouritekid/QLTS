# Codebase Exploration Summary: Pipeline Management & Related Structures

## 1. DIRECTORY STRUCTURE OVERVIEW

### Backend (FastAPI)
```
/home/user/QLTS/Backend_FastAPI/
├── app/
│   ├── models/           # SQLAlchemy ORM Models
│   │   ├── pipeline.py   # PipelineStage, ConsultationStatus models
│   │   ├── lead.py       # Lead, Consultation, Application models
│   │   └── ...
│   ├── routers/          # API Route Handlers
│   │   ├── pipeline.py   # Public pipeline endpoints
│   │   ├── admin.py      # Admin CRUD endpoints (105KB)
│   │   ├── leads.py      # Lead management
│   │   └── ...
│   ├── schemas/          # Pydantic Request/Response Models
│   │   ├── pipeline.py   # PipelineStage/ConsultationStatus schemas
│   │   ├── lead.py       # Lead schemas
│   │   └── ...
│   ├── services/         # Business Logic Layer
│   │   ├── pipeline_service.py   # Pipeline CRUD + Cache logic
│   │   ├── lead_service.py
│   │   └── ...
│   ├── main.py           # FastAPI app initialization
│   ├── database.py       # Database + Redis setup
│   └── ...
└── alembic/
    └── versions/         # Database migrations
        └── ec2713f8825b_initial_migration_create_all_tables.py  # Pipeline schema
```

### Frontend (Next.js + React)
```
/home/user/QLTS/frontend/src/
├── app/
│   ├── (dashboard)/
│   │   ├── admin/
│   │   │   ├── pipeline/
│   │   │   │   └── page.tsx        # Pipeline admin settings page
│   │   │   ├── users/
│   │   │   ├── organization/
│   │   │   └── policies/
│   │   ├── leads/
│   │   │   ├── page.tsx            # Leads list page
│   │   │   ├── [id]/page.tsx       # Lead detail page
│   │   │   └── pipeline/page.tsx   # Pipeline kanban board
│   │   ├── dashboard/
│   │   ├── settings/
│   │   └── layout.tsx              # Dashboard layout
│   ├── (auth)/
│   └── page.tsx
├── components/
│   ├── layouts/
│   │   ├── DashboardLayout.tsx     # Main layout with sidebar
│   │   ├── SocketHandler.tsx
│   │   └── dashboard/
│   │       ├── AppSidebar.tsx      # Navigation sidebar
│   │       ├── Header.tsx
│   │       ├── NavUser.tsx
│   │       ├── NavGroup.tsx
│   │       └── Main.tsx
│   ├── admin/
│   │   ├── PipelineStageDialog.tsx     # Create/Edit pipeline stage
│   │   ├── ConsultationStatusDialog.tsx # Create/Edit consultation status
│   │   └── ...
│   ├── leads/
│   │   ├── PipelineBoard.tsx       # Kanban board component
│   │   ├── PipelineColumn.tsx      # Pipeline stage column
│   │   ├── ConsultationDialog.tsx  # Change consultation status
│   │   └── ...
│   └── ui/                         # UI components (Card, Dialog, Button, etc)
├── hooks/
│   ├── usePipeline.ts             # Pipeline queries & mutations
│   ├── useLeads.ts                # Lead queries & mutations
│   └── ...
├── lib/
│   ├── api/
│   │   ├── pipeline.ts            # Pipeline API client
│   │   ├── leads.ts               # Leads API client
│   │   └── client.ts              # Axios configuration
│   ├── stores/
│   │   └── ui.store.ts            # UI state (sidebar collapse, etc)
│   └── ...
├── types/
│   ├── pipeline.types.ts          # Pipeline TypeScript types
│   ├── lead.types.ts              # Lead types
│   └── ...
└── test/
    └── mocks/
        ├── data/pipeline.ts       # Mock pipeline data
        └── handlers/pipeline.ts   # MSW handlers
```

---

## 2. DATABASE SCHEMA

### Pipeline-Related Tables

#### `pipeline_stage`
```sql
CREATE TABLE pipeline_stage (
    id VARCHAR(50) PRIMARY KEY,          -- e.g., 'new_lead', 'contacted'
    name VARCHAR(255) NOT NULL,          -- e.g., 'New Lead', 'Contacted'
    order INTEGER NOT NULL UNIQUE        -- Position in pipeline
);
```

#### `consultation_status`
```sql
CREATE TABLE consultation_status (
    id VARCHAR(50) PRIMARY KEY,          -- e.g., 'scheduled', 'rescheduled'
    name VARCHAR(255) NOT NULL,          -- e.g., 'Scheduled', 'Rescheduled'
    color_code VARCHAR(7) NOT NULL,      -- Hex color: '#FF5733'
    stage_id VARCHAR(50) NOT NULL        -- FK to pipeline_stage
);
```

#### `lead` (related columns)
```sql
CREATE TABLE lead (
    id INTEGER PRIMARY KEY,
    full_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(20),
    source VARCHAR(50),
    status VARCHAR(50),
    lead_score INTEGER,
    education_level VARCHAR(100),
    gpa FLOAT,
    location VARCHAR(255),
    officer_rating INTEGER,
    officer_summary TEXT,
    created_at TIMESTAMP WITH TIMEZONE,
    updated_at TIMESTAMP WITH TIMEZONE,
    assigned_at TIMESTAMP WITH TIMEZONE,
    offering_id INTEGER FK,              -- Link to program offering
    unit_id INTEGER FK NOT NULL,         -- Organization unit
    assigned_officer_id INTEGER FK,      -- Assigned sales officer
    consultation_status_id VARCHAR(50) FK, -- Current consultation status
    pipeline_stage_id VARCHAR(50) FK     -- Current pipeline stage
);
```

---

## 3. BACKEND: DATABASE MODELS

### File: `/home/user/QLTS/Backend_FastAPI/app/models/pipeline.py`

```python
class PipelineStage(Base):
    __tablename__ = "pipeline_stage"
    id: String(50)           # Primary key
    name: String(255)        # Display name
    order: Integer           # Unique ordering
    
    # Relationships
    leads: relationship(Lead, back_populates="pipeline_stage")
    statuses: relationship(ConsultationStatus, back_populates="stage")

class ConsultationStatus(Base):
    __tablename__ = "consultation_status"
    id: String(50)           # Primary key
    name: String(255)
    color_code: String(7)    # Hex color
    stage_id: String(50) FK  # Foreign key to PipelineStage
    
    # Relationships
    stage: relationship(PipelineStage, back_populates="statuses")
    leads: relationship(Lead, back_populates="consultation_status")
```

### File: `/home/user/QLTS/Backend_FastAPI/app/models/lead.py`

```python
class Lead(Base):
    __tablename__ = "lead"
    id: Integer (Primary Key)
    full_name, email, phone, source, status
    lead_score, education_level, gpa, location
    officer_rating, officer_summary
    created_at, updated_at, assigned_at
    offering_id FK
    unit_id FK
    assigned_officer_id FK
    consultation_status_id FK
    pipeline_stage_id FK
    
    # Relationships
    pipeline_stage: relationship(PipelineStage)
    consultation_status: relationship(ConsultationStatus)
    assigned_officer: relationship(User)

class Consultation(Base):
    __tablename__ = "consultation"
    id, lead_id FK, consultation_date
    method, notes, outcome, duration_minutes
    officer_id FK
    consultation_status_id FK

class Application(Base):
    __tablename__ = "application"
    id, lead_id FK, documents, status, officer_id FK

class CRMInteraction(Base), AssignmentLog(Base)
```

---

## 4. BACKEND: API SCHEMAS (Pydantic)

### File: `/home/user/QLTS/Backend_FastAPI/app/schemas/pipeline.py`

```python
# Pipeline Stage Schemas
class PipelineStageBase(BaseModel):
    name: str (min=3, max=255)
    order: int (gt=0)

class PipelineStageCreate(PipelineStageBase):
    id: str (min=3, max=50)

class PipelineStageUpdate(BaseModel):
    name: Optional[str]
    order: Optional[int]

class PipelineStage(PipelineStageBase):
    id: str

# Consultation Status Schemas
class ConsultationStatusBase(BaseModel):
    name: str (min=3, max=255)
    color_code: str (pattern=r"^#[0-9a-fA-F]{6}$")  # Hex validation
    stage_id: str

class ConsultationStatusCreate(ConsultationStatusBase):
    id: str (min=3, max=50)

class ConsultationStatusUpdate(BaseModel):
    name: Optional[str]
    color_code: Optional[str]
    stage_id: Optional[str]

class ConsultationStatus(ConsultationStatusBase):
    id: str

# Full Pipeline Response
class FullPipeline(BaseModel):
    stages: List[PipelineStage]
    statuses: List[ConsultationStatus]
```

---

## 5. BACKEND: API ROUTES

### Public Routes (Read-Only)
**File: `/home/user/QLTS/Backend_FastAPI/app/routers/pipeline.py`**

```
GET /api/pipeline/all                    Response: FullPipeline
  - Returns all stages and consultation statuses
  - Cache enabled (Redis)
  - Auth required: Basic user
```

### Admin-Only Routes (CRUD)
**File: `/home/user/QLTS/Backend_FastAPI/app/routers/admin.py` (Lines 1894-2024)**

#### Pipeline Stages
```
GET    /api/admin/pipeline-stages                Response: List[PipelineStage]
POST   /api/admin/pipeline-stages                Request: PipelineStageCreate
GET    /api/admin/pipeline-stages/{stage_id}    Response: PipelineStage
PUT    /api/admin/pipeline-stages/{stage_id}    Request: PipelineStageUpdate
DELETE /api/admin/pipeline-stages/{stage_id}    
  - All endpoints require Casbin permission check
  - Cache invalidation on CREATE/UPDATE/DELETE
  - Constraints: Cannot delete stage with linked statuses
```

#### Consultation Statuses
```
POST   /api/admin/consultation-statuses                Request: ConsultationStatusCreate
GET    /api/admin/consultation-statuses/{status_id}   Response: ConsultationStatus
PUT    /api/admin/consultation-statuses/{status_id}   Request: ConsultationStatusUpdate
DELETE /api/admin/consultation-statuses/{status_id}
  - All endpoints require Casbin permission check
  - Cache invalidation on CREATE/UPDATE/DELETE
  - Constraints: Cannot delete status in use by leads or consultations
```

#### Lead Operations (Related)
```
PUT    /api/admin/leads/{lead_id}/revert-status       Admin revert lead to previous stage
```

---

## 6. BACKEND: SERVICE LAYER

### File: `/home/user/QLTS/Backend_FastAPI/app/services/pipeline_service.py`

**Cache Configuration:**
- Key: `pipeline:all_stages`, `pipeline:all_statuses`
- TTL: `CONFIG_CACHE_TTL_SECONDS` (default 3600s)
- Stampede Prevention: Lock-based approach with `asyncio.Lock()`
- Redis Integration: `safe_redis_get`, `safe_redis_set`, `safe_redis_delete`

**CRUD Operations:**

1. **Pipeline Stages:**
   - `get_all_pipeline_stages()` - Cached + Ordered by `order` field
   - `create_pipeline_stage()` - Validates ID uniqueness & order uniqueness
   - `get_pipeline_stage()` - Direct DB query (no cache)
   - `update_pipeline_stage()` - Validates order constraints
   - `delete_pipeline_stage()` - Check for child statuses
   - Cache invalidation on mutation

2. **Consultation Statuses:**
   - `get_all_consultation_statuses()` - Cached
   - `create_consultation_status()` - Validates parent stage exists
   - `get_consultation_status()` - Direct DB query
   - `update_consultation_status()` - Validates parent stage
   - `delete_consultation_status()` - Check lead & consultation usage
   - Cache invalidation on mutation

3. **Cache Management:**
   - `invalidate_pipeline_cache()` - Clears all pipeline caches

---

## 7. BACKEND: MAIN ROUTE REGISTRATION

### File: `/home/user/QLTS/Backend_FastAPI/app/main.py` (Lines 563-574)

```python
app.include_router(auth.router, prefix="/api/auth")
app.include_router(profile.router, prefix="/api/profile")
app.include_router(users.router, prefix="/api/users")
app.include_router(sessions.router, prefix="/api")
app.include_router(notifications.router, prefix="/api/notifications")
app.include_router(notification_preferences.router, prefix="/api/notifications")
app.include_router(leads.router, prefix="/api/leads")
app.include_router(pipeline.router, prefix="/api/pipeline")        # Public pipeline
app.include_router(organization.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")              # Admin CRUD
```

---

## 8. FRONTEND: TYPE DEFINITIONS

### File: `/home/user/QLTS/frontend/src/types/pipeline.types.ts`

```typescript
// Pipeline Stage
interface PipelineStage {
    id: string;
    name: string;
    order: number;
    lead_count?: number;        // Statistics
    conversion_rate?: number;
}

interface PipelineStageCreate {
    id: string;
    name: string;
    order: number;
}

interface PipelineStageUpdate {
    name?: string;
    order?: number;
}

// Consultation Status
interface ConsultationStatus {
    id: string;
    name: string;
    color_code: string;         // '#FF5733'
    stage_id: string;
    stage?: PipelineStage;      // Relationship
}

interface ConsultationStatusCreate {
    id: string;
    name: string;
    color_code: string;
    stage_id: string;
}

interface ConsultationStatusUpdate {
    name?: string;
    color_code?: string;
    stage_id?: string;
}

// Full Pipeline Response
interface FullPipeline {
    stages: PipelineStageWithStats[];
    total_leads: number;
    conversion_rate?: number;
    avg_time_in_pipeline_days?: number;
}

interface PipelineStageWithStats extends PipelineStage {
    lead_count: number;
    statuses: ConsultationStatus[];
    leads?: Lead[];
    conversion_rate?: number;
    avg_time_in_stage_days?: number;
}

// Kanban Related
interface KanbanColumn {
    id: string;
    name: string;
    order: number;
    leads: Lead[];
    lead_count: number;
}

interface MoveLeadPayload {
    lead_id: number;
    from_stage_id: string;
    to_stage_id: string;
    reason?: string;
}

// Constants
const STAGE_COLORS = {
    new_lead: '#E3F2FD',                   // Light Blue
    contacted: '#FFF9C4',                  // Light Yellow
    consultation_scheduled: '#FFE0B2',     // Light Orange
    consultation_completed: '#C8E6C9',     // Light Green
    application_submitted: '#B2DFDB',      // Light Teal
    enrolled: '#4CAF50',                   // Green
    lost: '#FFCDD2',                       // Light Red
};
```

---

## 9. FRONTEND: API CLIENT

### File: `/home/user/QLTS/frontend/src/lib/api/pipeline.ts`

**Public Endpoints (Available to all authenticated users):**
```typescript
getStages()                    // GET /api/pipeline/stages
getFullPipeline(params)        // GET /api/pipeline/all
getPipelineStats(params)       // Derived from getFullPipeline()
getLeadsInStage(stageId)       // GET /api/leads?pipeline_stage_id=...
```

**Admin-Only Endpoints:**
```typescript
// Pipeline Stage Management
createStage(data)              // POST /api/admin/pipeline-stages
updateStage(stageId, data)     // PUT /api/admin/pipeline-stages/{id}
deleteStage(stageId)           // DELETE /api/admin/pipeline-stages/{id}

// Consultation Status Management
getConsultationStatuses()      // GET /api/admin/consultation-statuses
getConsultationStatus(statusId) // GET /api/admin/consultation-statuses/{id}
createConsultationStatus(data)  // POST /api/admin/consultation-statuses
updateConsultationStatus(id, data) // PUT /api/admin/consultation-statuses/{id}
deleteConsultationStatus(id)   // DELETE /api/admin/consultation-statuses/{id}

// Lead Operations
moveLeadToStage(data)          // PUT /api/leads/{lead_id}
revertLeadStatus(leadId)       // POST /api/admin/leads/{id}/revert-status

// Cache Control
invalidatePipelineCache()      // POST /api/admin/pipeline/invalidate-cache
```

---

## 10. FRONTEND: REACT HOOKS (React Query)

### File: `/home/user/QLTS/frontend/src/hooks/usePipeline.ts`

**Query Hooks (Data Fetching):**
```typescript
usePipelineStages()                      // Get all stages (5min cache)
useFullPipeline(params?)                 // Get full pipeline (30sec cache)
useLeadsInStage(stageId)                 // Get leads in stage (30sec cache)
useConsultationStatuses()                // Get all statuses (5min cache)
usePipelineStats(params?)                // Get statistics (1min cache)
```

**Mutation Hooks (CRUD Operations):**
```typescript
// Pipeline Stages
useCreatePipelineStage()        // POST, invalidates all pipeline queries
useUpdatePipelineStage()        // PUT, invalidates all pipeline queries
useDeletePipelineStage()        // DELETE, invalidates all pipeline queries

// Consultation Statuses
useCreateConsultationStatus()   // POST, invalidates consultation status cache
useUpdateConsultationStatus()   // PUT, invalidates consultation status cache
useDeleteConsultationStatus()   // DELETE, invalidates consultation status cache

// Lead Operations
useMoveLeadToStage()            // PUT, optimistic update + rollback
useRevertLeadStatus()           // POST admin revert

// Utilities
invalidatePipelineCache(queryClient)  // Manual cache invalidation
```

**Query Keys:**
```typescript
const pipelineKeys = {
    all: ['pipeline'],
    stages: () => [...pipelineKeys.all, 'stages'],
    fullPipeline: (params) => [...pipelineKeys.all, 'full', params],
    stageLeads: (stageId) => [...pipelineKeys.all, 'stageLeads', stageId],
    consultationStatuses: () => [...pipelineKeys.all, 'consultationStatuses'],
    stats: (params) => [...pipelineKeys.all, 'stats', params],
};
```

---

## 11. FRONTEND: UI COMPONENTS

### Admin Pipeline Management Page
**File: `/home/user/QLTS/frontend/src/app/(dashboard)/admin/pipeline/page.tsx`**

- **Layout:** Tabs interface (Pipeline Stages | Consultation Statuses)
- **Features:**
  - List all stages/statuses with details
  - Create new stage/status (+ button)
  - Edit existing stage/status (Pencil icon)
  - Delete stage/status (Trash icon with confirmation)
  - Display metadata: stage order, color code, stage ID, lead count, conversion rate
  - Loading skeletons
  - Back button navigation

### Pipeline Stage Dialog Component
**File: `/home/user/QLTS/frontend/src/components/admin/PipelineStageDialog.tsx`**

- **Form Fields:**
  - `id` (text) - Only in create mode, readonly in edit
  - `name` (text) - Required, 2-100 chars
  - `order` (number) - Required, >= 0
- **Validation:** Zod schema validation
- **Modes:** Create vs Edit
- **Handlers:** onSubmit triggers createStage or updateStage mutation

### Consultation Status Dialog Component
**File: `/home/user/QLTS/frontend/src/components/admin/ConsultationStatusDialog.tsx`**

- **Form Fields:**
  - `id` (text) - Only in create mode
  - `name` (text) - Required, 2-100 chars
  - `stage_id` (select) - Required, loads from usePipelineStages hook
  - `color_code` (text + color picker) - Hex format, preset colors
- **Features:**
  - 8 preset colors (Blue, Green, Yellow, Red, Purple, Pink, Indigo, Gray)
  - Hex color validation
  - Dynamic stage dropdown
- **Modes:** Create vs Edit

### Pipeline Board (Kanban)
**File: `/home/user/QLTS/frontend/src/components/leads/PipelineBoard.tsx`**

- Display pipeline stages as kanban columns
- Each column contains leads
- Drag-and-drop to move leads between stages
- Uses `useMoveLeadToStage()` with optimistic updates

### Pipeline Column Component
**File: `/home/user/QLTS/frontend/src/components/leads/PipelineColumn.tsx`**

- Render individual pipeline stage column
- List leads in the stage
- Handle drag-and-drop interactions

---

## 12. FRONTEND: PAGES

### Admin Pipeline Settings Page
**Path: `/home/user/QLTS/frontend/src/app/(dashboard)/admin/pipeline/page.tsx`**
- Admin-only page for managing pipeline configuration
- Tabs: Pipeline Stages | Consultation Statuses
- CRUD UI for each resource type

### Pipeline Board Page (Kanban)
**Path: `/home/user/QLTS/frontend/src/app/(dashboard)/leads/pipeline/page.tsx`**
- Kanban board view of leads by pipeline stage
- Drag-and-drop leads between stages
- Filter options
- Export functionality
- Refresh button

### Leads List Page
**Path: `/home/user/QLTS/frontend/src/app/(dashboard)/leads/page.tsx`**
- List all leads with filters
- Shows pipeline_stage_id and consultation_status_id
- Link to individual lead details

### Lead Detail Page
**Path: `/home/user/QLTS/frontend/src/app/(dashboard)/leads/[id]/page.tsx`**
- Individual lead information
- Current pipeline stage & consultation status display
- Option to change status/stage

---

## 13. FRONTEND: NAVIGATION & SIDEBAR

### File: `/home/user/QLTS/frontend/src/components/layouts/DashboardLayout.tsx`

Main layout component with:
- `<AppSidebar />` - Navigation sidebar (collapsible)
- `<Header />` - Top header bar
- `<Main>` - Main content area

### File: `/home/user/QLTS/frontend/src/components/layouts/dashboard/AppSidebar.tsx`

**Navigation Structure:**

**OVERVIEW Section:**
- Dashboard → `/dashboard`
- Leads → `/leads`
- Pipeline Board → `/leads/pipeline`
- Users (admin only) → `/admin/users`
- Organization (admin only) → `/admin/organization`
- Pipeline Settings (admin only) → `/admin/pipeline` ⭐
- Policy Management (admin only) → `/admin/policies`

**MANAGEMENT Section:**
- Settings → `/settings`
- Notifications → `/notifications` (with unread badge)

**Features:**
- Sidebar collapse/expand (72px or 256px width)
- Mobile responsive (hidden on mobile, overlay when visible)
- User profile section at bottom
- Admin role-based menu filtering
- Notification badge on Notifications link

---

## 14. DATABASE RELATIONSHIPS

```
┌─────────────────────┐
│   PipelineStage     │
│  (String PK: id)    │
│  - id               │
│  - name             │
│  - order (unique)   │
└──────────┬──────────┘
           │
           │ (1:N) back_populates="stage"
           │
           ▼
┌─────────────────────────────┐
│  ConsultationStatus         │
│  (String PK: id)            │
│  - id                       │
│  - name                     │
│  - color_code               │
│  - stage_id (FK) ◀──────────┘
└──────────┬──────────────────┘
           │
           │ (1:N) back_populates="consultation_status"
           │
           ▼
┌──────────────────────┐
│      Lead            │
│ (Integer PK: id)     │
│ - pipeline_stage_id  │ ◀──────────┐
│ - consultation_status_id (FK)     │
│ - ...                │           │
└──────────────────────┘  1:N     │
                          │   
                          └─ (Optional) Links to Consultation
                             (1:N) back_populates="lead"
```

---

## 15. API ROUTES REGISTRATION SUMMARY

| Router File | Prefix | Routes | Purpose |
|---|---|---|---|
| `pipeline.py` | `/api/pipeline` | GET /all | Public: Get full pipeline |
| `admin.py` | `/api/admin` | POST/PUT/DELETE /pipeline-stages | Admin: Stage CRUD |
| `admin.py` | `/api/admin` | POST/PUT/DELETE /consultation-statuses | Admin: Status CRUD |
| `leads.py` | `/api/leads` | CRUD for leads | Lead management |

---

## 16. CACHING STRATEGY

**Pipeline Service Cache:**
- **Key Pattern:** `pipeline:all_stages`, `pipeline:all_statuses`
- **TTL:** 3600 seconds (configurable)
- **Storage:** Redis
- **Invalidation:** On CREATE/UPDATE/DELETE mutations
- **Stampede Protection:** `asyncio.Lock()` for cache misses

**React Query Cache:**
- **Stages:** 5 minutes stale time, 10 minutes garbage collection
- **Full Pipeline:** 30 seconds stale time, 5 minutes GC
- **Leads in Stage:** 30 seconds stale time
- **Consultation Statuses:** 5 minutes stale time, 10 minutes GC
- **Statistics:** 1 minute stale time, 5 minutes GC

---

## 17. KEY FILES LOCATIONS (ABSOLUTE PATHS)

### Backend

**Models:**
- `/home/user/QLTS/Backend_FastAPI/app/models/pipeline.py` - PipelineStage, ConsultationStatus
- `/home/user/QLTS/Backend_FastAPI/app/models/lead.py` - Lead, Consultation, Application

**Routes:**
- `/home/user/QLTS/Backend_FastAPI/app/routers/pipeline.py` - Public endpoints
- `/home/user/QLTS/Backend_FastAPI/app/routers/admin.py` - Admin CRUD endpoints

**Schemas:**
- `/home/user/QLTS/Backend_FastAPI/app/schemas/pipeline.py` - Pydantic models

**Services:**
- `/home/user/QLTS/Backend_FastAPI/app/services/pipeline_service.py` - Business logic

**Database:**
- `/home/user/QLTS/Backend_FastAPI/alembic/versions/ec2713f8825b_initial_migration_create_all_tables.py` - Schema

**Config:**
- `/home/user/QLTS/Backend_FastAPI/app/main.py` - Route registration

### Frontend

**Types:**
- `/home/user/QLTS/frontend/src/types/pipeline.types.ts` - TypeScript types

**API Client:**
- `/home/user/QLTS/frontend/src/lib/api/pipeline.ts` - API functions

**Hooks:**
- `/home/user/QLTS/frontend/src/hooks/usePipeline.ts` - React Query hooks

**Components:**
- `/home/user/QLTS/frontend/src/components/admin/PipelineStageDialog.tsx`
- `/home/user/QLTS/frontend/src/components/admin/ConsultationStatusDialog.tsx`
- `/home/user/QLTS/frontend/src/components/leads/PipelineBoard.tsx`
- `/home/user/QLTS/frontend/src/components/leads/PipelineColumn.tsx`

**Layouts:**
- `/home/user/QLTS/frontend/src/components/layouts/DashboardLayout.tsx`
- `/home/user/QLTS/frontend/src/components/layouts/dashboard/AppSidebar.tsx`

**Pages:**
- `/home/user/QLTS/frontend/src/app/(dashboard)/admin/pipeline/page.tsx` - Admin settings
- `/home/user/QLTS/frontend/src/app/(dashboard)/leads/pipeline/page.tsx` - Kanban board
- `/home/user/QLTS/frontend/src/app/(dashboard)/leads/page.tsx` - Leads list
- `/home/user/QLTS/frontend/src/app/(dashboard)/leads/[id]/page.tsx` - Lead detail

---

## 18. DATA FLOW DIAGRAM

### Admin Creating Pipeline Stage

```
Admin clicks "Add Stage" in UI
    ↓
PipelineStageDialog component opens (create mode)
    ↓
Form submitted with {id, name, order}
    ↓
useCreatePipelineStage mutation triggered
    ↓
pipelineApi.createStage(data) calls POST /api/admin/pipeline-stages
    ↓
FastAPI: admin.py@create_new_pipeline_stage() handler
    ↓
pipeline_service.create_pipeline_stage(db, stage_in)
    - Validate ID uniqueness
    - Validate order uniqueness
    - Insert into DB
    - Invalidate Redis cache
    ↓
Response: PipelineStage object back to frontend
    ↓
useCreatePipelineStage.onSuccess():
    - Show success toast
    - Invalidate all pipeline queries
    - Close dialog
    ↓
React Query refetches all pipeline data
    ↓
UI updates with new stage
```

### User Viewing Pipeline Board

```
User navigates to /leads/pipeline
    ↓
PipelinePage component loads
    ↓
useFullPipeline() query triggered
    ↓
pipelineApi.getFullPipeline(params) calls GET /api/pipeline/all
    ↓
FastAPI: pipeline.py@get_full_pipeline() handler
    ↓
pipeline_service.get_all_pipeline_stages(db)
    - Check Redis cache "pipeline:all_stages"
    - If hit: return cached data
    - If miss: query DB, store in Redis (3600s TTL), return
    ↓
pipeline_service.get_all_consultation_statuses(db)
    - Same caching logic for "pipeline:all_statuses"
    ↓
Response: FullPipeline { stages, statuses }
    ↓
React Query caches for 30 seconds (staleTime)
    ↓
PipelineBoard component renders with data
    ↓
PipelineColumn for each stage displays leads
    ↓
User can drag leads between columns
    ↓
Drag detected → useMoveLeadToStage mutation
    ↓
PUT /api/leads/{lead_id} with pipeline_stage_id
    ↓
Lead updated in DB + all queries invalidated
```

---

## 19. VALIDATION & CONSTRAINTS

### Pipeline Stage
- **ID:** 3-50 chars, lowercase/underscore only
- **Name:** 3-255 chars
- **Order:** > 0, must be unique
- **Cannot delete:** If it has linked ConsultationStatus

### Consultation Status
- **ID:** 3-50 chars, lowercase/underscore only
- **Name:** 3-255 chars
- **Color:** Hex format `#[0-9A-Fa-f]{6}`
- **Stage:** Must reference existing PipelineStage
- **Cannot delete:** If used by any Lead or Consultation

### Lead
- **pipeline_stage_id:** Optional FK to PipelineStage
- **consultation_status_id:** Optional FK to ConsultationStatus

---

## 20. PERMISSION & SECURITY

### Route Protection
- **Public:** GET /api/pipeline/all - Available to all authenticated users
- **Admin Only:** All other pipeline endpoints require Casbin permission check
- **Implementation:** `PermissionDep = Depends(deps.check_permission)` on each endpoint

### Dependencies Used
- Casbin for RBAC (Role-Based Access Control)
- JWT tokens with refresh logic
- Server-side auth middleware
- User role check for admin-only menu items

---

END OF EXPLORATION SUMMARY
