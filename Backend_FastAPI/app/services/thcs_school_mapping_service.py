# app/services/thcs_school_mapping_service.py
"""Công cụ ghép tên trường THCS gõ tay → trường trong danh mục (đề xuất danh mục THCS Phần B, owner 22-11).

Ba việc:

1. **Gom nhóm** dòng lịch sử học THCS gõ tay (``graduation_type = 'THCS'`` hoặc ``level = 'THCS'``, không có
   ``school_id``) theo tên chuẩn hoá (``thcs_school_name.normalize_thcs_school_name`` — MỘT nguồn). Chỉ trả tên trường +
   số đếm, KHÔNG trả dữ liệu cá nhân.
2. **Ghép / huỷ ghép / tạo trường mới từ nhóm** — bảng ``thcs_school_name_mapping``. Trường đích phải còn hoạt động và
   ở cấp THCS / liên cấp. Tạo trường mới đi qua ``VnSchoolService.create_school`` (mã nội bộ NB, mã xã bắt buộc).
3. **Áp ghép** — gắn ``school_id`` + ``level`` vào dòng THCS khớp tên đã ghép:

   * chạy thử MẶC ĐỊNH; chế độ thật khoá bằng cờ CHO PHÉP ``THCS_MAPPING_APPLY_ENABLED`` (mặc định tắt — owner chưa
     quyết dòng y→y). Tầng chủ sở hữu của cờ = :meth:`ThcsSchoolMappingService.apply_mappings` (không phải router);
   * KHÔNG chạm dòng đã có ``school_id``; chỉ chạm hồ sơ năm :data:`APPLY_ACADEMIC_YEAR` ở
     :data:`APPLY_ELIGIBLE_STATUSES` (nháp + chờ xét — owner 22-11 câu 1, 2); bỏ qua hồ sơ gắn Quyết định / dấu
     AppSheet (``council_decision_status_service``);
   * chế độ thật khoá hồ sơ ``FOR UPDATE`` (thứ tự id tăng — thứ tự khoá chung), đọc lại dưới khoá, đối chiếu hai số
     của lượt chạy thử (lệch ⇒ 409, không ghi gì), tăng ``version`` (khoá lạc quan của form hồ sơ: cán bộ đang mở
     form nháp mà lưu bản cũ ⇒ ``ProfileVersionConflict`` có câu rõ ràng), ghi vết từng hồ sơ vào ``entity_audit_log``;
   * báo trước: số hồ sơ đang ở chế độ KV ấn định tay (đổi lịch sử học ⇒ vân tay đầu vào đổi ⇒ ấn định hết hiệu lực)
     và số dòng y→y.
"""
from __future__ import annotations

import copy
from collections import Counter
from typing import Any, Final, Iterable, Optional, Tuple

from sqlalchemy import func, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.admission import AdmissionProfile
from app.models.thcs_school_name_mapping import ThcsSchoolNameMapping
from app.models.vn_school import VnSchool
from app.models.vn_school_internal_code import INTERNAL_CODE_LEVELS
from app.services.audit_service import log_audit
from app.services.council_decision_status_service import (
    NO_DECISION,
    decision_state,
    lock_profiles,
)
from app.services.thcs_school_name import normalize_thcs_school_name
from app.services.vn_school_service import VnSchoolService
from app.utils.exceptions import (
    BusinessRuleViolation,
    ConflictError,
    ResourceNotFoundError,
)
from app.utils.exceptions import ValidationError as DomainValidationError

