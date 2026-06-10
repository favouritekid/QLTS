# app/repositories/administrative_repository.py
"""
Repository for administrative nodes (provinces, districts, wards).

Two distinct snapshots in DB:
- Legacy (valid_to IS NOT NULL): 63 provinces, 3-level (province → district → ward)
- Current (valid_to IS NULL):    34 provinces, 2-level (province → ward)

All public methods require an explicit `current` flag to select the snapshot.
"""

from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.administrative_node import AdministrativeNode, AdministrativeLevel
from app.repositories.base import BaseRepository


class AdministrativeRepository(BaseRepository[AdministrativeNode]):
    """Repository for administrative node queries."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, AdministrativeNode)

    # ------------------------------------------------------------------
    # PROVINCES
    # ------------------------------------------------------------------

    async def get_provinces(self, *, current: bool) -> list[AdministrativeNode]:
        """
        Get provinces for a specific era.

        current=True  → 34 provinces (valid_to IS NULL)
        current=False → 63 legacy provinces (valid_to IS NOT NULL)
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.PROVINCE)
            .where(AdministrativeNode.is_active == True)
        )
        if current:
            stmt = stmt.where(AdministrativeNode.valid_to.is_(None))
        else:
            stmt = stmt.where(AdministrativeNode.valid_to.isnot(None))
        stmt = stmt.order_by(AdministrativeNode.code)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # DISTRICTS (legacy only — current has no districts)
    # ------------------------------------------------------------------

    async def get_districts_by_province(self, province_code: str) -> list[AdministrativeNode]:
        """
        Get districts under a legacy province (3-level structure).
        Districts only exist in the legacy snapshot.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.DISTRICT)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.valid_to.isnot(None))  # legacy only
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # WARDS
    # ------------------------------------------------------------------

    async def get_wards_by_province(self, province_code: str) -> list[AdministrativeNode]:
        """
        Get wards directly under a current province (2-level structure).
        These wards have district_code = NULL and valid_to IS NULL.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.district_code.is_(None))
            .where(AdministrativeNode.valid_to.is_(None))
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_wards_by_district(
        self,
        province_code: str,
        district_code: str,
    ) -> list[AdministrativeNode]:
        """
        Get wards under a specific legacy district (3-level structure).
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.district_code == district_code)
            .where(AdministrativeNode.valid_to.isnot(None))  # legacy only
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # REVERSE LOOKUP
    # ------------------------------------------------------------------

    async def find_old_ward_by_code(self, ward_code: str) -> Optional[AdministrativeNode]:
        """
        Find the legacy (3-level) ward record by code.
        Used to lookup which district a ward belonged to.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.code == ward_code)
            .where(AdministrativeNode.valid_to.isnot(None))
            .where(AdministrativeNode.is_active == True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def resolve_current_ward_code(self, ward_code: str) -> Optional[str]:
        """Resolve ANY ward code (current or legacy) to its CURRENT-era commune
        code via ``successor_ward_code`` (PR-2 cross-era lineage).

        * current / survived ward → its own code (identity backfill)
        * legacy ward merged into a new commune → the new commune code
        * unknown code, or legacy ward with no successor mapped yet → ``None``

        Caller fail-closes on ``None`` (officer re-picks current commune), so a
        profile never persists a stale legacy code.
        """
        code = (ward_code or "").strip()
        if not code:
            return None
        stmt = (
            select(AdministrativeNode.successor_ward_code)
            .where(
                AdministrativeNode.code == code,
                AdministrativeNode.level == AdministrativeLevel.WARD,
                AdministrativeNode.successor_ward_code.isnot(None),
            )
            # A GSO ward code can be REUSED across the 2025 reform (the same code
            # exists in BOTH the legacy and current snapshots — e.g. 24717 =
            # legacy "Thị trấn Đức An" AND current "Xã Đức An"). The CURRENT-era
            # row (valid_to IS NULL) is authoritative: its successor is the live
            # commune. Order current-first so resolution is DETERMINISTIC and
            # correct regardless of row/scan order — a bare ``.limit(1)`` would
            # pick an arbitrary era when the code collides.
            .order_by(AdministrativeNode.valid_to.is_(None).desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_current_commune_display(
        self, ward_code: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Display tuple ``(ward_name, province_name)`` for a CURRENT-era ward code.

        ONE query for the ward row (name + province_code) + ONE for the province
        name — both ``valid_to IS NULL``. Powers the resolve-ward endpoint's full
        2-level address ("Xã X, Tỉnh Y") so the officer confirms the standardized
        residence (NĐ 238/NĐ-CP KV/miễn-giảm). Was 3 sequential round-trips when
        the ward name + province were fetched separately (review #5).

        Returns ``(None, None)`` if the code isn't a current-era commune;
        ``(name, None)`` if its current province can't be resolved.
        """
        code = (ward_code or "").strip()
        if not code:
            return None, None
        ward = (
            await self.db.execute(
                select(
                    AdministrativeNode.name,
                    AdministrativeNode.province_code,
                )
                .where(
                    AdministrativeNode.code == code,
                    AdministrativeNode.level == AdministrativeLevel.WARD,
                    AdministrativeNode.valid_to.is_(None),
                    AdministrativeNode.is_active.is_(True),
                )
                .limit(1)
            )
        ).first()
        if ward is None:
            return None, None
        ward_name, province_code = ward
        if not province_code:
            return ward_name, None
        province_name = await self.db.scalar(
            select(AdministrativeNode.name)
            .where(
                AdministrativeNode.code == province_code,
                AdministrativeNode.level == AdministrativeLevel.PROVINCE,
                AdministrativeNode.valid_to.is_(None),
                AdministrativeNode.is_active.is_(True),
            )
            .limit(1)
        )
        return ward_name, province_name

    # ------------------------------------------------------------------
    # GENERIC FILTERED (admin panel)
    # ------------------------------------------------------------------

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters,
    ) -> Tuple[int, List[AdministrativeNode]]:
        """
        Get filtered administrative nodes with pagination.

        Filters: level, province_code, district_code, is_active
        """
        from sqlalchemy import func

        query = select(AdministrativeNode)
        count_query = select(func.count()).select_from(AdministrativeNode)

        if filters.get("level"):
            query = query.where(AdministrativeNode.level == filters["level"])
            count_query = count_query.where(AdministrativeNode.level == filters["level"])
        if filters.get("province_code"):
            query = query.where(AdministrativeNode.province_code == filters["province_code"])
            count_query = count_query.where(AdministrativeNode.province_code == filters["province_code"])
        if filters.get("district_code"):
            query = query.where(AdministrativeNode.district_code == filters["district_code"])
            count_query = count_query.where(AdministrativeNode.district_code == filters["district_code"])
        if filters.get("is_active") is not None:
            query = query.where(AdministrativeNode.is_active == filters["is_active"])
            count_query = count_query.where(AdministrativeNode.is_active == filters["is_active"])

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        query = query.offset(skip).limit(limit).order_by(AdministrativeNode.code)
        result = await self.db.execute(query)

        return total, list(result.scalars().all())
