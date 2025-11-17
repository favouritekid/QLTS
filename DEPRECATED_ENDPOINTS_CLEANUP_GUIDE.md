# DEPRECATED ENDPOINTS - DETAILED CLEANUP GUIDE

**Project:** QLTS (Quản Lý Tuyển Sinh)
**Date:** 2025-11-17
**Status:** ⚠️ CLEANUP REQUIRED
**Migration:** k6l7m8n9o0p1_refactor_to_3tier_major_architecture

---

## EXECUTIVE SUMMARY

### Current Status: ✅ Backend Clean, ⚠️ Frontend Needs Cleanup

| Component | Status | Action Required |
|-----------|--------|-----------------|
| **Backend Routes** | ✅ REMOVED | None - Already cleaned up |
| **Database Tables** | ✅ MIGRATED | Remove legacy model file |
| **Frontend Hooks** | ⚠️ DEPRECATED | Remove 10 deprecated hooks |
| **Frontend Components** | ⚠️ ORPHANED | Remove 3 legacy components |
| **TypeScript Types** | ⚠️ LEGACY | Remove old type definitions |

---

## 1. THE 8 DEPRECATED ENDPOINTS

### Overview of Old vs New Architecture

**OLD (2-Tier):** `Major` → `MajorAcademicInfo`
- Tier 1: Major (program information)
- Tier 2: Academic Info (yearly data tied to major)

**NEW (3-Tier):** `MajorProgram` → `ProgramOffering` → `OfferingAcademicInfo`
- Tier 1: Major Program (static program info - e.g., "Kỹ thuật phần mềm")
- Tier 2: Program Offering (offering types - e.g., "Chính quy", "Liên thông")
- Tier 3: Offering Academic Info (yearly academic data)

---

### 1.1 Public Endpoints (5 endpoints)

#### Endpoint #1: List All Majors
```
DEPRECATED: GET /api/majors
REPLACEMENT: GET /api/major-programs
```

**Old Response:**
```json
[
  {
    "id": 1,
    "code": "KTPM",
    "name": "Kỹ thuật phần mềm",
    "unit_id": 1
  }
]
```

**New Response (3-tier):**
```json
[
  {
    "id": 1,
    "code": "KTPM",
    "name": "Kỹ thuật phần mềm",
    "degree_level": "bachelor",
    "unit_id": 1,
    "program_offerings": [...]
  }
]
```

**Frontend Location:**
- Hook: `useOrganization.ts:810` - `useMajors()`
- Endpoint constant: `endpoints.ts:53` - `LIST_MAJORS`

**Status:** ❌ Backend removed, ⚠️ Frontend deprecated hook still exists

---

#### Endpoint #2: Get Single Major
```
DEPRECATED: GET /api/majors/{id}
REPLACEMENT: GET /api/major-programs/{id}
```

**Changes:**
- Returns full 3-tier structure with nested offerings
- Includes degree level classification

**Frontend Location:**
- Hook: `useOrganization.ts:832` - `useMajor(id)`
- Endpoint constant: `endpoints.ts:54` - `GET_MAJOR(id)`
- Component: `MajorDialog.tsx:96` - Active usage in legacy component

**Status:** ❌ Backend removed, ⚠️ Frontend hook + component still exist

---

#### Endpoint #3: Get Academic Info History
```
DEPRECATED: GET /api/majors/{id}/academic-info
REPLACEMENT: GET /api/offerings/{offeringId}/academic-info
```

**Migration Notes:**
- Old: Academic info tied to Major
- New: Academic info tied to ProgramOffering (more granular)
- One major can have multiple offerings, each with separate academic info

**Frontend Location:**
- Hook: `useOrganization.ts:932` - `useAcademicInfoHistory(majorId)`
- Endpoint constant: `endpoints.ts:55` - `ACADEMIC_INFO_HISTORY(majorId)`
- Component: `AcademicInfoManagement.tsx:89` - Active usage

**Status:** ❌ Backend removed, ⚠️ Frontend hook + component still exist

---

#### Endpoint #4: Get Academic Info by Year
```
DEPRECATED: GET /api/majors/{id}/academic-info/{year}
REPLACEMENT: GET /api/offerings/{offeringId}/academic-info/{year}
```

