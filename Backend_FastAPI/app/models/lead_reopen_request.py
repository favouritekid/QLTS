# app/models/lead_reopen_request.py
"""Lead reopen request (Phase B) — officer xin mở lại lead "Đã ngừng tư vấn".

Phase A: chỉ manager/admin tự mở lại (sts20→sts04). Phase B: officer assigned GỬI yêu
cầu → manager/admin DUYỆT (approve gọi lõi ``lead_reopen_service.reopen_lead``) hoặc TỪ
CHỐI (lead giữ sts20). Xem Documents/LEAD_REOPEN_WORKFLOW_PLAN.md §7.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship

from .base import Base


class LeadReopenRequest(Base):
    """Yêu cầu mở lại lead consultation-terminal (officer xin → manager/admin duyệt)."""

    __tablename__ = "lead_reopen_request"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_lead_reopen_request_status",
        ),
        # Chặn 2 pending cùng 1 lead (race-safe, chống spam). Partial unique.
        Index(
            "uq_reopen_one_pending_per_lead",
            "lead_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        # Index list duyệt theo unit + status.
        Index("ix_lead_reopen_request_unit_status", "unit_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)
    requested_by_id = Column(
        Integer,
        ForeignKey("user.id"),
        nullable=False,
        index=True,
        comment="Officer xin mở lại",
    )
    reason = Column(Text, nullable=False)
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | approved | rejected | cancelled",
    )
    reviewed_by_id = Column(
        Integer,
        ForeignKey("user.id"),
        nullable=True,
        comment="Manager/admin duyệt",
    )
    review_note = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    # CHỈ để filter/sort list duyệt — KHÔNG phải nguồn phân quyền. IDOR
    # approve/reject dùng lead.unit_id HIỆN TẠI (get_reopen_request_for_user §7.4),
    # KHÔNG dùng snapshot.
    # KHÔNG index=True đơn lẻ: composite ix_lead_reopen_request_unit_status có
    # unit_id làm cột dẫn đầu nên đã phủ truy vấn theo unit_id.
    unit_id = Column(
        Integer,
        ForeignKey("organization_unit.id"),
        nullable=False,
    )

    lead = relationship("Lead", foreign_keys=[lead_id])
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
