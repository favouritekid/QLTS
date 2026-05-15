# app/repositories/path_subject_group_repository.py
"""Repository cho PathSubjectGroupConfig + Item (Phase 2 v8.2 PR-2D)."""

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.admission_config import PathSubjectGroupConfig, PathSubjectGroupItem


class PathSubjectGroupRepository:
    """Repository cho path-level subject group config CRUD."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_config_by_id(
        self, config_id: int, *, with_items: bool = True
    ) -> Optional[PathSubjectGroupConfig]:
        stmt = select(PathSubjectGroupConfig).where(
            PathSubjectGroupConfig.id == config_id
        )
        if with_items:
            stmt = stmt.options(selectinload(PathSubjectGroupConfig.items))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_configs_by_path(
        self, admission_path_id: int
    ) -> List[PathSubjectGroupConfig]:
        stmt = (
            select(PathSubjectGroupConfig)
            .where(PathSubjectGroupConfig.admission_path_id == admission_path_id)
            .options(selectinload(PathSubjectGroupConfig.items))
            .order_by(PathSubjectGroupConfig.subject_group_id)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_configs_by_path_with_subjects(
        self, admission_path_id: int
    ) -> List[PathSubjectGroupConfig]:
        """Phase 3 multi-NV AddChoiceDialog support: eager-load subject_group
        + subject_mappings → subject for FE render score input forms.

        Single round-trip: configs → subject_group → mappings → subject.
        FE consumer needs subject.code/name/max_score per dropdown option.
        """
        from app.models.admission_config.subject import (
            SubjectGroup,
            SubjectGroupSubject,
        )
        stmt = (
            select(PathSubjectGroupConfig)
            .where(PathSubjectGroupConfig.admission_path_id == admission_path_id)
            .options(
                selectinload(PathSubjectGroupConfig.items),
                selectinload(PathSubjectGroupConfig.subject_group)
                .selectinload(SubjectGroup.subject_mappings)
                .selectinload(SubjectGroupSubject.subject),
            )
            .order_by(PathSubjectGroupConfig.subject_group_id)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_config_by_path_and_group(
        self, admission_path_id: int, subject_group_id: int
    ) -> Optional[PathSubjectGroupConfig]:
        stmt = select(PathSubjectGroupConfig).where(
            PathSubjectGroupConfig.admission_path_id == admission_path_id,
            PathSubjectGroupConfig.subject_group_id == subject_group_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def sum_group_quota_by_path(
        self,
        admission_path_id: int,
        *,
        excluded_config_id: Optional[int] = None,
    ) -> int:
        """Sum group_quota in path (Tier 3 chain compute baseline).

        Excluded_config_id supports update flow (subtract current row's
        contribution before computing new sum).
        """
        stmt = select(func.coalesce(func.sum(PathSubjectGroupConfig.group_quota), 0)).where(
            PathSubjectGroupConfig.admission_path_id == admission_path_id,
            PathSubjectGroupConfig.group_quota.is_not(None),
        )
        if excluded_config_id is not None:
            stmt = stmt.where(PathSubjectGroupConfig.id != excluded_config_id)
        return int((await self.db.execute(stmt)).scalar_one())
