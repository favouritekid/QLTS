# ✅ Implementation Checklist - Organization Management

**Dự án:** QLTS  
**Bắt đầu:** __________  
**Hoàn thành:** __________  

---

## Phase 0: Chuẩn Bị (30 phút)

### Prerequisites Check
- [ ] Backend đang chạy (`http://localhost:8000/docs` accessible)
- [ ] Frontend đang chạy (`http://localhost:3000` accessible)
- [ ] Redis đang chạy (`redis-cli ping` returns PONG)
- [ ] Database migrations updated
- [ ] Created feature branch: `git checkout -b feature/organization-management`

### Dependencies Verification
- [ ] Backend: FastAPI, SQLAlchemy, Redis, Socket.IO installed
- [ ] Frontend: Next.js, React Query, shadcn/ui, Socket.IO client installed

---

## Phase 1: Backend Foundation (3-4 giờ)

### 1.1 Socket.IO Setup
- [ ] Opened `Backend_FastAPI/app/socket_manager.py`
- [ ] Added `emit_to_all` method to SocketManager class
- [ ] Tested emit function works

### 1.2 Organization Service
- [ ] Opened `Backend_FastAPI/app/services/organization_service.py`
- [ ] Added imports: `datetime`, `socket_manager`
- [ ] Created `emit_organization_updated` function
- [ ] Added emit call to `create_organization_unit`
- [ ] Added emit call to `update_organization_unit`
- [ ] Added emit call to `delete_organization_unit`
- [ ] Added emit call to `create_major`
- [ ] Added emit call to `update_major`
- [ ] Added emit call to `delete_major`

### 1.3 Admin Endpoints
- [ ] Opened `Backend_FastAPI/app/routers/admin.py`
- [ ] Added import: `organization_service`
- [ ] Created `POST /admin/organization-units` endpoint
- [ ] Created `GET /admin/organization-units/{id}` endpoint
- [ ] Created `PUT /admin/organization-units/{id}` endpoint
- [ ] Created `DELETE /admin/organization-units/{id}` endpoint
- [ ] Created `POST /admin/majors` endpoint
- [ ] Created `GET /admin/majors/{id}` endpoint
- [ ] Created `PUT /admin/majors/{id}` endpoint
- [ ] Created `DELETE /admin/majors/{id}` endpoint

### 1.4 Backend Testing
- [ ] Restarted backend server
- [ ] Opened Swagger docs (`http://localhost:8000/docs`)
- [ ] Logged in with admin account
- [ ] Tested CREATE unit (201 response)
- [ ] Tested UPDATE unit (200 response)
- [ ] Tested CREATE major (201 response)
- [ ] Tested DELETE major (204 response)
- [ ] Tested DELETE unit with children (4xx error)
- [ ] Tested DELETE unit without children (204 response)
- [ ] Verified Socket.IO emissions in browser console
- [ ] No errors in backend logs

**Phase 1 Completed:** _____ (Date/Time)

---

## Phase 2: Frontend Data Layer (2-3 giờ)

### 2.1 TypeScript Types
- [ ] Created `frontend/src/types/organization.types.ts`
- [ ] Defined `OrganizationUnit` interface
- [ ] Defined `Major` interface
- [ ] Defined `OrganizationUnitCreate` interface
- [ ] Defined `OrganizationUnitUpdate` interface
- [ ] Defined `MajorCreate` interface
- [ ] Defined `MajorUpdate` interface
- [ ] Defined helper interfaces (FlattenedUnit, etc.)
- [ ] No TypeScript errors

### 2.2 API Endpoints Config
- [ ] Opened `frontend/src/lib/api/endpoints.ts`
- [ ] Added `ORGANIZATION` block (public endpoints)
- [ ] Added `ADMIN.ORGANIZATION` block (admin endpoints)
- [ ] Verified all endpoint paths match backend

### 2.3 React Query Hooks
- [ ] Created `frontend/src/hooks/useOrganization.ts`
- [ ] Defined `organizationKeys` object
- [ ] Created `useOrganizationUnits` hook
- [ ] Created `useOrganizationUnit` hook
- [ ] Created `useMajors` hook
- [ ] Created `useMajor` hook
- [ ] Created `useCreateUnit` mutation
- [ ] Created `useUpdateUnit` mutation with optimistic update
- [ ] Created `useDeleteUnit` mutation
- [ ] Created `useCreateMajor` mutation
- [ ] Created `useUpdateMajor` mutation
- [ ] Created `useDeleteMajor` mutation
- [ ] Added utility functions:
  - [ ] `flattenOrganizationTree`
  - [ ] `getAllDescendantIds`
  - [ ] `wouldCreateCircularDependency`
- [ ] Tested hooks with mock data
- [ ] No TypeScript errors

