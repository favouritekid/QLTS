# app/models/sms/prefix_carrier_rule.py
"""
SMS prefix → carrier rule (config, seed idempotent).
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.5 / §5.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsPrefixCarrierRule(Base):
    """
    Bảng này CHỈ để khớp **định dạng file upload** của nhà mạng. Do MNP
    (chuyển mạng giữ số), đầu số chỉ phản ánh **mạng gốc**, KHÔNG phải
    mạng hiện tại. Không dùng để định tuyến chính xác. Số không khớp →
    bucket `unknown` kiểm tra thủ công. Rủi ro này được chấp nhận theo
    Quyết định #7 (SMS_MARKETING_MODULE_DESIGN.md §2.1).
    """

    __tablename__ = "sms_prefix_carrier_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prefix: Mapped[str] = mapped_column(
        String(4), nullable=False, unique=True,
        comment="3 ký tự đầu gồm số 0, vd '032','086'",
    )
    carrier_code: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="viettel/vinaphone/mobifone/vietnamobile/gmobile",
    )
    carrier_name: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SmsPrefixCarrierRule {self.prefix}→{self.carrier_code}>"
