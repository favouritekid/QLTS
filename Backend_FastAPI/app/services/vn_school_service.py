"""Phase D.0b — VnSchool search service.

Read-only service for candidate FE dropdown search. Diacritic-insensitive
match via PostgreSQL `unaccent()` extension (enabled by migration
q9_07_d0a).

Query pattern:
    SELECT s.*, kv.kv_code AS current_kv
    FROM vn_school s
    LEFT JOIN LATERAL (
        SELECT kv_code FROM vn_school_kv_assignment
        WHERE school_id = s.id AND effective_to_year IS NULL
        ORDER BY effective_from_year DESC LIMIT 1
    ) kv ON true
    WHERE s.is_active = true
      AND (:level IS NULL OR s.level = :level)
      AND (:province IS NULL OR s.moet_province_code = :province)
      AND unaccent(s.name) ILIKE unaccent('%' || :q || '%')
    ORDER BY s.name
    LIMIT :limit OFFSET :offset;

Auth: caller responsible for authentication. This service does NOT
enforce — router gates via `get_current_active_user` per QLTS V3
architecture (memory CLAUDE.md MANDATORY ARCHITECTURE RULES).
"""
from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vn_school import VnSchool, VnSchoolKvAssignment


class VnSchoolService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search_schools(
        self,
        query: str,
        level: Optional[str] = None,
        province: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[list[dict], int]:
        """Search active schools by name (diacritic-insensitive).

        Returns: (rows, total_count). Each row is a dict with VnSchool
        fields + `current_kv` (latest active KV assignment, may be NULL).
        """
        # Sanitize query: trim, escape SQL wildcards
        q_clean = (query or "").strip()
        if not q_clean:
            return [], 0

        # Escape ILIKE wildcards (% _) to prevent regex injection
        q_escaped = q_clean.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        # Base WHERE filters (shared between count + data queries)
        filters = [VnSchool.is_active.is_(True)]
        if level:
            filters.append(VnSchool.level == level)
        if province:
            filters.append(VnSchool.moet_province_code == province)

        # Diacritic-insensitive ILIKE: unaccent(name) ILIKE unaccent('%q%')
        name_match = func.unaccent(VnSchool.name).ilike(
            func.unaccent(f"%{q_escaped}%")
        )
        filters.append(name_match)

        # Count
        count_stmt = select(func.count(VnSchool.id)).where(*filters)
        total = (await self.db.execute(count_stmt)).scalar_one()

        if total == 0:
            return [], 0

        # Data: LEFT JOIN LATERAL for current KV (latest active assignment)
        current_kv_subq = (
            select(VnSchoolKvAssignment.kv_code)
            .where(
                VnSchoolKvAssignment.school_id == VnSchool.id,
                VnSchoolKvAssignment.effective_to_year.is_(None),
            )
            .order_by(VnSchoolKvAssignment.effective_from_year.desc())
            .limit(1)
            .correlate(VnSchool)
            .scalar_subquery()
        )

        stmt = (
            select(
                VnSchool.id,
                VnSchool.moet_school_code,
                VnSchool.moet_province_code,
                VnSchool.name,
                VnSchool.address,
                VnSchool.province,
                VnSchool.district,
                VnSchool.level,
                VnSchool.is_dtnt,
                current_kv_subq.label("current_kv"),
            )
            .where(*filters)
            .order_by(VnSchool.name)
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(stmt)
        rows = [dict(row._mapping) for row in result.all()]
        return rows, total
