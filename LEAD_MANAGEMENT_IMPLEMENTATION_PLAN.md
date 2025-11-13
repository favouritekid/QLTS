# 📋 KẾ HOẠCH TRIỂN KHAI LEAD MANAGEMENT

**Date:** 2025-11-04  
**Project:** QLTS (Quản Lý Tài Sản) - Lead Management System  
**Status:** 🟡 PLANNING PHASE

---

## 📊 PHÂN TÍCH HIỆN TRẠNG

### ✅ **Backend - ĐÃ CÓ SẴN (90% hoàn thành)**

#### **1. Database Models (✅ HOÀN CHỈNH)**

**Core Models:**
- ✅ `Lead` - Model chính cho học viên tiềm năng
  - Thông tin cơ bản: full_name, email, phone, source
  - Lead scoring: lead_score (0-100)
  - Status tracking: status, pipeline_stage_id
  - Assignment: assigned_officer_id, assigned_at
  - Relationships: consultations, application, interactions, assignment_logs

- ✅ `Consultation` - Buổi tư vấn
  - consultation_date, method, notes, outcome
  - duration_minutes, officer_id
  - consultation_status_id

- ✅ `Application` - Hồ sơ nhập học
  - documents (JSON), status
  - officer_id, lead_id (unique)

- ✅ `CRMInteraction` - Tương tác CRM tự động
  - type, details (JSON), created_at

- ✅ `AssignmentLog` - Lịch sử phân công
  - method, timestamp, reason, officer_id

**Supporting Models:**
- ✅ `PipelineStage` - Giai đoạn trong pipeline
- ✅ `ConsultationStatus` - Trạng thái tư vấn
- ✅ `LeadStatusHistory` - Lịch sử thay đổi trạng thái
- ✅ `LeadScoringConfig` - Cấu hình tính điểm
- ✅ `OfficerAssignmentConfig` - Cấu hình phân công
- ✅ `SkillRequirementRule` - Quy tắc kỹ năng

**Organization Models:**
- ✅ `OrganizationUnit` - Đơn vị tổ chức (phòng ban, khoa)
- ✅ `MajorProgram` - Chương trình đào tạo (Level 1)
- ✅ `ProgramOffering` - Khóa học cụ thể (Level 2)
- ✅ `OfferingAcademicInfo` - Thông tin học thuật (Level 3)

---

#### **2. API Endpoints (✅ HOÀN CHỈNH)**

**Lead CRUD:**
- ✅ `POST /api/leads` - Tạo lead mới
- ✅ `GET /api/leads` - Danh sách leads (pagination, filter, search, sort)
- ✅ `GET /api/leads/{lead_id}` - Chi tiết lead
- ✅ `PUT /api/leads/{lead_id}` - Cập nhật lead

**Lead Actions:**
- ✅ `POST /api/leads/{lead_id}/assign` - Phân công lead
- ✅ `POST /api/leads/bulk-assign` - Phân công hàng loạt
- ✅ `POST /api/leads/{lead_id}/action` - Xử lý action (reject/reassign)
- ✅ `POST /api/leads/{lead_id}/consultations` - Thêm buổi tư vấn
- ✅ `GET /api/leads/{lead_id}/timeline` - Lịch sử timeline
- ✅ `GET /api/leads/{lead_id}/insights` - Insights 360 độ

**Import/Export:**
- ✅ `POST /api/leads/import` - Import leads từ CSV/Excel
- ✅ `GET /api/leads/export` - Export leads ra CSV

**Pipeline Management:**
- ✅ `GET /api/pipeline/stages` - Danh sách stages
- ✅ `POST /api/pipeline/stages` - Tạo stage mới
- ✅ `GET /api/pipeline/full` - Full pipeline với stats

---

#### **3. Services Layer (✅ HOÀN CHỈNH)**

**Core Services:**
- ✅ `lead_service.py` - CRUD, assignment, actions, timeline
- ✅ `assignment_service.py` - Auto-assignment logic
- ✅ `insights_service.py` - Lead insights & analytics
- ✅ `pipeline_service.py` - Pipeline management
- ✅ `config_service.py` - Configuration management