**Frontend Location:**
- Hook: `useOrganization.ts:953` - `useAcademicInfoByYear(majorId, year)`
- Endpoint constant: `endpoints.ts:56` - `ACADEMIC_INFO_BY_YEAR(majorId, year)`

**Status:** ❌ Backend removed, ⚠️ Frontend deprecated hook still exists

---

#### Endpoint #5: Get Current Academic Info
```
DEPRECATED: GET /api/majors/{id}/academic-info/current
REPLACEMENT: GET /api/offerings/{offeringId}/academic-info/current
```

**Note:** This endpoint had an implicit "current year" variant that's now explicit.

**Status:** ❌ Backend removed, ✅ Frontend migrated to new endpoint

---

### 1.2 Admin Endpoints (3 endpoints)

#### Endpoint #6: Create Major
```
DEPRECATED: POST /api/admin/majors
REPLACEMENT: POST /api/admin/programs
```

**Old Payload:**
```json
{
  "code": "KTPM",
  "name": "Kỹ thuật phần mềm",
  "unit_id": 1
}
```

**New Payload (Enhanced):**
```json
{
  "code": "KTPM",
  "name": "Kỹ thuật phần mềm",
  "degree_level": "bachelor",
  "unit_id": 1,
  "description": "Optional description",
  "is_active": true
}
```

**Frontend Location:**
- Hook: `useOrganization.ts:848` - `useCreateMajor()`
- Endpoint constant: `endpoints.ts:107` - `CREATE_MAJOR`
- Component: `MajorDialog.tsx:38,96` - Active usage

**Status:** ❌ Backend removed, ⚠️ Frontend hook + component still exist

---

#### Endpoint #7: Update Major
```
DEPRECATED: PUT /api/admin/majors/{id}
REPLACEMENT: PUT /api/admin/programs/{id}
```

**Frontend Location:**
- Hook: `useOrganization.ts:876` - `useUpdateMajor()`
- Endpoint constant: `endpoints.ts:108` - `UPDATE_MAJOR(id)`
- Component: `MajorDialog.tsx:38,97` - Active usage

**Status:** ❌ Backend removed, ⚠️ Frontend hook + component still exist

---

#### Endpoint #8: Delete Major
```
DEPRECATED: DELETE /api/admin/majors/{id}
REPLACEMENT: DELETE /api/admin/programs/{id}
```

**Frontend Location:**
- Hook: `useOrganization.ts:907` - `useDeleteMajor()`
- Endpoint constant: `endpoints.ts:109` - `DELETE_MAJOR(id)`

**Status:** ❌ Backend removed, ⚠️ Frontend deprecated hook still exists

---

## 2. BACKEND STATUS

### 2.1 Routes: ✅ FULLY REMOVED

**Verification:**
```bash
# Search for any /api/majors routes
grep -r "majors" Backend_FastAPI/app/routers/*.py
# Result: No matches found
```

**Testing Guide Confirmation:**
File: `Backend_FastAPI/TESTING_GUIDE.md:95-96`
```
✅ Verify /api/majors returns 404 (removed)
✅ Verify /api/majors/{id}/academic-info returns 404 (removed)
```

**Status:** ✅ No action needed - Backend is clean

---

### 2.2 Database: ✅ MIGRATED

**Dropped Tables:**
- `major` (old Tier 1)
- `major_academic_info` (old Tier 2)

**Created Tables:**
- `major_program` (new Tier 1 - static program info)
- `program_offering` (new Tier 2 - offering types)
- `offering_academic_info` (new Tier 3 - yearly data)

**Migration File:**
`Backend_FastAPI/alembic/versions/k6l7m8n9o0p1_refactor_to_3tier_major_architecture.py`

**Verification SQL:**
`Backend_FastAPI/verify_phase2_migration.sql`

**Status:** ✅ Migration complete, verified

---

### 2.3 Models: ⚠️ LEGACY FILE EXISTS

**File to Remove:**
`Backend_FastAPI/app/models/major_academic_info.py`

**Reason:**
- Line 62: References dropped `major.id` foreign key
- Entire file is obsolete after migration
- No longer imported in `models/__init__.py`

**Current State:**
```python
# app/models/__init__.py (lines 25, 34)
# from .major import Major  # ❌ REMOVED AFTER MIGRATION
# from .major_academic_info import MajorAcademicInfo  # ❌ REMOVED AFTER MIGRATION
```

