# app/schemas/public_lead_intake.py
"""Schemas cho endpoint công khai nhận lead từ website (WordPress/Formidable).

Form bên website KHÔNG có field email và KHÔNG map ngành sang offering — hệ/ngành/
ghi-chú được gộp thành ghi chú (lưu vào một Consultation hệ thống ở tầng service).

Nguyên tắc "KHÔNG đánh rớt lead": chỉ ``full_name`` + ``phone`` bắt buộc & strict;
các field mô tả phụ thừa độ dài thì TRUNCATE (không 422), email rác thì bỏ về None
(không 422). Xem ``Documents/WEBSITE_LEAD_INTAKE_PLAN.md``.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Giới hạn độ dài từng field (truncate, không reject) — khớp cột DB tương ứng.
_FIELD_CAPS = {
    "full_name": 255,
    "education_level_raw": 100,
    "address": 255,
    "he": 255,
    "nganh_xet": 255,
    "nganh_dang_ky": 255,
    "extra_note": 2000,
    "email": 255,
    "hp": 255,
}


class PublicLeadIntake(BaseModel):
    """Payload website gửi vào ``POST /api/public/leads/intake``.

    Chỉ ``full_name`` + ``phone`` bắt buộc. ``hp`` là honeypot (Formidable đã lọc
    bot; ta double-check) — có giá trị ⇒ coi là bot, KHÔNG tạo lead.
    """

    full_name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=1, max_length=20)
    # Email CHỈ để hiển thị trong note (service KHÔNG ghi vào Lead.email) → khoan
    # dung tuyệt đối: rác/sai/non-str → None, không bao giờ 422 đánh rớt lead.
    email: Optional[str] = None
    # Nhãn trình độ thô từ web (vd "Cao đẳng", "THPT") — service chuẩn hoá sang enum.
    education_level_raw: Optional[str] = None
    # Địa chỉ liên hệ — map sang Lead.location.
    address: Optional[str] = None
    # Hệ + ngành + ghi chú — gộp vào note Consultation hệ thống.
    he: Optional[str] = None
    nganh_xet: Optional[str] = None
    nganh_dang_ky: Optional[str] = None
    extra_note: Optional[str] = None
    # Honeypot — phải để trống. Bot điền tự động → reject ở service.
    hp: Optional[str] = None

    @field_validator(
        "full_name",
        "email",
        "education_level_raw",
        "address",
        "he",
        "nganh_xet",
        "nganh_dang_ky",
        "extra_note",
        "hp",
        mode="before",
    )
    @classmethod
    def _strip_and_cap(cls, v, info):
        """Trim khoảng trắng (Field strip_whitespace là no-op ở Pydantic v2);
        non-str → None; rỗng → None; thừa độ dài → TRUNCATE (không 422 rớt lead).

        Áp cả ``hp`` (khoảng-trắng autofill → None, không bị coi là bot) và
        ``email`` (rác → None, chỉ vào note)."""
        if v is None or not isinstance(v, str):
            return None
        v = v.strip()
        if not v:
            return None
        return v[: _FIELD_CAPS.get(info.field_name, 2000)]

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_and_validate_phone(cls, v):
        """Chuẩn hoá + validate SĐT Việt Nam (reuse ``phone_helpers``).

        SĐT là khóa upsert nên BẮT BUỘC hợp lệ → sai định dạng vẫn 422 (đúng).
        """
        from app.utils.phone_helpers import (
            normalize_vietnam_phone,
            validate_vietnam_phone,
        )

        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("Số điện thoại không được để trống")
        normalized = normalize_vietnam_phone(v)
        if not normalized or not validate_vietnam_phone(normalized, normalize=False):
            raise ValueError("Số điện thoại không hợp lệ (định dạng Việt Nam)")
        return normalized


class PublicLeadIntakeResult(BaseModel):
    """Kết quả NỘI BỘ của service (log/test) — KHÔNG trả thẳng ra caller.

    - ``created``: tạo lead mới.
    - ``updated``: cập nhật lead đang hoạt động (trùng SĐT).
    - ``noted``: lead đã ngừng tư vấn / đã có hồ sơ → chỉ ghi nhận, không reopen.
    """

    status: Literal["created", "updated", "noted"]
    lead_id: int


class PublicLeadIntakeAck(BaseModel):
    """Phản hồi CÔNG KHAI cho caller — GENERIC, không lộ created/updated/noted hay
    lead_id thật (chống enumeration ứng viên theo SĐT từ endpoint công khai)."""

    status: Literal["received"] = "received"
