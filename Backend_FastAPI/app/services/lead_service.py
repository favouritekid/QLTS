# app/services/lead_service.py
from datetime import (
    datetime, timezone  # ✅ SỬA LỖI: Thêm dấu cách (E231) và xóa cách thừa cuối dòng (W291)
)
from typing import List, Optional, Tuple

import structlog
from sqlalchemy import func, or_, select  # ✅ SỬA LỖI: Thêm 'desc' vào import và xóa comment
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from .. import models, schemas
from ..config import settings
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


async def calculate_lead_score(
    db: AsyncSession,
    lead_education_level: Optional[str] = None,
    lead_gpa: Optional[float] = None,
    lead_source: Optional[str] = None,
    lead_location: Optional[str] = None,
    unit_id: Optional[int] = None,
) -> int:
    """
    Calculate lead score based on configurable rules from LeadScoringConfig.

    Args:
        db: Database session
        lead_education_level: Education level of lead (high_school, bachelor, master, phd)
        lead_gpa: GPA of lead (0.0-4.0)
        lead_source: Source of lead (website, referral, social_media, etc.)
        lead_location: Location of lead
        unit_id: Organization unit ID (for unit-specific scoring config)

    Returns:
        int: Calculated lead score (0-100)
    """
    try:
        # Default scoring weights (used if no config found)
        default_education_scores = {
            "high_school": 20,
            "bachelor": 40,
            "master": 60,
            "phd": 80,
        }
        default_source_scores = {
            "referral": 30,
            "website": 20,
            "social_media": 15,
            "walk_in": 10,
            "email": 15,
            "phone": 15,
            "event": 25,
            "other": 5,
        }
        default_gpa_multiplier = 10  # 4.0 GPA = 40 points
        default_location_bonus = 20

        score = 0

        # Try to load scoring config from database
        scoring_config = None
        if unit_id:
            scoring_config_query = (
                select(models.LeadScoringConfig)
                .where(models.LeadScoringConfig.unit_id == unit_id)
            )
            scoring_config_result = await db.execute(scoring_config_query)
            scoring_config = scoring_config_result.scalar_one_or_none()

        # Extract config params or use defaults
        if scoring_config and scoring_config.params:
            params = scoring_config.params
            education_scores = params.get("education_scores", default_education_scores)
            source_scores = params.get("source_scores", default_source_scores)
            gpa_multiplier = params.get("gpa_multiplier", default_gpa_multiplier)
            priority_locations = params.get("priority_locations", [])
            location_bonus = params.get("location_bonus", default_location_bonus)
        else:
            education_scores = default_education_scores
            source_scores = default_source_scores
            gpa_multiplier = default_gpa_multiplier
            priority_locations = []
            location_bonus = default_location_bonus

        # Calculate education score
        if lead_education_level:
            score += education_scores.get(lead_education_level.lower(), 0)

        # Calculate GPA score (0-4.0 scale)
        if lead_gpa is not None and lead_gpa > 0:
            gpa_score = min(int(lead_gpa * gpa_multiplier), 40)  # Cap at 40 points
            score += gpa_score

        # Calculate source score
        if lead_source:
            score += source_scores.get(lead_source.lower(), 0)

        # Calculate location bonus
        if lead_location and priority_locations:
            if lead_location.lower() in [loc.lower() for loc in priority_locations]:
                score += location_bonus

        # Cap score at 100
        final_score = min(score, 100)

        log.debug(
            "Lead score calculated",
            education_level=lead_education_level,
            gpa=lead_gpa,
            source=lead_source,
            location=lead_location,
            score=final_score,
        )

        return final_score

    except Exception as e:
        log.error(
            "Error calculating lead score, returning default 0",
            error=str(e),
            exc_info=True,
        )
        return 0


async def _log_lead_state_change(
    db: AsyncSession,
    lead: models.Lead,
    old_state: dict,
    new_state: dict,
    changed_by: Optional[models.User] = None,
    reason: str = "State updated",
):
    """
    Hàm helper tập trung để ghi lại bất kỳ thay đổi trạng thái nào của Lead.
    """
    # Chỉ ghi log nếu thực sự có thay đổi
    if old_state == new_state:
        log.debug(
            "No state change detected, skipping history log.",
            lead_id=getattr(lead, "id", None),
        )  # Thêm getattr phòng trường hợp lead chưa có ID
        return

    # Flush để lấy ID nếu chưa có (ví dụ khi tạo mới)
    if lead.id is None:
        try:
            await db.flush([lead])  # Flush chỉ đối tượng lead
            # Kiểm tra lại ID sau khi flush
            if lead.id is None:
                log.error(
                    "Failed to obtain Lead ID after flush, cannot log history.",
                    lead_email=lead.email,
                )
                # Có thể raise lỗi ở đây nếu việc log history là bắt buộc
                return  # Hoặc bỏ qua việc log nếu ID không lấy được
        except Exception as e:
            # Nếu flush bị lỗi (ví dụ: lỗi FK khác), ta log và raise ngay
            log.error(
                "Failed to flush Lead object before logging history",
                lead_email=lead.email,
                error=str(e),
            )
            raise  # Ném lỗi ban đầu (ví dụ: IntegrityError) lên để service xử lý

    history_entry = models.LeadStatusHistory(
        lead_id=lead.id,  # Giờ chắc chắn có ID
        changed_by_user_id=changed_by.id if changed_by else None,
        reason=reason,
        old_status=old_state.get("status"),
        old_consultation_status_id=old_state.get("consultation_status_id"),
        old_pipeline_stage_id=old_state.get("pipeline_stage_id"),
        old_assigned_officer_id=old_state.get("assigned_officer_id"),
        new_status=new_state.get("status"),
        new_consultation_status_id=new_state.get("consultation_status_id"),
        new_pipeline_stage_id=new_state.get("pipeline_stage_id"),
        new_assigned_officer_id=new_state.get("assigned_officer_id"),
    )
    db.add(history_entry)
    log.info(
        "Lead state change history logged",
        lead_id=lead.id,
        reason=reason,
        old=old_state,
        new=new_state,
    )