**Supporting Services:**
- ✅ `notification_service.py` - Real-time notifications
- ✅ `email_service.py` - Email notifications
- ✅ `activity_service.py` - Activity logging
- ✅ `casbin_service.py` - Permission management

---

#### **4. Features (✅ HOÀN CHỈNH)**

**Lead Scoring:**
- ✅ Automatic scoring based on configurable rules
- ✅ Score factors: education_level, GPA, source, location
- ✅ Dynamic recalculation on update

**Auto-Assignment:**
- ✅ Skill-based matching
- ✅ Workload balancing (max_capacity)
- ✅ Availability status check
- ✅ Round-robin fallback

**Permission System:**
- ✅ Casbin-based RBAC
- ✅ Resource-level permissions (lead:read, lead:write, lead:assign)
- ✅ IDOR protection (get_lead_for_user dependency)

**Real-time Features:**
- ✅ Socket.IO integration
- ✅ Real-time notifications
- ✅ Data invalidation events

---

### ❌ **Frontend - CHƯA CÓ (0% hoàn thành)**

**Missing Components:**
- ❌ Lead list page
- ❌ Lead detail page
- ❌ Lead create/edit forms
- ❌ Lead assignment UI
- ❌ Consultation management
- ❌ Pipeline kanban board
- ❌ Lead insights dashboard
- ❌ Import/export UI

**Missing Hooks:**
- ❌ useLeads (list, filter, search)
- ❌ useLead (detail, CRUD)
- ❌ useLeadAssignment
- ❌ useConsultations
- ❌ usePipeline
- ❌ useLeadInsights

**Missing API Clients:**
- ❌ leads.ts (API client)
- ❌ pipeline.ts (API client)

---

## 🎯 KẾ HOẠCH TRIỂN KHAI

### **PHASE 1: Foundation (Week 1)**

#### **Task 1.1: API Client & Types**
**Priority:** 🔴 CRITICAL  
**Estimated Time:** 4 hours

**Files to create:**
1. `frontend/src/lib/api/leads.ts` - Lead API client
2. `frontend/src/lib/api/pipeline.ts` - Pipeline API client
3. `frontend/src/types/lead.types.ts` - Lead TypeScript types
4. `frontend/src/types/pipeline.types.ts` - Pipeline TypeScript types

**API Endpoints to implement:**
```typescript
// leads.ts
export const leadsApi = {
  getLeads: (params: LeadListParams) => Promise<LeadsPage>
  getLead: (id: number) => Promise<Lead>
  createLead: (data: LeadCreate) => Promise<Lead>
  updateLead: (id: number, data: LeadUpdate) => Promise<Lead>
  assignLead: (id: number, data: AssignLead) => Promise<Lead>
  bulkAssign: (data: BulkAssignLeads) => Promise<void>
  addConsultation: (leadId: number, data: ConsultationCreate) => Promise<Consultation>
  getTimeline: (leadId: number) => Promise<TimelineItem[]>
  getInsights: (leadId: number) => Promise<LeadInsights>
  importLeads: (file: File) => Promise<LeadImportResult>
  exportLeads: (params: LeadListParams) => Promise<Blob>
}

// pipeline.ts
export const pipelineApi = {
  getStages: () => Promise<PipelineStage[]>
  getFullPipeline: () => Promise<FullPipeline>
  createStage: (data: PipelineStageCreate) => Promise<PipelineStage>
  updateStage: (id: string, data: PipelineStageUpdate) => Promise<PipelineStage>
  deleteStage: (id: string) => Promise<void>
}
```

---

#### **Task 1.2: React Query Hooks**
**Priority:** 🔴 CRITICAL  
**Estimated Time:** 6 hours

**Files to create:**
1. `frontend/src/hooks/useLeads.ts` - Lead list & CRUD hooks
2. `frontend/src/hooks/useLead.ts` - Single lead hooks
3. `frontend/src/hooks/useLeadAssignment.ts` - Assignment hooks
4. `frontend/src/hooks/useConsultations.ts` - Consultation hooks
5. `frontend/src/hooks/usePipeline.ts` - Pipeline hooks
6. `frontend/src/hooks/useLeadInsights.ts` - Insights hooks

