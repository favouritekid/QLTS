# -*- coding: utf-8 -*-
"""Schema của màn đồng bộ ký túc xá.

🔴 Nguyên tắc xuyên suốt file này: **client không được đặt thứ gì quyết định
phạm vi của một lần ghi**. Lượt đồng bộ hạ được cờ đủ-điều-kiện của cả một khoá
học, nên mọi tham số ảnh hưởng tới "ghi cái gì, cho năm nào" phải do **server**
chốt lúc xem trước và ký trong ``preview_token`` — không phải do request apply
mang lên.

Đó là lý do :class:`DormSyncApplyRequest` chỉ có ĐÚNG một trường và khai
``extra="forbid"``: một request gửi kèm ``academic_year`` phải bị từ chối 422
chứ không được im lặng bỏ qua. Bỏ qua trong im lặng là để client tin rằng mình
đã chọn được năm học — rồi ghi vào một năm khác.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DormSyncApplyRequest(BaseModel):
    """Thân request của ``POST /apply``. ĐÚNG một trường.

    🔴 ``extra="forbid"``: Pydantic mặc định **bỏ qua** trường lạ. Với endpoint
    này thì bỏ qua là kiểu hỏng tệ nhất — một client (hoặc một bản frontend cũ)
    gửi kèm ``academic_year=2025`` sẽ nhận 200 và tin rằng lượt vừa chạy là cho
    năm 2025, trong khi server ghi vào năm đã ký trong token. Không có gì trên
    màn hình nói ra sự chênh lệch đó.

    ``operation_id`` cũng KHÔNG nằm ở đây: nó do server sinh lúc xem trước và ký
    trong token: nhận nó từ client là mở lại đúng cửa chống-replay mà sổ cái
    ``dorm_sync_operations`` sinh ra để đóng.
    """

    model_config = ConfigDict(extra="forbid")

    preview_token: str = Field(
        ...,
        min_length=1,
        description=(
            "Token server ký ở bước xem trước. Mang theo năm học, operation_id "
            "và dấu vân tay trạng thái mà người bấm đã nhìn."
        ),
    )


class DormSyncPreviewRequest(BaseModel):
    """Thân request của bước xem trước.

    Đây là nơi DUY NHẤT client được chọn năm học — và nó là một lượt **chỉ
    đọc**. Từ đó trở đi năm học đã nằm trong token do server ký.
    """

    model_config = ConfigDict(extra="forbid")

    academic_year: int = Field(
        ...,
        ge=2000,
        le=2100,
        description="Năm học muốn xem trước. Phải là một năm ĐANG MỞ ở hệ KTX.",
    )


class DormSyncContextResponse(BaseModel):
    """Bối cảnh để dựng màn hình: chọn năm nào, mặc định là năm nào.

    ⚠️ ``default_academic_year`` có thể là ``None``. Frontend PHẢI xử lý ca đó
    thay vì tự điền năm hiện tại — "hệ KTX chưa mở năm nào" là một trạng thái
    thật, và đoán một năm ở đây nghĩa là dựng sẵn một lượt ghi vào năm không tồn
    tại bên đích.
    """

    model_config = ConfigDict(extra="forbid")

    open_academic_years: List[int] = Field(
        default_factory=list,
        description="Các năm học đang MỞ ở hệ KTX, sắp giảm dần.",
    )
    default_academic_year: Optional[int] = Field(
        None,
        description=(
            "Năm mở lớn nhất, hoặc ``None`` nếu không có năm nào mở. "
            "KHÔNG bao giờ suy ra từ ngày hệ thống."
        ),
    )


class DormSyncWarningRow(BaseModel):
    """Một người SẮP MẤT CỜ mà vẫn đang giữ giường.

    🔴 Đây là dòng người bấm phải đọc trước khi quyết định. Nó có họ tên và số
    phòng — dữ liệu cá nhân — nên nó đi trong THÂN PHẢN HỒI (sau cổng quyền
    admin), KHÔNG đi trong ``preview_token``: token chỉ được HMAC ký, không
    được mã hoá, và ai cầm chuỗi cũng đọc được.
    """

    model_config = ConfigDict(extra="forbid")

    qlts_profile_id: int
    full_name: str
    building_name: str
    room_code: str
    bed_no: int
    status: str


class DormSyncPreviewResponse(BaseModel):
    """Kết quả bước xem trước. CHỈ ĐỌC — chưa ghi gì sang hệ KTX."""

    model_config = ConfigDict(extra="forbid")

    academic_year: int
    source_count: int = Field(..., description="Số hồ sơ đủ điều kiện ở nguồn QLTS.")

    can_apply: bool = Field(
        ...,
        description=(
            "Có được bấm Ghi hay không. False ⇒ `preview_token` là None và nút "
            "phải bị khoá."
        ),
    )
    blocked_reason: Optional[str] = Field(
        None,
        description="Vì sao chưa ghi được. Chỉ có nghĩa khi `can_apply=False`.",
    )

    warnings: List[DormSyncWarningRow] = Field(
        default_factory=list,
        description="Sắp mất cờ mà vẫn đang giữ giường — người bấm phải đọc.",
    )

    source_hash: Optional[str] = Field(
        None, description="SHA-256 của ảnh chụp nguồn mà người bấm đã xem."
    )
    target_fingerprint: Optional[str] = Field(
        None, description="Dấu vân tay trạng thái chỗ ở phía KTX, do database tính."
    )

    preview_token: Optional[str] = Field(
        None,
        description=(
            "Vé để bấm Ghi. `None` khi chưa ghi được. Mang theo năm học, "
            "operation_id và hai dấu ở trên — KHÔNG mang dữ liệu cá nhân."
        ),
    )
    expires_at: Optional[int] = Field(
        None, description="Thời điểm token hết hạn (epoch giây)."
    )
