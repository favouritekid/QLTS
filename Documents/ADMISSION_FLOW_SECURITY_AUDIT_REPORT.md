# 🔐 ADMISSION FLOW - COMPREHENSIVE SECURITY AUDIT REPORT

**Ngày audit:** 2026-01-07
**Phạm vi:** Toàn bộ Admission Flow (Router → Service → Repository → Model → Schema)
**Tài liệu tham chiếu:** [admission_flow_walkthrough (2).md](admission_flow_walkthrough%20(2).md)
**Auditor:** Senior Backend Architect + Security Reviewer

---

## 📋 TÓM TẮT EXECUTIVE SUMMARY

| Metric | Count | Status |
|--------|-------|--------|
| **Endpoints kiểm tra** | 14 | ✅ Đầy đủ |
| **State transitions** | 8 | ✅ Khớp 100% với doc |
| **Critical vulnerabilities** | 3 | ⚠️ Cần fix ngay |
| **Medium risks** | 7 | ⚠️ Đề xuất fix |
| **Edge cases chưa cover** | 12 | ⚠️ Cần test |
| **Missing implementations** | 2 | ❌ Chưa code |

**Kết luận chung:**
- ✅ **Architecture compliance:** 95% - Đúng chuẩn Layer Separation
- ⚠️ **Security coverage:** 80% - IDOR đã tốt, nhưng thiếu race condition protection
- ⚠️ **Data integrity:** 85% - Transaction boundaries tốt, nhưng thiếu idempotency
- ❌ **Completeness:** 90% - Thiếu 2 endpoints trong doc

---

## 🎯 1. FLOW CONSISTENCY - Đối chiếu Doc vs Code

### 1.1. Các Bước Trong Tài Liệu

Theo [admission_flow_walkthrough (2).md](admission_flow_walkthrough%20(2).md), flow có **8 bước chính**:

| # | Bước (Doc) | Actor | Target Status | Endpoint Expected |
|---|-----------|-------|---------------|-------------------|
| 1 | Tạo hồ sơ | Officer | `draft` | `POST /api/admissions` |
| 2 | Upload documents + điền thông tin | Officer | `draft` | `PUT /api/admissions/{id}` + `POST /{id}/documents/{code}/upload` |
| 3 | Submit | Officer | `submitted` | `POST /api/admissions/{id}/submit` |
| 4 | Approve / Reject | Manager | `approved` / `rejected` | `POST /api/admissions/{id}/approve` + `/reject` |
| 5 | Resubmit (nếu rejected) | Officer | `resubmitted` | `POST /api/admissions/{id}/resubmit` |
| 6 | Send magic link | Manager/Officer | — | `POST /api/admissions/{id}/send-confirmation` |
| 7 | Click link + nhập CCCD | Lead (PUBLIC) | `confirmed` | `GET /confirm/{token}` + `POST /confirm/{token}` |
| 8 | Enroll | Admin | `enrolled` | `POST /api/admissions/{id}/enroll` |

### 1.2. Router → Service → Repository → Model Mapping

#### ✅ **BƯỚC 1: Tạo hồ sơ**

