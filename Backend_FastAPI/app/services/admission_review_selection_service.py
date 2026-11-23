# app/services/admission_review_selection_service.py
"""GĐ2-C C2 — lựa chọn của Ban thư ký cho từng hồ sơ trong một lần xét NHÁP + phép kiểm cờ "đang ngừng" (để C4 gọi).

Nguồn: QĐB:12, QĐB:18; ĐT3 §3, §4 bước 3a, §11, T9, T16; thiết kế GĐ2-C 22-11 §2.2, §3.1, §4, §6 hàng C2; owner C2 22-11 (Ban
thư ký xem TOÀN TRƯỜNG — không lọc đơn vị), C5 22-11 (cờ "đang ngừng": ĐÚNG hai lựa chọn "Vẫn giữ" / "Loại khỏi lần này"), C6
22-11 ("Loại khỏi lần này" và "Chờ bổ sung" BẮT BUỘC lý do).

Luật (dịch vụ là lớp kiểm trước, trả lỗi rõ; bất biến CSDL ở trigger + CHECK):

* **Ghi** (:func:`record_selection`) — một giao dịch, thứ tự khoá (thiết kế §3.1 "ghi lựa chọn"): [cổng
  ``deps.require_review_secretary`` đã giữ dòng ``user`` của người bấm ``FOR SHARE`` + quyền gán ``FOR SHARE``] → dòng lần xét
  ``FOR UPDATE`` (KHÔNG lấy khoá năm) → hồ sơ ``FOR UPDATE`` → đọc lượt ``evaluate`` mới nhất + dòng của hồ sơ + lựa chọn hiệu lực
  → chèn. Khoá ngoại ``decided_by_user_id`` lấy ``FOR KEY SHARE`` trên dòng người bấm — cổng đã giữ ``FOR SHARE`` (mạnh hơn) ngay
  từ đầu, trước mọi khoá khác ⇒ không khoá thêm dòng ``user`` nào (cùng chiều K4 "người → các dòng khác"; không cần
  ``lock_users_in_id_order``). KHÔNG đọc / khoá dòng tiền nào.
* So ``based_on_row_hash`` với ``row_hash`` của dòng (lượt ``evaluate`` ĐÃ XONG mới nhất, hồ sơ) dưới khoá dòng lần xét — lượt
  chạy ghi kết quả cũng khoá dòng ấy ⇒ hai việc nối tiếp. Lệch ⇒ 409 ``SELECTION_STALE`` (ĐT3 T9), không ghi gì.
* ``supersedes_id`` gửi lên = lựa chọn hiệu lực người bấm đã thấy (``null`` = chưa có). Khác lựa chọn hiệu lực hiện tại ⇒ 409
  ``SELECTION_CHANGED`` — hai Thư ký bấm cùng hồ sơ thì người sau không đè im lặng lên người trước. [ĐX — thêm ngoài thiết kế.]
* Lý do bắt buộc với ``exclude_this_session`` / ``defer_supplement`` (owner C6) ⇒ 400 ``selection_reason_required``.
* Loại áp được cho dòng (:func:`kind_applicability_error` — MỘT vị từ cho cổng ghi VÀ danh sách giao diện), sai ⇒ 400
  ``selection_kind_not_applicable``:

  - bốn loại TRÙNG bốn mã gợi ý của GĐ2-B (:data:`KINDS_FROM_DECISION_HINTS`) áp được KHI VÀ CHỈ KHI máy xét đã gợi ý đúng mã ấy ở
    ``decision_hints`` của CHÍNH dòng (CLAUDE.md §7, rà hợp nhất 23-11 H5.2 — C2 ĐỌC dữ liệu GĐ2-B, không tự suy lại "khi nào trúng
    vượt / xét NV kế / chờ bổ sung / không cộng dân tộc" từ tab hay NV). Ba loại nói về NV ĐƯỢC XẾP còn cần dòng có NV được xếp —
    ràng buộc định nghĩa (``choice_id`` của lựa chọn = NV ấy); với dòng do máy xét dựng thì vế này luôn đúng khi có gợi ý (gợi ý chỉ
    ở ``needs_decision``, mà ``needs_decision`` luôn có NV được xếp — CHECK của ``admission_review_row``);
  - ``keep_despite_inactive`` (owner C5) cần dòng có NV được xếp VÀ mang cờ "đang ngừng" (cờ của GĐ2-B);
  - ``exclude_this_session`` áp cho mọi dòng.

  [ĐX — thu hẹp so với bản 22-11 (trước đây bốn loại áp cho mọi dòng có NV được xếp, "Chờ bổ sung" cho mọi dòng); xem bàn giao
  ``BAN-GIAO-C2-DUNG-LAI-2026-11-23.md``.]
* Lần xét không có ⇒ 404 ``review_session_not_found``; không ``draft`` ⇒ 409 ``REVIEW_SESSION_NOT_DRAFT`` (cùng mã GĐ2-B, câu
  riêng cho lựa chọn); hồ sơ không có trong lượt ``evaluate`` xong mới nhất (hoặc chưa có lượt xong, hoặc hồ sơ không còn) ⇒ 404
  ``selection_row_not_found``.

* **Cờ "đang ngừng"** (:func:`inactive_flag_blockers`, :func:`assert_inactive_flags_resolved` — C4 gọi lúc "Đề xuất khoá"): dòng
  của lượt ``evaluate`` mới nhất mang ``offering_inactive`` / ``major_inactive`` phải có lựa chọn hiệu lực thuộc
  :data:`~app.models.admission_review_selection.SELECTION_KINDS_RESOLVING_INACTIVE` VÀ còn khớp ``row_hash`` của dòng; thiếu /
  loại khác / lệch ⇒ chặn (409 ``INACTIVE_FLAG_UNRESOLVED`` kèm id hồ sơ).

Dịch vụ thuần: không import FastAPI, ném lỗi miền, chỉ ``flush`` (router commit). Log chỉ id + loại — không họ tên, không lý do.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.admission_review import REVIEW_SESSION_DRAFT
from app.models.admission_review_selection import (
    SELECTION_ADMIT_OVER_MAJOR_QUOTA,
    SELECTION_ADMIT_WITHOUT_ETHNIC_BONUS,
    SELECTION_CONSIDER_NEXT_CHOICE,
    SELECTION_KEEP_DESPITE_INACTIVE,
    SELECTION_KINDS,
    SELECTION_KINDS_REASON_REQUIRED,
    SELECTION_KINDS_RESOLVING_INACTIVE,
)
from app.repositories import admission_review_repository as review_repo
from app.repositories import admission_review_selection_repository as repo
from app.services import admission_review_errors as review_errors
from app.services.admission_review_rules import (
    FLAG_MAJOR_INACTIVE,
    FLAG_OFFERING_INACTIVE,
    HINT_ADMIT_OVER_MAJOR_QUOTA,
    HINT_ADMIT_WITHOUT_ETHNIC_BONUS,
    HINT_CONSIDER_NEXT_CHOICE,
    HINT_DEFER_SUPPLEMENT,
)
from app.utils.exceptions import ConflictError, ResourceNotFoundError, ValidationError

log = structlog.get_logger(__name__)

#: Cờ "ngành / loại hình đang ngừng" của GĐ2-B (QĐB:18) — MỘT nguồn (hằng của luật GĐ2-B).
INACTIVE_FLAGS: Tuple[str, ...] = (FLAG_OFFERING_INACTIVE, FLAG_MAJOR_INACTIVE)
#: Bốn loại lựa chọn mà GĐ2-B đã GỢI Ý theo từng dòng (``decision_hints`` — hợp đồng API GĐ2-B bản 4 §4.9; đặc tả bản 4 §6.6 bước 5:
#: trúng vượt khi vượt / bằng điểm và nhóm còn chỗ sau phần ``auto``; NV kế khi còn NV sau xét được — không bao giờ học vụ chỉ tiêu
#: 0; chờ bổ sung + không cộng dân tộc khi ưu tiên dân tộc ``undetermined``). Mã lựa chọn = mã gợi ý (test khoá). Loại thuộc tập này
#: áp được cho dòng KHI VÀ CHỈ KHI dòng mang đúng gợi ý ấy — MỘT nguồn là máy xét GĐ2-B (CLAUDE.md §7).
KINDS_FROM_DECISION_HINTS = frozenset(
    {HINT_ADMIT_OVER_MAJOR_QUOTA, HINT_CONSIDER_NEXT_CHOICE, HINT_DEFER_SUPPLEMENT, HINT_ADMIT_WITHOUT_ETHNIC_BONUS}
)
#: Loại lựa chọn nói về NV ĐƯỢC XẾP của dòng (trúng vượt chỉ tiêu ngành của NV ấy / bỏ NV ấy xét NV kế / điểm của NV ấy không
#: cộng dân tộc / giữ NV ấy dù đang ngừng) ⇒ dòng phải có NV được xếp. Ràng buộc ĐỊNH NGHĨA (``choice_id`` của lựa chọn = NV ấy),
#: không phải luật "khi nào áp được" — luật ấy là gợi ý của GĐ2-B (:data:`KINDS_FROM_DECISION_HINTS`) và cờ "đang ngừng".
KINDS_NEEDING_PLACED_CHOICE = frozenset(
    {
        SELECTION_ADMIT_OVER_MAJOR_QUOTA,
        SELECTION_CONSIDER_NEXT_CHOICE,
        SELECTION_ADMIT_WITHOUT_ETHNIC_BONUS,
        SELECTION_KEEP_DESPITE_INACTIVE,
    }
)

# ── Mã lý do (``reason_code``) — khuôn hợp đồng API GĐ2-B §1.3 ───────────────────────────────────────────────────────────
REASON_REQUIRED = "selection_reason_required"
KIND_NOT_APPLICABLE = "selection_kind_not_applicable"
ROW_NOT_FOUND = "selection_row_not_found"
SELECTION_STALE = "selection_stale"
SELECTION_CHANGED = "selection_changed"
INACTIVE_FLAG_UNRESOLVED = "inactive_flag_unresolved"

#: Câu báo (tiếng Việt, không dữ liệu cá nhân). Câu MỚI — chờ owner duyệt (bàn giao C2 §câu chữ).
MESSAGES: Dict[str, str] = {
    REASON_REQUIRED: "Lựa chọn \"Loại khỏi lần này\" và \"Chờ bổ sung\" phải ghi lý do.",
    KIND_NOT_APPLICABLE: "Lựa chọn này không áp dụng cho hồ sơ ở kết quả hiện tại — tải lại kết quả rồi chọn lại.",
    ROW_NOT_FOUND: "Hồ sơ không có trong lượt kiểm hồ sơ mới nhất của lần xét này — tải lại kết quả.",
    SELECTION_STALE: "Kết quả của hồ sơ này đã đổi sau khi bạn mở (có lượt kiểm hồ sơ mới) — tải lại rồi chọn lại.",
    SELECTION_CHANGED: "Lựa chọn của hồ sơ này vừa được người khác đổi — tải lại rồi chọn lại.",
    INACTIVE_FLAG_UNRESOLVED: (
        "Còn hồ sơ có ngành / loại hình đang ngừng mà Ban thư ký chưa chọn \"Vẫn giữ\" hoặc \"Loại khỏi lần này\" "
        "(hoặc lựa chọn đã cũ so với kết quả mới nhất)."
    ),
}
#: Câu 409 lần xét không còn nháp — CÙNG mã GĐ2-B (``REVIEW_SESSION_NOT_DRAFT``), câu riêng cho lựa chọn.
MESSAGE_SESSION_NOT_DRAFT = "Lần xét không còn ở trạng thái nháp — không ghi lựa chọn được nữa."


class SelectionValidationError(ValidationError):
    """400 — ``error_code = "VALIDATION_ERROR"`` + ``reason_code``."""

    def __init__(self, reason_code: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(detail=MESSAGES[reason_code], public_payload={"reason_code": reason_code, **(payload or {})})
        self.reason_code = reason_code


class SelectionNotFound(ResourceNotFoundError):
    """404 — ``error_code = "RESOURCE_NOT_FOUND"`` + ``reason_code``."""

    def __init__(self, reason_code: str = ROW_NOT_FOUND):
        super().__init__(detail=MESSAGES[reason_code], public_payload={"reason_code": reason_code})
        self.reason_code = reason_code


class SelectionConflict(ConflictError):
    """409 — ``error_code = reason_code`` viết hoa; payload chỉ id / mã băm / mã."""

    def __init__(self, reason_code: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(detail=MESSAGES[reason_code], public_payload={"reason_code": reason_code, **(payload or {})})
        self.reason_code = reason_code
        self.error_code = reason_code.upper()


def normalize_note(note: Optional[str]) -> Optional[str]:
    """Lý do: bỏ khoảng trắng hai đầu; trắng ⇒ ``None`` (CHECK CSDL cấm lý do trắng)."""
    note = (note or "").strip()
    return note or None


def kind_applicability_error(
    kind: str,
    *,
    considered_choice_id: Optional[int],
    flags: Sequence[str],
    decision_hints: Sequence[str],
) -> Optional[str]:
    """``None`` = loại ``kind`` áp được cho dòng; ngược lại mã lý do 400. Hàm THUẦN (test bảng chân trị + test khoá với dòng THẬT
    của máy xét GĐ2-B). ``flags`` / ``decision_hints`` = đúng hai cột của ``admission_review_row`` (dữ liệu GĐ2-B)."""
    if kind not in SELECTION_KINDS:
        return KIND_NOT_APPLICABLE
    if kind in KINDS_NEEDING_PLACED_CHOICE and considered_choice_id is None:
        return KIND_NOT_APPLICABLE
    if kind in KINDS_FROM_DECISION_HINTS and kind not in set(decision_hints or ()):
        return KIND_NOT_APPLICABLE
    if kind == SELECTION_KEEP_DESPITE_INACTIVE and not set(flags or ()) & set(INACTIVE_FLAGS):
        return KIND_NOT_APPLICABLE
    return None


def applicable_selection_kinds(
    *, considered_choice_id: Optional[int], flags: Sequence[str], decision_hints: Sequence[str]
) -> List[str]:
    """Các loại Ban thư ký chọn được cho một dòng (đúng thứ tự hiển thị) — CÙNG vị từ với cổng ghi
    (:func:`kind_applicability_error`). Route dòng kết quả (L4 — khi mở cho Ban thư ký) đưa danh sách này vào bản xem dòng để giao
    diện hiện đúng nút theo máy chủ (thin client)."""
    return [
        k
        for k in SELECTION_KINDS
        if kind_applicability_error(
            k, considered_choice_id=considered_choice_id, flags=flags, decision_hints=decision_hints
        )
        is None
    ]


def _view(sel: models.AdmissionReviewSelection, current_row_hash: Optional[str], username: Any, full_name: Any) -> Dict[str, Any]:
    return {
        "id": sel.id,
        "session_id": sel.session_id,
        "profile_id": sel.profile_id,
        "kind": sel.kind,
        "choice_id": sel.choice_id,
        "based_on_run_id": sel.based_on_run_id,
        "based_on_row_hash": sel.based_on_row_hash,
        "decided_by_user_id": sel.decided_by_user_id,
        "decided_by_username": username,
        "decided_by_full_name": full_name,
        "decided_at": sel.decided_at,
        "note": sel.note,
        "supersedes_id": sel.supersedes_id,
        # Dòng hiện tại không có (hồ sơ rời lượt mới nhất) hoặc mã băm lệch ⇒ lựa chọn đã CŨ.
        "is_stale": current_row_hash is None or current_row_hash != sel.based_on_row_hash,
    }


# ---------------------------------------------------------------------------------------------------------------------
# Ghi
# ---------------------------------------------------------------------------------------------------------------------
async def record_selection(
    db: AsyncSession,
    *,
    session_id: int,
    profile_id: int,
    kind: str,
    based_on_row_hash: str,
    supersedes_id: Optional[int],
    note: Optional[str],
    actor_id: int,
) -> Dict[str, Any]:
    """Ghi MỘT lựa chọn mới cho (lần xét, hồ sơ). Trả bản xem của dòng vừa chèn. Không ghi gì khi lỗi."""
    note = normalize_note(note)
    if kind in SELECTION_KINDS_REASON_REQUIRED and note is None:
        raise SelectionValidationError(REASON_REQUIRED, {"kind": kind})

    # Khoá: lần xét FOR UPDATE (không khoá năm) → hồ sơ FOR UPDATE.
    session = await review_repo.lock_session(db, session_id)
    if session is None:
        raise review_errors.review_session_not_found()
    if session.status != REVIEW_SESSION_DRAFT:
        raise review_errors.ReviewConflict(
            review_errors.REVIEW_SESSION_NOT_DRAFT, {"status": str(session.status)}, detail=MESSAGE_SESSION_NOT_DRAFT
        )
    if not await repo.lock_profile(db, profile_id):
        raise SelectionNotFound()

    run_id = await repo.latest_done_evaluate_run_id(db, session_id)
    row = await repo.get_row(db, run_id, profile_id) if run_id is not None else None
    if row is None:
        raise SelectionNotFound()
    if based_on_row_hash != row.row_hash:
        raise SelectionConflict(SELECTION_STALE, {"latest_run_id": int(run_id), "current_row_hash": row.row_hash})
    current = await repo.effective_selection(db, session_id, profile_id)
    current_id = current.id if current is not None else None
    if supersedes_id != current_id:
        raise SelectionConflict(SELECTION_CHANGED, {"current_selection_id": current_id})
    problem = kind_applicability_error(
        kind, considered_choice_id=row.considered_choice_id, flags=row.flags, decision_hints=row.decision_hints
    )
    if problem is not None:
        raise SelectionValidationError(problem, {"kind": kind})

    sel = await repo.insert_selection(
        db,
        {
            "session_id": session_id,
            "academic_year": session.academic_year,
            "profile_id": profile_id,
            "kind": kind,
            "choice_id": row.considered_choice_id,
            "based_on_run_id": run_id,
            "based_on_row_hash": row.row_hash,
            "decided_by_user_id": actor_id,
            "decided_at": await repo.db_clock(db),
            "note": note,
            "supersedes_id": current_id,
        },
    )
    log.info(
        "review_selection_recorded",
        selection_id=sel.id,
        session_id=session_id,
        profile_id=profile_id,
        kind=kind,
        supersedes_id=current_id,
    )
    person = await repo.user_summary(db, actor_id)
    return _view(sel, row.row_hash, person[0] if person else None, person[1] if person else None)


# ---------------------------------------------------------------------------------------------------------------------
# Đọc
# ---------------------------------------------------------------------------------------------------------------------
async def _require_session(db: AsyncSession, session_id: int) -> None:
    if not await repo.session_exists(db, session_id):
        raise review_errors.review_session_not_found()


async def list_selections(db: AsyncSession, *, session_id: int) -> Dict[str, Any]:
    """Lựa chọn HIỆU LỰC của mọi hồ sơ trong lần xét (Ban thư ký xem toàn trường — không lọc đơn vị) + lượt mới nhất."""
    await _require_session(db, session_id)
    latest = await repo.latest_done_evaluate_run_id(db, session_id)
    items = [_view(s, h, un, fn) for s, h, un, fn in await repo.list_effective_selections(db, session_id)]
    return {"session_id": session_id, "latest_run_id": latest, "items": items}


async def selection_history(db: AsyncSession, *, session_id: int, profile_id: int) -> Dict[str, Any]:
    """Mọi lựa chọn của một hồ sơ trong lần xét (mới trước) + id lựa chọn hiệu lực (``None`` = chưa có)."""
    await _require_session(db, session_id)
    rows = await repo.selection_history(db, session_id, profile_id)
    items = [_view(s, h, un, fn) for s, h, un, fn in rows]
    replaced = {i["supersedes_id"] for i in items if i["supersedes_id"] is not None}
    effective = next((i["id"] for i in items if i["id"] not in replaced), None)
    return {"session_id": session_id, "profile_id": profile_id, "effective_selection_id": effective, "items": items}


# ---------------------------------------------------------------------------------------------------------------------
# Cờ "đang ngừng" — phép kiểm để C4 ("Đề xuất khoá") gọi
# ---------------------------------------------------------------------------------------------------------------------
PROBLEM_MISSING = "missing"  # chưa có lựa chọn
PROBLEM_NOT_RESOLVING = "not_resolving"  # có lựa chọn nhưng không phải "Vẫn giữ" / "Loại khỏi lần này"
PROBLEM_STALE = "stale"  # lựa chọn dựa trên dòng cũ (mã băm lệch dòng hiện tại)


@dataclass(frozen=True)
class InactiveFlagBlocker:
    profile_id: int
    flags: Tuple[str, ...]
    problem: str
    selection_id: Optional[int]


def classify_inactive_row(
    *, row_hash: str, selection_kind: Optional[str], selection_row_hash: Optional[str]
) -> Optional[str]:
    """Một dòng MANG cờ "đang ngừng": ``None`` = đã xử lý; ngược lại một trong ``PROBLEM_*``. Hàm THUẦN (test bảng chân trị).
    Owner C5: chỉ ``keep_despite_inactive`` / ``exclude_this_session`` xử lý được cờ; lựa chọn phải còn khớp dòng hiện tại."""
    if selection_kind is None:
        return PROBLEM_MISSING
    if selection_kind not in SELECTION_KINDS_RESOLVING_INACTIVE:
        return PROBLEM_NOT_RESOLVING
    if selection_row_hash != row_hash:
        return PROBLEM_STALE
    return None


async def inactive_flag_blockers(db: AsyncSession, session_id: int) -> List[InactiveFlagBlocker]:
    """Dòng của lượt ``evaluate`` mới nhất mang cờ "đang ngừng" mà CHƯA được xử lý (MỘT câu đọc). Chưa có lượt xong ⇒ rỗng (C4
    chặn đề xuất vì lý do khác). Người gọi (C4) phải giữ dòng lần xét ``FOR UPDATE`` để kết quả còn đúng tới lúc ghi."""
    out: List[InactiveFlagBlocker] = []
    for r in await repo.rows_with_flags_and_effective_selection(db, session_id, INACTIVE_FLAGS):
        problem = classify_inactive_row(
            row_hash=r.row_hash, selection_kind=r.selection_kind, selection_row_hash=r.selection_row_hash
        )
        if problem is not None:
            out.append(
                InactiveFlagBlocker(
                    profile_id=int(r.profile_id),
                    flags=tuple(sorted(set(r.flags or ()) & set(INACTIVE_FLAGS))),
                    problem=problem,
                    selection_id=r.selection_id,
                )
            )
    return out


async def assert_inactive_flags_resolved(db: AsyncSession, session_id: int) -> None:
    """Chặn "Đề xuất khoá" khi còn dòng cờ "đang ngừng" chưa xử lý ⇒ 409 ``INACTIVE_FLAG_UNRESOLVED`` (id hồ sơ tăng dần)."""
    blockers = await inactive_flag_blockers(db, session_id)
    if blockers:
        raise SelectionConflict(INACTIVE_FLAG_UNRESOLVED, {"profile_ids": sorted(b.profile_id for b in blockers)})
