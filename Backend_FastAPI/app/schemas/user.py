# NOTE: Các schema này được sử dụng cho các endpoint của /auth
# app/schemas/user.py
# NOTE: Các schema này được sử dụng cho các endpoint của /auth
import re
from typing import List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    constr,
    field_validator,
    model_validator,
)


# === TÁCH LOGIC RA HÀM RIÊNG ĐỂ TÁI SỬ DỤNG ===
def validate_password_strength_logic(v: str) -> str:
    """Hàm helper chứa logic kiểm tra độ mạnh mật khẩu."""
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[@$!%*?&]", v):
        raise ValueError("Password must contain at least one special character")
    return v


# === KẾT THÚC TÁCH LOGIC ===

# ✅ SECURITY: OWASP ASVS 5.0 recommends minimum 12 characters
PasswordStr = constr(min_length=12, strip_whitespace=True)


class UserBase(BaseModel):
    # ✅ SECURITY FIX (Deep Dive Audit): Strict regex validation to prevent injection attacks
    # Only allow: letters, numbers, hyphens, underscores
    # Pattern prevents: path traversal (../, ..\), special chars (@, =, +, etc.)
    username: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        strip_whitespace=True,
        description="Username must contain only letters, numbers, hyphens, and underscores"
    )
    email: EmailStr  # EmailStr tự động chuẩn hóa
    full_name: Optional[str] = Field(None, strip_whitespace=True)
    role: str
    status: str


class UserCreate(BaseModel):
    """
    Schema cho user registration.
    """

    # ✅ SECURITY FIX (Deep Dive Audit): Strict regex validation
    username: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        strip_whitespace=True,
        description="Username must contain only letters, numbers, hyphens, and underscores"
    )
    email: EmailStr
    password: PasswordStr
    full_name: Optional[str] = Field(None, max_length=120, strip_whitespace=True)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return validate_password_strength_logic(v)


class ResetPasswordSchema(BaseModel):
    """
    Schema cho reset password endpoint.
    backend chỉ cần nhận token và new_password.
    """

    token: str
    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class ChangePasswordSchema(BaseModel):
    """
    Schema cho change password endpoint.
    backend chỉ cần nhận old_password và new_password.
    """

    old_password: str
    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class AdminSetPasswordSchema(BaseModel):
    """
    Schema cho admin set password endpoint.
    backend chỉ cần nhận new_password.
    """

    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class BulkActionSchema(BaseModel):
    """Schema để validate hành động hàng loạt."""

    action: Literal["delete", "change_status"]
    user_ids: List[int]
    status: Optional[Literal["active", "pending", "banned"]] = None

    @model_validator(mode="after")
    def check_status_for_change_status_action(self) -> "BulkActionSchema":
        if self.action == "change_status" and self.status is None:
            raise ValueError("Status is required for 'change_status' action.")
        return self


# --- Các schema còn lại không đổi ---


class AdminUserCreate(UserCreate):
    role: Literal["admin", "manager", "accountant", "officer", "user"] = "user"
    status: Literal["active", "pending", "banned"] = "active"


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=120, strip_whitespace=True)
    phone_number: Optional[str] = Field(None, max_length=20, strip_whitespace=True)
    role: Optional[str] = None
    status: Optional[str] = None
    max_capacity: Optional[int] = None
    # Officer member-weighted assignment (1-100). Defense-in-depth: the router
    # already validates via Form(ge=1, le=100), but pinning it here guards the
    # UserUpdate(**update_dict) build so an out-of-range value can never reach
    # setattr on the model.
    assignment_weight: Optional[int] = Field(None, ge=1, le=100)
    skills: Optional[List[str]] = None
    unit_id: Optional[int] = None  # Organizational unit assignment

    # W8-A.3.2 defense-in-depth 2026-05-16: HTML-escape user-supplied
    # text fields. Frontend already escapes via React JSX, but server-
    # side belt+suspenders prevents stored XSS if any downstream
    # consumer (export CSV, PDF, email template, dangerouslySetInnerHTML
    # leak) bypasses React escaping. Mirror pattern from admission
    # schema (admission.py:70).
    @field_validator("full_name", mode="before")
    @classmethod
    def _escape_full_name(cls, v):
        if v is None or not isinstance(v, str):
            return v
        import html
        return html.escape(v.strip())


class UsersPage(BaseModel):
    total_count: int
    users: List["UserAdminResponse"]


class UserPickerSchema(BaseModel):
    """Lightweight user shape cho non-privileged role queries (E2E F3 fix
    2026-05-16). Officer + accountant + collaborator cần list user cho
    UI picker (assign officer / select reviewer) nhưng KHÔNG cần PII của
    user khác (email, phone, mfa_enabled, password_reset_required).

    Whitelist-only — fields not listed are dropped during serialization.
    Mirrors UserAdminResponse cấu trúc nhưng strip:
        - email (PII)
        - phone_number (PII)
        - mfa_enabled (security info — useful for targeted attacks)
        - password_reset_required (info disclosure)
        - max_capacity (admin-internal lead-routing detail)

    Use case: dropdown picker, list display "ai phụ trách hồ sơ này",
    avatar circle với name. Manager+admin vẫn dùng full UserAdminResponse.
    """
    id: int
    username: str
    full_name: Optional[str] = None
    role: str
    status: str
    unit_id: Optional[int] = None
    avatar_url: Optional[str] = None
    skills: Optional[List[str]] = None
    availability_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UsersPagePicker(BaseModel):
    """Paginated container cho UserPickerSchema list. Mirrors UsersPage
    shape — chỉ thay users element type."""
    total_count: int
    users: List[UserPickerSchema]


