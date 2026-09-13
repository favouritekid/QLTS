# app/services/status_helper.py
"""
StatusHelper: Database-driven status management for Leads.

This module replaces hardcoded status IDs with queries based on status characteristics.
It ensures lead.status is always synced with consultation_status.legacy_status.

Usage:
    from app.services.status_helper import StatusHelper

    # Get initial status for new lead
    initial_status = await StatusHelper.get_initial_status(db)

    # Sync lead status from consultation_status
    await StatusHelper.sync_lead_status(lead, initial_status)
"""

from typing import Optional
import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..core.status_mapping import INITIAL_CONSULTATION_STATUS_CODE
from ..utils.exceptions import InitialLeadStatusNotConfigured

log = structlog.get_logger(__name__)


# Assignment status constants (for assignment_status field)
class AssignmentStatus:
    """Constants for lead.assignment_status field."""
    PENDING = "pending"              # Lead waiting for first assignment
    ASSIGNED = "assigned"            # Successfully assigned to an officer
    FAILED = "failed"                # Assignment failed (no officers, full capacity)
    REASSIGN_PENDING = "reassign_pending"  # Waiting to be reassigned


class StatusHelper:
    """
    Helper class for database-driven status management.

    Instead of hardcoding status IDs like "TTHV000", we query statuses
    by their characteristics (legacy_status, is_final, outcome_type).
    """

    @staticmethod
    def check_initial_status_row(
        status: Optional[models.ConsultationStatus],
    ) -> list[str]:
        """Liệt kê những điều kiện hợp lệ mà hàng khởi tạo KHÔNG thoả.

        Tách riêng khỏi ``get_initial_status`` để phép kiểm là một hàm thuần —
        test khẳng định được TỪNG điều kiện mà không cần CSDL, và không ai phải
        chép lại danh sách này ở nơi thứ hai.

        Trả về danh sách rỗng nghĩa là hàng dùng được.

        Ba điều kiện, mỗi cái vì một hỏng hóc cụ thể (đọc ra từ chính mã gọi,
        không phải từ tên cột):

        * ``is_final is False`` — ``sync_lead_status`` sẽ đẩy lead thẳng vào
          trạng thái CUỐI vòng đời ngay lúc tạo. Lead chết lúc sinh ra, và
          ``check_terminal_status_guard`` sẽ chặn mọi consultation sau đó.
        * ``is_universal is False`` — hàng universal là *activity* (``sts01``
          NO_ANSWER, ``sts15``, ``sts19``): chúng cố tình đứng NGOÀI pipeline,
          ``updates_pipeline=false``, và ``add_consultation`` (:2291) bỏ qua
          hẳn nhánh cập nhật pipeline cho chúng. Lấy một hàng như thế làm điểm
          xuất phát là dựng lead trên một trạng thái không bao giờ tiến được.
        * ``stage_id is not None`` — ``StatusHelper.sync_lead_status`` gán
          ``lead.pipeline_stage_id = consultation_status.stage_id``. NULL ở đây
          tái tạo đúng thứ hỏng mà bản vá này đang đóng: lead có
          ``pipeline_stage_id = NULL``, rơi khỏi mọi phễu và mọi bộ lọc theo
          stage, mà HTTP vẫn 201.
        """
        if status is None:
            return ["không tìm thấy hàng nào"]

        problems: list[str] = []
        if status.is_final:
            problems.append("is_final=True (trạng thái cuối vòng đời)")
        if status.is_universal:
            problems.append("is_universal=True (activity, đứng ngoài pipeline)")
        if not status.stage_id:
            problems.append("stage_id=NULL (không thuộc pipeline stage nào)")
        return problems

    @staticmethod
    async def get_initial_status(db: AsyncSession) -> models.ConsultationStatus:
        """
        Lấy trạng thái tư vấn KHỞI TẠO cho lead mới.

        Truy vấn theo ĐỊNH DANH CHUẨN ``code = 'NOT_CONTACTED'``
        (:data:`app.core.status_mapping.INITIAL_CONSULTATION_STATUS_CODE`), có
        ``uq_consultation_status_code UNIQUE (code)`` canh ở tầng CSDL. Không
        ``ORDER BY``, không ``LIMIT``: nếu ràng buộc UNIQUE có ngày biến mất thì
        ``scalar_one_or_none`` ném ``MultipleResultsFound`` thay vì im lặng chọn
        hàng đầu tiên — đúng thứ đã suýt xảy ra khi migration ``v7w8x9y0z1a2``
        gán ``legacy_status='new'`` cho cả ``sts00`` lẫn ``sts01``.

        Returns:
            ConsultationStatus — luôn là một hàng đã qua
            :meth:`check_initial_status_row`.

        Raises:
            InitialLeadStatusNotConfigured: 503. Hàm này KHÔNG trả ``None`` nữa.
                Mọi người gọi trước đây đều có nhánh fallback ghi lead với
                ``consultation_status_id=NULL`` + ``pipeline_stage_id=NULL`` rồi
                trả 201 — hỏng dữ liệu im lặng. Fail-closed ở ĐÂY, tầng
                canonical, để không phải rải lại hàng rào ở năm nơi gọi.
        """
        result = await db.execute(
            select(models.ConsultationStatus)
            .where(models.ConsultationStatus.code == INITIAL_CONSULTATION_STATUS_CODE)
        )
        status = result.scalar_one_or_none()

        problems = StatusHelper.check_initial_status_row(status)
        if problems:
            log.error(
                "Initial consultation status not usable",
                expected_code=INITIAL_CONSULTATION_STATUS_CODE,
                found_status_id=status.id if status else None,
                problems=problems,
            )
            raise InitialLeadStatusNotConfigured(
                context={
                    "expected_code": INITIAL_CONSULTATION_STATUS_CODE,
                    "found_status_id": status.id if status else None,
                    "problems": problems,
                }
            )

        log.debug(
            "Found initial status",
            status_id=status.id,
            status_name=status.name,
            stage_id=status.stage_id,
        )
        return status

    @staticmethod
    async def get_rejected_status(db: AsyncSession) -> Optional[models.ConsultationStatus]:
        """
        Get the rejected/lost consultation status for leads that are rejected.

        Query: legacy_status = "rejected" AND is_final = true
        Expected result: sts03 (Nhầm số) or sts04 (Không đồng ý)

        Returns:
            ConsultationStatus or None if not found
        """
        result = await db.execute(
            select(models.ConsultationStatus)
            .where(
                and_(
                    models.ConsultationStatus.legacy_status == "rejected",
                    models.ConsultationStatus.is_final == True
                )
            )
            .order_by(models.ConsultationStatus.id)
            .limit(1)
        )
        status = result.scalar_one_or_none()

        if status:
            log.debug(
                "Found rejected status",
                status_id=status.id,
                status_name=status.name
            )
        else:
            log.warning("No rejected consultation status found in database")

        return status

    @staticmethod
    async def get_status_by_legacy(
        db: AsyncSession,
        legacy_status: str,
        is_final: Optional[bool] = None
    ) -> Optional[models.ConsultationStatus]:
        """
        Get consultation status by legacy_status value.

        Args:
            db: Database session
            legacy_status: One of: new, contacted, qualified, unqualified, converted, rejected
            is_final: Optional filter for is_final

        Returns:
            ConsultationStatus or None if not found
        """
        query = select(models.ConsultationStatus).where(
            models.ConsultationStatus.legacy_status == legacy_status
        )

        if is_final is not None:
            query = query.where(models.ConsultationStatus.is_final == is_final)

        query = query.order_by(models.ConsultationStatus.id).limit(1)

        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def sync_lead_status(
        lead: models.Lead,
        consultation_status: models.ConsultationStatus
    ) -> None:
        """
        Sync lead fields from consultation_status.

        This ensures:
        - lead.consultation_status_id = consultation_status.id
        - lead.pipeline_stage_id = consultation_status.stage_id
        - lead.status = derived from consultation_status (NULL-safe fallback)

        Args:
            lead: Lead model instance
            consultation_status: ConsultationStatus to sync from
        """
        from ..core.status_mapping import sync_lead_status_from_consultation

        lead.consultation_status_id = consultation_status.id
        lead.pipeline_stage_id = consultation_status.stage_id
        sync_lead_status_from_consultation(lead, consultation_status)

        log.debug(
            "Synced lead status from consultation_status",
            lead_id=getattr(lead, 'id', 'new'),
            consultation_status_id=consultation_status.id,
            pipeline_stage_id=consultation_status.stage_id,
            status=lead.status,
        )

    @staticmethod
    def set_assignment_status(lead: models.Lead, status: str) -> None:
        """
        Set the assignment workflow status.

        Args:
            lead: Lead model instance
            status: One of AssignmentStatus constants
        """
        valid_statuses = [
            AssignmentStatus.PENDING,
            AssignmentStatus.ASSIGNED,
            AssignmentStatus.FAILED,
            AssignmentStatus.REASSIGN_PENDING
        ]

        if status not in valid_statuses:
            raise ValueError(f"Invalid assignment_status: {status}. Must be one of {valid_statuses}")

        lead.assignment_status = status

        log.debug(
            "Set lead assignment_status",
            lead_id=getattr(lead, 'id', 'new'),
            assignment_status=status
        )

    @staticmethod
    async def get_initial_status_id(db: AsyncSession) -> str:
        """
        Get just the ID of the initial status.
        Useful when you only need the ID without loading the full object.

        Returns:
            Status ID string.

        Raises:
            InitialLeadStatusNotConfigured: uỷ quyền hoàn toàn cho
                :meth:`get_initial_status` — không có nhánh ``None`` riêng ở
                đây, nếu không lại đẻ ra nguồn chuẩn thứ hai cho cùng phép hỏi.
        """
        status = await StatusHelper.get_initial_status(db)
        return status.id

    @staticmethod
    async def get_rejected_status_id(db: AsyncSession) -> Optional[str]:
        """
        Get just the ID of the rejected status.

        Returns:
            Status ID string or None
        """
        status = await StatusHelper.get_rejected_status(db)
        return status.id if status else None
