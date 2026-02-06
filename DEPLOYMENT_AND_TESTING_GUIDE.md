# 🚀 Deployment & Testing Guide - Document Management Features

## ✅ HOÀN THÀNH 100%

Tất cả các tính năng đã được implement đầy đủ:

- ✅ Backend: Migration, Models, Repositories, Services, Routers, Schemas
- ✅ Frontend API: API clients, React Query hooks, Zod schemas
- ✅ Frontend UI: DocumentsTab với modal và nút undo

---

## 📋 PRE-DEPLOYMENT CHECKLIST

### 1. Backend Changes Review

```bash
# Check modified files
git status

# Expected changes:
# - alembic/versions/6g5h4i3j2k1l_*.py (NEW)
# - app/models/admission_config/profile_data.py (MODIFIED)
# - app/repositories/admission_repository.py (MODIFIED)
# - app/services/admission_service.py (MODIFIED)
# - app/routers/admissions.py (MODIFIED)
# - app/schemas/admission.py (MODIFIED)
```

### 2. Frontend Changes Review

```bash
# Expected changes:
# - lib/api/admissions.ts (MODIFIED)
# - hooks/admissions/useAdmissions.ts (MODIFIED)
# - lib/zod/admissions.ts (MODIFIED)
# - app/(dashboard)/admissions/[id]/_components/tabs/DocumentsTab.tsx (MODIFIED)
# - app/(dashboard)/admissions/[id]/_components/layout/PipelineSidebar.tsx (MODIFIED)
```

---

## 🗄️ DATABASE MIGRATION

### Step 1: Review Migration

```bash
cd Backend_FastAPI
cat alembic/versions/6g5h4i3j2k1l_add_actual_submission_format_to_profile_document.py
```

**Migration adds**:
```sql
ALTER TABLE profile_document
ADD COLUMN actual_submission_format VARCHAR(50);
```

### Step 2: Run Migration

```bash
# DEV Environment
alembic upgrade head

# Verify migration
alembic current
# Should show: 6g5h4i3j2k1l (head)

# Check database
# Connect to your PostgreSQL and verify:
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'profile_document'
  AND column_name = 'actual_submission_format';
```

### Step 3: Rollback Plan (if needed)

```bash
# If something goes wrong, rollback:
alembic downgrade -1

# This will drop the actual_submission_format column
```

---

## 🖥️ BACKEND DEPLOYMENT

### Step 1: Install Dependencies (if any new packages)

```bash
cd Backend_FastAPI
pip install -r requirements.txt
```

### Step 2: Restart Backend Server

**Development**:
```bash
uvicorn app.main:app --reload
```

**Production** (with gunicorn):
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### Step 3: Verify API Endpoints

```bash
# Test reset endpoint
curl -X POST http://localhost:8000/api/admissions/1/documents/hoc_ba/reset \
  -H "Authorization: Bearer YOUR_TOKEN"

# Expected: 200 OK with AdmissionProfileResponse

# Test upload with format
curl -X POST http://localhost:8000/api/admissions/1/documents/hoc_ba/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@test.pdf" \
  -F "actual_submission_format=original"

# Expected: 200 OK with updated profile
```

---

## 🌐 FRONTEND DEPLOYMENT

### Step 1: Type Check

```bash
cd frontend
npm run type-check
```

**Expected**: No errors in DocumentsTab or related files

### Step 2: Build

```bash
npm run build
```

**Expected**: Build success, no errors

### Step 3: Start Development Server (Testing)

```bash
npm run dev
```

Visit: http://localhost:3000/admissions/{id}

---

## 🧪 TESTING GUIDE

### Manual Testing Checklist

#### Test 1: Upload Document with Format Selection

1. ✅ Navigate to admission profile detail page
2. ✅ Click "Upload" button on a document (status: missing)
3. ✅ Select a file (PDF/JPG/PNG)
4. ✅ **Expected**: Modal "Xác nhận loại bản nộp" appears
5. ✅ Select format: Bản chính / Bản sao có chứng thực / Bản photocopy
6. ✅ Click "Xác nhận"
7. ✅ **Expected**:
   - Success toast: "Tài liệu đã được tải lên"
   - Document status → "Đã tải"
   - Format badge appears showing selected type
   - Validation errors updated (if applicable)
   - Completion % updated

