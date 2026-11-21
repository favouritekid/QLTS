# app/services/admission_review_errors.py
"""GĐ2-B — MỌI lỗi miền của hợp đồng API GĐ2-B bản 4 §5 (lần xét nháp, điểm sàn, chạy kiểm hồ sơ, xem kết quả). Khuôn
``admission_quota_table_service.QuotaTableConflict``: ``public_payload`` mang ``reason_code`` (chữ thường) + dữ liệu CÔNG KHAI (chỉ
id / số / mã), handler đổ payload TRƯỚC rồi ``detail`` / ``error_code`` ghi đè (``middleware/exception_handlers.py``).

Quy ước mã (hợp đồng §1.3):

* 400 — ``error_code = "VALIDATION_ERROR"`` + ``reason_code`` (:class:`ReviewValidationError`);
* 404 — ``error_code = "RESOURCE_NOT_FOUND"`` + ``reason_code`` (:class:`ReviewNotFound`); run không có và run thuộc lần xét
  KHÁC trả CÙNG thân ``review_run_not_found`` (không lộ run có tồn tại ở lần xét khác);
* 409 riêng — ``error_code = reason_code`` viết hoa (:class:`ReviewConflict`);
* 409 ``ACADEMIC_INFO_IN_REVIEW_FLOOR`` — KHÔNG có ``reason_code`` (hợp đồng §5), câu báo chỉ tới HAI thao tác làm được
  (:class:`AcademicInfoInReviewFloor`; đặc tả §4.3);
* 503 cấu hình — MỘT ``error_code`` ``REVIEW_CONFIG_UNAVAILABLE``, phân biệt bằng ``reason_code`` (:class:`ReviewConfigUnavailable`);
* 503 ``PRIORITY_RATE_NOT_CONFIGURED`` — dùng NGUYÊN lớp có sẵn :class:`app.utils.exceptions.PriorityRateNotConfigured` (một nguồn;
  chỉ nhập lại ở đây cho đủ danh mục).

401 / 403 / 422 / 429 / 503 đóng băng / 500 đi đường có sẵn (``deps``, pydantic, bộ giới hạn, ``admission_freeze``, handler chung).

Lỗi trigger điểm sàn (SQLSTATE ``QLC02`` — ``app.models.admission_review_ddl``) được ``database_error_handler`` đổi ra ĐÚNG thân của
:func:`review_session_not_draft` gọi KHÔNG có ``status`` — MỘT nguồn câu / mã cho cả hai tầng.

``detail`` và payload KHÔNG chứa họ tên, CCCD hay dữ liệu cá nhân. Dịch vụ thuần: không import FastAPI.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.utils.exceptions import (
    ConflictError,
    PriorityRateNotConfigured,
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationError,
)

__all__ = [
    "AcademicInfoInReviewFloor",
    "PriorityRateNotConfigured",
    "ReviewConfigUnavailable",
    "ReviewConflict",
    "ReviewNotFound",
    "ReviewValidationError",
    "fee_gate_mode_invalid",
    "residence_proof_doc_type_missing",
    "review_floor_bad_member",
    "review_floor_duplicate",
    "review_quota_table_missing",
    "review_round_invalid",
    "review_run_in_progress",
    "review_run_not_done",
    "review_run_not_found",
    "review_session_not_draft",
    "review_session_not_found",
    "review_session_stale",
]

# ── Mã lý do (``reason_code``) — hợp đồng §5 ───────────────────────────────────────────────────────────────────────────
REVIEW_ROUND_INVALID = "review_round_invalid"
REVIEW_FLOOR_DUPLICATE = "review_floor_duplicate"
REVIEW_FLOOR_BAD_MEMBER = "review_floor_bad_member"
REVIEW_SESSION_NOT_FOUND = "review_session_not_found"
REVIEW_RUN_NOT_FOUND = "review_run_not_found"
REVIEW_QUOTA_TABLE_MISSING = "review_quota_table_missing"
REVIEW_SESSION_STALE = "review_session_stale"
REVIEW_SESSION_NOT_DRAFT = "review_session_not_draft"
REVIEW_RUN_IN_PROGRESS = "review_run_in_progress"
REVIEW_RUN_NOT_DONE = "review_run_not_done"
FEE_GATE_MODE_INVALID = "fee_gate_mode_invalid"
RESIDENCE_PROOF_DOC_TYPE_MISSING = "residence_proof_doc_type_missing"

ERROR_CODE_REVIEW_CONFIG_UNAVAILABLE = "REVIEW_CONFIG_UNAVAILABLE"
ERROR_CODE_ACADEMIC_INFO_IN_REVIEW_FLOOR = "ACADEMIC_INFO_IN_REVIEW_FLOOR"

#: Câu báo (tiếng Việt, không dữ liệu cá nhân) theo mã lý do. Câu có ``{…}`` được điền bằng số công khai ở hàm dựng lỗi.
MESSAGES: Dict[str, str] = {
    REVIEW_ROUND_INVALID: "Đợt tuyển sinh không tồn tại hoặc không thuộc năm của lần xét.",
    REVIEW_FLOOR_DUPLICATE: "Một học vụ xuất hiện nhiều lần trong danh sách điểm sàn — mỗi học vụ chỉ nhập một mức.",
    REVIEW_FLOOR_BAD_MEMBER: "Có học vụ không thuộc năm {academic_year} (không tồn tại, đã xoá, hoặc khác năm).",
    REVIEW_SESSION_NOT_FOUND: "Không tìm thấy lần xét.",
    REVIEW_RUN_NOT_FOUND: "Không tìm thấy lượt kiểm hồ sơ của lần xét này.",
    REVIEW_QUOTA_TABLE_MISSING: "Năm {academic_year} chưa có bảng chỉ tiêu — tạo bảng chỉ tiêu năm trước khi tạo lần xét.",
    REVIEW_SESSION_STALE: "Lần xét đã được sửa ở nơi khác sau khi bạn mở — hãy tải lại rồi làm lại.",
    REVIEW_SESSION_NOT_DRAFT: (
        "Lần xét không còn ở trạng thái nháp — không sửa điểm sàn, không chạy kiểm hồ sơ và không huỷ được nữa."
    ),
    REVIEW_RUN_IN_PROGRESS: (
        "Lần xét này đang có một lượt kiểm hồ sơ chạy — chờ lượt ấy xong rồi xem kết quả, không bấm lại."
    ),
    REVIEW_RUN_NOT_DONE: "Lượt kiểm hồ sơ chưa xong — chưa có dòng kết quả để xem.",
    FEE_GATE_MODE_INVALID: (
        "Cấu hình chế độ cổng học phí trên máy chủ không hợp lệ — không chạy kiểm hồ sơ. Báo quản trị hệ thống."
    ),
    RESIDENCE_PROOF_DOC_TYPE_MISSING: (
        "Máy chủ chưa cấu hình loại giấy xác nhận thông tin về cư trú — không chạy kiểm hồ sơ. Báo quản trị hệ thống."
    ),
}

#: Câu 409 ``ACADEMIC_INFO_IN_REVIEW_FLOOR`` — chỉ tới HAI thao tác làm được (đặc tả §4.3; hợp đồng §5).
MESSAGE_ACADEMIC_INFO_IN_REVIEW_FLOOR = (
    "Học vụ đang có điểm sàn ở lần xét nháp số {seq_no} năm {academic_year} — bỏ học vụ này khỏi danh sách sàn (lưu lại "
    "sàn) hoặc huỷ lần xét nháp đó, rồi làm lại."
)


def _payload(reason_code: str, extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {"reason_code": reason_code, **(extra or {})}


def _ids(values: Iterable[int]) -> List[int]:
    """Danh sách id công khai: số nguyên, bỏ trùng, TĂNG DẦN (hợp đồng §1.4 "Danh sách mã … đã sắp tăng dần")."""
    return sorted({int(v) for v in values})


class ReviewValidationError(ValidationError):
    """400 ``VALIDATION_ERROR`` + ``reason_code``."""

    def __init__(self, reason_code: str, payload: Optional[Dict[str, Any]] = None, *, detail: Optional[str] = None):
        super().__init__(detail=detail or MESSAGES[reason_code], public_payload=_payload(reason_code, payload))
        self.reason_code = reason_code


class ReviewNotFound(ResourceNotFoundError):
    """404 ``RESOURCE_NOT_FOUND`` + ``reason_code``."""

    def __init__(self, reason_code: str):
        super().__init__(detail=MESSAGES[reason_code], public_payload=_payload(reason_code, None))
        self.reason_code = reason_code


class ReviewConflict(ConflictError):
    """409 có mã lý do: ``error_code`` = ``reason_code`` viết hoa (khuôn ``QuotaTableConflict``)."""

    def __init__(self, reason_code: str, payload: Optional[Dict[str, Any]] = None, *, detail: Optional[str] = None):
        super().__init__(detail=detail or MESSAGES[reason_code], public_payload=_payload(reason_code, payload))
        self.reason_code = reason_code
        self.error_code = reason_code.upper()


class ReviewConfigUnavailable(ServiceUnavailableError):
    """503 ``REVIEW_CONFIG_UNAVAILABLE`` — cấu hình máy chủ thiếu / hỏng ⇒ không chạy kiểm hồ sơ (fail-closed). Không ghi gì."""

    error_code = ERROR_CODE_REVIEW_CONFIG_UNAVAILABLE

    def __init__(self, reason_code: str):
        super().__init__(detail=MESSAGES[reason_code], public_payload=_payload(reason_code, None))
        self.reason_code = reason_code


class AcademicInfoInReviewFloor(ConflictError):
    """409 ``ACADEMIC_INFO_IN_REVIEW_FLOOR`` (``PATCH`` học vụ có sẵn): dời năm học vụ đang có điểm sàn ở một lần xét NHÁP. Không có
    ``reason_code`` / trường thêm (hợp đồng §5). Khuôn ``admission_quota_table_service.AcademicInfoInQuotaGroup`` (R4). Nhiều lần xét
    nháp cùng giữ học vụ ⇒ người gọi truyền lần có ``seq_no`` NHỎ NHẤT (phụ lục kỹ thuật biên bản 21-11, điểm 5)."""

    error_code = ERROR_CODE_ACADEMIC_INFO_IN_REVIEW_FLOOR

    def __init__(self, seq_no: int, academic_year: int):
        super().__init__(
            detail=MESSAGE_ACADEMIC_INFO_IN_REVIEW_FLOOR.format(seq_no=int(seq_no), academic_year=int(academic_year))
        )


# ── Hàm dựng — MỘT chỗ cho mỗi dòng của hợp đồng §5 ────────────────────────────────────────────────────────────────────
def review_round_invalid(admission_round_id: int) -> ReviewValidationError:
    """400 — E1: đợt không có / khác năm."""
    return ReviewValidationError(REVIEW_ROUND_INVALID, {"admission_round_id": int(admission_round_id)})


def review_floor_duplicate(offering_academic_info_ids: Iterable[int]) -> ReviewValidationError:
    """400 — E4: học vụ trùng trong thân (danh sách id bị trùng, tăng dần)."""
    return ReviewValidationError(
        REVIEW_FLOOR_DUPLICATE, {"duplicate_offering_academic_info_ids": _ids(offering_academic_info_ids)}
    )


def review_floor_bad_member(offering_academic_info_ids: Iterable[int], academic_year: int) -> ReviewValidationError:
    """400 — E4: học vụ không có / đã xoá mềm / khác năm (kể cả vừa bị ``PATCH`` dời năm chạy trước). Liệt kê ĐỦ, tăng dần."""
    return ReviewValidationError(
        REVIEW_FLOOR_BAD_MEMBER,
        {"offering_academic_info_ids": _ids(offering_academic_info_ids)},
        detail=MESSAGES[REVIEW_FLOOR_BAD_MEMBER].format(academic_year=int(academic_year)),
    )


def review_session_not_found() -> ReviewNotFound:
    """404 — E3–E9: lần xét không có."""
    return ReviewNotFound(REVIEW_SESSION_NOT_FOUND)


def review_run_not_found() -> ReviewNotFound:
    """404 — E8, E9: run không có HOẶC thuộc lần xét khác (cùng thân)."""
    return ReviewNotFound(REVIEW_RUN_NOT_FOUND)


def review_quota_table_missing(academic_year: int) -> ReviewConflict:
    """409 — E1: năm chưa có bảng chỉ tiêu."""
    return ReviewConflict(
        REVIEW_QUOTA_TABLE_MISSING,
        {"academic_year": int(academic_year)},
        detail=MESSAGES[REVIEW_QUOTA_TABLE_MISSING].format(academic_year=int(academic_year)),
    )


def review_session_stale(current_version: int) -> ReviewConflict:
    """409 — E4, E5, E6: ``version`` gửi lên lệch phiên bản hiện tại. Không ghi gì."""
    return ReviewConflict(REVIEW_SESSION_STALE, {"current_version": int(current_version)})


def review_session_not_draft(status: Optional[str] = None) -> ReviewConflict:
    """409 — E4, E5, E6: lần xét không ở ``draft`` (cả khi huỷ chen giữa). ``status`` có khi dịch vụ biết; đường trigger CSDL
    (``QLC02``) gọi KHÔNG có ``status`` (hợp đồng §1.3 "trường ``status`` có thể vắng ở đường này")."""
    return ReviewConflict(REVIEW_SESSION_NOT_DRAFT, {"status": str(status)} if status is not None else None)


def review_run_in_progress() -> ReviewConflict:
    """409 — E6: lượt khác của cùng lần xét đang chạy (khoá thử bận)."""
    return ReviewConflict(REVIEW_RUN_IN_PROGRESS)


def review_run_not_done(status: str) -> ReviewConflict:
    """409 — E9: xem dòng của lượt chưa xong (chỉ có khi chạy nền — GĐ2-C)."""
    return ReviewConflict(REVIEW_RUN_NOT_DONE, {"status": str(status)})


def fee_gate_mode_invalid() -> ReviewConfigUnavailable:
    """503 — E6: chế độ cổng học phí không rõ / không hợp lệ (QĐB:19)."""
    return ReviewConfigUnavailable(FEE_GATE_MODE_INVALID)


def residence_proof_doc_type_missing() -> ReviewConfigUnavailable:
    """503 — E6: thiếu cấu hình loại giấy xác nhận cư trú."""
    return ReviewConfigUnavailable(RESIDENCE_PROOF_DOC_TYPE_MISSING)
