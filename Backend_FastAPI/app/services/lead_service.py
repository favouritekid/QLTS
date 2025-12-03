# app/services/lead_service.py
from datetime import (
    datetime, timezone  # ✅ SỬA LỖI: Thêm dấu cách (E231) và xóa cách thừa cuối dòng (W291)
)
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy import case, func, or_, select  # ✅ SỬA LỖI: Thêm 'desc' vào import và xóa comment
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
from ..services import pipeline_service, distribution_service
from ..core.status_mapping import sync_lead_status_from_consultation
from .status_helper import StatusHelper, AssignmentStatus

log = structlog.get_logger(__name__)


async def update_lead_next_activity(
    db: AsyncSession,
    lead_id: int
) -> None:
    """
    Cập nhật lead.next_activity_at = scheduled_at sớm nhất chưa gửi reminder.

    Logic:
    - Tìm MIN(scheduled_at) trong consultations WHERE:
      - lead_id = lead_id
      - reminder_sent = False
      - scheduled_at >= NOW (chỉ tương lai, không lấy quá khứ)
      - scheduled_at IS NOT NULL
    - Set lead.next_activity_at = giá trị tìm được (hoặc NULL nếu không có)

    Args:
        db: Database session
        lead_id: Lead ID cần update
    """
    from sqlalchemy import and_

    # Lấy lead
    lead = await db.get(models.Lead, lead_id)
    if not lead:
        log.warning("update_lead_next_activity: Lead not found", lead_id=lead_id)
        return

    # Tìm scheduled_at sớm nhất chưa reminder
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(func.min(models.Consultation.scheduled_at))
        .where(
            and_(
                models.Consultation.lead_id == lead_id,
                models.Consultation.scheduled_at.isnot(None),
                models.Consultation.scheduled_at >= now,
                models.Consultation.reminder_sent == False,
            )
        )
    )
    earliest_scheduled = result.scalar_one_or_none()

    # Update lead
    lead.next_activity_at = earliest_scheduled

    log.debug(
        "Updated lead.next_activity_at",
        lead_id=lead_id,
        next_activity_at=earliest_scheduled.isoformat() if earliest_scheduled else None,
    )


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
        "assignment_status": getattr(lead, "assignment_status", "pending"),
        "consultation_status_id": lead.consultation_status_id,
        "pipeline_stage_id": lead.pipeline_stage_id,
        "assigned_officer_id": lead.assigned_officer_id,
    }


async def get_lead_by_id(db: AsyncSession, lead_id: int, include_deleted: bool = False) -> models.Lead:
    """
    Lấy chi tiết Lead bằng ID (Detail View).
    Hàm này giữ nguyên eager loading đầy đủ
    vì nó cần thiết cho Timeline và Insights.

    Args:
        db: Database session
        lead_id: Lead ID to fetch
        include_deleted: If True, include soft-deleted leads (default: False)
    """
    query = (
        select(models.Lead)
        .options(
            selectinload(models.Lead.offering).options(
                selectinload(models.ProgramOffering.program)  # Eager load program for name display
            ),
            selectinload(models.Lead.unit).options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.major_programs),
            ),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
            selectinload(models.Lead.application).options(
                selectinload(models.Application.officer)
            ),  # Fix MissingGreenlet: Eager load application and its officer
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

    # Filter deleted leads unless explicitly requested
    if not include_deleted:
        query = query.where(models.Lead.deleted_at.is_(None))

    result = await db.execute(query)
    lead = result.scalar_one_or_none()
    if not lead:
        raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
    return lead

async def get_lead_by_id_shallow(db: AsyncSession, lead_id: int, include_deleted: bool = False) -> models.Lead:
    """
    Lấy chi tiết Lead (Shallow View - Nhanh).
    Chỉ Eager Load các quan hệ 1-1 cần thiết cho List/Detail View.

    Args:
        db: Database session
        lead_id: Lead ID to fetch
        include_deleted: If True, include soft-deleted leads (default: False)
    """
    query = (
        select(models.Lead)
        .options(
            selectinload(models.Lead.offering).options(
                selectinload(models.ProgramOffering.program)  # Eager load program for name display
            ),
            selectinload(models.Lead.unit), # <--- Load unit (thường là cần)
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
            selectinload(models.Lead.application).options(
                selectinload(models.Application.officer)
            ),  # Fix MissingGreenlet: Eager load application and its officer
        )
        .where(models.Lead.id == lead_id)
    )

    # Filter deleted leads unless explicitly requested
    if not include_deleted:
        query = query.where(models.Lead.deleted_at.is_(None))

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
    # Filter out soft-deleted leads (always applied)
    filters.append(models.Lead.deleted_at.is_(None))
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

    # === Áp dụng sắp xếp (Bubble Up Logic) ===
    # Priority sorting: Overdue/Today activities bubble up to top
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Create priority weight using CASE statement:
    # Priority 0: Overdue (next_activity_at <= now) - Most urgent
    # Priority 1: Today (next_activity_at is today but not yet due)
    # Priority 2: Future or NULL - Less urgent
    activity_priority = case(
        (models.Lead.next_activity_at <= now, 0),  # Overdue
        (models.Lead.next_activity_at.between(today_start, today_end), 1),  # Today
        else_=2  # Future or NULL
    )

    # Default sort with bubble-up: priority first, then by sort_column
    sort_column = getattr(models.Lead, sort_by, models.Lead.created_at)

    if order.lower() == "desc":
        leads_query = base_query.order_by(
            activity_priority.asc(),  # Always prioritize urgent items first
            models.Lead.next_activity_at.asc().nullslast(),  # Oldest/most urgent first
            sort_column.desc()
        )
    else:
        leads_query = base_query.order_by(
            activity_priority.asc(),  # Always prioritize urgent items first
            models.Lead.next_activity_at.asc().nullslast(),  # Oldest/most urgent first
            sort_column.asc()
        )

    # === Áp dụng eager loading tối ưu và pagination ===
    leads_query = (
        leads_query.options(
            selectinload(models.Lead.offering).options(
                selectinload(models.ProgramOffering.program)  # Eager load program for name display
            ),
            selectinload(models.Lead.unit).options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.major_programs),
            ),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
            selectinload(models.Lead.application).options(
                selectinload(models.Application.officer)
            ),  # Fix MissingGreenlet: Eager load application and its officer
        )
        .offset(skip)
        .limit(limit)
    )

    # === Thực thi query lấy dữ liệu ===
    leads_result = await db.execute(leads_query)
    leads = leads_result.scalars().unique().all()

    return total_count, leads


