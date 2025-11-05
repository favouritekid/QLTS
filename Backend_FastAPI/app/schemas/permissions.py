# app/schemas/permissions.py
from pydantic import BaseModel, Field


class Policy(BaseModel):
    """Schema để đọc một policy."""

    subject: str
    object: str
    action: str


class PolicyCreate(BaseModel):
    """Schema để tạo một policy mới."""

    subject: str = Field(..., description="Chủ thể, vd: 'role:manager' hoặc 'user:123'")
    object: str = Field(
        ..., description="Đối tượng, vd: '/api/leads/*' hoặc '/api/admin/users'"
    )
    action: str = Field(..., description="Hành động, vd: 'GET', 'POST', '*'")


class RoleAssignment(BaseModel):
    """Schema để gán vai trò cho người dùng."""

    user_id: int = Field(..., gt=0)
    role: str = Field(..., description="Vai trò (đã có tiền tố), vd: 'role:officer'")
