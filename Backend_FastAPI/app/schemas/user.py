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
    skills: Optional[List[str]] = None
    unit_id: Optional[int] = None  # Organizational unit assignment


class UsersPage(BaseModel):
    total_count: int
    users: List["User"]


class User(UserBase):
    id: int
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None
    unit_id: Optional[int] = None
    skills: Optional[List[str]] = None
    availability_status: Optional[str] = None
    password_reset_required: Optional[bool] = False  # Security: True when user needs to change password
    mfa_enabled: bool = False  # MFA: Whether TOTP MFA is enabled

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
    code: str = Field(..., min_length=6, max_length=8)  # 6-digit TOTP or 8-char backup


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