async def create_lead(
    db: AsyncSession,
    lead_in: schemas.LeadCreate,
    created_by: models.User = None
) -> Tuple[models.Lead, Callable]:
    """
    Tạo Lead mới với role-based logic.

    Role-based behavior:
    - Admin: Can set any unit_id, can assign to any officer or use auto-assignment
    - Manager: Can assign to officers in their unit or use auto-assignment
    - Officer: Auto-assigned to themselves, unit forced to their unit

    Args:
        db: Database session
        lead_in: Lead creation data
        created_by: User creating the lead (determines role-based behavior)

    Returns:
        Created Lead model

    Raises:
        DuplicateResourceError: If lead with same email/phone exists in unit
        PermissionDeniedError: If user tries to assign to officer outside their scope
    """
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task
    from datetime import datetime, timezone

    try:
        # === ROLE-BASED PREPROCESSING ===
        create_data = lead_in.model_dump()
        direct_assignment_officer_id = None  # Will be set if direct assignment is needed
        skip_auto_assignment = False
        unit_already_distributed = False  # Flag to skip second distribution call

        if created_by:
            user_role = created_by.role

            if user_role == "officer":
                # Officer: Force unit to their unit, auto-assign to themselves
                create_data["unit_id"] = created_by.unit_id
                direct_assignment_officer_id = created_by.id
                skip_auto_assignment = True
                log.info(
                    "Officer creating lead - will be assigned to themselves",
                    officer_id=created_by.id,
                    unit_id=created_by.unit_id
                )

            elif user_role == "manager":
                # Manager: Always use their unit
                create_data["unit_id"] = created_by.unit_id
                # Can choose officer in their unit or use auto-assignment
                if create_data.get("assigned_officer_id"):
                    # Validate officer belongs to manager's unit
                    officer = await db.get(models.User, create_data["assigned_officer_id"])
                    if not officer or officer.unit_id != created_by.unit_id:
                        raise PermissionDeniedError(
                            detail="Manager can only assign leads to officers in their unit"
                        )
                    if officer.role != "officer":
                        raise PermissionDeniedError(
                            detail="Can only assign leads to users with 'officer' role"
                        )
                    direct_assignment_officer_id = create_data["assigned_officer_id"]
                    skip_auto_assignment = True
                    log.info(
                        "Manager directly assigning lead to officer",
                        manager_id=created_by.id,
                        officer_id=direct_assignment_officer_id
                    )
                # If no officer specified, use auto-assignment (Celery)

            elif user_role == "admin":
                # Admin: unit_id can be auto-determined from offering distribution
                # If offering_id is provided, try to get unit from distribution config FIRST
                if create_data.get("offering_id") and not create_data.get("unit_id"):
                    # Try to get target unit from distribution config
                    target_unit_id = await distribution_service.get_target_unit_for_offering(
                        db,
                        offering_id=create_data["offering_id"],
                        fallback_unit_id=None  # No fallback - we want to know if config exists
                    )
                    if target_unit_id:
                        create_data["unit_id"] = target_unit_id
                        unit_already_distributed = True  # Skip second distribution call
                        log.info(
                            "Admin: unit auto-determined from offering distribution",
                            offering_id=create_data["offering_id"],
                            unit_id=target_unit_id
                        )
                    else:
                        raise BadRequest(
                            detail="Cannot determine unit: No distribution config for this offering. Please select a unit manually."
                        )

                # If still no unit_id after trying offering distribution, error
                if not create_data.get("unit_id"):
                    raise BadRequest(
                        detail="unit_id is required when no offering_id is provided"
                    )

                # Admin: Full control - can assign to any officer or use auto
                if create_data.get("assigned_officer_id"):
                    # Validate officer exists and has correct role
                    officer = await db.get(models.User, create_data["assigned_officer_id"])
                    if not officer:
                        raise ResourceNotFoundError(
                            detail=f"Officer with id {create_data['assigned_officer_id']} not found"
                        )
                    if officer.role != "officer":
                        raise PermissionDeniedError(
                            detail="Can only assign leads to users with 'officer' role"
                        )
                    direct_assignment_officer_id = create_data["assigned_officer_id"]
                    skip_auto_assignment = True
                    log.info(
                        "Admin directly assigning lead to officer",
                        admin_id=created_by.id,
                        officer_id=direct_assignment_officer_id
                    )
                # If no officer specified, use auto-assignment (Celery)

        # Remove assigned_officer_id from create_data (it's not a Lead model field for creation)
        create_data.pop("assigned_officer_id", None)

        # === DUPLICATE CHECK ===
        # Kiểm tra trùng lặp email hoặc phone trong cùng unit
        # Build phone conditions
        phone_conditions = [models.Lead.phone == lead_in.phone]
        if lead_in.phone2:
            phone_conditions.append(models.Lead.phone == lead_in.phone2)
            phone_conditions.append(models.Lead.phone2 == lead_in.phone)
            phone_conditions.append(models.Lead.phone2 == lead_in.phone2)

        # Build email condition - only check if email is provided
        email_condition = models.Lead.email == lead_in.email if lead_in.email else None

        # Build OR conditions
        if email_condition is not None:
            duplicate_conditions = or_(email_condition, *phone_conditions)
        else:
            duplicate_conditions = or_(*phone_conditions)

        existing_lead_query = (
            select(models.Lead)
            .where(
                models.Lead.unit_id == create_data["unit_id"],
                models.Lead.deleted_at.is_(None),  # Exclude soft-deleted
                duplicate_conditions
            )
            .with_for_update()  # Khóa để tránh race condition khi tạo
        )
        existing_lead_result = await db.execute(existing_lead_query)
        existing_lead = existing_lead_result.scalar_one_or_none()
        if existing_lead:
            # Determine which field caused the duplicate
            if lead_in.email and existing_lead.email == lead_in.email:
                raise DuplicateResourceError(
                    detail="Lead with this email already exists in the unit."
                )
            else:
                raise DuplicateResourceError(
                    detail="Lead with this phone number already exists in the unit."
                )

        # === NEW FEATURE: Shared Offering Distribution ===
        # If Lead has offering_id, determine target unit via distribution config
        # This overrides the unit_id provided by user (if any offering-based routing exists)
        # SKIP distribution if officer/manager is creating lead (they keep lead in their unit)
        # SKIP if unit was already determined via distribution in role preprocessing
        if create_data.get("offering_id") and not skip_auto_assignment and not unit_already_distributed:
            original_unit_id = create_data.get("unit_id")
            target_unit_id = await distribution_service.get_target_unit_for_offering(
                db,
                offering_id=create_data["offering_id"],
                fallback_unit_id=original_unit_id  # Use provided unit as fallback
            )

            # Override unit_id with distribution result
            if target_unit_id != original_unit_id:
                log.info(
                    "Lead unit routed via Offering Distribution",
                    offering_id=create_data["offering_id"],
                    original_unit_id=original_unit_id,
                    routed_unit_id=target_unit_id,
                    routing_rule="WeightedRoundRobin"
                )
                create_data["unit_id"] = target_unit_id

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

        # Lấy trạng thái ban đầu từ DB (database-driven, không hardcode ID)
        initial_status = await StatusHelper.get_initial_status(db)

        # Trạng thái "trước khi tạo"
        old_state = _get_current_lead_state(models.Lead())  # Trạng thái rỗng

        # Gán trạng thái ban đầu cho Lead mới
        if initial_status:
            await StatusHelper.sync_lead_status(db_lead, initial_status)
        else:
            # Ghi log cảnh báo nếu không tìm thấy status mặc định
            log.warning(
                "Initial consultation status not found during lead creation."
            )
            # Gán giá trị mặc định an toàn
            db_lead.status = "new"
            db_lead.consultation_status_id = None
            db_lead.pipeline_stage_id = None

        # Set initial assignment status
        StatusHelper.set_assignment_status(db_lead, AssignmentStatus.PENDING)

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

        # === DIRECT ASSIGNMENT (if specified) ===
        # If direct assignment is needed, set it before commit
        if direct_assignment_officer_id:
            db_lead.assigned_officer_id = direct_assignment_officer_id
            db_lead.assigned_at = datetime.now(timezone.utc)
            # Update assignment_status to "assigned" (workflow status)
            StatusHelper.set_assignment_status(db_lead, AssignmentStatus.ASSIGNED)
            log.info(
                "Lead directly assigned to officer",
                lead_id=db_lead.id,
                officer_id=direct_assignment_officer_id,
                assignment_type="direct",
                assignment_status=db_lead.assignment_status
            )

        # === ✅ CRITICAL: Load relationships BEFORE flush to avoid greenlet errors ===
        # Must load offering while we're still in transaction context
        # Store relationship references immediately to avoid triggering lazy loads
        offering_name = ""
        if db_lead.offering_id:
            await db.refresh(db_lead, ["offering"])
            offering_obj = db_lead.offering  # Store reference immediately

            if offering_obj is not None:
                # Check if offering has program_id before attempting to load
                if hasattr(offering_obj, 'program_id') and offering_obj.program_id:
                    await db.refresh(offering_obj, ["program"])
                    program_obj = offering_obj.program  # Store reference

                    if program_obj is not None:
                        offering_name = f"{program_obj.name} - {offering_obj.offering_type}"
                    else:
                        offering_name = offering_obj.offering_type
                else:
                    offering_name = offering_obj.offering_type

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_lead)

        # ✅ Create post-commit callback with all post-commit actions
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "New lead created successfully", lead_id=db_lead.id, email=db_lead.email
            )

            # === ✅ REFACTOR: Dispatch LEAD_CREATED notification ===
            try:
                from ..core.events import SystemEvents
                from .notification_dispatcher import dispatch

                await dispatch(
                    db=db,
                    event=SystemEvents.LEAD_CREATED,
                    payload={
                        "lead_id": db_lead.id,
                        "unit_id": db_lead.unit_id,
                        "lead_name": db_lead.full_name or "Unknown",
                        "source": db_lead.source or "Unknown",
                        "actor_id": created_by.id if created_by else 0
                    },
                    dedupe_key=f"lead_created:{db_lead.id}"
                )
                log.info("Lead creation notification dispatched", lead_id=db_lead.id)
            except Exception as e:
                log.warning("Failed to dispatch lead_created notification", lead_id=db_lead.id, error=str(e))

            # === POST-COMMIT ACTIONS ===
            if skip_auto_assignment:
                # Direct assignment was done - dispatch LEAD_ASSIGNED notification
                if direct_assignment_officer_id:
                    try:
                        from ..core.events import SystemEvents
                        from .notification_dispatcher import dispatch

                        await dispatch(
                            db=db,
                            event=SystemEvents.LEAD_ASSIGNED,
                            payload={
                                "lead_id": db_lead.id,
                                "officer_id": direct_assignment_officer_id,
                                "actor_id": created_by.id if created_by else 0,
                                "lead_name": db_lead.full_name or "Unknown",
                                "lead_phone": db_lead.phone or "",
                                "offering_name": offering_name
                            },
                            dedupe_key=f"lead_assigned:{db_lead.id}:{direct_assignment_officer_id}"
                        )
                        log.info(
                            "Direct assignment notification dispatched",
                            lead_id=db_lead.id,
                            officer_id=direct_assignment_officer_id
                        )
                    except Exception as e:
                        log.warning(
                            "Failed to dispatch direct assignment notification",
                            lead_id=db_lead.id,
                            error=str(e)
                        )
            else:
                # Dispatch Celery task for auto-assignment
                try:
                    process_automatic_lead_assignment_task.delay(db_lead.id)
                    log.info("Auto-assignment task dispatched successfully", lead_id=db_lead.id)
                except Exception as e:
                    log.error(
                        "Failed to dispatch Celery auto-assignment task",
                        lead_id=db_lead.id,
                        error=str(e),
                        exc_info=True,
                    )

        # Get fully loaded lead object for return
        lead = await get_lead_by_id(db, db_lead.id)
        return lead, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to create lead",
            lead_email=lead_in.email,
            error=str(e),
            exc_info=True,
        )
        raise e


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

            # Kiểm tra trùng lặp phone/phone2 nếu được cập nhật
            phone_changed = "phone" in update_data and update_data["phone"] != db_lead.phone
            phone2_changed = "phone2" in update_data and update_data["phone2"] != db_lead.phone2

            if phone_changed or phone2_changed:
                # Determine the new phone values to check
                new_phone = update_data.get("phone", db_lead.phone)
                new_phone2 = update_data.get("phone2", db_lead.phone2)

                # Build phone duplicate check conditions
                phone_conditions = []
                if new_phone:
                    phone_conditions.append(models.Lead.phone == new_phone)
                if new_phone2:
                    phone_conditions.append(models.Lead.phone == new_phone2)
                    phone_conditions.append(models.Lead.phone2 == new_phone)
                    phone_conditions.append(models.Lead.phone2 == new_phone2)

                if phone_conditions:
                    existing_lead_query = select(models.Lead).where(
                        models.Lead.unit_id == db_lead.unit_id,  # Trong cùng unit
                        models.Lead.id != lead_id,  # Loại trừ chính lead này
                        models.Lead.deleted_at.is_(None),  # Exclude soft-deleted
                        or_(*phone_conditions)
                    )
                    existing_lead_result = await db.execute(existing_lead_query)
                    if existing_lead_result.scalar_one_or_none():
                        raise DuplicateResourceError(
                            detail="Another lead with this phone number already exists in the unit."
                        )

            # === NEW FEATURE: Auto-Reassign on Offering Change ===
            # Track offering_id change before applying updates
            old_offering_id = db_lead.offering_id
            offering_changed = "offering_id" in update_data and update_data["offering_id"] != old_offering_id

            # Check if scoring-related fields are being updated
            scoring_fields = ["education_level", "gpa", "source", "location"]
            should_recalculate_score = any(field in update_data for field in scoring_fields)

            # Cập nhật các trường thông thường
            for key, value in update_data.items():
                # Xử lý consultation_status_id riêng (processed separately below)
                # Xử lý offering_id riêng (processed for auto-reassign below)
                if key not in ["consultation_status_id", "offering_id"]:
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
                current_status_id = db_lead.consultation_status_id
                
                # Chỉ kiểm tra nếu trạng thái thực sự thay đổi
                if new_status_id and new_status_id != current_status_id:
                    # Nếu current_status là None (Lead mới), thường cho phép gán bất kỳ
                    if current_status_id:
                        # Gọi service để kiểm tra trong bảng AllowedTransition
                        is_valid = await pipeline_service.validate_status_transition(
                            db, from_status_id=current_status_id, to_status_id=new_status_id
                        )
                        
                        if not is_valid:
                            # Chỉ cho phép Admin bypass quy tắc này (Tùy chọn)
                            if updated_by.role != "admin":
                                raise BadRequest(
                                    detail=f"Không thể chuyển trạng thái từ '{current_status_id}' sang '{new_status_id}'. Quy trình không cho phép (Allowed Transitions)."
                                )
                            else:
                                # ✅ IMPROVED: Log with more context
                                # Note: Universal status sẽ pass validation, nên không vào đây
                                new_status_obj = await db.get(models.ConsultationStatus, new_status_id)
                                log.warning(
                                    "Admin bypassed transition rule",
                                    admin_username=updated_by.username,
                                    from_status=current_status_id,
                                    to_status=new_status_id,
                                    to_status_name=new_status_obj.name if new_status_obj else "Unknown",
                                    is_universal=new_status_obj.is_universal if new_status_obj else False,
                                    reason="Admin override - no explicit transition rule exists",
                                )

                    # Logic gán status mới (Giữ nguyên)
                    new_status_obj = await db.get(models.ConsultationStatus, new_status_id)
                    if not new_status_obj:
                        raise BadRequest(detail=f"Consultation status '{new_status_id}' not found.")
                    
                    db_lead.consultation_status_id = new_status_id
                    db_lead.pipeline_stage_id = new_status_obj.stage_id
                elif new_status_id is None:
                     # Trường hợp clear status (hiếm)
                     db_lead.consultation_status_id = None
                     db_lead.pipeline_stage_id = None  # Hoặc một trạng thái mặc định khác

            # === NEW FEATURE: Auto-Reassign when Offering Changes ===
            # If offering_id changed, re-route Lead to new Unit and reset assignment
            reassignment_triggered = False
            if offering_changed:
                new_offering_id = update_data["offering_id"]

                log.info(
                    "Offering changed on Lead update - checking for unit change",
                    lead_id=lead_id,
                    old_offering_id=old_offering_id,
                    new_offering_id=new_offering_id,
                    current_unit_id=db_lead.unit_id
                )

                # Apply offering_id update
                db_lead.offering_id = new_offering_id

                # Determine new target unit via distribution
                if new_offering_id:
                    new_target_unit_id = await distribution_service.get_target_unit_for_offering(
                        db,
                        offering_id=new_offering_id,
                        fallback_unit_id=db_lead.unit_id  # Current unit as fallback
                    )
                else:
                    # Offering removed - keep current unit
                    new_target_unit_id = db_lead.unit_id

                # Check if unit actually changed (territory conflict)
                if new_target_unit_id != db_lead.unit_id:
                    old_unit_id = db_lead.unit_id
                    old_officer_id = db_lead.assigned_officer_id

                    log.warning(
                        "Offering change causes Unit change - Auto-reassigning Lead",
                        lead_id=lead_id,
                        old_offering_id=old_offering_id,
                        new_offering_id=new_offering_id,
                        old_unit_id=old_unit_id,
                        new_unit_id=new_target_unit_id,
                        old_officer_id=old_officer_id,
                        reason="territorial_conflict"
                    )

                    # === ATOMIC REASSIGNMENT TRANSACTION ===
                    # 1. Update unit_id
                    db_lead.unit_id = new_target_unit_id

                    # 2. Reset assignment fields
                    db_lead.assigned_officer_id = None
                    db_lead.assigned_at = None

                    # 3. Set assignment_status to pending (waiting for new assignment)
                    StatusHelper.set_assignment_status(db_lead, AssignmentStatus.PENDING)

                    # 4. Create system AssignmentLog
                    reassignment_log = models.AssignmentLog(
                        lead_id=lead_id,
                        officer_id=updated_by.id,  # Log who triggered the change
                        method="system_auto_reassign",
                        reason=f"Offering changed from #{old_offering_id} to #{new_offering_id}. "
                               f"Unit changed from #{old_unit_id} to #{new_target_unit_id}. "
                               f"Previous officer: {old_officer_id}",
                        timestamp=datetime.now(timezone.utc)
                    )
                    db.add(reassignment_log)

                    reassignment_triggered = True

                    log.info(
                        "Lead auto-reassignment completed",
                        lead_id=lead_id,
                        new_unit_id=new_target_unit_id,
                        old_officer_id=old_officer_id,
                        assignment_status=db_lead.assignment_status
                    )

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

        # === POST-COMMIT ACTIONS (Only if transaction succeeded) ===

        # 1. Dispatch Celery task for auto-assignment if reassignment was triggered
        if reassignment_triggered:
            try:
                from ..celery_utils import process_automatic_lead_assignment_task
                process_automatic_lead_assignment_task.delay(lead_id)
                log.info(
                    "Auto-assignment task dispatched after offering change",
                    lead_id=lead_id
                )
            except Exception as e:
                log.error(
                    "Failed to dispatch auto-assignment task after offering change",
                    lead_id=lead_id,
                    error=str(e),
                    exc_info=True
                )
                # Don't fail the request - assignment can be done manually

            # 2. Dispatch notification for lead reassignment
            try:
                from .notification_dispatcher import dispatch
                from ..core.events import SystemEvents
                await dispatch(
                    db=db,
                    event=SystemEvents.LEAD_REASSIGNED,
                    payload={
                        "lead_id": lead_id,
                        "old_officer_id": old_officer_id,  # type: ignore
                        "new_officer_id": None,  # Will be assigned by auto-assignment
                        "old_unit_id": old_unit_id,  # type: ignore
                        "new_unit_id": new_target_unit_id,  # type: ignore
                        "actor_id": updated_by.id,
                        "reason": f"Offering changed from #{old_offering_id} to #{new_offering_id}",  # type: ignore
                        "user_ids": [old_officer_id] if old_officer_id else [],  # Notify old officer
                    }
                )
                log.info(
                    "Lead reassignment notification dispatched",
                    lead_id=lead_id
                )
            except Exception as e:
                log.error(
                    "Failed to dispatch lead reassignment notification",
                    lead_id=lead_id,
                    error=str(e),
                    exc_info=True
                )
                # Don't fail the request - notifications are non-critical

        # Trả về lead đã được tải đầy đủ (bao gồm relations)
        # Gọi lại get_lead_by_id để đảm bảo dữ liệu mới nhất và relations
        return await get_lead_by_id(db, lead_id)


