# app/schemas/review_secretary.py
"""Schema GĐ2-C C1 — quyền "Thư ký Hội đồng" (Admin gán / thu hồi / liệt kê). Tên trường tiếng Anh (quy ước owner 17-11).

Thân request ``extra = "forbid"`` (khoá lạ ⇒ 422). Không có trường hạn: owner C1 22-11 "không hết hạn". Không có trường đơn vị:
owner C2 22-11 "toàn trường". Phản hồi chỉ mang tóm tắt CÁN BỘ được gán (id, tên đăng nhập, họ tên, vai, trạng thái) — không
dữ liệu học sinh.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

INT4_MAX = 2**31 - 1
#: Trần độ dài lý do — cùng trần của quyền duyệt chéo GĐ1b (``CrossReviewGrantCreate.reason``).
REASON_MAX_LENGTH = 500


class ReviewSecretaryGrantCreate(BaseModel):
    user_id: int = Field(..., ge=1, le=INT4_MAX)
    reason: str = Field(..., min_length=1, max_length=REASON_MAX_LENGTH)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewSecretaryGrantRevoke(BaseModel):
    reason: str = Field(..., min_length=1, max_length=REASON_MAX_LENGTH)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewSecretaryUserSummary(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    role: str
    status: str


class ReviewSecretaryGrantView(BaseModel):
    id: int
    user_id: int
    user: Optional[ReviewSecretaryUserSummary] = None
    granted_by_user_id: int
    granted_at: datetime
    reason: str
    revoked_at: Optional[datetime] = None
    revoked_by_user_id: Optional[int] = None
    revoke_reason: Optional[str] = None
    #: ``revoked_at IS NULL`` — quyền không có hạn nên chỉ thu hồi mới làm hết hiệu lực.
    is_active: bool
