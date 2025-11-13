# 🏗️ QLTS - LEAD MANAGEMENT SYSTEM ARCHITECTURE

**Project:** QLTS (Quản Lý Tài Sản) - Lead Management Module
**Date:** 2025-11-13
**Version:** 1.0
**Status:** 📐 ARCHITECTURE DESIGN

---

## 📊 TABLE OF CONTENTS

1. [System Overview Diagram](#1-system-overview-diagram)
2. [Database ER Diagram](#2-database-er-diagram)
3. [Frontend Component Tree](#3-frontend-component-tree)
4. [API Architecture](#4-api-architecture)
5. [Data Flow Diagrams](#5-data-flow-diagrams)
6. [Security Architecture](#6-security-architecture)
7. [Deployment Architecture](#7-deployment-architecture)

---

## 1. SYSTEM OVERVIEW DIAGRAM

### High-Level Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        Browser[Web Browser]
        Mobile[Mobile Browser]
    end

    subgraph "Frontend - Next.js 16"
        NextApp[Next.js App]
        ReactQuery[React Query Cache]
        SocketClient[Socket.IO Client]
        Zustand[Zustand State]
    end

    subgraph "Backend - FastAPI"
        API[FastAPI Server]
        SocketIO[Socket.IO Server]
        Celery[Celery Workers]

        subgraph "Services Layer"
            LeadSvc[Lead Service]
            AssignSvc[Assignment Service]
            InsightSvc[Insights Service]
            PipelineSvc[Pipeline Service]
            ConfigSvc[Config Service]
        end

        subgraph "Core Services"
            AuthSvc[Auth Service]
            CasbinSvc[Casbin Service]
            NotifSvc[Notification Service]
            EmailSvc[Email Service]
        end
    end

    subgraph "Data Layer"
        PostgreSQL[(PostgreSQL)]
        Redis[(Redis Cache)]
        RedisQueue[(Redis Queue)]
    end

    subgraph "External Services"
        Email[SMTP Server]
        Storage[File Storage]
        GeoIP[GeoIP Service]
    end

    Browser --> NextApp
    Mobile --> NextApp

    NextApp --> ReactQuery
    NextApp --> SocketClient
    NextApp --> Zustand

    NextApp -->|HTTP/HTTPS| API
    SocketClient -->|WebSocket| SocketIO

    API --> LeadSvc
    API --> AssignSvc
    API --> InsightSvc
    API --> PipelineSvc
    API --> ConfigSvc

    API --> AuthSvc
    API --> CasbinSvc
    API --> NotifSvc
    API --> EmailSvc

    LeadSvc --> PostgreSQL
    AssignSvc --> PostgreSQL
    InsightSvc --> PostgreSQL
    PipelineSvc --> Redis
    ConfigSvc --> PostgreSQL

    AuthSvc --> PostgreSQL
    CasbinSvc --> PostgreSQL

    API --> Celery
    Celery --> RedisQueue
    Celery --> PostgreSQL

    SocketIO --> Redis
    NotifSvc --> SocketIO
    EmailSvc --> Email

    API --> Storage
    API --> GeoIP

    style NextApp fill:#61dafb
    style API fill:#009688
    style PostgreSQL fill:#336791
    style Redis fill:#dc382d
```

### Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| **Frontend** | Next.js | 16.0 | React framework with SSR |
| | React | 19.2 | UI library |
| | TypeScript | 5.x | Type safety |
| | Tailwind CSS | 4.x | Styling |
| | React Query | 5.90 | Server state management |
| | Zustand | 5.0 | Client state management |
| | Socket.IO Client | 4.8 | Real-time communication |
| | React Hook Form | 7.65 | Form management |
| | Zod | 4.1 | Schema validation |
| **Backend** | FastAPI | Latest | Python web framework |
| | Python | 3.11+ | Programming language |
| | SQLAlchemy | Latest | ORM |
| | Alembic | Latest | Database migrations |
| | Pydantic | Latest | Data validation |
| | Celery | Latest | Background tasks |
| | Socket.IO | Latest | Real-time server |
| | Casbin | Latest | Authorization |
| **Database** | PostgreSQL | 15+ | Primary database |
| | Redis | 7+ | Caching & pub/sub |
| **Testing** | Vitest | 4.0 | Unit/integration tests |
| | Playwright | 1.56 | E2E tests |
| | MSW | 2.8 | API mocking |
| | Pytest | Latest | Backend tests |

---

## 2. DATABASE ER DIAGRAM

### Lead Management Schema

```mermaid
erDiagram
    %% Core Tables
    USER ||--o{ LEAD : "assigned_to"
    USER ||--o{ CONSULTATION : "handles"
    USER ||--o{ APPLICATION : "handles"
    USER ||--o{ ASSIGNMENT_LOG : "assigned_by"

    ORGANIZATION_UNIT ||--o{ LEAD : "belongs_to"
    PROGRAM_OFFERING ||--o{ LEAD : "interested_in"

    LEAD ||--o{ CONSULTATION : "has"
    LEAD ||--o{ CRM_INTERACTION : "has"
    LEAD ||--o{ ASSIGNMENT_LOG : "has"
    LEAD ||--o| APPLICATION : "submits"
    LEAD ||--o{ LEAD_STATUS_HISTORY : "has"

    PIPELINE_STAGE ||--o{ LEAD : "in_stage"
    CONSULTATION_STATUS ||--o{ LEAD : "has_status"
    CONSULTATION_STATUS ||--o{ CONSULTATION : "has_status"
    PIPELINE_STAGE ||--o{ CONSULTATION_STATUS : "contains"

    %% Configuration Tables
    LEAD_SCORING_CONFIG ||--o{ LEAD : "scores"
    OFFICER_ASSIGNMENT_CONFIG ||--o{ USER : "configures"
    SKILL_REQUIREMENT_RULE ||--o{ PROGRAM_OFFERING : "requires"

    %% Entities

    USER {
        int id PK
        string username UK
        string email UK
        string password_hash
        string full_name
        string role
        string availability_status
        int max_capacity
        datetime created_at
    }

    LEAD {
        int id PK
        string full_name
        string email
        string phone
        string source
        string status
        int lead_score
        string education_level
        float gpa
        string location
        int officer_rating
        text officer_summary
        datetime created_at
        datetime updated_at
        datetime assigned_at
        int offering_id FK
        int unit_id FK
        int assigned_officer_id FK
        string consultation_status_id FK
        string pipeline_stage_id FK
    }

    CONSULTATION {
        int id PK
        int lead_id FK
        datetime consultation_date
        string method
        text notes
        string outcome
        int duration_minutes
        int officer_id FK
        string consultation_status_id FK
    }

    APPLICATION {
        int id PK
        int lead_id FK UK
        json documents
        string status
        int officer_id FK
    }

    CRM_INTERACTION {
        int id PK
        int lead_id FK
        string type
        json details
        datetime created_at
    }

    ASSIGNMENT_LOG {
        int id PK
        int lead_id FK
        string method
        datetime timestamp
        text reason
        int officer_id FK
    }

    LEAD_STATUS_HISTORY {
        int id PK
        int lead_id FK
        string old_status
        string new_status
        datetime changed_at
        int changed_by FK
        text reason
    }

    PIPELINE_STAGE {
        string id PK
        string name
        int order UK
    }

    CONSULTATION_STATUS {
        string id PK
        string name
        string color_code
        string stage_id FK
    }

    ORGANIZATION_UNIT {
        int id PK
        string name
        string code UK
        int parent_id FK
        string type
    }

    PROGRAM_OFFERING {
        int id PK
        string name
        string code UK
        int major_id FK
        string level
        int duration_months
    }

    LEAD_SCORING_CONFIG {
        int id PK
        string name
        json rules
        boolean is_active
        datetime created_at
    }

    OFFICER_ASSIGNMENT_CONFIG {
        int id PK
        int officer_id FK
        json preferences
        int max_capacity
        boolean auto_assign_enabled
    }

    SKILL_REQUIREMENT_RULE {
        int id PK
        int offering_id FK
        string required_skill
        int priority
    }
```

### Key Relationships

1. **Lead → User (assigned_officer_id)**
   - Many-to-One: Multiple leads can be assigned to one officer
   - Nullable: Leads can be unassigned

2. **Lead → PipelineStage (pipeline_stage_id)**
   - Many-to-One: Multiple leads in each pipeline stage
   - Required: All leads must be in a stage

3. **Lead → Consultation**
   - One-to-Many: A lead can have multiple consultations
   - Cascade delete: Consultations deleted when lead is deleted

4. **Lead → Application**
   - One-to-One: Each lead can have at most one application
   - Unique constraint on lead_id

5. **PipelineStage → ConsultationStatus**
   - One-to-Many: Each stage can have multiple statuses
   - Example: "Consultation Scheduled" stage has statuses: pending, completed, cancelled

---

## 3. FRONTEND COMPONENT TREE

### Application Structure

```mermaid
graph TB
    subgraph "App Layout"
        RootLayout[app/layout.tsx]
        RootLayout --> Providers[Providers]
        RootLayout --> DashboardLayout[app/dashboard/layout.tsx]
    end

    subgraph "Providers"
        Providers --> QueryClientProvider
        Providers --> AuthProvider
        Providers --> ThemeProvider
        Providers --> SocketProvider
        Providers --> ToastProvider
    end

    subgraph "Lead Pages"
        DashboardLayout --> LeadListPage[leads/page.tsx]
        DashboardLayout --> LeadDetailPage[leads/[id]/page.tsx]
        DashboardLayout --> PipelinePage[leads/pipeline/page.tsx]
        DashboardLayout --> InsightsPage[leads/insights/page.tsx]
    end

    subgraph "Lead List Components"
        LeadListPage --> LeadListTable
        LeadListPage --> LeadFilters
        LeadListPage --> LeadBulkActions
        LeadListPage --> LeadCreateDialog

        LeadListTable --> LeadRow
        LeadRow --> LeadQuickActions
        LeadRow --> LeadScoreBadge
        LeadRow --> StatusBadge

        LeadFilters --> MultiSelect
        LeadFilters --> DateRangePicker
        LeadFilters --> SearchInput
    end

    subgraph "Lead Detail Components"
        LeadDetailPage --> LeadDetailHeader
        LeadDetailPage --> TabsComponent[Tabs]

        TabsComponent --> OverviewTab
        TabsComponent --> TimelineTab
        TabsComponent --> ConsultationsTab
        TabsComponent --> InsightsTab

        OverviewTab --> LeadInfoCard
        OverviewTab --> ContactCard
        OverviewTab --> ProgramCard
        OverviewTab --> AssignmentCard

        TimelineTab --> TimelineList
        TimelineList --> TimelineItem

        ConsultationsTab --> ConsultationList
        ConsultationsTab --> ConsultationDialog
        ConsultationList --> ConsultationCard

        InsightsTab --> ScoreBreakdown
        InsightsTab --> EngagementMetrics
        InsightsTab --> RecommendedActions
        InsightsTab --> InsightsChart
    end

    subgraph "Pipeline Components"
        PipelinePage --> PipelineBoard
        PipelineBoard --> PipelineColumn
        PipelineColumn --> LeadCard
        PipelineBoard --> PipelineFilters
        PipelineColumn --> StageStats

        LeadCard --> DragHandle
        LeadCard --> LeadScoreBadge
    end

    subgraph "Insights Components"
        InsightsPage --> MetricCards
        InsightsPage --> LeadsOverTimeChart
        InsightsPage --> LeadsBySourceChart
        InsightsPage --> PipelineFunnelChart
        InsightsPage --> OfficerPerformanceTable
    end

    subgraph "Shared Dialogs"
        LeadCreateDialog --> LeadForm
        LeadEditDialog --> LeadForm
        LeadAssignDialog --> OfficerSelector
        ConsultationDialog --> ConsultationForm
        LeadImportDialog --> FileUploader
        LeadExportDialog --> ColumnSelector
    end

    subgraph "UI Components shadcn"
        Button
        Input
        Select
        Dialog
        Table
        Tabs
        Badge
        Card
        Form
        Popover
        Dropdown
    end

    LeadForm --> Input
    LeadForm --> Select
    LeadForm --> Button

    style LeadListPage fill:#e3f2fd
    style LeadDetailPage fill:#e3f2fd
    style PipelinePage fill:#e3f2fd
    style InsightsPage fill:#e3f2fd
```

### Component File Structure

```
frontend/src/
├── app/
│   ├── layout.tsx                          # Root layout
│   ├── providers.tsx                       # All providers
│   └── (dashboard)/
│       ├── layout.tsx                      # Dashboard layout
│       └── leads/
│           ├── page.tsx                    # Lead list page
│           ├── [id]/
│           │   └── page.tsx                # Lead detail page
│           ├── pipeline/
│           │   └── page.tsx                # Pipeline kanban
│           └── insights/
│               └── page.tsx                # Insights dashboard
│
├── components/
│   ├── ui/                                 # shadcn/ui components
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   ├── select.tsx
│   │   ├── dialog.tsx
│   │   ├── table.tsx
│   │   ├── tabs.tsx
│   │   ├── badge.tsx
│   │   └── ...
│   │
│   └── leads/                              # Lead-specific components
│       ├── LeadListTable.tsx              # Data table
│       ├── LeadFilters.tsx                # Filter sidebar
│       ├── LeadBulkActions.tsx            # Bulk actions toolbar
│       ├── LeadQuickActions.tsx           # Row actions
│       ├── LeadDetailHeader.tsx           # Detail page header
│       ├── LeadOverviewTab.tsx            # Overview tab
│       ├── LeadTimelineTab.tsx            # Timeline tab
│       ├── LeadConsultationsTab.tsx       # Consultations tab
│       ├── LeadInsightsTab.tsx            # Insights tab
│       ├── LeadInfoCard.tsx               # Lead info card
│       ├── TimelineItem.tsx               # Timeline event
│       ├── ConsultationCard.tsx           # Consultation card
│       ├── InsightsChart.tsx              # Insights charts
│       ├── LeadCreateDialog.tsx           # Create dialog
│       ├── LeadEditDialog.tsx             # Edit dialog
│       ├── LeadAssignDialog.tsx           # Assign dialog
│       ├── ConsultationDialog.tsx         # Consultation dialog
│       ├── LeadImportDialog.tsx           # Import dialog
│       ├── LeadExportDialog.tsx           # Export dialog
│       ├── PipelineBoard.tsx              # Kanban board
│       ├── PipelineColumn.tsx             # Kanban column
│       ├── LeadCard.tsx                   # Kanban card
│       ├── PipelineFilters.tsx            # Pipeline filters
│       └── StageStats.tsx                 # Stage statistics
│
├── hooks/
│   ├── useLeads.ts                        # Lead list hooks
│   ├── useLead.ts                         # Single lead hooks
│   ├── useLeadAssignment.ts               # Assignment hooks
│   ├── useConsultations.ts                # Consultation hooks
│   ├── usePipeline.ts                     # Pipeline hooks
│   └── useLeadInsights.ts                 # Insights hooks
│
├── lib/
│   ├── api/
│   │   ├── client.ts                      # Axios client
│   │   ├── leads.ts                       # Lead API
│   │   └── pipeline.ts                    # Pipeline API
│   │
│   ├── stores/
│   │   ├── auth.store.ts                  # Auth state
│   │   └── ui.store.ts                    # UI state
│   │
│   └── utils/
│       ├── cn.ts                          # Class name utils
│       ├── format.ts                      # Formatters
│       └── validation.ts                  # Validators
│
└── types/
    ├── lead.types.ts                      # Lead types
    └── pipeline.types.ts                  # Pipeline types
```

---

## 4. API ARCHITECTURE

### API Endpoint Structure

```mermaid
graph LR
    subgraph "API Routes"
        Root[/api]

        Root --> Auth[/auth]
        Root --> Leads[/leads]
        Root --> Pipeline[/pipeline]
        Root --> Admin[/admin]

        Auth --> Login[POST /login]
        Auth --> Logout[POST /logout]
        Auth --> Refresh[POST /refresh]
        Auth --> Me[GET /me]

        Leads --> LeadsCRUD[CRUD Operations]
        Leads --> LeadsActions[Actions]
        Leads --> LeadsData[Data Access]

        LeadsCRUD --> CreateLead[POST /]
        LeadsCRUD --> GetLeads[GET /]
        LeadsCRUD --> GetLead[GET /:id]
        LeadsCRUD --> UpdateLead[PUT /:id]

        LeadsActions --> AssignLead[POST /:id/assign]
        LeadsActions --> LeadAction[POST /:id/action]
        LeadsActions --> AddConsult[POST /:id/consultations]

        LeadsData --> Timeline[GET /:id/timeline]
        LeadsData --> Insights[GET /:id/insights]

        Pipeline --> GetStages[GET /stages]
        Pipeline --> GetFull[GET /all]

        Admin --> AdminLeads[/leads]
        Admin --> AdminPipeline[/pipeline-stages]
        Admin --> AdminConfig[/config]

        AdminLeads --> BulkAssign[POST /bulk-assign]
        AdminLeads --> ImportLeads[POST /import]
        AdminLeads --> ExportLeads[GET /export]

        AdminPipeline --> CreateStage[POST /]
        AdminPipeline --> UpdateStage[PUT /:id]
        AdminPipeline --> DeleteStage[DELETE /:id]
    end

    style Root fill:#4CAF50
    style Auth fill:#2196F3
    style Leads fill:#FF9800
    style Pipeline fill:#9C27B0
    style Admin fill:#F44336
```

### API Request/Response Flow

```mermaid
sequenceDiagram
    participant Client
    participant NextJS as Next.js Frontend
    participant API as FastAPI Backend
    participant DB as PostgreSQL
    participant Cache as Redis
    participant Queue as Celery Queue

    %% GET Request Flow
    Client->>NextJS: User opens Lead List
    NextJS->>API: GET /api/leads?page=1&page_size=10
    API->>Cache: Check cache
    alt Cache Hit
        Cache-->>API: Cached data
    else Cache Miss
        API->>DB: Query leads
        DB-->>API: Lead data
        API->>Cache: Store in cache
    end
    API-->>NextJS: 200 OK + LeadsPage
    NextJS-->>Client: Render lead list

    %% POST Request Flow
    Client->>NextJS: User creates new lead
    NextJS->>API: POST /api/leads + LeadCreate
    API->>API: Validate data (Pydantic)
    API->>DB: INSERT lead
    DB-->>API: Created lead
    API->>Cache: Invalidate cache
    API->>Queue: Queue auto-assignment task
    Queue->>DB: Assign lead to officer
    API-->>NextJS: 201 Created + Lead
    NextJS-->>Client: Show success toast

    %% Real-time Update Flow
    Queue->>DB: Lead assigned
    Queue->>API: Trigger notification
    API->>Cache: Publish event
    Cache-->>NextJS: WebSocket push
    NextJS-->>Client: Update UI (lead status changed)
```

### Middleware Stack

```mermaid
graph TB
    Request[HTTP Request]

    Request --> CORS[CORS Middleware]
    CORS --> RateLimit[Rate Limiter]
    RateLimit --> Auth[Authentication]
    Auth --> Casbin[Authorization Casbin]
    Casbin --> IDOR[IDOR Protection]
    IDOR --> Endpoint[API Endpoint]

    Endpoint --> Response[HTTP Response]

    style Request fill:#e3f2fd
    style Response fill:#c8e6c9
    style Auth fill:#fff3e0
    style Casbin fill:#fce4ec
```

---

## 5. DATA FLOW DIAGRAMS

### Lead Creation Flow

```mermaid
flowchart TD
    Start([User Clicks Create Lead]) --> OpenDialog[Open LeadCreateDialog]
    OpenDialog --> FillForm[User Fills Form]
    FillForm --> Validate{Form Valid?}

    Validate -->|No| ShowErrors[Show Validation Errors]
    ShowErrors --> FillForm

    Validate -->|Yes| Submit[Submit Form]
    Submit --> APICall[POST /api/leads]

    APICall --> BackendValidate{Backend Validation}

    BackendValidate -->|Fail| ShowAPIErrors[Show API Errors]
    ShowAPIErrors --> FillForm

    BackendValidate -->|Pass| SaveDB[(Save to Database)]
    SaveDB --> CalcScore[Calculate Lead Score]
    CalcScore --> QueueAssignment[Queue Auto-Assignment]

    QueueAssignment --> InvalidateCache[Invalidate React Query Cache]
    InvalidateCache --> EmitEvent[Emit Socket.IO Event]

    EmitEvent --> ShowSuccess[Show Success Toast]
    ShowSuccess --> CloseDialog[Close Dialog]
    CloseDialog --> RefreshList[Refresh Lead List]

    RefreshList --> End([End])

    style Start fill:#4CAF50
    style End fill:#4CAF50
    style SaveDB fill:#2196F3
    style ShowErrors fill:#F44336
    style ShowSuccess fill:#8BC34A
```

### Lead Assignment Flow

```mermaid
flowchart TD
    Start([Lead Created/Assigned]) --> CheckAutoAssign{Auto-Assignment Enabled?}

    CheckAutoAssign -->|No| ManualAssign[Wait for Manual Assignment]
    ManualAssign --> End([End])

    CheckAutoAssign -->|Yes| CeleryTask[Celery Background Task]
    CeleryTask --> GetConfig[Get Assignment Config]
    GetConfig --> GetRequirements[Get Skill Requirements]

    GetRequirements --> FindOfficers[Find Available Officers]
    FindOfficers --> FilterSkills[Filter by Required Skills]

    FilterSkills --> HasSkilled{Officers Found?}

    HasSkilled -->|No| Fallback[Fallback: Get All Available]
    Fallback --> CheckAvailable{Any Available?}

    HasSkilled -->|Yes| CheckWorkload[Calculate Workload]
    CheckWorkload --> SortByWorkload[Sort by Least Workload]
    SortByWorkload --> SelectOfficer[Select Officer]

    CheckAvailable -->|No| MarkUnassigned[Mark as Unassigned]
    MarkUnassigned --> NotifyAdmin[Notify Admin]
    NotifyAdmin --> End

    CheckAvailable -->|Yes| SelectOfficer

    SelectOfficer --> AssignLead[(Update Lead in DB)]
    AssignLead --> LogAssignment[(Create Assignment Log)]
    LogAssignment --> UpdateStatus[Set Status to Assigned]

    UpdateStatus --> EmitEvent[Emit Socket Event]
    EmitEvent --> NotifyOfficer[Notify Officer]
    NotifyOfficer --> SendEmail[Send Email]

    SendEmail --> End

    style Start fill:#4CAF50
    style End fill:#4CAF50
    style CeleryTask fill:#FF9800
    style AssignLead fill:#2196F3
    style NotifyAdmin fill:#F44336
```

### Pipeline Stage Movement

```mermaid
flowchart TD
    Start([User Drags Lead Card]) --> Drop[Drop in New Stage]
    Drop --> ValidatePermission{Has Permission?}

    ValidatePermission -->|No| ShowError[Show Permission Error]
    ShowError --> Revert[Revert to Original Position]
    Revert --> End([End])

    ValidatePermission -->|Yes| OptimisticUpdate[Optimistic UI Update]
    OptimisticUpdate --> APICall[PUT /api/leads/:id]

    APICall --> UpdateDB[(Update pipeline_stage_id)]
    UpdateDB --> CreateHistory[(Create Status History)]
    CreateHistory --> CheckTrigger{Stage Has Trigger?}

    CheckTrigger -->|No| EmitEvent[Emit Socket Event]

    CheckTrigger -->|Yes| ExecuteTrigger[Execute Trigger]
    ExecuteTrigger --> TriggerType{Trigger Type}

    TriggerType -->|Email| SendEmail[Send Email Notification]
    TriggerType -->|Task| CreateTask[Create Follow-up Task]
    TriggerType -->|Webhook| CallWebhook[Call External Webhook]

    SendEmail --> EmitEvent
    CreateTask --> EmitEvent
    CallWebhook --> EmitEvent

    EmitEvent --> InvalidateCache[Invalidate Query Cache]
    InvalidateCache --> UpdateStats[Update Pipeline Stats]
    UpdateStats --> ShowSuccess[Show Success Toast]

    ShowSuccess --> End

    style Start fill:#4CAF50
    style End fill:#4CAF50
    style OptimisticUpdate fill:#FFC107
    style UpdateDB fill:#2196F3
```

---

## 6. SECURITY ARCHITECTURE

### Authentication & Authorization Flow

```mermaid
sequenceDiagram
    participant Client
    participant Frontend
    participant API
    participant Casbin
    participant DB
    participant Redis

    %% Login Flow
    Client->>Frontend: Enter credentials
    Frontend->>API: POST /auth/login
    API->>DB: Verify credentials
    DB-->>API: User data
    API->>API: Generate tokens
    API->>Redis: Store refresh token
    API-->>Frontend: Set httpOnly cookies
    Frontend-->>Client: Redirect to dashboard

    %% Authorized Request Flow
    Client->>Frontend: Access protected resource
    Frontend->>API: GET /api/leads (with cookie)
    API->>API: Extract token from cookie
    API->>API: Verify access token

    alt Token Valid
        API->>Casbin: Check permission (user, resource, action)
        Casbin->>DB: Load policies
        DB-->>Casbin: Policies data
        Casbin-->>API: Permission result

        alt Has Permission
            API->>DB: Query data
            DB-->>API: Resource data
            API-->>Frontend: 200 OK + Data
            Frontend-->>Client: Display data
        else No Permission
            API-->>Frontend: 403 Forbidden
            Frontend-->>Client: Show error
        end
    else Token Invalid/Expired
        API-->>Frontend: 401 Unauthorized
        Frontend->>API: POST /auth/refresh (with refresh cookie)
        API->>Redis: Verify refresh token
        Redis-->>API: Token valid
        API->>API: Generate new access token
        API-->>Frontend: Set new cookie
        Frontend->>API: Retry original request
        API-->>Frontend: 200 OK + Data
        Frontend-->>Client: Display data
    end
```

### Permission Matrix

```mermaid
graph LR
    subgraph "Roles"
        Admin[Admin]
        Manager[Manager]
        Officer[Officer]
    end

    subgraph "Resources"
        LeadRead[lead:read]
        LeadWrite[lead:write]
        LeadAssign[lead:assign]
        LeadDelete[lead:delete]

        ConsultRead[consultation:read]
        ConsultWrite[consultation:write]

        PipelineRead[pipeline:read]
        PipelineWrite[pipeline:write]

        ConfigRead[config:read]
        ConfigWrite[config:write]
    end

    Admin --> LeadRead
    Admin --> LeadWrite
    Admin --> LeadAssign
    Admin --> LeadDelete
    Admin --> ConsultRead
    Admin --> ConsultWrite
    Admin --> PipelineRead
    Admin --> PipelineWrite
    Admin --> ConfigRead
    Admin --> ConfigWrite

    Manager --> LeadRead
    Manager --> LeadWrite
    Manager --> LeadAssign
    Manager --> ConsultRead
    Manager --> ConsultWrite
    Manager --> PipelineRead
    Manager --> ConfigRead

    Officer --> LeadRead
    Officer --> ConsultRead
    Officer --> ConsultWrite
    Officer --> PipelineRead

    style Admin fill:#F44336
    style Manager fill:#FF9800
    style Officer fill:#4CAF50
```

### IDOR Protection

```mermaid
flowchart TD
    Request[API Request: GET /api/leads/123] --> ExtractID[Extract lead_id: 123]
    ExtractID --> GetUser[Get current_user from token]
    GetUser --> CheckOwnership{User owns lead OR Has permission?}

    CheckOwnership -->|No| Return403[403 Forbidden]
    Return403 --> End([End])

    CheckOwnership -->|Yes| GetLead[(Query lead from DB)]
    GetLead --> LeadExists{Lead exists?}

    LeadExists -->|No| Return404[404 Not Found]
    Return404 --> End

    LeadExists -->|Yes| CheckUnit{Lead.unit_id == User.unit_id?}

    CheckUnit -->|No| CheckRole{User is Admin/Manager?}
    CheckRole -->|No| Return403
    CheckRole -->|Yes| ReturnLead

    CheckUnit -->|Yes| ReturnLead[200 OK + Lead data]
    ReturnLead --> End

    style Request fill:#e3f2fd
    style Return403 fill:#ffcdd2
    style Return404 fill:#fff9c4
    style ReturnLead fill:#c8e6c9
```

---

## 7. DEPLOYMENT ARCHITECTURE

### Production Infrastructure

```mermaid
graph TB
    subgraph "CDN & DNS"
        DNS[Cloudflare DNS]
        CDN[Cloudflare CDN]
    end

    subgraph "Load Balancer"
        LB[Nginx Load Balancer]
    end

    subgraph "Frontend Servers"
        NextJS1[Next.js Server 1]
        NextJS2[Next.js Server 2]
        NextJS3[Next.js Server 3]
    end

    subgraph "Backend Servers"
        FastAPI1[FastAPI Server 1]
        FastAPI2[FastAPI Server 2]
        FastAPI3[FastAPI Server 3]
    end

    subgraph "Background Workers"
        Celery1[Celery Worker 1]
        Celery2[Celery Worker 2]
        Celery3[Celery Worker 3]
    end

    subgraph "Database Cluster"
        PG_Primary[(PostgreSQL Primary)]
        PG_Replica1[(PostgreSQL Replica 1)]
        PG_Replica2[(PostgreSQL Replica 2)]
    end

    subgraph "Cache Cluster"
        Redis_Master[(Redis Master)]
        Redis_Replica1[(Redis Replica 1)]
        Redis_Replica2[(Redis Replica 2)]
    end

    subgraph "Monitoring"
        Sentry[Sentry Error Tracking]
        Grafana[Grafana Metrics]
        Prometheus[Prometheus]
    end

    subgraph "Backups"
        S3[AWS S3 Backups]
    end

    DNS --> CDN
    CDN --> LB

    LB --> NextJS1
    LB --> NextJS2
    LB --> NextJS3

    NextJS1 --> FastAPI1
    NextJS2 --> FastAPI2
    NextJS3 --> FastAPI3

    FastAPI1 --> PG_Primary
    FastAPI2 --> PG_Replica1
    FastAPI3 --> PG_Replica2

    FastAPI1 --> Redis_Master
    FastAPI2 --> Redis_Master
    FastAPI3 --> Redis_Master

    PG_Primary --> PG_Replica1
    PG_Primary --> PG_Replica2

    Redis_Master --> Redis_Replica1
    Redis_Master --> Redis_Replica2

    Celery1 --> PG_Primary
    Celery2 --> PG_Primary
    Celery3 --> PG_Primary

    Celery1 --> Redis_Master
    Celery2 --> Redis_Master
    Celery3 --> Redis_Master

    PG_Primary --> S3

    NextJS1 --> Sentry
    FastAPI1 --> Sentry

    FastAPI1 --> Prometheus
    Prometheus --> Grafana

    style DNS fill:#FF6B35
    style LB fill:#004E89
    style PG_Primary fill:#336791
    style Redis_Master fill:#dc382d
```

### Container Architecture (Docker)

```mermaid
graph TB
    subgraph "Docker Compose Stack"
        subgraph "Web Services"
            Frontend[frontend:latest<br/>Next.js 16<br/>Port 3000]
            Backend[backend:latest<br/>FastAPI<br/>Port 8000]
        end

        subgraph "Worker Services"
            Celery[celery-worker:latest<br/>Background Tasks]
            Beat[celery-beat:latest<br/>Scheduler]
        end

        subgraph "Data Services"
            Postgres[(postgres:15<br/>Port 5432)]
            Redis[(redis:7-alpine<br/>Port 6379)]
        end

        subgraph "Support Services"
            Nginx[nginx:alpine<br/>Reverse Proxy<br/>Port 80/443]
            Mailhog[mailhog:latest<br/>Email Testing<br/>Port 8025]
        end
    end

    Nginx --> Frontend
    Nginx --> Backend

    Frontend --> Backend
    Backend --> Postgres
    Backend --> Redis

    Celery --> Postgres
    Celery --> Redis
    Beat --> Redis

    Backend --> Mailhog
    Celery --> Mailhog

    style Frontend fill:#61dafb
    style Backend fill:#009688
    style Postgres fill:#336791
    style Redis fill:#dc382d
```

### CI/CD Pipeline

```mermaid
flowchart LR
    subgraph "Development"
        Dev[Developer Push]
        Git[GitHub Repo]
    end

    subgraph "CI Pipeline"
        Lint[Linting<br/>ESLint/Ruff]
        Test[Unit Tests<br/>Vitest/Pytest]
        Build[Build<br/>Docker Images]
        Scan[Security Scan<br/>Trivy]
    end

    subgraph "CD Pipeline"
        Push[Push to Registry<br/>Docker Hub]
        DeployStaging[Deploy to Staging]
        E2E[E2E Tests<br/>Playwright]
        DeployProd[Deploy to Production]
    end

    subgraph "Monitoring"
        Health[Health Checks]
        Metrics[Collect Metrics]
        Alerts[Send Alerts]
    end

    Dev --> Git
    Git --> Lint
    Lint --> Test
    Test --> Build
    Build --> Scan

    Scan --> Push
    Push --> DeployStaging
    DeployStaging --> E2E

    E2E -->|Pass| DeployProd
    E2E -->|Fail| Alerts

    DeployProd --> Health
    Health --> Metrics
    Metrics --> Alerts

    style Dev fill:#4CAF50
    style DeployProd fill:#2196F3
    style Alerts fill:#F44336
```

---

## 📚 REFERENCES

### External Documentation

- **Next.js:** https://nextjs.org/docs
- **FastAPI:** https://fastapi.tiangolo.com/
- **React Query:** https://tanstack.com/query/latest
- **Casbin:** https://casbin.org/docs/overview
- **Socket.IO:** https://socket.io/docs/v4/
- **PostgreSQL:** https://www.postgresql.org/docs/
- **Redis:** https://redis.io/docs/
- **Mermaid Diagrams:** https://mermaid.js.org/

### Internal Documentation

- `LEAD_MANAGEMENT_IMPLEMENTATION_PLAN.md` - Original implementation plan
- `LEAD_MANAGEMENT_PLAN_REVIEW.md` - Plan review & recommendations
- `BACKEND_VERIFICATION_REPORT.md` - Backend verification results
- `TESTING_INFRASTRUCTURE_SETUP.md` - Testing setup documentation
- `frontend/src/test/README.md` - Testing guide

---

## 📝 NOTES

### Diagram Rendering

These diagrams use **Mermaid** syntax and can be rendered in:
- GitHub (native support)
- VS Code (with Mermaid extension)
- Notion (with Mermaid integration)
- Obsidian (with Mermaid plugin)
- Online: https://mermaid.live/

### Updating Diagrams

When system architecture changes:
1. Update relevant diagrams in this file
2. Commit changes with descriptive message
3. Notify team via Slack/Email
4. Update API documentation if needed

---

**Document Version:** 1.0
**Last Updated:** 2025-11-13
**Maintained By:** Development Team
**Status:** ✅ COMPLETE
