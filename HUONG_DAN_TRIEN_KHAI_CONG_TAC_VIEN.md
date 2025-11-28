# 🎯 HƯỚNG DẪN TRIỂN KHAI HỆ THỐNG QUẢN LÝ CỘNG TÁC VIÊN

## 📌 TỔNG QUAN

Tài liệu này hướng dẫn chi tiết cách triển khai hệ thống quản lý cộng tác viên (Collaborator/Referrer Management System) cho hệ thống QLTS.

### Yêu cầu nghiệp vụ:
1. ✅ Cộng tác viên nhập lead vào hệ thống
2. ✅ Theo dõi quá trình tư vấn lead
3. ✅ Tự động tính và trả hoa hồng khi lead nhập học thành công

---

## 🏗️ KIẾN TRÚC HỆ THỐNG

### 1. Database Schema

```
┌─────────────────────┐
│   Collaborators     │
│  (Cộng tác viên)    │
├─────────────────────┤
│ id (PK)             │
│ code (unique)       │◄────┐
│ full_name           │     │
│ email (unique)      │     │
│ phone               │     │
│ category            │     │
│ total_leads         │     │
│ successful_leads    │     │
│ total_commission... │     │
└─────────────────────┘     │
         ▲                  │
         │                  │
         │                  │
┌─────────────────────┐     │
│    Commissions      │     │
│    (Hoa hồng)       │     │
├─────────────────────┤     │
│ id (PK)             │     │
│ code (unique)       │     │
│ collaborator_id (FK)├─────┘
│ lead_id (FK)        ├──────┐
│ application_id (FK) │      │
│ policy_id (FK)      │      │
│ base_amount         │      │
│ commission_rate     │      │
│ commission_amount   │      │
│ status              │      │
│ approved_by_user_id │      │
│ paid_by_user_id     │      │
└─────────────────────┘      │
         ▲                   │
         │                   │
         │                   │
┌─────────────────────┐      │
│ CommissionPolicies  │      │
│ (Chính sách HH)     │      │
├─────────────────────┤      │
│ id (PK)             │      │
│ code (unique)       │      │
│ name                │      │
│ calculation_type    │      │
│ percentage_value    │      │
│ fixed_amount        │      │
│ applicable_scope    │      │
│ effective_start_date│      │
│ effective_end_date  │      │
└─────────────────────┘      │
                             │
                             ▼
                    ┌─────────────────────┐
                    │       Leads         │
                    │  (Khách hàng TN)    │
                    ├─────────────────────┤
                    │ id (PK)             │
                    │ referrer_id (FK)    │◄─── MỚI THÊM
                    │ referrer_code       │◄─── MỚI THÊM
                    │ full_name           │
                    │ email               │
                    │ status              │
                    │ assigned_officer_id │
                    └─────────────────────┘
                             │
                             │
                             ▼
                    ┌─────────────────────┐
                    │   Applications      │
                    │  (Hồ sơ nhập học)   │
                    ├─────────────────────┤
                    │ id (PK)             │
                    │ lead_id (FK)        │
                    │ status              │◄─── "passed" → trigger hoa hồng
                    └─────────────────────┘
```

### 2. Luồng Nghiệp vụ (Business Flow)

