# 🔍 Phân Tích Logic Kiểm Tra Điều Kiện Hồ Sơ

## ❌ Vấn Đề Hiện Tại

**Báo cáo**: Hồ sơ đã nhập đầy đủ thông tin nhưng vẫn hiển thị "Không đủ điều kiện"

---

## 📊 Phân Tích Backend Logic

### Logic Hiện Tại (`_compute_frontend_fields()`)

```python
# Line 325-331
if len(validation_errors) == 0:
    profile.eligibility_status = "eligible"
elif status in ["approved", "enrolled"]:
    profile.eligibility_status = "eligible"
else:
    profile.eligibility_status = "ineligible"
```

**Kết luận**: Hồ sơ chỉ "eligible" khi `validation_errors` rỗng.

---

## 🧪 Các Validation Checks Hiện Tại

### 1. **Score Validation** (Lines 200-242)

#### Method Type: `gpa_only`
- ✅ Check: `current_gpa >= min_gpa`
- Error: "GPA không đạt: X < Y"

#### Method Type: `subject_based` (default)
- ✅ Check 1: `current_count >= required_count` (đủ số môn)
- ✅ Check 2: `current_total >= min_score` (đạt điểm chuẩn)
- Error: "Chưa nhập đủ đầu điểm" hoặc "Tổng điểm thấp hơn điểm chuẩn"

#### Method Type: `combined`
- ✅ Check 1: Subject count
- ✅ Check 2: Total score
- ✅ Check 3: GPA
- Errors: Combination of above

---

### 2. **Document Validation** (Lines 243-256)

```python
upload_required_docs = applied_rules.get("upload_required_docs",
                                          applied_rules.get("mandatory_docs", []))

for doc_code in upload_required_docs:
    if doc_code not in uploaded_doc_codes:
        validation_errors.append(f"Thiếu tài liệu bắt buộc: {doc_code}")
```

**Counted as uploaded**:
- Status = `"uploaded"` AND has `file_path`
- Status = `"verified"` AND has `file_path`
- Status = `"paper_submitted"` (không cần file)

**⚠️ VẤN ĐỀ TIỀM ẨN**:
- Nếu `applied_rules` không có `upload_required_docs` hoặc `mandatory_docs`, sẽ check với empty list `[]`
- Document đang trong trạng thái `"uploaded"` (chưa verify) có được tính không?

---

### 3. **Personal Info Validation** (Lines 257-313)

**8 Mandatory Fields** (HARD-CODED):

| Field | Required | Error Message |
|-------|----------|---------------|
| `full_name` | ✅ YES | "Thiếu thông tin cá nhân: Họ tên" |
| `dob` | ✅ YES | "Thiếu thông tin cá nhân: Ngày sinh" |
| `gender` | ✅ YES | "Thiếu thông tin cá nhân: Giới tính" |
| `citizen_id` | ✅ YES | "Thiếu thông tin cá nhân: Số CCCD/CMND" |
| `nationality` | ✅ YES | "Thiếu thông tin cá nhân: Quốc tịch" |
| `ethnicity` | ✅ YES | "Thiếu thông tin cá nhân: Dân tộc" |
| `phone` | ✅ YES | "Thiếu thông tin cá nhân: Số điện thoại" |
| `place_of_birth` | ✅ YES | "Thiếu thông tin cá nhân: Nơi sinh" |

**⚠️ VẤN ĐỀ**:
1. **Hard-coded mandatory fields**: Không flexible, không thể configure
2. **`place_of_birth` (Nơi sinh)**: Có thực sự bắt buộc không?
3. **`phone`**: Có thể đã có ở Lead nhưng chưa sync vào Profile

---

## 🐛 Root Causes (Nguyên Nhân Gốc)

### Issue 1: Hard-coded Personal Info Validation

**Problem**: 8 fields được hard-code là mandatory, không dựa vào `applied_rules` hay configuration.

**Impact**: Ngay cả khi user không cần một số field (như nơi sinh), vẫn bị báo lỗi.

**Example**:
```
Hồ sơ A: Chỉ cần CCCD + Họ tên + Điểm
→ Nhưng bị báo thiếu: Nơi sinh, Dân tộc, Quốc tịch, ...
→ Kết quả: "Không đủ điều kiện" ❌
```

---

### Issue 2: Document Validation Depends on `applied_rules`

**Problem**: Nếu `applied_rules` không có `upload_required_docs` hoặc `mandatory_docs`, check với empty list.

**Scenarios**:

#### Scenario A: No Document Config in applied_rules
```python
upload_required_docs = []  # Empty
# → No document errors added
# → Documents pass validation ✅
```

#### Scenario B: Config exists but documents in "uploaded" status
```python
# Document status: "uploaded" (not "verified" yet)
# → Counted as uploaded ✅
# → But if Officer hasn't verified, should it pass?
```

**Question**: Có nên yêu cầu documents phải ở trạng thái `"verified"` mới pass validation?

---

### Issue 3: Score Validation May Be Too Strict

**Example**:
```
Phương thức: Xét học bạ (subject_based)
- required_count = 3 môn
- min_score = 18.0

User nhập:
- Toán: 9.0
- Lý: 9.0
- Hóa: 8.0
- Tổng: 26.0 > 18.0 ✅

Nhưng nếu backend chưa tính total_score hoặc lưu sai format:
→ Validation fails ❌
```

---

## ✅ Đề Xuất Fix