**Action Required:**
```bash
rm Backend_FastAPI/app/models/major_academic_info.py
```

---

### 2.4 Commented Code: ⚠️ CLEANUP NEEDED

**File:** `Backend_FastAPI/app/models/organization.py`
**Lines:** 204-214

**Current State:**
```python
# class Major(Base):
#     """
#     Major table (REMOVED AFTER MIGRATION k6l7m8n9o0p1)
#     Migrated to 3-tier: MajorProgram -> ProgramOffering -> OfferingAcademicInfo
#     """
#     # ... commented out code
```

**Action Required:**
Remove entire commented block (lines 204-214)

---

## 3. FRONTEND STATUS

### 3.1 Deprecated Hooks: ⚠️ REMOVE 10 HOOKS

**File:** `frontend/src/hooks/useOrganization.ts`
**Lines to Remove:** 803-1080 (278 lines)

#### Hooks to Delete:

1. **`useMajors()`** - Line 810
   ```typescript
   /** @deprecated Use useMajorPrograms() instead */
   export function useMajors() { ... }
   ```

2. **`useMajor(id)`** - Line 832
   ```typescript
   /** @deprecated Use useMajorProgram(id) instead */
   export function useMajor(id: number) { ... }
   ```

3. **`useCreateMajor()`** - Line 848
   ```typescript
   /** @deprecated Use useCreateMajorProgram() instead */
   export function useCreateMajor() { ... }
   ```

4. **`useUpdateMajor()`** - Line 876
   ```typescript
   /** @deprecated Use useUpdateMajorProgram() instead */
   export function useUpdateMajor() { ... }
   ```

5. **`useDeleteMajor()`** - Line 907
   ```typescript
   /** @deprecated Use useDeleteMajorProgram() instead */
   export function useDeleteMajor() { ... }
   ```

6. **`useAcademicInfoHistory(majorId)`** - Line 932
   ```typescript
   /** @deprecated Use useOfferingAcademicInfoList(offeringId) instead */
   export function useAcademicInfoHistory(majorId: number) { ... }
   ```

7. **`useAcademicInfoByYear(majorId, year)`** - Line 953
   ```typescript
   /** @deprecated Use useOfferingAcademicInfoByYear(offeringId, year) instead */
   export function useAcademicInfoByYear(majorId: number, year: number) { ... }
   ```

8. **`useCreateAcademicInfo()`** - Line 971
   ```typescript
   /** @deprecated Use useCreateOfferingAcademicInfo() instead */
   export function useCreateAcademicInfo() { ... }
   ```

9. **`useUpdateAcademicInfo()`** - Line 1008
   ```typescript
   /** @deprecated Use useUpdateOfferingAcademicInfo() instead */
   export function useUpdateAcademicInfo() { ... }
   ```

10. **`useDeleteAcademicInfo()`** - Line 1055
    ```typescript
    /** @deprecated Use useDeleteOfferingAcademicInfo() instead */
    export function useDeleteAcademicInfo() { ... }
    ```

**Replacement Hooks (Already Implemented):**
- ✅ `useMajorPrograms()` - Line 187
- ✅ `useMajorProgram(id)` - Line 214
- ✅ `useCreateMajorProgram()` - Line 474
- ✅ `useUpdateMajorProgram()` - Line 513
- ✅ `useDeleteMajorProgram()` - Line 546
- ✅ `useOfferingAcademicInfoList(offeringId)` - Line 291
- ✅ Full CRUD hooks for all 3 tiers

---

### 3.2 Legacy Components: ⚠️ REMOVE 3 COMPONENTS

#### Component #1: MajorDialog.tsx (ORPHANED)
**Path:** `frontend/src/components/admin/organization/MajorDialog.tsx`

**Current State:**
- Lines 38-39: Imports deprecated hooks
- Lines 96-97: Uses `useCreateMajor()`, `useUpdateMajor()`

**Replacement:**
Already exists: `MajorProgramDialog.tsx` (uses new 3-tier architecture)

**Imports Found:**
❌ No files import `MajorDialog` → Component is orphaned/unused

**Action:**
```bash
rm frontend/src/components/admin/organization/MajorDialog.tsx
```

---

