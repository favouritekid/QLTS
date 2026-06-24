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

import csv
import io
from typing import Any, Awaitable, Callable, Optional, Tuple

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vn_school import VnSchool, VnSchoolKvAssignment
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from app.utils.exceptions import ValidationError as DomainValidationError

PostCommitCallback = Optional[Callable[[], Awaitable[None]]]


async def _noop_callback() -> None:
    return None


_VN_SCHOOL_LEVELS = {"THCS", "THPT", "THCS_THPT", "TRUNG_HOC_NGHE", "OTHER"}


def _years_overlap(
    a_from: int, a_to: Optional[int], b_from: int, b_to: Optional[int]
) -> bool:
    """2 khoảng năm [from, to] (to=None → ongoing) có giao nhau không."""
    a_to_eff = a_to if a_to is not None else 9999
    b_to_eff = b_to if b_to is not None else 9999
    return a_from <= b_to_eff and b_from <= a_to_eff


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

        # Relevance ranking (thay cho ORDER BY name thuần). Không có nó, sắp xếp
        # alphabet vùi các trường "THPT <tên>" phổ biến xuống sau hàng loạt tiền
        # tố đứng trước theo bảng chữ cái (DTNT/GDNN/PT/TH-/THCS...). Với limit
        # ~50, trường người dùng cần có thể không bao giờ xuất hiện (đo thực tế:
        # q="nguyen" khớp 438 trường nhưng dòng "THPT ..." đầu tiên nằm ở vị trí
        # alphabet 40). Ưu tiên:
        #   0 = tên bắt đầu bằng q (prefix)
        #   1 = q ở đầu một từ (word boundary — phổ biến nhất khi gõ tên riêng)
        #   2 = q ở giữa từ
        # rồi tên ngắn lên trước (khớp sát hơn), cuối cùng alphabet cho ổn định.
        name_unaccent = func.unaccent(VnSchool.name)
        relevance = case(
            (name_unaccent.ilike(func.unaccent(f"{q_escaped}%")), 0),
            (name_unaccent.ilike(func.unaccent(f"% {q_escaped}%")), 1),
            else_=2,
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
            .order_by(relevance, func.length(VnSchool.name), VnSchool.name)
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(stmt)
        rows = [dict(row._mapping) for row in result.all()]
        return rows, total

    # =========================================================================
    # Admin CRUD (PR-B). DELETE school = deactivate (is_active=false). KV
    # assignment overlap check ở service (M3: không GiST EXCLUDE).
    # =========================================================================

    SCHOOL_CSV_REQUIRED = {
        "moet_school_code", "moet_province_code", "name", "province", "level",
    }

    def _current_kv_subq(self):
        return (
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

    async def list_schools(
        self,
        moet_province_code: Optional[str] = None,
        level: Optional[str] = None,
        q: Optional[str] = None,
        active_only: bool = True,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[list[dict], int]:
        """Paginated list + lọc moet_province_code/level/q. Read-only."""
        page = max(1, page)
        page_size = min(max(1, page_size), 200)
        filters = []
        if active_only:
            filters.append(VnSchool.is_active.is_(True))
        if moet_province_code:
            filters.append(VnSchool.moet_province_code == moet_province_code)
        if level:
            filters.append(VnSchool.level == level)
        if q:
            qc = (
                q.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            filters.append(
                or_(
                    func.unaccent(VnSchool.name).ilike(func.unaccent(f"%{qc}%")),
                    VnSchool.moet_school_code.ilike(f"%{qc}%"),
                )
            )
        total = (
            await self.db.execute(
                select(func.count(VnSchool.id)).where(*filters)
            )
        ).scalar_one()
        stmt = (
            select(
                VnSchool.id,
                VnSchool.moet_school_code,
                VnSchool.moet_province_code,
                VnSchool.moet_district_code,
                VnSchool.name,
                VnSchool.address,
                VnSchool.province,
                VnSchool.district,
                VnSchool.ward,
                VnSchool.level,
                VnSchool.is_dtnt,
                VnSchool.is_active,
                self._current_kv_subq().label("current_kv"),
            )
            .where(*filters)
            .order_by(VnSchool.province, VnSchool.name, VnSchool.id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = [dict(r._mapping) for r in (await self.db.execute(stmt)).all()]
        return rows, int(total)

    async def list_school_provinces(self) -> list[dict]:
        """Distinct {moet_province_code, province} từ trường active — FE filter."""
        stmt = (
            select(VnSchool.moet_province_code, VnSchool.province)
            .where(VnSchool.is_active.is_(True))
            .distinct()
            .order_by(VnSchool.province)
        )
        return [dict(r._mapping) for r in (await self.db.execute(stmt)).all()]

    async def current_kv(self, school_id: int) -> Optional[str]:
        """KV active mới nhất của 1 trường (effective_to_year IS NULL) — cho
        response single-school (create/update/deactivate)."""
        stmt = (
            select(VnSchoolKvAssignment.kv_code)
            .where(
                VnSchoolKvAssignment.school_id == school_id,
                VnSchoolKvAssignment.effective_to_year.is_(None),
            )
            .order_by(VnSchoolKvAssignment.effective_from_year.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _active_school(
        self, moet_school_code: str, moet_province_code: str
    ) -> Optional[VnSchool]:
        stmt = select(VnSchool).where(
            VnSchool.moet_school_code == moet_school_code,
            VnSchool.moet_province_code == moet_province_code,
            VnSchool.is_active.is_(True),
        )
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    async def create_school(
        self, data: dict[str, Any]
    ) -> Tuple[VnSchool, PostCommitCallback]:
        if (
            await self._active_school(
                data["moet_school_code"], data["moet_province_code"]
            )
            is not None
        ):
            raise DuplicateResourceError(
                f"Đã có trường active với mã MOET "
                f"{data['moet_school_code']!r}/{data['moet_province_code']!r}."
            )
        clean = {k: v for k, v in data.items() if v is not None}
        school = VnSchool(**clean)
        self.db.add(school)
        await self.db.flush()
        return school, _noop_callback

    async def update_school(
        self, school_id: int, data: dict[str, Any]
    ) -> Tuple[VnSchool, PostCommitCallback]:
        school = await self.db.get(VnSchool, school_id)
        if school is None:
            raise ResourceNotFoundError(f"VnSchool {school_id} not found")
        # Không đổi định danh MOET / is_active qua PATCH (DELETE=deactivate).
        for f in ("moet_school_code", "moet_province_code", "is_active"):
            data.pop(f, None)
        for key in (
            "moet_district_code", "name", "address", "province",
            "district", "ward", "level", "is_dtnt",
        ):
            if key in data:
                setattr(school, key, data[key])
        await self.db.flush()
        return school, _noop_callback

    async def deactivate_school(
        self, school_id: int
    ) -> Tuple[VnSchool, PostCommitCallback]:
        """DELETE = soft-delete (is_active=false). KHÔNG hard-delete (FK
        vn_school_kv_assignment.school_id CASCADE sẽ xoá lịch sử KV)."""
        school = await self.db.get(VnSchool, school_id)
        if school is None:
            raise ResourceNotFoundError(f"VnSchool {school_id} not found")
        if not school.is_active:
            raise BusinessRuleViolation(
                f"Trường {school_id} đã ngừng kích hoạt trước đó."
            )
        school.is_active = False
        await self.db.flush()
        return school, _noop_callback

    # --- KV assignment (vn_school_kv_assignment) ---

    async def list_kv_assignments(
        self, school_id: int
    ) -> list[VnSchoolKvAssignment]:
        if await self.db.get(VnSchool, school_id) is None:
            raise ResourceNotFoundError(f"VnSchool {school_id} not found")
        stmt = (
            select(VnSchoolKvAssignment)
            .where(VnSchoolKvAssignment.school_id == school_id)
            .order_by(VnSchoolKvAssignment.effective_from_year)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def _guard_kv(
        self,
        school_id: int,
        from_year: int,
        to_year: Optional[int],
        exclude_id: Optional[int] = None,
    ) -> None:
        if to_year is not None and to_year < from_year:
            raise BusinessRuleViolation(
                f"effective_to_year ({to_year}) < effective_from_year "
                f"({from_year})."
            )
        stmt = select(VnSchoolKvAssignment).where(
            VnSchoolKvAssignment.school_id == school_id
        )
        if exclude_id is not None:
            stmt = stmt.where(VnSchoolKvAssignment.id != exclude_id)
        for row in (await self.db.execute(stmt)).scalars().all():
            if _years_overlap(
                from_year, to_year,
                row.effective_from_year, row.effective_to_year,
            ):
                raise BusinessRuleViolation(
                    f"Khoảng năm chồng lấn phân loại KV đã có (id={row.id}: "
                    f"{row.effective_from_year}-"
                    f"{row.effective_to_year or 'nay'})."
                )

    async def add_kv_assignment(
        self, school_id: int, data: dict[str, Any]
    ) -> Tuple[VnSchoolKvAssignment, PostCommitCallback]:
        if await self.db.get(VnSchool, school_id) is None:
            raise ResourceNotFoundError(f"VnSchool {school_id} not found")
        await self._guard_kv(
            school_id, data["effective_from_year"],
            data.get("effective_to_year"),
        )
        clean = {k: v for k, v in data.items() if v is not None}
        row = VnSchoolKvAssignment(school_id=school_id, **clean)
        self.db.add(row)
        await self.db.flush()
        return row, _noop_callback

    async def update_kv_assignment(
        self, assignment_id: int, data: dict[str, Any]
    ) -> Tuple[VnSchoolKvAssignment, PostCommitCallback]:
        row = await self.db.get(VnSchoolKvAssignment, assignment_id)
        if row is None:
            raise ResourceNotFoundError(
                f"VnSchoolKvAssignment {assignment_id} not found"
            )
        # Validate trạng thái ỨNG VIÊN TRƯỚC khi mutate — guard raise sẽ không
        # để row hỏng trong session (memory partial-update-loses-cross-field).
        new_from = data.get("effective_from_year", row.effective_from_year)
        new_to = (
            data["effective_to_year"]
            if "effective_to_year" in data
            else row.effective_to_year
        )
        await self._guard_kv(
            row.school_id, new_from, new_to, exclude_id=row.id
        )
        for key in (
            "kv_code", "effective_from_year", "effective_to_year",
            "source", "notes",
        ):
            if key in data:
                setattr(row, key, data[key])
        await self.db.flush()
        return row, _noop_callback

    async def delete_kv_assignment(
        self, assignment_id: int
    ) -> Tuple[None, PostCommitCallback]:
        row = await self.db.get(VnSchoolKvAssignment, assignment_id)
        if row is None:
            raise ResourceNotFoundError(
                f"VnSchoolKvAssignment {assignment_id} not found"
            )
        await self.db.delete(row)
        await self.db.flush()
        return None, _noop_callback

    # --- CSV import (school-only; KV-via-CSV defer → quản lý qua endpoint KV) ---

    async def import_schools_csv(
        self, csv_bytes: bytes
    ) -> Tuple[dict[str, Any], PostCommitCallback]:
        """Bulk import trường (idempotent theo (moet_school_code,
        moet_province_code) active). Cột: moet_school_code, moet_province_code,
        name, province, level (+ moet_district_code/district/ward/is_dtnt tuỳ
        chọn). KV assignment KHÔNG qua CSV — dùng endpoint /kv."""
        try:
            text_data = csv_bytes.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            raise DomainValidationError(
                "CSV phải encode UTF-8. Trong Excel: 'Save As → CSV UTF-8'."
            )
        reader = csv.DictReader(io.StringIO(text_data))
        missing = self.SCHOOL_CSV_REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise DomainValidationError(
                f"CSV thiếu cột bắt buộc: {', '.join(sorted(missing))}."
            )
        inserted = 0
        skipped = 0
        errors: list[dict] = []
        # Dedupe TRONG file: tránh 2 dòng cùng (code, prov) cùng được add →
        # vi phạm partial-unique lúc flush (IntegrityError). KHÔNG dựa autoflush.
        seen: set[tuple[str, str]] = set()
        for row_num, raw in enumerate(reader, start=2):
            try:
                code = (raw.get("moet_school_code") or "").strip()
                prov = (raw.get("moet_province_code") or "").strip()
                name = (raw.get("name") or "").strip()
                province = (raw.get("province") or "").strip()
                level = (raw.get("level") or "").strip()
                if not (code and prov and name and province):
                    raise ValueError(
                        "thiếu giá trị bắt buộc "
                        "(moet_school_code/moet_province_code/name/province)"
                    )
                if level not in _VN_SCHOOL_LEVELS:
                    raise ValueError(f"level không hợp lệ: {level!r}")
                if (code, prov) in seen or (
                    await self._active_school(code, prov) is not None
                ):
                    skipped += 1
                    continue
                seen.add((code, prov))
                self.db.add(
                    VnSchool(
                        moet_school_code=code,
                        moet_province_code=prov,
                        moet_district_code=(
                            raw.get("moet_district_code") or ""
                        ).strip() or None,
                        name=name,
                        province=province,
                        district=(raw.get("district") or "").strip() or None,
                        ward=(raw.get("ward") or "").strip() or None,
                        level=level,
                        is_dtnt=(raw.get("is_dtnt") or "").strip().lower()
                        in ("1", "true", "yes", "x", "có"),
                    )
                )
                inserted += 1
            except ValueError as e:
                errors.append({"row_num": row_num, "error": str(e)})
                continue
        await self.db.flush()
        return (
            {
                "inserted": inserted,
                "skipped_existing": skipped,
                "error_rows": errors,
            },
            _noop_callback,
        )
