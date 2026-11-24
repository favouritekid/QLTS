# app/services/admission_review_floor_candidate_service.py
"""GĐ2-B — S1 / E10 ``GET /api/admission-config/review-sessions/{session_id}/floor-candidates``: danh sách học vụ của năm lần xét cho
màn nhập điểm sàn (owner G4 24-11 "làm thêm chức năng máy chủ nhỏ"; thiết kế giao diện GĐ2-B §4.1; ĐÍNH CHÍNH 24-11 §3; rà TK2 / TK4;
phụ lục HĐ4 E10).

Bất biến (một nguồn — CLAUDE.md §7; giao diện KHÔNG tự suy luật):

* Dữ kiện học vụ dựng bằng CHÍNH bộ đọc của máy xét (``admission_review_loader.load_floor_candidate_facts`` — cùng câu đọc, cùng
  ``academic_info_facts`` với ``load_run_facts``; lấy cả học vụ đã xoá mềm), toàn bộ trong MỘT ảnh chụp ``REPEATABLE READ READ ONLY``
  (``council_candidate_repository.read_only_transaction`` — khuôn E6).
* Tập học vụ = tập của ``quota_view`` (``admission_review_rules.quota_view_academic_info_ids`` — ĐÚNG năm, kể cả đã xoá).
* ``state`` = ``admission_review_rules.quota_state(ai, có sàn đang lưu)`` — CÙNG hàm ``quota_view`` dùng.
* ``floor_applicable`` = ``admission_review_rules.floor_applicable`` (suy từ ``quota_state``) — nhóm "Cần nhập sàn" của giao diện.
* ``floor_accepted`` ("E4 nhận được") = ``admission_review_service.floor_member_accepted`` — CÙNG vị từ ``review_floor_bad_member``
  của E4. Cờ theo HỌC VỤ; lần xét còn sửa sàn được hay không đọc ở ``available_actions`` (``session_actions`` — cổng của E4).

Chỉ đọc; không khoá dòng nào; không import FastAPI. Không dữ liệu cá nhân (chỉ học vụ / ngành / nhóm / số).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from app.repositories.council_candidate_repository import read_only_transaction
from app.services import admission_review_loader as loader
from app.services import admission_review_rules as rules
from app.services.admission_review_service import floor_member_accepted, session_actions

if TYPE_CHECKING:
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncEngine


def _sort_key(item: Dict[str, Any]) -> Tuple[Any, ...]:
    """Sắp (phụ lục HĐ4 E10): mã ngành, nhãn loại hình (trống xếp sau), rồi id học vụ — thứ tự trình bày, không phải luật."""
    return (
        item["major_code"] is None,
        item["major_code"] or "",
        item["offering_type"] is None,
        item["offering_type"] or "",
        item["offering_academic_info_id"],
    )


def floor_candidate_item(
    ai: rules.AcademicInfoFacts, *, floor: Optional["Decimal"], group_code: Optional[str], academic_year: int
) -> Dict[str, Any]:
    """Một phần tử ``FloorCandidateOut``. ``floor`` = mức đang lưu ở lần xét (``None`` = chưa có sàn)."""
    return {
        "offering_academic_info_id": int(ai.offering_academic_info_id),
        "offering_id": ai.offering_id,
        "major_code": ai.major_code,
        "major_name": ai.major_name,
        "offering_type": ai.offering_type,
        "annual_admission_quota": ai.annual_quota,
        "group_id": ai.group_id,
        "group_code": group_code,
        "is_deleted": bool(ai.is_deleted),
        "offering_inactive": bool(ai.offering_inactive),
        "major_inactive": bool(ai.major_inactive),
        "floor_score": rules.format_score(floor),
        "state": rules.quota_state(ai, floor is not None),
        "floor_applicable": rules.floor_applicable(ai),
        "floor_accepted": floor_member_accepted(ai, academic_year),
    }


def build_floor_candidates_out(loaded: loader.LoadedFloorCandidates) -> Dict[str, Any]:
    """``FloorCandidatesOut`` từ dữ kiện đã nạp (thuần — không đọc CSDL)."""
    year = int(loaded.academic_year)
    items = []
    for ai_id in rules.quota_view_academic_info_ids(loaded.academic_infos, year):
        ai = loaded.academic_infos[ai_id]
        items.append(
            floor_candidate_item(
                ai,
                floor=loaded.floors.get(ai_id),
                group_code=loaded.group_codes.get(ai.group_id) if ai.group_id is not None else None,
                academic_year=year,
            )
        )
    items.sort(key=_sort_key)
    state_counts = {s: 0 for s in rules.QUOTA_STATES}
    for item in items:
        state_counts[item["state"]] += 1  # trạng thái lạ ⇒ KeyError (500) — không đếm lặng lẽ
    return {
        "session_id": int(loaded.session_id),
        "academic_year": year,
        "session_version": int(loaded.session_version),
        "session_status": loaded.session_status,
        "available_actions": session_actions(loaded.session_status),
        "quota_table": dict(loaded.quota_table),
        "items": items,
        "state_counts": state_counts,
    }


async def get_floor_candidates(engine: "AsyncEngine", session_id: int) -> Dict[str, Any]:
    """E10 — đọc MỘT ảnh chụp ``REPEATABLE READ READ ONLY`` trên kết nối riêng của ``engine`` (khuôn E6) rồi dựng phản hồi. Lần xét
    không có ⇒ 404 ``review_session_not_found``."""
    async with read_only_transaction(engine) as (conn, _snapshot):
        loaded = await loader.load_floor_candidate_facts(conn, session_id=session_id)
    return build_floor_candidates_out(loaded)