### 2.4 SocketHandler Integration
- [ ] Opened `frontend/src/components/layouts/SocketHandler.tsx`
- [ ] Added import: `organizationKeys`
- [ ] Found `handleDataUpdated` function
- [ ] Added case for "organization"
- [ ] Added invalidation logic
- [ ] Added toast notification
- [ ] Added case for "major"
- [ ] Added invalidation logic
- [ ] Added toast notification
- [ ] Tested Socket events in browser console

**Phase 2 Completed:** _____ (Date/Time)

---

## Phase 3: UI Components (4-5 giờ)

### 3.1 UnitDialog Component
- [ ] Created `frontend/src/components/admin/organization/UnitDialog.tsx`
- [ ] Imported all required dependencies
- [ ] Created validation schema with Zod
- [ ] Set up form with react-hook-form
- [ ] Added useEffect for form reset
- [ ] Implemented `validParentOptions` logic
- [ ] Implemented `flattenedParentOptions` with hierarchy
- [ ] Created onSubmit handler with circular dependency check
- [ ] Built Dialog UI:
  - [ ] Name field
  - [ ] Type field with Select
  - [ ] Parent field with hierarchical Select
  - [ ] Description textarea
  - [ ] Warning alert for units with children
  - [ ] Footer buttons
- [ ] Tested dialog open/close
- [ ] Tested form validation
- [ ] Tested create flow
- [ ] Tested edit flow
- [ ] Tested parent selection shows hierarchy
- [ ] Tested circular dependency prevention
- [ ] Mobile responsive

### 3.2 MajorDialog Component
- [ ] Created `frontend/src/components/admin/organization/MajorDialog.tsx`
- [ ] Imported all required dependencies
- [ ] Created validation schema with Zod
- [ ] Set up form with react-hook-form
- [ ] Added useEffect for form reset
- [ ] Flattened units for unit selector
- [ ] Created onSubmit handler
- [ ] Built Dialog UI:
  - [ ] Name field
  - [ ] Code field (uppercase, disabled when editing)
  - [ ] Unit field with hierarchical Select
  - [ ] Description textarea
  - [ ] Footer buttons
- [ ] Tested dialog open/close
- [ ] Tested form validation
- [ ] Tested create flow
- [ ] Tested edit flow
- [ ] Code field enforces uppercase
- [ ] Code field disabled in edit mode
- [ ] Mobile responsive

**Phase 3 Completed:** _____ (Date/Time)

---

## Phase 4: Admin Page (3-4 giờ)

### 4.1 Main Admin Page
- [ ] Created `frontend/src/app/(dashboard)/admin/organization/page.tsx`
- [ ] Imported all required dependencies
- [ ] Set up state management:
  - [ ] activeTab
  - [ ] Dialog states
  - [ ] Delete confirmation states
  - [ ] Filter states
- [ ] Set up queries (units, majors)
- [ ] Set up mutations (delete)
- [ ] Added permission check
- [ ] Built page header
- [ ] Created Tabs component
- [ ] Built Units Tab:
  - [ ] Card with header
  - [ ] Action buttons
  - [ ] Search and filter inputs
  - [ ] Error state
  - [ ] Table with loading skeleton
  - [ ] Unit rows with hierarchy display
  - [ ] Actions dropdown menu
  - [ ] Empty state
- [ ] Built Majors Tab:
  - [ ] Card with header
  - [ ] Action buttons
  - [ ] Unit selector
  - [ ] Info alert
  - [ ] Table with loading skeleton
  - [ ] Major rows
  - [ ] Actions dropdown menu
  - [ ] Empty state
- [ ] Added UnitDialog component
- [ ] Added MajorDialog component
- [ ] Added delete confirmation AlertDialogs
- [ ] Tested page renders
- [ ] Tested tab switching
- [ ] Tested search functionality
- [ ] Tested filter functionality
- [ ] Tested all CRUD operations
- [ ] Tested delete confirmations
- [ ] Mobile responsive

### 4.2 Sidebar Integration
- [ ] Opened `frontend/src/components/layouts/dashboard/AppSidebar.tsx`
- [ ] Added import: `Building2` icon
- [ ] Added "Quản lý Tổ chức" menu item
- [ ] Set url: `/admin/organization`
- [ ] Verified sidebar link works

**Phase 4 Completed:** _____ (Date/Time)

---

## Phase 5: Integration & Testing (2-3 giờ)

### 5.1 Environment Setup
- [ ] Backend running
- [ ] Frontend running
- [ ] Redis running

### 5.2 Backend API Testing
- [ ] All endpoints accessible in Swagger
- [ ] CREATE unit returns 201
- [ ] UPDATE unit returns 200
- [ ] CREATE major returns 201
- [ ] DELETE major returns 204
- [ ] DELETE unit with children returns error
- [ ] DELETE unit without children returns 204
- [ ] Socket emissions visible

