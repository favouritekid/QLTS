# app/services/admission_quota_service.py
"""Admission quota chain service (Phase 2 v8.2 PR-2B v2).

Tier 1 chain root per Q2 v8.2: ``admit_quota`` per academic_info.
Year-level scope (Option A) — KHÔNG school-wide cap.

Tier semantics:
* Tier 1: ``∑(path.admit_quota WHERE academic_info_id=X) ≤
  academic_info[X].annual_admission_quota``
* Tier 2: path invariant ``admit_quota ≤ round_quota`` nếu cả 2 set
* Tier 3 (PR-2D): ``∑(group_quota in path) ≤ path.admit_quota``

Pattern A (PLAN §5.a): SELECT FOR UPDATE academic_info row trước
compute sum cho race-safety. Filter ``path.status != 'archived'``
(P0-1 v8.1 — verified ``admission_path.py:91-98`` dùng ``status``
column, KHÔNG có ``archived_at``).
"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.admission_config.admission_path import AdmissionPath
from app.models.offering_academic_info import OfferingAcademicInfo
from app.utils.exceptions import BusinessRuleViolation, ResourceNotFoundError

log = structlog.get_logger(__name__)


class AdmissionQuotaService:
    """Quota chain validation service (Phase 2 v8.2 PR-2B v2)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate_tier1_chain_on_path_quota_change(
        self,
        academic_info_id: int,
        delta_admit_quota: int,
        excluded_path_id: int | None = None,
    ) -> None:
        """Validate Tier 1 chain on path admit_quota change.

        ``∑(path.admit_quota WHERE academic_info_id=X AND status !=
        'archived' AND admit_quota IS NOT NULL) + delta ≤
        academic_info[X].annual_admission_quota``

        Pattern A: SELECT FOR UPDATE academic_info row trước compute
        sum cho race-safety (PLAN §5.a). Excluded path ID supports
        update flow (subtract current value trước compute new sum).
        """
        ai_stmt = (
            select(OfferingAcademicInfo)
            .where(OfferingAcademicInfo.id == academic_info_id)
            .with_for_update()
        )
        academic_info = (await self.db.execute(ai_stmt)).scalar_one_or_none()
        if academic_info is None:
            raise ResourceNotFoundError(
                f"OfferingAcademicInfo {academic_info_id} not found"
            )

        annual_cap = academic_info.annual_admission_quota
        if annual_cap is None:
            # NULL annual cap = unbounded; Tier 1 inactive.
            return

        sum_stmt = select(
            func.coalesce(func.sum(AdmissionPath.admit_quota), 0)
        ).where(
            AdmissionPath.academic_info_id == academic_info_id,
            AdmissionPath.status != "archived",
            AdmissionPath.admit_quota.is_not(None),
        )
        if excluded_path_id is not None:
            sum_stmt = sum_stmt.where(AdmissionPath.id != excluded_path_id)

        current_sum = (await self.db.execute(sum_stmt)).scalar_one()
        new_sum = current_sum + delta_admit_quota

        if new_sum > annual_cap:
            log.warning(
                "tier1_chain_violation",
                academic_info_id=academic_info_id,
                annual_cap=annual_cap,
                current_sum=current_sum,
                delta=delta_admit_quota,
                new_sum=new_sum,
            )
            raise BusinessRuleViolation(
                f"Tier 1 chain violated: tổng admit_quota của ngành "
                f"academic_info_id={academic_info_id} sẽ là {new_sum} "
                f"(current {current_sum} + delta {delta_admit_quota}), "
                f"vượt annual_admission_quota={annual_cap}"
            )

    async def validate_tier2_path_invariant(
        self,
        admit_quota: int | None,
        round_quota: int | None,
    ) -> None:
        """Validate Tier 2 path invariant: admit_quota ≤ round_quota.

        Service-layer guard — nếu cả 2 set, admit không được vượt round.
        NULL trên 1 trong 2 = pass-through (no constraint).
        """
        if admit_quota is None or round_quota is None:
            return
        if admit_quota > round_quota:
            raise BusinessRuleViolation(
                f"Tier 2 invariant violated: admit_quota={admit_quota} > "
                f"round_quota={round_quota} trên cùng path"
            )