**Hooks to implement:**
```typescript
// useLeads.ts
export function useLeadsList(params: LeadListParams)
export function useCreateLead()
export function useUpdateLead()
export function useDeleteLead()
export function useBulkAssignLeads()
export function useImportLeads()
export function useExportLeads()

// useLead.ts
export function useLead(leadId: number)
export function useLeadTimeline(leadId: number)
export function useLeadInsights(leadId: number)

// useLeadAssignment.ts
export function useAssignLead()
export function useReassignLead()
export function useRejectLead()

// useConsultations.ts
export function useConsultations(leadId: number)
export function useCreateConsultation()
export function useUpdateConsultation()

// usePipeline.ts
export function usePipelineStages()
export function useFullPipeline()
export function useCreateStage()
export function useUpdateStage()
export function useDeleteStage()
```

**Features:**
- ✅ Optimistic updates
- ✅ Cache invalidation
- ✅ Error handling
- ✅ Loading states
- ✅ Socket.IO integration (real-time sync)

---

### **PHASE 2: Core UI Components (Week 2)**

#### **Task 2.1: Lead List Page**
**Priority:** 🔴 CRITICAL  
**Estimated Time:** 8 hours

**File:** `frontend/src/app/(dashboard)/leads/page.tsx`

**Features:**
- ✅ Data table with pagination
- ✅ Advanced filters:
  - Status (multi-select)
  - Assigned officer (select)
  - Organization unit (select)
  - Program offering (select)
  - Source (multi-select)
  - Date range (created_at)
- ✅ Search (name, email, phone)
- ✅ Sorting (all columns)
- ✅ Bulk actions:
  - Bulk assign
  - Bulk export
  - Bulk delete (admin only)
- ✅ Quick actions:
  - View details
  - Assign
  - Edit
  - Delete
- ✅ Lead score badge
- ✅ Status badge
- ✅ Pipeline stage indicator

**Components to create:**
1. `LeadListTable.tsx` - Main table component
2. `LeadFilters.tsx` - Filter sidebar
3. `LeadBulkActions.tsx` - Bulk action toolbar
4. `LeadQuickActions.tsx` - Row action menu

---

#### **Task 2.2: Lead Detail Page**
**Priority:** 🔴 CRITICAL  
**Estimated Time:** 10 hours

