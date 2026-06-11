# app/models/sms/campaign_recipient.py
"""
SMS campaign recipient — snapshot đóng băng tại thời điểm build (bảng
trung tâm). Mỗi recipient unique theo (campaign, build_revision, phone).
KHÔNG lưu raw short code: chỉ `token_hash` (HMAC, lookup) + `token_ciphertext`
(Fernet, re-export) + `rendered_message_skeleton` (sentinel cho link).
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.8.

⚠ Index đặc biệt (đã khai ở __table_args__ để create_all() cho qlts_test
sinh đúng; migration cũng phải viết tay khớp): partial UNIQUE token_hash,
GIN group_ids_snapshot, composite (campaign, revision, carrier).
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
    Text, text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsCampaignRecipient(Base):
    """Snapshot 1 người nhận trong 1 build revision của campaign."""

    __tablename__ = "sms_campaign_recipient"

    __table_args__ = (
        # Gửi 1 lần/người trong 1 revision.
        Index(
            "uq_sms_recipient_campaign_rev_phone",
            "campaign_id", "build_revision", "phone_normalized_snapshot",
            unique=True,
        ),
        # Partial UNIQUE token_hash (chỉ khi có link) → resolve /r/{code}.
        Index(
            "uq_sms_recipient_token_hash",
            "token_hash",
            unique=True,
            postgresql_where=text("token_hash IS NOT NULL"),
        ),
        # GIN cho query nhóm: group_ids_snapshot @> ARRAY[:gid]::integer[].
        Index(
            "ix_sms_recipient_group_ids_gin",
            "group_ids_snapshot",
            postgresql_using="gin",
        ),
        # Tăng tốc export/preflight.
        Index(
            "ix_sms_recipient_campaign_rev_carrier",
            "campaign_id", "build_revision", "carrier_bucket",
        ),
        CheckConstraint(
            "excluded_reason IS NULL OR excluded_reason IN "
            "('no_consent','opted_out','dnc_suppressed','frequency_capped',"
            "'over_limit','missing_data')",
            name="chk_sms_recipient_excluded_reason",
        ),
        CheckConstraint(
            "encoding IS NULL OR encoding IN ('GSM7','UCS2')",
            name="chk_sms_recipient_encoding",
        ),
        # Token triplet: cùng NULL (không link) hoặc cùng NOT NULL (re-export được).
        CheckConstraint(
            "(token_hash IS NULL AND token_ciphertext IS NULL "
            "AND token_key_version IS NULL) OR "
            "(token_hash IS NOT NULL AND token_ciphertext IS NOT NULL "
            "AND token_key_version IS NOT NULL)",
            name="chk_sms_recipient_token_triplet",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_campaign.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    build_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    contact_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="SET NULL"),
        nullable=True,
        comment="snapshot giữ kể cả khi contact bị xoá",
    )
    group_ids_snapshot: Mapped[List[int]] = mapped_column(
        ARRAY(Integer), nullable=False,
        comment="nhóm đã chọn đóng góp contact này (report theo nhóm)",
    )
    full_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_normalized_snapshot: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="0xxxxxxxxx",
    )
    phone_international_snapshot: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="84xxxxxxxxx (xuất Excel)",
    )
    note_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    carrier_bucket: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="viettel … unknown",
    )

    # --- Token (KHÔNG lưu plaintext) ---
    token_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="HMAC-SHA256(code, SMS_TOKEN_HASH_SECRET); NULL nếu không có {link}",
    )
    token_ciphertext: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Fernet ciphertext của code",
    )
    token_key_version: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="chọn key trong key-ring",
    )
    rendered_message_skeleton: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="tin cuối dùng sentinel cố định cho link; KHÔNG chứa raw code",
    )
    message_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    encoding: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True, comment="GSM7 / UCS2",
    )
    segments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_over_limit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    excluded_reason: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="no_consent/opted_out/dnc_suppressed/frequency_capped/"
        "over_limit/missing_data/NULL(=export)",
    )
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="revision cũ chưa bàn giao bị vô hiệu khi rebuild",
    )
    handed_off_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="set khi batch tương ứng được xác nhận bàn giao",
    )

    # --- Click denormalize (bot tách khỏi human) ---
    raw_click_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="tổng click GỒM bot (audit)",
    )
    human_click_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="click loại bot — 'đã click' hiển thị cho người dùng",
    )
    first_human_clicked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_human_clicked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<SmsCampaignRecipient {self.id} campaign={self.campaign_id} "
            f"rev={self.build_revision} {self.phone_normalized_snapshot}>"
        )
