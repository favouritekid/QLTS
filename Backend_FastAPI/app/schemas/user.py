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

PasswordStr = constr(min_length=8, strip_whitespace=True)


class UserBase(BaseModel):
    # ✅ SỬA: Thêm validation
    username: str = Field(..., min_length=1, strip_whitespace=True)
    email: EmailStr  # EmailStr tự động chuẩn hóa
    full_name: Optional[str] = Field(None, strip_whitespace=True)
    role: str
    status: str


class UserCreate(BaseModel):
    """
    Schema cho user registration.
    """

    # ✅ SỬA: Thêm validation
    username: str = Field(..., min_length=3, max_length=64, strip_whitespace=True)
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
    role: str = "user"
    status: str = "active"


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

    model_config = ConfigDict(from_attributes=True)


class UserInDB(UserBase):
    id: int
    password_hash: str

    model_config = ConfigDict(from_attributes=True)


class LoginSchema(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class RefreshTokenRequest(BaseModel):
    """Schema cho request body của endpoint /refresh."""

    refresh_token: str


class SyncUsersRequest(BaseModel):
    """Schema cho request body của POST /admin/sync/users endpoint."""

    user_ids: Optional[List[int]] = None  # None hoặc empty list = sync all users
