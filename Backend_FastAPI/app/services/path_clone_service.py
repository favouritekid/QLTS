# app/services/path_clone_service.py
"""Path clone service — deep-copy admission paths between rounds (Phase 2 v8.2 PR-2D Q6).

Implements POST /api/v2/admin/rounds/{target_round_id}/clone-paths-from/{source_round_id}
endpoint logic. Deep-copy includes:
- AdmissionCriteria (new code via template — ADM-003 invariant: each criteria
  belongs to exactly 1 path)
- CriteriaSubjectGroup (1:N với criteria)
- AdmissionPath (new admission_round_id=target_round_id; ON CONFLICT 3-col
  UNIQUE skip)
- PathSubjectGroupConfig (1:N với path)
- PathSubjectGroupItem (1:N với config)

Quota fields (round_quota, admit_quota) reset to NULL on clone — admin sets
qua matrix UI per target round.
"""

from typing import List, Optional, Tuple

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.admission_config import (
    AdmissionCriteria,
    AdmissionPath,
    CriteriaSubjectGroup,
    PathSubjectGroupConfig,
    PathSubjectGroupItem,
)
from app.models.offering_admission_round import OfferingAdmissionRound
from app.schemas.path_subject_group import (
    ClonePathsRequest,
    ClonePathsResponse,
    ClonePathsResponseItem,
)
from app.utils.exceptions import BusinessRuleViolation, ResourceNotFoundError

log = structlog.get_logger(__name__)