#: Trạng thái hồ sơ lượt áp ghép ĐƯỢC chạm — owner 22-11 (``QUYET-DINH-OWNER-THCS-CONG-CU-GHEP`` câu 1): nháp + chờ xét.
#: Danh sách CHO PHÉP (fail-closed): trạng thái mới thêm về sau mặc định KHÔNG bị chạm. Ngoài tập: đã có kết quả
#: (``result_published`` / ``admitted`` / ``waitlisted`` / ``rejected`` / ``approved`` / ``confirmed`` / ``overridden`` /
#: ``enrolled``), đã / đang rút (``withdrawal_pending`` / ``withdrawn``).
APPLY_ELIGIBLE_STATUSES: Final[tuple[str, ...]] = (
    "draft",
    "submitted",
    "resubmitted",
    "revision_requested",
    "reviewing",
)
#: Năm tuyển sinh lượt áp ghép được chạm — owner 22-11 câu 2 ("giới hạn năm 2026").
APPLY_ACADEMIC_YEAR: Final[int] = 2026
#: Trạng thái nháp — lượt chạy thử báo riêng số hồ sơ nháp (owner câu 1).
DRAFT_STATUS: Final[str] = "draft"
#: Hồ sơ đã / đang rút: không tính vào nhóm (owner đo "bỏ hồ sơ rút").
WITHDRAWN_STATUSES: Final[frozenset[str]] = frozenset({"withdrawal_pending", "withdrawn"})

AUDIT_ENTITY_MAPPING: Final[str] = "ThcsSchoolNameMapping"
AUDIT_ACTION_APPLIED: Final[str] = "thcs_school_mapping_applied"
OPERATION_APPLY: Final[str] = "thcs_mapping_apply"

_APPLY_LOCKED_DETAIL: Final[str] = (
    "Áp ghép THẬT đang tạm khoá: chưa có quyết định về dòng THCS một năm (năm bắt "
    "đầu = năm kết thúc). Chỉ chạy thử được."
)

# Bộ lọc SƠ BỘ ở CSDL — CHỈ để thu hẹp số hồ sơ phải đọc. Nó là TẬP CHA của vị từ thật
# (:func:`is_thcs_manual_row`, Python): quyết định dòng nào thuộc nhóm / bị sửa luôn do vị từ thật.
_PREFILTER_JSONPATH: Final[str] = '$[*] ? (@.graduation_type == "THCS" || @.level == "THCS")'
_PREFILTER_JSONPATH_SQL = literal_column(f"'{_PREFILTER_JSONPATH}'::jsonpath")


def candidate_profiles_stmt(ids: Optional[Iterable[int]] = None):
    """Câu đọc hồ sơ CÓ THỂ có dòng THCS (lọc sơ bộ — tập CHA của :func:`is_thcs_manual_row`)."""
    t = AdmissionProfile.__table__
    stmt = (
        select(t.c.id, t.c.status, t.c.academic_year, t.c.area_resolution_basis, t.c.academic_history)
        .where(
            func.jsonb_typeof(t.c.academic_history) == "array",
            # Hằng ``::jsonpath`` viết thẳng: tham số ràng buộc của asyncpg bị ép ``::VARCHAR`` và PostgreSQL không
            # có ``jsonb_path_exists(jsonb, varchar)``.
            func.jsonb_path_exists(t.c.academic_history, _PREFILTER_JSONPATH_SQL),
        )
        .order_by(t.c.id)
    )
    if ids is not None:
        stmt = stmt.where(t.c.id.in_(sorted(set(ids))))
    return stmt


def is_apply_target(profile: dict) -> bool:
    """MỘT nguồn: hồ sơ thuộc phạm vi áp ghép (trạng thái cho phép + năm tuyển sinh). Chưa xét Quyết định."""
    return (
        profile.get("status") in APPLY_ELIGIBLE_STATUSES
        and profile.get("academic_year") == APPLY_ACADEMIC_YEAR
    )


def is_thcs_manual_row(entry: Any) -> bool:
    """MỘT nguồn: dòng lịch sử học THCS gõ tay (chưa gắn trường trong danh mục)."""
    return (
        isinstance(entry, dict)
        and (entry.get("graduation_type") == "THCS" or entry.get("level") == "THCS")
        and entry.get("school_id") is None
    )


