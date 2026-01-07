# 📋 PHASE 0: JSONB → RELATIONAL REFACTOR – IMPLEMENTATION PLAN

> **Version:** 1.0  
> **Created:** 2026-01-07  
> **Author:** Architecture Team  
> **Status:** 🔄 PENDING REVIEW  
> **Compliance:** MASTER_ARCHITECTURE.md v3.0 + AUTHORIZATION_GUIDELINES.md v1.0

---

## 0. ARCHITECTURE COMPLIANCE REFERENCES

### 0.1 Source of Truth Documents

| Document | Path | Purpose |
|----------|------|---------|
| **MASTER_ARCHITECTURE.md** | `Backend_FastAPI/MASTER_ARCHITECTURE.md` | 4-layer architecture, coding standards |
| **AUTHORIZATION_GUIDELINES.md** | `Backend_FastAPI/AUTHORIZATION_GUIDELINES.md` | 3-layer auth model, IDOR protection |
| **profile_data.py** | `app/models/admission_config/profile_data.py` | Target relational models |

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

### 0.3 Architecture Invariants (CRITICAL RULES)

> ⚠️ **MUST READ:** Các quy tắc bất biến không được vi phạm.

#### 0.3.1 Data Access Pattern

> **ALL data access MUST go through Repository Layer.**
> **Direct SQL in Router/Service is FORBIDDEN.**

| Action | Allowed? | Reason |
|--------|:--------:|--------|
| `repo.get_documents(profile_id)` | ✅ | Via Repository |
| `db.query(ProfileDocument).filter(...)` | ❌ | Bypasses Repository |
| `profile.documents` (relationship) | ✅ | Eager loaded |

#### 0.3.2 Relationship Loading

> **ALL relationships MUST use `selectinload` to prevent N+1 queries.**

```python
# ✅ CORRECT - selectinload in Repository
.options(selectinload(AdmissionProfile.documents))

# ❌ WRONG - lazy loading in Router
for doc in profile.documents:  # N+1 if not eager loaded!
```

#### 0.3.3 Service Return Pattern

> **Service methods modifying data MUST return `(result, callback)`.**

```python
# ✅ CORRECT
async def upload_document(...) -> tuple[ProfileDocument, Callable]:
    ...
    return doc, post_commit_callback

# ❌ WRONG
async def upload_document(...) -> ProfileDocument:
    await db.commit()  # NEVER in service!
    return doc
```

---

## 1. TỔNG QUAN

### 1.1 Mục tiêu

Loại bỏ JSONB legacy columns (`admission_scores`, `documents_checklist`) và chuyển hoàn toàn sang Relational tables để đảm bảo:
- ✅ Data integrity với FK constraints
- ✅ Query performance với indexes
- ✅ Type safety với typed columns
- ✅ Consistent với architecture patterns

### 1.2 Current State vs Target State

```
CURRENT (Hybrid):
┌─────────────────────────────────────────────┐
│ admission_profile                            │
│ ├── admission_scores (JSONB)     ← XÓA     │
│ ├── documents_checklist (JSONB)  ← XÓA     │
│ ├── subject_scores (relationship) ✓ GIỮ    │
│ └── documents (relationship)      ✓ GIỮ    │
└─────────────────────────────────────────────┘

TARGET (Relational Only):
┌─────────────────────────────────────────────┐
│ admission_profile                            │
│ ├── subject_scores → ProfileSubjectScore    │
│ └── documents → ProfileDocument             │
└─────────────────────────────────────────────┘
```

### 1.3 Scope

| In Scope | Out of Scope |
|----------|--------------|
| Remove 2 JSONB columns | Frontend changes |
| Refactor 6 service methods | API response format change |
| Add Repository methods | New endpoints |
| Migration script | Data migration (no production data) |

### 1.4 Entity Relationship Diagram