#### Component #2: AcademicInfoManagement.tsx (ORPHANED)
**Path:** `frontend/src/components/admin/organization/AcademicInfoManagement.tsx`

**Current State:**
- Line 52: Imports `useAcademicInfoHistory`
- Line 89: Uses deprecated hook

**Replacement:**
New academic info management is embedded in `ProgramOfferingDialog.tsx`

**Imports Found:**
❌ No files import `AcademicInfoManagement` → Component is orphaned/unused

**Action:**
```bash
rm frontend/src/components/admin/organization/AcademicInfoManagement.tsx
```

---

#### Component #3: AcademicInfoDialog.tsx (ORPHANED)
**Path:** `frontend/src/components/admin/organization/AcademicInfoDialog.tsx`

**Status:**
Likely orphaned (companion to AcademicInfoManagement)

**Action:**
```bash
rm frontend/src/components/admin/organization/AcademicInfoDialog.tsx
```

---

### 3.3 Endpoint Constants: ⚠️ REMOVE DEFINITIONS

**File:** `frontend/src/lib/api/endpoints.ts`

#### Public Endpoints (Lines 52-56)
```typescript
// === LEGACY (DEPRECATED) - REMOVE THESE ===
LIST_MAJORS: "/api/majors",
GET_MAJOR: (id: number) => `/api/majors/${id}`,
ACADEMIC_INFO_HISTORY: (majorId: number) => `/api/majors/${majorId}/academic-info`,
ACADEMIC_INFO_BY_YEAR: (majorId: number, year: number) =>
  `/api/majors/${majorId}/academic-info/${year}`,
```

**Replacement (Already exists):**
```typescript
// Lines 40-50 (NEW - Keep these)
LIST_MAJOR_PROGRAMS: "/api/major-programs",
GET_MAJOR_PROGRAM: (id: number) => `/api/major-programs/${id}`,
GET_PROGRAM_OFFERINGS: (programId: number) => `/api/major-programs/${programId}/offerings`,
GET_OFFERING: (id: number) => `/api/offerings/${id}`,
GET_CURRENT_OFFERING_INFO: (id: number) => `/api/offerings/${id}/current-info`,
LIST_OFFERING_ACADEMIC_INFO: (offeringId: number) =>
  `/api/offerings/${offeringId}/academic-info`,
GET_OFFERING_ACADEMIC_INFO_BY_YEAR: (offeringId: number, year: number) =>
  `/api/offerings/${offeringId}/academic-info/${year}`,
```

#### Admin Endpoints (Lines 106-110)
```typescript
// === LEGACY (DEPRECATED) - REMOVE THESE ===
CREATE_MAJOR: "/api/admin/majors",
UPDATE_MAJOR: (id: number) => `/api/admin/majors/${id}`,
DELETE_MAJOR: (id: number) => `/api/admin/majors/${id}`,
GET_MAJOR: (id: number) => `/api/admin/majors/${id}`,
```

**Replacement (Already exists):**
```typescript
// Lines 61-80 (NEW - Keep these)
CREATE_MAJOR_PROGRAM: "/api/admin/programs",
UPDATE_MAJOR_PROGRAM: (id: number) => `/api/admin/programs/${id}`,
DELETE_MAJOR_PROGRAM: (id: number) => `/api/admin/programs/${id}`,
// ... full 3-tier CRUD endpoints
```

---

### 3.4 TypeScript Types: ⚠️ REMOVE OLD TYPES

**File:** `frontend/src/types/organization.types.ts`

**Types to Remove:**
```typescript
// Old 2-tier types (REMOVE)
export interface Major { ... }
export interface MajorCreate { ... }
export interface MajorUpdate { ... }
export interface MajorAcademicInfo { ... }
export interface MajorAcademicInfoCreate { ... }
export interface MajorAcademicInfoUpdate { ... }
```

**Replacement Types (Already exist):**
```typescript
// New 3-tier types (KEEP)
export interface MajorProgram { ... }
export interface MajorProgramCreate { ... }
export interface MajorProgramUpdate { ... }
export interface ProgramOffering { ... }
export interface ProgramOfferingCreate { ... }
export interface ProgramOfferingUpdate { ... }
export interface OfferingAcademicInfo { ... }
export interface OfferingAcademicInfoCreate { ... }
export interface OfferingAcademicInfoUpdate { ... }
```

