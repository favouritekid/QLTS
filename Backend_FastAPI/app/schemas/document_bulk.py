"""Schema GĐ1b — lô duyệt giấy (§5) + duyệt chéo tạm thời (§6). Hợp đồng API GĐ1b bản 4 §2.1, §2.2.

Tên trường / mã tiếng Anh (quy ước owner 17-11); chú thích tiếng Việt. Phản hồi lô KHÔNG mang tên / mã học sinh — id là đủ,
giao diện tự tra. Thân ``execute`` KHÔNG có danh sách mục (máy chủ chạy đúng danh sách đã lưu lúc xem trước — F373).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

INT4_MAX = 2**31 - 1

#: Trạng thái lô trả cho giao diện (§5.6) — suy từ trạng thái lưu + khoá tư vấn.
BATCH_VIEW_STATUSES = (
    "not_started",
    "starting",
    "expired",
    "running",
    "unknown",
    "interrupted_unfinalized",
    "completed",
    "stopped",
    "interrupted",
)
#: Kết quả từng mục trong ``BatchView`` (``pending`` = chưa có dòng kết quả bền).
BATCH_ITEM_VIEW_RESULTS = ("recorded", "error", "not_processed", "pending")

#: Bộ lọc ``payment_status`` — CHÉP của ``app/routers/admissions.py::ALLOWED_PAYMENT_STATUSES`` (schema không import router);
#: ``tests/unit/test_gd1b_lo_khoa_tu_van.py::test_bo_loc_thanh_toan_khop_danh_sach`` khoá hai bản bằng nhau.
PaymentStatusFilter = Literal["paid", "unpaid", "partial", "no_fee", "overdue"]


def _parse_id_csv(value: Optional[str]) -> Optional[List[int]]:
    """Cùng luật với ``routers/admissions._parse_id_csv``: danh sách id cách nhau dấu phẩy, mỗi id trong [1, INT4_MAX]."""
    if not value:
        return None
    try:
        ids = [int(x.strip()) for x in value.split(",") if x.strip()]
    except ValueError:
        raise ValueError("invalid id list")
    if any(not (1 <= i <= INT4_MAX) for i in ids):
        raise ValueError("invalid id list")
    return ids or None


class BulkVerifyFilter(BaseModel):
    """Tham số lọc của ``GET /api/admissions`` — cùng TÊN, cùng KIỂU (chuỗi id cách nhau dấu phẩy) để giao diện chuyển nguyên
    bộ lọc đang xem. Máy chủ áp đúng hàm lọc của danh sách, giao với tập chờ xét, rồi áp phạm vi Quản lý (§2.1)."""

    status: Optional[str] = Field(None, max_length=500)
    search: Optional[str] = Field(None, max_length=200)
    major_id: Optional[str] = Field(None, max_length=2000)
    academic_year: Optional[int] = Field(None, ge=1900, le=2999)
    degree_level: Optional[str] = Field(None, max_length=100)
    payment_status: Optional[PaymentStatusFilter] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    assigned_officer_id: Optional[str] = Field(None, max_length=2000)
    unit_id: Optional[int] = Field(None, ge=1, le=INT4_MAX)
    assigned_reviewer_id: Optional[str] = Field(None, max_length=2000)
    unassigned: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("major_id", "assigned_officer_id", "assigned_reviewer_id")
    @classmethod
    def _ids_hop_le(cls, v: Optional[str]) -> Optional[str]:
        _parse_id_csv(v)
        return v

    def statuses(self) -> Optional[List[str]]:
        if not self.status:
            return None
        return [s.strip() for s in self.status.split(",") if s.strip()] or None

    def major_ids(self) -> Optional[List[int]]:
        return _parse_id_csv(self.major_id)

    def officer_ids(self) -> Optional[List[int]]:
        return _parse_id_csv(self.assigned_officer_id)

    def reviewer_ids(self) -> Optional[List[int]]:
        return _parse_id_csv(self.assigned_reviewer_id)


class _ProfileIdsMixin(BaseModel):
    #: Trần 100 hồ sơ kiểm ở DỊCH VỤ (422 ``TOO_MANY_PROFILES`` kèm số đếm — hợp đồng §2.1). Giới hạn ở đây chỉ chặn thân
    #: bất thường.
    profile_ids: Optional[List[int]] = Field(None, max_length=10_000)

    @field_validator("profile_ids")
    @classmethod
    def _profile_ids_hop_le(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return None
        if any(not (1 <= i <= INT4_MAX) for i in v):
            raise ValueError("invalid profile id")
        return sorted(set(v))


class BulkVerifyPreviewRequest(_ProfileIdsMixin):
    """Đúng MỘT trong ``profile_ids`` / ``filter``."""

    filter: Optional[BulkVerifyFilter] = None
    include_optional: bool = False

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _dung_mot_nguon(self) -> "BulkVerifyPreviewRequest":
        if (self.profile_ids is None) == (self.filter is None):
            raise ValueError("exactly one of profile_ids / filter is required")
        if self.profile_ids is not None and not self.profile_ids:
            raise ValueError("profile_ids must not be empty")
        return self


class CrossBulkVerifyPreviewRequest(_ProfileIdsMixin):
    """Lô duyệt chéo (§6 "lô cùng khuôn §5"): chọn theo ``profile_ids`` (lấy từ hàng đợi chéo) + ``grant_id`` = quyền cho
    thao tác ``verify`` (``grant_id_by_action.verify`` của hàng đợi). KHÔNG nhận ``filter``: bộ lọc danh sách gồm tìm theo tên
    — cán bộ chéo chỉ có phản hồi hẹp, không được dò tên hồ sơ của đơn vị khác."""

    grant_id: int = Field(..., ge=1, le=INT4_MAX)
    include_optional: bool = False

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _co_ho_so(self) -> "CrossBulkVerifyPreviewRequest":
        if not self.profile_ids:
            raise ValueError("profile_ids is required")
        return self


class BulkVerifyExecuteRequest(BaseModel):
    """Chỉ ô xác nhận — KHÔNG danh sách mục (test khẳng định schema không có trường mục)."""

    confirmation_text: str = Field(..., min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BulkVerifyFinalizeRequest(BaseModel):
    """``reason`` BẮT BUỘC khi người gọi là Admin khác người tạo (dịch vụ kiểm — 422)."""

    reason: Optional[str] = Field(None, min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PreviewCounts(BaseModel):
    profiles: int
    #: N — số giấy của danh sách xác nhận (= ``len(items)``).
    documents: int
    required: int
    optional: int
    #: Owner Q3 (20-11, PR-B): M — số giấy bị loại vì hồ sơ do CHÍNH cán bộ chéo phụ trách (chỉ số đếm; định danh của nhóm
    #: này KHÔNG có ở ``items`` / ``excluded``). Lô thường luôn 0.
    own_assigned_excluded: int = 0


class PreviewItem(BaseModel):
    profile_id: int
    document_row_id: int
    document_type_code: Optional[str] = None
    expected_row_version: int
    is_mandatory: bool


class PreviewExcluded(BaseModel):
    profile_id: int
    document_row_id: int
    document_type_code: Optional[str] = None
    reason_code: str


class PreviewResponse(BaseModel):
    batch_id: UUID
    expires_at: datetime
    counts: PreviewCounts
    items: List[PreviewItem]
    excluded: List[PreviewExcluded]


class BatchCounts(BaseModel):
    profiles: int
    recorded: int
    error: int
    not_processed: int
    pending: int


#: Trạng thái lô ĐÃ SUY RA (§5.6) — 3 trạng thái kết thúc lưu bền + 6 trạng thái suy từ khoá. MỘT nguồn cho OpenAPI / giao
#: diện (bổ sung hợp đồng bản 6 C3); ``tests/unit/test_gd1b_lo_trang_thai_literal.py`` khoá bằng tập ``_derive_status`` trả.
BatchStatus = Literal[
    "completed", "stopped", "interrupted",
    "expired", "starting", "running", "not_started", "interrupted_unfinalized", "unknown",
]
#: Kết quả một mục — ``NULL`` trong CSDL hiển thị là ``pending``.
BatchItemResult = Literal["recorded", "error", "not_processed", "pending"]


class BatchItemView(BaseModel):
    profile_id: int
    document_row_id: int
    document_type_code: Optional[str] = None
    result: BatchItemResult
    reason_code: Optional[str] = None
    message: Optional[str] = None


class BatchView(BaseModel):
    batch_id: UUID
    status: BatchStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    finalized_at: Optional[datetime] = None
    finalized_by_user_id: Optional[int] = None
    finalize_reason: Optional[str] = None
    counts: BatchCounts
    items: List[BatchItemView]
    can_execute: bool
    can_finalize: bool
    #: Hợp đồng bản 5 B4: người gọi là Admin KHÁC người tạo VÀ ``can_finalize`` ⇒ chốt phải kèm ``reason`` (không thì 422).
    finalize_requires_reason: bool


class FinalizeResponse(BaseModel):
    batch: BatchView
    finalized_now: bool


class BatchSummary(BaseModel):
    """Không id hồ sơ / giấy / tên (§5.8)."""

    batch_id: UUID
    status: BatchStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    profile_count: int
    counts: BatchCounts


class BatchListResponse(BaseModel):
    items: List[BatchSummary]
    next_cursor: Optional[str] = None
    #: Hợp đồng bản 5 B4: người gọi dùng được ``scope=all`` (Admin, đường lô thường); đường lô chéo luôn ``False``.
    can_view_all: bool


class BulkVerifyEligibility(BaseModel):
    """Bổ sung hợp đồng bản 6 C1 — cờ "được chạy lô duyệt giấy" của CHÍNH người gọi (mục thanh bên, nút duyệt theo bộ lọc)."""

    eligible: bool


# ---------------------------------------------------------------------------------------------------------------------
# Duyệt chéo tạm thời (§6)
# ---------------------------------------------------------------------------------------------------------------------
class CrossReviewGrantCreate(BaseModel):
    grantee_user_id: int = Field(..., ge=1, le=INT4_MAX)
    unit_id: int = Field(..., ge=1, le=INT4_MAX)
    allow_verify: bool = False
    allow_reject: bool = False
    expires_at: datetime
    reason: str = Field(..., min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("expires_at")
    @classmethod
    def _co_mui_gio(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("expires_at must carry a timezone")
        return v

    @model_validator(mode="after")
    def _it_nhat_mot_thao_tac(self) -> "CrossReviewGrantCreate":
        if not (self.allow_verify or self.allow_reject):
            raise ValueError("at least one of allow_verify / allow_reject is required")
        return self


class CrossReviewGrantRevoke(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CrossReviewGrantView(BaseModel):
    id: int
    grantee_user_id: int
    unit_id: int
    allow_verify: bool
    allow_reject: bool
    granted_by_user_id: int
    granted_at: datetime
    expires_at: datetime
    reason: str
    revoked_at: Optional[datetime] = None
    revoked_by_user_id: Optional[int] = None
    is_active: bool


class CrossReviewEligibilityGrant(BaseModel):
    grant_id: int
    unit_id: int
    allow_verify: bool
    allow_reject: bool
    expires_at: datetime


class CrossReviewEligibility(BaseModel):
    eligible: bool
    grants: List[CrossReviewEligibilityGrant]


class GrantIdByAction(BaseModel):
    verify: Optional[int] = None
    reject: Optional[int] = None


class CrossReviewQueueItem(BaseModel):
    """Phản hồi HẸP (§6 + hợp đồng §2.2) — không tên, không đường dẫn tệp."""

    profile_id: int
    document_row_id: int
    document_type_code: Optional[str] = None
    row_version: int
    actual_submission_format: Optional[str] = None
    profile_status: str
    grant_id_by_action: GrantIdByAction


class CrossReviewQueuePage(BaseModel):
    items: List[CrossReviewQueueItem]
    page: int
    page_size: int
    total_count: int


class CrossReviewActionRequest(BaseModel):
    grant_id: int = Field(..., ge=1, le=INT4_MAX)
    profile_id: int = Field(..., ge=1, le=INT4_MAX)
    document_row_id: int = Field(..., ge=1, le=INT4_MAX)
    expected_row_version: int = Field(..., ge=1, le=INT4_MAX)
    reason: Optional[str] = Field(None, min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CrossReviewActionResponse(BaseModel):
    profile_id: int
    document_row_id: int
    action: str
    new_status: str
    row_version: int
