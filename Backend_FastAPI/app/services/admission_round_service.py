# app/services/admission_round_service.py
"""Service layer for OfferingAdmissionRound (Phase 2 PR-2A).

Implements:
* Round CRUD với Casbin + idempotent guards
* v2.12 P1 fix #4: admin reduce round_quota validation + override
* SPEC §2.1.a Rule 2: extend endpoint với audit log
* SPEC §5 tier 1: sum(round_quota) ≤ academic_info.annual_admission_quota guard
"""

from datetime import datetime, timezone
from typing import List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OfferingAcademicInfo, OfferingAdmissionRound, User
from app.repositories.admission_round_repository import AdmissionRoundRepository
from app.schemas.admission_round import (
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
    """Business logic for admission rounds."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AdmissionRoundRepository(db)

    async def create(
        self, academic_info_id: int, payload: AdmissionRoundCreate, current_admin: User
    ) -> OfferingAdmissionRound:
        """Create new round under academic_info.

        Guards:
        * ``academic_info_id`` exists + not soft-deleted
        * ``round_code`` UNIQUE per academic_info
        * SPEC §5 tier 1: sum(rounds.round_quota) + new.round_quota
          ≤ academic_info.annual_admission_quota
        """
        academic_info = await self.db.get(OfferingAcademicInfo, academic_info_id)
        if academic_info is None or academic_info.is_deleted:
            raise ResourceNotFoundError(
                f"OfferingAcademicInfo {academic_info_id} not found"
            )

        existing = await self.repo.get_by_code(academic_info_id, payload.round_code)
        if existing is not None:
            raise DuplicateResourceError(
                f"Round {payload.round_code!r} đã tồn tại cho academic_info {academic_info_id}"
            )

        if payload.round_quota is not None:
            await self._validate_tier1_quota_chain(
                academic_info, delta=payload.round_quota
            )

        round_obj = OfferingAdmissionRound(
            academic_info_id=academic_info_id,
            round_code=payload.round_code,
            round_name=payload.round_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            round_quota=payload.round_quota,
            admit_quota=payload.admit_quota,
            is_active=payload.is_active,
            submission_count=0,
        )
        self.db.add(round_obj)
        await self.db.flush()

        log.info(
            "admission_round_created",
            round_id=round_obj.id,
            academic_info_id=academic_info_id,
            round_code=payload.round_code,
            admin_id=current_admin.id,
        )
        return round_obj

    async def update(
        self, round_id: int, payload: AdmissionRoundUpdate, current_admin: User
    ) -> OfferingAdmissionRound:
        """Update round fields. v2.12 P1 fix #4: round_quota decrease
        below submission_count requires explicit ``override=true``.
        """
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")

        update_data = payload.model_dump(exclude_unset=True, exclude={"override"})

        # v2.12 P1 fix #4: validate quota decrease vs submission_count
        if "round_quota" in update_data and update_data["round_quota"] is not None:
            new_quota = update_data["round_quota"]
            if new_quota < round_obj.submission_count and not payload.override:
                raise BusinessRuleViolation(
                    detail=(
                        f"Quota mới ({new_quota}) thấp hơn submission_count "
                        f"({round_obj.submission_count}). "
                        f"Set override=true để confirm."
                    ),
                    context={
                        "current_submission_count": round_obj.submission_count,
                        "new_quota": new_quota,
                        "delta": new_quota - round_obj.submission_count,
                    },
                )

            # Tier 1 chain re-validation when quota changes.
            # Override flag bypasses ONLY the submission_count check above.
            # Tier 1 annual cap re-validation runs UNCONDITIONALLY — annual
            # quota constraint applies even when admin overrides per-round
            # oversubscribed scenario.
            academic_info = await self.db.get(
                OfferingAcademicInfo, round_obj.academic_info_id
            )
            # Tier 1 chain math: current_sum already includes this round's
            # OLD round_quota (in `_validate_tier1_quota_chain` SUM query),
            # delta = new - old. Therefore current_sum + delta = new sum
            # after change. Verified for 3 cases:
            #   * create (delta = new): current_sum excludes this round → +new
            #   * increase (delta > 0): current_sum has old → old + (new-old) = new
            #   * decrease (delta < 0): same math, delta negative
            delta = new_quota - (round_obj.round_quota or 0)
            await self._validate_tier1_quota_chain(academic_info, delta=delta)

            if new_quota < round_obj.submission_count and payload.override:
                log.warning(
                    "admission_round_quota_decrease_override",
                    round_id=round_id,
                    old_quota=round_obj.round_quota,
                    new_quota=new_quota,
                    submission_count=round_obj.submission_count,
                    admin_id=current_admin.id,
                )

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
        """DELETE endpoint = soft-archive (Concern γ v6 fix).

        Phase 2 behavior: allow regardless of submission_count (admin
        discretion). ``is_active=false`` hides round khỏi storefront +
        path config dropdown nhưng giữ data integrity (existing
        profiles vẫn link round_id qua applied_rules).

        Phase 3 future: tighten to block-with-hint when
        archive_expired_rounds_task cron ships.
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
            submission_count=round_obj.submission_count,
            admin_id=current_admin.id,
        )
        return round_obj

    async def extend(
        self, round_id: int, payload: AdmissionRoundExtend, current_admin: User
    ) -> OfferingAdmissionRound:
        """Admin extend end_date per SPEC §2.1.a Rule 2.

        Audit fields ``extended_at``, ``extended_by_user_id``,
        ``extension_reason`` written atomically. Reason ≥10 chars
        enforced at schema layer.
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

    async def list_by_academic_info(
        self, academic_info_id: int
    ) -> List[OfferingAdmissionRound]:
        return await self.repo.list_by_academic_info(academic_info_id)

    async def get_by_id(self, round_id: int) -> OfferingAdmissionRound:
        round_obj = await self.repo.get_by_id(round_id)
        if round_obj is None:
            raise ResourceNotFoundError(f"Round {round_id} not found")
        return round_obj

    async def _validate_tier1_quota_chain(
        self, academic_info: OfferingAcademicInfo, delta: int
    ) -> None:
        """Tier 1 chain (PLAN §5): sum(round_quota) ≤ annual_admission_quota.

        Runs SELECT ... FOR UPDATE on academic_info row trước khi compute
        sum (Pattern A per PLAN §5.a) để tránh race window.
        """
        if academic_info.annual_admission_quota is None:
            return  # No annual cap → no chain enforcement

        # Lock parent row to serialize concurrent quota mutations
        result = await self.db.execute(
            select(OfferingAcademicInfo)
            .where(OfferingAcademicInfo.id == academic_info.id)
            .with_for_update()
        )
        result.scalar_one()

        # Archived rounds NOT counted in tier 1 sum: when admin soft-archives
        # a round, its quota is "freed" — admin can re-allocate to new active
        # rounds. Trade-off: archive→un-archive flow could violate tier 1
        # (no re-check implemented Phase 2; defense-in-depth gap acknowledged
        # per memory phase2-plan-locked critical risks).
        sum_result = await self.db.execute(
            select(OfferingAdmissionRound.round_quota).where(
                OfferingAdmissionRound.academic_info_id == academic_info.id,
                OfferingAdmissionRound.round_quota.isnot(None),
                OfferingAdmissionRound.archived_at.is_(None),
            )
        )
        current_sum = sum(q for q in sum_result.scalars().all() if q is not None)

        if current_sum + delta > academic_info.annual_admission_quota:
            raise BusinessRuleViolation(
                f"Sum round_quota ({current_sum + delta}) sẽ vượt "
                f"annual_admission_quota ({academic_info.annual_admission_quota}) "
                f"của academic_info {academic_info.id}"
            )
