# app/services/admission_round_service.py
"""Service layer for OfferingAdmissionRound year-level (Phase 2 v8.2 PR-2A v2).

Implements:
* Round CRUD year-level
* Bulk-create (4 đợt atomic per academic_year)
* SPEC §2.1.a Rule 2: extend endpoint với audit log
* Soft-archive (Concern γ v6 — Phase 2 admin discretion regardless of
  submission_count; per-path counter PR-2B v2 sẽ handle)

Tier 1 chain logic (admit_quota per academic_info) MOVED to
``admission_quota_service`` (PR-2B v2 ships sau khi quota fields trên
admission_path). Round table không có quota fields nữa (Q1 Option A).
"""

from datetime import datetime, timezone
from typing import List

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OfferingAdmissionRound, User
from app.repositories.admission_round_repository import AdmissionRoundRepository
from app.schemas.admission_round import (
    AdmissionRoundBulkCreate,
    AdmissionRoundCreate,
    AdmissionRoundExtend,
    AdmissionRoundUpdate,
)
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


class AdmissionRoundService:
    """Business logic for admission rounds year-level."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AdmissionRoundRepository(db)

    async def create(
        self, academic_year: int, payload: AdmissionRoundCreate, current_admin: User
    ) -> OfferingAdmissionRound:
        """Create new round under academic_year.

        Guards:
        * round_code UNIQUE per academic_year
        """
        existing = await self.repo.get_by_year_and_code(academic_year, payload.round_code)
        if existing is not None:
            raise DuplicateResourceError(
                f"Round {payload.round_code!r} đã tồn tại cho năm {academic_year}"
            )

        round_obj = OfferingAdmissionRound(
            academic_year=academic_year,
            round_code=payload.round_code,
            round_name=payload.round_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_active=payload.is_active,
        )
        self.db.add(round_obj)
        await self.db.flush()

        log.info(
            "admission_round_created",
            round_id=round_obj.id,
            academic_year=academic_year,
            round_code=payload.round_code,
            admin_id=current_admin.id,
        )
        return round_obj

    async def bulk_create(
        self, academic_year: int, payload: AdmissionRoundBulkCreate, current_admin: User
    ) -> tuple[List[OfferingAdmissionRound], int]:
        """Bulk-create rounds idempotent per academic_year.

        Per-item duplicate check + skip; non-duplicate DB errors abort
        entire txn (router db.commit() không chạy → rollback). Returns
        (created_rounds, skipped_count). P2-3 v8.2 semantic clarification.

        Race-window mitigation (P2-4 v8.2): wrap IntegrityError trên flush
        thành DuplicateResourceError friendly cho concurrent admin scenario.
        """
        from sqlalchemy.exc import IntegrityError

        created: List[OfferingAdmissionRound] = []
        skipped = 0

        for item in payload.rounds:
            existing = await self.repo.get_by_year_and_code(academic_year, item.round_code)
            if existing is not None:
                skipped += 1
                continue

            round_obj = OfferingAdmissionRound(
                academic_year=academic_year,
                round_code=item.round_code,
                round_name=item.round_name,
                start_date=item.start_date,
                end_date=item.end_date,
                is_active=item.is_active,
            )
            self.db.add(round_obj)
            try:
                await self.db.flush()
            except IntegrityError as exc:
                # Race: 2 admins bulk-create same round_code concurrently.
                # First commit, second hits UNIQUE → friendly 409 instead
                # of raw 500.
                await self.db.rollback()
                raise DuplicateResourceError(
                    f"Round {item.round_code!r} đã tồn tại cho năm {academic_year} "
                    f"(race condition — admin khác vừa tạo cùng lúc)"
                ) from exc
            created.append(round_obj)

        log.info(
            "admission_round_bulk_created",
            academic_year=academic_year,
            requested=len(payload.rounds),
            created=len(created),
            skipped_duplicates=skipped,
            admin_id=current_admin.id,
        )
        return created, skipped

    async def update(
        self, round_id: int, payload: AdmissionRoundUpdate, current_admin: User
    ) -> OfferingAdmissionRound:
        """Update round time-window/lifecycle fields (Phase 2 scope per Q3)."""
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")

        update_data = payload.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(round_obj, field, value)

        await self.db.flush()
        log.info(
            "admission_round_updated",
            round_id=round_id,
            fields=list(update_data.keys()),
            admin_id=current_admin.id,
        )
        return round_obj

    async def soft_archive(
        self, round_id: int, current_admin: User
    ) -> OfferingAdmissionRound:
        """DELETE endpoint = soft-archive (Concern γ v6 carry forward).

        Phase 2 behavior: allow regardless of submission_count (admin
        discretion). is_active=false hides round khỏi storefront. Per-path
        submission_count (PR-2B v2) preserved cho audit.
        """
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")

        if round_obj.archived_at is not None:
            raise BusinessRuleViolation(
                f"Round {round_id} already archived at {round_obj.archived_at}"
            )

        round_obj.archived_at = datetime.now(timezone.utc)
        round_obj.is_active = False

        await self.db.flush()
        log.info(
            "admission_round_soft_archived",
            round_id=round_id,
            admin_id=current_admin.id,
        )
        return round_obj

    async def extend(
        self, round_id: int, payload: AdmissionRoundExtend, current_admin: User
    ) -> OfferingAdmissionRound:
        """Admin extend end_date per SPEC §2.1.a Rule 2.

        Audit fields ``extended_at``, ``extended_by_user_id``,
        ``extension_reason`` written atomically. Reason ≥10 chars enforced
        at schema layer.
        """
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")

        if round_obj.end_date is not None and payload.end_date <= round_obj.end_date:
            raise BusinessRuleViolation(
                f"New end_date ({payload.end_date}) phải sau current end_date "
                f"({round_obj.end_date})"
            )

        round_obj.end_date = payload.end_date
        round_obj.extended_at = datetime.now(timezone.utc)
        round_obj.extended_by_user_id = current_admin.id
        round_obj.extension_reason = payload.extension_reason

        await self.db.flush()
        log.info(
            "admission_round_extended",
            round_id=round_id,
            new_end_date=payload.end_date.isoformat(),
            admin_id=current_admin.id,
            reason_len=len(payload.extension_reason),
        )
        return round_obj

    async def list_by_year(
        self, academic_year: int
    ) -> List[OfferingAdmissionRound]:
        return await self.repo.list_by_year(academic_year)

    async def get_by_id(self, round_id: int) -> OfferingAdmissionRound:
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")
        return round_obj
