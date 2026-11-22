"""Bảng GĐ1b — duyệt giấy nhanh, duyệt chéo tạm thời, dấu tải xuống, tệp bằng chứng.

Đặc tả: ``logs-P5/cong-bo-ket-qua/gd1b/DAC-TA-GD1B-DUYET-GIAY-NHANH-BAN3-6-2026-11-17.md`` (sha256 ``9ef02da2…4e2e``)
§4.3, §4.6b, §5.1, §6. Tên bảng / cột tiếng Anh (quy ước owner 17-11); chú thích tiếng Việt.

Bản cho ``create_all()`` (CSDL test không chạy Alembic). Bản thật: migration ``gd1b20261117``. Hai bản khoá bằng
``tests/unit/test_gd1b_models_khop_migration.py``.

Không khai quan hệ ORM từ ``ProfileDocument`` / ``DocumentAuditLog`` / ``User`` sang các bảng này: ORM mà có quan hệ
không ``passive_deletes`` sẽ tự gán NULL vượt qua ``RESTRICT`` của CSDL (§4.6b).
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from app.models.base import Base, TruncatedString

#: Trần một lần cấp quyền duyệt chéo (owner chốt 6a = 14 ngày). Đổi ⇒ test khoá đỏ.
CROSS_REVIEW_MAX_DAYS = 14

#: Trạng thái lô (§5.1). ``expired`` không ghi — suy từ ``expires_at``.
BULK_BATCH_STATUSES = ("previewed", "processing", "completed", "stopped", "interrupted")
#: Kết quả từng mục (§5.1).
BULK_ITEM_RESULTS = ("recorded", "error", "not_processed")
#: Đường chạy lô: duyệt hàng loạt của Quản lý / Admin, hoặc lô duyệt chéo (§6 "lô cùng khuôn §5").
BULK_REVIEW_MODES = ("batch", "cross")


class DocumentDownloadLog(Base):
    """Dấu tải xuống giấy tờ — ĐỘC LẬP vòng đời hồ sơ / giấy (K4c, §4.3).

    ``profile_id`` / ``document_row_id`` là số nguyên KHÔNG khoá ngoại: xoá hồ sơ nháp (CASCADE nhật ký giấy) không làm
    mất dấu tải ⇒ K4 vẫn thấy người đã tải.
    """

    __tablename__ = "document_download_log"

    id = Column(BigInteger, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id = Column(Integer, nullable=False, index=True)
    document_row_id = Column(Integer, nullable=False, index=True)
    document_type_code = Column(String(100), nullable=True)
    downloaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ip_address = Column(String(45), nullable=True)
    #: PR-D (F12): cắt theo độ dài cột ở tầng kiểu (``TruncatedString``) — nơi ghi không tự cắt.
    user_agent = Column(TruncatedString(500), nullable=True)
    #: Dòng nhật ký giấy cùng lượt tải (NULL khi dòng ấy đã bị xoá dây chuyền). Dùng cho điền ngược không trùng.
    source_audit_id = Column(Integer, nullable=True, unique=True)


class DocumentEvidenceFile(Base):
    """Tệp đang gắn với giấy thường LÚC giấy được duyệt (K5, §4.6b). Chỉ thêm, không sửa / xoá trong GĐ1b."""

    __tablename__ = "document_evidence_file"

    id = Column(Integer, primary_key=True)
    profile_document_id = Column(
        Integer, ForeignKey("profile_document.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    verification_audit_id = Column(
        Integer, ForeignKey("document_audit_log.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    profile_id = Column(Integer, nullable=False, index=True)
    file_path = Column(String(500), nullable=False, index=True)
    sha256 = Column(String(64), nullable=True)
    verified_by_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True)
    verified_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    file_missing = Column(Boolean, nullable=False, server_default=text("false"))
    retention_basis = Column(String(100), nullable=True)
    retain_until = Column(Date, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_evidence_file_sha256",
        ),
        CheckConstraint(
            "file_missing OR sha256 IS NOT NULL",
            name="ck_document_evidence_file_sha256_present",
        ),
    )


class DocumentCrossReviewGrant(Base):
    """Quyền duyệt chéo tạm thời — MỘT loại quyền, cấp theo từng cán bộ nêu tên (C3, §6). Chỉ thu hồi, không xoá."""

    __tablename__ = "document_cross_review_grant"

    id = Column(Integer, primary_key=True)
    grantee_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    unit_id = Column(Integer, ForeignKey("organization_unit.id", ondelete="RESTRICT"), nullable=False, index=True)
    allow_verify = Column(Boolean, nullable=False, server_default=text("false"))
    allow_reject = Column(Boolean, nullable=False, server_default=text("false"))
    granted_by_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    granted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True)

    __table_args__ = (
        CheckConstraint("allow_verify OR allow_reject", name="ck_cross_review_grant_action"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_cross_review_grant_reason"),
        CheckConstraint(
            "expires_at > granted_at AND expires_at <= granted_at + interval '14 days'",
            name="ck_cross_review_grant_max_days",
        ),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_user_id IS NULL)",
            name="ck_cross_review_grant_revoked_pair",
        ),
    )


class DocumentBulkBatch(Base):
    """Một lô duyệt giấy — có dòng ngay từ bước xem trước (``previewed``, F373, §5.1)."""

    __tablename__ = "document_bulk_batch"

    batch_id = Column(PG_UUID(as_uuid=True), primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    review_mode = Column(String(10), nullable=False, server_default="batch")
    grant_id = Column(
        Integer, ForeignKey("document_cross_review_grant.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    filter_json = Column(JSONB, nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    include_optional = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    confirmation_text = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    finalized_by_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    finalize_reason = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, server_default="previewed")
    ip_address = Column(String(45), nullable=True)
    #: PR-D (F12): ghi bằng ``__table__.insert()`` (Core) — kiểu cột vẫn cắt; nơi ghi không tự cắt ``[:500]``.
    user_agent = Column(TruncatedString(500), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('previewed','processing','completed','stopped','interrupted')",
            name="ck_document_bulk_batch_status",
        ),
        CheckConstraint("review_mode IN ('batch','cross')", name="ck_document_bulk_batch_review_mode"),
        CheckConstraint(
            "(review_mode = 'cross') = (grant_id IS NOT NULL)",
            name="ck_document_bulk_batch_grant",
        ),
        CheckConstraint(
            "(finalized_at IS NULL) = (finalized_by_user_id IS NULL)",
            name="ck_document_bulk_batch_finalized_pair",
        ),
        Index("ix_document_bulk_batch_actor_created", "actor_user_id", "created_at"),
    )


class DocumentBulkBatchItem(Base):
    """Một giấy trong lô, khoá theo ``document_row_id`` (= ``profile_document.id``). Không khoá ngoại tới giấy / hồ sơ:
    dòng kết quả của lô đã chạy là dấu vết thao tác, sống độc lập với giấy (§5.8)."""

    __tablename__ = "document_bulk_batch_item"

    batch_id = Column(
        PG_UUID(as_uuid=True), ForeignKey("document_bulk_batch.batch_id", ondelete="CASCADE"), nullable=False
    )
    document_row_id = Column(Integer, nullable=False)
    profile_id = Column(Integer, nullable=False, index=True)
    document_type_code = Column(String(100), nullable=True)
    expected_row_version = Column(Integer, nullable=False)
    result = Column(String(20), nullable=True)
    reason_code = Column(String(60), nullable=True)
    message = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("batch_id", "document_row_id", name="pk_document_bulk_batch_item"),
        CheckConstraint(
            "result IS NULL OR result IN ('recorded','error','not_processed')",
            name="ck_document_bulk_batch_item_result",
        ),
    )
