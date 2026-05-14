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

    @staticmethod
    def _validate_date_window(start, end) -> None:
        """Cross-field invariant: start_date ≤ end_date nếu cả 2 set.

        Apply chung create/update/extend để tránh drift logic giữa các path.
        """
        if start is not None and end is not None and start > end:
            raise BusinessRuleViolation(
                f"start_date ({start}) phải ≤ end_date ({end})"
            )

    async def create(
        self, academic_year: int, payload: AdmissionRoundCreate, current_admin: User
    ) -> OfferingAdmissionRound:
        """Create new round under academic_year.

        Guards:
        * round_code UNIQUE per academic_year
        * start_date ≤ end_date nếu cả 2 set (BUG #C2 fix)
        """
        self._validate_date_window(payload.start_date, payload.end_date)

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
            # Phase 3 Q-P3-02 / Q-P3-06 — pass-through the 2 round flags
            # that PR #292 added to the Pydantic schema + FE form. Before
            # this hotfix the service was dropping both fields on the
            # floor — admin could check "Cho phép nhiều nguyện vọng"
            # in the create dialog, see a "Đã tạo đợt tuyển sinh" toast,
            # but the persisted row would always come back with
            # allow_multi_nv=false (caught by Phase 1 prod smoke
            # 2026-05-14 immediately after PR #293 deploy).
            allow_multi_nv=payload.allow_multi_nv,
            confirm_expiry_hours=payload.confirm_expiry_hours,
        )
        self.db.add(round_obj)
        await self.db.flush()

        log.info(
            "admission_round_created",
            round_id=round_obj.id,
            academic_year=academic_year,
            round_code=payload.round_code,
            allow_multi_nv=payload.allow_multi_nv,
            confirm_expiry_hours=payload.confirm_expiry_hours,
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
                # Phase 3 pass-through — same drift as create() above.
                # ``AdmissionRoundBulkCreateItem`` ships the 2 round
                # flags with defaults (False / 168) so existing
                # "Tạo nhanh 4 đợt" callers keep their legacy behavior
                # without touching the FE call site.
                allow_multi_nv=item.allow_multi_nv,
                confirm_expiry_hours=item.confirm_expiry_hours,
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

        # Validate time-window invariant: start_date ≤ end_date (shared helper).
        self._validate_date_window(round_obj.start_date, round_obj.end_date)

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

    async def restore(
        self, round_id: int, current_admin: User
    ) -> tuple[OfferingAdmissionRound, dict]:
        """Khôi phục đợt đã lưu trữ — clear archived_at, set is_active=true.

        Inverse của soft_archive. Chỉ admin discretion; đợt đã archive vẫn
        giữ nguyên end_date / extended_at để preserve audit trail.

        Pass 2 hard-review B-2-2: trả tuple ``(round_obj, prior_state)`` để
        router log_activity ghi delta old → new. Restore-archive-restore loop
        không mất extension history vì ``extended_at`` / ``extension_reason``
        được giữ nguyên + capture vào prior_state cho audit reconstruction.
        """
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")

        if round_obj.archived_at is None:
            raise BusinessRuleViolation(
                f"Round {round_id} chưa lưu trữ — không cần khôi phục"
            )

        prior_state = {
            "old_archived_at": round_obj.archived_at.isoformat(),
            "old_is_active": round_obj.is_active,
            "old_extended_at": (
                round_obj.extended_at.isoformat()
                if round_obj.extended_at is not None
                else None
            ),
            "old_extension_reason": round_obj.extension_reason,
        }

        round_obj.archived_at = None
        round_obj.is_active = True

        await self.db.flush()
        log.info(
            "admission_round_restored",
            round_id=round_id,
            admin_id=current_admin.id,
            **prior_state,
        )
        return round_obj, prior_state

    async def extend(
        self, round_id: int, payload: AdmissionRoundExtend, current_admin: User
    ) -> tuple[OfferingAdmissionRound, dict]:
        """Admin extend end_date per SPEC §2.1.a Rule 2.

        Audit fields ``extended_at``, ``extended_by_user_id``,
        ``extension_reason`` written atomically. Reason ≥10 chars enforced
        at schema layer.

        Pass 2 hard-review B-2-2: trả tuple ``(round_obj, prior_state)`` —
        capture ``old_end_date`` + ``old_extended_at`` để router log delta.
        Pre-extend value cần thiết cho audit reconstruction nếu admin
        extend nhiều lần liên tiếp.
        """
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")

        # BUG #C1 fix: chặn extend khi đã archive — tránh corrupt audit trail
        # (extended_at + archived_at cùng tồn tại). Admin phải restore trước
        # nếu thật sự muốn extend.
        if round_obj.archived_at is not None:
            raise BusinessRuleViolation(
                f"Round {round_id} đã lưu trữ ({round_obj.archived_at}); "
                f"khôi phục trước khi gia hạn"
            )

        if round_obj.end_date is not None and payload.end_date <= round_obj.end_date:
            raise BusinessRuleViolation(
                f"New end_date ({payload.end_date}) phải sau current end_date "
                f"({round_obj.end_date})"
            )

        # Validate window after extend nếu start_date đã set.
        self._validate_date_window(round_obj.start_date, payload.end_date)

        prior_state = {
            "old_end_date": (
                round_obj.end_date.isoformat()
                if round_obj.end_date is not None
                else None
            ),
            "old_extended_at": (
                round_obj.extended_at.isoformat()
                if round_obj.extended_at is not None
                else None
            ),
            "old_extension_reason": round_obj.extension_reason,
        }

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
            **prior_state,
        )
        return round_obj, prior_state

    async def list_by_year(
        self, academic_year: int
    ) -> List[OfferingAdmissionRound]:
        return await self.repo.list_by_year(academic_year)

    async def get_by_id(self, round_id: int) -> OfferingAdmissionRound:
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")
        return round_obj