def _get_current_lead_state(lead: models.Lead) -> dict:
    """Helper để chụp nhanh trạng thái hiện tại của Lead."""
    return {
        "status": lead.status,
        "consultation_status_id": lead.consultation_status_id,
        "pipeline_stage_id": lead.pipeline_stage_id,
        "assigned_officer_id": lead.assigned_officer_id,
    }


async def get_lead_by_id(db: AsyncSession, lead_id: int) -> models.Lead:
    """
    Lấy chi tiết Lead bằng ID (Detail View).
    Hàm này giữ nguyên eager loading đầy đủ
    vì nó cần thiết cho Timeline và Insights.
    """
    query = (
        select(models.Lead)
        .options(
            selectinload(models.Lead.offering),
            selectinload(models.Lead.unit).options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.major_programs),
            ),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
            # Load sâu consultations và logs để dùng cho timeline/insights
            selectinload(models.Lead.consultations).options(
                joinedload(models.Consultation.officer),
                joinedload(models.Consultation.consultation_status),
            ),
            selectinload(models.Lead.assignment_logs).options(
                joinedload(models.AssignmentLog.officer)
            ),
        )
        .where(models.Lead.id == lead_id)
    )
    result = await db.execute(query)
    lead = result.scalar_one_or_none()
    if not lead:
        raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
    return lead

async def get_lead_by_id_shallow(db: AsyncSession, lead_id: int) -> models.Lead:
    """
    Lấy chi tiết Lead (Shallow View - Nhanh).
    Chỉ Eager Load các quan hệ 1-1 cần thiết cho List/Detail View.
    """
    query = (
        select(models.Lead)
        .options(
            selectinload(models.Lead.offering),
            selectinload(models.Lead.unit), # <--- Load unit (thường là cần)
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
        )
        .where(models.Lead.id == lead_id)
    )
    result = await db.execute(query)
    lead = result.scalar_one_or_none()
    if not lead:
        raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
    return lead

async def get_leads(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 10,
    status: Optional[str] = None,
    assigned_officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    offering_id: Optional[int] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    order: str = "desc",
) -> Tuple[int, List[models.Lead]]:
    """
    Lấy danh sách Leads (List View) - Đã tối ưu hóa eager loading.
    """

    # === Xây dựng query cơ bản ===
    base_query = select(models.Lead)
    count_query = select(func.count(models.Lead.id))  # Đếm dựa trên query gốc

    # === Áp dụng filter ===
    filters = []
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            filters.append(models.Lead.status.in_(statuses))
    if assigned_officer_id is not None:
        filters.append(models.Lead.assigned_officer_id == assigned_officer_id)
    if unit_id is not None:
        filters.append(models.Lead.unit_id == unit_id)
    if offering_id is not None:
        filters.append(models.Lead.offering_id == offering_id)
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            filters.append(models.Lead.source.in_(sources))

    # === Áp dụng search ===
    if search:
        search_term = f"%{search.strip()}%"
        search_conditions = or_(
            models.Lead.full_name.ilike(search_term),
            models.Lead.email.ilike(search_term),
            models.Lead.phone.ilike(search_term),
        )
        filters.append(search_conditions)

    # Áp dụng tất cả filters vào cả hai query
    if filters:
        base_query = base_query.where(*filters)
        count_query = count_query.where(*filters)

    # === Thực thi count query ===
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return 0, []

    # === Áp dụng sắp xếp ===
    sort_column = getattr(models.Lead, sort_by, models.Lead.created_at)
    if order.lower() == "desc":
        leads_query = base_query.order_by(sort_column.desc())
    else:
        leads_query = base_query.order_by(sort_column.asc())

    # === Áp dụng eager loading tối ưu và pagination ===
    leads_query = (
        leads_query.options(
            selectinload(models.Lead.offering),
            selectinload(models.Lead.unit).options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.major_programs),
            ),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
        )
        .offset(skip)
        .limit(limit)
    )

    # === Thực thi query lấy dữ liệu ===
    leads_result = await db.execute(leads_query)
    leads = leads_result.scalars().unique().all()

    return total_count, leads


