# app/schemas/admission_review.py
"""GĐ2-B — thân request / phản hồi của 9 API lần xét nháp (hợp đồng API GĐ2-B bản 4 ``b877fba1…`` §1–§4, E1–E9).

Tên trường tiếng Anh (owner 17-11); mã có sẵn của GĐ1 / engine giữ nguyên chữ trong giá trị. Mọi thân request ``extra = "forbid"``
(khoá lạ ⇒ 422 — kể cả mọi khoá kiểu "vượt chỉ tiêu": hợp đồng §1.1, HĐ10). Giới hạn số phần tử / độ dài là giới hạn KỸ THUẬT
(hợp đồng ghi rõ), không phải con số nghiệp vụ.

Điểm (hợp đồng §1.4): request nhận SỐ hoặc CHUỖI thập phân, ``>= 0``, tối đa hai chữ số thập phân, ``<= 999.99``; phản hồi luôn là
CHUỖI đúng hai chữ số (``admission_review_rules.format_score`` — một nguồn). Phản hồi KHÔNG có CCCD, điện thoại, ngày sinh, địa
chỉ, tên dân tộc, và không có trường / tham số nào cho phép vượt chỉ tiêu (hợp đồng §3.5, §1.8).
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Chuỗi điểm của phản hồi (hợp đồng §1.4, HĐ3).
SCORE_TEXT_PATTERN = r"^\d{1,3}\.\d{2}$"
#: Chuỗi điểm của REQUEST: 1–3 chữ số ASCII phần nguyên, tối đa 2 chữ số thập phân (không dấu, không mũ; ``[0-9]`` chứ không ``\d`` —
#: ``\d`` của Python khớp cả chữ số Unicode khác, ``Decimal`` lại nhận chúng).
_SCORE_IN_TEXT = re.compile(r"^[0-9]{1,3}(\.[0-9]{1,2})?$")
_CENT = Decimal("0.01")
FLOOR_SCORE_MAX = Decimal("999.99")  # NUMERIC(5,2) của ``admission_review_floor.floor_score`` — giới hạn kỹ thuật

#: Giới hạn kỹ thuật (hợp đồng §2 E4, E5; §1.6).
FLOORS_MAX_ITEMS = 500
CANCEL_REASON_MAX_LENGTH = 1000
LIST_PAGE_SIZE_MAX = 100  # E2, E7
LIST_PAGE_SIZE_DEFAULT = 20
ROWS_PAGE_SIZE_MAX = 200  # E9
ROWS_PAGE_SIZE_DEFAULT = 50
#: E9 — mẫu tham số lọc (hợp đồng §2 E9).
ROW_REASON_CODE_PATTERN = r"^[A-Za-z0-9_:]+$"
ROW_FLAG_PATTERN = r"^[a-z0-9_]+$"

SessionStatus = Literal["draft", "cancelled"]  # hợp đồng §4.1 (C nới ``locked``, ``signed``)
SessionAction = Literal["edit_floors", "run_evaluate", "cancel"]  # hợp đồng §4.2
RowTab = Literal["auto", "needs_decision", "not_passed", "ineligible"]  # hợp đồng §4.5


def parse_floor_score(value: Any) -> Decimal:
    """Điểm sàn gửi lên ⇒ ``Decimal`` hai chữ số. Số nguyên / số thực (giá trị phải biểu diễn được bằng ≤ 2 chữ số thập phân) hoặc
    chuỗi ``^[0-9]{1,3}(\\.[0-9]{1,2})?$``; ``>= 0``; ``<= 999.99``. ``bool``, NaN, vô cực, chuỗi mũ / có dấu ⇒ lỗi (⇒ 422). Số thực đi qua
    ``repr`` (chuỗi ngắn nhất) — ``0.1 + 0.2`` không lọt thành ``0.30``."""
    if isinstance(value, bool):
        raise ValueError("điểm sàn phải là số hoặc chuỗi thập phân")
    if isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("điểm sàn không hợp lệ")
        d = Decimal(repr(value))
    elif isinstance(value, str):
        s = value.strip()
        if not _SCORE_IN_TEXT.fullmatch(s):
            raise ValueError("điểm sàn phải là số thập phân, tối đa hai chữ số sau dấu chấm")
        d = Decimal(s)
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("điểm sàn không hợp lệ")
        d = value
    else:
        raise ValueError("điểm sàn phải là số hoặc chuỗi thập phân")
    try:
        q = d.quantize(_CENT)
    except InvalidOperation:
        raise ValueError("điểm sàn không hợp lệ") from None
    if q != d:
        raise ValueError("điểm sàn tối đa hai chữ số sau dấu chấm")
    if q < 0 or q > FLOOR_SCORE_MAX:
        raise ValueError("điểm sàn phải trong khoảng 0 đến 999.99")
    if q == 0:
        q = Decimal("0.00")  # không để "-0.00"
    return q


# ═══════════════════════════════════════════ request ═══════════════════════════════════════════
class ReviewSessionCreateIn(BaseModel):
    """E1 — tạo lần xét nháp cho một năm + một đợt (đợt phải thuộc đúng năm)."""

    academic_year: int = Field(..., ge=2000, le=2100, description="Năm tuyển sinh")
    admission_round_id: int = Field(..., ge=1, description="Đợt tuyển sinh — thuộc đúng năm")

    model_config = ConfigDict(extra="forbid")


class ReviewFloorIn(BaseModel):
    offering_academic_info_id: int = Field(..., ge=1, description="Học vụ cùng năm với lần xét, có thật, chưa xoá mềm")
    floor_score: Decimal = Field(
        ..., description="Số hoặc chuỗi thập phân, >= 0, tối đa 2 chữ số thập phân, <= 999.99 — so với tổng điểm ĐÃ cộng ưu tiên"
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("floor_score", mode="before")
    @classmethod
    def _floor_score(cls, v: Any) -> Decimal:
        return parse_floor_score(v)


class ReviewFloorsPutIn(BaseModel):
    """E4 — thay TOÀN BỘ điểm sàn; mảng rỗng = xoá hết. ``version`` = phiên bản lần xét đang xem (lệch ⇒ 409, không ghi gì)."""

    version: int = Field(..., ge=1)
    floors: List[ReviewFloorIn] = Field(..., max_length=FLOORS_MAX_ITEMS)

    model_config = ConfigDict(extra="forbid")


class ReviewSessionCancelIn(BaseModel):
    """E5 — huỷ lần xét nháp (giải phóng mọi điểm sàn). Lý do bắt buộc (1–1000 ký tự sau khi cắt khoảng trắng), lưu vết."""

    version: int = Field(..., ge=1)
    reason: str = Field(..., description="Lý do huỷ — bắt buộc, lưu vết")

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("lý do huỷ không được để trống")
        if len(v) > CANCEL_REASON_MAX_LENGTH:
            raise ValueError("lý do huỷ tối đa %d ký tự" % CANCEL_REASON_MAX_LENGTH)
        return v


class ReviewRunCreateIn(BaseModel):
    """E6 — chạy kiểm hồ sơ. KHÔNG có trường nào khác (không vượt chỉ tiêu / sàn / điều kiện — hợp đồng §2 E6, HĐ10)."""

    kind: Literal["evaluate"]
    session_version: int = Field(..., ge=1)

    model_config = ConfigDict(extra="forbid")


# ═══════════════════════════════════════════ phản hồi ═══════════════════════════════════════════
class AdmissionRoundRefOut(BaseModel):
    id: int
    round_code: str
    round_name: str


class QuotaTableStateOut(BaseModel):
    """Bảng chỉ tiêu năm — ``SessionOut.quota_table`` là trạng thái HIỆN TẠI; ``RunInputs.quota_table`` là lúc chạy."""

    status: str
    version: int
    quota_fingerprint: str


class FloorOut(BaseModel):
    offering_academic_info_id: int
    floor_score: str = Field(..., pattern=SCORE_TEXT_PATTERN)
    major_code: Optional[str] = None
    major_name: Optional[str] = None
    offering_type: Optional[str] = None
    #: ``null`` = chưa cấu hình; ``0`` = đóng tuyệt đối (hợp đồng §1.4).
    annual_admission_quota: Optional[int] = None
    group_code: Optional[str] = None
    is_deleted: bool
    updated_by_user_id: int
    updated_at: datetime


class RunSummaryOut(BaseModel):
    """Một dòng của danh sách run (E7) / ``latest_run`` (E2, E3)."""

    id: int
    kind: str
    status: str
    rule_version: str
    requested_by_user_id: int
    requested_at: datetime
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    tab_counts: Optional[Dict[str, int]] = None
    config_changed_since_run: bool


class SessionOut(BaseModel):
    """E1, E3, E4, E5 — chi tiết lần xét. ``floors`` luôn ``[]`` khi ``cancelled`` (P4)."""

    id: int
    academic_year: int
    admission_round: AdmissionRoundRefOut
    seq_no: int
    status: str
    version: int
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime
    cancelled_by_user_id: Optional[int] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    quota_table: QuotaTableStateOut
    floors: List[FloorOut]
    latest_run: Optional[RunSummaryOut] = None
    latest_done_run_id: Optional[int] = None
    #: CÙNG hàm với cổng ghi (``admission_review_service.session_actions``) — giao diện hiện nút theo cờ này, không theo ``status``.
    available_actions: List[SessionAction]


class SessionListItemOut(BaseModel):
    id: int
    academic_year: int
    admission_round: AdmissionRoundRefOut
    seq_no: int
    status: str
    version: int
    created_by_user_id: int
    created_at: datetime
    floor_count: int
    latest_run: Optional[RunSummaryOut] = None


class SessionPageOut(BaseModel):
    items: List[SessionListItemOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class RunFloorInputOut(BaseModel):
    offering_academic_info_id: int
    floor_score: str = Field(..., pattern=SCORE_TEXT_PATTERN)


class RunInputsOut(BaseModel):
    """Đầu vào của run — BẤT BIẾN; ``floors`` là ẢNH CHỤP GIÁ TRỊ (P4), không tham chiếu bảng sàn."""

    academic_year: int
    session_version: int
    floors: List[RunFloorInputOut]
    quota_table: QuotaTableStateOut
    fee_gate_mode: str
    snapshot_at: datetime


class RunSummaryCountsOut(BaseModel):
    """``RunSummary`` (hợp đồng §3.3) — chỉ số đếm + mã."""

    rows_total: int
    pool_total: int
    tab_counts: Dict[str, int]
    reason_counts: Dict[str, int]
    flag_counts: Dict[str, int]
    warnings: List[str]


class QuotaViewMajorOut(BaseModel):
    offering_academic_info_id: int
    offering_id: Optional[int] = None
    major_code: Optional[str] = None
    major_name: Optional[str] = None
    offering_type: Optional[str] = None
    group_id: Optional[int] = None
    group_code: Optional[str] = None
    annual_admission_quota: Optional[int] = None
    floor_score: Optional[str] = None
    used_publish: int
    used_approved: int
    used: int
    remaining: Optional[int] = None
    state: str
    candidates: int
    auto: int
    needs_decision: int
    offering_inactive: bool
    major_inactive: bool


class QuotaViewGroupOut(BaseModel):
    group_id: int
    code: str
    name: str
    ceiling: int
    used_publish: int
    used_approved: int
    used: int
    auto_in_run: int
    remaining_after_auto: int
    would_exceed: bool


class QuotaViewOut(BaseModel):
    majors: List[QuotaViewMajorOut]
    groups: List[QuotaViewGroupOut]


class RunOut(BaseModel):
    """E6 (202), E8 — chi tiết run. Mọi trường trừ ``config_changed_since_run`` (tính lúc GET) là bất biến (hợp đồng §7)."""

    id: int
    session_id: int
    kind: str
    status: str
    rule_version: str
    requested_by_user_id: int
    requested_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    inputs: RunInputsOut
    summary: Optional[RunSummaryCountsOut] = None
    quota_view: Optional[QuotaViewOut] = None
    config_changed_since_run: bool


class RunPageOut(BaseModel):
    items: List[RunSummaryOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentGapsOut(BaseModel):
    missing: List[str]
    not_verified: List[str]


class ConsideredChoiceOut(BaseModel):
    choice_id: int
    display_order: int
    offering_academic_info_id: int
    offering_id: int
    admission_path_id: int
    major_code: Optional[str] = None
    major_name: Optional[str] = None
    offering_type: Optional[str] = None


class ScorePartsOut(BaseModel):
    subject_total: Optional[str] = None
    area: Optional[str] = None
    object: Optional[str] = None
    priority_total: Optional[str] = None


class PerChoiceOut(BaseModel):
    choice_id: int
    display_order: int
    offering_academic_info_id: Optional[int] = None
    status: str
    reason_codes: List[str]
    review_total: Optional[str] = None
    floor_score: Optional[str] = None


class PriorYearFindingOut(BaseModel):
    """Cờ A13 kèm năm + căn cứ (phụ lục kỹ thuật đợt 1 §1 — thêm trường phản hồi, loại "không phá")."""

    year: int
    basis: str
    status: Optional[str] = None


class RowOut(BaseModel):
    """E9 — một em trong một run. ``full_name`` / ``unit_id`` đọc LÚC GET (không bất biến); mọi trường khác bất biến."""

    profile_id: int
    full_name: Optional[str] = None
    unit_id: Optional[int] = None
    profile_status: str
    tab: str
    reason_codes: List[str]
    flags: List[str]
    decision_hints: List[str]
    document_gaps: Optional[DocumentGapsOut] = None
    considered_choice: Optional[ConsideredChoiceOut] = None
    review_total: Optional[str] = None
    score_parts: Optional[ScorePartsOut] = None
    floor_score: Optional[str] = None
    rank_in_major: Optional[int] = None
    within_seats: Optional[bool] = None
    ethnic_priority_state: Optional[str] = None
    per_choice: List[PerChoiceOut]
    prior_year_findings: List[PriorYearFindingOut]
    row_hash: str


class RowPageOut(BaseModel):
    items: List[RowOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    #: Số dòng theo tab của CẢ run (không theo bộ lọc).
    tab_counts: Dict[str, int]
