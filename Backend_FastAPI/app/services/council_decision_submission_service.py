# app/services/council_decision_submission_service.py
"""Lượt gửi ghi nhận Quyết định — vòng giao diện GĐ1 (đặc tả bản 2 mục 3.7; bản 3 mục 3.7.2, 3.7.6).

Mục đích: mất mạng khi gửi ghi nhận KHÔNG gây ghi đôi và KHÔNG báo sai "chưa ghi". Mã lượt (uuid, không dữ liệu cá
nhân) do máy chủ cấp; trình duyệt không lưu (khôi phục qua id bộ).

Vòng đời (chỉ đổi khi commit; mỗi chuyển là MỘT câu đặt đủ cột — F265):

* mở lượt ⇒ ``cho_gui``;
* ghi nhận: câu khoá DÒNG đầu tiên khoá lượt ``cho_gui`` (:func:`lock_pending_submission`, ``FOR UPDATE``, GIỮ ``cho_gui``) —
  thứ tự khoá chung ([khoá năm chia sẻ — PR-1 GĐ1 P2] → lượt → văn bản → mục chờ → bộ → hồ sơ → học vụ → đường xét); câu CUỐI
  trước commit
  :func:`finalize_recorded` đặt ``da_ghi`` + ``decision_id`` + sha + ``ket_thuc_luc``. Bị từ chối / lỗi ⇒ rollback ⇒ vẫn
  ``cho_gui`` (gửi lại cùng mã được — sha chỉ chốt khi thành công);
* phân xử (:func:`adjudicate`): ``UPDATE … WHERE trang_thai = 'cho_gui'`` dưới ``lock_timeout`` ⇒ ``da_chan`` / đọc lại
  (``da_ghi`` ⇒ trả văn bản; ``da_chan`` ⇒ lặp luỹ đẳng) / hết hạn ⇒ :class:`SubmissionProcessing` (router ROLLBACK trước khi
  trả "đang xử lý").

F272: nhánh "0 dòng" của ghi nhận và của phân xử CHỈ ĐỌC (không ``FOR UPDATE`` / ``FOR SHARE``, không ghi, không khoá
bộ / văn bản) và kết thúc giao dịch ngay — câu ``FOR UPDATE`` / ``UPDATE`` ở READ COMMITTED có thể đã khoá phiên bản
mới nhất của một lượt đã kết thúc rồi mới thấy nó không còn ``cho_gui`` (giữ khoá tới hết giao dịch); xoá bộ (dây chuyền
``SET NULL``) có thể phải CHỜ khoá ấy, nhưng không có cạnh chờ ngược.
"""
import hashlib
import json
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.council_document import CouncilDecisionSubmission
from app.repositories.council_decision_repository import db_error_codes
from app.utils.exceptions import ConflictError, ResourceNotFoundError, ServiceError

#: Tên chỉ mục duy nhất một phần "mỗi bộ tối đa một lượt chưa rõ".
ONE_PENDING_SUBMISSION_ONLY = "uq_council_decision_submission_cho_gui"
#: Trần chờ khoá của phân xử (đặc tả 3.7.4).
ADJUDICATION_WAIT_CAP = "5s"
#: Số lần thử mở lượt khi lượt cũ vừa kết thúc giữa câu chèn và câu đọc (bản 3 mục 3.7.2).
MAX_OPEN_ATTEMPTS = 3

NOT_RECORDED_BLOCKED = "chua_ghi_da_chan"
RECORDED = "da_ghi"
PROCESSING = "dang_xu_ly"


class SubmissionProcessingError(Exception):
    """Phân xử hết ``lock_timeout`` (55P03): giao dịch ghi nhận đang giữ lượt. Router PHẢI rollback rồi trả
    ``dang_xu_ly`` — không kết luận gì."""


def check_submission_code(code: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(code))
    except (ValueError, TypeError, AttributeError):
        raise ConflictError(
            "Mã lượt gửi không hợp lệ.", public_payload={"ma_loi": "luot_khong_hop_le"}
        ) from None