#### Test 2: Mark Paper Submitted with Format

1. ✅ Navigate to admission profile detail page
2. ✅ Find a document with "Nộp giấy" type (requires_upload=false)
3. ✅ Check the "Đã nộp" checkbox
4. ✅ **Expected**: Modal "Xác nhận loại bản nộp" appears
5. ✅ Select format
6. ✅ Click "Xác nhận"
7. ✅ **Expected**:
   - Success toast: "Đã xác nhận nhận giấy tờ"
   - Document status → "Đã nộp"
   - Format badge appears
   - Validation errors updated

#### Test 3: Reset/Undo Document

1. ✅ Navigate to a document with status: uploaded/paper_submitted/verified/rejected
2. ✅ **Expected**: Undo button (RotateCcw icon) visible
3. ✅ Click undo button
4. ✅ **Expected**: Confirmation dialog appears:
   ```
   Hoàn tác tài liệu "[Document Name]"?

   Tài liệu sẽ về trạng thái "Chưa nộp" và file sẽ bị xóa (nếu có).
   ```
5. ✅ Click "OK"
6. ✅ **Expected**:
   - Success toast: "Đã hoàn tác tài liệu"
   - Document status → "Chưa nộp"
   - File deleted from server
   - Format badge removed
   - Validation errors updated
   - Undo button disappears

#### Test 4: Validation Count Fix

1. ✅ Create a profile with missing fields:
   - 8 personal info fields missing
   - 12 documents missing
   - 1 score requirement not met
2. ✅ **Expected**:
   - Sidebar badge "Vấn đề cần sửa (21)"
   - Personal Info badge: 8
   - Documents badge: 12
   - Scores badge: 1
3. ✅ Expand "Vấn đề cần sửa"
4. ✅ **Expected**: Grouped by category:
   ```
   Thông tin cá nhân (8)
   • Thiếu thông tin: Họ tên
   • Thiếu thông tin: Ngày sinh
   • ... (8 items)

   Tài liệu (12)
   • Thiếu tài liệu: hoc_ba_thpt
   • ... (12 items)

   Điểm số (1)
   • Chưa nhập đủ điểm
   ```

#### Test 5: Completion % Tracking

1. ✅ Start with empty profile (0%)
2. ✅ Fill Personal Info (all required fields)
3. ✅ **Expected**: ~14% (Step 1 success)
4. ✅ Add Family member
5. ✅ **Expected**: ~28% (Step 2 success)
6. ✅ Add Academic History
7. ✅ **Expected**: ~42% (Step 3 success)
8. ✅ Add Scores (meet requirement)
9. ✅ **Expected**: ~57% (Step 4 success)
10. ✅ Upload all required documents
11. ✅ **Expected**: ~72% (Step 5 success)
12. ✅ Complete remaining steps
13. ✅ **Expected**: 100%

#### Test 6: Format Mismatch Warning (Future Enhancement)

Current behavior: All formats accepted, no validation against required format.

**Future**: If `actual_submission_format` ≠ `required_submission_format`:
- Show warning badge
- Require manager verification

---

## 🐛 TROUBLESHOOTING

### Issue: Modal doesn't appear on file upload

**Cause**: `submissionFormatDialog` state not set correctly

**Fix**: Check `handleUploadClick` is called with all 3 parameters:
```tsx
onClick={() => handleUploadClick(doc.code, doc.label, doc.submission_format)}
```

### Issue: Reset button not visible

**Possible causes**:
1. User doesn't have `edit` permission → Check `can('edit')` returns true
2. Document status not in allowed list → Verify status is uploaded/paper_submitted/verified/rejected
3. Profile status is "enrolled" → Reset is blocked for enrolled profiles (backend)

**Debug**:
```tsx
console.log('can edit:', can('edit'))
console.log('doc status:', doc.status)
```

### Issue: Validation errors count still wrong

**Check**:
1. Backend migration ran successfully
2. Backend code updated correctly (`_compute_frontend_fields`)
3. Frontend cache cleared (hard refresh: Ctrl+Shift+R)

**Verify backend response**:
```bash
curl http://localhost:8000/api/admissions/1 \
  -H "Authorization: Bearer TOKEN" | jq '.grouped_validation_errors'
```