async def add_consultation(
    db: AsyncSession, lead_id: int, officer_id: int, data: schemas.ConsultationCreate
) -> models.Consultation:
    """
    Thêm consultation mới, cập nhật trạng thái Lead và ghi log lịch sử.

    CONCURRENCY SAFE: Uses SELECT ... FOR UPDATE to prevent race conditions
    when multiple requests try to update the same lead's pipeline_stage.
    """
    async with db.begin_nested():
        try:
            # ✅ FIX: Row-level lock để prevent race condition
            # Sử dụng with_for_update() thay vì get_lead_by_id() đơn thuần
            stmt = (
                select(models.Lead)
                .options(
                    selectinload(models.Lead.assigned_officer),
                    selectinload(models.Lead.pipeline_stage),
                    selectinload(models.Lead.consultation_status),
                )
                .where(models.Lead.id == lead_id)
                .where(models.Lead.deleted_at.is_(None))
                .with_for_update()  # ROW LOCK - prevents concurrent modifications
            )
            result = await db.execute(stmt)
            lead = result.scalar_one_or_none()

            if not lead:
                raise ResourceNotFoundError(f"Lead with id {lead_id} not found")
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

            # ✅ NEW: Chỉ cập nhật pipeline nếu status.updates_pipeline = True
            if new_status.updates_pipeline:
                # Cập nhật trạng thái Lead theo status mới của consultation
                lead.consultation_status_id = new_status.id
                lead.pipeline_stage_id = new_status.stage_id
                # ✅ Sync lead.status từ consultation_status (Hybrid Approach)
                sync_lead_status_from_consultation(lead, new_status)

                log.info(
                    "Updating lead pipeline",
                    lead_id=lead_id,
                    old_status=old_state.get("consultation_status_id"),
                    new_status=new_status.id,
                    status_name=new_status.name
                )
            else:
                # Universal status - chỉ ghi nhận consultation, không thay đổi pipeline
                log.info(
                    "Universal status - không update pipeline",
                    lead_id=lead_id,
                    status_id=new_status.id,
                    status_name=new_status.name,
                    is_universal=new_status.is_universal
                )

            # Chuẩn bị dữ liệu để tạo Consultation
            create_consult_data = data.model_dump(exclude={"status_id", "consultation_date"})
            # (Đã xóa .strip() vì Pydantic xử lý)

            # Handle consultation_date: use provided value or default to NOW
            consultation_date = data.consultation_date or datetime.now(timezone.utc)

            # Tạo đối tượng Consultation mới
            new_consultation = models.Consultation(
                lead_id=lead_id,
                officer_id=officer_id,
                consultation_status_id=new_status.id,  # Gán status ID cho consultation
                consultation_date=consultation_date,
                **create_consult_data,
            )

            # Thêm các đối tượng vào session
            db.add(new_consultation)
            if new_status.updates_pipeline:
                db.add(lead)  # Chỉ đánh dấu lead dirty nếu có thay đổi

            # Lấy trạng thái Lead mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái Lead (chỉ khi có thay đổi thực sự)
            if new_status.updates_pipeline and old_state != new_state:
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

            # ✅ Quick Disposition: Cập nhật next_activity_at dựa trên tất cả consultations
            if data.scheduled_at:
                await update_lead_next_activity(db, lead_id)

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

    ✅ REFACTORED: Now uses notification_dispatcher instead of direct socket calls.
    This ensures notifications are persisted to database AND sent via Socket.IO/Email.
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
            # Cập nhật assignment_status thành 'assigned'
            StatusHelper.set_assignment_status(lead, AssignmentStatus.ASSIGNED)

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
            # Commit nested transaction (auto-commits on context exit)

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

    # === ✅ REFACTOR: Dispatch notification after transaction commit ===
    try:
        from ..core.events import SystemEvents
        from .notification_dispatcher import dispatch

        # Load lead relationships for notification payload
        await db.refresh(lead, ["offering", "unit"])

        # Prepare notification payload according to LEAD_ASSIGNED schema
        notification_payload = {
            "lead_id": lead.id,
            "officer_id": officer.id,
            "actor_id": assigner.id,
            "lead_name": lead.full_name or "Unknown",
            "lead_phone": lead.phone or "",
            "offering_name": f"{lead.offering.program.name} - {lead.offering.offering_type}" if lead.offering and lead.offering.program else (lead.offering.offering_type if lead.offering else "N/A")
        }

        # Dispatch notification (saves to DB + sends via Socket.IO/Email)
        await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNED,
            payload=notification_payload,
            dedupe_key=f"lead_assigned:{lead.id}:{officer.id}"
        )

        log.info(
            "Manual assignment notification dispatched",
            lead_id=lead.id,
            officer_id=officer.id,
            assigner_id=assigner.id
        )
    except Exception as e:
        # Log but don't fail - lead assignment already succeeded
        log.error(
            "Failed to dispatch assignment notification (lead still assigned successfully)",
            lead_id=lead.id,
            officer_id=officer.id,
            error=str(e),
            exc_info=True
        )

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
    """
    Xóa một consultation và cập nhật lại trạng thái Lead.

    Permission Rules:
    - Admin: Can delete any consultation
    - Officer: Can only delete the most recent consultation (prevents breaking consultation chain)

    CONCURRENCY SAFE: Uses SELECT ... FOR UPDATE to prevent race conditions
    when multiple requests try to update the same lead's pipeline_stage.
    """
    async with db.begin_nested():
        try:
            # ✅ FIX: Row-level lock để prevent race condition
            lead_query = (
                select(models.Lead)
                .where(models.Lead.id == lead_id)
                .where(models.Lead.deleted_at.is_(None))
                .with_for_update()  # ROW LOCK - prevents concurrent modifications
            )
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

            # Kiểm tra quyền
            if current_user.role == "admin":
                # Admin có quyền xóa bất kỳ consultation nào
                pass
            elif current_user.role == "officer":
                # Officer chỉ được xóa consultation mới nhất
                # Tìm consultation mới nhất của Lead này
                latest_consultation_query = (
                    select(models.Consultation)
                    .where(models.Consultation.lead_id == lead_id)
                    .order_by(
                        models.Consultation.consultation_date.desc(),
                        models.Consultation.id.desc(),
                    )
                )
                latest_consultation_result = await db.execute(latest_consultation_query)
                latest_consultation = latest_consultation_result.scalars().first()

                if not latest_consultation or latest_consultation.id != consultation_id:
                    raise PermissionDeniedError(
                        detail="Officers can only delete the most recent consultation to maintain consultation chain integrity."
                    )

                # Kiểm tra officer có được gán cho Lead này không
                if lead.assigned_officer_id != current_user.id:
                    raise PermissionDeniedError(
                        detail="You are not assigned to this lead."
                    )
            else:
                # Các role khác không có quyền xóa consultation
                raise PermissionDeniedError(detail="You don't have permission to delete consultations.")

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
            latest_remaining = remaining_consultations_result.scalars().first()

            new_status_id = None
            new_stage_id = None
            revert_status_obj = None  # ConsultationStatus object for sync

            # Nếu còn consultation khác
            if latest_remaining and latest_remaining.consultation_status_id:
                latest_status = await db.get(
                    models.ConsultationStatus, latest_remaining.consultation_status_id
                )
                if latest_status:
                    new_status_id = latest_status.id
                    new_stage_id = latest_status.stage_id
                    revert_status_obj = latest_status
                    log.info(
                        f"Reverting lead status to latest remaining consultation's status: {new_status_id}",
                        lead_id=lead_id,
                    )
                else:
                    log.warning(
                        f"Status '{latest_remaining.consultation_status_id}' not found for latest consultation {latest_remaining.id}",
                        lead_id=lead_id,
                    )
            # Nếu không còn consultation nào, revert về trạng thái ban đầu
            else:
                initial_status = await StatusHelper.get_initial_status(db)
                if initial_status:
                    new_status_id = initial_status.id
                    new_stage_id = initial_status.stage_id
                    revert_status_obj = initial_status
                    log.info(
                        "Reverting lead status to initial status",
                        lead_id=lead_id,
                        status_id=new_status_id,
                    )
                else:
                    log.warning(
                        "Initial status not found when reverting lead status.",
                        lead_id=lead_id,
                    )
                    # Gán giá trị an toàn nếu không tìm thấy status ban đầu
                    new_status_id = None
                    new_stage_id = None

            # Cập nhật trạng thái Lead
            lead.consultation_status_id = new_status_id
            lead.pipeline_stage_id = new_stage_id
            # ✅ Sync lead.status từ consultation_status (Hybrid Approach)
            if revert_status_obj:
                sync_lead_status_from_consultation(lead, revert_status_obj)
            else:
                # Fallback khi không tìm thấy status object
                lead.status = "new"
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
                reason=f"Deleted consultation ID {consultation_id}",
            )

            # ✅ Quick Disposition: Cập nhật next_activity_at sau khi xóa consultation
            await update_lead_next_activity(db, lead_id)

            # Store values for use after transaction
            _lead_id = lead_id
            _consultation_id = consultation_id
            _officer_id = lead.assigned_officer_id
            _new_status_id = new_status_id

        except Exception as e:
            # Rollback tự động by begin_nested context
            log.error(
                "Failed to delete consultation",
                lead_id=lead_id,
                consultation_id=consultation_id,
                error=str(e),
                exc_info=True,
            )
            raise e

    # After successful transaction, log and emit events
    log.info(
        "Consultation deleted and lead status reverted",
        user_id=current_user.id,
        lead_id=_lead_id,
        consultation_id=_consultation_id,
        new_lead_status=_new_status_id,
    )

    # Dispatch notification for consultation deleted
    try:
        from .notification_dispatcher import dispatch
        from ..core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.CONSULTATION_DELETED,
            payload={
                "consultation_id": _consultation_id,
                "lead_id": _lead_id,
                "officer_id": _officer_id,
                "actor_id": current_user.id,
            }
        )
    except Exception as e:
        log.error(
            "Failed to dispatch consultation deleted notification",
            lead_id=_lead_id,
            consultation_id=_consultation_id,
            error=str(e),
            exc_info=True
        )


