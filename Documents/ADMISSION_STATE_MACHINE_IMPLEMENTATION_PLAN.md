# 📋 ADMISSION STATE MACHINE - IMPLEMENTATION PLAN

> **Version:** 3.0  
> **Created:** 2026-01-06  
> **Updated:** 2026-01-06 (Final improvements + Phase 0 JSONB Refactor)  
> **Author:** Architecture Team  
> **Status:** ✅ PRODUCTION-READY FOR MVP  
> **Compliance:** MASTER_ARCHITECTURE.md v3.0 + AUTHORIZATION_GUIDELINES.md v1.0

---

## 0. ARCHITECTURE COMPLIANCE REFERENCES

### 0.1 Source of Truth Documents

| Document | Path | Purpose |
|----------|------|---------|
| **MASTER_ARCHITECTURE.md** | `Backend_FastAPI/MASTER_ARCHITECTURE.md` | 4-layer architecture, coding standards |
| **AUTHORIZATION_GUIDELINES.md** | `Backend_FastAPI/AUTHORIZATION_GUIDELINES.md` | 3-layer auth model, IDOR protection |
| **AUTHORIZATION_DECISIONS.md** | `Backend_FastAPI/AUTHORIZATION_DECISIONS.md` | Quyết định authorization đã được phê duyệt |
| **policy_templates.py** | `app/casbin_config/policy_templates.py` | Casbin policy definitions |

### 0.2 Architecture Layers (MASTER_ARCHITECTURE v3.0)

```
┌───────────────────────────────────────────────────────────────┐
│  LAYER 1: ROUTER (Dumb HTTP Coordinator)                       │
│  - No business logic (no if/else)                              │
│  - All dependencies via Depends()                              │
│  - response_model required                                     │
│  - Router calls db.commit()                                    │
├───────────────────────────────────────────────────────────────┤
│  LAYER 2: SECURITY GATEWAY (deps.py)                           │
│  - Identity (get_current_active_user)                          │
│  - Gatekeeping (CasbinAuth / require_roles)                    │
│  - Resource Access (get_admission_for_user) → IDOR 404         │
│  - Context Filtering (sanitize params)                         │
├───────────────────────────────────────────────────────────────┤
│  LAYER 3: SERVICE (Pure Business Logic)                        │
│  - No HTTPException, no Request imports                        │
│  - Return (result, post_commit_callback)                       │
│  - Raise Domain Exceptions only                                │
│  - Use Repository for DB access                                │
├───────────────────────────────────────────────────────────────┤
│  LAYER 4: REPOSITORY (Data Access)                             │
│  - Inherit BaseRepository                                      │
│  - selectinload for relationships                              │
│  - Return None (not exceptions)                                │
└───────────────────────────────────────────────────────────────┘
```

### 0.3 Authorization Layers (AUTHORIZATION_GUIDELINES v1.0)

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: AUTHENTICATION (WHO are you?)                      │
│  → get_current_active_user (DEFAULT for business APIs)       │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: AUTHORIZATION (WHAT can you do?)                   │
│  → CasbinAuth (Casbin RBAC) - DEFAULT                        │
│  → require_admin / require_admin_or_manager - Static         │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: RESOURCE ACCESS (WHAT can you touch?)              │
│  → get_admission_for_user (IDOR protection)                  │
│  → Return 404 for unauthorized (NOT 403)                     │
└─────────────────────────────────────────────────────────────┘
```

### 0.4 Architecture Invariants (CRITICAL RULES)

> ⚠️ **MUST READ:** Các quy tắc bất biến không được vi phạm.

#### 0.4.1 State Machine Enforcement

> **ALL updates to `admission_profile.status` MUST go through Service Layer.**
> **Direct database updates are FORBIDDEN except via controlled migrations.**

| Action | Allowed? | Reason |
|--------|:--------:|--------|
| Service `profile.status = "approved"` | ✅ | Has validation |
| SQL `UPDATE admission_profile SET status = 'approved'` | ❌ | Bypasses validation |
| Migration fixing corrupt data | ⚠️ Allowed | Must have audit |

**Risk:** DB không tự chặn update `status` → SQL manual/migration sai sẽ phá invariant.

> **MVP Trade-off Statement:**
> "In MVP, state transitions are validated manually in each service method.
> This is an intentional trade-off for speed.
> A centralized enforcement helper (Section 9.1) will be mandatory before scale."

#### 0.4.2 Audit Scope (MVP vs Scale)

| Transition | MVP Audit | Scale Audit |
|------------|:---------:|:-----------:|
| `override()` | ✅ Full audit | ✅ Full audit |
| `approve()` / `reject()` | ⚡ Basic log | ✅ Full audit |
| `confirm()` / `enroll()` | ⚡ Basic log | ✅ Full audit |

> **Conscious Decision:** MVP chỉ audit **exception path** (override).
> Normal flow sẽ được full audit ở Phase 2 (Section 9.2).

> **Risk Acknowledgment:**
> "Lack of full audit for normal transitions means limited forensic capability in MVP.
> This is acceptable given current scope and single-team ownership."

#### 0.4.3 Lead Coupling Architecture

> **Current design intentionally uses `lead` as identity bridge.**

```
lead.user_id        → Applicant identity (for SELF check)
lead.unit_id        → Organization scope (for Manager check)
lead.assigned_officer_id → Responsible officer
```

**Future Consideration:**
> Future versions MAY snapshot critical identity fields into `admission_profile` to reduce coupling if:
> - 1 lead có nhiều admission
> - lead bị archive / merge

> **Trade-off Statement:**
> "As a result, admission_profile is not fully identity-self-contained in MVP."
> This is a conscious architectural decision to reduce initial complexity.

#### 0.4.4 Version Locking Rule

> **ALL write endpoints MUST check `version` field.**

```python
# MANDATORY pattern for ALL write operations
if profile.version != expected_version:
    raise ConcurrentModificationError("Profile modified by another user")