### 5.3 Frontend Feature Testing
- [ ] Navigate to `/admin/organization` works
- [ ] Units tab displays correctly
- [ ] Majors tab displays correctly
- [ ] Search works
- [ ] Filter works
- [ ] Create unit dialog opens
- [ ] Create unit works
- [ ] Edit unit dialog pre-fills
- [ ] Edit unit works
- [ ] Delete unit confirmation shows
- [ ] Delete unit works
- [ ] Create major works
- [ ] Edit major works
- [ ] Delete major works

### 5.4 Real-time Sync Testing
- [ ] Opened two browser windows
- [ ] Logged in as admin in both
- [ ] Navigated to `/admin/organization` in both
- [ ] Created unit in window 1
- [ ] Window 2 showed toast
- [ ] Window 2 auto-updated
- [ ] Tested with update
- [ ] Tested with delete

### 5.5 Error Handling Testing
- [ ] Turned off backend
- [ ] Tried to create unit
- [ ] Error toast showed
- [ ] Turned on backend
- [ ] Retry worked

### 5.6 Mobile Responsive Testing
- [ ] Tested on iPhone SE (375px)
- [ ] Tested on iPad (768px)
- [ ] All buttons accessible
- [ ] Dialogs fit screen
- [ ] Table scrolls horizontally

### 5.7 Performance Testing
- [ ] Created 50+ test units
- [ ] Table renders in < 500ms
- [ ] Search responds in < 100ms
- [ ] No lag when typing

### 5.8 Common Issues Check
- [ ] Socket.IO connects properly
- [ ] Cache invalidates correctly
- [ ] Circular dependencies prevented
- [ ] Forms reset after submit

**Phase 5 Completed:** _____ (Date/Time)

---

## Phase 6: Polish & Deploy (1-2 giờ)

### 6.1 Code Cleanup
- [ ] Removed unnecessary console.log statements
- [ ] Formatted frontend code (`npm run format`)
- [ ] Formatted backend code (`black .`)
- [ ] Ran linters (frontend: `npm run lint`)
- [ ] Ran linters (backend: `flake8 app/`)
- [ ] Fixed all warnings

### 6.2 Documentation
- [ ] Created `docs/organization-management.md`
- [ ] Documented features
- [ ] Documented architecture
- [ ] Documented API endpoints
- [ ] Added usage examples
- [ ] Added troubleshooting guide
- [ ] Updated main README

### 6.3 Git Workflow
- [ ] Staged all changes: `git add .`
- [ ] Committed with descriptive message
- [ ] Pushed to remote: `git push origin feature/organization-management`
- [ ] Created Pull Request
- [ ] Added PR description
- [ ] Requested code review

### 6.4 Pre-Deployment
- [ ] All tests passing
- [ ] Build succeeds: `npm run build`
- [ ] No console errors in production build
- [ ] Database migrations ready
- [ ] Redis configured for production
- [ ] Socket.IO CORS configured
- [ ] Environment variables set (backend)
- [ ] Environment variables set (frontend)

### 6.5 Deployment
- [ ] Deployed to staging
- [ ] Smoke test on staging
- [ ] Real-time sync tested on staging
- [ ] Mobile tested on actual devices
- [ ] Permission checks verified
- [ ] Deployed to production
- [ ] Post-deployment verification:
  - [ ] Health check passed
  - [ ] API endpoints accessible
  - [ ] Frontend loads
  - [ ] Socket.IO connects
  - [ ] Redis operational

### 6.6 Monitoring
- [ ] Set up logging
- [ ] Set up alerts for errors
- [ ] Monitored for first 24 hours
- [ ] No critical issues

### 6.7 Handover
- [ ] Notified team of new feature
- [ ] Created user training materials
- [ ] Conducted demo session (optional)
- [ ] Documented known issues (if any)

**Phase 6 Completed:** _____ (Date/Time)

---

## 🎉 Final Sign-off

### Project Statistics
- **Total Time Spent:** _____ hours
- **Lines of Code:** _____ (estimated ~2,500)
- **Files Created:** _____
- **Files Modified:** _____
- **Test Cases Passed:** _____

### Quality Metrics
- [ ] Code coverage > 70%
- [ ] No critical bugs
- [ ] Performance acceptable
- [ ] Security reviewed
- [ ] Accessibility checked

### Deliverables
- [ ] Source code committed
- [ ] Documentation complete
- [ ] Tests passing
- [ ] Deployed to production
- [ ] Team trained

### Lessons Learned
**What went well:**
_________________________________
_________________________________
_________________________________

**What could be improved:**
_________________________________
_________________________________
_________________________________

**Next time:**
_________________________________
_________________________________
_________________________________

---

## 📝 Notes

_________________________________
_________________________________
_________________________________
_________________________________
_________________________________

---

**Implementation Status:** ⬜ Not Started | 🟡 In Progress | ✅ Completed

**Overall Progress:** _____ %

**Signed off by:** ___________________  
**Date:** ___________________