async def update_consultation(
    db: AsyncSession,
    lead_id: int,
    consultation_id: int,
    consultation_in: schemas.ConsultationUpdate,
    current_user: models.User,
):
    """
    Cập nhật một consultation.

    Permission Rules:
    - Admin: Can update any consultation
    - Officer: Can only update the most recent consultation (prevents breaking consultation chain)

    Business Logic:
    - If status_id is changed, update lead's consultation_status_id and pipeline_stage_id
    - Log the change in LeadStatusHistory if lead status changes
    - Emit Socket.IO event for real-time updates

    CONCURRENCY SAFE: Uses SELECT ... FOR UPDATE to prevent race conditions
    when multiple requests try to update the same lead's pipeline_stage.
    """
    async with db.begin_nested():
        try:
            # ✅ FIX: Row-level lock để prevent race condition
            lead_query = (
                select(models.Lead)
                .where(models.Lead.id == lead_id)
                .where(models.Lead.deleted_at.is_(None))
                .with_for_update()  # ROW LOCK - prevents concurrent modifications
            )
            lead_result = await db.execute(lead_query)
            lead = lead_result.scalar_one_or_none()
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Lấy Consultation cần update
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

            # ✅ FIX: Single check for latest consultation (eliminates TOCTOU vulnerability)
            # Query once and reuse the result for both permission check and status update
            latest_consultation_query = (
                select(models.Consultation)
                .where(models.Consultation.lead_id == lead_id)
                .order_by(
                    models.Consultation.consultation_date.desc(),
                    models.Consultation.id.desc(),
                )
            )
            latest_consultation_result = await db.execute(latest_consultation_query)
            latest_consultation = latest_consultation_result.scalars().first()
            is_latest_consultation = (
                latest_consultation and latest_consultation.id == consultation_id
            )

            # Kiểm tra quyền
            if current_user.role == "admin":
                # Admin có quyền update bất kỳ consultation nào
                pass
            elif current_user.role == "officer":
                # Officer chỉ được update consultation mới nhất
                if not is_latest_consultation:
                    raise PermissionDeniedError(
                        detail="Officers can only update the most recent consultation to maintain consultation chain integrity."
                    )

                # Kiểm tra officer có được gán cho Lead này không
                if lead.assigned_officer_id != current_user.id:
                    raise PermissionDeniedError(
                        detail="You are not assigned to this lead."
                    )
            else:
                # Các role khác không có quyền update consultation
                raise PermissionDeniedError(
                    detail="You don't have permission to update consultations."
                )

            # Lưu trạng thái cũ của Lead trước khi update
            old_state = _get_current_lead_state(lead)
            old_consultation_status_id = consultation.consultation_status_id

            # Update các trường được cung cấp
            update_data = consultation_in.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                if field == "status_id":
                    # Đặt consultation_status_id
                    consultation.consultation_status_id = value
                else:
                    setattr(consultation, field, value)

            db.add(consultation)

            # Nếu status_id thay đổi và đây là consultation mới nhất
            # Cập nhật trạng thái Lead (reuse is_latest_consultation from above)
            status_changed = False
            if "status_id" in update_data and update_data["status_id"] != old_consultation_status_id:
                if is_latest_consultation:
                    # Đây là consultation mới nhất, cập nhật lead status
                    new_status = await db.get(
                        models.ConsultationStatus, update_data["status_id"]
                    )
                    if new_status:
                        lead.consultation_status_id = new_status.id
                        lead.pipeline_stage_id = new_status.stage_id
                        # ✅ Sync lead.status từ consultation_status (Hybrid Approach)
                        sync_lead_status_from_consultation(lead, new_status)
                        db.add(lead)
                        status_changed = True

                        log.info(
                            "Lead status updated via consultation update",
                            lead_id=lead_id,
                            consultation_id=consultation_id,
                            old_status=old_consultation_status_id,
                            new_status=new_status.id,
                        )
                    else:
                        log.warning(
                            f"Status '{update_data['status_id']}' not found",
                            lead_id=lead_id,
                        )

            # Lấy trạng thái mới sau khi cập nhật
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái Lead (nếu có thay đổi)
            if status_changed:
                await _log_lead_state_change(
                    db,
                    lead,
                    old_state,
                    new_state,
                    changed_by=current_user,
                    reason=f"Updated consultation ID {consultation_id}",
                )

            # Flush to get changes ready (commit handled by begin_nested context)
            await db.flush()
            await db.refresh(consultation)

            # ✅ Quick Disposition: Cập nhật next_activity_at nếu scheduled_at thay đổi
            if "scheduled_at" in update_data:
                await update_lead_next_activity(db, lead_id)

            # Store values for use after transaction
            _lead_id = lead_id
            _consultation_id = consultation_id
            _officer_id = lead.assigned_officer_id
            _consultation_status_id = consultation.consultation_status_id or ""
            _status_changed = status_changed

        except Exception as e:
            # Rollback tự động by begin_nested context
            log.error(
                "Failed to update consultation",
                lead_id=lead_id,
                consultation_id=consultation_id,
                error=str(e),
                exc_info=True,
            )
            raise e

    # After successful transaction, log and emit events
    log.info(
        "Consultation updated successfully",
        user_id=current_user.id,
        lead_id=_lead_id,
        consultation_id=_consultation_id,
        status_changed=_status_changed,
    )

    # Dispatch notification for consultation updated
    try:
        from .notification_dispatcher import dispatch
        from ..core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.CONSULTATION_UPDATED,
            payload={
                "consultation_id": _consultation_id,
                "lead_id": _lead_id,
                "officer_id": _officer_id,
                "old_status_id": None,  # Could be tracked if needed
                "new_status_id": _consultation_status_id,
                "actor_id": current_user.id,
            }
        )
    except Exception as e:
        log.error(
            "Failed to dispatch consultation updated notification",
            lead_id=_lead_id,
            consultation_id=_consultation_id,
            error=str(e),
            exc_info=True
        )

    return consultation


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
                new_state["assigned_officer_id"] = None
                # Giữ nguyên consult/stage và status (không đổi consultation workflow)
                new_state["consultation_status_id"] = lead.consultation_status_id
                new_state["pipeline_stage_id"] = lead.pipeline_stage_id
                new_state["status"] = lead.status  # Keep status synced from consultation
                lead.assigned_at = None
                lead.assigned_officer = None  # Set cả relationship thành None
                # Update assignment_status to reassign_pending
                StatusHelper.set_assignment_status(lead, AssignmentStatus.REASSIGN_PENDING)
                log_method = "officer_reassign"
                trigger_reassignment = True
                log.info(
                    "Officer requested lead reassignment",
                    lead_id=lead_id,
                    officer_id=officer.id,
                    assignment_status=lead.assignment_status,
                )

            elif action == "reject":
                # Get rejected status from database (database-driven)
                rejected_status = await StatusHelper.get_rejected_status(db)
                log_method = "officer_reject"

                if rejected_status:
                    # Sync lead status from consultation_status
                    await StatusHelper.sync_lead_status(lead, rejected_status)
                    new_state["status"] = lead.status
                    new_state["consultation_status_id"] = rejected_status.id
                    new_state["pipeline_stage_id"] = rejected_status.stage_id
                    log.info(
                        "Setting consultation status to rejected",
                        lead_id=lead_id,
                        status_id=rejected_status.id,
                        legacy_status=rejected_status.legacy_status,
                    )
                else:
                    log.warning(
                        "Rejected consultation status not found in database.",
                        lead_id=lead_id,
                    )
                    # Fallback: set status directly
                    new_state["status"] = "rejected"
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


