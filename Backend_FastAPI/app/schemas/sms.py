# app/schemas/sms.py
"""
Pydantic v2 schemas cho SMS Marketing — PR-2 (Contact Management BE).

Bao gồm: contact group CRUD, contact CRUD, membership, consent-event
ledger (append-only), kết quả import. Các enum literal mirror đúng CHECK
constraint ở model (app/models/sms/) để validate fail-fast (400) trước khi
chạm DB. Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4 + §10.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _strip_required_text(v):
    """Strip + chặn chuỗi toàn khoảng trắng cho trường NOT NULL. None
    (field không gửi / gửi null ở Update) giữ nguyên để service xử lý."""
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("không được rỗng/toàn khoảng trắng")
    return v


def validate_consent_datetime(dt, *, label="thời điểm"):
    """Yêu cầu datetime CÓ timezone và KHÔNG ở tương lai.

    Naive datetime bị TỪ CHỐI (KHÔNG tự coi là UTC): client gửi giờ địa
    phương (vd Asia/Saigon +07) mà coi là UTC sẽ lệch 7h → giờ hiện tại bị
    xem là "tương lai" + sai thứ tự consent ledger. Bắt buộc tz tường minh.
    Dung sai 5' cho lệch đồng hồ. Raise ValueError (Pydantic → 422)."""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        raise ValueError(f"{label} phải kèm timezone (vd +07:00 hoặc Z)")
    if dt > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError(f"{label} không được ở tương lai")
    return dt


def validate_future_datetime(dt, *, label="thời điểm"):
    """Yêu cầu tz-aware + PHẢI ở tương lai (link hết hạn không được quá khứ/
    naive → tránh tạo link chết hoặc expiry lệch 7h). Raise → 422."""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        raise ValueError(f"{label} phải kèm timezone (vd +07:00 hoặc Z)")
    if dt <= datetime.now(timezone.utc):
        raise ValueError(f"{label} phải ở tương lai")
    return dt


def _strip_optional_url(v):
    """Strip URL optional; chuỗi rỗng sau strip → None (chống lưu whitespace)."""
    if v is None:
        return v
    v = v.strip()
    return v or None


# --- Enum literal (mirror CHECK constraint model) ---
GroupType = Literal["parent", "student", "teacher", "lead", "custom"]
ConsentBasis = Literal[
    "explicit_form", "signed_form", "recorded_call", "imported_proof"
]
RevokeSource = Literal[
    "sms_reply", "landing_optout", "manual", "phone_call",
    "external_suppression",
]
ConsentEventType = Literal["granted", "revoked"]