### Issue: Completion % not updating

**Check**:
1. `step_status` is being returned from backend
2. Backend refactored completion calculation is active
3. Frontend is reading from `profile.completion_percent`

**Verify**:
```tsx
console.log('step_status:', profile.step_status)
console.log('completion:', profile.completion_percent)
```

---

## 📊 MONITORING

### Key Metrics to Watch

1. **Document Operations**:
   - Upload success rate
   - Reset frequency (too many resets = UX issue)
   - Format selection distribution (original vs copy vs photo)

2. **Validation Errors**:
   - Most common missing fields
   - Average errors per profile
   - Time to resolve all errors

3. **Completion Tracking**:
   - Average completion % at submission
   - Steps with highest drop-off rate
   - Time to 100% completion

### Database Queries

```sql
-- Format distribution
SELECT actual_submission_format, COUNT(*)
FROM profile_document
WHERE actual_submission_format IS NOT NULL
GROUP BY actual_submission_format;

-- Reset frequency
SELECT COUNT(*) as reset_count
FROM profile_document
WHERE status = 'missing'
  AND uploaded_at IS NOT NULL; -- Had file before

-- Documents by status
SELECT status, COUNT(*)
FROM profile_document
GROUP BY status;
```

---

## 🔄 ROLLBACK PROCEDURE

If critical issues arise in production:

### 1. Backend Rollback

```bash
# Stop server
systemctl stop qlts-api

# Rollback migration
cd Backend_FastAPI
alembic downgrade -1

# Revert code changes
git revert HEAD

# Restart server
systemctl start qlts-api
```

### 2. Frontend Rollback

```bash
# Revert changes
git revert HEAD

# Rebuild
npm run build

# Restart
pm2 restart qlts-frontend
```

### 3. Database Cleanup (if needed)

```sql
-- Remove orphaned data
UPDATE profile_document
SET actual_submission_format = NULL
WHERE actual_submission_format IS NOT NULL;
```

---

## ✅ POST-DEPLOYMENT VERIFICATION

After deployment, verify:

1. ✅ Migration completed: `alembic current` shows latest version
2. ✅ API endpoints respond: Test reset, upload with format
3. ✅ Frontend builds: No TypeScript errors
4. ✅ UI displays correctly: Modal, buttons, badges
5. ✅ Data persists: Upload → Check DB → Reload page
6. ✅ Validation works: Counts match, grouped display correct
7. ✅ Permissions enforced: Officer can reset draft, cannot reset enrolled

---

## 📝 RELEASE NOTES

**Version**: 1.1.0
**Date**: 2026-01-23

### New Features

✨ **Document Submission Format Tracking**
- Users now declare document type when submitting (Original/Certified Copy/Photo)
- Applies to both file uploads and paper submissions
- Format displayed as badge next to each document

✨ **Undo/Reset Document**
- New undo button for submitted documents
- Resets document to "missing" status
- Automatically deletes uploaded files
- Available for: uploaded, paper_submitted, verified, rejected statuses

🐛 **Bug Fixes**

- Fixed validation error count mismatch (badge vs panel)
- Fixed completion % calculation to sync with step status
- Added grouped validation errors display (by category)

🔧 **Improvements**

- Completion tracking now based on 7 steps (14% each)
- Validation errors grouped: Personal Info, Documents, Scores
- Better UX with confirmation dialogs

### Breaking Changes

None - Fully backward compatible

### Migration Required

Yes - Run `alembic upgrade head` before deploying

---

## 💡 FUTURE ENHANCEMENTS

1. **Format Validation**:
   - Warn if actual_format ≠ required_format
   - Require manager approval for mismatches

2. **Audit Log**:
   - Track document reset history
   - Show who reset what and when

3. **Bulk Operations**:
   - Reset multiple documents at once
   - Batch upload with format selection

4. **Auto-detection**:
   - OCR to detect document type
   - Suggest format based on file metadata

---

## 🆘 SUPPORT

If issues arise:

1. Check logs: `tail -f logs/qlts-api.log`
2. Check browser console for frontend errors
3. Review this guide's Troubleshooting section
4. Contact dev team with error logs

---

**Implementation Date**: 2026-01-23
**Status**: ✅ READY FOR DEPLOYMENT