profile.version += 1
```

| Endpoint | Version Check |
|----------|:-------------:|
| approve | ✅ Required |
| reject | ✅ Required |
| resubmit | ✅ Required |
| confirm | ✅ Required |
| override | ✅ Required |
| finalize | ✅ Required |

**No endpoint is allowed to skip version check.**

#### 0.4.5 applied_rules (JSONB) Usage Guidelines

> `applied_rules` is a **SNAPSHOT** of admission rules at profile creation time.

| Purpose | Allowed? |
|---------|:--------:|
| Snapshot config at creation | ✅ |
| Explain evaluation logic | ✅ |
| Decision-making in submit() | ✅ |
| Update after APPROVED | ❌ FORBIDDEN |
| Business logic outside submit() | ⚠️ Not recommended |

**Rule:** Once status leaves DRAFT, `applied_rules` is **IMMUTABLE**.

#### 0.4.6 Applicant Identity - citizen_id Business Rule

> ⚠️ **CRITICAL BUSINESS RULE - READ CAREFULLY**

**Requirement:** A citizen may participate in multiple admission cycles across different years.

| Scenario | Example |
|----------|--------|
| Student fails → reapplies next year | 2024 REJECTED → 2025 new profile |
| Student changes major/program | 2024 IT → 2025 Business |
| Student changes campus | 2024 HN → 2025 HCM |

**Constraint Change:**

```python
# ❌ WRONG (current):
citizen_id: UNIQUE  # Blocks re-application!

# ✅ CORRECT (recommended):
UNIQUE (citizen_id, admission_cycle_id)
# OR
UNIQUE (citizen_id, admission_year)
```

**State Machine Impact:** NONE
- State machine applies per `admission_profile`
- ENROLLED is final only for THAT cycle
- New year = new profile = new state lifecycle

> **Definitive Statement:**
> "Citizen_id uniqueness is scoped per admission cycle, not globally.
> The system enforces identity consistency within a single admission lifecycle,
> while allowing historical re-application without data mutation."

---

## 1. TỔNG QUAN

### 1.1 Mục tiêu
Triển khai State Machine đầy đủ cho quy trình Admission, thay thế flow đơn giản hiện tại bằng workflow có kiểm soát chặt chẽ hơn.

### 1.2 State Diagram

```
DRAFT → SUBMITTED → APPROVED → CONFIRMED → ENROLLED
                 ↘ REJECTED → RESUBMITTED ↗
          APPROVED ↘ OVERRIDDEN ↗ → ENROLLED
```

### 1.3 Scope

| In Scope | Out of Scope |
|----------|--------------|
| 6 endpoints mới | UI/Frontend changes |
| Casbin policies | Email notifications |
| State machine validation | Reporting/Analytics |
| Audit logging | Batch operations |

### 1.4 State Transition Map (Enum-based)

> ⚠️ **REQUIRED:** Use this map for validation. Future states (WAIT_PAYMENT, EXPIRED) can be added easily.

```python
# app/services/admission_state_machine.py
from enum import Enum
from typing import Set, Dict

class AdmissionStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESUBMITTED = "resubmitted"
    CONFIRMED = "confirmed"
    OVERRIDDEN = "overridden"
    ENROLLED = "enrolled"  # FINAL

# Single source of truth for transitions
ALLOWED_TRANSITIONS: Dict[AdmissionStatus, Set[AdmissionStatus]] = {
    AdmissionStatus.DRAFT: {AdmissionStatus.SUBMITTED},
    AdmissionStatus.SUBMITTED: {AdmissionStatus.APPROVED, AdmissionStatus.REJECTED},
    AdmissionStatus.REJECTED: {AdmissionStatus.RESUBMITTED},
    AdmissionStatus.RESUBMITTED: {AdmissionStatus.APPROVED, AdmissionStatus.REJECTED},
    AdmissionStatus.APPROVED: {AdmissionStatus.CONFIRMED, AdmissionStatus.OVERRIDDEN},
    AdmissionStatus.OVERRIDDEN: {AdmissionStatus.ENROLLED},
    AdmissionStatus.CONFIRMED: {AdmissionStatus.ENROLLED},
    AdmissionStatus.ENROLLED: set(),  # Final state - no transitions
}

def can_transition(current: str, target: str) -> bool:
    """Check if transition is valid according to state machine."""
    try:
        current_status = AdmissionStatus(current)
        target_status = AdmissionStatus(target)
        return target_status in ALLOWED_TRANSITIONS.get(current_status, set())
    except ValueError:
        return False

