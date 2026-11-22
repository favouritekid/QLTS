# app/models/thcs_school_name_mapping.py
"""Bảng ghép tên trường THCS gõ tay → trường trong danh mục (đề xuất danh mục THCS Phần B1, owner 22-11).

Một dòng = "mọi dòng lịch sử học THCS gõ tay có tên chuẩn hoá ``normalized_name`` là trường ``school_id``". Khoá
chuẩn hoá: ``app/services/thcs_school_name.normalize_thcs_school_name`` (MỘT nguồn). Duy nhất theo tên chuẩn hoá —
một tên chỉ ghép được MỘT trường; hai trường trùng tên ở hai xã thì Admin để nhóm "chưa xác định" (sửa tay từng hồ sơ).

Bảng này KHÔNG tự sửa hồ sơ: gắn ``school_id`` vào lịch sử học là lượt "áp ghép" riêng
(``ThcsSchoolMappingService.apply_mappings``), chạy thử mặc định, chế độ thật khoá bằng cờ CHO PHÉP.

Migration ``thcsmap20261122`` chép NGUYÊN câu ``CREATE TABLE`` / ``CREATE INDEX`` của model này (test khoá hai bên).
"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ThcsSchoolNameMapping(Base):
    __tablename__ = "thcs_school_name_mapping"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_thcs_school_name_mapping_normalized_name"),
        CheckConstraint(
            "length(btrim(normalized_name)) > 0",
            name="ck_thcs_school_name_mapping_normalized_name_nonempty",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Tên trường THCS đã chuẩn hoá (``normalize_thcs_school_name``) — khoá ghép.
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    school_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("vn_school.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mapped_by_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mapped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<ThcsSchoolNameMapping id={self.id} name={self.normalized_name!r} "
            f"school_id={self.school_id}>"
        )
