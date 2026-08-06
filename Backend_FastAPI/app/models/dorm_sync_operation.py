# app/models/dorm_sync_operation.py
"""Sổ cái idempotency cho lượt đồng bộ ký túc xá, phía QLTS.

🔴 Vì sao cần bảng này thay vì dựa vào ``sync_runs.note`` bên KTX:

* ``find_run_by_token`` bên CLI **lọc ``status='running'``**, kèm chính comment
  của nó rằng ``note`` KHÔNG unique. Một lượt đã ``completed`` sẽ không tìm
  thấy, nên retry HTTP mở lượt thứ hai và tiền sử được ghi hai lần.
* ``sync_runs.note`` là ``text`` thường, không ràng buộc gì.
* Index ``uq_sync_run_active_per_year`` bên KTX chỉ chống "một lượt *running*
  mỗi năm" — nó không chặn replay **sau khi** lượt đã hoàn tất.

``sync_runs.note`` vẫn mang ``operation_id`` nhưng **chỉ để đối soát hai hệ**,
tuyệt đối không dùng làm cơ chế bảo đảm duy nhất.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 🔴 BỐN trạng thái, và cả bốn phải có mặt ở MỌI nơi khai báo: hằng số này,
# CHECK constraint dưới đây, và migration Alembic.
#
# ``outcome_unknown`` là trạng thái **non-terminal**: nó nghĩa là lượt bên KTX
# đã chạy nhưng ta không xác định được nó kết thúc ra sao. Gộp nó vào ``failed``
# sẽ mời người vận hành chạy lại một lượt có thể đã ghi xong — đúng loại thao
# tác không có đường lùi.
TRANG_THAI_RUNNING = "running"
TRANG_THAI_COMPLETED = "completed"
TRANG_THAI_FAILED = "failed"
TRANG_THAI_OUTCOME_UNKNOWN = "outcome_unknown"

CAC_TRANG_THAI = (
    TRANG_THAI_RUNNING,
    TRANG_THAI_COMPLETED,
    TRANG_THAI_FAILED,
    TRANG_THAI_OUTCOME_UNKNOWN,
)


class DormSyncOperation(Base):
    """Một lượt bấm "Đồng bộ" — ghi TRƯỚC khi chạm KTX, cập nhật SAU khi xong."""

    __tablename__ = "dorm_sync_operations"

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'outcome_unknown')",
            name="ck_dorm_sync_operations_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 🔴 UNIQUE là hàng rào chống replay. Nó do **server** sinh lúc preview và
    # được **ký trong preview token**, nên client không tự đặt được giá trị
    # khác để đi vòng qua idempotency.
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
        comment="Do server sinh lúc preview và ký trong token; client không đặt được.",
    )

    actor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Ai bấm. RESTRICT vì đây là sổ đối soát — xoá người là mất dấu vết.",
    )
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    snapshot_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Băm của snapshot nguồn + đích mà người bấm đã xem.",
    )
    snapshot_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sa.text("1"),
        comment="Đổi cấu trúc snapshot thì tăng số này; token phiên bản cũ bị từ chối.",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=sa.text("'running'"),
        index=True,
    )

    ktx_run_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="sync_runs.id bên KTX — cột đối soát duy nhất giữa hai hệ.",
    )
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Số liệu lượt chạy, để retry đọc lại mà không gọi sang KTX.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        onupdate=sa.text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<DormSyncOperation op={self.operation_id} year={self.academic_year} "
            f"status={self.status} ktx_run={self.ktx_run_id}>"
        )