# =====================================================================
# Contact Group
# =====================================================================
class SmsContactGroupCreate(BaseModel):
    """Tạo nhóm liên hệ. `code` tùy chọn — service tự slugify từ `name`."""

    name: str = Field(..., min_length=1, max_length=200)
    code: Optional[str] = Field(
        None, max_length=50, pattern=r"^[a-z0-9][a-z0-9-]*$",
        description="slug duy nhất; bỏ trống để tự sinh từ name",
    )
    group_type: GroupType
    description: Optional[str] = Field(None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _v_name(cls, v):
        return _strip_required_text(v)


class SmsContactGroupUpdate(BaseModel):
    """Sửa nhóm — không cho đổi `code` (slug bền vững)."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    group_type: Optional[GroupType] = None
    description: Optional[str] = Field(None, max_length=2000)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _v_name(cls, v):
        return _strip_required_text(v)


class SmsContactGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    group_type: str
    description: Optional[str] = None
    is_active: bool
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    member_count: Optional[int] = Field(
        None, description="số thành viên (chỉ điền ở list/detail có đếm)"
    )


class SmsContactGroupList(BaseModel):
    total: int
    items: List[SmsContactGroupOut]


# =====================================================================
# Contact
# =====================================================================
class SmsContactCreate(BaseModel):
    """Tạo 1 liên hệ. `phone` là số gốc — service normalize + validate
    mobile-only. Consent KHÔNG set ở đây (mặc định `unknown`); dùng
    endpoint consent-events để ghi bằng chứng."""

    full_name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=1, max_length=32)
    note: Optional[str] = Field(None, max_length=2000)
    source_label: Optional[str] = Field(None, max_length=255)

    @field_validator("full_name")
    @classmethod
    def _v_full_name(cls, v):
        return _strip_required_text(v)


class SmsContactUpdate(BaseModel):
    """Sửa identity/note — KHÔNG cho đổi `phone` (identity unique) và
    KHÔNG đụng consent ledger (dùng consent-events)."""

    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    note: Optional[str] = Field(None, max_length=2000)
    source_label: Optional[str] = Field(None, max_length=255)

    @field_validator("full_name")
    @classmethod
    def _v_full_name(cls, v):
        return _strip_required_text(v)


class SmsContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    phone_raw: Optional[str] = None
    phone_normalized: str
    phone_international: str
    note: Optional[str] = None
    source_label: Optional[str] = None
    marketing_consent_status: str
    marketing_consented_at: Optional[datetime] = None
    marketing_consent_basis: Optional[str] = None
    marketing_consent_proof_ref: Optional[str] = None
    consent_disclosure_version: Optional[str] = None
    last_handed_off_at: Optional[datetime] = None
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class SmsContactList(BaseModel):
    total: int
    items: List[SmsContactOut]


# =====================================================================
# Membership
# =====================================================================
class SmsGroupMembershipAdd(BaseModel):
    """Thêm contact vào 1 nhóm (note riêng trong nhóm tùy chọn)."""

    group_id: int = Field(..., ge=1, le=2147483647)
    note: Optional[str] = Field(None, max_length=2000)


# =====================================================================
# Consent event (append-only ledger)
# =====================================================================
class SmsConsentEventCreate(BaseModel):
    """Append 1 sự kiện consent. GRANT cần đủ basis + disclosure_version +
    proof_reference (non-rỗng); REVOKE cần revoke_source. Validate fail-fast
    mirror CHECK ở DB để trả 400 thay vì 500."""

    event_type: ConsentEventType
    occurred_at: datetime
    # GRANT-only
    basis: Optional[ConsentBasis] = None
    disclosure_version: Optional[str] = Field(None, max_length=50)
    proof_reference: Optional[str] = Field(None, max_length=512)
    # REVOKE-only
    revoke_source: Optional[RevokeSource] = None
    metadata_json: Optional[dict] = None

    @field_validator("occurred_at")
    @classmethod
    def _v_occurred_at(cls, v):
        return validate_consent_datetime(v, label="occurred_at")

    @model_validator(mode="after")
    def _check_consent_contract(self) -> "SmsConsentEventCreate":
        if self.event_type == "granted":
            missing = (
                self.basis is None
                or not (self.disclosure_version or "").strip()
                or not (self.proof_reference or "").strip()
            )
            if missing:
                raise ValueError(
                    "GRANT cần basis + disclosure_version + proof_reference "
                    "(không rỗng)"
                )
            if self.revoke_source is not None:
                raise ValueError("GRANT không được mang revoke_source")
        else:  # revoked
            if self.revoke_source is None:
                raise ValueError("REVOKE cần revoke_source")
            if (
                self.basis is not None
                or (self.disclosure_version or "").strip()
                or (self.proof_reference or "").strip()
            ):
                raise ValueError(
                    "REVOKE không được mang grant-data "
                    "(basis/disclosure_version/proof_reference)"
                )
        return self


class SmsConsentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: Optional[int] = None
    phone_normalized_snapshot: str
    event_type: str
    basis: Optional[str] = None
    revoke_source: Optional[str] = None
    disclosure_version: Optional[str] = None
    proof_reference: Optional[str] = None
    occurred_at: datetime
    recorded_by_id: Optional[int] = None
    import_batch_id: Optional[int] = None
    metadata_json: Optional[dict] = None
    created_at: datetime


class SmsConsentEventList(BaseModel):
    total: int
    items: List[SmsConsentEventOut]


# =====================================================================
# Import (upload contacts vào nhóm)
# =====================================================================
class SmsImportRowError(BaseModel):
    """Lỗi 1 dòng import (bỏ qua, không chặn cả lô)."""

    row_number: int = Field(..., description="số dòng trong file (1-based)")
    phone_raw: Optional[str] = None
    reason: str


class SmsImportResult(BaseModel):
    """Kết quả import — counts thỏa bất biến anchor (§4.4)."""

    model_config = ConfigDict(from_attributes=True)

    batch_id: int
    group_id: Optional[int] = None
    file_name: Optional[str] = None
    row_count: int
    valid_count: int
    invalid_count: int
    duplicate_contact_count: int
    existing_member_count: int
    inserted_contact_count: int
    added_member_count: int
    skipped_count: int
    consent_applied: bool = Field(
        ...,
        description="True nếu lô đủ bằng chứng → áp granted cho mọi contact "
        "trong lô (theo occurred_at; revoke mới hơn không bị override)",
    )
    errors: List[SmsImportRowError] = Field(default_factory=list)


# =====================================================================
# Campaign (PR-3 — build BE)
# =====================================================================
SmsLandingType = Literal["qlts_hosted", "external"]
SmsAttestationKind = Literal["consent", "dnc", "optout_channel"]
# Lý do loại recipient (mirror CHECK chk_sms_recipient_excluded_reason)
SmsExcludedReason = Literal[
    "no_consent", "opted_out", "dnc_suppressed", "frequency_capped",
    "over_limit", "missing_data",
]


class SmsCampaignCreate(BaseModel):
    """Tạo campaign. Validate cross-field (biến template, external+{link},
    allowlist host) ở service (cần config + candidate state)."""

    name: str = Field(..., min_length=1, max_length=200)
    code: Optional[str] = Field(
        None, max_length=50, pattern=r"^[a-z0-9][a-z0-9-]*$",
        description="slug duy nhất; bỏ trống để tự sinh từ name",
    )
    sms_template: str = Field(..., min_length=1, max_length=2000)
    landing_type: SmsLandingType = "qlts_hosted"
    landing_url: Optional[str] = Field(None, max_length=2000)
    landing_headline: Optional[str] = Field(None, max_length=200)
    landing_body: Optional[str] = Field(None, max_length=10000)
    landing_cta_label: Optional[str] = Field(None, max_length=100)
    landing_cta_url: Optional[str] = Field(None, max_length=2000)
    frequency_cap_days: Optional[int] = Field(None, ge=0, le=3650)
    link_expires_at: Optional[datetime] = None

    @field_validator("name", "sms_template")
    @classmethod
    def _v_text(cls, v):
        return _strip_required_text(v)

    @field_validator("landing_url", "landing_cta_url")
    @classmethod
    def _v_url(cls, v):
        return _strip_optional_url(v)

    @field_validator("link_expires_at")
    @classmethod
    def _v_expiry(cls, v):
        return validate_future_datetime(v, label="link_expires_at")


class SmsCampaignUpdate(BaseModel):
    """Sửa campaign — chỉ khi status=draft (gate ở service). KHÔNG đổi code."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    sms_template: Optional[str] = Field(None, min_length=1, max_length=2000)
    landing_type: Optional[SmsLandingType] = None
    landing_url: Optional[str] = Field(None, max_length=2000)
    landing_headline: Optional[str] = Field(None, max_length=200)
    landing_body: Optional[str] = Field(None, max_length=10000)
    landing_cta_label: Optional[str] = Field(None, max_length=100)
    landing_cta_url: Optional[str] = Field(None, max_length=2000)
    frequency_cap_days: Optional[int] = Field(None, ge=0, le=3650)
    link_expires_at: Optional[datetime] = None

    @field_validator("name", "sms_template")
    @classmethod
    def _v_text(cls, v):
        return _strip_required_text(v)

    @field_validator("landing_url", "landing_cta_url")
    @classmethod
    def _v_url(cls, v):
        return _strip_optional_url(v)

    @field_validator("link_expires_at")
    @classmethod
    def _v_expiry(cls, v):
        return validate_future_datetime(v, label="link_expires_at")


class SmsCampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    status: str
    sms_template: str
    frequency_cap_days: Optional[int] = None
    landing_type: str
    landing_url: Optional[str] = None
    landing_headline: Optional[str] = None
    landing_body: Optional[str] = None
    landing_cta_label: Optional[str] = None
    landing_cta_url: Optional[str] = None
    build_revision: int
    link_expires_at: Optional[datetime] = None
    optout_instruction_snapshot: Optional[str] = None
    # Attestation (khớp build_revision mới hợp lệ)
    consent_checked_at: Optional[datetime] = None
    consent_checked_by_id: Optional[int] = None
    consent_reference: Optional[str] = None
    consent_checked_build_revision: Optional[int] = None
    dnc_checked_at: Optional[datetime] = None
    dnc_checked_by_id: Optional[int] = None
    dnc_reference: Optional[str] = None
    dnc_checked_build_revision: Optional[int] = None
    optout_channel_checked_at: Optional[datetime] = None
    optout_channel_checked_by_id: Optional[int] = None
    optout_channel_reference: Optional[str] = None
    optout_channel_checked_build_revision: Optional[int] = None
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    handed_off_marked_at: Optional[datetime] = None
    # Computed (service điền)
    has_link: Optional[bool] = None
    group_count: Optional[int] = None
    # Gate TRẠNG THÁI export/re-export (status + đã build). KHÔNG gồm
    # attestation/preflight — FE hiển thị riêng phần "còn thiếu gì".
    # 'handed_off' VẪN true: re-export để retry batch nhà mạng lỗi (§8.4).
    # KHÔNG đặt default: đây là cờ gate, path nào quên `_with_computed` phải
    # vỡ ngay lúc serialize chứ không im lặng phát ra false rồi ẩn mất nút
    # bàn giao — đúng lớp sự cố #6. Cả 6 endpoint trả SmsCampaignOut hiện đều
    # đi qua `_with_computed`.
    can_export: bool


class SmsCampaignList(BaseModel):
    total: int
    items: List[SmsCampaignOut]


class SmsCampaignGroupAttach(BaseModel):
    group_id: int = Field(..., ge=1, le=2147483647)  # int4 — chặn overflow


class SmsOverLimitRow(BaseModel):
    """1 recipient vượt 1 segment (admin cần rút gọn template/dữ liệu)."""

    phone_normalized: str
    full_name: str
    encoding: Optional[str] = None
    length: Optional[int] = None
    segments: Optional[int] = None


class SmsPreflightReport(BaseModel):
    """Báo cáo build/preflight: tổng/exportable/loại theo lý do + phân bố
    nhà mạng + danh sách over_limit + cảnh báo. Dùng cho POST build và
    GET preflight."""

    campaign_id: int
    build_revision: int
    status: str
    has_link: bool
    total: int
    exportable: int
    excluded_by_reason: Dict[str, int]
    carrier_distribution: Dict[str, int]
    over_limit: List[SmsOverLimitRow] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    # ≤5 dòng tin cuối MẪU từ segment thực (sentinel link → URL mẫu) — §D6.
    preview: List[str] = Field(default_factory=list)


class SmsMeasureRequest(BaseModel):
    """Đo thử 1 template soạn dở (chưa gắn recipient) cho form soạn campaign.
    `sample_full_name` tùy chọn — bỏ trống → render dùng NAME_FALLBACK
    (worst-case tiếng Việt → UCS2)."""

    template: str = Field(..., min_length=1, max_length=2000)
    sample_full_name: Optional[str] = Field(None, max_length=255)

    @field_validator("template")
    @classmethod
    def _v_template(cls, v):
        return _strip_required_text(v)


class SmsMeasureResult(BaseModel):
    """Kết quả đo/preview template. Phân 2 tầng cho FE:
    - BLOCKING (sẽ bị `_validate_content` từ chối khi LƯU): `unknown_vars`
      (biến lạ) + `has_internal_sentinel` (template chứa __SMS_LINK__).
    - SOFT (`warnings`) + `optout_configured`: optout chưa cấu hình/placeholder
      />160 (build sẽ chặn), tin vượt 1 segment."""

    encoding: str
    length: int
    segments: int
    is_over_limit: bool
    preview: str
    has_link: bool
    unknown_vars: List[str] = Field(default_factory=list)
    has_internal_sentinel: bool = False
    optout_configured: bool = True
    warnings: List[str] = Field(default_factory=list)


class SmsAttestationCreate(BaseModel):
    """Ghi attestation consent/DNC/opt-out-channel cho build_revision hiện
    tại (gate export PR-4)."""

    kind: SmsAttestationKind
    reference: str = Field(..., min_length=1, max_length=512)

    @field_validator("reference")
    @classmethod
    def _v_reference(cls, v):
        return _strip_required_text(v)


# =====================================================================
# Export batch (PR-4) — 1 file Excel / nhà mạng / build_revision
# =====================================================================
# Mirror CHECK chk_sms_export_batch_status.
SmsExportStatus = Literal[
    "pending", "generated", "handed_off", "failed", "purged", "invalidated"
]


class SmsExportBatchOut(BaseModel):
    """Metadata + vòng đời 1 file export per nhà mạng. KHÔNG lộ
    `storage_path`/`file_sha256` (nội bộ); FE thin-client đọc cờ `can_*`
    thay vì tự suy trạng thái."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    build_revision: int
    group_id: Optional[int] = None
    group_name_snapshot: Optional[str] = None
    carrier_bucket: str
    recipient_count: int
    file_name: Optional[str] = None
    file_size_bytes: Optional[int] = None
    status: str
    failure_reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    generated_at: Optional[datetime] = None
    generated_by_id: Optional[int] = None
    marked_handed_off_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    # Computed (service điền) — thin-client đọc cờ, không suy luận role/status.
    can_download: bool = False
    can_mark_handed_off: bool = False
    is_expired: bool = False


class SmsExportResult(BaseModel):
    """Kết quả POST export: danh sách batch per nhà mạng + tổng quan. File
    sinh ở post-commit (status có thể 'pending'→'generated' khi callback xong)."""

    campaign_id: int
    build_revision: int
    total_exportable: int
    batches: List[SmsExportBatchOut] = Field(default_factory=list)
    message: Optional[str] = None


class SmsExportBatchList(BaseModel):
    """GET danh sách batch của campaign (revision hiện tại) — FE hiển thị lại
    sau reload."""

    campaign_id: int
    build_revision: int
    batches: List[SmsExportBatchOut] = Field(default_factory=list)


# =====================================================================
# Tracking / Landing / Reports / Opt-out (PR-5)
# =====================================================================
SmsGranularity = Literal["day", "month", "year"]
# Nguồn opt-out admin ghi tay (mirror CHECK chk_sms_opt_out_source; landing
# dùng riêng 'landing_optout').
SmsManualOptOutSource = Literal[
    "manual", "sms_reply", "phone_call", "external_suppression"
]


class SmsLandingProgram(BaseModel):
    """1 ngành trong danh mục landing 2 tầng (Phase 2 §16.1). Public — chỉ
    trường hiển thị (id/tên/mã/trình độ), KHÔNG PII."""

    id: int
    name: str
    code: str
    degree_level: str
    # §16.1 — nghề nặng nhọc/độc hại/nguy hiểm (metadata). FE hiển thị badge
    # học phí theo bảng học phí chi tiết, không phụ thuộc cờ này.
    is_heavy: bool = False


class SmsLandingResponse(BaseModel):
    """Nội dung landing `/lp/{code}` — read-only, KHÔNG lộ PII recipient
    (phòng code bị chia sẻ). §19.4. Phase 2: +danh mục ngành (no session)."""

    school_name: str
    headline: Optional[str] = None
    body: Optional[str] = None
    cta_label: Optional[str] = None
    cta_url: Optional[str] = None
    consent_notice: str
    already_opted_out: bool = False
    # Phase 2 (§16.1) — danh mục ngành để render landing 2 tầng; rỗng nếu
    # chưa có ngành active (FE ẩn khối "chọn ngành").
    programs: List[SmsLandingProgram] = Field(default_factory=list)


# =====================================================================
# Phase 2 (§16) — deep engagement tracking (session / view / heartbeat)
# =====================================================================
class SmsSessionStartResponse(BaseModel):
    """Trả sau `POST /landing/{code}/session` — session_token raw TRẢ 1 LẦN
    (server chỉ lưu hash). Client giữ token để gửi program-view/heartbeat."""

    session_token: str
    session_id: int


class SmsProgramViewRequest(BaseModel):
    """Body `POST /landing/{code}/program-view` — mở 1 lượt xem trang ngành."""

    session_token: str = Field(..., min_length=16, max_length=128)
    major_program_id: int = Field(..., ge=1, le=2147483647)
    program_offering_id: Optional[int] = Field(None, ge=1, le=2147483647)


class SmsProgramViewResponse(BaseModel):
    """Trả program_view_id để client đính vào heartbeat của trang ngành đó."""

    program_view_id: int
    sequence_no: int


class SmsHeartbeatRequest(BaseModel):
    """Body `POST /landing/{code}/heartbeat` — báo dwell tích luỹ (giây) trên
    trang ngành đang xem. Server clamp theo wall-clock chống thổi phồng."""

    session_token: str = Field(..., min_length=16, max_length=128)
    program_view_id: int = Field(..., ge=1, le=2147483647)
    # dwell tích luỹ client đo (không delta) — server tự clamp trần theo thời
    # gian thực đã trôi kể từ khi mở view. le lớn = 24h an toàn (server vẫn cap).
    dwell_seconds: int = Field(..., ge=0, le=86400)


class SmsHeartbeatResponse(BaseModel):
    """Xác nhận dwell đã ghi (đã clamp) + tổng active của phiên."""

    ok: bool = True
    dwell_seconds: int = 0
    active_seconds: int = 0


class SmsProgramInterestRow(BaseModel):
    """1 ngành trong report 'ngành nóng' (admin) — aggregate qua program_view."""

    major_program_id: Optional[int] = None
    program_name: str
    distinct_contacts: int = 0
    view_count: int = 0
    total_dwell_seconds: int = 0
    avg_dwell_seconds: float = 0.0


class SmsProgramInterestReport(BaseModel):
    """Report ngành nóng theo campaign/nhóm/thời gian (§16.7). Rank dwell desc."""

    items: List[SmsProgramInterestRow] = Field(default_factory=list)
    distinct_contacts_total: int = 0
    view_count_total: int = 0
    total_dwell_seconds: int = 0


class SmsContactInterestRow(BaseModel):
    """1 ngành trong hồ sơ sở thích 1 contact (rank total_dwell_seconds desc)."""

    major_program_id: int
    program_name: str
    view_count: int = 0
    total_dwell_seconds: int = 0
    interest_score: float = 0.0
    first_interest_at: Optional[datetime] = None
    last_interest_at: Optional[datetime] = None


class SmsContactInterestList(BaseModel):
    """Hồ sơ 'quan tâm ngành' của 1 contact (§16.7 admin / P2-4b lead tab)."""

    contact_id: int
    items: List[SmsContactInterestRow] = Field(default_factory=list)


class SmsProgramContactRow(BaseModel):
    """1 contact quan tâm 1 ngành (drill-down §16.7). PII masked (§16.9).

    `view_count`/`total_dwell_seconds`/`first_viewed_at`/`last_viewed_at` là số
    liệu TRONG scope filter (khớp dòng report đã bấm). `interest_score` là điểm
    GLOBAL rolling (ngoài scope) — chỉ làm bối cảnh 'nóng tổng thể'; NULL (contact
    đã xem nhưng chưa heartbeat) → 0.0."""

    contact_id: int
    full_name: str
    phone_masked: str
    view_count: int = 0
    total_dwell_seconds: int = 0
    interest_score: float = 0.0
    first_viewed_at: Optional[datetime] = None
    last_viewed_at: Optional[datetime] = None


class SmsProgramContactsResponse(BaseModel):
    """Danh sách contact quan tâm 1 ngành (drill-down từ report ngành nóng).
    `total` = distinct contact trong scope (cho phân trang), rank total_dwell desc."""

    major_program_id: int
    total: int = 0
    items: List[SmsProgramContactRow] = Field(default_factory=list)


# --- P2-3 consult officer (§16.7) ---
class SmsConsultLinkResponse(BaseModel):
    """Trả sau `POST /leads/{id}/consult-link` — `code`/`url` raw TRẢ 1 LẦN để
    officer copy gửi Zalo/tay. Server chỉ lưu token_hash."""

    code: str
    url: str
    consult_link_id: int
    contact_id: int


class SmsLeadInterestResponse(BaseModel):
    """Hồ sơ 'quan tâm ngành' của 1 LEAD (match qua phone → contact). Rỗng nếu
    lead chưa có contact / chưa có tương tác landing."""

    lead_id: int
    contact_id: Optional[int] = None
    items: List[SmsContactInterestRow] = Field(default_factory=list)


class SmsPublicOptOutRequest(BaseModel):
    """Body opt-out công khai từ landing — chỉ mang bearer code (§19.3)."""

    code: str = Field(..., min_length=1, max_length=64)


class SmsPublicOptOutResponse(BaseModel):
    """Idempotent: lần 2 vẫn success=True."""

    success: bool = True
    already_opted_out: bool = False


class SmsOptOutManualCreate(BaseModel):
    """Admin ghi opt-out thủ công (đối tác/điện thoại/SMS reply)."""

    phone: str = Field(..., min_length=8, max_length=32)
    source: SmsManualOptOutSource = "manual"
    source_reference: Optional[str] = Field(None, max_length=512)
    reason: Optional[str] = Field(None, max_length=2000)


class SmsOptOutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone_normalized: str
    source: str
    source_reference: Optional[str] = None
    reason: Optional[str] = None
    observed_at: datetime
    created_at: datetime


class SmsOptOutList(BaseModel):
    total: int
    items: List[SmsOptOutOut]


class SmsClickBucket(BaseModel):
    """1 mốc thời gian (day/month/year) — số liệu click."""

    period: str
    total_clicks: int
    human_clicks: int
    distinct_contacts_clicked: int


class SmsClickReport(BaseModel):
    """Report click theo granularity + tổng + CTR (mẫu số = handed_off). §9."""

    granularity: str
    buckets: List[SmsClickBucket] = Field(default_factory=list)
    total_clicks: int = 0
    human_clicks: int = 0
    distinct_contacts_clicked: int = 0
    recipients_handed_off: int = 0
    ctr_percent: float = 0.0


class SmsClickerOut(BaseModel):
    """1 liên hệ đã click (non-bot) cho dashboard — admin xem (PII masked)."""

    recipient_id: int
    contact_id: Optional[int] = None
    full_name: str
    phone_masked: str
    carrier_bucket: str
    human_click_count: int
    first_human_clicked_at: Optional[datetime] = None
    last_human_clicked_at: Optional[datetime] = None


class SmsCampaignDashboard(BaseModel):
    """Dashboard CTR + phân bố nhà mạng + danh sách số đã click của campaign."""

    campaign_id: int
    build_revision: int
    has_link: bool
    recipients_handed_off: int = 0
    total_clicks: int = 0
    human_clicks: int = 0
    distinct_contacts_clicked: int = 0
    ctr_percent: float = 0.0
    carrier_distribution: Dict[str, int] = Field(default_factory=dict)
    clickers: List[SmsClickerOut] = Field(default_factory=list)