async def create_lead(db: AsyncSession, lead_in: schemas.LeadCreate) -> models.Lead:
    """Tạo Lead mới, ném DuplicateResourceError nếu trùng."""
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task

    try:
        # Kiểm tra trùng lặp email + unit_id
        existing_lead_query = (
            select(models.Lead)
            .where(
                models.Lead.email == lead_in.email,
                models.Lead.unit_id == lead_in.unit_id,
            )
            .with_for_update()  # Khóa để tránh race condition khi tạo
        )
        existing_lead_result = await db.execute(existing_lead_query)
        if existing_lead_result.scalar_one_or_none():
            raise DuplicateResourceError(
                detail="Lead with this email already exists in the unit."
            )

        # Chuẩn bị dữ liệu và tạo đối tượng Lead
        create_data = lead_in.model_dump()

        # Calculate lead score before creating the lead
        calculated_score = await calculate_lead_score(
            db,
            lead_education_level=create_data.get("education_level"),
            lead_gpa=create_data.get("gpa"),
            lead_source=create_data.get("source"),
            lead_location=create_data.get("location"),
            unit_id=create_data.get("unit_id"),
        )

        # Set the calculated score
        create_data["lead_score"] = calculated_score
        db_lead = models.Lead(**create_data)

        # Lấy trạng thái ban đầu từ DB
        initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
        initial_status = await db.get(models.ConsultationStatus, initial_status_id)

        # Trạng thái "trước khi tạo"
        old_state = _get_current_lead_state(models.Lead())  # Trạng thái rỗng

        # Gán trạng thái ban đầu cho Lead mới
        db_lead.status = "new"  # Trạng thái text mặc định
        if initial_status:
            db_lead.consultation_status_id = initial_status_id
            db_lead.pipeline_stage_id = initial_status.stage_id
        else:
            # Ghi log cảnh báo nếu không tìm thấy status mặc định
            log.warning(
                "Initial consultation status not found during lead creation.",
                status_id=initial_status_id,
            )
            # Gán giá trị mặc định an toàn
            db_lead.consultation_status_id = None
            db_lead.pipeline_stage_id = None

        # Trạng thái "sau khi gán"
        new_state = _get_current_lead_state(db_lead)

        # Thêm Lead vào session (chưa commit)
        db.add(db_lead)

        # Ghi log lịch sử thay đổi (cần flush để lấy lead.id)
        await _log_lead_state_change(
            db,
            db_lead,
            old_state,
            new_state,
            changed_by=None,  # Không có user nào thay đổi khi tạo
            reason="Lead created",
        )

        # Commit transaction
        await db.commit()
        # Refresh để lấy dữ liệu mới nhất (bao gồm cả ID nếu chưa flush)
        await db.refresh(db_lead)
        log.info(
            "New lead created successfully", lead_id=db_lead.id, email=db_lead.email
        )

        # Dispatch Celery task SAU KHI commit thành công
        try:
            process_automatic_lead_assignment_task.delay(db_lead.id)
            log.info("Auto-assignment task dispatched successfully", lead_id=db_lead.id)
        except Exception as e:
            # Ghi log lỗi nếu không dispatch được, nhưng không rollback transaction
            log.error(
                "Failed to dispatch Celery auto-assignment task",
                lead_id=db_lead.id,
                error=str(e),
                exc_info=True,
            )

        # Trả về đối tượng Lead đã được load đầy đủ (bao gồm relations)
        return await get_lead_by_id(db, db_lead.id)

    except Exception as e:
        # Rollback nếu có bất kỳ lỗi nào xảy ra trong khối try
        await db.rollback()
        log.error(
            "Failed to create lead",
            lead_email=lead_in.email,
            error=str(e),
            exc_info=True,
        )
        raise e  # Ném lại lỗi để router xử lý


