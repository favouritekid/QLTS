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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.admission_config import (
    AdmissionPath,
    PathSubjectGroupConfig,
    PathSubjectGroupItem,
    SubjectGroup,
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
    ConflictError,
    DuplicateResourceError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


class PathSubjectGroupService:
    """Service for path-level subject group config (Phase 2 v8.2 PR-2D)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PathSubjectGroupRepository(db)

    async def _require_writable_path(self, admission_path_id: int) -> AdmissionPath:
        """Load the path or 404; block writes on an archived path.

        Mirrors the AdmissionPathService lifecycle guard for archived paths.
        All config/item mutations run through this so a bad ``admission_path_id``
        surfaces as a clean 404 (instead of falling through to an FK 500) and
        archived paths reject with a domain 400. Routes are ``require_admin`` so
        no manager branch is needed here.
        """
        path = (
            await self.db.execute(
                select(AdmissionPath).where(AdmissionPath.id == admission_path_id)
            )
        ).scalar_one_or_none()
        if path is None:
            raise ResourceNotFoundError(
                f"AdmissionPath {admission_path_id} not found"
            )
        if path.status == "archived":
            raise BusinessRuleViolation(
                "Không thể sửa tổ hợp môn của đường tuyển sinh đã lưu trữ "
                "(archived)."
            )
        return path

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
        await self._require_writable_path(admission_path_id)

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
        # Reject a duplicated payload item (FE double-add) up front — the
        # composite-invariant check dedups via id.in_(set) so it would NOT catch
        # it, and the insert would otherwise hit uq_path_subject_group_item.
        if len(item_sgs_ids) != len(set(item_sgs_ids)):
            raise DuplicateResourceError(
                "Danh sách môn (items) có subject_group_subject_id trùng lặp."
            )
        await self._validate_composite_invariant(
            payload.subject_group_id, item_sgs_ids
        )
        # When NO items, the composite invariant is skipped, so a bad
        # subject_group_id would only surface at the FK (→ 500). Validate here.
        if not item_sgs_ids:
            sg_exists = (
                await self.db.execute(
                    select(SubjectGroup.id).where(
                        SubjectGroup.id == payload.subject_group_id
                    )
                )
            ).scalar_one_or_none()
            if sg_exists is None:
                raise ResourceNotFoundError(
                    f"SubjectGroup {payload.subject_group_id} not found"
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
        # config + items in ONE savepoint so ANY UNIQUE violation — the config
        # (admission_path_id, subject_group_id) race OR a duplicated payload
        # item hitting uq_path_subject_group_item — maps to a clean 409, not an
        # IntegrityError 500. (Payload item dup is also prechecked above for a
        # clearer message; the config dup is prechecked via get_config_*.)
        try:
            async with self.db.begin_nested():
                await self.db.flush()  # config insert
                for item_payload in payload.items:
                    self.db.add(PathSubjectGroupItem(
                        path_subject_group_config_id=config.id,
                        subject_group_subject_id=(
                            item_payload.subject_group_subject_id
                        ),
                        is_principal=item_payload.is_principal,
                        min_subject_score=item_payload.min_subject_score,
                    ))
                await self.db.flush()  # items insert
        except IntegrityError:
            raise DuplicateResourceError(
                f"Tổ hợp trùng cho path={admission_path_id}, subject_group="
                f"{payload.subject_group_id} (hoặc môn lặp trong danh sách)."
            )

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
        await self._require_writable_path(config.admission_path_id)

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
        await self._require_writable_path(config.admission_path_id)

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
        # Savepoint: UNIQUE(config_id, subject_group_subject_id) dup → 409, not
        # an IntegrityError 500.
        try:
            async with self.db.begin_nested():
                await self.db.flush()
        except IntegrityError:
            raise DuplicateResourceError(
                f"Môn (subject_group_subject={payload.subject_group_subject_id}) "
                f"đã có trong tổ hợp này."
            )

        log.info(
            "path_subject_group_item_added",
            config_id=config_id,
            item_id=item.id,
        )
        return item

    async def delete_config(self, config_id: int) -> None:
        """Delete config (cascade items). Blocks if a choice references it."""
        config = await self.repo.get_config_by_id(config_id, with_items=False)
        if config is None:
            raise ResourceNotFoundError(f"Config {config_id} not found")
        await self._require_writable_path(config.admission_path_id)

        # FK admission_profile_choice.path_subject_group_config_id is RESTRICT.
        used = await self.repo.count_choices_by_config(config_id)
        if used > 0:
            raise ConflictError(
                f"Không thể xóa: tổ hợp đang được {used} nguyện vọng sử dụng."
            )
        # Savepoint catches the race where a choice is created after the
        # precheck (still RESTRICT → IntegrityError) → clean 409, not 500.
        try:
            async with self.db.begin_nested():
                await self.db.delete(config)
                await self.db.flush()
        except IntegrityError:
            raise ConflictError(
                "Không thể xóa: tổ hợp đang được nguyện vọng sử dụng."
            )
        log.info("path_subject_group_config_deleted", config_id=config_id)

    async def update_item(
        self,
        config_id: int,
        item_id: int,
        payload: PathSubjectGroupItemUpdate,
    ) -> PathSubjectGroupItem:
        """Update an item's is_principal / min_subject_score, scoped to its
        config. ``subject_group_subject_id`` is NOT mutable here, so neither the
        composite invariant nor the item UNIQUE can be violated."""
        config = await self.repo.get_config_by_id(config_id, with_items=False)
        if config is None:
            raise ResourceNotFoundError(f"Config {config_id} not found")
        await self._require_writable_path(config.admission_path_id)

        item = (
            await self.db.execute(
                select(PathSubjectGroupItem).where(
                    PathSubjectGroupItem.id == item_id,
                    PathSubjectGroupItem.path_subject_group_config_id == config_id,
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise ResourceNotFoundError(
                f"Item {item_id} not found trong config {config_id}"
            )

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)
        await self.db.flush()
        log.info(
            "path_subject_group_item_updated",
            config_id=config_id,
            item_id=item_id,
            fields=list(update_data.keys()),
        )
        return item

    async def delete_item(self, config_id: int, item_id: int) -> None:
        """Delete an item scoped to its config (avoids cross-config IDOR)."""
        config = await self.repo.get_config_by_id(config_id, with_items=False)
        if config is None:
            raise ResourceNotFoundError(f"Config {config_id} not found")
        await self._require_writable_path(config.admission_path_id)

        item = (
            await self.db.execute(
                select(PathSubjectGroupItem).where(
                    PathSubjectGroupItem.id == item_id,
                    PathSubjectGroupItem.path_subject_group_config_id == config_id,
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise ResourceNotFoundError(
                f"Item {item_id} not found trong config {config_id}"
            )
        await self.db.delete(item)
        await self.db.flush()
        log.info(
            "path_subject_group_item_deleted",
            config_id=config_id,
            item_id=item_id,
        )