# =============================================================================
# PHASE 1 - Task 1.8: LEAD IMPORT (EXTRACTED FROM ROUTER)
# =============================================================================

async def import_leads_from_file_content(
    file_content: bytes,
    filename: str,
    db: AsyncSession,
    default_unit_id: Optional[int] = None,  # Force all leads to this unit
    auto_assign_officer_id: Optional[int] = None,  # Auto-assign to this officer
) -> Tuple[schemas.LeadImportResult, Callable]:
    """
    Import leads from CSV or Excel file content.

    This function extracts business logic from the router layer, making it
    protocol-independent and reusable across different contexts (HTTP, CLI, Celery).

    Business Rules:
    - Supports CSV (.csv) and Excel (.xlsx) files
    - Required columns: full_name, email, phone, source, unit_id
    - Optional columns: offering_id
    - Email must be unique (checks both DB and current file)
    - Leads are created with default initial status
    - Batch insertion with error collection (doesn't fail fast)
    - Transaction rollback on bulk insert failure

    Args:
        file_content: File content as bytes (CSV or Excel)
        filename: Original filename (used to determine file type)
        db: Database session (injected via DI)

    Returns:
        LeadImportResult containing:
        - total_rows_processed: Number of rows processed
        - successful_imports: Number of leads created
        - failed_imports: Number of rows with errors
        - created_lead_ids: List of created lead IDs
        - errors: List of LeadImportError objects

    Raises:
        ValueError: If file format is invalid or file is empty

    Example:
        >>> with open("leads.csv", "rb") as f:
        ...     content = f.read()
        >>> result = await import_leads_from_file_content(
        ...     file_content=content,
        ...     filename="leads.csv",
        ...     db=session
        ... )
        >>> print(f"Created {result.successful_imports} leads")
    """
    import io
    import pandas as pd
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # --- 1. Validate file extension ---
    file_extension = ""
    if filename:
        file_extension = filename.rsplit(".", 1)[-1].lower()

    if file_extension not in ["csv", "xlsx"]:
        log.warning(
            "Import failed: Invalid file extension",
            filename=filename,
            ext=file_extension,
        )
        raise ValueError(
            "Invalid file format. Only .csv and .xlsx files are supported."
        )

    # --- 2. Read file content into DataFrame ---
    try:
        if not file_content:
            raise ValueError("Empty file uploaded.")

        if file_extension == "csv":
            df = pd.read_csv(io.BytesIO(file_content))
        else:  # xlsx
            df = pd.read_excel(io.BytesIO(file_content), engine="openpyxl")

        log.info(f"Successfully read {len(df)} rows from {file_extension} file.")

    except ValueError as e:
        raise e  # Re-raise validation errors
    except Exception as e:
        log.error(
            "Failed to read or parse file content",
            filename=filename,
            error=str(e),
            exc_info=True,
        )
        raise ValueError(
            f"Could not read or parse the file. Ensure it is a valid {file_extension} file. Error: {e}"
        )

    # --- 3. Validate columns and process data ---
    required_columns = {"full_name", "email", "phone", "source", "unit_id"}

    # Normalize column names (lowercase, strip, replace spaces)
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "_")

    # Check required columns
    missing_cols = required_columns - set(df.columns)
    if missing_cols:
        log.warning(
            "Import failed: Missing required columns", missing=list(missing_cols)
        )
        raise ValueError(
            f"File is missing required columns: {', '.join(missing_cols)}"
        )

    leads_to_insert = []
    errors: List[schemas.LeadImportError] = []
    processed_row_count = 0

    # Get default initial status (database-driven)
    initial_status_obj = await StatusHelper.get_initial_status(db)
    if not initial_status_obj:
        log.error(
            "FATAL: Initial consultation status not found in DB. Cannot import leads."
        )
        raise ValueError(
            "System configuration error: Initial lead status not found."
        )

    initial_status_id = initial_status_obj.id
    initial_stage_id = initial_status_obj.stage_id
    initial_legacy_status = initial_status_obj.legacy_status or "new"

    # Get existing emails to check for duplicates efficiently
    existing_emails_in_db = set()
    async for email_tuple in await db.stream(select(models.Lead.email)):
        existing_emails_in_db.add(email_tuple[0])
    emails_in_current_file = set()

    # --- 4. Process each row ---
    for index, row in df.iterrows():
        processed_row_count += 1
        row_number = index + 2  # Excel row number (header is row 1)
        row_data = row.to_dict()
        cleaned_data = {}
        validation_errors_for_row = []

        # Type conversion for required fields
        try:
            cleaned_data["full_name"] = str(row_data.get("full_name", "")).strip()
            cleaned_data["email"] = str(row_data.get("email", "")).strip()

            # Special handling for 'phone': convert to string, remove ".0" if float
            phone_val = row_data.get("phone")
            cleaned_data["phone"] = (
                str(phone_val).split(".")[0] if pd.notna(phone_val) else ""
            )

            cleaned_data["source"] = str(row_data.get("source", "")).strip()

            # Convert 'unit_id' to int (or use default if provided)
            if default_unit_id:
                # Override with default unit (for officer import)
                cleaned_data["unit_id"] = default_unit_id
            else:
                unit_id_val = row_data.get("unit_id")
                if pd.notna(unit_id_val):
                    cleaned_data["unit_id"] = int(float(unit_id_val))
                else:
                    cleaned_data["unit_id"] = None

        except (ValueError, TypeError, Exception) as e:
            validation_errors_for_row.append(f"Type conversion error: {e}")

        # Type conversion for optional 'offering_id'
        offering_id_val = row_data.get("offering_id")
        if pd.notna(offering_id_val):
            try:
                cleaned_data["offering_id"] = int(float(offering_id_val))
            except (ValueError, TypeError):
                validation_errors_for_row.append(
                    "Invalid format for 'offering_id', expected a number."
                )
        else:
            cleaned_data["offering_id"] = None

        # Validate with Pydantic
        try:
            # If there are type conversion errors, raise them
            if validation_errors_for_row:
                raise ValueError(", ".join(validation_errors_for_row))

            lead_in = schemas.LeadCreate(**cleaned_data)

            # Check email duplication
            if (
                lead_in.email in existing_emails_in_db
                or lead_in.email in emails_in_current_file
            ):
                raise ValueError(
                    f"Email '{lead_in.email}' already exists in the database or this file."
                )

            emails_in_current_file.add(lead_in.email)

            # Prepare dict for bulk insert
            lead_dict = lead_in.model_dump()
            lead_dict["status"] = initial_legacy_status  # Use legacy_status from DB
            lead_dict["consultation_status_id"] = initial_status_id
            lead_dict["pipeline_stage_id"] = initial_stage_id

            # Auto-assign to officer if specified
            if auto_assign_officer_id:
                lead_dict["assigned_officer_id"] = auto_assign_officer_id
                lead_dict["assigned_at"] = datetime.now(timezone.utc)
                lead_dict["assignment_status"] = AssignmentStatus.ASSIGNED
            else:
                lead_dict["assigned_officer_id"] = None
                lead_dict["assigned_at"] = None
                lead_dict["assignment_status"] = AssignmentStatus.PENDING

            leads_to_insert.append(lead_dict)

        except (ValueError, TypeError) as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Data validation failed: {e}",
                    row_data=row_data,
                )
            )
        except Exception as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Unexpected error processing row: {e}",
                    row_data=row_data,
                )
            )

    # --- 5. Bulk insert ---
    created_lead_ids: List[int] = []
    batch_size = 100  # Commit every 100 leads

    if leads_to_insert:
        try:
            for i in range(0, len(leads_to_insert), batch_size):
                batch = leads_to_insert[i : i + batch_size]

                async with db.begin_nested():  # Start nested transaction
                    # Insert batch
                    await db.execute(pg_insert(models.Lead), batch)

                    # Get IDs of inserted leads
                    inserted_emails = [ld["email"] for ld in batch]
                    query = select(models.Lead.id).where(
                        models.Lead.email.in_(inserted_emails)
                    )
                    result = await db.execute(query)
                    batch_ids = result.scalars().all()
                    created_lead_ids.extend(batch_ids)

                log.info(
                    f"Committed batch {i // batch_size + 1}, {len(batch_ids)} leads inserted."
                )

            # ✅ TRANSACTION FIX: Flush instead of commit
            await db.flush()

        except Exception as e:
            # ✅ Router will handle rollback
            log.error(
                "Bulk lead insertion failed during batch",
                error=str(e),
                exc_info=True,
            )
            # Record error
            errors.append(
                schemas.LeadImportError(
                    row_number=-1,
                    error_message=f"Database bulk insert error (batch failed): {e}",
                    row_data={},
                )
            )
            created_lead_ids = []  # Reset IDs due to rollback

    # --- 6. Build result ---
    result = schemas.LeadImportResult(
        total_rows_processed=processed_row_count,
        successful_imports=len(created_lead_ids),
        failed_imports=len(errors),
        created_lead_ids=created_lead_ids,
        errors=errors,
    )

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        result_summary = result.model_dump(exclude={"errors"})
        if errors:
            log.warning("Lead import process finished with errors", result=result_summary)
        else:
            log.info("Lead import process finished successfully", result=result_summary)

    return result, _post_commit