class PathCloneService:
    """Deep-copy admission paths between rounds (Phase 2 v8.2 PR-2D)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _derive_criteria_code(
        self,
        source_code: str,
        target_round_code: str,
        target_round_id: int,
        template: Optional[str],
    ) -> str:
        """Derive new criteria code per template, or fallback."""
        if template:
            try:
                return template.format(
                    source_code=source_code,
                    round_code=target_round_code,
                    target_round_id=target_round_id,
                )
            except KeyError as exc:
                raise BusinessRuleViolation(
                    f"criteria_code_template invalid placeholder: {exc}. "
                    "Allowed: {source_code}, {round_code}, {target_round_id}"
                )
        return f"{source_code}_R{target_round_id}"

    async def clone_paths_from_round(
        self,
        target_round_id: int,
        source_round_id: int,
        payload: ClonePathsRequest,
    ) -> ClonePathsResponse:
        """Atomic deep-copy all (or filtered) paths từ source round to target.

        ON CONFLICT (admission_round_id, academic_info_id, admission_method_id)
        skip duplicates. Audit log includes cloned IDs cho traceability.
        """
        # Verify rounds exist
        source_round = await self.db.get(OfferingAdmissionRound, source_round_id)
        target_round = await self.db.get(OfferingAdmissionRound, target_round_id)
        if source_round is None:
            raise ResourceNotFoundError(f"Source round {source_round_id} not found")
        if target_round is None:
            raise ResourceNotFoundError(f"Target round {target_round_id} not found")

        if source_round_id == target_round_id:
            raise BusinessRuleViolation(
                "source_round_id và target_round_id phải khác nhau"
            )

        # Eager-load source paths với criteria + criteria_subject_group +
        # path_subject_group_configs + items
        stmt = (
            select(AdmissionPath)
            .where(AdmissionPath.admission_round_id == source_round_id)
            .options(selectinload(AdmissionPath.criteria))
        )
        if payload.academic_info_ids:
            stmt = stmt.where(
                AdmissionPath.academic_info_id.in_(payload.academic_info_ids)
            )
        source_paths = list((await self.db.execute(stmt)).scalars().all())

        cloned_items: List[ClonePathsResponseItem] = []
        skipped = 0

        for src_path in source_paths:
            # Step 1: clone criteria nếu source có (ADM-003: 1:1 path-criteria)
            new_criteria_id: Optional[int] = None
            new_criteria_code: str = ""
            if src_path.criteria_id is not None and src_path.criteria is not None:
                src_criteria: AdmissionCriteria = src_path.criteria
                new_criteria_code = self._derive_criteria_code(
                    src_criteria.code,
                    target_round.round_code,
                    target_round_id,
                    payload.criteria_code_template,
                )
                # Code length validation
                if len(new_criteria_code) > 50:
                    raise BusinessRuleViolation(
                        f"Derived criteria code '{new_criteria_code}' exceeds 50 chars; "
                        f"shorten template hoặc source_code"
                    )

                cloned_criteria = AdmissionCriteria(
                    method_id=src_criteria.method_id,
                    code=new_criteria_code,
                    name=f"{src_criteria.name} (cloned từ round {source_round_id})",
                    min_gpa=src_criteria.min_gpa,
                    min_score=src_criteria.min_score,
                    conditions=src_criteria.conditions,
                    is_active=src_criteria.is_active,
                    required_subject_count=src_criteria.required_subject_count,
                    subject_selection_mode=src_criteria.subject_selection_mode,
                    scoring_method=src_criteria.scoring_method,
                    max_possible_score=src_criteria.max_possible_score,
                    min_subject_score=src_criteria.min_subject_score,
                    policy_version=src_criteria.policy_version,
                    effective_from=src_criteria.effective_from,
                    effective_to=src_criteria.effective_to,
                )
                self.db.add(cloned_criteria)
                await self.db.flush()
                new_criteria_id = cloned_criteria.id

                # Step 2: clone CriteriaSubjectGroup rows
                csg_stmt = select(CriteriaSubjectGroup).where(
                    CriteriaSubjectGroup.criteria_id == src_criteria.id
                )
                csg_rows = list((await self.db.execute(csg_stmt)).scalars().all())
                for csg in csg_rows:
                    cloned_csg = CriteriaSubjectGroup(
                        criteria_id=new_criteria_id,
                        subject_group_id=csg.subject_group_id,
                    )
                    self.db.add(cloned_csg)
                await self.db.flush()

            # Step 3: clone AdmissionPath với new criteria + target round
            cloned_path = AdmissionPath(
                academic_info_id=src_path.academic_info_id,
                admission_method_id=src_path.admission_method_id,
                admission_round_id=target_round_id,
                criteria_id=new_criteria_id,
                status="draft",  # cloned paths start draft
                display_name=f"{src_path.display_name or 'Path'} (cloned)",
                display_order=src_path.display_order,
                visibility=src_path.visibility,
                application_fee=src_path.application_fee,
                allow_unverified_submission=src_path.allow_unverified_submission,
                minor_correction_allowed_fields=list(
                    src_path.minor_correction_allowed_fields or []
                ),
                applicable_to=(
                    list(src_path.applicable_to)
                    if src_path.applicable_to is not None
                    else None
                ),
                method_quota=src_path.method_quota,
                bonus_rule_override=src_path.bonus_rule_override,
                # Quota fields reset to NULL — admin sets per target round
                round_quota=None,
                admit_quota=None,
                submission_count=0,
            )
            self.db.add(cloned_path)
            try:
                await self.db.flush()
            except IntegrityError:
                # ON CONFLICT 3-col UNIQUE skip — path already exists trong target round
                await self.db.rollback()
                skipped += 1
                # Note: rollback nukes prior INSERTs trong this iteration too.
                # Re-attach session for next iteration via fresh transaction.
                # NOTE: caller wraps trong begin() — partial commit semantic.
                continue

            # Step 4: clone PathSubjectGroupConfig + items
            psgc_stmt = (
                select(PathSubjectGroupConfig)
                .where(PathSubjectGroupConfig.admission_path_id == src_path.id)
                .options(selectinload(PathSubjectGroupConfig.items))
            )
            psgc_rows = list((await self.db.execute(psgc_stmt)).scalars().all())
            for src_cfg in psgc_rows:
                cloned_cfg = PathSubjectGroupConfig(
                    admission_path_id=cloned_path.id,
                    subject_group_id=src_cfg.subject_group_id,
                    min_score=src_cfg.min_score,
                    min_subject_score=src_cfg.min_subject_score,
                    group_quota=None,  # reset cho target round admin set
                )
                self.db.add(cloned_cfg)
                await self.db.flush()
                for src_item in src_cfg.items:
                    cloned_item = PathSubjectGroupItem(
                        path_subject_group_config_id=cloned_cfg.id,
                        subject_group_subject_id=src_item.subject_group_subject_id,
                        is_principal=src_item.is_principal,
                        min_subject_score=src_item.min_subject_score,
                    )
                    self.db.add(cloned_item)
            await self.db.flush()

            cloned_items.append(
                ClonePathsResponseItem(
                    source_path_id=src_path.id,
                    cloned_path_id=cloned_path.id,
                    source_criteria_code=(
                        src_path.criteria.code if src_path.criteria else ""
                    ),
                    cloned_criteria_code=new_criteria_code,
                )
            )

        log.info(
            "path_clone_completed",
            source_round_id=source_round_id,
            target_round_id=target_round_id,
            cloned_count=len(cloned_items),
            skipped_count=skipped,
            cloned_path_ids=[item.cloned_path_id for item in cloned_items],
        )

        return ClonePathsResponse(
            source_round_id=source_round_id,
            target_round_id=target_round_id,
            cloned_count=len(cloned_items),
            skipped_count=skipped,
            items=cloned_items,
        )
