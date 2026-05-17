# app/repositories/priority_config_repository.py
"""Repository for priority_area_config + priority_object_config.

Single repo handles both tables since they share the temporal + active-
filter idiom; service layer (priority_config_service) provides the
domain-level methods.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.priority_config import PriorityAreaConfig, PriorityObjectConfig


class PriorityConfigRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ----- Area -----

    async def list_areas(
        self, academic_year: int, active_only: bool = False
    ) -> list[PriorityAreaConfig]:
        stmt = select(PriorityAreaConfig).where(
            PriorityAreaConfig.academic_year == academic_year
        )
        if active_only:
            stmt = stmt.where(PriorityAreaConfig.effective_to.is_(None))
        stmt = stmt.order_by(PriorityAreaConfig.area_code)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_area(self, area_id: int) -> Optional[PriorityAreaConfig]:
        return await self.db.get(PriorityAreaConfig, area_id)

    async def get_active_area(
        self, academic_year: int, area_code: str
    ) -> Optional[PriorityAreaConfig]:
        stmt = (
            select(PriorityAreaConfig)
            .where(
                PriorityAreaConfig.academic_year == academic_year,
                PriorityAreaConfig.area_code == area_code,
                PriorityAreaConfig.effective_to.is_(None),
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_area(
        self, data: dict
    ) -> PriorityAreaConfig:
        row = PriorityAreaConfig(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def update_area(
        self, row: PriorityAreaConfig, data: dict
    ) -> PriorityAreaConfig:
        for k, v in data.items():
            setattr(row, k, v)
        await self.db.flush()
        return row

    async def retire_area(
        self, row: PriorityAreaConfig, effective_to: date
    ) -> PriorityAreaConfig:
        """Soft-delete via effective_to (temporal versioning)."""
        row.effective_to = effective_to
        await self.db.flush()
        return row

    # ----- Object -----

    async def list_objects(
        self, academic_year: int, active_only: bool = False
    ) -> list[PriorityObjectConfig]:
        stmt = select(PriorityObjectConfig).where(
            PriorityObjectConfig.academic_year == academic_year
        )
        if active_only:
            stmt = stmt.where(PriorityObjectConfig.effective_to.is_(None))
        stmt = stmt.order_by(
            PriorityObjectConfig.group_code, PriorityObjectConfig.sub_code
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_object(self, obj_id: int) -> Optional[PriorityObjectConfig]:
        return await self.db.get(PriorityObjectConfig, obj_id)

    async def get_active_object(
        self, academic_year: int, sub_code: str
    ) -> Optional[PriorityObjectConfig]:
        stmt = (
            select(PriorityObjectConfig)
            .where(
                PriorityObjectConfig.academic_year == academic_year,
                PriorityObjectConfig.sub_code == sub_code,
                PriorityObjectConfig.effective_to.is_(None),
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_object(self, data: dict) -> PriorityObjectConfig:
        row = PriorityObjectConfig(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def update_object(
        self, row: PriorityObjectConfig, data: dict
    ) -> PriorityObjectConfig:
        for k, v in data.items():
            setattr(row, k, v)
        await self.db.flush()
        return row

    async def retire_object(
        self, row: PriorityObjectConfig, effective_to: date
    ) -> PriorityObjectConfig:
        row.effective_to = effective_to
        await self.db.flush()
        return row
