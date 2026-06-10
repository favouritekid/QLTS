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
from datetime import date
from typing import Any, Awaitable, Callable, Optional, Tuple

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vn_locality import VnCommuneAreaMap
from app.schemas.vn_locality import VnCommuneAreaMapRow
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)
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


def _guard_close_not_before_open(open_date: date, close_date: date) -> None:
    """``effective_to`` / cutover phải >= ``effective_from`` — chặn khoảng
    temporal ngược. vn_commune_area_map KHÔNG có CHECK interval ở DB (khác
    vn_school_kv_assignment), nên guard ở service để 1 effective_from/to quá
    khứ không tạo dòng [from, to) với to < from (làm sai lookup/audit lịch sử)."""
    if close_date < open_date:
        raise BusinessRuleViolation(
            f"Ngày đóng ({close_date}) không được trước ngày bắt đầu "
            f"({open_date}) — sẽ tạo khoảng thời gian ngược."
        )


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

    # =========================================================================
    # vn_commune_area_map — admin CRUD (PR-A)
    #
    # Temporal half-open (active = ``effective_to IS NULL``, ≤1/commune_code per
    # partial-unique ``uq_vn_commune_area_map_code_active``). Mirror SEMANTICS
    # của priority_config_service (temporal, ``(row, callback)``, domain
    # exceptions) nhưng giữ STRUCTURE direct-``db.execute`` của file này (không
    # repo). Đổi KV ĐI QUA ``replace_commune_area`` (giữ lịch sử), KHÔNG update
    # ``area_code`` tại chỗ.
    # =========================================================================

    async def _active_commune(
        self, commune_code: str, exclude_id: Optional[int] = None
    ) -> Optional[VnCommuneAreaMap]:
        """Dòng active (effective_to IS NULL) của 1 commune_code, nếu có."""
        stmt = select(VnCommuneAreaMap).where(
            VnCommuneAreaMap.commune_code == commune_code,
            VnCommuneAreaMap.effective_to.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(VnCommuneAreaMap.id != exclude_id)
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    async def list_communes(
        self,
        province: Optional[str] = None,
        q: Optional[str] = None,
        active_only: bool = True,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[list[VnCommuneAreaMap], int]:
        """Paginated list + lọc tỉnh/search. Read-only (no callback)."""
        page = max(1, page)
        page_size = min(max(1, page_size), 200)
        conds = []
        if active_only:
            conds.append(VnCommuneAreaMap.effective_to.is_(None))
        if province:
            conds.append(VnCommuneAreaMap.province == province)
        if q:
            like = f"%{q.strip()}%"
            conds.append(
                or_(
                    VnCommuneAreaMap.ward.ilike(like),
                    VnCommuneAreaMap.commune_code.ilike(like),
                )
            )
        total = (
            await self.db.execute(
                select(func.count())
                .select_from(VnCommuneAreaMap)
                .where(*conds)
            )
        ).scalar_one()
        rows = (
            (
                await self.db.execute(
                    select(VnCommuneAreaMap)
                    .where(*conds)
                    .order_by(
                        VnCommuneAreaMap.province,
                        VnCommuneAreaMap.ward,
                        VnCommuneAreaMap.id,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    async def create_commune(
        self, data: dict[str, Any]
    ) -> Tuple[VnCommuneAreaMap, PostCommitCallback]:
        """Tạo dòng KV mới. Chặn nếu commune_code đã có dòng active."""
        if await self._active_commune(data["commune_code"]) is not None:
            raise DuplicateResourceError(
                f"Đã có dòng KV active cho mã xã {data['commune_code']!r} — "
                f"retire dòng cũ hoặc dùng /replace-area để đổi KV."
            )
        # Drop None để effective_from lấy server_default (CURRENT_DATE).
        clean = {k: v for k, v in data.items() if v is not None}
        row = VnCommuneAreaMap(**clean)
        self.db.add(row)
        await self.db.flush()
        return row, _noop_callback

    async def update_commune(
        self, commune_id: int, data: dict[str, Any]
    ) -> Tuple[VnCommuneAreaMap, PostCommitCallback]:
        """PATCH metadata (province/district/ward/effective_to). KHÔNG đổi
        area_code/commune_code. effective_to=None = re-activate (chặn 2 active)."""
        row = await self.db.get(VnCommuneAreaMap, commune_id)
        if row is None:
            raise ResourceNotFoundError(
                f"VnCommuneAreaMap {commune_id} not found"
            )
        # Defense-in-depth: schema đã loại 2 field này, service vẫn drop.
        data.pop("area_code", None)
        data.pop("commune_code", None)
        if "effective_to" in data and data["effective_to"] is None:
            other = await self._active_commune(row.commune_code, exclude_id=row.id)
            if other is not None:
                raise BusinessRuleViolation(
                    f"Không thể re-activate: mã xã {row.commune_code!r} đã có "
                    f"dòng active khác (id={other.id})."
                )
        if data.get("effective_to") is not None:
            _guard_close_not_before_open(row.effective_from, data["effective_to"])
        for key in ("province", "district", "ward", "effective_to"):
            if key in data:
                setattr(row, key, data[key])
        await self.db.flush()
        return row, _noop_callback

    async def replace_commune_area(
        self,
        commune_id: int,
        area_code: str,
        effective_from: Optional[date] = None,
    ) -> Tuple[VnCommuneAreaMap, PostCommitCallback]:
        """Đổi KV temporal: retire dòng active cũ + insert dòng active mới."""
        old = await self.db.get(VnCommuneAreaMap, commune_id)
        if old is None:
            raise ResourceNotFoundError(
                f"VnCommuneAreaMap {commune_id} not found"
            )
        if old.effective_to is not None:
            raise BusinessRuleViolation(
                f"Dòng {commune_id} đã retire (effective_to={old.effective_to}) "
                f"— không thể đổi KV trên dòng đã đóng."
            )
        cutover = effective_from or date.today()
        _guard_close_not_before_open(old.effective_from, cutover)
        # Đóng dòng cũ TRƯỚC + flush để giải phóng partial-unique active slot,
        # rồi mới insert dòng mới (tránh 2 active cùng commune_code lúc INSERT).
        old.effective_to = cutover
        await self.db.flush()
        new_row = VnCommuneAreaMap(
            commune_code=old.commune_code,
            province=old.province,
            district=old.district,
            ward=old.ward,
            area_code=area_code,
            effective_from=cutover,
        )
        self.db.add(new_row)
        await self.db.flush()
        return new_row, _noop_callback

    async def retire_commune(
        self, commune_id: int, effective_to: Optional[date] = None
    ) -> Tuple[VnCommuneAreaMap, PostCommitCallback]:
        """Retire dòng KV (soft-close effective_to). Chặn double-retire."""
        row = await self.db.get(VnCommuneAreaMap, commune_id)
        if row is None:
            raise ResourceNotFoundError(
                f"VnCommuneAreaMap {commune_id} not found"
            )
        if row.effective_to is not None:
            raise BusinessRuleViolation(
                f"Dòng {commune_id} đã retire trước đó "
                f"(effective_to={row.effective_to})."
            )
        target = effective_to or date.today()
        _guard_close_not_before_open(row.effective_from, target)
        row.effective_to = target
        await self.db.flush()
        return row, _noop_callback