### Fix 1: Make Personal Info Validation Configurable

**Option A: Reduce Mandatory Fields (Quick Fix)**

Chỉ giữ lại **5 fields thực sự bắt buộc**:
```python
# ABSOLUTELY REQUIRED (cannot enroll without)
✅ full_name
✅ dob
✅ gender
✅ citizen_id
✅ phone (for contact)

# OPTIONAL (can be empty for some admission paths)
❌ nationality (default: "Việt Nam")
❌ ethnicity (default: "Kinh")
❌ place_of_birth (can be derived from citizen_id)
```

**Implementation**:
```python
# Only check 5 core fields
if not profile.full_name:
    # error
if not profile.dob:
    # error
if not profile.gender:
    # error
if not profile.citizen_id:
    # error
if not profile.phone:
    # error

# Remove checks for nationality, ethnicity, place_of_birth
```

**Pros**: Simple, immediate fix
**Cons**: Still hard-coded

---

**Option B: Configuration-based Validation (Long-term)**

Add to `applied_rules`:
```json
{
  "required_personal_fields": ["full_name", "dob", "gender", "citizen_id", "phone"],
  "optional_personal_fields": ["nationality", "ethnicity", "place_of_birth"]
}
```

Check based on config:
```python
required_fields = applied_rules.get("required_personal_fields", [
    "full_name", "dob", "gender", "citizen_id", "phone"  # Default
])

for field in required_fields:
    if not getattr(profile, field, None):
        error_msg = f"Thiếu thông tin cá nhân: {FIELD_LABELS[field]}"
        validation_errors.append(error_msg)
```

**Pros**: Flexible, can customize per admission path
**Cons**: Requires migration, config setup

---

### Fix 2: Clarify Document Validation

**Current Logic**:
```python
# Counts as fulfilled if:
status in ["uploaded", "verified"] or status == "paper_submitted"
```

**Question**: Should `"uploaded"` (chưa verify) count?

**Option A: Strict Mode (Recommended for submission)**
```python
# Only count verified documents
uploaded_doc_codes = {
    doc.document_type.code for doc in documents
    if doc.status == "verified" or doc.status == "paper_submitted"
}
```

**Option B: Lenient Mode (Current - OK for draft)**
```python
# Count uploaded + verified + paper
uploaded_doc_codes = {
    doc.document_type.code for doc in documents
    if (doc.file_path and doc.status in ["uploaded", "verified"])
       or doc.status == "paper_submitted"
}
```

**Recommendation**: Keep current logic (lenient), but add warning:
```python
if doc.status == "uploaded":
    # Add to uploaded_doc_codes (pass validation)
    # But add warning to validation_summary
    warnings.append(f"Tài liệu '{doc.label}' chưa được xác nhận")
```

---

### Fix 3: Add Debug Endpoint

Add endpoint để xem chi tiết validation:

```python
@router.get("/{profile_id}/debug/validation")
async def debug_validation(profile_id: int):
    """Return detailed validation breakdown"""
    return {
        "validation_errors": validation_errors,
        "score_validation": {
            "method_type": method_type,
            "min_gpa": min_gpa,
            "current_gpa": current_gpa,
            "min_score": min_score,
            "current_total": current_total,
            "required_count": required_count,
            "current_count": current_count,
        },
        "document_validation": {
            "required_docs": upload_required_docs,
            "uploaded_docs": list(uploaded_doc_codes),
            "missing_docs": doc_errors,
        },
        "personal_validation": {
            "missing_fields": missing_personal,
        }
    }
```

---

## 🎯 Recommended Action Plan

### Phase 1: Quick Fix (Immediate - 15 mins)

1. ✅ **Reduce mandatory personal fields to 5**:
   - Keep: `full_name`, `dob`, `gender`, `citizen_id`, `phone`
   - Remove: `nationality`, `ethnicity`, `place_of_birth`

2. ✅ **Add logging to see actual validation errors**:
   ```python
   logger.info(f"Profile {profile.id} validation_errors: {validation_errors}")
   ```

3. ✅ **Test with user's actual profile**

---

### Phase 2: Debug & Investigate (30 mins)

1. ✅ **Add debug endpoint** (see above)
2. ✅ **Check applied_rules content**:
   - Does it have `upload_required_docs`?
   - Does it have correct `min_score`, `min_gpa`?
3. ✅ **Check score calculation**:
   - Is `total_score` computed correctly?
   - Is `average_score` populated?

---

### Phase 3: Long-term Fix (1-2 hours)

1. ✅ **Make personal field validation configurable**
2. ✅ **Add validation warnings vs errors**:
   - Errors: Block submission
   - Warnings: Allow submission but show notification
3. ✅ **Add validation_detail to response**:
   ```json
   {
     "eligibility_status": "eligible_with_warnings",
     "validation_errors": [],
     "validation_warnings": [
       "Tài liệu 'Học bạ' chưa được xác nhận",
       "Chưa điền quốc tịch (mặc định: Việt Nam)"
     ]
   }
   ```

---

## 🔍 Next Steps

### Immediate: Run Quick Fix

Tôi sẽ implement **Phase 1** ngay:
1. Sửa backend: Giảm mandatory fields xuống 5
2. Test với profile thực tế
3. Report kết quả

Bạn có đồng ý không?

---

**Created**: 2026-01-23
**Status**: Analysis Complete - Awaiting Approval for Fix