```
┌────────────────────────┐        ┌──────────────────────┐
│   admission_profile    │───1:N─▶│ profile_subject_score│
│                        │        │ ├── profile_id (FK)  │
│  - id                  │        │ ├── subject_id (FK)  │
│  - lead_id             │        │ └── score            │
│  - status              │        └──────────────────────┘
│  - version             │
│                        │        ┌──────────────────────┐
│ ❌ admission_scores    │───1:N─▶│   profile_document   │
│ ❌ documents_checklist │        │ ├── profile_id (FK)  │
│                        │        │ ├── document_type_id │
│                        │        │ ├── status           │
└────────────────────────┘        │ └── file_path        │
                                  └──────────────────────┘
```

---

## 2. IMPLEMENTATION PHASES

### Phase 1: Repository Layer (0.5 day)

#### 2.1.1 Files to Modify

| Layer | File | Changes |
|-------|------|---------|
| **Repository** | `app/repositories/admission_repository.py` | Add 4 new methods |

#### 2.1.2 New Repository Methods

```python
# app/repositories/admission_repository.py

class AdmissionRepository(BaseRepository):
    
    async def create_profile_documents(
        self, 
        profile_id: int, 
        document_type_ids: List[int]
    ) -> List[ProfileDocument]:
        """Create ProfileDocument records for mandatory docs."""
        docs = []
        for doc_type_id in document_type_ids:
            doc = ProfileDocument(
                profile_id=profile_id,
                document_type_id=doc_type_id,
                status="missing"
            )
            self.db.add(doc)
            docs.append(doc)
        await self.db.flush()
        return docs

    async def get_profile_document_by_type(
        self, 
        profile_id: int, 
        document_type_code: str
    ) -> Optional[ProfileDocument]:
        """Get single document by type code."""
        stmt = (
            select(ProfileDocument)
            .join(ProfileDocument.document_type)
            .where(
                ProfileDocument.profile_id == profile_id,
                ConfigDocumentType.code == document_type_code
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_profile_document_status(
        self,
        doc_id: int,
        status: str,
        file_path: Optional[str] = None
    ) -> ProfileDocument:
        """Update document status and file_path."""
        doc = await self.db.get(ProfileDocument, doc_id)
        doc.status = status
        if file_path:
            doc.file_path = file_path
            doc.uploaded_at = datetime.now(timezone.utc)
        return doc

    async def get_uploaded_documents(
        self, 
        profile_id: int
    ) -> List[ProfileDocument]:
        """Get all uploaded documents for a profile."""
        stmt = (
            select(ProfileDocument)
            .options(selectinload(ProfileDocument.document_type))
            .where(
                ProfileDocument.profile_id == profile_id,
                ProfileDocument.status == "uploaded"
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
```

---

### Phase 2: Service Layer Refactor (2 days)

#### 2.2.1 Files to Modify

| Layer | File | Changes |
|-------|------|---------|
| **Service** | `app/services/admission_service.py` | Refactor 6 functions |

#### 2.2.2 Functions to Refactor

| Function | Line | JSONB Usage | New Approach |
|----------|:----:|-------------|--------------|
| `_generate_documents_checklist()` | 83-114 | Creates JSONB array | **DELETE** - replace with repo call |
| `create_profile()` | 254-275 | Sets JSONB fields | Use `repo.create_profile_documents()` |
| `update_profile()` | 510-514 | Updates JSONB | Update via relationships |
| `submit_and_evaluate()` | 591-686 | Reads JSONB | Query from relationships |
| `upload_document()` | 813-880 | Updates JSONB item | Use `repo.update_profile_document_status()` |
| `enroll_student()` | 1011-1034 | Reads JSONB | Use `profile.documents` |

#### 2.2.3 Code Changes

##### `create_profile()` - Lines 254-275

```python
# ❌ BEFORE (JSONB)
documents_checklist = _generate_documents_checklist(mandatory_docs)
new_profile = models.AdmissionProfile(
    admission_scores=None,
    documents_checklist=documents_checklist,
)

# ✅ AFTER (Relational)
new_profile = models.AdmissionProfile(...)
db.add(new_profile)
await db.flush()

# Create ProfileDocument records via Repository
doc_type_ids = await config_repo.get_document_type_ids_by_codes(mandatory_docs)
await admission_repo.create_profile_documents(new_profile.id, doc_type_ids)
```

##### `upload_document()` - Lines 813-880

