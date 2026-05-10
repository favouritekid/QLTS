# app/services/path_subject_group_service.py
"""Path-level Subject Group Config service (Phase 2 v8.2 PR-2D).

Implements:
- CRUD config + items với composite invariant guard
- Tier 3 chain validation: ∑(group_quota in path) ≤ path.admit_quota
- Composite invariant: subject_group_subject.subject_group_id ==
  config.subject_group_id (service-layer assert)
"""

from typing import List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.admission_config import (
    AdmissionPath,
    PathSubjectGroupConfig,
    PathSubjectGroupItem,
    SubjectGroupSubject,
)
from app.repositories.path_subject_group_repository import PathSubjectGroupRepository
from app.schemas.path_subject_group import (
    PathSubjectGroupConfigCreate,
    PathSubjectGroupConfigUpdate,
    PathSubjectGroupItemCreate,
    PathSubjectGroupItemUpdate,
)
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


class PathSubjectGroupService:
    """Service for path-level subject group config (Phase 2 v8.2 PR-2D)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PathSubjectGroupRepository(db)

    async def validate_tier3_chain(
        self,
        admission_path_id: int,
        delta_group_quota: int,
        *,
        excluded_config_id: int | None = None,
    ) -> None:
        """Tier 3 quota chain: ∑(group_quota in path) + delta ≤ path.admit_quota.

        Pattern A: SELECT FOR UPDATE admission_path row trước compute sum
        cho race-safety (PLAN §5.a). NULL admit_quota = unbounded → no check.
        """
        path_stmt = (
            select(AdmissionPath)
            .where(AdmissionPath.id == admission_path_id)
            .with_for_update()
        )
        path = (await self.db.execute(path_stmt)).scalar_one_or_none()
        if path is None:
            raise ResourceNotFoundError(
                f"AdmissionPath {admission_path_id} not found"
            )

        admit_quota = path.admit_quota
        if admit_quota is None:
            return  # Unbounded admit_quota → Tier 3 inactive

        current_sum = await self.repo.sum_group_quota_by_path(
            admission_path_id, excluded_config_id=excluded_config_id
        )
        new_sum = current_sum + delta_group_quota
        if new_sum > admit_quota:
            raise BusinessRuleViolation(
                f"Tier 3 chain violated: ∑(group_quota) = {new_sum} "
                f"vượt path.admit_quota={admit_quota} "
                f"(current_sum={current_sum}, delta={delta_group_quota})"
            )

    async def _validate_composite_invariant(
        self,
        config_subject_group_id: int,
        subject_group_subject_ids: List[int],
    ) -> None:
        """Composite invariant: SubjectGroupSubject.subject_group_id MUST
        equal config.subject_group_id cho mọi item trong config."""
        if not subject_group_subject_ids:
            return
        stmt = select(SubjectGroupSubject).where(
            SubjectGroupSubject.id.in_(subject_group_subject_ids)
        )
        rows = list((await self.db.execute(stmt)).scalars().all())
        for sgs in rows:
            if sgs.subject_group_id != config_subject_group_id:
                raise BusinessRuleViolation(
                    f"Composite invariant violated: SubjectGroupSubject {sgs.id} "
                    f"belongs to subject_group {sgs.subject_group_id}, "
                    f"nhưng config gán cho subject_group {config_subject_group_id}"
                )
        # Verify all IDs exist
        found_ids = {r.id for r in rows}
        missing = set(subject_group_subject_ids) - found_ids
        if missing:
            raise ResourceNotFoundError(
                f"SubjectGroupSubject IDs not found: {sorted(missing)}"
            )

    async def create_config(
        self,
        admission_path_id: int,
        payload: PathSubjectGroupConfigCreate,
    ) -> PathSubjectGroupConfig:
        """Create config + items atomic.

        Guards:
        - UNIQUE(admission_path_id, subject_group_id) — DuplicateResourceError
        - Composite invariant — BusinessRuleViolation
        - Tier 3 chain (if group_quota set) — BusinessRuleViolation
        """
        existing = await self.repo.get_config_by_path_and_group(
            admission_path_id, payload.subject_group_id
        )
        if existing is not None:
            raise DuplicateResourceError(
                f"PathSubjectGroupConfig đã tồn tại cho path={admission_path_id}, "
                f"subject_group={payload.subject_group_id}"
            )

        # Composite invariant check (if items provided)
        item_sgs_ids = [item.subject_group_subject_id for item in payload.items]
        await self._validate_composite_invariant(
            payload.subject_group_id, item_sgs_ids
        )

        # Tier 3 chain check (if group_quota provided)
        if payload.group_quota is not None:
            await self.validate_tier3_chain(
                admission_path_id, delta_group_quota=payload.group_quota
            )

        config = PathSubjectGroupConfig(
            admission_path_id=admission_path_id,
            subject_group_id=payload.subject_group_id,
            min_score=payload.min_score,
            min_subject_score=payload.min_subject_score,
            group_quota=payload.group_quota,
        )
        self.db.add(config)
        await self.db.flush()

        for item_payload in payload.items:
            item = PathSubjectGroupItem(
                path_subject_group_config_id=config.id,
                subject_group_subject_id=item_payload.subject_group_subject_id,
                is_principal=item_payload.is_principal,
                min_subject_score=item_payload.min_subject_score,
            )
            self.db.add(item)
        await self.db.flush()

        log.info(
            "path_subject_group_config_created",
            config_id=config.id,
            admission_path_id=admission_path_id,
            subject_group_id=payload.subject_group_id,
            item_count=len(payload.items),
        )
        return config

    async def update_config(
        self,
        config_id: int,
        payload: PathSubjectGroupConfigUpdate,
    ) -> PathSubjectGroupConfig:
        """Update config — score thresholds + group_quota.

        Tier 3 chain re-validated nếu group_quota changed.
        """
        config = await self.repo.get_config_by_id(config_id)
        if config is None:
            raise ResourceNotFoundError(f"Config {config_id} not found")

        update_data = payload.model_dump(exclude_unset=True)

        if "group_quota" in update_data:
            new_quota = update_data["group_quota"]
            if new_quota is not None:
                await self.validate_tier3_chain(
                    config.admission_path_id,
                    delta_group_quota=new_quota,
                    excluded_config_id=config_id,
                )

        for field, value in update_data.items():
            setattr(config, field, value)

        await self.db.flush()
        log.info(
            "path_subject_group_config_updated",
            config_id=config_id,
            fields=list(update_data.keys()),
        )
        return config

    async def add_item(
        self,
        config_id: int,
        payload: PathSubjectGroupItemCreate,
    ) -> PathSubjectGroupItem:
        """Add item to config với composite invariant guard."""
        config = await self.repo.get_config_by_id(config_id)
        if config is None:
            raise ResourceNotFoundError(f"Config {config_id} not found")

        await self._validate_composite_invariant(
            config.subject_group_id, [payload.subject_group_subject_id]
        )

        item = PathSubjectGroupItem(
            path_subject_group_config_id=config_id,
            subject_group_subject_id=payload.subject_group_subject_id,
            is_principal=payload.is_principal,
            min_subject_score=payload.min_subject_score,
        )
        self.db.add(item)
        await self.db.flush()

        log.info(
            "path_subject_group_item_added",
            config_id=config_id,
            item_id=item.id,
        )
        return item

    async def delete_config(self, config_id: int) -> None:
        """Delete config + cascade items."""
        config = await self.repo.get_config_by_id(config_id, with_items=False)
        if config is None:
            raise ResourceNotFoundError(f"Config {config_id} not found")
        await self.db.delete(config)
        await self.db.flush()
        log.info("path_subject_group_config_deleted", config_id=config_id)