**File:** `frontend/src/app/(dashboard)/leads/[id]/page.tsx`

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│ Header: Lead Name | Score Badge | Status Badge      │
├─────────────────────────────────────────────────────┤
│ Tabs: Overview | Timeline | Consultations | Insights│
├─────────────────────────────────────────────────────┤
│                                                       │
│  [Tab Content]                                        │
│                                                       │
└─────────────────────────────────────────────────────┘
```

**Tab 1: Overview**
- Lead information card
- Contact information
- Program interest
- Assignment information
- Quick actions (assign, edit, delete)

**Tab 2: Timeline**
- Chronological activity feed
- Status changes
- Consultations
- Assignments
- Interactions

**Tab 3: Consultations**
- List of consultations
- Add consultation form
- Consultation details (date, method, notes, outcome)

**Tab 4: Insights**
- Lead score breakdown
- Engagement metrics
- Conversion probability
- Recommended actions

**Components to create:**
1. `LeadDetailHeader.tsx`
2. `LeadOverviewTab.tsx`
3. `LeadTimelineTab.tsx`
4. `LeadConsultationsTab.tsx`
5. `LeadInsightsTab.tsx`
6. `LeadInfoCard.tsx`
7. `TimelineItem.tsx`
8. `ConsultationCard.tsx`
9. `InsightsChart.tsx`

---

#### **Task 2.3: Lead Forms**
**Priority:** 🔴 CRITICAL  
**Estimated Time:** 6 hours

**Files:**
1. `frontend/src/components/leads/LeadCreateDialog.tsx`
2. `frontend/src/components/leads/LeadEditDialog.tsx`
3. `frontend/src/components/leads/LeadAssignDialog.tsx`
4. `frontend/src/components/leads/ConsultationDialog.tsx`

**LeadCreateDialog:**
- Full name (required)
- Email (required, validated)
- Phone (required, validated)
- Source (select)
- Organization unit (select)
- Program offering (select)
- Education level (select)
- GPA (number input)
- Location (text input)

**LeadEditDialog:**
- Same fields as create
- Pre-filled with current data

**LeadAssignDialog:**
- Officer selection (with skill matching)
- Assignment reason (textarea)
- Auto-assignment option

**ConsultationDialog:**
- Consultation date (datetime picker)
- Method (select: phone, email, in-person, online)
- Notes (textarea)
- Outcome (select)
- Duration (number input)

---

### **PHASE 3: Advanced Features (Week 3)**

#### **Task 3.1: Pipeline Kanban Board**
**Priority:** 🟡 HIGH  
**Estimated Time:** 12 hours

**File:** `frontend/src/app/(dashboard)/leads/pipeline/page.tsx`

**Features:**
- ✅ Drag-and-drop kanban board
- ✅ Columns = Pipeline stages
- ✅ Cards = Leads
- ✅ Drag to move between stages
- ✅ Stage statistics (count, conversion rate)
- ✅ Filter by officer, unit, offering
- ✅ Quick view lead details (modal)
- ✅ Add consultation from card
- ✅ Real-time updates (Socket.IO)

**Libraries:**
- `@dnd-kit/core` - Drag and drop
- `@dnd-kit/sortable` - Sortable lists

**Components:**
1. `PipelineBoard.tsx` - Main kanban board
2. `PipelineColumn.tsx` - Stage column
3. `LeadCard.tsx` - Lead card in kanban
4. `PipelineFilters.tsx` - Filter controls
5. `StageStats.tsx` - Stage statistics

---

#### **Task 3.2: Lead Import/Export**
**Priority:** 🟡 HIGH  
**Estimated Time:** 6 hours

**Files:**
1. `frontend/src/components/leads/LeadImportDialog.tsx`
2. `frontend/src/components/leads/LeadExportDialog.tsx`

**Import Features:**
- File upload (CSV, Excel)
- Column mapping
- Validation preview
- Error handling
- Progress indicator
- Import summary

**Export Features:**
- Format selection (CSV, Excel)
- Column selection
- Filter application
- Download trigger

---

#### **Task 3.3: Lead Insights Dashboard**
**Priority:** 🟡 HIGH  
**Estimated Time:** 8 hours

**File:** `frontend/src/app/(dashboard)/leads/insights/page.tsx`

**Metrics:**
- Total leads
- Conversion rate
- Average lead score
- Leads by source
- Leads by status
- Leads by pipeline stage
- Officer performance
- Response time metrics

**Charts:**
- Line chart: Leads over time
- Pie chart: Leads by source
- Bar chart: Leads by status
- Funnel chart: Pipeline conversion
- Heatmap: Officer workload

**Libraries:**
- `recharts` - Charts library

**Components:**
1. `InsightsDashboard.tsx`
2. `MetricCard.tsx`
3. `LeadsOverTimeChart.tsx`
4. `LeadsBySourceChart.tsx`
5. `PipelineFunnelChart.tsx`
6. `OfficerPerformanceTable.tsx`

---

### **PHASE 4: Polish & Testing (Week 4)**

#### **Task 4.1: UI/UX Polish**
**Priority:** 🟢 MEDIUM  
**Estimated Time:** 6 hours

- ✅ Responsive design (mobile, tablet, desktop)
- ✅ Loading skeletons
- ✅ Empty states
- ✅ Error states
- ✅ Success/error toasts
- ✅ Confirmation dialogs
- ✅ Keyboard shortcuts
- ✅ Accessibility (ARIA labels, focus management)

---

#### **Task 4.2: Testing**
**Priority:** 🟢 MEDIUM  
**Estimated Time:** 8 hours

**Unit Tests:**
- API client functions
- React Query hooks
- Utility functions

**Integration Tests:**
- Lead CRUD flow
- Assignment flow
- Consultation flow
- Import/export flow

**E2E Tests:**
- Create lead → Assign → Add consultation → Convert
- Bulk assign leads
- Pipeline drag-and-drop

---

## 📁 FILE STRUCTURE

```
frontend/src/
├── app/
│   └── (dashboard)/
│       └── leads/
│           ├── page.tsx                    # Lead list
│           ├── [id]/
│           │   └── page.tsx                # Lead detail
│           ├── pipeline/
│           │   └── page.tsx                # Pipeline kanban
│           └── insights/
│               └── page.tsx                # Insights dashboard
├── components/
│   └── leads/
│       ├── LeadListTable.tsx
│       ├── LeadFilters.tsx
│       ├── LeadBulkActions.tsx
│       ├── LeadQuickActions.tsx
│       ├── LeadDetailHeader.tsx
│       ├── LeadOverviewTab.tsx
│       ├── LeadTimelineTab.tsx
│       ├── LeadConsultationsTab.tsx
│       ├── LeadInsightsTab.tsx
│       ├── LeadInfoCard.tsx
│       ├── TimelineItem.tsx
│       ├── ConsultationCard.tsx
│       ├── InsightsChart.tsx
│       ├── LeadCreateDialog.tsx
│       ├── LeadEditDialog.tsx
│       ├── LeadAssignDialog.tsx
│       ├── ConsultationDialog.tsx
│       ├── LeadImportDialog.tsx
│       ├── LeadExportDialog.tsx
│       ├── PipelineBoard.tsx
│       ├── PipelineColumn.tsx
│       ├── LeadCard.tsx
│       ├── PipelineFilters.tsx
│       └── StageStats.tsx
├── hooks/
│   ├── useLeads.ts
│   ├── useLead.ts
│   ├── useLeadAssignment.ts
│   ├── useConsultations.ts
│   ├── usePipeline.ts
│   └── useLeadInsights.ts
├── lib/
│   └── api/
│       ├── leads.ts
│       └── pipeline.ts
└── types/
    ├── lead.types.ts
    └── pipeline.types.ts
