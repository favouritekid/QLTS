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

from app.models.vn_locality import VnCommuneAreaMap
from app.schemas.vn_locality import VnCommuneAreaMapRow
from app.utils.exceptions import ValidationError as DomainValidationError

# VnHighSchool DROPPED in phase1_09 — see app/models/vn_school.py for the
# 3-table replacement family. Old methods (import_high_school_csv,
# seed_sample_high_schools, search_high_schools) REMOVED from this service;
# routes also removed from admin_vn_locality.py. Replacement will live in
# Phase B.1 import script (app/scripts/import_moet_schools_2025.py) +
# new VnSchool admin search service (Phase D candidate FE).


def _decode_csv_bytes(csv_bytes: bytes) -> str:
    """N2 fix: utf-8-sig handles Excel BOM, but CP1258 / latin1 / other
    Excel-VN encodings raise UnicodeDecodeError → bubbles up as opaque
    500. Catch + re-raise as domain ValidationError so router returns
    422 with a clear "save as CSV UTF-8" hint."""
    try:
        return csv_bytes.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise DomainValidationError(
            "CSV phải encode UTF-8. Trong Excel chọn 'Save As → CSV UTF-8 "
            "(Comma delimited) (*.csv)' rồi upload lại."
        )


# F.5 fix: required columns per CSV format. DictReader otherwise silently
# parses any header into a dict; rows with wrong-named columns would
# either silently pass with all-None fields (admin tưởng OK), or fail
# Pydantic per-row (noisy). Upfront header check returns a clear 422.
COMMUNE_CSV_REQUIRED_COLS = {
    "commune_code", "province", "district", "ward", "area_code",
}
# HIGH_SCHOOL_CSV_REQUIRED_COLS DROPPED phase1_09. New THPT import will live
# in app/scripts/import_moet_schools_2025.py (Phase B.1) — uses MOET file
# structure directly, không cần required_cols const ở service layer.


def _validate_csv_header(
    reader: csv.DictReader, required_cols: set[str], format_name: str
) -> None:
    """Raise DomainValidationError if reader.fieldnames missing any
    required column. Called before per-row parsing so admin gets a
    single clear error instead of N row-level errors."""
    header = set(reader.fieldnames or [])
    missing = required_cols - header
    if missing:
        raise DomainValidationError(
            f"CSV {format_name} thiếu cột bắt buộc: "
            f"{', '.join(sorted(missing))}. "
            f"Header phải có: {', '.join(sorted(required_cols))}."
        )


PostCommitCallback = Optional[Callable[[], Awaitable[None]]]


async def _noop_callback() -> None:
    return None


# SAMPLE_HIGH_SCHOOLS DROPPED phase1_09. Demo seed for VnSchool family
# will live in app/scripts/import_moet_schools_2025.py (Phase B.1).


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
        reader = csv.DictReader(io.StringIO(_decode_csv_bytes(csv_bytes)))
        _validate_csv_header(reader, COMMUNE_CSV_REQUIRED_COLS, "commune")
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
    # VnHighSchool methods DROPPED phase1_09 — see vn_school family (TBD service)
    # =========================================================================

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