class User(UserBase):
    id: int
    email: str  # Override EmailStr: response serialization must not reject DB values (e.g. placeholder emails)
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None
    unit_id: Optional[int] = None
    skills: Optional[List[str]] = None
    availability_status: Optional[str] = None
    password_reset_required: Optional[bool] = False  # Security: True when user needs to change password
    mfa_enabled: bool = False  # MFA: Whether TOTP MFA is enabled

    model_config = ConfigDict(from_attributes=True)


class UserAdminResponse(UserBase):
    """Response schema for every ``/api/admin/users`` surface.

    Whitelist-only: fields not listed here are stripped during
    serialization. The four admin endpoints used to return the raw
    SQLAlchemy ``models.User`` without a ``response_model``, leaking
    every column — including ``password_hash``, ``totp_secret_encrypted``,
    ``backup_codes_hashed``, ``active_jti``, and the ``search_vector``
    tsvector. Pinning a Pydantic schema with
    ``ConfigDict(from_attributes=True)`` makes the leak structurally
    impossible: any new sensitive column added to the model stays
    invisible to the API unless someone explicitly extends this list.

    Used by all four admin user surfaces — paginated list
    (``UsersPage.users``), unpaginated list (``GET /users/list``),
    detail (``GET /users/{id}``), and mutation responses (``POST``,
    ``PUT``) — so the FE can rely on a single shape across them.
    ``max_capacity`` matters for cache reconciliation in
    ``useAdminUpdateUser``; without it the optimistic update would
    drop the field.

    Distinct from ``User`` because admin contexts surface
    ``max_capacity`` (lead-assignment capacity), which is not
    appropriate to leak from ``/me``, ``/profile``, ``/auth/register``,
    or ``/auth/reset-password``.
    """
    id: int
    email: str  # Override EmailStr to tolerate placeholder/legacy DB values
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None
    unit_id: Optional[int] = None
    skills: Optional[List[str]] = None
    availability_status: Optional[str] = None
    max_capacity: Optional[int] = None
    # Admin-internal lead-routing weight — surfaced alongside max_capacity so the
    # admin UI can display/edit it. Deliberately NOT on UserPickerSchema (officer/
    # accountant picker) — same treatment as max_capacity.
    assignment_weight: Optional[int] = None
    password_reset_required: Optional[bool] = False
    mfa_enabled: bool = False

    model_config = ConfigDict(from_attributes=True)


class UserInDB(UserBase):
    """
    🚨 DEPRECATED: DO NOT USE THIS SCHEMA IN API RESPONSES! 🚨

    This schema contains sensitive field (password_hash) and should ONLY be used
    for internal database operations, NEVER as a response_model.

    For API responses, use the `User` schema instead.

    Security Note: password_hash field exists but is hidden from serialization
    to prevent accidental exposure.
    """
    id: int
    # 🔒 SECURITY FIX: Exclude password_hash from JSON serialization
    # This prevents exposure even if someone accidentally uses this as response_model
    password_hash: str = Field(exclude=True)

    model_config = ConfigDict(from_attributes=True)

    def dict(self, **kwargs):
        """
        Override dict() to ensure password_hash is always excluded.

        This handles backward compatibility with code using deprecated .dict() method
        instead of .model_dump().

        Delegates to model_dump() which properly respects Field(exclude=True).
        """
        # Use model_dump() which respects Field(exclude=True)
        # This ensures password_hash is excluded regardless of serialization method used
        return self.model_dump(**kwargs)

    def __iter__(self):
        """
        Override iteration to exclude password_hash.

        This ensures that dict(instance) also excludes password_hash,
        not just instance.dict() or instance.model_dump().
        """
        # Iterate over model_dump() output which excludes password_hash
        return iter(self.model_dump().items())


class LoginSchema(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class LoginNotificationData(BaseModel):
    """
    R1+R2: Suspicious login notification data included in login response.
    
    This eliminates the need for socket-based notification delivery,
    providing immediate feedback to the user upon login.
    """
    type: str = "SUSPICIOUS_LOGIN"
    login_id: int
    ip_address: str
    location: Optional[str] = None
    device: Optional[str] = None
    browser: Optional[str] = None
    os: Optional[str] = None
    risk_score: float = 0.0
    anomalies: List[str] = []


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class RefreshTokenRequest(BaseModel):
    """Schema cho request body của endpoint /refresh."""

    refresh_token: str


class SyncUsersRequest(BaseModel):
    """Schema cho request body của POST /admin/sync/users endpoint."""

    user_ids: Optional[List[int]] = None  # None hoặc empty list = sync all users


# =============================================================================
# MFA (Multi-Factor Authentication) Schemas
# =============================================================================


class MfaVerifySchema(BaseModel):
    """Schema for verifying MFA code during login."""
    mfa_token: str
    code: str = Field(..., min_length=6, max_length=10)  # 6-digit TOTP or 10-char backup


class MfaSetupResponse(BaseModel):
    """Response from /mfa/setup with QR code and secret."""
    secret: str          # Base32 secret for manual entry
    qr_code: str         # Base64 data URI of QR code
    provisioning_uri: str


class MfaEnableRequest(BaseModel):
    """Request to enable MFA (must provide valid TOTP code)."""
    code: str = Field(..., min_length=6, max_length=6)  # Must use TOTP to enable


class MfaDisableRequest(BaseModel):
    """Request to disable MFA (requires password verification)."""
    password: str


class MfaStatusResponse(BaseModel):
    """Response from /mfa/status."""
    mfa_enabled: bool
    has_backup_codes: bool


class MfaBackupCodesResponse(BaseModel):
    """Response containing backup codes (shown ONCE only)."""
    backup_codes: List[str]


class MfaBackupCodesRequest(BaseModel):
    """Request to regenerate backup codes (requires password)."""
    password: str