---

## 4. CLEANUP EXECUTION PLAN

### Phase 1: Backend Cleanup (Low Risk)
**Estimated Time:** 5 minutes

```bash
# Step 1: Remove legacy model file
rm Backend_FastAPI/app/models/major_academic_info.py

# Step 2: Clean up commented code in organization.py
# Edit: Backend_FastAPI/app/models/organization.py
# Delete lines 204-214 (commented Major class)

# Step 3: Verify no remaining references
grep -r "major_academic_info" Backend_FastAPI/
grep -r "class Major" Backend_FastAPI/app/models/
```

**Testing:**
```bash
cd Backend_FastAPI
pytest tests/ -v
# All tests should pass
```

---

### Phase 2: Frontend Cleanup (Medium Risk)
**Estimated Time:** 15 minutes

```bash
cd frontend

# Step 1: Remove orphaned components
rm src/components/admin/organization/MajorDialog.tsx
rm src/components/admin/organization/AcademicInfoDialog.tsx
rm src/components/admin/organization/AcademicInfoManagement.tsx

# Step 2: Verify no imports of removed components
grep -r "MajorDialog" src/
grep -r "AcademicInfoDialog" src/
grep -r "AcademicInfoManagement" src/
# Should return no results

# Step 3: Edit useOrganization.ts
# Delete lines 803-1080 (all deprecated hooks)

# Step 4: Edit endpoints.ts
# Remove lines 52-56 (public legacy endpoints)
# Remove lines 106-110 (admin legacy endpoints)

# Step 5: Edit organization.types.ts
# Remove old Major* types
# Remove old MajorAcademicInfo* types
```

**Testing:**
```bash
# TypeScript compilation
npm run type-check
# Should pass with no errors

# ESLint
npm run lint
# Should pass (no unused imports)

# Build test
npm run build
# Should build successfully
```

---

### Phase 3: Verification (Critical)
**Estimated Time:** 10 minutes

#### Backend Verification
```bash
cd Backend_FastAPI

# 1. Verify endpoints return 404
curl http://localhost:8000/api/majors
# Expected: 404 Not Found

curl http://localhost:8000/api/majors/1
# Expected: 404 Not Found

# 2. Verify new endpoints work
curl http://localhost:8000/api/major-programs
# Expected: 200 OK with data

# 3. Run full test suite
pytest tests/ -v --cov=app
```

#### Frontend Verification
```bash
cd frontend

# 1. Search for any remaining "majors" references
grep -r "/api/majors" src/
# Expected: No results

grep -r "useMajor" src/
# Expected: Only useMajorProgram*, not useMajor()

# 2. Verify app runs
npm run dev
# Navigate to admin org management
# Create/edit/delete operations should work
```

---

## 5. RISK ASSESSMENT

### Low Risk ✅
- **Backend model file removal** - File already unused
- **Commented code cleanup** - Already non-functional
- **Orphaned component removal** - No imports found

### Medium Risk ⚠️
- **Hook removal** - Properly deprecated with warnings
- **Endpoint constant removal** - May have indirect references
- **Type removal** - Could affect type inference

### Mitigation Strategies

1. **Pre-cleanup verification:**
   ```bash
   # Search for any active usage
   grep -r "useMajor\|LIST_MAJORS\|Major\(" frontend/src/
   ```

2. **Git safety:**
   ```bash
   # Create backup branch
   git checkout -b backup/pre-deprecated-cleanup
   git checkout -b feature/remove-deprecated-majors
   ```

3. **Incremental testing:**
   - Test after each phase
   - Keep browser console open
   - Check for runtime errors

4. **Rollback plan:**
   ```bash
   # If issues found
   git checkout backup/pre-deprecated-cleanup
   ```

---

## 6. DETAILED FILE LOCATIONS

### Backend Files
| File | Action | Lines | Notes |
|------|--------|-------|-------|
| `app/models/major_academic_info.py` | DELETE | All | Entire file |
| `app/models/organization.py` | EDIT | 204-214 | Remove commented code |
| `app/models/__init__.py` | ✅ CLEAN | - | Already cleaned up |