def get_allowed_transitions(current: str) -> Set[str]:
    """Get all valid next states for current status."""
    try:
        current_status = AdmissionStatus(current)
        return {s.value for s in ALLOWED_TRANSITIONS.get(current_status, set())}
    except ValueError:
        return set()
```

### 1.5 Database Schema

> 📌 **Coders cần nắm rõ các bảng và mối quan hệ trước khi code.**

#### 1.5.1 Entity Relationship Diagram (ERD)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ADMISSION WORKFLOW ERD                             │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌────────────────┐
                              │      user      │
                              │  (actor: who)  │
                              └───────┬────────┘
                                      │ approved_by_id, created_by_id
                                      ▼
┌──────────────────┐        ┌────────────────────────────────┐
│       lead       │───────▶│      admission_profile         │
│  (thí sinh gốc)  │ 1:1    │   (CORE - status state machine)│
│                  │        ├────────────────────────────────┤
│  - user_id (FK)  │        │  - lead_id (FK)                │
│  - unit_id (FK)  │        │  - status: draft/submitted/... │
│  - assigned_     │        │  - version (optimistic lock)   │
│    officer_id    │        │  - applied_rules (JSONB)       │
└──────────────────┘        └───────┬────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼ 1:N                     ▼ 1:N                     ▼ 1:1 (on ENROLLED)
┌──────────────────┐  ┌────────────────────┐  ┌──────────────────────┐
│profile_subject_  │  │  profile_document  │  │       student        │
│     score        │  │                    │  │  (final enrollment)  │
├──────────────────┤  ├────────────────────┤  ├──────────────────────┤
│ - profile_id(FK) │  │ - profile_id (FK)  │  │ - profile_id (FK)    │
│ - subject_id(FK) │  │ - doc_type_id (FK) │  │ - student_code       │
│ - score          │  │ - status           │  │ - enrolled_at        │
└──────────────────┘  │ - file_path        │  └──────────┬───────────┘
                      └────────────────────┘             │ 1:N
                                                         ▼
                                            ┌──────────────────────┐
                                            │   student_document   │
                                            └──────────────────────┘
```

#### 1.5.2 Danh Sách Bảng Liên Quan

| # | Table Name | Model Class | File | Vai trò |
|:-:|------------|-------------|------|---------|
| 1 | `admission_profile` | AdmissionProfile | admission.py | **CHÍNH** - Chứa status |
| 2 | `lead` | Lead | lead.py | IDOR check via `unit_id` |
| 3 | `user` | User | user.py | Actor (officer/manager/admin) |
| 4 | `profile_subject_score` | ProfileSubjectScore | profile_data.py | Điểm thi |
| 5 | `profile_document` | ProfileDocument | profile_data.py | Documents uploaded |
| 6 | `student` | Student | student.py | Kết quả enrollment |
| 7 | `student_document` | StudentDocument | student.py | Docs from profile |
| 8 | `casbin_rule` | - | Casbin adapter | Authorization |

#### 1.5.3 Mối Quan Hệ Chính

```python
# 1. admission_profile ←→ lead (One-to-One)
admission_profile.lead_id → lead.id  # FK, UNIQUE

# 2. admission_profile ←→ profile_subject_score (One-to-Many)
profile_subject_score.profile_id → admission_profile.id  # CASCADE

# 3. admission_profile ←→ profile_document (One-to-Many)  
profile_document.profile_id → admission_profile.id  # CASCADE

# 4. admission_profile ←→ student (One-to-One, on ENROLLED)
student.profile_id → admission_profile.id  # UNIQUE

# 5. lead ←→ user (IDOR check points)
lead.user_id → user.id  # Owner (for SELF check in confirm)
lead.assigned_officer_id → user.id  # Officer managing
lead.unit_id → organization_unit.id  # Manager unit check
```

#### 1.5.4 Optimistic Locking (Race Condition Prevention)

```python
# admission_profile.version - Increment on every update
async def approve_profile(db, profile, expected_version):
    if profile.version != expected_version:
        raise ConcurrentModificationError("Profile modified by another user")
    profile.version += 1
```

#### 1.5.5 Index Strategy

> 📌 **DBA/Reviewer cần biết:** Các index chiến lược cho performance.

| Table | Column(s) | Index Type | Purpose |
|-------|-----------|:----------:|---------|
| `admission_profile` | `status` | B-tree | Filter by status |
| `admission_profile` | `lead_id` | UNIQUE | 1:1 relationship |
| `admission_profile` | `citizen_id` | UNIQUE | Prevent duplicate enrollment |
| `student` | `profile_id` | UNIQUE | 1:1 relationship |
| `profile_subject_score` | `profile_id` | B-tree | FK lookup |
| `profile_subject_score` | `(profile_id, subject_id)` | UNIQUE | Composite unique |
| `profile_document` | `profile_id` | B-tree | FK lookup |
| `profile_document` | `(profile_id, document_type_id)` | UNIQUE | Composite unique |

> **Note:** Các index này đã tồn tại trong model definitions.

---

## PHASE 0: JSONB → RELATIONAL REFACTOR (NEW)

> 🔄 **Pre-requisite cho MVP:** Loại bỏ JSONB legacy, chuyển hoàn toàn sang Relational tables.

### 0.1 Tại sao làm Phase 0?

