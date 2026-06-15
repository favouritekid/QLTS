# app/schemas/sms.py
"""
Pydantic v2 schemas cho SMS Marketing — PR-2 (Contact Management BE).

Bao gồm: contact group CRUD, contact CRUD, membership, consent-event
ledger (append-only), kết quả import. Các enum literal mirror đúng CHECK
constraint ở model (app/models/sms/) để validate fail-fast (400) trước khi
chạm DB. Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4 + §10.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

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