```
BƯỚC 1: Cộng tác viên tạo Lead
┌──────────────────────────────────────────────────────────────────┐
│ POST /api/leads                                                  │
│ {                                                                │
│   "full_name": "Nguyễn Văn A",                                   │
│   "email": "nguyenvana@email.com",                               │
│   "phone": "0901234567",                                         │
│   "referrer_code": "CTV001"  ◄─── Mã cộng tác viên              │
│ }                                                                │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
                 Hệ thống tự động:
                 - Tìm Collaborator theo referrer_code
                 - Gán referrer_id cho Lead
                 - Tăng total_leads của Collaborator
                 - Phân công Officer tư vấn


BƯỚC 2: Officer tư vấn Lead
┌──────────────────────────────────────────────────────────────────┐
│ POST /api/leads/{lead_id}/consultations                          │
│ - Officer ghi nhận buổi tư vấn                                   │
│ - Cập nhật trạng thái lead                                       │
│ - Cộng tác viên có thể xem (read-only)                           │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
              Cộng tác viên theo dõi:
              GET /api/collaborators/me/leads
              GET /api/collaborators/me/leads/{lead_id}


BƯỚC 3: Lead nộp hồ sơ
┌──────────────────────────────────────────────────────────────────┐
│ POST /api/leads/{lead_id}/applications                           │
│ - Tạo Application (hồ sơ nhập học)                               │
│ - Status: pending → completed → passed                           │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
              PUT /api/applications/{id}
              {"status": "passed"}


BƯỚC 4: Hệ thống tự động tính hoa hồng
┌──────────────────────────────────────────────────────────────────┐
│ TRIGGER: Application.status = "passed"                           │
│                                                                  │
│ 1. Lấy Lead → Collaborator                                       │
│ 2. Tìm CommissionPolicy phù hợp:                                 │
│    - Kiểm tra applicable_scope (ngành, chương trình)             │
│    - Kiểm tra collaborator_categories                            │
│    - Kiểm tra effective_date                                     │
│    - Sắp xếp theo priority (cao nhất)                            │
│                                                                  │
│ 3. Tính commission_amount:                                       │
│    - Nếu PERCENTAGE: amount = tuition * (percentage / 100)       │
│    - Nếu FIXED_AMOUNT: amount = fixed_amount                     │
│                                                                  │
│ 4. Tạo Commission record:                                        │
│    - status = "pending"                                          │
│    - earned_at = now()                                           │
│                                                                  │
│ 5. Cập nhật Collaborator:                                        │
│    - successful_leads += 1                                       │
│    - pending_commission += commission_amount                     │
│                                                                  │
│ 6. Gửi thông báo cho Cộng tác viên                               │
└──────────────────────────────────────────────────────────────────┘


BƯỚC 5: Admin phê duyệt hoa hồng
┌──────────────────────────────────────────────────────────────────┐
│ POST /api/admin/commissions/{id}/approve                         │
│ - Cập nhật status: pending → approved                            │
│ - approved_at = now()                                            │
│ - approved_by_user_id = current_user.id                          │
└──────────────────────────────────────────────────────────────────┘


BƯỚC 6: Admin thanh toán hoa hồng
┌──────────────────────────────────────────────────────────────────┐
│ POST /api/admin/commissions/{id}/pay                             │
│ - Cập nhật status: approved → paid                               │
│ - paid_at = now()                                                │
│ - paid_by_user_id = current_user.id                              │
│                                                                  │
│ Cập nhật Collaborator:                                           │
│ - pending_commission -= commission_amount                        │
│ - total_commission_earned += commission_amount                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📝 BƯỚC TRIỂN KHAI CHI TIẾT

### **BƯỚC 1: Cập nhật Models**

#### 1.1. Thêm models mới vào `app/models/__init__.py`

```python
# app/models/__init__.py

from app.models.base import Base
from app.models.user import User
from app.models.lead import Lead
from app.models.organization import OrganizationUnit
# ... existing imports ...

# THÊM MỚI
from app.models.collaborator import Collaborator
from app.models.commission import Commission, CommissionPolicy, CommissionStatus, CommissionType, CalculationType

__all__ = [
    "Base",
    "User",
    "Lead",
    # ... existing exports ...
    # THÊM MỚI
    "Collaborator",
    "Commission",
    "CommissionPolicy",
    "CommissionStatus",
    "CommissionType",
    "CalculationType",
]
```

#### 1.2. Cập nhật Lead model để thêm trường referrer

```python
# app/models/lead.py

from sqlalchemy import Column, Integer, ForeignKey, String
from sqlalchemy.orm import relationship

class Lead(Base):
    __tablename__ = "leads"

    # ... existing fields ...

    # THÊM MỚI - Liên kết đến Collaborator
    referrer_id = Column(Integer, ForeignKey("collaborators.id"), nullable=True, index=True)
    referrer_code = Column(String(50), nullable=True, index=True)

    # THÊM MỚI - Relationships
    referrer = relationship("Collaborator", back_populates="leads", foreign_keys=[referrer_id])
    commissions = relationship("Commission", back_populates="lead")
```

---

### **BƯỚC 2: Chạy Migration**

```bash
cd Backend_FastAPI

# Kiểm tra migration
alembic heads
alembic current

# Chạy migration để tạo bảng mới
alembic upgrade head