async def update_lead(
    db: AsyncSession, lead_id: int, lead_in: schemas.LeadUpdate, updated_by: models.User
) -> models.Lead:
    """
    Cập nhật Lead một cách an toàn, ghi log lịch sử.
    """
    async with db.begin_nested():  # Sử dụng transaction lồng nhau
        try:
            # Lấy và khóa Lead để cập nhật
            stmt = (
                select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            )
            result = await db.execute(stmt)
            db_lead = result.scalar_one_or_none()

            if not db_lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")

            # Lưu trạng thái cũ trước khi thay đổi
            old_state = _get_current_lead_state(db_lead)

            # Lấy dữ liệu cập nhật từ schema Pydantic
            update_data = lead_in.model_dump(exclude_unset=True)

            # (Dọn dẹp .strip() đã bị xóa vì Pydantic xử lý)

            # Kiểm tra trùng lặp email nếu email được cập nhật
            if "email" in update_data and update_data["email"] != db_lead.email:
                existing_lead_query = select(models.Lead).where(
                    models.Lead.email == update_data["email"],
                    models.Lead.unit_id == db_lead.unit_id,  # Trong cùng unit
                    models.Lead.id != lead_id,  # Loại trừ chính lead này
                )
                existing_lead_result = await db.execute(existing_lead_query)
                if existing_lead_result.scalar_one_or_none():
                    raise DuplicateResourceError(
                        detail="Another lead with this email already exists in the unit."
                    )

            # Check if scoring-related fields are being updated
            scoring_fields = ["education_level", "gpa", "source", "location"]
            should_recalculate_score = any(field in update_data for field in scoring_fields)

            # Cập nhật các trường thông thường
            for key, value in update_data.items():
                # Xử lý consultation_status_id riêng
                if key != "consultation_status_id":
                    setattr(db_lead, key, value)

            # Recalculate lead score if relevant fields changed
            if should_recalculate_score:
                recalculated_score = await calculate_lead_score(
                    db,
                    lead_education_level=db_lead.education_level,
                    lead_gpa=db_lead.gpa,
                    lead_source=db_lead.source,
                    lead_location=db_lead.location,
                    unit_id=db_lead.unit_id,
                )
                db_lead.lead_score = recalculated_score
                log.info(
                    "Lead score recalculated on update",
                    lead_id=lead_id,
                    old_score=db_lead.lead_score if not should_recalculate_score else "N/A",
                    new_score=recalculated_score,
                )

            # Xử lý cập nhật consultation_status_id (nếu có)
            if "consultation_status_id" in update_data:
                new_status_id = update_data["consultation_status_id"]
                if new_status_id:  # Nếu có status ID mới
                    # Lấy đối tượng ConsultationStatus từ DB
                    new_status = await db.get(models.ConsultationStatus, new_status_id)
                    if not new_status:
                        raise BadRequest(
                            detail=f"Consultation status with id '{new_status_id}' not found."
                        )
                    # Cập nhật consultation_status_id và pipeline_stage_id
                    db_lead.consultation_status_id = new_status.id
                    db_lead.pipeline_stage_id = new_status.stage_id
                    # Giữ nguyên status hoặc update theo logic nghiệp vụ
                    # (không gán status = consultation_status_id vì đây là 2 field khác nhau)
                else:  # Nếu status ID mới là None (hiếm khi xảy ra khi update)
                    db_lead.consultation_status_id = None
                    db_lead.pipeline_stage_id = None
                    db_lead.status = "unknown"  # Hoặc một trạng thái mặc định khác

            # Lấy trạng thái mới sau khi cập nhật
            new_state = _get_current_lead_state(db_lead)

            # Thêm đối tượng vào session (đánh dấu là dirty)
            db.add(db_lead)

            # Ghi log lịch sử nếu có thay đổi
            await _log_lead_state_change(
                db,
                db_lead,
                old_state,
                new_state,
                changed_by=updated_by,
                reason=f"Lead details updated by {updated_by.role}",
            )

            log.info("Lead updated successfully within transaction", lead_id=lead_id)
            # Transaction sẽ commit khi ra khỏi `async with db.begin_nested()`

        except Exception as e:
            # Rollback tự động xảy ra khi có lỗi trong `async with`
            log.error(
                "Failed to update lead, rolling back nested transaction",
                lead_id=lead_id,
                error=str(e),
                exc_info=True,
            )
            raise e  # Ném lại lỗi để router xử lý

        # Trả về lead đã được tải đầy đủ (bao gồm relations)
        # Gọi lại get_lead_by_id để đảm bảo dữ liệu mới nhất và relations
        return await get_lead_by_id(db, lead_id)


async def add_consultation(
    db: AsyncSession, lead_id: int, officer_id: int, data: schemas.ConsultationCreate
) -> models.Consultation:
    """
    Thêm consultation mới, cập nhật trạng thái Lead và ghi log lịch sử.
    """
    async with db.begin_nested():
        try:
            # Lấy Lead (dùng get_lead_by_id để có relations)
            lead = await get_lead_by_id(db, lead_id)
            # Lấy Officer
            officer = await db.get(models.User, officer_id)
            if not officer:
                raise ResourceNotFoundError(f"Officer with id {officer_id} not found.")

            # Kiểm tra quyền: Officer phải được gán cho Lead này
            if lead.assigned_officer_id != officer_id:
                raise PermissionDeniedError(detail="You are not assigned to this lead.")

            # Lấy ConsultationStatus mới từ DB
            new_status = await db.get(models.ConsultationStatus, data.status_id)
            if not new_status:
                raise ResourceNotFoundError(
                    detail=f"Consultation status with id {data.status_id} not found."
                )

            # Lưu trạng thái Lead cũ
            old_state = _get_current_lead_state(lead)

            # Cập nhật trạng thái Lead theo status mới của consultation
            lead.consultation_status_id = new_status.id
            lead.pipeline_stage_id = new_status.stage_id
            # Giữ nguyên status (đây là field riêng, không phải consultation_status_id)

            # Chuẩn bị dữ liệu để tạo Consultation
            create_consult_data = data.model_dump(exclude={"status_id"})
            # (Đã xóa .strip() vì Pydantic xử lý)

            # Tạo đối tượng Consultation mới
            new_consultation = models.Consultation(
                lead_id=lead_id,
                officer_id=officer_id,
                consultation_status_id=new_status.id,  # Gán status ID cho consultation
                **create_consult_data,
            )

            # Thêm các đối tượng vào session
            db.add(new_consultation)
            db.add(lead)  # Đánh dấu lead là dirty

            # Lấy trạng thái Lead mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái Lead
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=officer,
                reason=f"Consultation added: {data.method}",
            )

            # Không cần commit ở đây, `async with` sẽ xử lý

            # Flush để lấy ID cho consultation mới (cần cho refresh)
            await db.flush([new_consultation])

            # Refresh consultation mới để tải relations (officer, consultation_status)
            await db.refresh(new_consultation, ["officer", "consultation_status"])

            log.info(
                "New consultation added for lead",
                lead_id=lead_id,
                consultation_id=new_consultation.id,
                officer_id=officer_id,
            )
            return new_consultation  # Trả về consultation đã được refresh

        except Exception as e:
            # Rollback tự động
            log.error(
                "Failed to add consultation",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True,
            )
            raise e


