# DEPRECATED ENDPOINTS CLEANUP CHECKLIST

**Date Started:** _______________
**Completed By:** _______________
**Verified By:** _______________

---

## PRE-CLEANUP

### Safety
- [ ] Create backup branch: `git checkout -b backup/pre-deprecated-cleanup`
- [ ] Verify all changes are committed
- [ ] Inform team members about cleanup
- [ ] Schedule maintenance window (if needed)

### Documentation Review
- [ ] Read `DEPRECATED_ENDPOINTS_CLEANUP_GUIDE.md`
- [ ] Review `API_ENDPOINTS_AUDIT_REPORT.md`
- [ ] Understand 3-tier architecture migration

---

## BACKEND CLEANUP

### Files to Delete
- [ ] `Backend_FastAPI/app/models/major_academic_info.py`

### Files to Edit
- [ ] `Backend_FastAPI/app/models/organization.py`
  - [ ] Remove lines 204-214 (commented `Major` class)

### Verification
- [ ] Search: `grep -r "major_academic_info" Backend_FastAPI/` → No results
- [ ] Search: `grep -r "class Major" Backend_FastAPI/app/models/` → No results
- [ ] Run: `cd Backend_FastAPI && pytest tests/ -v` → All pass
- [ ] Test: `curl http://localhost:8000/api/majors` → 404
- [ ] Test: `curl http://localhost:8000/api/major-programs` → 200

---

## FRONTEND CLEANUP

### Components to Delete
- [ ] `frontend/src/components/admin/organization/MajorDialog.tsx`
- [ ] `frontend/src/components/admin/organization/AcademicInfoDialog.tsx`
- [ ] `frontend/src/components/admin/organization/AcademicInfoManagement.tsx`

### Files to Edit

#### 1. `frontend/src/hooks/useOrganization.ts`
- [ ] Delete lines 803-1080 (10 deprecated hooks)
  - [ ] `useMajors()`
  - [ ] `useMajor(id)`
  - [ ] `useCreateMajor()`
  - [ ] `useUpdateMajor()`
  - [ ] `useDeleteMajor()`
  - [ ] `useAcademicInfoHistory(majorId)`
  - [ ] `useAcademicInfoByYear(majorId, year)`
  - [ ] `useCreateAcademicInfo()`
  - [ ] `useUpdateAcademicInfo()`
  - [ ] `useDeleteAcademicInfo()`

#### 2. `frontend/src/lib/api/endpoints.ts`
- [ ] Delete lines 52-56 (public legacy endpoints)
  - [ ] `LIST_MAJORS`
  - [ ] `GET_MAJOR`
  - [ ] `ACADEMIC_INFO_HISTORY`
  - [ ] `ACADEMIC_INFO_BY_YEAR`
- [ ] Delete lines 106-110 (admin legacy endpoints)
  - [ ] `CREATE_MAJOR`
  - [ ] `UPDATE_MAJOR`
  - [ ] `DELETE_MAJOR`

#### 3. `frontend/src/types/organization.types.ts`
- [ ] Remove old types:
  - [ ] `Major` interface
  - [ ] `MajorCreate` interface
  - [ ] `MajorUpdate` interface
  - [ ] `MajorAcademicInfo` interface
  - [ ] `MajorAcademicInfoCreate` interface
  - [ ] `MajorAcademicInfoUpdate` interface

### Verification
- [ ] Search: `grep -r "/api/majors" frontend/src/` → No results
- [ ] Search: `grep -r "useMajor\(" frontend/src/` → No old hook refs
- [ ] Search: `grep -r "MajorDialog" frontend/src/` → No imports
- [ ] Search: `grep -r "AcademicInfoDialog" frontend/src/` → No imports
- [ ] Run: `cd frontend && npm run type-check` → No errors
- [ ] Run: `cd frontend && npm run lint` → No errors
- [ ] Run: `cd frontend && npm run build` → Success

---

## FUNCTIONAL TESTING

### Admin Organization Management
- [ ] Navigate to admin panel → Organization Management
- [ ] Create new Major Program
  - [ ] Form loads correctly
  - [ ] All fields work
  - [ ] Validation works
  - [ ] Save succeeds
- [ ] Edit existing Major Program
  - [ ] Can open edit dialog
  - [ ] Data loads correctly
  - [ ] Updates save successfully
- [ ] Delete Major Program
  - [ ] Confirmation dialog appears
  - [ ] Delete succeeds
  - [ ] List updates

### Program Offerings
- [ ] Create Program Offering for Major Program
  - [ ] Offering types dropdown works
  - [ ] Can save offering
- [ ] Edit Program Offering
  - [ ] Data loads correctly
  - [ ] Updates work
- [ ] Delete Program Offering
  - [ ] Deletion works

### Academic Info (Tier 3)
- [ ] Add academic info to offering
  - [ ] Year selection works
  - [ ] All fields save correctly
- [ ] Edit academic info
  - [ ] Updates work
- [ ] View academic info history
  - [ ] List displays correctly

### Lead Management
- [ ] Create lead with offering
  - [ ] Offering dropdown populated
  - [ ] Lead saves with correct offering_id
- [ ] Lead detail page
  - [ ] Offering info displays correctly
  - [ ] Academic info displays correctly

### Browser Console
- [ ] No errors in console
- [ ] No 404 requests to `/api/majors`
- [ ] No warnings about missing modules

---

## POST-CLEANUP

### Code Quality
- [ ] No TypeScript errors
- [ ] No ESLint warnings
- [ ] No unused imports
- [ ] Code formatted correctly

### Git
- [ ] Review all changes: `git diff`
- [ ] Stage changes: `git add .`
- [ ] Commit: `git commit -m "chore: Remove deprecated /api/majors/* endpoints"`
- [ ] Push to feature branch
- [ ] Create Pull Request

### Documentation
- [ ] Update CHANGELOG.md (if exists)
- [ ] Update API documentation
- [ ] Notify team of changes

### Cleanup
- [ ] Remove `.bak` backup files
- [ ] Delete backup branch (after merge)
- [ ] Archive this checklist

---

## ROLLBACK PLAN (If Issues Found)

### Quick Rollback
- [ ] `git checkout backup/pre-deprecated-cleanup`
- [ ] `git branch -D feature/remove-deprecated-majors`

### Partial Rollback (Restore from .bak files)
- [ ] `cp organization.py.bak organization.py`
- [ ] `cp useOrganization.ts.bak useOrganization.ts`
- [ ] `cp endpoints.ts.bak endpoints.ts`

---

## SIGN-OFF

### Developer
- **Name:** _______________
- **Date:** _______________
- **Signature:** _______________

### Code Reviewer
- **Name:** _______________
- **Date:** _______________
- **Signature:** _______________

### QA Tester
- **Name:** _______________
- **Date:** _______________
- **Signature:** _______________

---

## NOTES

_Use this space for any issues encountered, workarounds, or additional steps taken:_

```
___________________________________________________________________________

___________________________________________________________________________

___________________________________________________________________________

___________________________________________________________________________
```

---

**Estimated Time:** 30 minutes
**Priority:** High
**Risk Level:** Medium

**Dependencies:**
- Migration k6l7m8n9o0p1 must be applied
- New 3-tier architecture must be working
- No active development on major management features during cleanup