### Frontend Files
| File | Action | Lines | Notes |
|------|--------|-------|-------|
| `components/admin/organization/MajorDialog.tsx` | DELETE | All | Orphaned component |
| `components/admin/organization/AcademicInfoDialog.tsx` | DELETE | All | Orphaned component |
| `components/admin/organization/AcademicInfoManagement.tsx` | DELETE | All | Orphaned component |
| `hooks/useOrganization.ts` | EDIT | 803-1080 | Remove 10 deprecated hooks |
| `lib/api/endpoints.ts` | EDIT | 52-56, 106-110 | Remove endpoint constants |
| `types/organization.types.ts` | EDIT | TBD | Remove Major* types |

---

## 7. SUCCESS CRITERIA

### Backend
- ✅ No `major_academic_info.py` file exists
- ✅ No commented Major class in `organization.py`
- ✅ All tests pass
- ✅ `/api/majors` returns 404
- ✅ `/api/major-programs` returns 200

### Frontend
- ✅ TypeScript compilation successful
- ✅ ESLint passes with no warnings
- ✅ No search results for `/api/majors`
- ✅ No search results for orphaned components
- ✅ Admin org management UI works correctly
- ✅ Can create/edit/delete major programs
- ✅ Can manage program offerings
- ✅ Can manage academic info

---

## 8. TIMELINE

| Phase | Duration | Owner | Priority |
|-------|----------|-------|----------|
| Phase 1: Backend Cleanup | 5 min | Backend Dev | High |
| Phase 2: Frontend Cleanup | 15 min | Frontend Dev | High |
| Phase 3: Verification | 10 min | QA/Dev | Critical |
| **Total** | **30 min** | - | - |

---

## 9. REFERENCES

### Migration Documentation
- Migration file: `alembic/versions/k6l7m8n9o0p1_refactor_to_3tier_major_architecture.py`
- Verification SQL: `verify_phase2_migration.sql`
- Testing guide: `TESTING_GUIDE.md`

### New Architecture Documentation
- Backend: `app/routers/organization.py`
- Backend Admin: `app/routers/admin/organization.py`
- Frontend: `hooks/useOrganization.ts` (lines 187-802)
- Types: `types/organization.types.ts`

### API Documentation
- Old endpoints: All return 404
- New endpoints: Documented in OpenAPI/Swagger at `/docs`

---

## 10. APPENDIX: CODE SNIPPETS

### A. Backend Model Cleanup

**Before (`app/models/organization.py:204-214`):**
```python
# class Major(Base):
#     """
#     Major table (REMOVED AFTER MIGRATION k6l7m8n9o0p1)
#     Migrated to 3-tier: MajorProgram -> ProgramOffering -> OfferingAcademicInfo
#     """
#     __tablename__ = "major"
#     id = Column(Integer, primary_key=True, index=True)
#     # ... more commented code
```

**After:**
```python
# Delete entire commented block
```

---

### B. Frontend Hook Cleanup

**Before (`hooks/useOrganization.ts:803-1080`):**
```typescript
/**
 * @deprecated Use useMajorPrograms() instead
 * Legacy hook for old 2-tier architecture
 */
export function useMajors() {
  return useQuery({
    queryKey: ["majors"],
    queryFn: async () => {
      const response = await api.get(endpoints.LIST_MAJORS);
      return response.data;
    },
  });
}
// ... 9 more deprecated hooks
```

**After:**
```typescript
// Delete all deprecated hooks (lines 803-1080)
// Keep only new 3-tier hooks above line 803
```

---

### C. Endpoint Constants Cleanup

**Before (`lib/api/endpoints.ts`):**
```typescript
export const endpoints = {
  // ... other endpoints

  // === LEGACY (DEPRECATED) ===
  LIST_MAJORS: "/api/majors",
  GET_MAJOR: (id: number) => `/api/majors/${id}`,

  // ... admin endpoints
  CREATE_MAJOR: "/api/admin/majors",
  UPDATE_MAJOR: (id: number) => `/api/admin/majors/${id}`,
};
```

**After:**
```typescript
export const endpoints = {
  // ... other endpoints

  // === REMOVE LEGACY SECTION ===
  // Use new 3-tier endpoints instead
};
```

---

**END OF REPORT**

For questions or assistance with cleanup:
1. Review this guide
2. Check migration file for database schema details
3. Consult API audit report for new endpoint usage
4. Test thoroughly before deploying