```

---

## 📊 TIMELINE SUMMARY

| Phase | Duration | Tasks | Priority |
|-------|----------|-------|----------|
| **Phase 1: Foundation** | Week 1 (16h) | API clients, hooks | 🔴 CRITICAL |
| **Phase 2: Core UI** | Week 2 (24h) | List, detail, forms | 🔴 CRITICAL |
| **Phase 3: Advanced** | Week 3 (26h) | Kanban, import, insights | 🟡 HIGH |
| **Phase 4: Polish** | Week 4 (14h) | UI/UX, testing | 🟢 MEDIUM |
| **TOTAL** | **4 weeks (80h)** | **40+ files** | - |

---

## 🎯 SUCCESS CRITERIA

### **Functional Requirements:**
- ✅ Users can view, create, edit, delete leads
- ✅ Users can assign leads to officers (manual & auto)
- ✅ Users can add consultations to leads
- ✅ Users can track lead timeline
- ✅ Users can view lead insights
- ✅ Users can manage pipeline stages
- ✅ Users can drag leads between stages
- ✅ Users can import/export leads
- ✅ Users can filter, search, sort leads
- ✅ Real-time updates via Socket.IO

### **Non-Functional Requirements:**
- ✅ Responsive design (mobile-first)
- ✅ Fast loading (<2s initial load)
- ✅ Optimistic updates (instant feedback)
- ✅ Error handling (graceful degradation)
- ✅ Accessibility (WCAG 2.1 AA)
- ✅ Type-safe (100% TypeScript)
- ✅ Test coverage (>80%)

---

## 🚀 NEXT STEPS

1. **Review & Approve Plan** ✅
2. **Start Phase 1: Foundation** 🔜
3. **Create API clients & types**
4. **Implement React Query hooks**
5. **Build core UI components**
6. **Add advanced features**
7. **Polish & test**
8. **Deploy to production**

---

**Có cần tôi bắt đầu implement Phase 1 ngay không?** 😊