# =============================================================================
# BULK OPERATIONS
# =============================================================================

async def bulk_assign_leads(
    db: AsyncSession,
    lead_ids: List[int],
    officer_id: int,
    assigner: models.User
) -> dict:
    """
    Bulk assign multiple leads to a single officer (Admin/Manager only).

    Args:
        db: Database session
        lead_ids: List of Lead IDs to assign
        officer_id: Target officer ID
        assigner: User performing the assignment

    Returns:
        dict: {
            "total": int,
            "successful": int,
            "failed": int,
            "assigned_lead_ids": List[int],
            "errors": List[dict]
        }

    Business Rules:
    - All leads must exist and not be deleted
    - Officer must be active and have role="officer"
    - Creates AssignmentLog for each successful assignment
    - Logs state change in LeadStatusHistory
    - Continues on errors (doesn't fail fast)
    """
    # Validate officer
    officer = await db.get(models.User, officer_id)
    if not officer:
        raise ResourceNotFoundError(f"Officer with id {officer_id} not found")
    if officer.role != "officer":
        raise PermissionDeniedError(f"User {officer_id} is not an officer")
    if officer.status != "active":
        raise BadRequest(f"Officer {officer_id} is not active")

    assigned_lead_ids = []
    errors = []

    for lead_id in lead_ids:
        try:
            # Assign lead using existing service function
            lead = await assign_lead_manually(db, lead_id, officer_id, assigner)
            assigned_lead_ids.append(lead.id)

        except (ResourceNotFoundError, PermissionDeniedError, BadRequest) as e:
            errors.append({
                "lead_id": lead_id,
                "error": str(e)
            })
            log.warning(
                "Bulk assign: Failed to assign lead",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e)
            )
        except Exception as e:
            errors.append({
                "lead_id": lead_id,
                "error": f"Unexpected error: {str(e)}"
            })
            log.error(
                "Bulk assign: Unexpected error",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True
            )

    log.info(
        "Bulk assign completed",
        total=len(lead_ids),
        successful=len(assigned_lead_ids),
        failed=len(errors),
        officer_id=officer_id,
        assigner_id=assigner.id
    )

    return {
        "total": len(lead_ids),
        "successful": len(assigned_lead_ids),
        "failed": len(errors),
        "assigned_lead_ids": assigned_lead_ids,
        "errors": errors
    }