| Factor | JSONB (Legacy) | Relational (New) |
|--------|:--------------:|:----------------:|
| Query performance | ⚠️ Chậm với filter | ✅ Tối ưu với index |
| Data integrity | ❌ Không FK | ✅ Có FK constraints |
| Type safety | ❌ Untyped | ✅ Typed columns |
| Migration complexity | N/A | 1 lần duy nhất |

**Quyết định:** Vì chưa có data trong admission, refactor NGAY để tránh technical debt.

### 0.2 Scope

| JSONB Field (XÓA) | Relational Table (GIỮ) |
|-------------------|------------------------|
| `admission_scores` | `profile_subject_score` |
| `documents_checklist` | `profile_document` |

### 0.3 Files to Modify

| Layer | File | Changes |
|-------|------|---------|
| **Model** | `app/models/admission.py` | Remove JSONB columns |
| **Schema** | `app/schemas/admission.py` | Remove JSONB schemas, use nested |
| **Service** | `app/services/admission_service.py` | Refactor 25+ usages |
| **Router** | `app/routers/admissions.py` | Update docstrings |
| **Migration** | `alembic/versions/` | Drop JSONB columns |

### 0.4 Detailed Changes

#### 0.4.1 Model Changes (`admission.py`)

```python
# ❌ REMOVE these lines:
admission_scores: Mapped[dict] = mapped_column(JSONB, ...)      # Line ~158
documents_checklist: Mapped[list] = mapped_column(JSONB, ...)   # Line ~167

# ✅ KEEP these (already exist):
subject_scores: Mapped[list] = relationship("ProfileSubjectScore", ...)
documents: Mapped[list] = relationship("ProfileDocument", ...)
```

#### 0.4.2 Service Refactor (`admission_service.py`)

```python
# ❌ BEFORE (JSONB):
profile.admission_scores = {"math": 8.5, "gpa": 7.5}
gpa = profile.admission_scores.get("gpa")

# ✅ AFTER (Relational):
await ProfileSubjectScore.create(profile_id=profile.id, subject_id=1, score=8.5)
scores = await repo.get_scores_by_profile(profile.id)
gpa = calculate_gpa(scores)
```

```python
# ❌ BEFORE (JSONB):
profile.documents_checklist = [{"code": "CMND", "status": "uploaded"}]

# ✅ AFTER (Relational):
await ProfileDocument.create(profile_id=profile.id, doc_type_id=1, status="uploaded")
docs = profile.documents  # via relationship
```

#### 0.4.3 Schema Changes (`admission.py`)

```python
# ❌ REMOVE:
class AdmissionScoreSchema(BaseModel):
    gpa: Optional[float]
    ...

# ✅ ADD/USE:
class ProfileSubjectScoreResponse(BaseModel):
    subject_id: int
    subject_name: str
    score: float

class ProfileDocumentResponse(BaseModel):
    document_type_id: int
    document_type_name: str
    status: str
    file_path: Optional[str]
```

### 0.5 Migration Script

```python
# p7_remove_jsonb_columns.py
def upgrade():
    # 1. Verify no data exists
    result = conn.execute(text("SELECT COUNT(*) FROM admission_profile"))
    if result.scalar() > 0:
        raise Exception("ABORT: Data exists. Manual migration required.")
    
    # 2. Drop JSONB columns
    op.drop_column('admission_profile', 'admission_scores')
    op.drop_column('admission_profile', 'documents_checklist')

def downgrade():
    # Restore JSONB columns
    op.add_column('admission_profile', sa.Column('admission_scores', JSONB, nullable=True))
    op.add_column('admission_profile', sa.Column('documents_checklist', JSONB, nullable=True))
```

### 0.6 Timeline & Effort

| Task | Effort | Priority |
|------|:------:|:--------:|
| Model changes | 0.5 day | P0 |
| Service refactor | 2 days | P0 |
| Schema updates | 0.5 day | P0 |
| Migration | 0.5 day | P0 |
| Testing | 1 day | P0 |
| **TOTAL** | **4.5 days** | |

### 0.7 Acceptance Criteria

- [ ] `admission_scores` column removed from model
- [ ] `documents_checklist` column removed from model
- [ ] All service methods use `ProfileSubjectScore` 
- [ ] All service methods use `ProfileDocument`
- [ ] Schemas updated for relational responses
- [ ] All tests pass
- [ ] No grep results for `admission_scores` or `documents_checklist` (except comments)

> **Architectural Correction Statement:**
> "This refactor is a one-time architectural correction, not an optimization.
> Skipping it would permanently lock the system into weak data integrity.
> Doing it now (with zero data) is 10x cheaper than migrating production data later."

---

## 2. PHÂN CÔNG QUYỀN HẠN

### 2.1 Role-Action Matrix

| Action | Endpoint | User | Officer | Manager | Admin | STATE Check |
|--------|----------|:----:|:-------:|:-------:|:-----:|:-----------:|
| `approve()` | `POST /admissions/{id}/approve` | ❌ | ❌ | ✅ | ✅ | SUBMITTED/RESUBMITTED |
| `reject()` | `POST /admissions/{id}/reject` | ❌ | ❌ | ✅ | ✅ | SUBMITTED/RESUBMITTED |
| `resubmit()` | `POST /admissions/{id}/resubmit` | ❌ | ✅ | ✅ | ✅ | REJECTED |
| `confirm()` | `POST /admissions/{id}/confirm` | ✅* | ❌ | ❌ | ✅ | APPROVED |
| `override()` | `POST /admissions/{id}/override` | ❌ | ❌ | ❌ | ✅ | APPROVED |
| `finalize()` | `POST /admissions/{id}/finalize` | ❌ | ❌ | ❌ | ✅ | OVERRIDDEN |

