# app/services/vn_locality_service.py
"""Admin CSV import service for vn_commune_area_map + vn_high_school
(Q9 #07 PR4).

Both imports are idempotent — re-running the same CSV is safe:
* commune: skip rows where (commune_code, effective_to IS NULL) already exists
* high_school: skip rows where (name, province) already exists active

Validation strategy: row-level Pydantic parse + skip-on-error so a
malformed line doesn't abort the whole import. Errors collected into
``error_rows`` for admin to fix + re-upload.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Awaitable, Callable, Optional, Tuple

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vn_locality import VnCommuneAreaMap, VnHighSchool
from app.schemas.vn_locality import (
    VnCommuneAreaMapRow,
    VnHighSchoolRow,
)


PostCommitCallback = Optional[Callable[[], Awaitable[None]]]


async def _noop_callback() -> None:
    return None


# Demo seed (5 rows) so the candidate FE dropdown can render something
# usable before the admin uploads the real MOET CSV. Rows are inserted
# on first call only; subsequent calls skip existing names.
SAMPLE_HIGH_SCHOOLS: list[dict[str, Any]] = [
    {"name": "THPT Lê Quý Đôn", "province": "Hà Nội", "district": "Hà Đông", "kv_code": "KV3"},
    {"name": "THPT Chu Văn An", "province": "Hà Nội", "district": "Tây Hồ", "kv_code": "KV3"},
    {"name": "THPT Nguyễn Thị Minh Khai", "province": "Hồ Chí Minh", "district": "Quận 3", "kv_code": "KV3"},
    {"name": "THPT chuyên Lê Hồng Phong", "province": "Hồ Chí Minh", "district": "Quận 5", "kv_code": "KV3"},
    {"name": "THPT DTNT N'Trang Lơng", "province": "Đắk Lắk", "district": "Buôn Ma Thuột", "kv_code": "KV1"},
]


class VnLocalityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # =========================================================================
    # vn_commune_area_map
    # =========================================================================

    async def import_commune_csv(
        self, csv_bytes: bytes
    ) -> Tuple[dict[str, Any], PostCommitCallback]:
        """Parse + upsert commune rows. Expected CSV columns:
        commune_code,province,district,ward,area_code

        Idempotency key: ``commune_code`` (BNV's immutable identifier).
        CR-M2: ``utf-8-sig`` decode strips the BOM that Excel-exported
        CSVs commonly include — without this the first header column
        parses as ``\\ufeffcommune_code`` and every row fails validation.

        Returns ``{inserted, skipped_existing, error_rows}``.
        """
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig", errors="strict")))
        inserted = 0
        skipped = 0
        errors: list[dict] = []

        for row_num, raw in enumerate(reader, start=2):  # row 1 = header
            try:
                row = VnCommuneAreaMapRow.model_validate(raw)
            except ValidationError as e:
                errors.append({"row_num": row_num, "error": str(e)})
                continue

            # Skip if active row exists
            existing = await self.db.execute(
                select(VnCommuneAreaMap.id)
                .where(
                    VnCommuneAreaMap.commune_code == row.commune_code,
                    VnCommuneAreaMap.effective_to.is_(None),
                )
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                continue

            self.db.add(VnCommuneAreaMap(**row.model_dump()))
            inserted += 1

        await self.db.flush()
        return (
            {
                "inserted": inserted,
                "skipped_existing": skipped,
                "error_rows": errors,
            },
            _noop_callback,
        )

    # =========================================================================
    # vn_high_school
    # =========================================================================

    async def import_high_school_csv(
        self, csv_bytes: bytes
    ) -> Tuple[dict[str, Any], PostCommitCallback]:
        """Parse + upsert high school rows. Expected CSV columns:
        name,province,district,ward,kv_code

        Idempotency key: ``(name, province)`` — MOET CSV has no stable
        unique identifier across years; (name, province) is the
        practical compromise. NOTE: same school name in 2 provinces
        creates 2 distinct rows (correct — different schools).

        CR-M2: ``utf-8-sig`` decode strips Excel-exported BOM.
        """
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig", errors="strict")))
        inserted = 0
        skipped = 0
        errors: list[dict] = []

        for row_num, raw in enumerate(reader, start=2):
            # csv.DictReader returns "" for blank cells; Pydantic regex
            # pattern would reject "" — convert to None so optional fields
            # stay optional (MOET CSV often omits kv_code / ward).
            cleaned = {k: (v if v != "" else None) for k, v in raw.items()}
            try:
                row = VnHighSchoolRow.model_validate(cleaned)
            except ValidationError as e:
                errors.append({"row_num": row_num, "error": str(e)})
                continue

            existing = await self.db.execute(
                select(VnHighSchool.id)
                .where(
                    VnHighSchool.name == row.name,
                    VnHighSchool.province == row.province,
                    VnHighSchool.is_active.is_(True),
                )
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                continue

            self.db.add(VnHighSchool(**row.model_dump()))
            inserted += 1

        await self.db.flush()
        return (
            {
                "inserted": inserted,
                "skipped_existing": skipped,
                "error_rows": errors,
            },
            _noop_callback,
        )

    async def seed_sample_high_schools(
        self,
    ) -> Tuple[dict[str, Any], PostCommitCallback]:
        """Insert 5 demo rows (Q9 #07 hybrid C2: ship empty + free-text
        fallback, but a handful of rows let candidate FE dropdown +
        Chrome MCP smoke test work end-to-end without waiting on the
        real MOET CSV)."""
        inserted = 0
        for row_data in SAMPLE_HIGH_SCHOOLS:
            existing = await self.db.execute(
                select(VnHighSchool.id)
                .where(
                    VnHighSchool.name == row_data["name"],
                    VnHighSchool.province == row_data["province"],
                    VnHighSchool.is_active.is_(True),
                )
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                continue
            self.db.add(VnHighSchool(**row_data))
            inserted += 1
        await self.db.flush()
        return (
            {"inserted": inserted, "total_in_seed": len(SAMPLE_HIGH_SCHOOLS)},
            _noop_callback,
        )

    # =========================================================================
    # Read endpoints (used by PR5 candidate FE)
    # =========================================================================

    async def search_high_schools(
        self, query: str, limit: int = 20
    ) -> list[VnHighSchool]:
        """CR-M3 fix: prefix match (NOT substring) — index-friendly +
        cleaner UX. Vietnamese school names canonically start with
        'THPT' or 'Trường THPT' so candidate types the school's actual
        name (vd 'Lê Quý Đôn') and we surface anything starting with
        that string.

        Returns active rows only (is_active=true)."""
        stmt = (
            select(VnHighSchool)
            .where(
                VnHighSchool.name.ilike(f"{query}%"),
                VnHighSchool.is_active.is_(True),
            )
            .order_by(VnHighSchool.name)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def lookup_commune_kv(
        self, commune_code: str
    ) -> Optional[str]:
        """Backup KV resolution for special-case profiles (PT DTNT,
        quân nhân) — looks up the ACTIVE commune row."""
        stmt = (
            select(VnCommuneAreaMap.area_code)
            .where(
                VnCommuneAreaMap.commune_code == commune_code,
                VnCommuneAreaMap.effective_to.is_(None),
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