```python
# ❌ BEFORE (JSONB with flag_modified)
checklist = profile.documents_checklist or []
doc_item = next((d for d in checklist if d["code"] == doc_code), None)
...
profile.documents_checklist = new_checklist
flag_modified(profile, "documents_checklist")

# ✅ AFTER (Relational via Repository)
doc_record = await admission_repo.get_profile_document_by_type(
    profile_id, doc_code
)
if not doc_record:
    raise BadRequest(f"Document code '{doc_code}' not found")

await admission_repo.update_profile_document_status(
    doc_record.id, 
    status="uploaded",
    file_path=file_path
)
```

##### `submit_and_evaluate()` - Score Validation (Lines 591-662)

```python
# ❌ BEFORE (JSONB)
admission_scores = profile.admission_scores or {}
gpa = admission_scores.get("gpa")

# ✅ AFTER (Relational)
# GPA calculated from ProfileSubjectScore records
gpa = await admission_repo.calculate_profile_gpa(profile.id)
# OR use eager loaded relationship
scores_dict = {
    s.subject.code: float(s.score) 
    for s in profile.subject_scores
}
```

##### `submit_and_evaluate()` - Document Validation (Lines 668-686)

```python
# ❌ BEFORE (JSONB)
uploaded_docs = {
    doc["code"]: doc
    for doc in profile.documents_checklist
    if doc.get("status") == "uploaded"
}

# ✅ AFTER (Relational)
uploaded_docs = {
    doc.document_type.code: doc
    for doc in profile.documents
    if doc.status == "uploaded"
}
```

##### `enroll_student()` - Lines 1011-1034

```python
# ❌ BEFORE (JSONB)
for doc_item in profile.documents_checklist:
    if doc_item.get("status") == "uploaded":
        doc = models.StudentDocument(
            doc_type=doc_item["code"],
            file_path=doc_item["file_path"],
        )

# ✅ AFTER (Relational)
for profile_doc in profile.documents:
    if profile_doc.status == "uploaded":
        doc = models.StudentDocument(
            doc_type=profile_doc.document_type.code,
            file_path=profile_doc.file_path,
            uploaded_at=profile_doc.uploaded_at,
        )
```

---

### Phase 3: Model & Migration (0.5 day)

#### 2.3.1 Files to Modify

| Layer | File | Changes |
|-------|------|---------|
| **Model** | `app/models/admission.py` | Remove 2 JSONB columns |
| **Migration** | `alembic/versions/p9_*.py` | Drop columns |

#### 2.3.2 Model Changes

```python
# app/models/admission.py

# ❌ REMOVE (lines 156-172):
-    admission_scores: Mapped[dict] = mapped_column(JSONB, ...)
-    documents_checklist: Mapped[list] = mapped_column(JSONB, ...)

# ✅ KEEP (lines 212-223):
    subject_scores: Mapped[list] = relationship("ProfileSubjectScore", ...)
    documents: Mapped[list] = relationship("ProfileDocument", ...)
```

#### 2.3.3 Migration Script

```python
# alembic/versions/p9_remove_jsonb_columns.py

revision = 'p9a1b2c3d4e5'
down_revision = 'p8a1b2c3d4e5'

def upgrade():
    # Safety: Verify tables exist
    op.drop_column('admission_profile', 'admission_scores')
    op.drop_column('admission_profile', 'documents_checklist')
    print("✅ Removed JSONB columns from admission_profile")

def downgrade():
    op.add_column('admission_profile', 
        sa.Column('admission_scores', JSONB, nullable=True))
    op.add_column('admission_profile', 
        sa.Column('documents_checklist', JSONB, nullable=True))
    print("✅ Restored JSONB columns to admission_profile")
```

---

### Phase 4: Schema Updates (0.5 day)

#### 2.4.1 Files to Modify

| Layer | File | Changes |
|-------|------|---------|
| **Schema** | `app/schemas/admission.py` | Update response schemas |

#### 2.4.2 Schema Changes

