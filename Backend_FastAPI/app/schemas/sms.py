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

    group_id: int = Field(..., ge=1)
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


class SmsAttestationCreate(BaseModel):
    """Ghi attestation consent/DNC/opt-out-channel cho build_revision hiện
    tại (gate export PR-4)."""

    kind: SmsAttestationKind
    reference: str = Field(..., min_length=1, max_length=512)

    @field_validator("reference")
    @classmethod
    def _v_reference(cls, v):
        return _strip_required_text(v)