async def assign_lead_manually(
    db: AsyncSession, lead_id: int, officer_id: int, assigner: models.User
) -> models.Lead:
    """
    Gán lead thủ công cho một officer, cập nhật trạng thái và ghi logs.
    """
    async with db.begin_nested():
        try:
            # Lấy Lead và Officer
            lead = await get_lead_by_id(db, lead_id)
            officer = await db.get(models.User, officer_id)

            # Kiểm tra Officer hợp lệ
            if not officer:
                raise ResourceNotFoundError(
                    detail=f"User (Officer) with id {officer_id} not found."
                )
            if officer.role != "officer":
                raise PermissionDeniedError(
                    detail=f"User with id {officer_id} is not an officer."
                )

            # Lưu trạng thái cũ
            old_state = _get_current_lead_state(lead)

            # Cập nhật Lead
            lead.assigned_officer_id = officer.id
            lead.assigned_at = datetime.now(timezone.utc)
            # Cập nhật status thành 'assigned' nếu đang ở trạng thái ban đầu/chờ gán lại
            if (
                lead.status
                in [
                    settings.DEFAULT_INITIAL_LEAD_STATUS_ID,
                    settings.DEFAULT_REASSIGN_LEAD_STATUS,
                    "new",
                ]
                or not lead.status
            ):
                lead.status = settings.DEFAULT_ASSIGNED_LEAD_STATUS

            # Cập nhật Officer
            officer.last_assigned_at = datetime.now(timezone.utc)
            db.add(officer)  # Đánh dấu officer là dirty

            # Tạo Assignment Log
            log_reason = f"Manually assigned by {assigner.role} {assigner.username}"
            log_entry = models.AssignmentLog(
                lead_id=lead_id,
                officer_id=officer_id,
                method="manual",
                reason=log_reason,
                timestamp=datetime.now(timezone.utc),  # Thêm timestamp
            )
            db.add(lead)  # Đánh dấu lead là dirty
            db.add(log_entry)

            # Lấy trạng thái mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái
            await _log_lead_state_change(
                db, lead, old_state, new_state, changed_by=assigner, reason=log_reason
            )

            log.info(
                "Lead assigned manually",
                lead_id=lead_id,
                officer_id=officer_id,
                assigner_id=assigner.id,
            )
            # Commit transaction

        except Exception as e:
            # Rollback tự động
            log.error(
                "Failed to assign lead manually",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True,
            )
            raise e

        # Trả về lead đã được tải đầy đủ sau khi commit thành công
        return await get_lead_by_id(db, lead_id)


async def get_lead_timeline(db: AsyncSession, lead_id: int) -> List[dict]:
    """Lấy timeline tổng hợp của Lead (consultations và assignment logs)."""

    # 1. ✅ GỌI HÀM ĐÃ TỐI ƯU HÓA EAGER LOADING (từ dòng 104)
    # Hàm này đã load sẵn:
    # - consultations.officer
    # - consultations.consultation_status
    # - assignment_logs.officer
    try:
        lead = await get_lead_by_id(db, lead_id)
    except ResourceNotFoundError:
        raise
    except Exception as e:
        log.error("Failed to get lead for timeline", lead_id=lead_id, error=str(e))
        raise

    # 2. ✅ XÓA BỎ TẤT CẢ CÁC LỆNH `db.refresh(...)`
    log.debug(
        "Lead and all relations loaded via eager loading for timeline", lead_id=lead_id
    )

    timeline_items = []

    # 3. Xử lý consultations (Dữ liệu đã có sẵn)
    if lead.consultations:
        for c in lead.consultations:
            # ❌ KHÔNG CẦN: await db.refresh(c, ["officer", "consultation_status"])
            timeline_items.append(
                schemas.TimelineItem(
                    type="consultation",
                    data=schemas.Consultation.model_validate(c),
                    timestamp=c.consultation_date,
                ).model_dump()
            )

    # 4. Xử lý assignment logs (Dữ liệu đã có sẵn)
    if lead.assignment_logs:
        for log_entry in lead.assignment_logs:
            # ❌ KHÔNG CẦN: await db.refresh(log_entry, ["officer"])
            timeline_items.append(
                schemas.TimelineItem(
                    type="assignment",
                    data=schemas.AssignmentLog.model_validate(log_entry),
                    timestamp=log_entry.timestamp,
                ).model_dump()
            )

    # Sắp xếp timeline theo timestamp giảm dần (mới nhất trước)
    timeline_items.sort(key=lambda x: x["timestamp"], reverse=True)
    return timeline_items


