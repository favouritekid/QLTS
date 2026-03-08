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
    async def get_initial_status(db: AsyncSession) -> Optional[models.ConsultationStatus]:
        """
        Get the initial consultation status for new leads.

        Query: legacy_status = "new" AND is_final = false
        Expected result: sts00 (Chưa liên hệ)

        Returns:
            ConsultationStatus or None if not found
        """
        result = await db.execute(
            select(models.ConsultationStatus)
            .where(
                and_(
                    models.ConsultationStatus.legacy_status == "new",
                    models.ConsultationStatus.is_final == False
                )
            )
            .order_by(models.ConsultationStatus.id)
            .limit(1)
        )
        status = result.scalar_one_or_none()

        if status:
            log.debug(
                "Found initial status",
                status_id=status.id,
                status_name=status.name,
                legacy_status=status.legacy_status
            )
        else:
            log.warning("No initial consultation status found in database")

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
    async def get_initial_status_id(db: AsyncSession) -> Optional[str]:
        """
        Get just the ID of the initial status.
        Useful when you only need the ID without loading the full object.

        Returns:
            Status ID string or None
        """
        status = await StatusHelper.get_initial_status(db)
        return status.id if status else None

    @staticmethod
    async def get_rejected_status_id(db: AsyncSession) -> Optional[str]:
        """
        Get just the ID of the rejected status.

        Returns:
            Status ID string or None
        """
        status = await StatusHelper.get_rejected_status(db)
        return status.id if status else None