def is_same_year_row(entry: dict) -> bool:
    """Dòng y→y: năm bắt đầu = năm kết thúc (nút "thêm 4 năm THCS" cũ sinh ra)."""
    y_from = entry.get("year_from")
    return y_from is not None and y_from == entry.get("year_to")


def is_apply_allowed() -> bool:
    """Đọc cờ tại THỜI ĐIỂM GỌI (không chụp lúc import). Truy cập thẳng thuộc tính — mất cờ ⇒ AttributeError, vẫn
    là fail-closed (xem ``finance_killswitch.is_period_close_allowed``)."""
    return bool(settings.THCS_MAPPING_APPLY_ENABLED)


def assert_apply_allowed() -> None:
    if not is_apply_allowed():
        raise ConflictError(
            detail=_APPLY_LOCKED_DETAIL,
            context={"flag": "THCS_MAPPING_APPLY_ENABLED", "operation": OPERATION_APPLY},
            public_payload={"operation": OPERATION_APPLY, "reason": "apply_disabled"},
        )


def _require_normalized_key(name: Any) -> str:
    key = name.strip() if isinstance(name, str) else ""
    if not key or normalize_thcs_school_name(key) != key:
        raise DomainValidationError(
            "Tên nhóm phải là tên đã chuẩn hoá (lấy từ danh sách nhóm)."
        )
    return key


def _school_usable(school: VnSchool) -> bool:
    return bool(school.is_active) and school.level in INTERNAL_CODE_LEVELS


class ThcsSchoolMappingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------ đọc

    async def _candidate_profiles(
        self, ids: Optional[Iterable[int]] = None
    ) -> list[dict[str, Any]]:
        """(id, status, area_resolution_basis, academic_history) của hồ sơ CÓ THỂ có dòng THCS (lọc sơ bộ)."""
        stmt = candidate_profiles_stmt(ids)
        return [dict(r._mapping) for r in (await self.db.execute(stmt)).all()]

    async def _mappings(self) -> dict[str, Tuple[ThcsSchoolNameMapping, VnSchool]]:
        stmt = select(ThcsSchoolNameMapping, VnSchool).join(
            VnSchool, VnSchool.id == ThcsSchoolNameMapping.school_id
        )
        return {
            m.normalized_name: (m, s) for m, s in (await self.db.execute(stmt)).all()
        }

    async def list_groups(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        mapped: Optional[bool] = None,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = min(max(1, page_size), 200)
        groups: dict[str, dict[str, Any]] = {}
        blank_rows = 0
        all_profiles: set[int] = set()
        for p in await self._candidate_profiles():
            if p["status"] in WITHDRAWN_STATUSES:
                continue
            for entry in p["academic_history"]:
                if not is_thcs_manual_row(entry):
                    continue
                raw = entry.get("school_name")
                key = normalize_thcs_school_name(raw)
                if not key:
                    blank_rows += 1
                    continue
                g = groups.setdefault(
                    key,
                    {
                        "variants": Counter(),
                        "rows": 0,
                        "profiles": set(),
                        "eligible": set(),
                        "same_year": 0,
                    },
                )
                g["variants"][" ".join(str(raw).split())] += 1
                g["rows"] += 1
                g["profiles"].add(p["id"])
                all_profiles.add(p["id"])
                if is_apply_target(p):
                    g["eligible"].add(p["id"])
                if is_same_year_row(entry):
                    g["same_year"] += 1
        mappings = await self._mappings()
        # Dòng ghép còn giữ mà không còn dòng gõ tay nào (đã áp, hoặc hồ sơ đã sửa) vẫn hiện — để huỷ ghép được.
        for key in mappings:
            groups.setdefault(
                key,
                {"variants": Counter(), "rows": 0, "profiles": set(), "eligible": set(), "same_year": 0},
            )
        items: list[dict[str, Any]] = []
        for key, g in groups.items():
            m = mappings.get(key)
            if mapped is True and m is None or mapped is False and m is not None:
                continue
            items.append(
                {
                    "normalized_name": key,
                    "variants": [
                        {"text": text, "row_count": n}
                        for text, n in sorted(g["variants"].items(), key=lambda kv: (-kv[1], kv[0]))
                    ],
                    "row_count": g["rows"],
                    "profile_count": len(g["profiles"]),
                    "eligible_profile_count": len(g["eligible"]),
                    "same_year_row_count": g["same_year"],
                    "mapping": None
                    if m is None
                    else {
                        "school_id": m[1].id,
                        "school_name": m[1].name,
                        "moet_school_code": m[1].moet_school_code,
                        "school_level": m[1].level,
                        "school_is_active": m[1].is_active,
                        "usable": _school_usable(m[1]),
                        "mapped_by_user_id": m[0].mapped_by_user_id,
                        "mapped_at": m[0].mapped_at,
                    },
                }
            )
        items.sort(key=lambda it: (-it["profile_count"], -it["row_count"], it["normalized_name"]))
        start = (page - 1) * page_size
        return {
            "items": items[start : start + page_size],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "summary": {
                "group_count": sum(1 for g in groups.values() if g["rows"]),
                "mapped_group_count": len(mappings),
                "row_count": sum(g["rows"] for g in groups.values()),
                "profile_count": len(all_profiles),
                "blank_name_row_count": blank_rows,
            },
        }

    # ------------------------------------------------------------------ ghép

    async def _usable_school(self, school_id: int) -> VnSchool:
        school = await self.db.get(VnSchool, school_id)
        if school is None:
            raise ResourceNotFoundError(f"VnSchool {school_id} not found")
        if not school.is_active:
            raise BusinessRuleViolation("Trường đã ngừng — không ghép được.")
        if school.level not in INTERNAL_CODE_LEVELS:
            raise BusinessRuleViolation(
                "Chỉ ghép với trường cấp THCS hoặc liên cấp THCS-THPT. Nếu đây là "
                "trường liên cấp đang ghi cấp THPT, sửa cấp của trường trước."
            )
        return school

    async def _ensure_unmapped(self, key: str) -> None:
        existing = (
            await self.db.execute(
                select(ThcsSchoolNameMapping).where(ThcsSchoolNameMapping.normalized_name == key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(
                f"Nhóm '{key}' đã ghép với trường #{existing.school_id} — huỷ ghép trước."
            )

    async def _insert_mapping(
        self, key: str, school: VnSchool, actor_id: int
    ) -> ThcsSchoolNameMapping:
        row = ThcsSchoolNameMapping(
            normalized_name=key, school_id=school.id, mapped_by_user_id=actor_id
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        await log_audit(
            self.db,
            AUDIT_ENTITY_MAPPING,
            row.id,
            "mapped",
            actor_user_id=actor_id,
            new_value={
                "normalized_name": key,
                "school_id": school.id,
                "moet_school_code": school.moet_school_code,
            },
            source="admin_panel",
        )
        return row

    async def map_group(
        self, normalized_name: str, school_id: int, actor_id: int
    ) -> ThcsSchoolNameMapping:
        key = _require_normalized_key(normalized_name)
        school = await self._usable_school(school_id)
        await self._ensure_unmapped(key)
        return await self._insert_mapping(key, school, actor_id)

    async def unmap_group(self, normalized_name: str, actor_id: int) -> dict[str, Any]:
        """Huỷ ghép = xoá dòng ghép. KHÔNG gỡ ``school_id`` đã áp vào hồ sơ (việc ấy sửa từng hồ sơ)."""
        key = _require_normalized_key(normalized_name)
        row = (
            await self.db.execute(
                select(ThcsSchoolNameMapping).where(ThcsSchoolNameMapping.normalized_name == key)
            )
        ).scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError(f"Nhóm '{key}' chưa ghép")
        old = {"normalized_name": key, "school_id": row.school_id, "mapped_by_user_id": row.mapped_by_user_id}
        row_id = row.id
        await self.db.delete(row)
        await self.db.flush()
        await log_audit(
            self.db,
            AUDIT_ENTITY_MAPPING,
            row_id,
            "unmapped",
            actor_user_id=actor_id,
            old_value=old,
            source="admin_panel",
        )
        return old

    async def create_school_from_group(
        self, normalized_name: str, school_data: dict[str, Any], actor_id: int
    ) -> Tuple[VnSchool, ThcsSchoolNameMapping]:
        """Tạo trường MỚI mã nội bộ NB (đúng luật ``VnSchoolService.create_school``) + ghép nhóm — một giao dịch."""
        key = _require_normalized_key(normalized_name)
        await self._ensure_unmapped(key)
        if (school_data.get("moet_school_code") or "").strip():
            raise DomainValidationError(
                "Trường tạo từ nhóm tên gõ tay luôn là trường mã nội bộ NB — để trống "
                "ô mã trường."
            )
        school, _ = await VnSchoolService(self.db).create_school(
            {**school_data, "moet_school_code": None}
        )
        school = await self._usable_school(school.id)
        return school, await self._insert_mapping(key, school, actor_id)

    # ------------------------------------------------------------------ áp ghép

    def _plan(
        self,
        profiles: list[dict[str, Any]],
        usable: dict[str, Tuple[int, str]],
        states: dict[int, Any],
    ) -> Tuple[list[dict[str, Any]], dict[str, int]]:
        eligible = set(APPLY_ELIGIBLE_STATUSES)
        plan: list[dict[str, Any]] = []
        c = Counter()
        for p in profiles:
            if p["status"] in WITHDRAWN_STATUSES:
                continue
            changes = []
            unmapped = 0
            for idx, entry in enumerate(p["academic_history"]):
                if not is_thcs_manual_row(entry):
                    continue
                hit = usable.get(normalize_thcs_school_name(entry.get("school_name")))
                if hit is None:
                    unmapped += 1
                    continue
                changes.append((idx, hit[0], hit[1], entry))
            if is_apply_target(p):
                c["unmapped_rows"] += unmapped
            if not changes:
                continue
            if p["status"] not in eligible:
                c["skipped_status_profiles"] += 1
                c["skipped_status_rows"] += len(changes)
                continue
            if not is_apply_target(p):  # đúng trạng thái nhưng khác năm tuyển sinh
                c["skipped_year_profiles"] += 1
                c["skipped_year_rows"] += len(changes)
                continue
            st = states.get(p["id"])
            if st is not None and (st.code != NO_DECISION or st.dau_appsheet or st.named_in_document):
                c["skipped_decision_profiles"] += 1
                continue
            plan.append({"profile": p, "changes": changes})
            c["rows_to_change"] += len(changes)
            c["profiles_to_change"] += 1
            if p["status"] == DRAFT_STATUS:
                c["draft_rows_to_change"] += len(changes)
                c["draft_profiles_to_change"] += 1
            same = sum(1 for ch in changes if is_same_year_row(ch[3]))
            c["same_year_rows"] += same
            c["same_year_profiles"] += 1 if same else 0
            if p.get("area_resolution_basis") == "manual_override":
                c["manual_kv_override_profiles"] += 1
        return plan, c

    async def apply_mappings(
        self,
        *,
        dry_run: bool = True,
        actor_id: Optional[int] = None,
        expected_rows_to_change: Optional[int] = None,
        expected_profiles_to_change: Optional[int] = None,
    ) -> dict[str, Any]:
        if not dry_run:
            # Cờ CHO PHÉP kiểm TRƯỚC mọi đọc / khoá / ghi (fail-closed, không ghi gì).
            assert_apply_allowed()
            if expected_rows_to_change is None or expected_profiles_to_change is None:
                raise DomainValidationError(
                    "Chế độ thật cần số dòng và số hồ sơ của lượt chạy thử ngay trước."
                )
        mappings = await self._mappings()
        usable = {k: (s.id, s.level) for k, (_m, s) in mappings.items() if _school_usable(s)}
        unusable = len(mappings) - len(usable)

        profiles = await self._candidate_profiles()
        if not dry_run:
            ids = [p["id"] for p in profiles]
            await lock_profiles(self.db, ids)
            profiles = await self._candidate_profiles(ids)  # đọc lại DƯỚI khoá
        touched = [
            p["id"]
            for p in profiles
            if is_apply_target(p)
            and any(
                is_thcs_manual_row(e) and normalize_thcs_school_name(e.get("school_name")) in usable
                for e in p["academic_history"]
            )
        ]
        states = await decision_state(self.db, touched, lock=False)
        plan, c = self._plan(profiles, usable, states)

        result: dict[str, Any] = {
            "dry_run": dry_run,
            "applied": False,
            "apply_enabled": is_apply_allowed(),
            "eligible_statuses": list(APPLY_ELIGIBLE_STATUSES),
            "academic_year": APPLY_ACADEMIC_YEAR,
            "rows_to_change": c["rows_to_change"],
            "profiles_to_change": c["profiles_to_change"],
            "draft_rows_to_change": c["draft_rows_to_change"],
            "draft_profiles_to_change": c["draft_profiles_to_change"],
            "same_year_rows": c["same_year_rows"],
            "same_year_profiles": c["same_year_profiles"],
            "manual_kv_override_profiles": c["manual_kv_override_profiles"],
            "skipped_status_profiles": c["skipped_status_profiles"],
            "skipped_status_rows": c["skipped_status_rows"],
            "skipped_year_profiles": c["skipped_year_profiles"],
            "skipped_year_rows": c["skipped_year_rows"],
            "skipped_decision_profiles": c["skipped_decision_profiles"],
            "unmapped_rows": c["unmapped_rows"],
            "unusable_mappings": unusable,
        }
        if dry_run:
            return result
        if (
            expected_rows_to_change != result["rows_to_change"]
            or expected_profiles_to_change != result["profiles_to_change"]
        ):
            raise ConflictError(
                detail=(
                    "Số dòng / hồ sơ sẽ đổi đã khác lượt chạy thử (dữ liệu vừa thay "
                    "đổi). Chạy thử lại rồi mới áp."
                ),
                public_payload={
                    "operation": OPERATION_APPLY,
                    "reason": "preview_mismatch",
                    "rows_to_change": result["rows_to_change"],
                    "profiles_to_change": result["profiles_to_change"],
                },
            )
        t = AdmissionProfile.__table__
        for item in plan:
            p = item["profile"]
            history = copy.deepcopy(p["academic_history"])
            old_rows, new_rows = [], []
            for idx, school_id, level, entry in item["changes"]:
                old_rows.append(
                    {
                        "index": idx,
                        "school_name": entry.get("school_name"),
                        "school_id": entry.get("school_id"),
                        "level": entry.get("level"),
                    }
                )
                history[idx]["school_id"] = school_id
                history[idx]["level"] = level
                new_rows.append({"index": idx, "school_id": school_id, "level": level})
            await self.db.execute(
                update(t)
                .where(t.c.id == p["id"])
                .values(
                    academic_history=history,
                    version=t.c.version + 1,
                    updated_at=func.now(),
                )
            )
            await log_audit(
                self.db,
                "AdmissionProfile",
                p["id"],
                AUDIT_ACTION_APPLIED,
                actor_user_id=actor_id,
                field_name="academic_history",
                old_value=old_rows,
                new_value=new_rows,
                reason="Áp ghép tên trường THCS gõ tay với danh mục trường",
                source="admin_panel",
            )
        await self.db.flush()
        result["applied"] = True
        return result