# =============================================================================
# DELETE LEAD (SOFT DELETE)
# =============================================================================

async def delete_lead(
    db: AsyncSession,
    lead_id: int,
    deleted_by: models.User
) -> models.Lead:
    """
    Soft delete a Lead (Admin only).

    Business Rules:
    - Sets deleted_at timestamp instead of physically deleting
    - Preserves all historical data (consultations, applications, logs)
    - Deleted leads are filtered out from normal queries
    - Only Admin can delete leads
    - Cannot delete already-deleted leads

    Args:
        db: Database session
        lead_id: Lead ID to delete
        deleted_by: User performing the deletion (for audit trail)

    Returns:
        models.Lead: The soft-deleted lead object

    Raises:
        ResourceNotFoundError: If lead not found or already deleted
        PermissionDeniedError: If user doesn't have permission (checked in router)

    Example:
        >>> lead = await delete_lead(db, lead_id=123, deleted_by=admin_user)
        >>> print(lead.deleted_at)  # 2025-11-18 02:30:00+00:00
    """
    try:
        async with db.begin_nested():
            # Fetch lead (exclude already deleted leads)
            lead = await get_lead_by_id_shallow(db, lead_id, include_deleted=False)

            # Check if lead is already deleted (double-check)
            if lead.deleted_at is not None:
                raise ResourceNotFoundError(
                    detail=f"Lead with id {lead_id} is already deleted"
                )

            # Capture old state for history logging
            old_state = _get_current_lead_state(lead)

            # Set deleted_at timestamp (soft delete)
            lead.deleted_at = datetime.now(timezone.utc)

            # Optionally update status to indicate deletion
            lead.status = "deleted"

            # Mark as modified
            db.add(lead)

            # Get new state
            new_state = _get_current_lead_state(lead)

            # Log state change in history
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=deleted_by,
                reason=f"Lead soft-deleted by {deleted_by.role} {deleted_by.username}"
            )

            log.info(
                "Lead soft-deleted successfully",
                lead_id=lead_id,
                deleted_by_user_id=deleted_by.id,
                deleted_by_username=deleted_by.username
            )

            return lead

    except ResourceNotFoundError:
        # Lead not found or already deleted
        raise
    except Exception as e:
        # Rollback on any error
        await db.rollback()
        log.error(
            "Failed to delete lead",
            lead_id=lead_id,
            deleted_by_user_id=deleted_by.id,
            error=str(e),
            exc_info=True
        )
        raise e