> *User chỉ confirm profile của chính mình (SELF check)

### 2.2 Authorization Layers per Endpoint

| Endpoint | Layer 1 (Auth) | Layer 2 (RBAC) | Layer 3 (IDOR) | Extra Check |
|----------|----------------|----------------|----------------|-------------|
| `approve` | `get_current_active_user` | `CasbinAuth` | `get_admission_for_manager` | STATE |
| `reject` | `get_current_active_user` | `CasbinAuth` | `get_admission_for_manager` | STATE + reason |
| `resubmit` | `get_current_active_user` | `CasbinAuth` | `get_admission_for_user` | STATE |
| `confirm` | `get_current_active_user` | `CasbinAuth` | `get_admission_for_owner` | SELF + STATE |
| `override` | `get_current_active_user` | `require_admin` | Direct (admin) | AUDIT + reason |
| `finalize` | `get_current_active_user` | `require_admin` | Direct (admin) | STATE + AUDIT |

---

## 3. IMPLEMENTATION PHASES

### Phase 1: Core Approval Flow (3 days)
**Priority:** HIGH

#### 3.1.1 Endpoints

| Endpoint | Method | Router Auth | IDOR Dep | Service Method |
|----------|--------|-------------|----------|----------------|
| `/admissions/{id}/approve` | POST | CasbinAuth | get_admission_for_manager | approve_profile() |
| `/admissions/{id}/reject` | POST | CasbinAuth | get_admission_for_manager | reject_profile() |

#### 3.1.2 Files to Modify (Layer Structure)

| Layer | File | Changes |
|-------|------|---------|
| **Router** | `app/routers/admissions.py` | Add 2 endpoints (no logic!) |
| **Dependency** | `app/core/deps.py` | Add `get_admission_for_manager` |
| **Service** | `app/services/admission_service.py` | Add approve/reject with callback |
| **Schema** | `app/schemas/admission.py` | Add ApproveRequest, RejectRequest |

#### 3.1.3 Code Template (Compliant)

```python
# Router (LAYER 1) - DUMB COORDINATOR
@router.post("/{profile_id}/approve", response_model=AdmissionProfileResponse)
async def approve_admission(
    request: Request,
    profile_id: int,
    data: ApproveRequest,
    # ======== LAYER 2: AUTH + RBAC ========
    current_user: models.User = CasbinAuth,  # Casbin checks Manager/Admin
    # ======== LAYER 3: IDOR ========
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve admission profile.
    
    **Architecture Compliance:**
    - Router: No logic, just delegation
    - Auth: CasbinAuth (Manager+ via Casbin policy)
    - IDOR: get_admission_for_manager (unit check)
    - Service: Returns (result, callback)
    """
    # 1. DELEGATE to Service (no if/else here!)
    result, callback = await admission_service.approve_profile(
        db, profile, current_user, data
    )
    
    # 2. COMMIT Transaction (Router responsibility)
    await db.commit()
    
    # 3. POST-COMMIT Side Effects
    await callback()
    
    # 4. RETURN Pydantic Model
    return result
```

```python
# Service (LAYER 3) - PURE LOGIC
async def approve_profile(
    db: AsyncSession,
    profile: AdmissionProfile,
    approver: User,
    data: ApproveRequest,
) -> Tuple[AdmissionProfile, Callable]:
    """
    **Architecture Compliance:**
    - No HTTPException (use Domain Exceptions)
    - No Request/Response imports
    - Return callback for side effects
    - Use Repository for DB access
    """
    # 1. STATE VALIDATION (Business Rule)
    if profile.status not in ["submitted", "resubmitted"]:
        raise BusinessRuleViolation(
            f"Cannot approve profile in {profile.status} status"
        )
    
    # 2. STATE CHANGE
    profile.status = "approved"
    profile.approved_at = datetime.now(timezone.utc)
    profile.approved_by_id = approver.id
    profile.approval_notes = data.notes
    
    await db.flush()  # Flush, don't commit!
    
    # 3. PREPARE CALLBACK
    async def post_commit():
        await notify_applicant_approved(profile)
    
    return profile, post_commit
```

```python
# Dependency (LAYER 2) - SECURITY GATEWAY
async def get_admission_for_manager(
    profile_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> models.AdmissionProfile:
    """
    IDOR Protection for Manager actions.
    
    **Rules:**
    - Admin: Can access all profiles
    - Manager: Can access profiles in their unit
    - Return 404 (not 403) for unauthorized
    """
    repo = AdmissionRepository(db)
    profile = await repo.get_with_lead(profile_id)
    
    if not profile:
        raise ResourceNotFoundError()  # 404
    
    # IDOR CHECK
    if current_user.role != "admin":
        if profile.lead.unit_id != current_user.unit_id:
            raise ResourceNotFoundError()  # Fake 404!
    
    return profile
```