# Kiểm tra kết quả
alembic current
```

**Kết quả mong đợi:**
- Bảng `collaborators` được tạo
- Bảng `commission_policies` được tạo
- Bảng `commissions` được tạo
- Bảng `leads` có thêm 2 cột: `referrer_id`, `referrer_code`

---

### **BƯỚC 3: Tạo Services (Business Logic)**

#### 3.1. Collaborator Service

```python
# app/services/collaborator_service.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.collaborator import Collaborator
from app.models.lead import Lead
from app.schemas.collaborator import CollaboratorCreate, CollaboratorUpdate
from typing import Optional, List
import structlog

logger = structlog.get_logger(__name__)


class CollaboratorService:
    """Service xử lý logic nghiệp vụ cho Collaborator"""

    @staticmethod
    async def generate_collaborator_code(db: AsyncSession) -> str:
        """Tạo mã cộng tác viên tự động: CTV001, CTV002, ..."""
        result = await db.execute(
            select(func.max(Collaborator.id))
        )
        max_id = result.scalar() or 0
        return f"CTV{str(max_id + 1).zfill(3)}"

    @staticmethod
    async def create_collaborator(
        db: AsyncSession,
        collaborator_data: CollaboratorCreate,
        created_by_user_id: Optional[int] = None
    ) -> Collaborator:
        """Tạo mới cộng tác viên"""

        # Tạo mã cộng tác viên
        code = await CollaboratorService.generate_collaborator_code(db)

        # Tạo đối tượng
        collaborator = Collaborator(
            code=code,
            **collaborator_data.model_dump(),
            created_by_user_id=created_by_user_id
        )

        db.add(collaborator)
        await db.commit()
        await db.refresh(collaborator)

        logger.info("collaborator_created", collaborator_code=code)
        return collaborator

    @staticmethod
    async def get_collaborator_by_code(
        db: AsyncSession,
        code: str
    ) -> Optional[Collaborator]:
        """Lấy cộng tác viên theo mã"""
        result = await db.execute(
            select(Collaborator).where(Collaborator.code == code)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_collaborator_by_id(
        db: AsyncSession,
        collaborator_id: int
    ) -> Optional[Collaborator]:
        """Lấy cộng tác viên theo ID"""
        result = await db.execute(
            select(Collaborator).where(Collaborator.id == collaborator_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_collaborator(
        db: AsyncSession,
        collaborator: Collaborator,
        update_data: CollaboratorUpdate
    ) -> Collaborator:
        """Cập nhật thông tin cộng tác viên"""

        for field, value in update_data.model_dump(exclude_unset=True).items():
            setattr(collaborator, field, value)

        await db.commit()
        await db.refresh(collaborator)

        logger.info("collaborator_updated", collaborator_id=collaborator.id)
        return collaborator

    @staticmethod
    async def update_statistics(
        db: AsyncSession,
        collaborator: Collaborator
    ) -> None:
        """Cập nhật thống kê cộng tác viên"""

        # Đếm tổng số lead
        total_leads_result = await db.execute(
            select(func.count(Lead.id))
            .where(Lead.referrer_id == collaborator.id)
        )
        collaborator.total_leads = total_leads_result.scalar() or 0

        # Đếm số lead thành công (có application.status = 'passed')
        successful_leads_result = await db.execute(
            select(func.count(Lead.id))
            .join(Lead.application)
            .where(
                Lead.referrer_id == collaborator.id,
                Lead.application.has(status="passed")
            )
        )
        collaborator.successful_leads = successful_leads_result.scalar() or 0

        await db.commit()

    @staticmethod
    async def list_collaborators(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        category: Optional[str] = None
    ) -> List[Collaborator]:
        """Lấy danh sách cộng tác viên"""

        query = select(Collaborator)

        if status:
            query = query.where(Collaborator.status == status)
        if category:
            query = query.where(Collaborator.category == category)

        query = query.offset(skip).limit(limit).order_by(Collaborator.created_at.desc())

        result = await db.execute(query)
        return result.scalars().all()
```

#### 3.2. Commission Service

```python
# app/services/commission_service.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.models.commission import Commission, CommissionPolicy, CommissionStatus, CalculationType
from app.models.lead import Lead
from app.models.application import Application
from app.models.collaborator import Collaborator
from app.schemas.commission import CommissionCreate
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
import structlog

logger = structlog.get_logger(__name__)


class CommissionService:
    """Service xử lý logic nghiệp vụ cho Commission"""

    @staticmethod
    async def generate_commission_code(db: AsyncSession) -> str:
        """Tạo mã hoa hồng tự động: COM001, COM002, ..."""
        result = await db.execute(
            select(func.max(Commission.id))
        )
        max_id = result.scalar() or 0
        return f"COM{str(max_id + 1).zfill(6)}"

    @staticmethod
    async def find_applicable_policy(
        db: AsyncSession,
        collaborator: Collaborator,
        application: Application
    ) -> Optional[CommissionPolicy]:
        """
        Tìm chính sách hoa hồng phù hợp

        Logic:
        1. Kiểm tra effective_date (hiện tại trong khoảng hiệu lực)
        2. Kiểm tra is_active = True
        3. Kiểm tra applicable_scope (major_program_id, offering_id)
        4. Kiểm tra collaborator_categories
        5. Sắp xếp theo priority (cao nhất) và lấy 1
        """

        now = datetime.utcnow()

        query = select(CommissionPolicy).where(
            and_(
                CommissionPolicy.is_active == True,
                CommissionPolicy.effective_start_date <= now,
                or_(
                    CommissionPolicy.effective_end_date == None,
                    CommissionPolicy.effective_end_date >= now
                )
            )
        )

        result = await db.execute(query)
        policies = result.scalars().all()

        # Filter theo applicable_scope và collaborator_categories
        applicable_policies = []
        for policy in policies:
            # Kiểm tra scope
            if policy.applicable_scope:
                scope = policy.applicable_scope
                if "major_programs" in scope:
                    if application.major_program_id not in scope["major_programs"]:
                        continue
                if "offerings" in scope:
                    if application.program_offering_id not in scope["offerings"]:
                        continue

            # Kiểm tra category
            if policy.collaborator_categories:
                if collaborator.category not in policy.collaborator_categories:
                    continue

            applicable_policies.append(policy)

        # Sắp xếp theo priority và lấy cao nhất
        if applicable_policies:
            applicable_policies.sort(key=lambda p: p.priority, reverse=True)
            return applicable_policies[0]

        return None

    @staticmethod
    async def calculate_commission_amount(
        policy: CommissionPolicy,
        base_amount: Decimal
    ) -> tuple[Decimal, Optional[Decimal]]:
        """
        Tính số tiền hoa hồng

        Returns:
            (commission_amount, commission_rate)
        """

        if policy.calculation_type == CalculationType.PERCENTAGE:
            rate = policy.percentage_value
            amount = base_amount * (rate / Decimal(100))
            return (amount, rate)

        elif policy.calculation_type == CalculationType.FIXED_AMOUNT:
            return (policy.fixed_amount, None)

        return (Decimal(0), None)

    @staticmethod
    async def create_commission_for_enrollment(
        db: AsyncSession,
        application: Application,
        tuition_amount: Decimal
    ) -> Optional[Commission]:
        """
        Tạo hoa hồng khi lead nhập học thành công

        TRIGGER: Application.status = "passed"
        """

        # Lấy Lead
        lead = await db.get(Lead, application.lead_id)
        if not lead or not lead.referrer_id:
            logger.info("no_referrer_for_lead", lead_id=application.lead_id)
            return None

        # Lấy Collaborator
        collaborator = await db.get(Collaborator, lead.referrer_id)
        if not collaborator or not collaborator.is_active:
            logger.info("collaborator_inactive", collaborator_id=lead.referrer_id)
            return None

        # Tìm chính sách hoa hồng phù hợp
        policy = await CommissionService.find_applicable_policy(
            db, collaborator, application
        )
        if not policy:
            logger.warning("no_applicable_policy",
                          collaborator_id=collaborator.id,
                          application_id=application.id)
            return None

        # Kiểm tra minimum_tuition
        if policy.minimum_tuition and tuition_amount < policy.minimum_tuition:
            logger.info("tuition_below_minimum",
                       tuition=tuition_amount,
                       minimum=policy.minimum_tuition)
            return None

        # Tính hoa hồng
        commission_amount, commission_rate = await CommissionService.calculate_commission_amount(
            policy, tuition_amount
        )

        # Tạo mã hoa hồng
        code = await CommissionService.generate_commission_code(db)

        # Tạo Commission record
        commission = Commission(
            code=code,
            collaborator_id=collaborator.id,
            lead_id=lead.id,
            application_id=application.id,
            policy_id=policy.id,
            base_amount=tuition_amount,
            commission_rate=commission_rate,
            commission_amount=commission_amount,
            status=CommissionStatus.PENDING,
            earned_at=datetime.utcnow()
        )

        db.add(commission)

        # Cập nhật Collaborator statistics
        collaborator.successful_leads += 1
        collaborator.pending_commission += commission_amount

        await db.commit()
        await db.refresh(commission)

        logger.info("commission_created",
                   commission_code=code,
                   amount=float(commission_amount),
                   collaborator_id=collaborator.id)

        return commission

    @staticmethod
    async def approve_commission(
        db: AsyncSession,
        commission: Commission,
        approved_by_user_id: int,
        notes: Optional[str] = None
    ) -> Commission:
        """Phê duyệt hoa hồng"""

        if commission.status != CommissionStatus.PENDING:
            raise ValueError(f"Cannot approve commission with status: {commission.status}")

        commission.status = CommissionStatus.APPROVED
        commission.approved_at = datetime.utcnow()
        commission.approved_by_user_id = approved_by_user_id
        if notes:
            commission.notes = notes

        await db.commit()
        await db.refresh(commission)

        logger.info("commission_approved",
                   commission_id=commission.id,
                   approved_by=approved_by_user_id)

        return commission

    @staticmethod
    async def pay_commission(
        db: AsyncSession,
        commission: Commission,
        paid_by_user_id: int,
        notes: Optional[str] = None
    ) -> Commission:
        """Thanh toán hoa hồng"""

        if commission.status != CommissionStatus.APPROVED:
            raise ValueError(f"Cannot pay commission with status: {commission.status}")

        commission.status = CommissionStatus.PAID
        commission.paid_at = datetime.utcnow()
        commission.paid_by_user_id = paid_by_user_id
        if notes:
            commission.notes = notes

        # Cập nhật Collaborator
        collaborator = await db.get(Collaborator, commission.collaborator_id)
        if collaborator:
            collaborator.pending_commission -= commission.commission_amount
            collaborator.total_commission_earned += commission.commission_amount

        await db.commit()
        await db.refresh(commission)

        logger.info("commission_paid",
                   commission_id=commission.id,
                   amount=float(commission.commission_amount),
                   paid_by=paid_by_user_id)

        return commission

    @staticmethod
    async def reject_commission(
        db: AsyncSession,
        commission: Commission,
        rejected_by_user_id: int,
        rejection_reason: str
    ) -> Commission:
        """Từ chối hoa hồng"""

        if commission.status != CommissionStatus.PENDING:
            raise ValueError(f"Cannot reject commission with status: {commission.status}")

        commission.status = CommissionStatus.REJECTED
        commission.approved_by_user_id = rejected_by_user_id  # Track who rejected
        commission.approved_at = datetime.utcnow()
        commission.rejection_reason = rejection_reason

        # Trừ lại pending_commission
        collaborator = await db.get(Collaborator, commission.collaborator_id)
        if collaborator:
            collaborator.pending_commission -= commission.commission_amount

        await db.commit()
        await db.refresh(commission)

        logger.info("commission_rejected",
                   commission_id=commission.id,
                   reason=rejection_reason)

        return commission
```

---

### **BƯỚC 4: Tạo API Endpoints**

#### 4.1. Collaborator Router

```python
# app/routers/collaborators.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.collaborator import (
    CollaboratorCreate,
    CollaboratorUpdate,
    CollaboratorResponse,
    CollaboratorListResponse,
    CollaboratorStatsResponse
)
from app.services.collaborator_service import CollaboratorService
from typing import List

router = APIRouter(prefix="/api/collaborators", tags=["Collaborators"])


@router.post("", response_model=CollaboratorResponse, status_code=status.HTTP_201_CREATED)
async def create_collaborator(
    data: CollaboratorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Tạo mới cộng tác viên (Admin/Manager only)"""

    # TODO: Kiểm tra quyền (admin/manager)

    collaborator = await CollaboratorService.create_collaborator(
        db, data, created_by_user_id=current_user.id
    )
    return collaborator


@router.get("", response_model=List[CollaboratorListResponse])
async def list_collaborators(
    skip: int = 0,
    limit: int = 50,
    status: str = None,
    category: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lấy danh sách cộng tác viên"""

    collaborators = await CollaboratorService.list_collaborators(
        db, skip=skip, limit=limit, status=status, category=category
    )
    return collaborators


@router.get("/{collaborator_id}", response_model=CollaboratorResponse)
async def get_collaborator(
    collaborator_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lấy thông tin cộng tác viên"""

    collaborator = await CollaboratorService.get_collaborator_by_id(db, collaborator_id)
    if not collaborator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collaborator not found"
        )
    return collaborator


@router.put("/{collaborator_id}", response_model=CollaboratorResponse)
async def update_collaborator(
    collaborator_id: int,
    data: CollaboratorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cập nhật thông tin cộng tác viên"""

    collaborator = await CollaboratorService.get_collaborator_by_id(db, collaborator_id)
    if not collaborator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collaborator not found"
        )

    updated = await CollaboratorService.update_collaborator(db, collaborator, data)
    return updated


@router.get("/{collaborator_id}/leads")
async def get_collaborator_leads(
    collaborator_id: int,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lấy danh sách leads của cộng tác viên"""

    # TODO: Implement lead listing
    pass


@router.get("/{collaborator_id}/commissions")
async def get_collaborator_commissions(
    collaborator_id: int,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lấy danh sách hoa hồng của cộng tác viên"""

    # TODO: Implement commission listing
    pass


@router.get("/{collaborator_id}/stats", response_model=CollaboratorStatsResponse)
async def get_collaborator_stats(
    collaborator_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lấy thống kê của cộng tác viên"""

    # TODO: Implement statistics
    pass
```

#### 4.2. Commission Admin Router

```python
# app/routers/admin/commissions.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.commission import (
    CommissionResponse,
    CommissionApprove,
    CommissionReject,
    CommissionPay
)
from app.services.commission_service import CommissionService

router = APIRouter(prefix="/api/admin/commissions", tags=["Admin - Commissions"])


@router.post("/{commission_id}/approve", response_model=CommissionResponse)
async def approve_commission(
    commission_id: int,
    data: CommissionApprove,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Phê duyệt hoa hồng (Admin only)"""

    commission = await db.get(Commission, commission_id)
    if not commission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commission not found"
        )

    try:
        approved = await CommissionService.approve_commission(
            db, commission, current_user.id, data.notes
        )
        return approved
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{commission_id}/reject", response_model=CommissionResponse)
async def reject_commission(
    commission_id: int,
    data: CommissionReject,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Từ chối hoa hồng (Admin only)"""

    commission = await db.get(Commission, commission_id)
    if not commission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commission not found"
        )

    try:
        rejected = await CommissionService.reject_commission(
            db, commission, current_user.id, data.rejection_reason
        )
        return rejected
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{commission_id}/pay", response_model=CommissionResponse)
async def pay_commission(
    commission_id: int,
    data: CommissionPay,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Thanh toán hoa hồng (Admin only)"""

    commission = await db.get(Commission, commission_id)
    if not commission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commission not found"
        )

    try:
        paid = await CommissionService.pay_commission(
            db, commission, current_user.id, data.notes
        )
        return paid
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
```

---

### **BƯỚC 5: Cập nhật Lead Creation để hỗ trợ Referrer Code**

```python
# app/routers/leads.py (cập nhật existing)

from app.services.collaborator_service import CollaboratorService

@router.post("", response_model=LeadResponse)
async def create_lead(
    data: LeadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Tạo lead mới (có thể có referrer_code)"""

    lead_dict = data.model_dump()

    # XỬ LÝ REFERRER CODE
    referrer_code = lead_dict.pop("referrer_code", None)
    if referrer_code:
        collaborator = await CollaboratorService.get_collaborator_by_code(db, referrer_code)
        if collaborator and collaborator.is_active:
            lead_dict["referrer_id"] = collaborator.id
            lead_dict["referrer_code"] = referrer_code

            # Tăng total_leads
            collaborator.total_leads += 1
            await db.commit()

    # Tạo lead như bình thường
    lead = Lead(**lead_dict)
    db.add(lead)
    await db.commit()
    await db.refresh(lead)

    return lead
```

---

### **BƯỚC 6: Tạo Trigger tự động tính hoa hồng**

```python
# app/routers/applications.py (cập nhật existing)

from app.services.commission_service import CommissionService

@router.put("/{application_id}", response_model=ApplicationResponse)
async def update_application(
    application_id: int,
    data: ApplicationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cập nhật application - TỰ ĐỘNG TẠO HOA HỒNG khi status = 'passed'"""

    application = await db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    old_status = application.status

    # Cập nhật application
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(application, field, value)

    await db.commit()
    await db.refresh(application)

    # TRIGGER: Nếu status chuyển sang "passed" → Tạo hoa hồng
    if old_status != "passed" and application.status == "passed":
        # Lấy học phí từ offering academic info
        tuition_amount = Decimal(0)
        if application.program_offering_id:
            offering = await db.get(ProgramOffering, application.program_offering_id)
            if offering and offering.academic_info_history:
                # Lấy academic info hiện tại
                current_info = next(
                    (info for info in offering.academic_info_history if info.is_active),
                    None
                )
                if current_info:
                    tuition_amount = current_info.tuition_base

        # Tạo hoa hồng
        if tuition_amount > 0:
            commission = await CommissionService.create_commission_for_enrollment(
                db, application, tuition_amount
            )

            if commission:
                # Gửi notification cho cộng tác viên
                # TODO: Implement notification
                pass

    return application
```

---

### **BƯỚC 7: Đăng ký Routers trong main.py**

```python
# app/main.py

from app.routers import collaborators
from app.routers.admin import commissions as admin_commissions

app.include_router(collaborators.router)
app.include_router(admin_commissions.router)
```

---

### **BƯỚC 8: Tạo dữ liệu mẫu (Seed Data)**

```python
# scripts/seed_commission_policies.py

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.commission import CommissionPolicy, CalculationType
from datetime import datetime
from decimal import Decimal

async def seed_commission_policies(db: AsyncSession):
    """Tạo chính sách hoa hồng mẫu"""

    policies = [
        CommissionPolicy(
            code="DEFAULT_5PCT",
            name="Hoa hồng mặc định 5%",
            description="Hoa hồng 5% học phí cho tất cả cộng tác viên",
            calculation_type=CalculationType.PERCENTAGE,
            percentage_value=Decimal("5.00"),
            effective_start_date=datetime(2024, 1, 1),
            is_active=True,
            priority=1
        ),
        CommissionPolicy(
            code="VIP_10PCT",
            name="Hoa hồng VIP 10%",
            description="Hoa hồng 10% học phí cho cộng tác viên VIP",
            calculation_type=CalculationType.PERCENTAGE,
            percentage_value=Decimal("10.00"),
            collaborator_categories=["VIP", "Gold"],
            effective_start_date=datetime(2024, 1, 1),
            is_active=True,
            priority=10
        ),
        CommissionPolicy(
            code="FIXED_2M",
            name="Hoa hồng cố định 2 triệu",
            description="Hoa hồng 2 triệu VND cố định cho ngành Công nghệ thông tin",
            calculation_type=CalculationType.FIXED_AMOUNT,
            fixed_amount=Decimal("2000000"),
            applicable_scope={"major_programs": [1, 2]},  # IDs của ngành CNTT
            effective_start_date=datetime(2024, 1, 1),
            is_active=True,
            priority=5
        )
    ]

    for policy in policies:
        db.add(policy)

    await db.commit()
```

---

## 🎯 TỔNG KẾT

### ✅ Đã triển khai:

1. **Database Schema**: 3 bảng mới + 2 cột mới trong `leads`
2. **Models**: Collaborator, Commission, CommissionPolicy
3. **Schemas**: Pydantic schemas cho API
4. **Services**: CollaboratorService, CommissionService
5. **API Endpoints**:
   - `/api/collaborators/*` - Quản lý cộng tác viên
   - `/api/admin/commissions/*` - Quản lý hoa hồng
6. **Auto Commission**: Tự động tạo hoa hồng khi Application.status = "passed"

### 📊 Quy trình sử dụng:

```
1. Admin tạo Collaborator → Nhận mã CTV001
2. Admin tạo CommissionPolicy → Thiết lập chính sách HH
3. Collaborator nhập Lead với referrer_code = "CTV001"
4. Officer tư vấn Lead → Tạo Consultation
5. Lead nộp hồ sơ → Tạo Application
6. Admin duyệt hồ sơ → Application.status = "passed"
7. HỆ THỐNG TỰ ĐỘNG tạo Commission với status = "pending"
8. Admin phê duyệt hoa hồng → Commission.status = "approved"
9. Admin thanh toán → Commission.status = "paid"
```

### 🔒 Bảo mật & Phân quyền:

- **Collaborator**: Chỉ xem được leads và commissions của mình
- **Officer**: Tư vấn leads, không thấy thông tin hoa hồng
- **Manager**: Quản lý collaborators, xem báo cáo
- **Admin**: Full quyền, phê duyệt và thanh toán hoa hồng

---

## 📞 Liên hệ hỗ trợ

Nếu có thắc mắc trong quá trình triển khai, vui lòng liên hệ team phát triển.
