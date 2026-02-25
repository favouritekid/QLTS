# KẾ HOẠCH TRIỂN KHAI: KHẮC PHỤC AUDIT + HỆ THỐNG HOA HỒNG CTV

> **Ngày lập**: 2026-02-24
> **Cập nhật xác minh**: 2026-02-25 — S-1 hạ Critical→Low, F-5 loại (not a bug), thêm Tasks 1.9, 1.10, 4.11, 4.12
> **Phiên bản**: 1.1
> **Tài liệu tham chiếu**:
> - `CTV_MODULE_AUDIT_REPORT.md` — Báo cáo audit (cập nhật 2026-02-25, thêm 8 issues mới)
> - `CTV_ORIGINAL_DESIGN_V1.md` — Thiết kế gốc V1 (Nov 2025)
> - `PHASE_WORKFLOW.md` — Lead FSM (sts00 → sts11)
> - `FINANCE_MODULE_DESIGN.md` — Module tài chính hiện tại
>
> **Quyết định nghiệp vụ đã xác nhận**:
> 1. Scope chính sách: **Global** (không phân theo đơn vị)
> 2. Base tính hoa hồng: **Chỉ học phí** (tuition fee)
> 3. Approval workflow: **1 bước** (Admin duyệt)
> 4. Hoàn hoa hồng: **Không hoàn** (quyết định của sinh viên)
> 5. CTV categories/tiers: **Chưa cần** (deferred)
>
> **Nguyên tắc**: Nền tảng (Foundation) phải đầy đủ → mới triển khai dịch vụ (Services) → dịch vụ phải đầy đủ theo nền tảng và kế hoạch → mới triển khai API/Frontend

---

## MỤC LỤC