#### 3.1.4 Casbin Policies

```python
# Add to policy_templates.py MANAGER_TEMPLATE
("role:manager", "/api/admissions/{id}/approve", "POST"),
("role:manager", "/api/admissions/{id}/reject", "POST"),
```

---

### Phase 2: Recovery Flow (2 days)
**Priority:** HIGH

#### 3.2.1 Endpoint

| Endpoint | Method | Router Auth | IDOR Dep | Service Method |
|----------|--------|-------------|----------|----------------|
| `/admissions/{id}/resubmit` | POST | CasbinAuth | get_admission_for_user | resubmit_profile() |

#### 3.2.2 Authorization Layers

```python
# Router
current_user: models.User = CasbinAuth,  # Officer+
profile: models.AdmissionProfile = Depends(get_admission_for_user),  # IDOR
```

#### 3.2.3 Casbin Policies

```python
# Add to OFFICER_TEMPLATE
("role:officer", "/api/admissions/{id}/resubmit", "POST"),
```

---

### Phase 3: User Confirmation (2 days)
**Priority:** MEDIUM

#### 3.3.1 Endpoint

| Endpoint | Method | Router Auth | IDOR Dep | Service Method |
|----------|--------|-------------|----------|----------------|
| `/admissions/{id}/confirm` | POST | CasbinAuth | get_admission_for_owner | confirm_enrollment() |

#### 3.3.2 Special: SELF Check

```python
# Dependency - OWNER ONLY (SELF CHECK)
async def get_admission_for_owner(
    profile_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> models.AdmissionProfile:
    """
    SELF check: Only the profile owner (applicant) can confirm.
    
    ⚠️ FIXED (Review 2026-01-06):
    - OLD (BUG): assigned_officer_id check (wrong! that's officer)
    - NEW (CORRECT): lead.user_id check (actual applicant)
    
    Admin can also confirm as override.
    """
    repo = AdmissionRepository(db)
    profile = await repo.get_with_lead(profile_id)
    
    if not profile:
        raise ResourceNotFoundError()
    
    # SELF CHECK - Must be profile OWNER (applicant)
    # NOT assigned_officer_id (that's the officer managing the lead!)
    if current_user.role != "admin":
        # The applicant is linked via lead.user_id (not assigned_officer_id)
        if profile.lead.user_id != current_user.id:
            raise ResourceNotFoundError()  # Fake 404 (IDOR protection)
    
    return profile
```

#### 3.3.3 Casbin Policies

```python
# Add to BASIC_USER_TEMPLATE
("role:user", "/api/admissions/{id}/confirm", "POST"),
```

---

### Phase 4: Exception Handling (2 days)
**Priority:** MEDIUM

#### 3.4.1 Endpoints

| Endpoint | Method | Router Auth | IDOR Dep | Audit |
|----------|--------|-------------|----------|:-----:|
| `/admissions/{id}/override` | POST | `require_admin` | Direct | ✅ |
| `/admissions/{id}/finalize` | POST | `require_admin` | Direct | ✅ |

#### 3.4.2 Override Audit Requirements

```python
# Schema - Reason REQUIRED
class OverrideRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Required explanation")
    bypass_rules: list[str] = []

# Service - Full Audit
async def override_profile(db, profile, admin, data):
    # ... business logic ...
    
    # AUDIT LOG (per AUTHORIZATION_DECISIONS.md Decision 11)
    await log_override_action(
        actor_id=admin.id,
        profile_id=profile.id,
        reason=data.reason,
        bypassed_rules=data.bypass_rules,
    )
    
    return profile, callback
```

---

### Phase 5: Migration & Testing (2 days)
**Priority:** HIGH

#### 3.5.1 Alembic Migration

```python
# p6_add_admission_state_policies.py
policies_to_add = [
    # Manager: approve/reject
    ("role:manager", "/api/admissions/{id}/approve", "POST"),
    ("role:manager", "/api/admissions/{id}/reject", "POST"),
    # Officer: resubmit
    ("role:officer", "/api/admissions/{id}/resubmit", "POST"),
    # User: confirm (SELF check in dependency)
    ("role:user", "/api/admissions/{id}/confirm", "POST"),
    # Admin: explicit override/finalize (NOT via wildcard for clarity)
    # NOTE: Admin already has /* wildcard, but we add explicit for:
    # 1. Documentation/clarity
    # 2. Audit trail (can track usage)
    # 3. Fine-grained control if needed later
    ("role:admin", "/api/admissions/{id}/override", "POST"),
    ("role:admin", "/api/admissions/{id}/finalize", "POST"),
]
```

> ⚠️ **WILDCARD CLARIFICATION (Review 2026-01-06):**
> - Admin has `(role:admin, /*, .*)` wildcard → covers all endpoints
> - But we add override/finalize explicitly for:
>   - Documentation clarity
>   - Audit tracking
>   - Future fine-grained control
> - **NEVER** add `"/api/admissions/*"` wildcard for non-admin roles

#### 3.5.2 Tests

| Test Type | Scope | Tool |
|-----------|-------|------|
| Unit | State machine transitions | pytest |
| Unit | Service logic | pytest + mock |
| Integration | Full endpoint flow | pytest + TestClient |
| Authorization | Role-based access | pytest + CasbinAuth mock |