```python
# ❌ REMOVE from AdmissionProfileUpdate:
-    admission_scores: Optional[AdmissionScoreSchema] = None
-    documents_checklist: Optional[List[DocumentItemSchema]] = None

# ✅ ADD new response schemas:
class ProfileDocumentResponse(BaseModel):
    id: int
    document_type_code: str
    document_type_name: str
    status: str  # missing | uploaded | verified | rejected
    file_path: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

# ✅ UPDATE AdmissionProfileResponse:
class AdmissionProfileResponse(BaseModel):
-    admission_scores: Optional[AdmissionScoreSchema] = None
-    documents_checklist: List[DocumentItemSchema] = []
+    subject_scores: List[ProfileSubjectScoreResponse] = []
+    documents: List[ProfileDocumentResponse] = []
```

---

## 3. COMPLIANCE CHECKLISTS

### 3.1 Repository Checklist (per MASTER_ARCHITECTURE Part 1.4)

| Method | Inherits Base | selectinload | Returns None | No Exception |
|--------|:-------------:|:------------:|:------------:|:------------:|
| `create_profile_documents` | ✅ | N/A | N/A | ✅ |
| `get_profile_document_by_type` | ✅ | ✅ | ✅ | ✅ |
| `update_profile_document_status` | ✅ | N/A | N/A | ✅ |
| `get_uploaded_documents` | ✅ | ✅ | ✅ | ✅ |

### 3.2 Service Checklist (per MASTER_ARCHITECTURE Part 1.3)

| Function | No HTTPException | No db.commit() | Uses Repository | Returns callback |
|----------|:----------------:|:--------------:|:---------------:|:----------------:|
| `create_profile` | ✅ | ✅ | ✅ | ✅ |
| `upload_document` | ✅ | ✅ | ✅ | ✅ |
| `submit_and_evaluate` | ✅ | ✅ | ✅ | N/A |
| `enroll_student` | ✅ | ✅ | ✅ | N/A |

### 3.3 Migration Checklist

| Item | Required | Notes |
|------|:--------:|-------|
| `downgrade()` function | ✅ | Must restore columns |
| Idempotent script | ✅ | Safe to run multiple times |
| No data loss | ✅ | (No production data) |

---

## 4. ACCEPTANCE CRITERIA

### Phase 1: Repository Layer
- [ ] `create_profile_documents()` creates ProfileDocument records
- [ ] `get_profile_document_by_type()` returns correct document
- [ ] `update_profile_document_status()` updates status and file_path
- [ ] `get_uploaded_documents()` returns only uploaded docs

### Phase 2: Service Layer
- [ ] `create_profile()` creates ProfileDocument instead of JSONB
- [ ] `upload_document()` updates ProfileDocument instead of JSONB
- [ ] `submit_and_evaluate()` validates from relationships
- [ ] `enroll_student()` reads from `profile.documents`
- [ ] No usages of `admission_scores` or `documents_checklist` in service

### Phase 3: Model & Migration
- [ ] `admission_scores` column removed from model
- [ ] `documents_checklist` column removed from model
- [ ] Migration has `upgrade()` and `downgrade()`
- [ ] Migration runs without error

### Phase 4: Schema
- [ ] `ProfileDocumentResponse` schema added
- [ ] `AdmissionProfileResponse` uses new field names
- [ ] All existing tests pass

### Final Verification
- [ ] No grep results for JSONB field names in service (except comments)
- [ ] API responses match new schema
- [ ] Document upload flow works end-to-end

---

## 5. TIMELINE

```
Day 1:
├── Phase 1: Repository methods (0.5 day)
└── Phase 2: Start service refactor

Day 2:
├── Phase 2: Complete service refactor (1.5 days total)
└── Phase 3: Model + Migration (0.5 day)

Day 3:
├── Phase 4: Schema updates (0.5 day)
└── Testing + Bug fixes (0.5 day)
```

**Total estimate:** 3 days

---

## 6. RISKS & MITIGATIONS

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking existing tests | MEDIUM | HIGH | Run tests after each phase |
| Forgot relationship loading | HIGH | MEDIUM | Verify selectinload in Repository |
| Frontend expects old schema | HIGH | LOW | (Out of scope - coordinate separately) |

---

**END OF PLAN**

> *"Refactoring is not about making code work.*  
> *It's about making code correct by construction."*