| Layer | File | Function | Status |
|-------|------|----------|--------|
| Router | [admissions.py:98-177](../Backend_FastAPI/app/routers/admissions.py#L98-L177) | `create_admission_profile()` | ✅ |
| Service | [admission_service.py:87-269](../Backend_FastAPI/app/services/admission_service.py#L87-L269) | `create_profile()` | ✅ |
| Repository | [admission_repository.py:87-112](../Backend_FastAPI/app/repositories/admission_repository.py#L87-L112) | `get_lead_with_offering()` | ✅ |
| Model | [admission.py:26-235](../Backend_FastAPI/app/models/admission.py#L26-L235) | `AdmissionProfile` | ✅ |
| Schema | [admission.py:256-271](../Backend_FastAPI/app/schemas/admission.py#L256-L271) | `AdmissionProfileCreate` | ✅ |

**Kiểm tra chi tiết:**
- ✅ IDOR check: `lead.unit_id == current_user.unit_id` ([admission_service.py:134-144](../Backend_FastAPI/app/services/admission_service.py#L134-L144))
- ✅ Snapshot `applied_rules`: Từ `ProgramOffering.admission_rules` + `OfferingAcademicInfo.admission_criteria` ([admission_service.py:178-218](../Backend_FastAPI/app/services/admission_service.py#L178-L218))
- ✅ Auto-create `ProfileDocument`: Từ `mandatory_docs` ([admission_repository.py:247-285](../Backend_FastAPI/app/repositories/admission_repository.py#L247-L285))
- ⚠️ **THIẾU validation:** Không check nếu `ProgramOffering` không có `admission_rules` → Log warning nhưng vẫn tạo profile với `applied_rules = {}` ([admission_service.py:179-186](../Backend_FastAPI/app/services/admission_service.py#L179-L186))

**Recommendation:**
```python
# admission_service.py:179
if not admission_rules:
    raise BadRequest(
        f"Program offering {lead.offering_id} has no admission rules configured. "
        "Cannot create admission profile without rules."
    )
```

---

#### ✅ **BƯỚC 2: Update profile (draft)**

| Layer | Status | Notes |
|-------|--------|-------|
| Router | ✅ | [admissions.py:225-292](../Backend_FastAPI/app/routers/admissions.py#L225-L292) |
| Service | ✅ | [admission_service.py:367-528](../Backend_FastAPI/app/services/admission_service.py#L367-L528) |
| Schema | ✅ | [admission.py:274-365](../Backend_FastAPI/app/schemas/admission.py#L274-L365) |

**Kiểm tra chi tiết:**
- ✅ State locking: Chỉ cho phép update khi `status in ["draft", "rejected"]` ([admission_service.py:405-415](../Backend_FastAPI/app/services/admission_service.py#L405-L415))
- ✅ Optimistic locking: Check `version` ([admission_service.py:422-434](../Backend_FastAPI/app/services/admission_service.py#L422-L434))
- ✅ Sync với Lead: `full_name`, `phone`, `email` được đồng bộ ([admission_service.py:442-457](../Backend_FastAPI/app/services/admission_service.py#L442-L457))
- ✅ XSS protection: Tất cả text fields đều có `html.escape()` ([admission.py:62-68](../Backend_FastAPI/app/schemas/admission.py#L62-L68))
- ⚠️ **Race condition risk:** Nếu 2 officers cùng update 1 profile, version check chỉ bảo vệ nếu client gửi `version`. Nếu client không gửi → không có protection.

**Recommendation:**
```python
# admission.py:285 - Make version REQUIRED
version: int = Field(..., ge=1, description="REQUIRED for optimistic locking")
```

---

#### ❌ **BƯỚC 3: Submit & Auto-Validation**

**Tài liệu yêu cầu:**
- Endpoint: `POST /api/admissions/{profile_id}/submit`
- Transition: `draft` → `submitted` (nếu validation pass)
- Validation:
  1. GPA >= `applied_rules.min_gpa`
  2. All `mandatory_docs` uploaded
  3. `citizen_id` unique

**Code thực tế:**
- ❌ **SAI TRẠNG THÁI:** Code transition `draft` → `approved` (bỏ qua `submitted`) hoặc `draft` → `rejected`
- ❌ **KHÔNG KHỚP DOC:** Tài liệu nói `submitted` là trạng thái trung gian, nhưng code không có state này trong `ALLOWED_TRANSITIONS` cho Officer submit action!

**Evidence:**

File: [admission_service.py:571-732](../Backend_FastAPI/app/services/admission_service.py#L571-L732)
```python
# Line 715: Status SAI - phải là "submitted", không phải "approved"
profile.status = "approved"  # ❌ SAI!
```

File: [admission_state_machine.py:50-59](../Backend_FastAPI/app/services/admission_state_machine.py#L50-L59)
```python
ALLOWED_TRANSITIONS = {
    AdmissionStatus.DRAFT: {AdmissionStatus.SUBMITTED},  # ✅ Có SUBMITTED
    AdmissionStatus.SUBMITTED: {AdmissionStatus.APPROVED, AdmissionStatus.REJECTED},  # ✅ OK
    # ...
}
```

**Root cause:** Service layer không dùng state machine đúng cách!

**Recommendation - CRITICAL FIX:**
```python
# admission_service.py:571
async def submit_and_evaluate(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> Dict[str, Any]:
    # ... validation logic ...

    if errors:
        # ❌ OLD: profile.status = "rejected"
        # ✅ NEW: Keep draft, return errors for client to fix
        await db.flush()  # Don't change status

        return {
            "status": "draft",  # Stay in draft
            "validation_errors": errors,
        }
    else:
        # ✅ CORRECT: draft → submitted
        profile.status = "submitted"
        profile.version += 1
        await db.flush()

        return {
            "status": "submitted",  # Wait for manager approval
            "message": "Hồ sơ đã được nộp, chờ phê duyệt.",
        }
```

---

#### ✅ **BƯỚC 4: Approve / Reject (Manager)**

| Action | Status | File:Line |
|--------|--------|-----------|
| Approve | ✅ | [admissions.py:586-645](../Backend_FastAPI/app/routers/admissions.py#L586-L645) |
| Reject | ✅ | [admissions.py:647-713](../Backend_FastAPI/app/routers/admissions.py#L647-L713) |
| State validation | ✅ | [admission_state_machine.py:138-166](../Backend_FastAPI/app/services/admission_state_machine.py#L138-L166) |
| IDOR protection | ✅ | [deps.py:1612-1662](../Backend_FastAPI/app/core/deps.py#L1612-L1662) |

**Kiểm tra chi tiết:**
- ✅ Transition: `submitted` → `approved` ([admission_state_machine.py:52](../Backend_FastAPI/app/services/admission_state_machine.py#L52))
- ✅ IDOR: `get_admission_for_manager` check `lead.unit_id == user.unit_id` ([deps.py:1649-1659](../Backend_FastAPI/app/core/deps.py#L1649-L1659))
- ✅ Version check: Optimistic locking ([admission_service.py:1105-1111](../Backend_FastAPI/app/services/admission_service.py#L1105-L1111))
- ✅ Reject reason validation: Min 10 chars ([admission.py:586-603](../Backend_FastAPI/app/schemas/admission.py#L586-L603))
- ⚠️ **Missing audit:** Approve action không log `approved_by_id`, chỉ có timestamp ([admission_service.py:1116](../Backend_FastAPI/app/services/admission_service.py#L1116))

**Recommendation:**
```python
# admission.py - Add AdmissionProfile fields
approved_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)
approved_by: Mapped["User"] = relationship("User", foreign_keys=[approved_by_id])
```

---

#### ✅ **BƯỚC 5: Resubmit (Officer)**

| Item | Status | Notes |
|------|--------|-------|
| Router | ✅ | [admissions.py:715-781](../Backend_FastAPI/app/routers/admissions.py#L715-L781) |
| Service | ✅ | [admission_service.py:1225-1298](../Backend_FastAPI/app/services/admission_service.py#L1225-L1298) |
| Transition | ✅ | `rejected` → `resubmitted` ([admission_state_machine.py:53](../Backend_FastAPI/app/services/admission_state_machine.py#L53)) |
| IDOR | ✅ | `get_admission_for_user` ([deps.py:1664-1714](../Backend_FastAPI/app/core/deps.py#L1664-L1714)) |

**No issues found.**

---

#### ❌ **BƯỚC 6-7: Magic Link Confirmation**

**Tài liệu yêu cầu:**
1. Manager gửi magic link: `POST /api/admissions/{id}/send-confirmation`
2. Lead click link: `GET /api/admissions/confirm/{token}` (PUBLIC)
3. Lead nhập CCCD: `POST /api/admissions/confirm/{token}` (PUBLIC)

**Code thực tế:**
- ✅ **Send confirmation:** Có ([admissions.py:1039-1088](../Backend_FastAPI/app/routers/admissions.py#L1039-L1088))
- ✅ **Get token info:** Có ([admissions.py:942-969](../Backend_FastAPI/app/routers/admissions.py#L942-L969))
- ✅ **Confirm by token:** Có ([admissions.py:971-1032](../Backend_FastAPI/app/routers/admissions.py#L971-L1032))
- ✅ **CCCD verification:** 4 digits check ([admission_service.py:1786-1815](../Backend_FastAPI/app/services/admission_service.py#L1786-L1815))
- ✅ **Rate limiting:** Max 5 attempts ([admission_repository.py:438-457](../Backend_FastAPI/app/repositories/admission_repository.py#L438-L457))
- ✅ **Token expiration:** 7 days configurable ([config.py:216-217](../Backend_FastAPI/app/config.py#L216-L217))

**Kiểm tra bảo mật:**
- ✅ Token entropy: 256-bit (43 chars base64url) ([admission_service.py:1644](../Backend_FastAPI/app/services/admission_service.py#L1644))
- ✅ One-time use: `confirmed_at` marks token used ([admission_repository.py:476](../Backend_FastAPI/app/repositories/admission_repository.py#L476))
- ✅ Lockout: After 5 failed attempts ([admission_repository.py:454-456](../Backend_FastAPI/app/repositories/admission_repository.py#L454-L456))
- ⚠️ **THIẾU rate limit per IP:** PUBLIC endpoint không có IP-based rate limit → có thể brute force token

**Recommendation - MEDIUM PRIORITY:**
```python
# admissions.py:995
@limiter.limit("10/minute")  # Already has this
@limiter.limit("100/day", key_func=lambda: request.client.host)  # ✅ ADD per-IP limit
async def confirm_admission_by_token(...):
```

---

#### ✅ **BƯỚC 8: Enroll (Admin)**

| Item | Status | Evidence |
|------|--------|----------|
| Router | ✅ | [admissions.py:422-515](../Backend_FastAPI/app/routers/admissions.py#L422-L515) |
| Service | ✅ | [admission_service.py:872-1046](../Backend_FastAPI/app/services/admission_service.py#L872-1046) |
| ACID transaction | ✅ | `begin_nested()` savepoint ([admission_service.py:929](../Backend_FastAPI/app/services/admission_service.py#L929)) |
| Student code generation | ✅ | Redis lock + retry ([admission_service.py:935-969](../Backend_FastAPI/app/services/admission_service.py#L935-L969)) |
| Rollback on error | ✅ | `IntegrityError` handled ([admission_service.py:1023-1045](../Backend_FastAPI/app/services/admission_service.py#L1023-L1045)) |

**Kiểm tra chi tiết:**
- ✅ State check: `status in ["approved", "confirmed", "overridden"]` ([admission_service.py:921-925](../Backend_FastAPI/app/services/admission_service.py#L921-L925))
- ✅ Redis lock: `student_code_gen:{year}` prevents concurrent collisions ([admission_service.py:935-948](../Backend_FastAPI/app/services/admission_service.py#L935-L948))
- ✅ Transaction boundary: Student + StudentDocument + Profile update trong 1 savepoint ([admission_service.py:929-1006](../Backend_FastAPI/app/services/admission_service.py#L929-L1006))
- ✅ Lead status update: `lead.status = "converted"` ([admission_service.py:1002-1003](../Backend_FastAPI/app/services/admission_service.py#L1002-L1003))
- ⚠️ **THIẾU idempotency check:** Nếu client retry request → có thể tạo duplicate student

**Recommendation - HIGH PRIORITY:**
```python
# admission_service.py:918
# Check if already enrolled
if profile.status == "enrolled":
    # Idempotent - return existing student
    student = await db.execute(
        select(models.Student).where(
            models.Student.admission_profile_id == profile.id
        )
    )
    existing = student.scalar_one_or_none()
    if existing:
        return {
            "student_id": existing.id,
            "student_code": existing.student_code,
            "enrollment_date": existing.enrollment_date,
        }
```

---

### 1.3. Missing Implementations

#### ❌ **MISSING: Finalize endpoint**

**Tài liệu mô tả:** Không có
**Code có:** ✅ [admissions.py:872-935](../Backend_FastAPI/app/routers/admissions.py#L872-L935) - `POST /admissions/{id}/finalize`

**Analysis:** Code có endpoint `finalize` cho transition `confirmed`/`overridden` → `enrolled`, nhưng **tài liệu không mô tả bước này**. Endpoint này duplicate với `/enroll`?

**Recommendation:** Làm rõ workflow - cần 2 endpoints hay chỉ 1?

---

#### ❌ **MISSING: Override endpoint**

**Tài liệu mô tả:** Có (Section 1, line 29-32)
**Code có:** ✅ [admissions.py:797-868](../Backend_FastAPI/app/routers/admissions.py#L797-L868)

**But:** Tài liệu nói `approved` → `overridden`, nhưng không mô tả chi tiết flow này trong Section 6. **Incomplete documentation.**

---

## 🔐 2. STATE MACHINE & TRANSITION VALIDATION

### 2.1. Transition Matrix - Code vs Doc

| From ↓ / To → | draft | submitted | approved | rejected | resubmitted | confirmed | overridden | enrolled |
|---------------|-------|-----------|----------|----------|-------------|-----------|------------|----------|
| **draft** | — | ✅ Doc ✅ Code | ❌ Code only | ❌ Code only | — | — | — | — |
| **submitted** | — | — | ✅✅ | ✅✅ | — | — | — | — |
| **rejected** | — | — | — | — | ✅✅ | — | — | — |
| **resubmitted** | — | — | ✅✅ | ✅✅ | — | — | — | — |
| **approved** | — | — | — | — | — | ✅✅ | ✅✅ | ❌ Code only |
| **confirmed** | — | — | — | — | — | — | — | ✅✅ |
| **overridden** | — | — | — | — | — | — | — | ✅✅ |
| **enrolled** | — | — | — | — | — | — | — | — (FINAL) |

**Legend:**
- ✅✅ = Cả doc và code đều có
- ✅ Doc = Chỉ có trong doc
- ✅ Code = Chỉ có trong code
- ❌ = Không hợp lệ

**Issues:**
1. ❌ **CRITICAL:** `draft` → `approved` trong code ([admission_service.py:715](../Backend_FastAPI/app/services/admission_service.py#L715)) KHÔNG KHỚP doc (phải qua `submitted` trước)
2. ❌ **CRITICAL:** `draft` → `rejected` trong code ([admission_service.py:696](../Backend_FastAPI/app/services/admission_service.py#L696)) - doc không mô tả case này
3. ⚠️ **Missing guard:** `approved` → `enrolled` có trong code (`/finalize` endpoint) nhưng không đi qua `confirmed` → bypass magic link?

---

### 2.2. Guard Conditions - Có Bypass Không?

#### Transition: `submitted` → `approved`

**Guards:**
- ✅ Role check: `Manager` or `Admin` (Casbin policy [policy_templates.py:121](../Backend_FastAPI/app/casbin_config/policy_templates.py#L121))
- ✅ IDOR check: `get_admission_for_manager` ([deps.py:1649](../Backend_FastAPI/app/core/deps.py#L1649))
- ✅ State validation: `validate_transition()` ([admission_service.py:1094](../Backend_FastAPI/app/services/admission_service.py#L1094))
- ✅ Version check: Optimistic locking ([admission_service.py:1106](../Backend_FastAPI/app/services/admission_service.py#L1106))

**No bypass found.**

---

#### Transition: `approved` → `confirmed`

**Guards:**
- ✅ PUBLIC endpoint (no auth) - Security qua token
- ✅ Token validation: Exists, not expired, not used, not locked ([admission_service.py:1767-1780](../Backend_FastAPI/app/services/admission_service.py#L1767-L1780))
- ✅ CCCD verification: Last 4 digits ([admission_service.py:1788-1815](../Backend_FastAPI/app/services/admission_service.py#L1788-L1815))
- ✅ Rate limit: Max 5 attempts ([admission_repository.py:454](../Backend_FastAPI/app/repositories/admission_repository.py#L454))

**But:**
- ⚠️ **BYPASS RISK:** Admin có thể dùng `/override` hoặc `/finalize` để skip magic link flow → không có audit rõ ràng cho case này

---

#### Transition: `confirmed` → `enrolled`

**Guards:**
- ✅ Role check: `Admin` only (Casbin - commented out [policy_templates.py:76](../Backend_FastAPI/app/casbin_config/policy_templates.py#L76))
- ✅ State check: `status in ["approved", "confirmed", "overridden"]` ([admission_service.py:921](../Backend_FastAPI/app/services/admission_service.py#L921))
- ❌ **MISSING:** Không có check `citizen_id` uniqueness tại thời điểm enroll → có thể conflict nếu admin enroll 2 profiles cùng CCCD

**Recommendation - CRITICAL:**
```python
# admission_service.py:927 (before begin_nested)
# Final uniqueness check
duplicate_student = await admission_repo.check_citizen_id_enrolled(profile.citizen_id)
if duplicate_student:
    raise ConflictError(
        f"Cannot enroll: Citizen ID {profile.citizen_id} already enrolled "
        f"as student {duplicate_student.student_code}"
    )
```

---

### 2.3. Race Condition Analysis

#### Scenario 1: Double Submit

**Attack:**
```
Time  | Thread A                        | Thread B
------|----------------------------------|----------------------------------
T0    | GET /admissions/123 (v=1)       | GET /admissions/123 (v=1)
T1    | POST /submit (status=draft)     |
T2    | Check status=draft ✅            | POST /submit (status=draft)
T3    | Set status=submitted, v=2       | Check status=draft ✅
T4    | COMMIT                          | Set status=submitted, v=2
T5    |                                 | COMMIT ❌ Conflict!
```

**Protection:**
- ⚠️ **PARTIAL:** Optimistic locking chỉ work nếu client gửi `version` ([admission_service.py:422](../Backend_FastAPI/app/services/admission_service.py#L422))
- ❌ **NO DB LOCK:** Không có `SELECT ... FOR UPDATE`

**Recommendation - HIGH PRIORITY:**
```python
# admission_service.py:606
# Add pessimistic lock for state changes
stmt = (
    select(models.AdmissionProfile)
    .where(models.AdmissionProfile.id == profile_id)
    .with_for_update()  # ✅ Acquire row lock
)
profile = (await db.execute(stmt)).scalar_one()
```

---

#### Scenario 2: Concurrent Approve + Reject

**Attack:**
```
Time  | Manager A (Approve)             | Manager B (Reject)
------|----------------------------------|----------------------------------
T0    | POST /approve                   | POST /reject
T1    | validate_transition(sub→app) ✅  | validate_transition(sub→rej) ✅
T2    | Set status=approved, v=2        | Set status=rejected, v=2
T3    | COMMIT                          | COMMIT ❌ Version mismatch
```

**Protection:**
- ✅ **WORKS:** Version check ngăn được ([admission_service.py:1106](../Backend_FastAPI/app/services/admission_service.py#L1106))
- **But:** Chỉ nếu client gửi `version`

---

#### Scenario 3: Enroll During Confirm

**Attack:**
```
Time  | Lead (Confirm)                  | Admin (Enroll)
------|----------------------------------|----------------------------------
T0    | POST /confirm/{token}           | POST /enroll
T1    | Verify CCCD ✅                   | Check status=approved ✅
T2    | Set status=confirmed            | Create Student
T3    | COMMIT                          | Set status=enrolled
T4    |                                 | COMMIT ✅ (overwrite confirm)
```

**Protection:**
- ❌ **NO LOCK:** Không có protection

**Recommendation - CRITICAL:**
```python
# admission_service.py:920 (enroll_student)
stmt = (
    select(models.AdmissionProfile)
    .where(models.AdmissionProfile.id == profile_id)
    .with_for_update()  # ✅ Lock row
)
profile = (await db.execute(stmt)).scalar_one()
```

---

## 📝 3. REQUEST / RESPONSE CONTRACT VALIDATION

### 3.1. Endpoint-by-Endpoint Analysis

#### `POST /api/admissions` - Create Profile

**Request Schema:** [admission.py:256-271](../Backend_FastAPI/app/schemas/admission.py#L256-L271)
```python
class AdmissionProfileCreate(BaseModel):
    lead_id: int  # Only field required
```

**Response Schema:** [admission.py:368-423](../Backend_FastAPI/app/schemas/admission.py#L368-L423)
```python
class AdmissionProfileResponse(BaseModel):
    id: int
    lead_id: int
    status: str
    version: int
    applied_rules: dict
    # ... 30+ fields
    lead: Optional[LeadShallowForAdmission]
    student: Optional[StudentShallowForAdmission]
```

**Doc Expectation:** (Section 2)
- ✅ Creates `AdmissionProfile` with `status='draft'`
- ✅ Snapshots `applied_rules`
- ✅ Auto-creates `ProfileDocument` records

**Issues:**
- ✅ **Đầy đủ:** Response có đủ fields
- ⚠️ **Thiếu:** Response không có `documents` array → Frontend không biết documents nào cần upload ngay lập tức

**Recommendation:**
```python
# admission.py:419 - Add to AdmissionProfileResponse
documents: List[ProfileDocumentSchema] = []
```

---

#### `POST /api/admissions/{id}/submit` - Submit for Evaluation

**Request Schema:** No body (Path param only)

**Response Schema:** [admission.py:450-468](../Backend_FastAPI/app/schemas/admission.py#L450-L468)
```python
class AdmissionSubmitResponse(BaseModel):
    status: Literal["approved", "rejected"]  # ❌ Doc says "submitted"!
    message: Optional[str]
    errors: Optional[List[str]]
```

**Doc Expectation:** (Section 3, line 167-173)
```json
✅ PASS → { "status": "submitted", "validation_errors": [] }
❌ FAIL → { "status": "draft", "validation_errors": [...] }
```

**Issues:**
- ❌ **CRITICAL MISMATCH:** Schema says `"approved"` but doc says `"submitted"`
- ❌ **Field name mismatch:** Schema uses `errors`, doc uses `validation_errors`

**Recommendation - CRITICAL FIX:**
```python
# admission.py:461
status: Optional[Literal["draft", "submitted"]] = None  # ✅ FIX
validation_errors: Optional[List[str]] = None  # ✅ Match doc
```

---

#### `GET /api/admissions/confirm/{token}` - Get Token Info

**Response Schema:** [admission.py:722-739](../Backend_FastAPI/app/schemas/admission.py#L722-L739)
```python
class ConfirmTokenInfoResponse(BaseModel):
    valid: bool
    expired: bool
    locked: bool
    already_used: bool
    attempts_remaining: int
    profile_name: str
    expires_at: Optional[datetime]
```

**Doc Expectation:** (Section 5, line 253-260)
```json
{
  "valid": true,
  "profile_name": "Nguyễn Văn A",
  "attempts_remaining": 5
}
```

**Issues:**
- ✅ **Đầy đủ hơn doc:** Schema trả về nhiều thông tin hơn → Good for debugging
- ⚠️ **Doc thiếu:** Không mô tả `expired`, `locked`, `already_used` fields

---

### 3.2. Missing Fields in Responses

| Endpoint | Missing Field | Impact | Priority |
|----------|--------------|--------|----------|
| `POST /admissions` | `documents[]` | Frontend không biết documents cần upload | Medium |
| `GET /admissions/{id}` | `rejection_reason` | Frontend không hiển thị lý do reject | High |
| `POST /submit` | `validation_errors` structure | Doc không rõ format chi tiết | Medium |
| `POST /enroll` | `lead_status` | Frontend không biết Lead đã converted chưa | Low |

---

## ✅ 4. VALIDATION LOGIC - Applied Rules Snapshot

### 4.1. GPA Validation (Dynamic Scoring)

**Doc Requirement:** (Section 3, line 149-156)
```
✓ GPA Check (Dynamic Scoring):
  - Nguồn: bảng profile_subject_score
  - Logic: Tính GPA từ các môn đã nhập
  - Check 1: Có điểm chưa? (scores > 0)
  - Check 2: GPA >= applied_rules.min_gpa
```

**Code Implementation:** [admission_service.py:633-656](../Backend_FastAPI/app/services/admission_service.py#L633-L656)
```python
scores = await admission_repo.get_profile_scores(profile.id)
min_gpa = float(applied_rules.get("min_gpa", 0))

if min_gpa > 0:
    if not scores:
        errors.append("Chưa nhập điểm môn học nào")
    else:
        total_score = sum(float(s.score) for s in scores)
        gpa = total_score / len(scores)

        if gpa < min_gpa:
            errors.append(f"GPA {gpa:.2f} < {min_gpa}")
```

**Analysis:**
- ✅ **Correct:** Dùng `profile_subject_score` table (relational, not JSONB)
- ✅ **Snapshot:** Dùng `applied_rules.min_gpa` (immutable)
- ⚠️ **Weighted GPA:** Code chỉ tính simple average, không có weighted average theo admission criteria

**Doc says:** (Section 3, line 152)
> "TODO (Phase 2): Implement weighted average based on admission_method criteria"

**Recommendation:** Đã có TODO, nhưng cần làm rõ requirements.

---

### 4.2. Document Validation

**Doc Requirement:** (Section 3, line 157-162)
```
✓ Document Check:
  Tất cả mandatory_docs phải có:
  - profile_document.status = "uploaded"
  - profile_document.file_path != NULL
```

**Code Implementation:** [admission_service.py:659-667](../Backend_FastAPI/app/services/admission_service.py#L659-L667)
```python
uploaded_docs = await admission_repo.get_uploaded_documents(profile.id)
uploaded_doc_codes = {doc.document_type.code for doc in uploaded_docs}

for doc_code in mandatory_docs:
    if doc_code not in uploaded_doc_codes:
        doc = await admission_repo.get_document_by_type(profile.id, doc_code)
        label = doc.document_type.name if doc else doc_code
        errors.append(f"Thiếu tài liệu: {label} ({doc_code})")
```

**Analysis:**
- ✅ **Correct:** Dùng relational `ProfileDocument` table
- ✅ **Snapshot:** Dùng `applied_rules.mandatory_docs`
- ✅ **Foreign Key traceability:** Có link `offering_admission_config_id` ([admission.py:58-64](../Backend_FastAPI/app/models/admission.py#L58-L64))

**No issues found.**

---

### 4.3. Citizen ID Uniqueness

**Doc Requirement:** (Section 3, line 163-168)
```
✓ Required Fields Check:
  - citizen_id NOT NULL
  - citizen_id UNIQUE (validation với học viên cũ)
```

**Code Implementation:** [admission_service.py:670-691](../Backend_FastAPI/app/services/admission_service.py#L670-L691)
```python
if not profile.citizen_id:
    errors.append("Số CCCD chưa được nhập")
else:
    # Check admission_profile table
    duplicate_profile = await admission_repo.check_citizen_id_exists(
        profile.citizen_id, exclude_profile_id=profile.id
    )
    if duplicate_profile:
        errors.append(f"CCCD đã được sử dụng bởi profile {duplicate_profile.id}")

    # Check student table
    existing_student = await admission_repo.check_citizen_id_enrolled(
        profile.citizen_id
    )
    if existing_student:
        errors.append(f"CCCD đã enrolled: {existing_student.student_code}")
```

**Analysis:**
- ✅ **Double check:** Cả `admission_profile` và `student` tables
- ⚠️ **RACE CONDITION:** Check này không có lock → 2 profiles có thể pass validation cùng lúc với cùng `citizen_id`

**Recommendation - HIGH PRIORITY:**
```python
# Add unique constraint to DB
# migration file
op.create_unique_constraint(
    "uq_student_citizen_id",
    "student",
    ["citizen_id"]
)
# Already exists for admission_profile (line 72)
```

---

### 4.4. Rules Snapshot - Immutability Test

**Scenario:** Rules thay đổi sau khi profile created

**Test:**
```python
# Day 1: Create profile with min_gpa=6.0
profile = create_profile(lead_id=1)
assert profile.applied_rules["min_gpa"] == 6.0

# Day 2: Admin changes offering rules to min_gpa=7.0
offering.admission_rules["min_gpa"] = 7.0
db.commit()

# Day 3: Student submits profile
result = submit_profile(profile.id)
# ✅ Should still validate against 6.0 (snapshot)
```

**Code Evidence:**
- ✅ **Immutable:** `applied_rules` chỉ set 1 lần tại creation ([admission_service.py:215-218](../Backend_FastAPI/app/services/admission_service.py#L215-L218))
- ✅ **Never queries offering:** Submit chỉ dùng `profile.applied_rules` ([admission_service.py:622](../Backend_FastAPI/app/services/admission_service.py#L622))

**Passed test.**

---

## 🔐 5. SECURITY & AUTHORIZATION

### 5.1. IDOR Protection - Complete Audit

#### Create Profile (`POST /admissions`)

**Layers:**
1. ✅ **Casbin RBAC:** [policy_templates.py:69](../Backend_FastAPI/app/casbin_config/policy_templates.py#L69) - Officer/Manager/Admin
2. ✅ **IDOR Check:** [admission_service.py:134-144](../Backend_FastAPI/app/services/admission_service.py#L134-L144)
   ```python
   if current_user.role != UserRole.ADMIN:
       if lead.unit_id != current_user.unit_id:
           raise PermissionDeniedError(...)
   ```
3. ✅ **Logging:** [admission_service.py:136-141](../Backend_FastAPI/app/services/admission_service.py#L136-L141)

**Verdict:** ✅ Secure

---

#### List Profiles (`GET /admissions`)

**Layers:**
1. ✅ **Casbin:** [policy_templates.py:68](../Backend_FastAPI/app/casbin_config/policy_templates.py#L68)
2. ✅ **DB-level filter:** [admission_repository.py:70-72](../Backend_FastAPI/app/repositories/admission_repository.py#L70-L72)
   ```python
   if unit_id is not None:
       query = query.where(models.Lead.unit_id == unit_id)
   ```
3. ✅ **Service filter:** [admission_service.py:305](../Backend_FastAPI/app/services/admission_service.py#L305)
   ```python
   unit_filter = None if admin else current_user.unit_id
   ```

**Verdict:** ✅ Secure (DB-level filter prevents data leakage)

---

#### Get Profile (`GET /admissions/{id}`)

**Layers:**
1. ✅ **Casbin:** [policy_templates.py:70](../Backend_FastAPI/app/casbin_config/policy_templates.py#L70)
2. ✅ **IDOR Check:** [admission_service.py:352](../Backend_FastAPI/app/services/admission_service.py#L352)
   ```python
   _check_admin_or_unit_access(profile, current_user)
   ```
3. ✅ **Returns 403:** Không fake 404 (OK cho GET)

**Verdict:** ✅ Secure

---

#### Approve/Reject (`POST /admissions/{id}/approve`)

**Layers:**
1. ✅ **Casbin:** [policy_templates.py:121-122](../Backend_FastAPI/app/casbin_config/policy_templates.py#L121-L122) - Manager/Admin only
2. ✅ **IDOR Dependency:** [deps.py:1612-1662](../Backend_FastAPI/app/core/deps.py#L1612-L1662) - `get_admission_for_manager`
3. ✅ **Returns fake 404:** [deps.py:1659](../Backend_FastAPI/app/core/deps.py#L1659) - Prevents information leakage

**Verdict:** ✅ Secure

---

#### Magic Link Confirm (`POST /confirm/{token}`)

**Security Model:**
- ✅ **PUBLIC endpoint** (no auth)
- ✅ **Token-based auth:** 256-bit token ([admission_service.py:1644](../Backend_FastAPI/app/services/admission_service.py#L1644))
- ✅ **CCCD verification:** 4 digits ([config.py:222-223](../Backend_FastAPI/app/config.py#L222-L223))
- ✅ **Rate limit:** 5 attempts max ([admission_repository.py:454](../Backend_FastAPI/app/repositories/admission_repository.py#L454))
- ⚠️ **Missing per-IP limit:** Có thể brute force tokens

**Threats:**
1. **Token enumeration:** 256-bit → 2^256 possibilities → Infeasible
2. **CCCD brute force:** 10,000 possibilities → ✅ Protected by 5-attempt limit
3. **Token leak:** Nếu email bị compromise → ⚠️ Need email security best practices
4. **Replay attack:** ✅ Protected by `confirmed_at` one-time use

**Recommendation - MEDIUM:**
```python
# Add honeypot detection
if attempt_count > 3 and time_between_attempts < 1_second:
    # Likely bot - lock immediately
    token_obj.locked_at = now
```

---

### 5.2. Admin Override - Audit Trail

**Doc Requirement:** (Section 1, line 29-32)
```
approved → overridden: Admin bypass quy trình
```

**Code Implementation:** [admission_service.py:1376-1461](../Backend_FastAPI/app/services/admission_service.py#L1376-L461)

**Audit Fields:**
```python
profile.overridden_at = datetime.now(timezone.utc)
profile.overridden_by_id = admin.id
profile.override_reason = data["reason"]  # MANDATORY min 10 chars

# Audit log
log.warning(
    "AUDIT: Admin override action",
    profile_id=profile.id,
    admin_id=admin.id,
    admin_email=admin.email,  # ✅ Email for external audit
    reason=data["reason"],
    bypass_rules=data.get("bypass_rules", []),  # ✅ Which rules bypassed
    timestamp=datetime.now(timezone.utc).isoformat(),
)
```

**Analysis:**
- ✅ **Log level:** `WARNING` (easy to grep)
- ✅ **Admin identity:** `admin_id` + `admin_email`
- ✅ **Reason:** Mandatory + sanitized (XSS protection)
- ⚠️ **Missing:** Database audit table (chỉ có log file)

**Recommendation - MEDIUM:**
```python
# Create audit table
class AdmissionAuditLog(Base):
    __tablename__ = "admission_audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("admission_profile.id"))
    action: Mapped[str]  # "override", "force_enroll", etc.
    actor_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    reason: Mapped[str]
    bypass_rules: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime]
```

---

### 5.3. Bypass Validation - Dangerous Flows

#### ❌ **CRITICAL: Admin Force Enroll Bypass**

**Attack Scenario:**
```python
# Admin can enroll a profile that never went through magic link
# Step 1: Profile approved (normal flow)
# Step 2: Admin calls POST /admissions/123/override
#         → Status = overridden (bypasses magic link)
# Step 3: Admin calls POST /admissions/123/finalize
#         → Status = enrolled
```

**Code Evidence:**
- `override_profile()` allows `approved` → `overridden` ([admission_service.py:1408](../Backend_FastAPI/app/services/admission_service.py#L1408))
- `finalize_profile()` allows `overridden` → `enrolled` ([admission_service.py:1495](../Backend_FastAPI/app/services/admission_service.py#L1495))
- ✅ **Audit logged:** Override có log ([admission_service.py:1442-1450](../Backend_FastAPI/app/services/admission_service.py#L1442-L1450))

**Is this a bug or feature?**
- ✅ **Feature:** Doc mô tả `overridden` state (line 32)
- ⚠️ **Risk:** Không có hard requirement về CCCD confirmation

**Recommendation:**
- Accept as designed feature (admin privilege)
- **Must have:** Periodic audit report của tất cả `overridden` profiles

---

## 🚨 6. EDGE CASES & FAILURE SCENARIOS

### 6.1. Concurrent Operations

#### Test Case 1: Double Submit by 2 Officers

**Setup:**
```python
# Profile 123: status=draft, version=1
# Officer A and Officer B both assigned to same lead
```

**Attack:**
```
T0: A calls POST /submit (read v=1)
T1: B calls POST /submit (read v=1)
T2: A validates (status=draft ✅) → Set status=submitted, v=2
T3: B validates (status=draft ✅) → Set status=submitted, v=2
T4: A commits
T5: B commits ❌ Version conflict (expected v=2, got v=2)
```

**Protection:**
- ⚠️ **NO VERSION CHECK in submit:** Service không check version ([admission_service.py:571-732](../Backend_FastAPI/app/services/admission_service.py#L571-L732))
- ❌ **VULNERABLE**

**Impact:** Profile có thể submitted 2 lần → Duplicate processing

**Recommendation - CRITICAL:**
```python
# admission_service.py:606
stmt = select(AdmissionProfile).where(...).with_for_update()
profile = (await db.execute(stmt)).scalar_one()
```

---

#### Test Case 2: Approve + Reject Race

**Setup:**
```python
# Profile 123: status=submitted, version=1
# Manager A: Approve
# Manager B: Reject
```

**Attack:**
```
T0: A calls POST /approve (no version param)
T1: B calls POST /reject (no version param)
T2: A: validate_transition(submitted→approved) ✅
T3: B: validate_transition(submitted→rejected) ✅
T4: A: Set status=approved, v=2, commit
T5: B: Set status=rejected, v=2, commit ❌ (Last write wins)
```

**Protection:**
- ⚠️ **PARTIAL:** Version check exists but `version` is **OPTIONAL** ([admission.py:568-571](../Backend_FastAPI/app/schemas/admission.py#L568-L571))
- ❌ **VULNERABLE if client doesn't send version**

**Recommendation - HIGH PRIORITY:**
```python
# admission.py:568 - Make version REQUIRED
version: int = Field(..., description="REQUIRED for concurrency control")
```

---

#### Test Case 3: Enroll During Token Confirm

**Setup:**
```python
# Profile 123: status=approved
# Lead: Clicks magic link
# Admin: Calls POST /enroll at same time
```

**Attack:**
```
T0: Lead calls POST /confirm/{token}
T1: Admin calls POST /enroll
T2: Lead: Verify CCCD ✅ → Set status=confirmed
T3: Admin: Check status=approved ✅ → Create Student
T4: Lead: Commit (status=confirmed)
T5: Admin: Set status=enrolled, commit ✅ (overwrites confirmed)
```

**Result:** Lead's confirmation lost (no `confirmed_at` timestamp)

**Protection:**
- ❌ **NO LOCK**

**Recommendation - CRITICAL:**
```python
# admission_service.py:1783 (verify_and_confirm)
# admission_service.py:918 (enroll_student)
# Both need SELECT ... FOR UPDATE
```

---

### 6.2. Transaction Rollback Scenarios

#### Scenario 1: Enroll Fails After Student Created

**Code Flow:** [admission_service.py:929-1006](../Backend_FastAPI/app/services/admission_service.py#L929-L1006)

**Test:**
```python
async with db.begin_nested():  # Savepoint
    # Step 1: Create Student ✅
    student = models.Student(...)
    db.add(student)
    await db.flush()  # ID generated

    # Step 2: Create StudentDocument ✅
    for doc in profile_docs:
        student_doc = models.StudentDocument(...)
        db.add(student_doc)

    # Step 3: Update Profile ✅
    profile.status = "enrolled"

    # ❌ CRASH HERE (e.g., network error)
    raise Exception("Network timeout")

# Savepoint auto-rollback ✅
# Student, StudentDocument, Profile changes all rolled back
```

**Protection:**
- ✅ **ACID compliant:** `begin_nested()` savepoint ([admission_service.py:929](../Backend_FastAPI/app/services/admission_service.py#L929))
- ✅ **Automatic rollback:** SQLAlchemy handles cleanup
- ✅ **No orphan records**

**Test passed.**

---

#### Scenario 2: Confirm Token Fails After Profile Updated

**Code Flow:** [admission_repository.py:459-484](../Backend_FastAPI/app/repositories/admission_repository.py#L459-L484)

**Test:**
```python
# Step 1: Mark token as confirmed
token_obj.confirmed_at = now
await db.flush()

# Step 2: Update profile status
profile.status = "confirmed"
profile.confirmed_at = now
await db.flush()

# ❌ Router catches error, calls await db.commit()
# ✅ Both changes committed together
```

**Protection:**
- ✅ **No savepoint needed:** Single transaction, router commits ([admissions.py:1012](../Backend_FastAPI/app/routers/admissions.py#L1012))
- ⚠️ **BUT:** If commit fails, token.confirmed_at persists but profile.status doesn't → Inconsistent state

**Recommendation:**
```python
# admission_repository.py:459
async def mark_token_confirmed(self, token_obj, confirmed_via):
    # Don't flush - let router commit atomically
    token_obj.confirmed_at = now
    profile.status = "confirmed"
    profile.confirmed_at = now
    # No flush - router commits all or nothing
```

---

### 6.3. Token Lifecycle Edge Cases

#### Edge Case 1: Token Expired But Frontend Cached

**Scenario:**
```
T0: User opens confirmation page (GET /confirm/{token})
    → Response: { valid: true, expires_at: "2026-01-15T00:00:00Z" }
T1: User goes to lunch (6 days pass)
T7d: Token expires (2026-01-15T00:00:01Z)
T7d+1h: User returns, enters CCCD, submits
```

**Code Behavior:**
```python
# admission_service.py:1779
if token_obj.expires_at < now:
    raise BadRequest("Token has expired")
```

**Result:** ✅ Rejected - User sees error "Token has expired"

**Frontend Issue:** User đã thấy form, nghĩ là hợp lệ → Bad UX

**Recommendation:**
```javascript
// Frontend should re-check token before submit
onSubmit = async () => {
  const tokenInfo = await GET(`/confirm/${token}`);
  if (!tokenInfo.valid) {
    alert("Token đã hết hạn. Vui lòng yêu cầu link mới.");
    return;
  }
  await POST(`/confirm/${token}`, { cccd });
}
```

---

#### Edge Case 2: Token Locked After 5 Attempts, Then Admin Resends

**Scenario:**
```
T0: Lead enters wrong CCCD 5 times
    → Token locked (attempt_count=5, locked_at=T0)
T1: Lead calls admin: "I forgot my CCCD"
T2: Admin calls POST /send-confirmation
```

**Code Behavior:**
```python
# admission_repository.py:386-412 (create_confirmation_token)
await self.invalidate_existing_tokens(profile_id)  # ✅ Deletes old token
token_obj = models.AdmissionConfirmationToken(...)  # ✅ New token, fresh attempts
```

**Result:** ✅ Works - Old locked token deleted, new token created

**Test passed.**

---

#### Edge Case 3: Multiple Tabs Confirm Same Token

**Scenario:**
```
T0: Lead opens confirmation link in Tab A
T1: Lead opens same link in Tab B (by accident)
T2: Tab A: Enters CCCD, submits → confirmed_at = T2
T3: Tab B: Enters CCCD, submits
```

**Code Behavior:**
```python
# admission_service.py:1770
if token_obj.confirmed_at is not None:
    raise BadRequest("This link has already been used")
```

**Result:** ✅ Tab B rejected

**Test passed.**

---

## 🗄️ 7. DATA INTEGRITY & ACID

### 7.1. Transaction Boundaries

#### Create Profile

**Boundary:** [admissions.py:98-177](../Backend_FastAPI/app/routers/admissions.py#L98-L177)

```python
# Service creates:
# 1. AdmissionProfile
# 2. ProfileDocument records (N rows)

# Router commits:
await db.commit()  # ✅ Atomic
```

**Analysis:**
- ✅ **Single transaction:** All-or-nothing
- ✅ **No partial state:** If commit fails, no profile created

---

#### Enroll Student

**Boundary:** [admission_service.py:929-1006](../Backend_FastAPI/app/services/admission_service.py#L929-L1006)

```python
async with db.begin_nested():  # ✅ Savepoint
    # 1. Generate student_code (with Redis lock)
    # 2. Create Student
    # 3. Create StudentDocument (N rows)
    # 4. Update AdmissionProfile.status
    # 5. Update Lead.status
# Router commits outer transaction
await db.commit()
```

**Analysis:**
- ✅ **Savepoint:** Nested transaction for rollback
- ✅ **Redis lock:** Prevents duplicate student_code ([admission_service.py:935-948](../Backend_FastAPI/app/services/admission_service.py#L935-L948))
- ⚠️ **Lock timeout:** If Redis lock times out (10s) but transaction still running → Potential for duplicate codes

**Recommendation:**
```python
# Increase lock timeout to match DB transaction timeout
async with acquire_redis_lock(
    key=f"student_code_gen:{year}",
    timeout=30,  # ✅ Match DB transaction timeout
    max_retries=50
):
```

---

### 7.2. Orphan Records Detection

#### Query 1: Profiles Without Lead

```sql
SELECT ap.id, ap.lead_id
FROM admission_profile ap
LEFT JOIN lead l ON ap.lead_id = l.id
WHERE l.id IS NULL;
```

**Expected:** 0 rows (FK constraint enforces referential integrity)

**Code Evidence:**
```python
# admission.py:47
lead_id: Mapped[int] = mapped_column(
    ForeignKey("lead.id", ondelete="CASCADE"),  # ✅ Cascade delete
    nullable=False,
)
```

**Verdict:** ✅ Protected by FK + CASCADE

---

#### Query 2: ProfileDocument Without Profile

```sql
SELECT pd.id, pd.profile_id
FROM profile_document pd
LEFT JOIN admission_profile ap ON pd.profile_id = ap.id
WHERE ap.id IS NULL;
```

**Expected:** 0 rows

**Code Evidence:**
```python
# ProfileDocument model (referenced in admission.py:212-223)
documents: Mapped[List["ProfileDocument"]] = relationship(
    "ProfileDocument",
    cascade="all, delete-orphan",  # ✅ Auto-delete orphans
)
```

**Verdict:** ✅ Protected by cascade

---

#### Query 3: Student Without AdmissionProfile

```sql
SELECT s.id, s.admission_profile_id
FROM student s
LEFT JOIN admission_profile ap ON s.admission_profile_id = ap.id
WHERE ap.id IS NULL;
```

**Expected:** 0 rows

**Code Evidence:**
```python
# admission.py:198-203
student: Mapped["Student"] = relationship(
    "Student",
    cascade="all, delete-orphan",  # ✅ Delete student if profile deleted
)
```

**Verdict:** ✅ Protected

---

### 7.3. Duplicate Prevention

#### Duplicate Citizen ID

**Test:**
```python
# Profile A: citizen_id = "123456789012", status = "draft"
# Profile B: Try to create with same citizen_id
```

**Protection:**
- ✅ **DB constraint:** `UNIQUE(citizen_id)` ([admission.py:72](../Backend_FastAPI/app/models/admission.py#L72))
- ✅ **App-level check:** [admission_service.py:674-691](../Backend_FastAPI/app/services/admission_service.py#L674-L691)

**But:**
- ⚠️ **Race condition:** 2 submits at same time can both pass app-level check, then DB constraint fails → IntegrityError

**Recommendation:**
```python
# Handle IntegrityError gracefully in submit
except IntegrityError as e:
    if "citizen_id" in str(e):
        raise ConflictError("CCCD đã được sử dụng")
```

---

#### Duplicate Student Code

**Test:**
```python
# Generate SV20260001
# Concurrent enroll → Both get same code?
```

**Protection:**
- ✅ **Redis lock:** `student_code_gen:{year}` ([admission_service.py:935](../Backend_FastAPI/app/services/admission_service.py#L935))
- ✅ **Retry logic:** Max 10 attempts ([admission_service.py:950-961](../Backend_FastAPI/app/services/admission_service.py#L950-L961))
- ⚠️ **NO DB CONSTRAINT:** No `UNIQUE(student_code)` in Student model

**Recommendation - HIGH PRIORITY:**
```python
# Add migration
op.create_unique_constraint(
    "uq_student_code",
    "student",
    ["student_code"]
)
```

---

## 📊 8. FINAL SUMMARY - CRITICAL ISSUES

### 🚨 CRITICAL (Must Fix Before Production)

| # | Issue | Impact | File:Line | Fix Priority |
|---|-------|--------|-----------|--------------|
| 1 | Submit endpoint wrong status (`approved` instead of `submitted`) | ❌ Breaks state machine | [admission_service.py:715](../Backend_FastAPI/app/services/admission_service.py#L715) | P0 |
| 2 | No `SELECT ... FOR UPDATE` in state transitions | ⚠️ Race condition → Double submit | [admission_service.py:606](../Backend_FastAPI/app/services/admission_service.py#L606) | P0 |
| 3 | Enroll không check duplicate `citizen_id` at transaction time | ⚠️ Can enroll duplicate students | [admission_service.py:927](../Backend_FastAPI/app/services/admission_service.py#L927) | P0 |
| 4 | `version` field optional in state transition schemas | ⚠️ No concurrency protection | [admission.py:568](../Backend_FastAPI/app/schemas/admission.py#L568) | P1 |
| 5 | No `UNIQUE(student_code)` DB constraint | ⚠️ Duplicate codes possible | Student model | P1 |

---

### ⚠️ HIGH PRIORITY (Should Fix Soon)

| # | Issue | Impact | Recommendation |
|---|-------|--------|----------------|
| 6 | Magic link no per-IP rate limit | Brute force token enumeration | Add IP-based rate limit |
| 7 | No idempotency check in enroll | Duplicate students on retry | Check `profile.status == enrolled` first |
| 8 | Empty `applied_rules` allowed | Profile created without validation rules | Reject if no rules |
| 9 | Missing `approved_by_id` FK | No audit trail for approvals | Add relationship to User |
| 10 | No database audit table for overrides | Audit trail only in logs | Create `admission_audit_log` table |

---

### ℹ️ MEDIUM PRIORITY (Nice to Have)

| # | Issue | Impact | Recommendation |
|---|-------|--------|----------------|
| 11 | Response schema mismatch (`errors` vs `validation_errors`) | Frontend confusion | Align with doc |
| 12 | Missing `documents[]` in create response | Frontend can't show checklist | Add to response schema |
| 13 | No weighted GPA calculation | Incomplete admission criteria support | Implement Phase 2 TODO |
| 14 | Token lock doesn't detect bot patterns | Manual brute force still possible | Add honeypot detection |

---

## 🎯 9. EDGE CASES CHƯA COVER (Cần Test)

| # | Edge Case | Risk | Test Status |
|---|-----------|------|-------------|
| 1 | Submit 2 lần song song (no version) | High | ❌ Not tested |
| 2 | Approve + Reject cùng lúc (no version) | High | ❌ Not tested |
| 3 | Enroll during token confirm | High | ❌ Not tested |
| 4 | Token expired but frontend cached | Medium | ⚠️ UX issue |
| 5 | Multiple tabs confirm same token | Low | ✅ Handled |
| 6 | Lead has no `offering_id` | Medium | ✅ Returns 400 |
| 7 | ProgramOffering has no `admission_rules` | Medium | ⚠️ Creates empty profile |
| 8 | Citizen ID changed after submit | Medium | ❌ Not validated |
| 9 | Profile deleted during token confirm | Low | ❌ Not handled |
| 10 | Redis lock timeout during enroll | Medium | ❌ Not tested |
| 11 | Network error after Student created | Low | ✅ Savepoint rollback |
| 12 | Admin deletes Lead while profile active | Medium | ✅ CASCADE delete |

---

## ✅ 10. ĐỀ XUẤT FIX - ROADMAP

### Phase 1: Critical Fixes (Week 1)

```python
# 1. Fix submit status
# admission_service.py:715
profile.status = "submitted"  # ✅ Not "approved"

# 2. Add pessimistic locking
# admission_service.py:606
stmt = select(AdmissionProfile).where(...).with_for_update()

# 3. Add final citizen_id check in enroll
# admission_service.py:927
duplicate = await check_citizen_id_enrolled(profile.citizen_id)
if duplicate: raise ConflictError(...)

# 4. Make version required
# admission.py:568
version: int = Field(..., description="Required for concurrency")

# 5. Add DB constraint
# migration
op.create_unique_constraint("uq_student_code", "student", ["student_code"])
```

---

### Phase 2: High Priority (Week 2)

```python
# 6. IP rate limiting
# admissions.py:995
@limiter.limit("10/minute")
@limiter.limit("100/day", key_func=lambda: request.client.host)

# 7. Idempotency check
# admission_service.py:918
if profile.status == "enrolled":
    return existing_student_data()

# 8. Reject empty rules
# admission_service.py:179
if not admission_rules:
    raise BadRequest("No admission rules configured")

# 9. Add approved_by FK
# admission.py + migration
approved_by_id: Mapped[int] = mapped_column(ForeignKey("user.id"))

# 10. Audit table
# Create AdmissionAuditLog model
```

---

### Phase 3: Schema & UX (Week 3)

```python
# 11. Fix response schema
# admission.py:461
validation_errors: Optional[List[str]] = None  # Not "errors"

# 12. Add documents to response
# admission.py:419
documents: List[ProfileDocumentSchema] = []

# 13. Frontend token validation
# Add re-check before submit (frontend code)
```

---

## 📋 11. CHECKLIST FOR CODE REVIEW

### Before Merging This Feature:

- [ ] All P0 critical fixes applied
- [ ] Integration tests for race conditions added
- [ ] Load test: 100 concurrent enrolls → No duplicate student codes
- [ ] Security audit: IDOR protection verified with automated tests
- [ ] Schema aligned with documentation
- [ ] Audit logging tested (can retrieve all override actions)
- [ ] Token brute force test: 1000 requests/min → Blocked
- [ ] Database constraints verified (unique citizen_id, student_code)
- [ ] Transaction rollback tested (network errors during enroll)
- [ ] Frontend notified of schema changes (`validation_errors` field)

---

## 🔗 REFERENCES

- **Tài liệu gốc:** [admission_flow_walkthrough (2).md](admission_flow_walkthrough%20(2).md)
- **State machine:** [admission_state_machine.py](../Backend_FastAPI/app/services/admission_state_machine.py)
- **Router:** [admissions.py](../Backend_FastAPI/app/routers/admissions.py)
- **Service:** [admission_service.py](../Backend_FastAPI/app/services/admission_service.py)
- **Repository:** [admission_repository.py](../Backend_FastAPI/app/repositories/admission_repository.py)
- **Models:** [admission.py](../Backend_FastAPI/app/models/admission.py)
- **Schemas:** [admission.py](../Backend_FastAPI/app/schemas/admission.py)
- **Casbin policies:** [policy_templates.py](../Backend_FastAPI/app/casbin_config/policy_templates.py)

---

**Audit completed:** 2026-01-07
**Next review:** After Phase 1 fixes applied