#### 3.5.3 Killer Test Cases (REQUIRED)

> ⚠️ **These 2 cases prevent production disasters. DO NOT SKIP.**

##### 🔥 Case 1: Race Condition (Concurrent Approval)

```python
# tests/integration/test_admission_race_condition.py
async def test_concurrent_approve_reject():
    """
    Scenario: 2 managers approve/reject same profile simultaneously.
    Expected: One succeeds, one fails with BusinessRuleViolation.
    
    Implementation options:
    1. Optimistic locking (version column)
    2. SELECT FOR UPDATE (pessimistic)
    3. Last-write-wins with audit trail
    """
    profile = await create_submitted_profile()
    
    # Simulate concurrent requests
    async with asyncio.TaskGroup() as tg:
        task1 = tg.create_task(approve_profile(profile.id, manager_1))
        task2 = tg.create_task(reject_profile(profile.id, manager_2))
    
    # One should succeed, one should fail
    results = [task1.result(), task2.result()]
    success_count = sum(1 for r in results if r.status_code == 200)
    error_count = sum(1 for r in results if r.status_code == 400)
    
    assert success_count == 1
    assert error_count == 1
    
    # Verify final state is consistent
    profile = await get_profile(profile.id)
    assert profile.status in ["approved", "rejected"]  # Not stuck!
```

##### 🔥 Case 2: Replay Attack (Double Approval)

```python
# tests/integration/test_admission_replay_attack.py
async def test_approve_already_approved():
    """
    Scenario: Attacker calls /approve again after profile already approved.
    Expected: BusinessRuleViolation (idempotent rejection).
    """
    profile = await create_submitted_profile()
    
    # First approve - should succeed
    response1 = await approve_profile(profile.id, manager)
    assert response1.status_code == 200
    
    # Second approve - should fail with clear error
    response2 = await approve_profile(profile.id, manager)
    assert response2.status_code == 400
    assert "Cannot approve profile in approved status" in response2.json()["detail"]
    
    # Status should remain approved (not corrupted)
    profile = await get_profile(profile.id)
    assert profile.status == "approved"
```

---

## 4. COMPLIANCE CHECKLISTS

### 4.1 Router Checklist (per MASTER_ARCHITECTURE Part 3)

| Endpoint | response_model | Depends() | No if/else | db.commit() | deps.py check |
|----------|:--------------:|:---------:|:----------:|:-----------:|:-------------:|
| approve | ✅ | ✅ | ✅ | ✅ | ✅ |
| reject | ✅ | ✅ | ✅ | ✅ | ✅ |
| resubmit | ✅ | ✅ | ✅ | ✅ | ✅ |
| confirm | ✅ | ✅ | ✅ | ✅ | ✅ |
| override | ✅ | ✅ | ✅ | ✅ | ✅ |
| finalize | ✅ | ✅ | ✅ | ✅ | ✅ |

### 4.2 Service Checklist

| Endpoint | No HTTPException | Uses Repo | Returns callback | Domain Exceptions |
|----------|:----------------:|:---------:|:----------------:|:-----------------:|
| approve | ✅ | ✅ | ✅ | ✅ |
| reject | ✅ | ✅ | ✅ | ✅ |
| resubmit | ✅ | ✅ | ✅ | ✅ |
| confirm | ✅ | ✅ | ✅ | ✅ |
| override | ✅ | ✅ | ✅ | ✅ |
| finalize | ✅ | ✅ | ✅ | ✅ |

### 4.3 Security Checklist (per AUTHORIZATION_GUIDELINES Part 10)

| Endpoint | get_current_active_user | Auth Layer | IDOR dep | 404 not 403 |
|----------|:-----------------------:|:----------:|:--------:|:-----------:|
| approve | ✅ | CasbinAuth | get_admission_for_manager | ✅ |
| reject | ✅ | CasbinAuth | get_admission_for_manager | ✅ |
| resubmit | ✅ | CasbinAuth | get_admission_for_user | ✅ |
| confirm | ✅ | CasbinAuth | get_admission_for_owner | ✅ |
| override | ✅ | require_admin | Direct | N/A |
| finalize | ✅ | require_admin | Direct | N/A |

---

## 5. TIMELINE

```
Week 1:
├── Day 1-2: Phase 1 (approve/reject) + deps.py
├── Day 3-4: Phase 2 (resubmit)
└── Day 5: Testing Phase 1-2

Week 2:
├── Day 1-2: Phase 3 (confirm) + SELF check
├── Day 3-4: Phase 4 (override/finalize) + audit
└── Day 5: Phase 5 (migration + full testing)
```

**Total estimate:** 10 working days

---

## 6. RISKS & MITIGATIONS

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Architecture violation | HIGH | LOW | Use checklists, PR review |
| IDOR vulnerability | HIGH | MEDIUM | All IDOR via deps.py |
| State machine bugs | HIGH | MEDIUM | Comprehensive unit tests |
| Override abuse | HIGH | LOW | Audit alerts + review |

---

## 7. ACCEPTANCE CRITERIA

### Phase 1
- [ ] Manager can approve → status = APPROVED
- [ ] Manager can reject → status = REJECTED with reason
- [ ] Non-manager cannot approve/reject → 403
- [ ] **Complies with ROUTER CHECKLIST**
- [ ] **Complies with SECURITY CHECKLIST**

