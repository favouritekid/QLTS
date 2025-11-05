from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import insights_service, lead_service

router = APIRouter(tags=["Leads"])

PermissionDep = Depends(deps.check_permission)
LeadAccessDep = Depends(deps.get_lead_for_user)


@router.post("", response_model=schemas.Lead, status_code=status.HTTP_201_CREATED)
async def create_new_lead(
    lead_in: schemas.LeadCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Tạo một Lead mới."""
    return await lead_service.create_lead(db, lead_in)


@router.get("", response_model=schemas.LeadsPage)
async def get_all_leads(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    # === ⭐️ THÊM CÁC THAM SỐ QUERY ===
    status: Optional[str] = Query(
        None, description="Filter by status (comma-separated)"
    ),
    assigned_officer_id: Optional[int] = Query(
        None, description="Filter by assigned officer ID"
    ),
    unit_id: Optional[int] = Query(None, description="Filter by organization unit ID"),
    major_id: Optional[int] = Query(None, description="Filter by major ID"),
    source: Optional[str] = Query(
        None, description="Filter by source (comma-separated)"
    ),
    search: Optional[str] = Query(
        None, description="Search term for name, email, phone"
    ),
    sort_by: str = Query("created_at", description="Field to sort by"),
    order: str = Query("desc", description="Sort order (asc or desc)"),
    # === KẾT THÚC THÊM THAM SỐ ===
):
    """Lấy danh sách Leads (có phân trang, filter, search, sort)."""
    skip = (page - 1) * page_size
    total, leads = await lead_service.get_leads(
        db,
        skip=skip,
        limit=page_size,
        # === ⭐️ TRUYỀN THAM SỐ VÀO SERVICE ===
        status=status,
        assigned_officer_id=assigned_officer_id,
        unit_id=unit_id,
        major_id=major_id,
        source=source,
        search=search,
        sort_by=sort_by,
        order=order,
        # === KẾT THÚC TRUYỀN THAM SỐ ===
    )
    return {"total_count": total, "leads": leads}


@router.get("/{lead_id}", response_model=schemas.Lead)
async def get_lead_details(
    lead: models.Lead = LeadAccessDep,
):
    """Lấy thông tin chi tiết của một Lead."""
    return lead


@router.put("/{lead_id}", response_model=schemas.Lead)
async def update_existing_lead(
    lead_in: schemas.LeadUpdate,
    lead: models.Lead = LeadAccessDep,
    # Lấy current_user từ Casbin check hoặc get_current_user
    current_user: models.User = PermissionDep,  # <<< LẤY USER TỪ DEPENDENCY
    db: AsyncSession = Depends(database.get_db),
):
    """Cập nhật một Lead (chỉ Admin/Manager)."""
    # <<< SỬA Ở ĐÂY: Truyền current_user vào service >>>
    return await lead_service.update_lead(db, lead.id, lead_in, updated_by=current_user)


@router.post(
    "/{lead_id}/consultations",
    response_model=schemas.Consultation,
    status_code=status.HTTP_201_CREATED,
)
async def add_new_consultation(
    consultation_in: schemas.ConsultationCreate,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Thêm một ghi chú tư vấn mới cho Lead (Đã xác thực 2 lớp)."""
    # Service 'add_consultation' có logic check quyền sở hữu
    # nhưng check ở đây vẫn an toàn hơn
    return await lead_service.add_consultation(
        db, lead.id, current_user.id, consultation_in
    )


@router.post("/{lead_id}/assign", response_model=schemas.Lead)
async def assign_lead_manually(
    assign_data: schemas.AssignLead,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin/Manager only) Gán thủ công một Lead (Đã xác thực 2 lớp)."""
    return await lead_service.assign_lead_manually(
        db, lead.id, assign_data.officer_id, current_user
    )


@router.post("/{lead_id}/action", response_model=schemas.Lead)
async def perform_lead_action(
    action_data: schemas.LeadAction,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Xử lý hành động (reject/reassign) của Officer (Đã xác thực 2 lớp)."""
    return await lead_service.process_officer_action(
        db, lead.id, current_user, action_data.action, action_data.reason
    )


@router.get("/{lead_id}/timeline", response_model=List[schemas.TimelineItem])
async def get_lead_timeline(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Lấy lịch sử tổng hợp (timeline) của một Lead (Đã xác thực quyền)."""
    return await lead_service.get_lead_timeline(db, lead.id)


@router.get("/{lead_id}/insights", response_model=schemas.LeadInsights)
async def get_lead_insights(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Lấy các chỉ số insight 360 độ của một Lead (Đã xác thực quyền)."""
    timeline = await lead_service.get_lead_timeline(db, lead.id)
    return await insights_service.get_lead_insights(db, lead, timeline)


@router.delete(
    "/{lead_id}/consultations/{consultation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_a_consultation(
    consultation_id: int,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin only) Xóa một ghi chú tư vấn (Đã xác thực 2 lớp)."""
    await lead_service.delete_consultation(db, lead.id, consultation_id, current_user)
    return None