def submission_content_sha(
    *,
    set_id: int,
    kind: str,
    root_id: Optional[int],
    decision_number: str,
    signing_date: date,
    paper_params: Optional[Dict[str, Any]],
    confirm_profile_count: object,
    confirm_printed_copy_match: object,
    confirm_status: Optional[Dict[str, int]],
    template_note: Optional[str],
    sha_scan: str,
) -> str:
    """sha256 của dạng JSON CHUẨN (khoá sắp xếp, không khoảng trắng) mọi thứ đã gửi trong một lần ghi nhận — gồm sha
    của tệp scan (không phải bytes). Cùng mã + cùng sha ⇒ gửi lặp (trả lại bản cũ); khác sha ⇒ 409."""
    paper_values = {
        k: (v.isoformat() if isinstance(v, date) else v)
        for k, v in sorted((paper_params or {}).items())
    }
    package = {
        "set_id": set_id,
        "loai": kind,
        "goc_id": root_id,
        "so_quyet_dinh": decision_number,
        "ngay_ky": signing_date.isoformat(),
        "tham_so_giay": paper_values,
        "xac_nhan_so_ho_so": confirm_profile_count,
        "xac_nhan_khop_ban_in": confirm_printed_copy_match,
        "xac_nhan_trang_thai": dict(sorted((confirm_status or {}).items())),
        "ghi_chu_mau": template_note,
        "sha_scan": sha_scan,
    }
    return hashlib.sha256(
        json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


async def _set_pending_submission(db: AsyncSession, set_id: int) -> Optional[CouncilDecisionSubmission]:
    return (
        await db.execute(
            select(CouncilDecisionSubmission).where(
                CouncilDecisionSubmission.set_id == set_id,
                CouncilDecisionSubmission.trang_thai == "cho_gui",
            )
        )
    ).scalar_one_or_none()


async def open_submission(db: AsyncSession, *, set_id: int, actor_id: int) -> CouncilDecisionSubmission:
    """Mở MỘT lượt ``cho_gui`` cho bộ (flush; router commit rồi mới trả mã). Bộ đang có lượt chưa rõ ⇒ 409
    ``luot_dang_cho`` kèm mã cũ. Lượt cũ vừa kết thúc giữa câu chèn và câu đọc ⇒ thử lại (tối đa
    :data:`MAX_OPEN_ATTEMPTS` lần) rồi 409 ``luot_dang_thay_doi`` không mã. Bộ không còn (khoá ngoại) ⇒ 404."""
    for _ in range(MAX_OPEN_ATTEMPTS):
        submission = CouncilDecisionSubmission(
            ma=uuid.uuid4(),
            set_id=set_id,
            set_id_luc_tao=set_id,
            trang_thai="cho_gui",
            nguoi_tao_id=actor_id,
        )
        try:
            async with db.begin_nested():
                db.add(submission)
                await db.flush()
            return submission
        except IntegrityError as e:
            sqlstate, constraint = db_error_codes(e)
            if sqlstate == "23503":
                raise ResourceNotFoundError("Không có bộ văn bản này.") from None
            if sqlstate != "23505" or constraint != ONE_PENDING_SUBMISSION_ONLY:
                raise ServiceError("Lỗi CSDL khi mở lượt gửi ghi nhận — không mở.") from None
        old = await _set_pending_submission(db, set_id)
        if old is not None:
            raise ConflictError(
                "Bộ đang có lượt gửi ghi nhận chưa rõ kết quả — bấm \"Kiểm tra trên máy chủ\" trước.",
                public_payload={
                    "ma_loi": "luot_dang_cho",
                    "ma": str(old.ma),
                    "tao_luc": old.tao_luc.isoformat() if old.tao_luc else None,
                },
            )
    raise ConflictError(
        "Lượt gửi trước của bộ vừa thay đổi — tải lại trạng thái bộ rồi thử lại.",
        public_payload={"ma_loi": "luot_dang_thay_doi", "ma": None},
    )


async def lock_pending_submission(
    db: AsyncSession, *, code: uuid.UUID, set_id: int
) -> Optional[CouncilDecisionSubmission]:
    """Câu khoá DÒNG đầu tiên của ghi nhận (sau khoá năm chia sẻ): khoá lượt ``cho_gui`` của đúng bộ, GIỮ ``cho_gui`` (F265). Lượt đang bị giao
    dịch ghi khác giữ ⇒ CHỜ; sau commit PostgreSQL đánh giá lại ``trang_thai = 'cho_gui'`` trên bản mới ⇒ None."""
    return (
        await db.execute(
            select(CouncilDecisionSubmission)
            .where(
                CouncilDecisionSubmission.ma == code,
                CouncilDecisionSubmission.set_id == set_id,
                CouncilDecisionSubmission.trang_thai == "cho_gui",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def read_submission(db: AsyncSession, code: uuid.UUID) -> Optional[CouncilDecisionSubmission]:
    """Đọc KHÔNG khoá (ảnh chụp mới của câu này ở READ COMMITTED) — dùng ở các nhánh "0 dòng" (F272: chỉ đọc)."""
    return (
        await db.execute(
            select(CouncilDecisionSubmission)
            .where(CouncilDecisionSubmission.ma == code)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def check_submission_finished(old: Optional[CouncilDecisionSubmission], *, set_id: int, sha: str) -> Optional[int]:
    """Nhánh "0 dòng" của ghi nhận (chỉ đọc). Trả ``decision_id`` khi đây là gửi LẶP đúng nội dung của lượt ``da_ghi``
    (router trả lại văn bản cũ, 200); mọi trường hợp khác ⇒ 409 với mã lỗi riêng."""
    if old is None or old.set_id_luc_tao != set_id:
        raise ConflictError(
            "Mã lượt gửi không thuộc bộ này — tải lại trạng thái bộ.",
            public_payload={"ma_loi": "luot_khong_hop_le"},
        )
    if old.trang_thai == "da_chan":
        raise ConflictError(
            "Lượt gửi này đã bị chặn (chưa ghi) — mở lượt gửi mới.",
            public_payload={"ma_loi": "luot_da_chan"},
        )
    if old.trang_thai == "da_ghi":
        if old.noi_dung_sha != sha:
            raise ConflictError(
                "Lượt gửi này ĐÃ ghi nhận với nội dung khác — không ghi lần hai.",
                public_payload={"ma_loi": "luot_da_dung_noi_dung_khac", "decision_id": old.decision_id},
            )
        return old.decision_id
    raise ServiceError("Trạng thái lượt gửi không xác định — không ghi.")


async def finalize_recorded(db: AsyncSession, *, submission_id: int, decision_id: int, sha: str) -> None:
    """Câu CUỐI trước commit: MỘT câu đặt đủ ``trang_thai`` + ``decision_id`` + ``noi_dung_sha`` + ``ket_thuc_luc``
    (CHECK kiểm theo câu). Số dòng ≠ 1 ⇒ lỗi (không thể khi đang giữ khoá — chốt fail-closed)."""
    r = await db.execute(
        update(CouncilDecisionSubmission)
        .where(CouncilDecisionSubmission.id == submission_id, CouncilDecisionSubmission.trang_thai == "cho_gui")
        .values(
            trang_thai="da_ghi",
            decision_id=decision_id,
            noi_dung_sha=sha,
            ket_thuc_luc=text("now()"),
        )
        .execution_options(synchronize_session=False)
    )
    if r.rowcount != 1:
        raise ServiceError("Không chốt được lượt gửi ghi nhận — không ghi.")


async def adjudicate(db: AsyncSession, code: uuid.UUID) -> Tuple[str, Optional[int]]:
    """Phân xử lượt chưa rõ (đặc tả 3.7.4). Trả ``(kết quả, decision_id)``:

    * cập nhật được ⇒ ``(chua_ghi_da_chan, None)`` — router COMMIT rồi mới trả;
    * 0 dòng ⇒ đọc lại: ``da_ghi`` ⇒ ``(da_ghi, id)``; ``da_chan`` ⇒ ``(chua_ghi_da_chan, None)`` (lặp luỹ đẳng);
      không có ⇒ 404;
    * hết ``lock_timeout`` (55P03) ⇒ :class:`SubmissionProcessing` (giao dịch đã hỏng — router ROLLBACK).

    Không nhánh nào suy "chưa ghi" từ 404."""
    await db.execute(text("SET LOCAL lock_timeout = '%s'" % ADJUDICATION_WAIT_CAP))
    try:
        r = await db.execute(
            update(CouncilDecisionSubmission)
            .where(CouncilDecisionSubmission.ma == code, CouncilDecisionSubmission.trang_thai == "cho_gui")
            .values(trang_thai="da_chan", ket_thuc_luc=text("now()"))
            .returning(CouncilDecisionSubmission.id)
            .execution_options(synchronize_session=False)
        )
        already_blocked = r.first() is not None
    except DBAPIError as e:
        if db_error_codes(e)[0] == "55P03":
            raise SubmissionProcessingError() from None
        raise
    if already_blocked:
        return NOT_RECORDED_BLOCKED, None
    old = await read_submission(db, code)
    if old is None:
        raise ResourceNotFoundError("Không có lượt gửi này.")
    if old.trang_thai == "da_chan":
        return NOT_RECORDED_BLOCKED, None
    if old.trang_thai == "da_ghi":
        return RECORDED, old.decision_id
    raise ServiceError("Trạng thái lượt gửi không xác định.")


async def set_submission(db: AsyncSession, set_id: int) -> List[CouncilDecisionSubmission]:
    return list(
        (
            await db.execute(
                select(CouncilDecisionSubmission)
                .where(CouncilDecisionSubmission.set_id == set_id)
                .order_by(CouncilDecisionSubmission.id)
            )
        ).scalars()
    )


async def has_pending_submission(db: AsyncSession, set_id: int) -> Optional[CouncilDecisionSubmission]:
    """Đọc KHÔNG khoá — dùng ở xoá bộ (đã khoá bộ trước): không chờ dòng lượt nào (F272)."""
    return await _set_pending_submission(db, set_id)