### Phase 2
- [ ] Officer can resubmit → status = RESUBMITTED
- [ ] Cannot resubmit non-REJECTED → 400
- [ ] **IDOR: Officer only sees their unit's profiles**

### Phase 3
- [ ] Owner can confirm → status = CONFIRMED
- [ ] Non-owner cannot confirm → 404 (not 403!)
- [ ] **SELF check enforced in dependency**

### Phase 4
- [ ] Admin can override → status = OVERRIDDEN
- [ ] Override requires reason → 400 if missing
- [ ] **Full audit trail logged**

---

## 8. APPENDIX

### 8.1 Architecture References
- `MASTER_ARCHITECTURE.md` - Part 0-5
- `AUTHORIZATION_GUIDELINES.md` - Section 1-11
- `AUTHORIZATION_DECISIONS.md` - Decision 10, 11

### 8.2 Related Files
- `app/routers/admissions.py` - Router layer
- `app/services/admission_service.py` - Service layer
- `app/repositories/admission_repository.py` - Repository layer
- `app/core/deps.py` - Security gateway
- `app/schemas/admission.py` - Pydantic models

### 8.3 New Dependencies to Create

| Dependency | Purpose | Location |
|------------|---------|----------|
| `get_admission_for_manager` | IDOR for Manager actions | `deps.py` |
| `get_admission_for_owner` | SELF check for confirm | `deps.py` |

---

## 9. FUTURE ENHANCEMENTS (PRINCIPAL LEVEL)

> ⚠️ **NOT REQUIRED for MVP.** These are architectural improvements for long-term maintainability.

### 9.1 Lock Invariant via Shared Helper

**Problem:** Manual state checks in each service can be bypassed or inconsistent.

**Current (Manual):**
```python
# In each service method
if profile.status not in ["submitted", "resubmitted"]:
    raise BusinessRuleViolation(...)
```

**Proposed (Forced):**
```python
# app/services/admission_state_machine.py
def transition_to(
    profile: AdmissionProfile, 
    target: AdmissionStatus,
    actor: User,
    db: AsyncSession,
) -> None:
    """
    SINGLE POINT OF TRUTH for all state transitions.
    
    Benefits:
    - Cannot bypass validation
    - Automatic audit logging
    - Consistent error messages
    """
    if not can_transition(profile.status, target.value):
        raise BusinessRuleViolation(
            f"Invalid transition: {profile.status} → {target.value}"
        )
    
    old_status = profile.status
    profile.status = target.value
    
    # Auto-audit (see 9.2)
    await log_state_transition(profile.id, old_status, target.value, actor.id)
```

**Service Usage:**
```python
# All services MUST use this
async def approve_profile(db, profile, approver, data):
    transition_to(profile, AdmissionStatus.APPROVED, approver, db)
    # ... rest of logic
```

**Benefits:**
- ❌ No service can bypass state machine
- ✅ Consistent validation across codebase
- ✅ Single place to add new states
- ✅ Audit logging built-in

---

### 9.2 Audit All Transitions (Not Just Override)

**Current:** Only `override()` has explicit audit logging.

**Proposed:** Log EVERY state transition.

```python
# app/services/admission_audit.py
from datetime import datetime, timezone
from typing import Optional

async def log_state_transition(
    profile_id: int,
    from_status: str,
    to_status: str,
    actor_id: int,
    reason: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Universal audit log for admission state changes.
    
    Use cases:
    - Debug: "Why is this profile in REJECTED?"
    - Legal: "Who approved this and when?"
    - Analytics: "Average time from SUBMITTED to APPROVED"
    - Compliance: "Show audit trail for profile #1234"
    """
    await AdmissionAuditLog.create(
        profile_id=profile_id,
        from_status=from_status,
        to_status=to_status,
        actor_id=actor_id,
        reason=reason,
        metadata=metadata or {},
        timestamp=datetime.now(timezone.utc),
    )
```

**Database Model:**
```python
class AdmissionAuditLog(Base):
    __tablename__ = "admission_audit_log"
    
    id: int
    profile_id: int  # FK to admission_profile
    from_status: str
    to_status: str
    actor_id: int  # FK to user
    reason: str | None  # Required for reject/override
    metadata: dict  # Extra context (e.g., bypass_rules)
    timestamp: datetime
```

**Benefits:**
| Use Case | Query Example |
|----------|---------------|
| Debug | `WHERE profile_id = 123 ORDER BY timestamp` |
| Legal | `WHERE to_status = 'enrolled' AND profile_id = 123` |
| Analytics | `AVG(timestamp diff) WHERE from='submitted' AND to='approved'` |
| Compliance | Full transition history with actor names |

---

### 9.3 Implementation Priority

| Enhancement | Priority | Effort | When to Implement |
|-------------|:--------:|:------:|-------------------|
| 9.1 Transition Helper | MEDIUM | 2 days | Phase 2 (after MVP) |
| 9.2 Universal Audit | MEDIUM | 3 days | Phase 2 (before scale) |

> 💡 **Recommendation:** Implement both together since 9.1 naturally calls 9.2.

---

**END OF PLAN**

> *"Architecture is not about making code work.*  
> *It's about making code correct by construction."*
