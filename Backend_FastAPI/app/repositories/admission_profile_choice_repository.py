# app/repositories/admission_profile_choice_repository.py
"""Repository for AdmissionProfileChoice + ProfileChoiceScore — Phase 3 PR-3A.

Per plan v0.6 LOCKED + UI design v0.6:

- **GAP-22 N+1 prevention**: selectinload chain pre-load admission_path
  (academic_info → program, admission_method, admission_round) +
  path_subject_group_config (subject_group) + scores (subject).
- **G7 service guard support**: `count_choices_by_profile` cho add_choice
  precheck.
- **Q-P3-02 per-round allow_multi_nv**: `get_round_by_path_id` lookup.
- **GAP-16 engine atomicity** (PR-3C scope): `get_choice_for_engine_with_lock`
  với SELECT FOR UPDATE — KHÔNG implement trong PR-3A, defer PR-3C.
"""
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AdmissionPath,
    AdmissionProfileChoice,
    OfferingAdmissionRound,
    ProfileChoiceScore,
)


class AdmissionProfileChoiceRepository:
    """Data access cho multi-NV choices."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============================================================
    # READ
    # ============================================================

    async def get_by_id(
        self, choice_id: int
    ) -> Optional[AdmissionProfileChoice]:
        """Plain get. Use ``get_by_id_with_relations`` cho UI/computed fields."""
        return await self.db.get(AdmissionProfileChoice, choice_id)

    async def get_by_id_with_relations(
        self, choice_id: int
    ) -> Optional[AdmissionProfileChoice]:
        """GAP-22: selectinload chain — Contract-06 computed display fields.

        Chain pre-loads:
        - admission_path → academic_info + admission_method + admission_round
        - path_subject_group_config → subject_group (Contract-06 fix v0.6)
        - scores → subject
        """
        # Imports local để tránh circular
        from app.models.admission_config.path_subject_group import (
            PathSubjectGroupConfig,
        )

        result = await self.db.execute(
            select(AdmissionProfileChoice)
            .where(AdmissionProfileChoice.id == choice_id)
            .options(
                # admission_path → academic_info (program) + method + round
                selectinload(AdmissionProfileChoice.admission_path).selectinload(
                    AdmissionPath.academic_info
                ),
                selectinload(AdmissionProfileChoice.admission_path).selectinload(
                    AdmissionPath.admission_method
                ),
                # admission_round qua AdmissionPath FK chain (Contract-06)
                selectinload(AdmissionProfileChoice.admission_path).selectinload(
                    AdmissionPath.admission_round
                ),
                # path_subject_group_config → subject_group (Contract-06)
                selectinload(
                    AdmissionProfileChoice.path_subject_group_config
                ).selectinload(PathSubjectGroupConfig.subject_group),
                # scores → subject (via choice.scores.selectinload trong model)
                selectinload(AdmissionProfileChoice.scores).selectinload(
                    ProfileChoiceScore.subject
                ),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_profile(
        self, profile_id: int, *, eager: bool = True
    ) -> List[AdmissionProfileChoice]:
        """List choices của 1 profile ordered by display_order.

        Args:
            eager: True → selectinload relations cho UI render.
                   False → plain query (engine internal, just needs IDs).
        """
        stmt = (
            select(AdmissionProfileChoice)
            .where(
                AdmissionProfileChoice.admission_profile_id == profile_id
            )
            .order_by(AdmissionProfileChoice.display_order)
        )
        if eager:
            from app.models.admission_config.path_subject_group import (
                PathSubjectGroupConfig,
            )
            stmt = stmt.options(
                selectinload(AdmissionProfileChoice.admission_path).selectinload(
                    AdmissionPath.academic_info
                ),
                selectinload(AdmissionProfileChoice.admission_path).selectinload(
                    AdmissionPath.admission_method
                ),
                selectinload(
                    AdmissionProfileChoice.path_subject_group_config
                ).selectinload(PathSubjectGroupConfig.subject_group),
                selectinload(AdmissionProfileChoice.scores).selectinload(
                    ProfileChoiceScore.subject
                ),
            )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_choices_by_profile(self, profile_id: int) -> int:
        """G7 v0.6 service guard support — service `add_choice` precheck count."""
        result = await self.db.execute(
            select(func.count(AdmissionProfileChoice.id)).where(
                AdmissionProfileChoice.admission_profile_id == profile_id
            )
        )
        return int(result.scalar() or 0)

    async def get_round_by_path_id(
        self, path_id: int
    ) -> Optional[OfferingAdmissionRound]:
        """Q-P3-02 lookup — service guard `add_choice` cần check
        `round.allow_multi_nv` flag từ path FK chain.
        """
        result = await self.db.execute(
            select(OfferingAdmissionRound)
            .join(AdmissionPath, AdmissionPath.admission_round_id == OfferingAdmissionRound.id)
            .where(AdmissionPath.id == path_id)
        )
        return result.scalar_one_or_none()

    # ============================================================
    # WRITE
    # ============================================================

    async def create(
        self,
        *,
        admission_profile_id: int,
        admission_path_id: int,
        path_subject_group_config_id: int,
        display_order: int,
    ) -> AdmissionProfileChoice:
        """Create choice row. Service-layer enforce invariants TRƯỚC khi gọi.

        Caller responsible:
        - count_choices < max_choices_per_profile (G7)
        - allow_multi_nv check (Q-P3-02)
        - path_subject_group_config.admission_path_id == admission_path_id
          (P1 fix #4 v1.3 invariant)
        - profile.status IN (draft, revision_requested) for Wave B add
        """
        choice = AdmissionProfileChoice(
            admission_profile_id=admission_profile_id,
            admission_path_id=admission_path_id,
            path_subject_group_config_id=path_subject_group_config_id,
            display_order=display_order,
            decision="pending",
        )
        self.db.add(choice)
        await self.db.flush()
        return choice

    async def update_decision(
        self,
        choice_id: int,
        *,
        decision: str,
        waitlist_rank: Optional[int] = None,
        eligibility_check_result: Optional[dict] = None,
        bonus_rule_snapshot: Optional[dict] = None,
    ) -> Optional[AdmissionProfileChoice]:
        """Engine writer — T6 publish. PR-3C engine uses this method.

        Caller (engine) wraps trong begin_nested + SELECT FOR UPDATE per
        GAP-16 atomicity.
        """
        choice = await self.db.get(AdmissionProfileChoice, choice_id)
        if choice is None:
            return None
        choice.decision = decision
        if waitlist_rank is not None:
            choice.waitlist_rank = waitlist_rank
        if eligibility_check_result is not None:
            choice.eligibility_check_result = eligibility_check_result
        if bonus_rule_snapshot is not None:
            choice.bonus_rule_snapshot = bonus_rule_snapshot
        await self.db.flush()
        return choice

    async def update_display_order(
        self, choice_id: int, *, new_display_order: int
    ) -> Optional[AdmissionProfileChoice]:
        """Admin manual reorder. UNIQUE constraint chặn duplicate priority."""
        choice = await self.db.get(AdmissionProfileChoice, choice_id)
        if choice is None:
            return None
        choice.display_order = new_display_order
        await self.db.flush()
        return choice

    async def delete(self, choice_id: int) -> bool:
        """Delete choice. CASCADE clears profile_choice_score via FK
        (GAP-18 v0.6 ON DELETE CASCADE).
        """
        choice = await self.db.get(AdmissionProfileChoice, choice_id)
        if choice is None:
            return False
        await self.db.delete(choice)
        await self.db.flush()
        return True

    # ============================================================
    # SCORE METHODS (ProfileChoiceScore)
    # ============================================================

    async def add_score(
        self,
        *,
        admission_profile_choice_id: int,
        subject_id: int,
        score,
        max_score_snapshot,
        weight_snapshot,
        min_possible_score_snapshot=None,
    ) -> ProfileChoiceScore:
        """Add 1 score row per (choice, subject). UNIQUE chặn duplicate."""
        score_row = ProfileChoiceScore(
            admission_profile_choice_id=admission_profile_choice_id,
            subject_id=subject_id,
            score=score,
            max_score_snapshot=max_score_snapshot,
            weight_snapshot=weight_snapshot,
            min_possible_score_snapshot=min_possible_score_snapshot,
        )
        self.db.add(score_row)
        await self.db.flush()
        return score_row

    async def list_scores_by_choice(
        self, choice_id: int
    ) -> List[ProfileChoiceScore]:
        """List scores per choice, eager-load subject."""
        result = await self.db.execute(
            select(ProfileChoiceScore)
            .where(
                ProfileChoiceScore.admission_profile_choice_id == choice_id
            )
            .options(selectinload(ProfileChoiceScore.subject))
        )
        return list(result.scalars().all())