- [Phase 1: Security Hardening + Foundation](#phase-1-security-hardening--foundation-3-ngày)
- [Phase 2: Commission Service Layer](#phase-2-commission-service-layer-3-4-ngày)
- [Phase 3: Commission API + Enrollment Trigger](#phase-3-commission-api--enrollment-trigger-3-4-ngày)
- [Phase 4: Frontend + Performance + Cleanup](#phase-4-frontend--performance--cleanup-4-5-ngày)
- [Tổng kết file changes](#tổng-kết-file-changes)
- [Test Matrix](#test-matrix)

---

## PHASE 1: SECURITY HARDENING + FOUNDATION (3 ngày)

### Mục tiêu
- Fix tất cả Critical + High security issues từ audit report
- Tạo database foundation cho commission system (models + migration)
- Đảm bảo nền tảng vững chắc trước khi viết business logic

### Điều kiện tiên quyết
- Docker compose đang chạy (`docker compose up -d`)
- Test deps đã cài (`docker compose exec backend pip install -r requirements-dev.txt`)

---

### Task 1.1: Xóa `status` khỏi `CollaboratorUpdate` schema

> **Audit**: B-2, P-1 (High) — Bypass approve/suspend workflow qua PUT update

**File**: `app/schemas/collaborator.py`

**Hành động**: Xóa field `status` khỏi `CollaboratorUpdate`. Status chỉ thay đổi qua dedicated endpoints: `/approve`, `/suspend`, `/reactivate`.

```python
# TÌM (khoảng dòng 90-95):
class CollaboratorUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    status: Optional[str] = None                # ← XÓA DÒNG NÀY
    managed_by_officer_id: Optional[int] = None
    ...

# SAU KHI SỬA:
class CollaboratorUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    # status: REMOVED — chỉ thay đổi qua /approve, /suspend, /reactivate
    managed_by_officer_id: Optional[int] = None
    ...
```

**Service check** (`app/services/collaborator_service.py`): Kiểm tra `update_collaborator()` method — nó dùng `setattr(collaborator, field, value)` loop từ schema. Khi `status` bị xóa khỏi schema, nó tự động không thể thay đổi status qua update nữa. Không cần sửa service.

**Test**: Viết test xác nhận PUT `/api/collaborators/{id}` với `{"status": "active"}` không thay đổi status (field bị ignore).

---

### Task 1.2: Thêm defensive Officer filter cho `list_claims`

> **Audit**: S-1 *(hạ từ Critical → Low — xác minh 2026-02-25)*
>
> **Xác minh**: OFFICER_TEMPLATE (`policy_templates.py:85-165`) **KHÔNG chứa** route `/api/collaborators/claims`. Route này nằm trong MANAGER_TEMPLATE (L307). Diamond inheritance: `admin > manager > officer` — Manager kế thừa Officer, không ngược lại. Do đó Officer bị Casbin chặn trước khi vào function. **Đây là defensive measure, không phải critical fix.**

**File**: `app/routers/collaborators.py`, function `list_claims` (khoảng dòng 118-142)

**Hành động**: Thêm defensive officer filter để phòng trường hợp Casbin policy thay đổi trong tương lai.

```python
# TÌM trong function list_claims:
# Sau block kiểm tra Manager scope (unit_id filter), thêm:

# Defensive: Officer không nên truy cập claims list
# Hiện tại Casbin đã chặn, nhưng thêm filter để phòng policy changes
if current_user.role == UserRole.OFFICER:
    raise ResourceNotFoundError("Resource not found")
```

**Giải thích**: Officer không có quyền `review_claim` (chỉ Admin/Manager) và hiện tại Casbin đã chặn access. Filter này là **defense-in-depth** — nếu sau này ai thêm claims routes vào OFFICER_TEMPLATE, code vẫn an toàn. Nếu cần cho Officer xem claims từ CTVs mình quản lý, thêm `managed_by_officer_id` filter vào `get_filtered()` của `LeadClaimRepository`.

**Ưu tiên**: Thấp — có thể làm cùng lúc với các task khác trong Phase 1.

**Test**: Viết test xác nhận Officer gọi `GET /api/collaborators/claims` nhận 404 (hoặc 403 từ Casbin).

---

### Task 1.3: Whitelist `sort_by` parameter

> **Audit**: S-3 (High) — `getattr(models.Collaborator, sort_by)` cho phép column enumeration

**File**: `app/repositories/collaborator_repository.py`, method `get_filtered` (khoảng dòng 140)

**Hành động**: Thêm whitelist trước `getattr`.

```python
# THÊM constant ở đầu file (sau imports):
ALLOWED_SORT_COLUMNS = {"created_at", "updated_at", "full_name", "code", "phone", "status"}

# TÌM trong get_filtered():
sort_column = getattr(models.Collaborator, sort_by, models.Collaborator.created_at)

# THAY BẰNG:
if sort_by not in ALLOWED_SORT_COLUMNS:
    sort_by = "created_at"
sort_column = getattr(models.Collaborator, sort_by)
```

**Test**: Viết test xác nhận `sort_by=bank_account` fallback về `created_at` (không lỗi, không tiết lộ column).

---

### Task 1.4: Thêm `reactivate` endpoint

> **Audit**: B-1 (High) — CTV bị suspended không thể kích hoạt lại

**Files cần sửa** (3 files):

#### 1. Service: `app/services/collaborator_service.py`

Thêm method `reactivate_collaborator()` (sau method `suspend_collaborator`):

```python
async def reactivate_collaborator(
    db: AsyncSession,
    collaborator: models.Collaborator,
    reactivated_by: models.User,
) -> Tuple[models.Collaborator, None]:
    """Kích hoạt lại CTV đang bị đình chỉ.

    Chỉ CTV có status 'suspended' mới được kích hoạt lại.
    """
    if collaborator.status != "suspended":
        raise BusinessRuleViolation(
            "Chỉ có thể kích hoạt lại CTV đang bị đình chỉ"
        )

    collaborator.status = "active"
    collaborator.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info(
        "collaborator_reactivated",
        collaborator_id=collaborator.id,
        code=collaborator.code,
        reactivated_by=reactivated_by.id,
    )

    return collaborator, None
```

#### 2. Router: `app/routers/collaborators.py`

Thêm endpoint sau `suspend_collaborator_endpoint` (cuối admin_router):

```python
@admin_router.post(
    "/{collaborator_id}/reactivate",
    response_model=CollaboratorResponse,
    summary="Kích hoạt lại CTV đã bị đình chỉ",
)
async def reactivate_collaborator_endpoint(
    collaborator: models.Collaborator = Depends(get_collaborator_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    reactivated, _ = await collaborator_service.reactivate_collaborator(
        db, collaborator, current_user,
    )
    await db.commit()
    repo = CollaboratorRepository(db)
    reactivated = await repo.get_by_id(reactivated.id)
    return reactivated
```

#### 3. Casbin: `app/casbin_config/policy_templates.py`

Thêm policy cho reactivate action (nếu cần — kiểm tra xem Casbin policy có cover `POST /api/collaborators/{id}/reactivate` chưa. Nếu admin/manager đã có wildcard policy cho `/api/collaborators/*` thì không cần thêm).

**Test**:
- suspended CTV → reactivate → status = "active" (200 OK)
- active CTV → reactivate → 400 "Chỉ có thể kích hoạt lại CTV đang bị đình chỉ"
- pending CTV → reactivate → 400

---

### Task 1.5: Mask financial data trong list response

> **Audit**: S-2 (High) — `bank_account`, `bank_name`, `id_card_number` exposed cho mọi GET request

**File**: `app/schemas/collaborator.py`

**Hành động**: Tạo `CollaboratorListItem` schema cho list view (không chứa sensitive data). Giữ `CollaboratorResponse` cho detail view (admin only).

```python
# THÊM schema mới (trước CollaboratorResponse):
class CollaboratorListItem(BaseModel):
    """Schema cho list view — không chứa thông tin tài chính/cá nhân nhạy cảm."""
    id: int
    code: str
    full_name: str
    phone: str
    email: Optional[str] = None
    status: str
    unit_id: int
    managed_by_officer_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime] = None

    # Nested relationships (shallow)
    unit: Optional[OrganizationUnitShallow] = None
    managed_by_officer: Optional[UserShallow] = None

    model_config = ConfigDict(from_attributes=True)

# CẬP NHẬT CollaboratorsPage:
class CollaboratorsPage(BaseModel):
    total_count: int
    collaborators: list[CollaboratorListItem]  # ← Đổi từ CollaboratorResponse
```

**File**: `app/routers/collaborators.py`

Cập nhật `list_collaborators` endpoint response_model:
```python
# TÌM:
@admin_router.get("/", response_model=CollaboratorsPage)
# Không cần đổi vì CollaboratorsPage đã dùng CollaboratorListItem
```

**Test**: Xác nhận GET `/api/collaborators` response KHÔNG chứa `bank_account`, `bank_name`, `id_card_number`. GET `/api/collaborators/{id}` VẪN chứa (cho admin detail view).

---

### Task 1.6: Fix code generation race condition

> **Audit**: D-1 (High) — `SELECT MAX(code)` có race condition

**File**: `app/repositories/collaborator_repository.py`, method `generate_next_code`

**Hành động**: Chuyển sang dùng PostgreSQL sequence.

#### Step 1: Tạo migration

```bash
docker compose exec backend alembic revision --autogenerate -m "add_collaborator_code_sequence"
```

Sửa migration file vừa tạo:

```python
def upgrade() -> None:
    # Tạo sequence bắt đầu từ giá trị hiện tại + 1
    op.execute("""
        DO $$
        DECLARE
            max_num INTEGER;
        BEGIN
            SELECT COALESCE(
                MAX(CAST(SPLIT_PART(code, '-', 3) AS INTEGER)), 0
            ) INTO max_num
            FROM collaborator
            WHERE code LIKE 'CTV-%';

            EXECUTE format(
                'CREATE SEQUENCE collaborator_code_seq START WITH %s INCREMENT BY 1',
                max_num + 1
            );
        END $$;
    """)

def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS collaborator_code_seq")
```

#### Step 2: Sửa repository

```python
# TÌM method generate_next_code() và THAY TOÀN BỘ:

async def generate_next_code(self) -> str:
    """Generate next CTV code using PostgreSQL sequence (race-condition safe)."""
    year = datetime.now().year
    result = await self.db.execute(text("SELECT nextval('collaborator_code_seq')"))
    seq = result.scalar_one()
    return f"CTV-{year}-{seq:04d}"
```

#### Step 3: Cập nhật service

Tìm nơi gọi `generate_next_code(year)` trong `collaborator_service.py` và sửa thành `generate_next_code()` (bỏ param `year`). Cũng xóa retry loop nếu có (sequence đảm bảo unique).

**Test**:
- Tạo 2 CTV liên tiếp → code tăng tuần tự
- Chạy migration: `docker compose exec backend alembic upgrade head`

---

### Task 1.7: Thêm rate limiting cho CTV endpoints

> **Audit**: B-3 (Medium) — CTV có thể spam submit leads

**File**: `app/routers/collaborators.py`

**Hành động**: Thêm rate limit decorator cho 2 endpoints nhạy cảm.

```python
# THÊM import (đầu file):
from app.core.rate_limits import limiter, RateLimits

# TÌM submit_lead endpoint và THÊM decorator:
@ctv_router.post("/leads/submit", ...)
@limiter.limit("10/minute")  # 10 lead submissions per minute per user
async def submit_lead(request: Request, ...):
    ...

# TÌM check-phone endpoint và THÊM decorator:
@ctv_router.get("/leads/check-phone", ...)
@limiter.limit("30/minute")  # 30 phone checks per minute per user
async def check_phone(request: Request, ...):
    ...
```

**Lưu ý**: Kiểm tra `app/core/rate_limits.py` để xem format rate limit string. Nếu dùng custom tier system, dùng tier phù hợp thay vì hardcode string.

**Cần thêm `Request` parameter**: Nếu endpoint chưa có `request: Request` parameter, thêm vào. slowapi cần `Request` object để extract client info.

**Test**: Gửi > 10 requests/phút → nhận 429 Too Many Requests.

---

### Task 1.8: Commission Database Foundation

> **Mục tiêu**: Tạo models + migration cho commission system. Đây là FOUNDATION — chưa có business logic.

#### Step 1: Tạo model file `app/models/commission.py`

```python
"""Commission models for CTV referral rewards."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class CommissionPolicy(Base):
    """Chính sách hoa hồng — cấu hình tỷ lệ % và điều kiện.

    Business rules:
    - Global scope (không phân theo đơn vị)
    - Chỉ 1 policy active tại 1 thời điểm
    - Base: tuition fee only
    - Chỉ hỗ trợ percentage (Phase 1)
    """
    __tablename__ = "commission_policy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="Tên chính sách")
    description = Column(Text, nullable=True, comment="Mô tả chi tiết")

    # Calculation
    rate_percent = Column(
        Numeric(5, 2), nullable=False, default=0,
        comment="Tỷ lệ hoa hồng (%). VD: 5.00 = 5%",
    )
    min_tuition = Column(
        Numeric(12, 2), nullable=True, default=0,
        comment="Học phí tối thiểu để đủ điều kiện hoa hồng (VND)",
    )

    # Lifecycle
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(
        DateTime(timezone=True), nullable=True,
        comment="NULL = không hết hạn",
    )

    # Audit
    created_by_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id])
    commissions = relationship("Commission", back_populates="policy")

    def __repr__(self):
        return f"<CommissionPolicy id={self.id} name='{self.name}' rate={self.rate_percent}%>"


class Commission(Base):
    """Bản ghi hoa hồng cho mỗi lead được giới thiệu thành công.

    Business rules:
    - 1 commission per lead (unique constraint)
    - Trigger: lead đạt sts11 (ENROLLED) + có referrer_id
    - Status flow: pending → approved → paid (hoặc pending → rejected)
    - Không hoàn hoa hồng (no clawback)
    - Admin 1-step approval
    """
    __tablename__ = "commission"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    collaborator_id = Column(
        Integer, ForeignKey("collaborator.id", ondelete="RESTRICT"),
        nullable=False, index=True,
        comment="CTV nhận hoa hồng",
    )
    lead_id = Column(
        Integer, ForeignKey("lead.id", ondelete="RESTRICT"),
        nullable=False, index=True,
        comment="Lead được giới thiệu",
    )
    admission_profile_id = Column(
        Integer, ForeignKey("admission_profile.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Hồ sơ tuyển sinh liên quan",
    )
    policy_id = Column(
        Integer, ForeignKey("commission_policy.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Chính sách áp dụng tại thời điểm tạo",
    )

    # Calculation snapshot (immutable after creation)
    base_amount = Column(
        Numeric(12, 2), nullable=False,
        comment="Học phí dùng làm base tính hoa hồng (VND)",
    )
    rate_percent = Column(
        Numeric(5, 2), nullable=False,
        comment="Tỷ lệ % tại thời điểm tạo (snapshot từ policy)",
    )
    commission_amount = Column(
        Numeric(12, 2), nullable=False,
        comment="Số tiền hoa hồng = base_amount × rate_percent / 100",
    )

    # Status workflow: pending → approved → paid | pending → rejected
    status = Column(
        String(20), nullable=False, default="pending", index=True,
        comment="pending, approved, rejected, paid",
    )

    # Trigger info
    trigger_event = Column(
        String(50), nullable=False, default="enrollment",
        comment="Sự kiện kích hoạt: enrollment",
    )
    triggered_at = Column(
        DateTime(timezone=True), nullable=False,
        comment="Thời điểm enrollment xảy ra",
    )

    # Approval
    approved_by_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Rejection
    rejected_by_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(String(500), nullable=True)

    # Payment
    paid_by_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    paid_at = Column(DateTime(timezone=True), nullable=True)
    payment_reference = Column(
        String(100), nullable=True,
        comment="Mã chuyển khoản / reference number",
    )
    payment_note = Column(Text, nullable=True)

    # Audit
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("lead_id", name="uq_commission_lead_id"),
    )

    # Relationships
    collaborator = relationship("Collaborator", back_populates="commissions")
    lead = relationship("Lead", back_populates="commission")
    admission_profile = relationship("AdmissionProfile")
    policy = relationship("CommissionPolicy", back_populates="commissions")
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    rejected_by = relationship("User", foreign_keys=[rejected_by_id])
    paid_by = relationship("User", foreign_keys=[paid_by_id])

    def __repr__(self):
        return (
            f"<Commission id={self.id} collaborator={self.collaborator_id} "
            f"amount={self.commission_amount} status={self.status}>"
        )
```

#### Step 2: Đăng ký models trong `app/models/__init__.py`

```python
# THÊM import:
from app.models.commission import Commission, CommissionPolicy

# THÊM vào __all__:
__all__ = [
    ...
    "Commission",
    "CommissionPolicy",
]
```

#### Step 3: Thêm relationships vào models hiện có

**File**: `app/models/collaborator.py` — thêm relationship:
```python
# THÊM vào class Collaborator (sau leads_referred relationship):
commissions = relationship("Commission", back_populates="collaborator")
```

**File**: `app/models/lead.py` — thêm relationship:
```python
# THÊM vào class Lead (khu vực relationships):
commission = relationship(
    "Commission", back_populates="lead", uselist=False,
    comment="1 lead tối đa 1 commission",
)
```

#### Step 4: Tạo migration

```bash
docker compose exec backend alembic revision --autogenerate -m "add_commission_policy_and_commission_tables"
```

**Kiểm tra migration file** vừa tạo:
- Confirm tạo 2 bảng: `commission_policy`, `commission`
- Confirm unique constraint trên `commission.lead_id`
- Confirm indexes trên `collaborator_id`, `lead_id`, `status`, `is_active`
- Confirm ForeignKey constraints đúng

```bash
docker compose exec backend alembic upgrade head
```

#### Step 5: Tạo Pydantic schemas `app/schemas/commission.py`

```python
"""Pydantic schemas for Commission module."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Commission Policy Schemas ───

class CommissionPolicyCreate(BaseModel):
    """Schema tạo chính sách hoa hồng mới."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    rate_percent: Decimal = Field(..., ge=0, le=100, decimal_places=2)
    min_tuition: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    is_active: bool = True
    effective_from: datetime
    effective_to: Optional[datetime] = None


class CommissionPolicyUpdate(BaseModel):
    """Schema cập nhật chính sách hoa hồng."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    rate_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    min_tuition: Optional[Decimal] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None


class CommissionPolicyResponse(BaseModel):
    """Schema response cho chính sách hoa hồng."""
    id: int
    name: str
    description: Optional[str] = None
    rate_percent: Decimal
    min_tuition: Optional[Decimal] = None
    is_active: bool
    effective_from: datetime
    effective_to: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CommissionPoliciesPage(BaseModel):
    """Paginated list of commission policies."""
    total_count: int
    policies: list[CommissionPolicyResponse]


# ─── Commission Schemas ───

class CommissionResponse(BaseModel):
    """Schema response cho bản ghi hoa hồng."""
    id: int
    collaborator_id: int
    lead_id: int
    admission_profile_id: Optional[int] = None
    policy_id: int

    # Calculation
    base_amount: Decimal
    rate_percent: Decimal
    commission_amount: Decimal

    # Status
    status: str
    trigger_event: str
    triggered_at: datetime

    # Approval
    approved_by_id: Optional[int] = None
    approved_at: Optional[datetime] = None

    # Rejection
    rejected_by_id: Optional[int] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    # Payment
    paid_by_id: Optional[int] = None
    paid_at: Optional[datetime] = None
    payment_reference: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CommissionDetailResponse(CommissionResponse):
    """Commission response with nested relationships (for detail view)."""
    collaborator_name: Optional[str] = None
    collaborator_code: Optional[str] = None
    lead_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CommissionsPage(BaseModel):
    """Paginated list of commissions."""
    total_count: int
    commissions: list[CommissionResponse]


class CommissionApproveRequest(BaseModel):
    """Schema cho Admin duyệt hoa hồng."""
    pass  # Không cần payload — action-based endpoint


class CommissionRejectRequest(BaseModel):
    """Schema cho Admin từ chối hoa hồng."""
    reason: str = Field(..., min_length=1, max_length=500)


class CommissionPayRequest(BaseModel):
    """Schema cho Admin ghi nhận thanh toán hoa hồng."""
    payment_reference: Optional[str] = Field(default=None, max_length=100)
    payment_note: Optional[str] = None


# ─── CTV Self-Service Schemas ───

class CommissionForCTV(BaseModel):
    """Commission response cho CTV (giới hạn thông tin)."""
    id: int
    lead_id: int
    commission_amount: Decimal
    status: str
    trigger_event: str
    triggered_at: datetime
    approved_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    payment_reference: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CommissionStatsForCTV(BaseModel):
    """Thống kê hoa hồng cho CTV dashboard."""
    total_commissions: int = 0
    pending_count: int = 0
    approved_count: int = 0
    paid_count: int = 0
    rejected_count: int = 0
    total_pending_amount: Decimal = Decimal("0")
    total_approved_amount: Decimal = Decimal("0")
    total_paid_amount: Decimal = Decimal("0")
```

---

### Task 1.9: Thêm explicit Officer check trong `get_collaborator_for_user`

> **Xác minh 2026-02-25**: NEW-B1 (Medium — phòng ngừa) — IDOR dependency chỉ check Admin & Manager, Officer fall-through vào 404 "by accident". Nếu sau này thêm Officer vào Casbin policy cho `/{id}`, sẽ vô tình mở full access.

**File**: `app/core/deps.py`, function `get_collaborator_for_user` (khoảng dòng 1983-2005)

**Hành động**: Thêm explicit Officer handling.

```python
# TÌM (khoảng dòng 2000-2005):
if current_user.role == UserRole.ADMIN:
    return collab
if current_user.role == UserRole.MANAGER:
    if collab.unit_id == current_user.unit_id:
        return collab
raise ResourceNotFoundError("Collaborator not found")

# THAY BẰNG:
if current_user.role == UserRole.ADMIN:
    return collab
if current_user.role == UserRole.MANAGER:
    if collab.unit_id == current_user.unit_id:
        return collab
if current_user.role == UserRole.OFFICER:
    # Officer chỉ xem CTV mình quản lý (read-only via list endpoint)
    # Không cho phép truy cập detail endpoint — consistent với Casbin policy
    pass  # fall through to 404
raise ResourceNotFoundError("Collaborator not found")
```

**Test**: Officer gọi `GET /api/collaborators/{id}` nhận 404.

---

### Task 1.10: Thêm field whitelist trong `update_collaborator` setattr loop

> **Xác minh 2026-02-25**: NEW-B3 (Medium — phòng ngừa) — Service dùng `setattr` loop không có whitelist. Nếu ai thêm `unit_id` vào schema → phá vỡ scope isolation.

**File**: `app/services/collaborator_service.py`, function `update_collaborator` (khoảng dòng 178-180)

**Hành động**: Thêm explicit field whitelist.

```python
# THÊM constant ở đầu file (sau CLAIMABLE_STATUSES):
UPDATABLE_FIELDS = {
    "full_name", "phone", "email", "managed_by_officer_id",
    "id_card_number", "bank_account", "bank_name", "address", "notes",
}

# TÌM trong update_collaborator():
update_data = data.model_dump(exclude_unset=True)
for field, value in update_data.items():
    setattr(collaborator, field, value)

# THAY BẰNG:
update_data = data.model_dump(exclude_unset=True)
for field, value in update_data.items():
    if field not in UPDATABLE_FIELDS:
        continue  # Skip fields not in whitelist (defense-in-depth)
    setattr(collaborator, field, value)
```

**Test**: Gửi PUT với `{"unit_id": 999}` → `unit_id` không thay đổi.

**Checklist Phase 1**:
- [ ] Task 1.1: Xóa status khỏi CollaboratorUpdate (B-2/P-1)
- [ ] Task 1.2: Thêm defensive Officer filter cho list_claims (S-1 — phòng ngừa, hạ từ Critical → Low)
- [ ] Task 1.3: Whitelist sort_by (S-3)
- [ ] Task 1.4: Thêm reactivate endpoint (B-1)
- [ ] Task 1.5: Mask financial data — CollaboratorListItem (S-2)
- [ ] Task 1.6: Fix code generation — PG sequence + migration (D-1)
- [ ] Task 1.7: Rate limiting cho CTV endpoints (B-3)
- [ ] Task 1.8: Commission models + schemas + migration
- [ ] Task 1.9: Thêm explicit Officer check trong `get_collaborator_for_user` (NEW-B1 — phòng ngừa)
- [ ] Task 1.10: Thêm field whitelist trong `update_collaborator` setattr loop (NEW-B3 — phòng ngừa)
- [ ] Chạy toàn bộ tests hiện tại để đảm bảo không regression
- [ ] Review migration file trước khi chạy

---

## PHASE 2: COMMISSION SERVICE LAYER (3-4 ngày)

### Mục tiêu
- Viết business logic cho commission: calculate, create, approve, reject, pay
- Tạo repository layer cho data access
- Đảm bảo service isolation (no FastAPI imports, domain exceptions only)

### Điều kiện tiên quyết
- Phase 1 hoàn thành (models, schemas, migration đã chạy)
- Tất cả tests Phase 1 pass

---

### Task 2.1: Tạo Commission Repository

**File mới**: `app/repositories/commission_repository.py`

```python
"""Repository for Commission data access."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models


class CommissionPolicyRepository:
    """Data access for CommissionPolicy."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, policy_id: int) -> Optional[models.CommissionPolicy]:
        query = select(models.CommissionPolicy).where(
            models.CommissionPolicy.id == policy_id,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_active_policy(self, at_time: Optional[datetime] = None) -> Optional[models.CommissionPolicy]:
        """Lấy chính sách active tại thời điểm chỉ định.

        Returns chính sách active đầu tiên theo effective_from DESC.
        """
        now = at_time or datetime.now(timezone.utc)
        query = (
            select(models.CommissionPolicy)
            .where(
                models.CommissionPolicy.is_active.is_(True),
                models.CommissionPolicy.effective_from <= now,
            )
            .where(
                (models.CommissionPolicy.effective_to.is_(None))
                | (models.CommissionPolicy.effective_to >= now)
            )
            .order_by(models.CommissionPolicy.effective_from.desc())
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_filtered(
        self,
        *,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[models.CommissionPolicy], int]:
        base = select(models.CommissionPolicy)
        count_base = select(func.count(models.CommissionPolicy.id))

        if is_active is not None:
            base = base.where(models.CommissionPolicy.is_active == is_active)
            count_base = count_base.where(models.CommissionPolicy.is_active == is_active)

        count_result = await self.db.execute(count_base)
        total = count_result.scalar_one()

        query = base.order_by(models.CommissionPolicy.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        policies = list(result.scalars().all())

        return policies, total


class CommissionRepository:
    """Data access for Commission records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, commission_id: int) -> Optional[models.Commission]:
        query = (
            select(models.Commission)
            .options(
                selectinload(models.Commission.collaborator),
                selectinload(models.Commission.lead),
                selectinload(models.Commission.policy),
                selectinload(models.Commission.approved_by),
                selectinload(models.Commission.paid_by),
            )
            .where(models.Commission.id == commission_id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_lead_id(self, lead_id: int) -> Optional[models.Commission]:
        """Check if commission already exists for this lead."""
        query = select(models.Commission).where(
            models.Commission.lead_id == lead_id,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_filtered(
        self,
        *,
        collaborator_id: Optional[int] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[models.Commission], int]:
        base = select(models.Commission)
        count_base = select(func.count(models.Commission.id))

        if collaborator_id is not None:
            base = base.where(models.Commission.collaborator_id == collaborator_id)
            count_base = count_base.where(models.Commission.collaborator_id == collaborator_id)
        if status is not None:
            base = base.where(models.Commission.status == status)
            count_base = count_base.where(models.Commission.status == status)

        count_result = await self.db.execute(count_base)
        total = count_result.scalar_one()

        query = (
            base
            .options(
                selectinload(models.Commission.collaborator),
                selectinload(models.Commission.lead),
            )
            .order_by(models.Commission.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        commissions = list(result.scalars().all())

        return commissions, total

    async def get_stats_by_collaborator(self, collaborator_id: int) -> dict:
        """Thống kê hoa hồng theo CTV — single GROUP BY query."""
        query = (
            select(
                models.Commission.status,
                func.count(models.Commission.id).label("count"),
                func.coalesce(func.sum(models.Commission.commission_amount), 0).label("total_amount"),
            )
            .where(models.Commission.collaborator_id == collaborator_id)
            .group_by(models.Commission.status)
        )
        result = await self.db.execute(query)
        rows = result.all()

        stats = {}
        for row in rows:
            stats[row.status] = {"count": row.count, "amount": row.total_amount}

        return {
            "total_commissions": sum(s["count"] for s in stats.values()),
            "pending_count": stats.get("pending", {}).get("count", 0),
            "approved_count": stats.get("approved", {}).get("count", 0),
            "paid_count": stats.get("paid", {}).get("count", 0),
            "rejected_count": stats.get("rejected", {}).get("count", 0),
            "total_pending_amount": stats.get("pending", {}).get("amount", Decimal("0")),
            "total_approved_amount": stats.get("approved", {}).get("amount", Decimal("0")),
            "total_paid_amount": stats.get("paid", {}).get("amount", Decimal("0")),
        }
```

---

### Task 2.2: Tạo Commission Service

**File mới**: `app/services/commission_service.py`

```python
"""Commission business logic — pure Python, no FastAPI imports."""

import structlog
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.commission_repository import (
    CommissionPolicyRepository,
    CommissionRepository,
)
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)

# ─── Commission Policy CRUD ───

async def create_commission_policy(
    db: AsyncSession,
    data,  # CommissionPolicyCreate
    created_by: models.User,
) -> Tuple[models.CommissionPolicy, None]:
    """Tạo chính sách hoa hồng mới."""
    policy = models.CommissionPolicy(
        name=data.name,
        description=data.description,
        rate_percent=data.rate_percent,
        min_tuition=data.min_tuition,
        is_active=data.is_active,
        effective_from=data.effective_from,
        effective_to=data.effective_to,
        created_by_id=created_by.id,
    )
    db.add(policy)
    await db.flush()

    log.info(
        "commission_policy_created",
        policy_id=policy.id,
        name=policy.name,
        rate=str(policy.rate_percent),
        created_by=created_by.id,
    )

    return policy, None


async def update_commission_policy(
    db: AsyncSession,
    policy: models.CommissionPolicy,
    data,  # CommissionPolicyUpdate
) -> Tuple[models.CommissionPolicy, None]:
    """Cập nhật chính sách hoa hồng."""
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(policy, field, value)

    policy.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info("commission_policy_updated", policy_id=policy.id)

    return policy, None


# ─── Commission Calculation ───

async def calculate_commission_for_lead(
    db: AsyncSession,
    lead: models.Lead,
    admission_profile_id: Optional[int],
    tuition_amount: Decimal,
    triggered_at: datetime,
) -> Tuple[Optional[models.Commission], None]:
    """Tính và tạo bản ghi hoa hồng cho lead đã enrolled.

    Preconditions (caller phải đảm bảo):
    - lead.referrer_id IS NOT NULL
    - lead đã đạt sts11 (ENROLLED)

    Returns:
    - (Commission, None) nếu tạo thành công
    - (None, None) nếu không đủ điều kiện

    Raises:
    - DuplicateResourceError nếu commission đã tồn tại cho lead này
    """
    commission_repo = CommissionRepository(db)
    policy_repo = CommissionPolicyRepository(db)

    # 1. Check duplicate
    existing = await commission_repo.get_by_lead_id(lead.id)
    if existing:
        raise DuplicateResourceError(
            f"Commission đã tồn tại cho lead {lead.id} (commission_id={existing.id})"
        )

    # 2. Get active policy
    policy = await policy_repo.get_active_policy(at_time=triggered_at)
    if not policy:
        log.warning(
            "no_active_commission_policy",
            lead_id=lead.id,
            referrer_id=lead.referrer_id,
        )
        return None, None

    # 3. Check minimum tuition
    if policy.min_tuition and tuition_amount < policy.min_tuition:
        log.info(
            "commission_below_min_tuition",
            lead_id=lead.id,
            tuition=str(tuition_amount),
            min_required=str(policy.min_tuition),
        )
        return None, None

    # 4. Calculate commission amount
    commission_amount = (tuition_amount * policy.rate_percent / Decimal("100")).quantize(
        Decimal("0.01")
    )

    # 5. Create commission record
    commission = models.Commission(
        collaborator_id=lead.referrer_id,
        lead_id=lead.id,
        admission_profile_id=admission_profile_id,
        policy_id=policy.id,
        base_amount=tuition_amount,
        rate_percent=policy.rate_percent,
        commission_amount=commission_amount,
        status="pending",
        trigger_event="enrollment",
        triggered_at=triggered_at,
    )
    db.add(commission)
    await db.flush()

    log.info(
        "commission_created",
        commission_id=commission.id,
        collaborator_id=lead.referrer_id,
        lead_id=lead.id,
        base_amount=str(tuition_amount),
        rate=str(policy.rate_percent),
        commission_amount=str(commission_amount),
        policy_id=policy.id,
    )

    return commission, None


# ─── Commission Workflow ───

async def approve_commission(
    db: AsyncSession,
    commission: models.Commission,
    approved_by: models.User,
) -> Tuple[models.Commission, None]:
    """Admin duyệt hoa hồng: pending → approved."""
    if commission.status != "pending":
        raise BusinessRuleViolation(
            f"Chỉ có thể duyệt hoa hồng ở trạng thái 'pending'. "
            f"Trạng thái hiện tại: '{commission.status}'"
        )

    commission.status = "approved"
    commission.approved_by_id = approved_by.id
    commission.approved_at = datetime.now(timezone.utc)
    commission.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info(
        "commission_approved",
        commission_id=commission.id,
        approved_by=approved_by.id,
        amount=str(commission.commission_amount),
    )

    return commission, None


async def reject_commission(
    db: AsyncSession,
    commission: models.Commission,
    rejected_by: models.User,
    reason: str,
) -> Tuple[models.Commission, None]:
    """Admin từ chối hoa hồng: pending → rejected."""
    if commission.status != "pending":
        raise BusinessRuleViolation(
            f"Chỉ có thể từ chối hoa hồng ở trạng thái 'pending'. "
            f"Trạng thái hiện tại: '{commission.status}'"
        )

    commission.status = "rejected"
    commission.rejected_by_id = rejected_by.id
    commission.rejected_at = datetime.now(timezone.utc)
    commission.rejection_reason = reason
    commission.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info(
        "commission_rejected",
        commission_id=commission.id,
        rejected_by=rejected_by.id,
        reason=reason,
    )

    return commission, None


async def pay_commission(
    db: AsyncSession,
    commission: models.Commission,
    paid_by: models.User,
    payment_reference: Optional[str] = None,
    payment_note: Optional[str] = None,
) -> Tuple[models.Commission, None]:
    """Admin ghi nhận thanh toán: approved → paid."""
    if commission.status != "approved":
        raise BusinessRuleViolation(
            f"Chỉ có thể thanh toán hoa hồng đã được duyệt. "
            f"Trạng thái hiện tại: '{commission.status}'"
        )

    commission.status = "paid"
    commission.paid_by_id = paid_by.id
    commission.paid_at = datetime.now(timezone.utc)
    commission.payment_reference = payment_reference
    commission.payment_note = payment_note
    commission.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info(
        "commission_paid",
        commission_id=commission.id,
        paid_by=paid_by.id,
        amount=str(commission.commission_amount),
        reference=payment_reference,
    )

    return commission, None


# ─── Commission Stats ───

async def get_commission_stats_for_ctv(
    db: AsyncSession,
    collaborator_id: int,
) -> dict:
    """Lấy thống kê hoa hồng cho CTV dashboard."""
    repo = CommissionRepository(db)
    return await repo.get_stats_by_collaborator(collaborator_id)
```

---

### Task 2.3: Tạo Celery task cho commission trigger

**File mới**: `app/tasks/commission_tasks.py`

```python
"""Celery tasks for commission calculation.

Trigger: Khi lead đạt sts11 (ENROLLED) và có referrer_id.
"""

import logging
from decimal import Decimal

from app.core.celery_app import celery_app
from app.tasks.utils import task_db_session, run_async_task, validate_result

task_log = logging.getLogger("commission_tasks")


@celery_app.task(
    name="calculate_commission_on_enrollment",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def calculate_commission_on_enrollment(
    self,
    lead_id: int,
    admission_profile_id: int,
    tuition_amount: str,  # Decimal as string for serialization
    triggered_at: str,  # ISO format datetime
):
    """Calculate and create commission record when lead is enrolled.

    Called as post-commit callback from enroll_student() service.
    Idempotent: skips if commission already exists for this lead.
    """
    task_log.info(
        f"Commission calculation started: lead_id={lead_id}, "
        f"profile_id={admission_profile_id}, tuition={tuition_amount}"
    )

    async def _run():
        from datetime import datetime
        from app import models
        from app.services import commission_service
        from app.utils.exceptions import DuplicateResourceError

        async with task_db_session() as session:
            # Load lead with referrer
            lead = await session.get(models.Lead, lead_id)
            if not lead:
                task_log.warning(f"Lead {lead_id} not found, skipping")
                return {"status": "skipped", "reason": "lead_not_found"}

            if not lead.referrer_id:
                task_log.info(f"Lead {lead_id} has no referrer, skipping")
                return {"status": "skipped", "reason": "no_referrer"}

            try:
                commission, _ = await commission_service.calculate_commission_for_lead(
                    db=session,
                    lead=lead,
                    admission_profile_id=admission_profile_id,
                    tuition_amount=Decimal(tuition_amount),
                    triggered_at=datetime.fromisoformat(triggered_at),
                )
                await session.commit()

                if commission:
                    task_log.info(
                        f"Commission created: id={commission.id}, "
                        f"amount={commission.commission_amount}, "
                        f"collaborator={commission.collaborator_id}"
                    )
                    return {
                        "status": "created",
                        "commission_id": commission.id,
                        "amount": str(commission.commission_amount),
                    }
                else:
                    task_log.info(f"No eligible policy for lead {lead_id}")
                    return {"status": "skipped", "reason": "no_eligible_policy"}

            except DuplicateResourceError:
                task_log.info(f"Commission already exists for lead {lead_id}")
                return {"status": "skipped", "reason": "already_exists"}

    result = run_async_task(_run())
    return validate_result(result, "calculate_commission_on_enrollment")
```

---

### Task 2.4: Optimize stats query (Audit E-1)

> **Audit**: E-1 (High) — 4 separate COUNT queries thay vì single GROUP BY

**File**: `app/repositories/lead_repository.py`

**Hành động**: Thêm method `count_leads_by_validity_grouped()` và cập nhật service dùng nó.

```python
# THÊM method mới vào LeadRepository:

async def count_leads_by_validity_grouped(self, referrer_id: int) -> dict:
    """Single GROUP BY query thay vì 4 separate COUNT."""
    query = (
        select(
            models.Lead.validity_status,
            func.count(models.Lead.id).label("count"),
        )
        .where(
            models.Lead.referrer_id == referrer_id,
            models.Lead.deleted_at.is_(None),
        )
        .group_by(models.Lead.validity_status)
    )
    result = await self.db.execute(query)
    rows = result.all()

    counts = {row.validity_status: row.count for row in rows}
    total = sum(counts.values())

    return {
        "total_leads": total,
        "valid_leads": counts.get("valid", 0),
        "qualified_leads": counts.get("qualified", 0),
        "converted_leads": counts.get("converted", 0),
    }
```

**File**: `app/services/collaborator_service.py`, method `get_collaborator_stats()`

Cập nhật để dùng method mới thay vì 4 separate queries:

```python
# TÌM get_collaborator_stats() và THAY logic đếm leads bằng:
lead_repo = LeadRepository(db)
lead_counts = await lead_repo.count_leads_by_validity_grouped(collaborator_id)
# Dùng lead_counts["total_leads"], lead_counts["valid_leads"], etc.
```

**Test**: So sánh kết quả giữa phương thức cũ và mới — phải trả về cùng giá trị.

**Checklist Phase 2**:
- [ ] Task 2.1: CommissionRepository + CommissionPolicyRepository
- [ ] Task 2.2: commission_service.py (calculate, approve, reject, pay)
- [ ] Task 2.3: Celery task calculate_commission_on_enrollment
- [ ] Task 2.4: Optimize stats query (GROUP BY) — cũng fix NEW-B4 (mixing validity_status vs lead.status)
- [ ] Unit tests cho commission_service (calculate, approve, reject, pay)
- [ ] Unit tests cho commission_repository (CRUD, stats)
- [ ] Tất cả tests pass (bao gồm regression tests)

---

## PHASE 3: COMMISSION API + ENROLLMENT TRIGGER (3-4 ngày)

### Mục tiêu
- Expose commission endpoints qua router
- Tạo IDOR dependencies cho commission access
- Kết nối enrollment trigger (enroll_student → commission calculation)
- Cấu hình Casbin policies

### Điều kiện tiên quyết
- Phase 2 hoàn thành (service + repository tests pass)

---

### Task 3.1: Tạo IDOR dependencies cho Commission

**File**: `app/core/deps.py`

Thêm dependencies cho commission access control:

```python
# ─── Commission Dependencies ───

async def get_commission_for_admin(
    commission_id: int = Path(...),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
) -> models.Commission:
    """IDOR protection cho commission — chỉ Admin.

    Admin: truy cập tất cả commissions.
    Others: 404.
    """
    from app.repositories.commission_repository import CommissionRepository

    repo = CommissionRepository(db)
    commission = await repo.get_by_id(commission_id)
    if not commission:
        raise ResourceNotFoundError("Commission not found")
    return commission


async def get_commission_policy_for_admin(
    policy_id: int = Path(...),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
) -> models.CommissionPolicy:
    """IDOR protection cho commission policy — chỉ Admin."""
    from app.repositories.commission_repository import CommissionPolicyRepository

    repo = CommissionPolicyRepository(db)
    policy = await repo.get_by_id(policy_id)
    if not policy:
        raise ResourceNotFoundError("Commission policy not found")
    return policy
```

---

### Task 3.2: Tạo Commission Router

**File mới**: `app/routers/commissions.py`

```python
"""Commission API endpoints.

admin_commission_router: Admin quản lý commissions + policies
ctv_commission_router: CTV xem commission của mình
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core import database
from app.core.deps import (
    get_commission_for_admin,
    get_commission_policy_for_admin,
    get_own_collaborator,
    require_admin,
)
from app.repositories.commission_repository import (
    CommissionPolicyRepository,
    CommissionRepository,
)
from app.schemas.commission import (
    CommissionApproveRequest,
    CommissionDetailResponse,
    CommissionForCTV,
    CommissionPayRequest,
    CommissionPoliciesPage,
    CommissionPolicyCreate,
    CommissionPolicyResponse,
    CommissionPolicyUpdate,
    CommissionRejectRequest,
    CommissionResponse,
    CommissionsPage,
    CommissionStatsForCTV,
)
from app.services import commission_service


# ─── Admin Commission Policy Router ───

admin_policy_router = APIRouter(
    prefix="/admin/commission-policies",
    tags=["Commission Policies (Admin)"],
)


@admin_policy_router.get("/", response_model=CommissionPoliciesPage)
async def list_policies(
    is_active: bool = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    repo = CommissionPolicyRepository(db)
    policies, total = await repo.get_filtered(
        is_active=is_active, skip=skip, limit=limit,
    )
    return CommissionPoliciesPage(total_count=total, policies=policies)


@admin_policy_router.post("/", response_model=CommissionPolicyResponse, status_code=201)
async def create_policy(
    data: CommissionPolicyCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    policy, _ = await commission_service.create_commission_policy(
        db, data, current_user,
    )
    await db.commit()
    return policy


@admin_policy_router.get("/{policy_id}", response_model=CommissionPolicyResponse)
async def get_policy(
    policy: models.CommissionPolicy = Depends(get_commission_policy_for_admin),
):
    return policy


@admin_policy_router.put("/{policy_id}", response_model=CommissionPolicyResponse)
async def update_policy(
    data: CommissionPolicyUpdate,
    policy: models.CommissionPolicy = Depends(get_commission_policy_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    updated, _ = await commission_service.update_commission_policy(db, policy, data)
    await db.commit()
    return updated


# ─── Admin Commission Router ───

admin_commission_router = APIRouter(
    prefix="/admin/commissions",
    tags=["Commissions (Admin)"],
)


@admin_commission_router.get("/", response_model=CommissionsPage)
async def list_commissions(
    collaborator_id: int = Query(default=None),
    status: str = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    repo = CommissionRepository(db)
    commissions, total = await repo.get_filtered(
        collaborator_id=collaborator_id, status=status,
        skip=skip, limit=limit,
    )
    return CommissionsPage(total_count=total, commissions=commissions)


@admin_commission_router.get("/{commission_id}", response_model=CommissionDetailResponse)
async def get_commission_detail(
    commission: models.Commission = Depends(get_commission_for_admin),
):
    return CommissionDetailResponse(
        **{c.name: getattr(commission, c.name) for c in commission.__table__.columns},
        collaborator_name=commission.collaborator.full_name if commission.collaborator else None,
        collaborator_code=commission.collaborator.code if commission.collaborator else None,
        lead_name=commission.lead.full_name if commission.lead else None,
    )


@admin_commission_router.post("/{commission_id}/approve", response_model=CommissionResponse)
async def approve_commission_endpoint(
    commission: models.Commission = Depends(get_commission_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    approved, _ = await commission_service.approve_commission(
        db, commission, current_user,
    )
    await db.commit()
    return approved


@admin_commission_router.post("/{commission_id}/reject", response_model=CommissionResponse)
async def reject_commission_endpoint(
    data: CommissionRejectRequest,
    commission: models.Commission = Depends(get_commission_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    rejected, _ = await commission_service.reject_commission(
        db, commission, current_user, data.reason,
    )
    await db.commit()
    return rejected


@admin_commission_router.post("/{commission_id}/pay", response_model=CommissionResponse)
async def pay_commission_endpoint(
    data: CommissionPayRequest,
    commission: models.Commission = Depends(get_commission_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    paid, _ = await commission_service.pay_commission(
        db, commission, current_user, data.payment_reference, data.payment_note,
    )
    await db.commit()
    return paid


# ─── CTV Self-Service Commission Router ───

ctv_commission_router = APIRouter(
    prefix="/ctv/commissions",
    tags=["Commissions (CTV)"],
)


@ctv_commission_router.get("/", response_model=list[CommissionForCTV])
async def list_own_commissions(
    status: str = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    collaborator: models.Collaborator = Depends(get_own_collaborator),
    db: AsyncSession = Depends(database.get_db),
):
    repo = CommissionRepository(db)
    commissions, _ = await repo.get_filtered(
        collaborator_id=collaborator.id, status=status,
        skip=skip, limit=limit,
    )
    return commissions


@ctv_commission_router.get("/stats", response_model=CommissionStatsForCTV)
async def get_own_commission_stats(
    collaborator: models.Collaborator = Depends(get_own_collaborator),
    db: AsyncSession = Depends(database.get_db),
):
    stats = await commission_service.get_commission_stats_for_ctv(
        db, collaborator.id,
    )
    return CommissionStatsForCTV(**stats)
```

---

### Task 3.3: Đăng ký Commission Router trong `main.py`

**File**: `app/main.py`

```python
# THÊM import:
from app.routers import commissions

# THÊM sau dòng đăng ký collaborators router (~line 707):
fastapi_app.include_router(commissions.admin_policy_router, prefix="/api")
fastapi_app.include_router(commissions.admin_commission_router, prefix="/api")
fastapi_app.include_router(commissions.ctv_commission_router, prefix="/api")
```

---

### Task 3.4: Cấu hình Casbin policies

**File**: `app/casbin_config/policy_templates.py`

Thêm policy template cho commission endpoints:

```python
# THÊM vào ADMIN_TEMPLATE hoặc tạo COMMISSION_TEMPLATE mới:
COMMISSION_ADMIN_POLICIES = [
    # Commission Policies
    ("p", "role:admin", "/api/admin/commission-policies", "GET"),
    ("p", "role:admin", "/api/admin/commission-policies", "POST"),
    ("p", "role:admin", "/api/admin/commission-policies/*", "GET"),
    ("p", "role:admin", "/api/admin/commission-policies/*", "PUT"),
    # Commissions
    ("p", "role:admin", "/api/admin/commissions", "GET"),
    ("p", "role:admin", "/api/admin/commissions/*", "GET"),
    ("p", "role:admin", "/api/admin/commissions/*/approve", "POST"),
    ("p", "role:admin", "/api/admin/commissions/*/reject", "POST"),
    ("p", "role:admin", "/api/admin/commissions/*/pay", "POST"),
]

# CTV commission endpoints (thêm vào COLLABORATOR_TEMPLATE):
COMMISSION_CTV_POLICIES = [
    ("p", "role:collaborator", "/api/ctv/commissions", "GET"),
    ("p", "role:collaborator", "/api/ctv/commissions/stats", "GET"),
]
```

**Lưu ý**: Kiểm tra xem commission endpoints cần đi qua Casbin middleware không. Nếu admin endpoints dùng `require_admin` dependency (không qua Casbin), thì chỉ cần thêm Casbin policies cho CTV endpoints. Đọc kỹ cách các router khác xử lý để nhất quán.

---

### Task 3.5: Kết nối Enrollment Trigger

> **Mục tiêu**: Khi `enroll_student()` hoàn thành → trigger commission calculation cho leads có referrer

**File**: `app/services/admission_service.py`, function `enroll_student()`

**Hành động**: Thêm post-commit callback để trigger Celery task.

```python
# TÌM cuối function enroll_student(), trước return statement.
# Thêm logic:

# Commission trigger: nếu lead có CTV referrer, tính hoa hồng
post_commit_callback = None
if profile.lead and profile.lead.referrer_id:
    # Lấy tuition amount từ Fee
    from app.models.finance import Fee
    tuition_fee_query = (
        select(Fee)
        .where(
            Fee.admission_profile_id == profile.id,
            Fee.fee_type == "tuition",
        )
    )
    tuition_fee_result = await db.execute(tuition_fee_query)
    tuition_fee = tuition_fee_result.scalar_one_or_none()

    if tuition_fee and tuition_fee.final_amount:
        tuition_amount = tuition_fee.final_amount
        lead_id = profile.lead_id
        profile_id = profile.id
        now_iso = datetime.now(timezone.utc).isoformat()

        def _trigger_commission():
            from app.tasks.commission_tasks import calculate_commission_on_enrollment
            calculate_commission_on_enrollment.delay(
                lead_id=lead_id,
                admission_profile_id=profile_id,
                tuition_amount=str(tuition_amount),
                triggered_at=now_iso,
            )

        # Wrap with existing callback if any
        original_callback = post_commit_callback
        async def combined_callback():
            if original_callback:
                await original_callback()
            _trigger_commission()
        post_commit_callback = combined_callback

# THAY return statement để bao gồm callback:
return result, post_commit_callback
```

**QUAN TRỌNG**: Đọc kỹ `enroll_student()` hiện tại trước khi sửa. Nếu nó đã return `(result, callback)`, thêm commission trigger vào callback chain. Nếu nó return trực tiếp result, cần refactor return.

**Xem xét fallback**: Nếu Fee/tuition chưa tồn tại tại thời điểm enrollment (edge case), log warning và skip commission. Không raise error — enrollment phải hoàn thành bất kể commission logic.

**Test**:
- Enroll lead có referrer → commission task được gọi
- Enroll lead không có referrer → commission task KHÔNG được gọi
- Enroll lead có referrer nhưng không có tuition fee → skip, không lỗi

---

### Task 3.6: Thêm commission vào CTV Stats endpoint

**File**: `app/services/collaborator_service.py`, method `get_collaborator_stats()`

**Hành động**: Bổ sung commission stats vào response.

```python
# TÌM get_collaborator_stats() và THÊM sau phần đếm leads:
from app.services import commission_service

commission_stats = await commission_service.get_commission_stats_for_ctv(db, collaborator_id)
```

**File**: `app/schemas/collaborator.py`, class `CollaboratorStats`

```python
# THÊM fields:
class CollaboratorStats(BaseModel):
    # Lead counts (existing)
    total_leads: int = 0
    valid_leads: int = 0
    qualified_leads: int = 0
    converted_leads: int = 0
    pending_claims: int = 0

    # Commission stats (NEW)
    total_commissions: int = 0
    pending_commission_amount: Decimal = Decimal("0")
    total_paid_amount: Decimal = Decimal("0")
```

**Checklist Phase 3**:
- [ ] Task 3.1: IDOR dependencies cho commission
- [ ] Task 3.2: Commission router (admin + CTV)
- [ ] Task 3.3: Đăng ký router trong main.py
- [ ] Task 3.4: Casbin policies
- [ ] Task 3.5: Enrollment trigger (enroll_student → Celery task)
- [ ] Task 3.6: Commission stats trong CTV dashboard
- [ ] API integration tests (CRUD policies, approve/reject/pay commission)
- [ ] IDOR tests (CTV chỉ xem commission của mình, Admin xem tất cả)
- [ ] Enrollment trigger tests (with/without referrer, with/without tuition)
- [ ] Tất cả tests pass

---

## PHASE 4: FRONTEND + PERFORMANCE + CLEANUP (4-5 ngày)

### Mục tiêu
- Frontend cho CTV commission view
- Frontend cho Admin commission management
- Fix các audit issues Medium/Low còn lại
- Polish UX

### Điều kiện tiên quyết
- Phase 3 hoàn thành (tất cả API endpoints hoạt động + tests pass)

---

### Task 4.1: Frontend Types + API Client cho Commission

**File mới**: `frontend/src/types/commission.types.ts`

```typescript
export interface CommissionPolicy {
  id: number;
  name: string;
  description?: string;
  rate_percent: number;
  min_tuition?: number;
  is_active: boolean;
  effective_from: string;
  effective_to?: string;
  created_at: string;
  updated_at: string;
}

export interface Commission {
  id: number;
  collaborator_id: number;
  lead_id: number;
  admission_profile_id?: number;
  policy_id: number;
  base_amount: number;
  rate_percent: number;
  commission_amount: number;
  status: "pending" | "approved" | "rejected" | "paid";
  trigger_event: string;
  triggered_at: string;
  approved_at?: string;
  rejected_at?: string;
  rejection_reason?: string;
  paid_at?: string;
  payment_reference?: string;
  created_at: string;
  updated_at: string;
}

export interface CommissionForCTV {
  id: number;
  lead_id: number;
  commission_amount: number;
  status: "pending" | "approved" | "rejected" | "paid";
  trigger_event: string;
  triggered_at: string;
  approved_at?: string;
  paid_at?: string;
  payment_reference?: string;
  created_at: string;
}

export interface CommissionStatsForCTV {
  total_commissions: number;
  pending_count: number;
  approved_count: number;
  paid_count: number;
  rejected_count: number;
  total_pending_amount: number;
  total_approved_amount: number;
  total_paid_amount: number;
}
```

**File mới**: `frontend/src/lib/api/commissions.ts`

```typescript
import { api } from "./client";

// Admin: Commission Policies
export const commissionPoliciesApi = {
  list: (params?: { is_active?: boolean; skip?: number; limit?: number }) =>
    api.get("/admin/commission-policies", { params }),
  create: (data: { name: string; rate_percent: number; /* ... */ }) =>
    api.post("/admin/commission-policies", data),
  getById: (id: number) =>
    api.get(`/admin/commission-policies/${id}`),
  update: (id: number, data: Record<string, unknown>) =>
    api.put(`/admin/commission-policies/${id}`, data),
};

// Admin: Commissions
export const commissionsAdminApi = {
  list: (params?: { collaborator_id?: number; status?: string; skip?: number; limit?: number }) =>
    api.get("/admin/commissions", { params }),
  getById: (id: number) =>
    api.get(`/admin/commissions/${id}`),
  approve: (id: number) =>
    api.post(`/admin/commissions/${id}/approve`),
  reject: (id: number, data: { reason: string }) =>
    api.post(`/admin/commissions/${id}/reject`, data),
  pay: (id: number, data: { payment_reference?: string; payment_note?: string }) =>
    api.post(`/admin/commissions/${id}/pay`, data),
};

// CTV: Own Commissions
export const commissionsCTVApi = {
  list: (params?: { status?: string; skip?: number; limit?: number }) =>
    api.get("/ctv/commissions", { params }),
  stats: () =>
    api.get("/ctv/commissions/stats"),
};
```

**File mới**: `frontend/src/hooks/useCommissions.ts`

Tạo React Query hooks cho:
- `useCommissionPolicies()` — list policies
- `useCommissions()` — list commissions (admin)
- `useCTVCommissions()` — list own commissions
- `useCTVCommissionStats()` — CTV stats
- `useApproveCommission()` — mutation
- `useRejectCommission()` — mutation
- `usePayCommission()` — mutation

---

### Task 4.2: CTV Commission Tab trong Dashboard

**File**: `frontend/src/app/(dashboard)/ctv/_components/CTVDashboardClient.tsx`

**Hành động**: Thêm tab "Hoa hồng" vào CTV dashboard.

Nội dung tab:
1. **Commission Stats Cards** (top):
   - Tổng hoa hồng: `total_paid_amount` (VND)
   - Đang chờ duyệt: `pending_count` (`total_pending_amount` VND)
   - Đã duyệt: `approved_count` (`total_approved_amount` VND)
   - Đã thanh toán: `paid_count` (`total_paid_amount` VND)

2. **Commission History Table**:
   - Columns: Lead ID | Số tiền | Trạng thái | Ngày tạo | Ngày thanh toán
   - Status badges: pending (yellow), approved (blue), paid (green), rejected (red)
   - Pagination

---

### Task 4.3: Admin Commission Management Page

**File mới**: `frontend/src/app/(dashboard)/admin/commissions/page.tsx` (server component)
**File mới**: `frontend/src/app/(dashboard)/admin/commissions/_components/CommissionsClient.tsx`

Nội dung:
1. **Summary Cards**: Tổng pending, tổng approved, tổng paid (amount)
2. **Commission Table** (TanStack Table):
   - Columns: CTV Code | CTV Name | Lead Name | Base Amount | Rate | Commission | Status | Actions
   - Filters: status dropdown, CTV search
   - Pagination
3. **Action Buttons**:
   - pending: [Approve] [Reject]
   - approved: [Pay]
   - paid: (read-only, show payment info)
4. **Approve Dialog**: AlertDialog xác nhận
5. **Reject Dialog**: AlertDialog + textarea cho lý do
6. **Pay Dialog**: Form nhập mã chuyển khoản + ghi chú

---

### Task 4.4: Admin Commission Policy Page

**File mới**: `frontend/src/app/(dashboard)/admin/commission-policies/page.tsx`
**File mới**: `frontend/src/app/(dashboard)/admin/commission-policies/_components/PoliciesClient.tsx`

Nội dung:
1. **Policy List**: Table hiển thị tất cả policies
   - Columns: Name | Rate % | Min Tuition | Active | Effective From | Effective To
2. **Create Policy Button**: Dialog form
3. **Edit Policy**: Inline edit hoặc dialog
4. **Toggle Active**: Switch on/off

---

### Task 4.5: Navigation Updates

**File**: `frontend/src/lib/config/navigation.ts`

Thêm menu items:
```typescript
// Admin menu:
{ label: "Hoa hồng", href: "/admin/commissions", icon: DollarSign },
{ label: "Chính sách HH", href: "/admin/commission-policies", icon: FileText },

// CTV dashboard: Thêm tab "Hoa hồng" (handled in CTVDashboardClient)
```

---

### Task 4.6: Fix CTV Dashboard Pagination (Audit F-1)

**File**: `frontend/src/app/(dashboard)/ctv/_components/CTVDashboardClient.tsx`

**Hành động**: Thêm pagination state + controls cho leads và claims tabs.

```typescript
// Thêm state:
const [leadsPage, setLeadsPage] = useState(0);
const [claimsPage, setClaimsPage] = useState(0);
const PAGE_SIZE = 10;

// Truyền params vào hooks:
const { data: leadsData } = useCTVLeads({ skip: leadsPage * PAGE_SIZE, limit: PAGE_SIZE });
const { data: claimsData } = useCTVClaims({ skip: claimsPage * PAGE_SIZE, limit: PAGE_SIZE });

// Thêm pagination controls (Prev/Next buttons) ở cuối mỗi tab
```

---

### Task 4.7: Fix Admin Search Debounce (Audit F-2)

**File**: `frontend/src/app/(dashboard)/admin/collaborators/_components/CollaboratorsClient.tsx`

**Hành động**: Thêm debounce cho search input.

```typescript
// Thêm:
const [searchInput, setSearchInput] = useState("");
const debouncedSearch = useDebouncedValue(searchInput, 300);

// Thay setSearch(e.target.value) bằng setSearchInput(e.target.value)
// Dùng debouncedSearch thay vì search cho API query
```

**Nếu chưa có `useDebouncedValue` hook**: Tạo tại `frontend/src/hooks/useDebouncedValue.ts`:

```typescript
import { useState, useEffect } from "react";

export function useDebouncedValue<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debouncedValue;
}
```

---

### Task 4.8: Fix CTV Dashboard Error Handling (Audit F-3)

**File**: `frontend/src/app/(dashboard)/ctv/_components/CTVDashboardClient.tsx`

**Hành động**: Thêm error state cho React Query hooks.

```tsx
const { data, isLoading, isError, error, refetch } = useCTVLeads(...);

// Thay vì chỉ kiểm tra isLoading, thêm:
if (isError) {
  return (
    <div className="text-center py-8">
      <p className="text-destructive">Không thể tải dữ liệu. Vui lòng thử lại.</p>
      <Button variant="outline" onClick={() => refetch()} className="mt-4">
        Thử lại
      </Button>
    </div>
  );
}
```

---

### Task 4.9: Empty State CTA (Audit F-6)

> ~~**F-5**~~: *(Loại bỏ — xác minh 2026-02-25)* `&agrave;` trong JSX **renders đúng** thành `à`. JSX hỗ trợ HTML entities natively. Không cần sửa.

**F-6**: Thêm CTA button trong empty state:

```tsx
// TÌM "Chưa có yêu cầu claim nào" và thay bằng:
<div className="text-center py-8">
  <p className="text-muted-foreground">Chưa có yêu cầu claim nào.</p>
  <Button variant="outline" className="mt-4" onClick={() => setShowSubmitDialog(true)}>
    Giới thiệu lead đầu tiên
  </Button>
</div>
```

---

### Task 4.10: Self-claim email check (Audit B-4)

**File**: `app/services/collaborator_service.py`, method `submit_lead_claim()`

**Hành động**: Thêm email cross-check bên cạnh phone check hiện tại.

```python
# TÌM self-claim phone check (khoảng dòng 303) và THÊM:
# Check email match (nếu CTV có email và claim data có email)
if (
    collaborator.email
    and claim_data.email
    and collaborator.email.lower() == claim_data.email.lower()
):
    raise BusinessRuleViolation(
        "Không thể claim lead có email trùng với email CTV"
    )
```

---

### Task 4.11: Sync frontend `CollaboratorUpdate` type (Xác minh NEW-F4)

> **Xác minh 2026-02-25**: NEW-F4 (Medium) — Frontend `CollaboratorUpdate` type include `status` field. Cần sync khi backend fix B-2/P-1.

**File**: `frontend/src/types/collaborator.types.ts`

**Hành động**: Xóa `status` field khỏi `CollaboratorUpdate` interface (đồng bộ với backend Task 1.1).

```typescript
// TÌM (khoảng dòng 51-62):
export interface CollaboratorUpdate {
  full_name?: string
  phone?: string
  email?: string | null
  status?: CollaboratorStatus    // ← XÓA DÒNG NÀY
  managed_by_officer_id?: number | null
  ...
}

// SAU KHI SỬA:
export interface CollaboratorUpdate {
  full_name?: string
  phone?: string
  email?: string | null
  // status: REMOVED — chỉ thay đổi qua /approve, /suspend, /reactivate
  managed_by_officer_id?: number | null
  ...
}
```

**Lưu ý**: Cũng cần kiểm tra Zod schema trong `frontend/src/lib/zod/collaborator.ts` có mirror `status` field không. Nếu có, cũng xóa.

---

### Task 4.12: Wrap `SubmitLeadDialog.onSubmit` trong try-catch (Xác minh NEW-F5)

> **Xác minh 2026-02-25**: NEW-F5 (Medium) — `mutateAsync` throw khi network error → unhandled rejection. Dialog state stale.

**File**: `frontend/src/components/ctv/SubmitLeadDialog.tsx`

**Hành động**: Wrap `onSubmit` trong try-catch.

```tsx
// TÌM (khoảng dòng 109-112):
async function onSubmit(data: LeadClaimFormData) {
    await submitLead.mutateAsync({ lead_data: data })
    onOpenChange(false)
}

// THAY BẰNG:
async function onSubmit(data: LeadClaimFormData) {
    try {
        await submitLead.mutateAsync({ lead_data: data })
        onOpenChange(false)
    } catch {
        // Error đã được xử lý bởi React Query onError/toast
        // Dialog giữ nguyên state để user có thể retry
    }
}
```

**Checklist Phase 4**:
- [ ] Task 4.1: Frontend types + API client + hooks
- [ ] Task 4.2: CTV commission tab
- [ ] Task 4.3: Admin commission management page
- [ ] Task 4.4: Admin commission policy page
- [ ] Task 4.5: Navigation updates
- [ ] Task 4.6: CTV dashboard pagination (F-1)
- [ ] Task 4.7: Admin search debounce (F-2)
- [ ] Task 4.8: CTV dashboard error handling (F-3)
- [ ] Task 4.9: Empty state CTA (F-6) — ~~F-5 loại bỏ (not a bug)~~
- [ ] Task 4.10: Self-claim email check (B-4)
- [ ] Task 4.11: Sync frontend `CollaboratorUpdate` type — xóa `status` (NEW-F4, cùng B-2)
- [ ] Task 4.12: Wrap `SubmitLeadDialog.onSubmit` trong try-catch (NEW-F5)
- [ ] Frontend E2E test: CTV commission flow
- [ ] Frontend E2E test: Admin commission management flow
- [ ] Type-check pass: `npm run type-check`
- [ ] Lint pass: `npm run lint`
- [ ] Build success: `npm run build`

---

## TỔNG KẾT FILE CHANGES

### Files mới (Backend)

| File | Phase | Mô tả |
|------|-------|-------|
| `app/models/commission.py` | 1 | CommissionPolicy + Commission models |
| `app/schemas/commission.py` | 1 | Pydantic schemas (15+ schemas) |
| `app/repositories/commission_repository.py` | 2 | Data access layer |
| `app/services/commission_service.py` | 2 | Business logic |
| `app/tasks/commission_tasks.py` | 2 | Celery task |
| `app/routers/commissions.py` | 3 | API endpoints (3 routers) |
| `alembic/versions/xxx_add_commission_*.py` | 1 | Migration (auto-generated) |
| `alembic/versions/xxx_add_code_sequence.py` | 1 | Migration for PG sequence |
| `tests/services/test_commission_service.py` | 2 | Service unit tests |
| `tests/api/test_commission_api.py` | 3 | API integration tests |

### Files sửa (Backend)

| File | Phase | Thay đổi |
|------|-------|----------|
| `app/models/__init__.py` | 1 | Import Commission, CommissionPolicy |
| `app/models/collaborator.py` | 1 | Thêm `commissions` relationship |
| `app/models/lead.py` | 1 | Thêm `commission` relationship |
| `app/schemas/collaborator.py` | 1 | Xóa status từ Update, thêm CollaboratorListItem, cập nhật Stats |
| `app/repositories/collaborator_repository.py` | 1 | Whitelist sort_by, fix code generation |
| `app/repositories/lead_repository.py` | 2 | Thêm count_leads_by_validity_grouped |
| `app/services/collaborator_service.py` | 1+2 | Thêm reactivate, field whitelist (Task 1.10), optimize stats, email check |
| `app/routers/collaborators.py` | 1 | Defensive officer filter, thêm reactivate, rate limit |
| `app/core/deps.py` | 1+3 | Thêm explicit Officer check (Task 1.9) + commission IDOR deps |
| `app/main.py` | 3 | Đăng ký commission routers |
| `app/casbin_config/policy_templates.py` | 3 | Thêm commission Casbin policies |
| `app/services/admission_service.py` | 3 | Thêm commission trigger trong enroll_student |

### Files mới (Frontend)

| File | Phase | Mô tả |
|------|-------|-------|
| `src/types/commission.types.ts` | 4 | TypeScript interfaces |
| `src/lib/api/commissions.ts` | 4 | API client |
| `src/hooks/useCommissions.ts` | 4 | React Query hooks |
| `src/hooks/useDebouncedValue.ts` | 4 | Debounce utility hook |
| `src/app/(dashboard)/admin/commissions/page.tsx` | 4 | Admin page |
| `src/app/(dashboard)/admin/commissions/_components/CommissionsClient.tsx` | 4 | Admin client |
| `src/app/(dashboard)/admin/commission-policies/page.tsx` | 4 | Policy page |
| `src/app/(dashboard)/admin/commission-policies/_components/PoliciesClient.tsx` | 4 | Policy client |

### Files sửa (Frontend)

| File | Phase | Thay đổi |
|------|-------|----------|
| `src/app/(dashboard)/ctv/_components/CTVDashboardClient.tsx` | 4 | Commission tab, pagination, error handling (NEW-F1), CTA (F-6) |
| `src/app/(dashboard)/admin/collaborators/_components/CollaboratorsClient.tsx` | 4 | Debounce search |
| `src/lib/config/navigation.ts` | 4 | Commission menu items |
| `src/types/collaborator.types.ts` | 4 | Xóa `status` từ `CollaboratorUpdate` (NEW-F4, sync với B-2) |
| `src/components/ctv/SubmitLeadDialog.tsx` | 4 | Wrap onSubmit trong try-catch (NEW-F5) |

---

## TEST MATRIX

### Unit Tests (Phase 2)

| Test File | Test Cases | Coverage |
|-----------|-----------|----------|
| `test_commission_service.py` | | |
| | `test_calculate_commission_basic` | Tính hoa hồng với policy 5% |
| | `test_calculate_commission_no_policy` | Không có policy active → skip |
| | `test_calculate_commission_below_min_tuition` | Tuition < min → skip |
| | `test_calculate_commission_duplicate` | Lead đã có commission → error |
| | `test_approve_commission` | pending → approved |
| | `test_approve_non_pending` | approved → approve → error |
| | `test_reject_commission` | pending → rejected |
| | `test_pay_commission` | approved → paid |
| | `test_pay_non_approved` | pending → pay → error |

### API Tests (Phase 3)

| Test File | Test Cases | Coverage |
|-----------|-----------|----------|
| `test_commission_api.py` | | |
| | `test_create_policy_admin` | Admin tạo policy (201) |
| | `test_create_policy_non_admin` | Officer tạo → 403 |
| | `test_list_commissions_admin` | Admin list all |
| | `test_approve_commission_admin` | Admin approve (200) |
| | `test_reject_commission_admin` | Admin reject with reason |
| | `test_pay_commission_admin` | Admin pay with reference |
| | `test_ctv_list_own_commissions` | CTV xem commission của mình |
| | `test_ctv_cannot_see_others` | CTV không thấy commission CTV khác |
| | `test_ctv_commission_stats` | CTV xem stats |
| | `test_enrollment_trigger` | Enroll lead có referrer → commission created |
| | `test_enrollment_no_referrer` | Enroll lead không referrer → no commission |

### Frontend Tests (Phase 4)

| Test | Description |
|------|-------------|
| Type check | `npm run type-check` pass |
| Lint | `npm run lint` pass |
| Build | `npm run build` success |
| CTV Dashboard | Commission tab renders, stats hiển thị đúng |
| Admin Commission | Table renders, approve/reject/pay actions work |

---

## TIMELINE TỔNG HỢP

```
Phase 1 (3 ngày):  [████████████░░░░░░░░░░░░░░░░░░]
Phase 2 (3-4 ngày): [░░░░░░░░░░░░████████████████░░░]
Phase 3 (3-4 ngày): [░░░░░░░░░░░░░░░░░░░░████████░░░]
Phase 4 (4-5 ngày): [░░░░░░░░░░░░░░░░░░░░░░░░████████]
                     ─────────────────────────────────
                     Tuần 1       Tuần 2       Tuần 3
```

**Tổng**: ~13-16 ngày làm việc (khoảng 3-4 tuần)

---

## GHI CHÚ QUAN TRỌNG

1. **Đọc file trước khi sửa**: Luôn đọc file hiện tại trước khi apply changes — code có thể đã thay đổi kể từ thời điểm viết plan này.

2. **Test trước mỗi Phase**: Chạy toàn bộ test suite sau mỗi Phase để đảm bảo không regression.

3. **Migration safety**: Review migration file trước khi chạy. Đảm bảo down migration hoạt động.

4. **Admission service**: Task 3.5 (enrollment trigger) là phần phức tạp nhất. Đọc kỹ `enroll_student()` hiện tại, hiểu flow, rồi mới thêm commission logic.

5. **Commission amount precision**: Dùng `Decimal` cho mọi tính toán tiền. Không dùng `float`.

6. **Idempotency**: Celery task phải idempotent — nếu chạy 2 lần cho cùng lead, chỉ tạo 1 commission (unique constraint + duplicate check).

7. **Không hoàn hoa hồng**: Theo business decision, không implement clawback. Nếu lead withdraw sau khi enrolled, commission vẫn giữ nguyên.
