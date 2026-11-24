# app/schemas/admission_review_selection.py
"""Schema GĐ2-C C2 — lựa chọn của Ban thư ký (``PUT / GET /review-sessions/{session_id}/selections…``). Tên trường tiếng Anh
(quy ước owner 17-11).

Thân request ``extra = "forbid"`` (khoá lạ ⇒ 422). ``supersedes_id`` BẮT BUỘC có mặt (``null`` = hồ sơ chưa có lựa chọn) — người
bấm khai lựa chọn hiệu lực mình đã thấy (409 ``SELECTION_CHANGED`` nếu đã đổi). ``note`` = lý do: chuỗi trắng coi như không có
(dịch vụ chuẩn hoá) — để lỗi "thiếu lý do" luôn là 400 ``selection_reason_required`` của dịch vụ, không chia đôi 400 / 422.
Phản hồi: chỉ id, mã, mã băm, lý do, tên CÁN BỘ ghi — không họ tên / CCCD học sinh.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

INT4_MAX = 2**31 - 1
#: Trần độ dài lý do — cùng trần lý do của quyền Thư ký (C1) / quyền duyệt chéo GĐ1b.
NOTE_MAX_LENGTH = 500

SelectionKind = Literal[
    "admit_over_major_quota",
    "consider_next_choice",
    "defer_supplement",
    "admit_without_ethnic_bonus",
    "exclude_this_session",
    "keep_despite_inactive",
]


class SelectionPut(BaseModel):
    kind: SelectionKind
    based_on_row_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    supersedes_id: Optional[int] = Field(..., ge=1, le=INT4_MAX)
    note: Optional[str] = Field(None, max_length=NOTE_MAX_LENGTH)

    model_config = ConfigDict(extra="forbid")


class SelectionView(BaseModel):
    id: int
    session_id: int
    profile_id: int
    kind: str
    choice_id: Optional[int] = None
    based_on_run_id: int
    based_on_row_hash: str
    decided_by_user_id: int
    decided_by_username: Optional[str] = None
    decided_by_full_name: Optional[str] = None
    decided_at: datetime
    note: Optional[str] = None
    supersedes_id: Optional[int] = None
    #: Dòng hiện tại (lượt ``evaluate`` xong mới nhất) không còn hồ sơ này, hoặc mã băm đã lệch ⇒ lựa chọn đã CŨ.
    is_stale: bool


class SelectionListOut(BaseModel):
    session_id: int
    latest_run_id: Optional[int] = None
    items: List[SelectionView]


class SelectionHistoryOut(BaseModel):
    session_id: int
    profile_id: int
    effective_selection_id: Optional[int] = None
    items: List[SelectionView]