async def delete_consultation(
    db: AsyncSession, lead_id: int, consultation_id: int, current_user: models.User
):
    """(Admin only) Xóa một consultation và cập nhật lại trạng thái Lead."""
    try:
        # Lấy Lead (không cần eager load consultations ở đây)
        lead_query = select(models.Lead).where(models.Lead.id == lead_id)
        lead_result = await db.execute(lead_query)
        lead = lead_result.scalar_one_or_none()
        if not lead:
            raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

        # Lấy Consultation cần xóa
        consultation = await db.get(models.Consultation, consultation_id)
        if not consultation:
            raise ResourceNotFoundError(
                detail=f"Consultation with id {consultation_id} not found."
            )
        # Kiểm tra consultation thuộc đúng Lead
        if consultation.lead_id != lead_id:
            raise BadRequest(
                detail="Consultation does not belong to the specified lead."
            )

        # Kiểm tra quyền Admin
        if current_user.role != "admin":
            raise PermissionDeniedError(detail="Only admins can delete consultations.")

        # Lưu trạng thái cũ của Lead trước khi xóa consultation
        old_state = _get_current_lead_state(lead)

        # Xóa consultation
        await db.delete(consultation)
        log.info("Consultation marked for deletion", consultation_id=consultation_id)

        # Tìm consultation gần nhất còn lại để cập nhật trạng thái Lead
        remaining_consultations_query = (
            select(models.Consultation)
            .where(models.Consultation.lead_id == lead.id)
            .order_by(
                models.Consultation.consultation_date.desc(),
                models.Consultation.id.desc(),
            )  # Sắp xếp cả theo ID để ổn định
        )
        remaining_consultations_result = await db.execute(remaining_consultations_query)
        latest_consultation = remaining_consultations_result.scalars().first()

        new_status_id = None
        new_stage_id = None
        # Nếu còn consultation khác
        if latest_consultation and latest_consultation.consultation_status_id:
            latest_status = await db.get(
                models.ConsultationStatus, latest_consultation.consultation_status_id
            )
            if latest_status:
                new_status_id = latest_status.id
                new_stage_id = latest_status.stage_id
                log.info(
                    f"Reverting lead status to latest remaining consultation's status: {new_status_id}",
                    lead_id=lead_id,
                )
            else:
                log.warning(
                    f"Status '{latest_consultation.consultation_status_id}' not found for latest consultation {latest_consultation.id}",
                    lead_id=lead_id,
                )
        # Nếu không còn consultation nào, revert về trạng thái ban đầu
        else:
            initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
            initial_status = await db.get(models.ConsultationStatus, initial_status_id)
            if initial_status:
                new_status_id = initial_status.id
                new_stage_id = initial_status.stage_id
                log.info(
                    f"Reverting lead status to initial status: {new_status_id}",
                    lead_id=lead_id,
                )
            else:
                log.warning(
                    f"Initial status '{initial_status_id}' not found when reverting lead status.",
                    lead_id=lead_id,
                )
                # Gán giá trị an toàn nếu không tìm thấy status ban đầu
                new_status_id = "unknown"
                new_stage_id = None

        # Cập nhật trạng thái Lead
        lead.consultation_status_id = new_status_id
        lead.pipeline_stage_id = new_stage_id
        # Cập nhật status dựa trên ngữ cảnh
        if new_status_id is None:
            lead.status = "unknown"
        elif new_status_id == settings.DEFAULT_INITIAL_LEAD_STATUS_ID:
            lead.status = "new"
        # Giữ nguyên status hiện tại nếu đang revert về consultation khác
        db.add(lead)  # Đánh dấu lead là dirty

        # Lấy trạng thái mới sau khi cập nhật
        new_state = _get_current_lead_state(lead)

        # Ghi log lịch sử thay đổi trạng thái Lead do xóa consultation
        await _log_lead_state_change(
            db,
            lead,
            old_state,
            new_state,
            changed_by=current_user,
            reason=f"Admin deleted consultation ID {consultation_id}",
        )

        # Commit transaction (xóa consultation và cập nhật lead)
        await db.commit()
        log.info(
            "Consultation deleted and lead status reverted by admin",
            admin_id=current_user.id,
            lead_id=lead_id,
            consultation_id=consultation_id,
            new_lead_status=new_status_id,
        )
    except Exception as e:
        # Rollback nếu có lỗi
        await db.rollback()
        log.error(
            "Failed to delete consultation",
            lead_id=lead_id,
            consultation_id=consultation_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def process_officer_action(
    db: AsyncSession, lead_id: int, officer: models.User, action: str, reason: str
) -> models.Lead:
    """
    Xử lý hành động (reject/reassign) của Officer trên Lead, ghi logs và dispatch task.
    """
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task

    trigger_reassignment = False  # Biến cờ để dispatch task sau commit
    try:
        async with db.begin_nested():
            # Lấy Lead (có thể không cần full eager loading ở đây)
            lead_query = (
                select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            )
            lead_result = await db.execute(lead_query)
            lead = lead_result.scalar_one_or_none()
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Kiểm tra quyền: Officer phải được gán
            if lead.assigned_officer_id != officer.id:
                raise PermissionDeniedError(detail="You are not assigned to this lead.")

            log_method = ""  # Method cho AssignmentLog
            # (Đã xóa .strip() vì Pydantic xử lý)
            log_reason = reason if reason else "No reason provided by officer"

            # Lưu trạng thái cũ
            old_state = _get_current_lead_state(lead)
            new_state = old_state.copy()  # Tạo bản sao để sửa đổi

            if action == "reassign":
                new_state["status"] = settings.DEFAULT_REASSIGN_LEAD_STATUS
                new_state["assigned_officer_id"] = None
                # Giữ nguyên consult/stage
                new_state["consultation_status_id"] = lead.consultation_status_id
                new_state["pipeline_stage_id"] = lead.pipeline_stage_id
                lead.assigned_at = None
                # THÊM DÒNG NÀY:
                lead.assigned_officer = None  # <-- Set cả relationship thành None
                log_method = "officer_reassign"
                trigger_reassignment = True
                log.info(
                    "Officer requested lead reassignment",
                    lead_id=lead_id,
                    officer_id=officer.id,
                )

            elif action == "reject":
                lost_status_id = settings.DEFAULT_LOST_LEAD_STATUS_ID
                new_state["status"] = lost_status_id  # Chuyển status chính sang LOST
                log_method = "officer_reject"

                # Tìm ConsultationStatus tương ứng với LOST
                lost_consult_status = await db.get(
                    models.ConsultationStatus, lost_status_id
                )
                if lost_consult_status:
                    new_state["consultation_status_id"] = lost_consult_status.id
                    new_state["pipeline_stage_id"] = lost_consult_status.stage_id
                    log.info(
                        f"Setting consultation status and stage to LOST status '{lost_status_id}'",
                        lead_id=lead_id,
                    )
                else:
                    log.warning(
                        f"Consultation status '{lost_status_id}' (Lost) not found. Lead status set, but consult/stage might be inconsistent.",
                        lead_id=lead_id,
                    )
                    # Giữ nguyên consult/stage cũ hoặc set là None/unknown nếu cần
                    new_state["consultation_status_id"] = None
                    new_state["pipeline_stage_id"] = None

                log.info(
                    "Officer rejected lead", lead_id=lead_id, officer_id=officer.id
                )

            else:
                # Hành động không hợp lệ
                raise BadRequest(
                    detail=f"Invalid action: {action}. Allowed actions: 'reject', 'reassign'."
                )

            # Cập nhật các trường của Lead dựa trên new_state
            lead.status = new_state["status"]
            lead.consultation_status_id = new_state["consultation_status_id"]
            lead.pipeline_stage_id = new_state["pipeline_stage_id"]
            lead.assigned_officer_id = new_state["assigned_officer_id"]
            # assigned_at đã được xử lý trong 'reassign'

            # Ghi log lịch sử thay đổi trạng thái
            await _log_lead_state_change(
                db, lead, old_state, new_state, changed_by=officer, reason=log_reason
            )

            # Tạo AssignmentLog cho hành động này
            log_entry = models.AssignmentLog(
                lead_id=lead.id,
                officer_id=officer.id,  # Ghi lại officer thực hiện action
                method=log_method,
                reason=log_reason,
                timestamp=datetime.now(timezone.utc),
            )
            db.add(lead)  # Đánh dấu lead là dirty
            db.add(log_entry)

            # Commit transaction bên trong
            log.info(
                f"Processed officer action '{action}' within transaction",
                lead_id=lead_id,
            )

        # Dispatch Celery task SAU KHI transaction thành công (nếu cần)
        if trigger_reassignment:
            try:
                process_automatic_lead_assignment_task.delay(lead.id)
                log.info("Re-assignment task dispatched for lead", lead_id=lead.id)
            except Exception as e:
                log.error(
                    "Failed to dispatch Celery re-assignment task after officer action",
                    lead_id=lead.id,
                    error=str(e),
                    exc_info=True,
                )
                # Không rollback transaction vì hành động chính đã thành công

        # Trả về lead đã được tải đầy đủ
        return await get_lead_by_id(db, lead_id)

    except (
        PermissionDeniedError,
        BadRequest,
        ResourceNotFoundError,
    ) as e:  # Thêm ResourceNotFoundError
        # Rollback nếu lỗi validation hoặc không tìm thấy
        await db.rollback()
        log.warning(
            "Officer action failed validation or resource not found",
            lead_id=lead_id,
            officer_id=getattr(officer, "id", None),  # Lấy ID an toàn
            action=action,
            detail=getattr(e, "detail", str(e)),
        )
        raise e
    except Exception as e:
        # Rollback cho các lỗi không mong muốn khác
        await db.rollback()
        log.error(
            "Failed to process officer action",
            lead_id=lead_id,
            officer_id=getattr(officer, "id", None),
            action=action,
            error=str(e),
            exc_info=True,
        )
        raise e


async def revert_last_status(
    db: AsyncSession,
    lead_id: int,
    admin_user: models.User,
    reason: Optional[str] = None,  # Cho phép reason là None
) -> models.Lead:
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của Lead về trạng thái trước đó.
    """
    # (Pydantic/Form() nên xử lý .strip(), nhưng giữ ở đây để an toàn nếu gọi nội bộ)
    final_reason = reason.strip() if reason else "Admin reverted last status change"
    try:
        async with db.begin_nested():
            # Lấy Lead (không cần eager load quá nhiều)
            lead_query = (
                select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            )
            lead_result = await db.execute(lead_query)
            lead = lead_result.scalar_one_or_none()
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Tìm bản ghi lịch sử gần nhất
            last_history_entry = await db.scalar(
                select(models.LeadStatusHistory)
                .where(models.LeadStatusHistory.lead_id == lead_id)
                .order_by(
                    models.LeadStatusHistory.changed_at.desc(),
                    models.LeadStatusHistory.id.desc(),
                )  # Sắp xếp cả theo ID
                .limit(1)
            )

            if not last_history_entry:
                raise BadRequest(
                    detail="No status history found for this lead to revert."
                )

            # Trạng thái "đích" để hoàn tác về chính là trạng thái "cũ" trong bản ghi history
            if (
                last_history_entry.old_status is None
                and last_history_entry.old_consultation_status_id is None
                and last_history_entry.old_pipeline_stage_id is None
                and last_history_entry.old_assigned_officer_id is None
            ):
                raise BadRequest(
                    detail="Cannot revert to the initial state (before any status change recorded)."
                )

            # Lấy trạng thái hiện tại của Lead
            current_state = _get_current_lead_state(lead)

            # Xây dựng trạng thái cần hoàn tác về
            revert_to_state = {
                "status": last_history_entry.old_status,
                "consultation_status_id": last_history_entry.old_consultation_status_id,
                "pipeline_stage_id": last_history_entry.old_pipeline_stage_id,
                "assigned_officer_id": last_history_entry.old_assigned_officer_id,
            }

            # Kiểm tra xem có cần hoàn tác không
            if current_state == revert_to_state:
                log.info(
                    "Lead state is already the same as the previous recorded state, no revert needed.",
                    lead_id=lead_id,
                )
                # Trả về lead hiện tại nếu không có gì thay đổi
                return await get_lead_by_id(
                    db, lead_id
                )  # Vẫn gọi get_lead_by_id để đảm bảo eager loading

            log.info(
                "Admin reverting lead state",
                lead_id=lead_id,
                admin_id=admin_user.id,
                from_state=current_state,
                to_state=revert_to_state,
                reason=final_reason,
            )

            # Ghi log lịch sử cho hành động hoàn tác này
            await _log_lead_state_change(
                db,
                lead,
                old_state=current_state,  # Trạng thái cũ là trạng thái hiện tại
                new_state=revert_to_state,  # Trạng thái mới là trạng thái cần revert về
                changed_by=admin_user,
                reason=final_reason,
            )

            # Cập nhật các trường của Lead về trạng thái cũ
            lead.status = revert_to_state["status"]
            lead.consultation_status_id = revert_to_state["consultation_status_id"]
            lead.pipeline_stage_id = revert_to_state["pipeline_stage_id"]
            lead.assigned_officer_id = revert_to_state["assigned_officer_id"]

            # Cập nhật assigned_at nếu officer được khôi phục từ trạng thái không có officer
            if (
                revert_to_state["assigned_officer_id"] is not None
                and current_state["assigned_officer_id"] is None
            ):
                lead.assigned_at = datetime.now(timezone.utc)
            elif revert_to_state["assigned_officer_id"] is None:
                lead.assigned_at = (
                    None  # Xóa assigned_at nếu revert về trạng thái không gán
                )

            db.add(lead)  # Đánh dấu lead là dirty

            # Commit transaction
            log.info("Revert lead status completed within transaction", lead_id=lead_id)

    except (BadRequest, ResourceNotFoundError) as e:
        await db.rollback()
        log.warning(
            "Failed to revert lead status due to validation error",
            lead_id=lead_id,
            detail=getattr(e, "detail", str(e)),
        )
        raise e
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to revert lead status",
            lead_id=lead_id,
            admin_id=admin_user.id,
            error=str(e),
            exc_info=True,
        )
        raise e

    # Trả về lead đã được tải đầy đủ sau khi commit thành công
    return await get_lead_by_id(db, lead_id)