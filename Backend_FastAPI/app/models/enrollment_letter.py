# app/models/enrollment_letter.py
"""
EnrollmentLetter — official "Giấy báo nhập học" issuance record.

Each row is one OFFICIAL admission letter issued for an AdmissionProfile that
is post-decision (admitted-like / confirmed / enrolled — see
``utils.admission_status.is_enrollment_letter_eligible``). Issuance is a
mutation: it snapshots the input dates + the rendered data, persists the PDF to
disk (path + sha256 + size + retention) and records who/when. Re-issue creates
a NEW row (versioned history); download is served by ``letter_id`` from disk.

Why persist (not just stream): this is an official document that tells a
candidate they have been admitted. We need an audit trail (generated_by/at),
integrity (sha256) and a record of WHAT was printed (data_snapshot) — a
fire-and-forget stream would leave no record. Preview/draft output for
pre-decision profiles is a SEPARATE, watermarked, non-persisted feature.

⚠️ Vòng đời của ``data_snapshot``: ĐẦY ĐỦ trong thời hạn lưu trữ (re-render
được nguyên văn), sau đó task retention XOÁ phần PII (tên/ngày sinh/địa chỉ/
điện thoại) và đánh dấu ``_purged``. Phần phi-PII đã in ở lại vĩnh viễn —
ngành, học phí, năm học, mức đợt 1, tài khoản ngân hàng, người ký — nên vẫn
đối chiếu được "giấy đã nói gì" dù không dựng lại được bản có danh tính.
Đừng viết code giả định snapshot luôn còn đủ trường.
"""

from datetime import date, datetime
from sqlalchemy import (
    Integer,
    BigInteger,
    String,
    Date,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class EnrollmentLetter(Base):
    """Official admission-letter issuance record (one row per issue)."""

    __tablename__ = "enrollment_letter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Hồ sơ được phát giấy báo nhập học",
    )

    # --- Officer-entered issuance window (validated end >= start at the API) ---
    enrollment_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Ngày bắt đầu lên trường làm thủ tục (officer nhập)",
    )
    enrollment_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Ngày kết thúc (officer nhập; validate >= start)",
    )

    # --- Reproducibility snapshot of the exact data rendered onto the PDF ---
    # Keys (minimal): full_name, dob, permanent_address, major_name,
    # degree_level, offering_type, hk1_fee_amount, fee_id.
    data_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Snapshot dữ liệu đã render (tái lập/đối chiếu về sau)",
    )

    # --- Artifact on disk (outside webroot, same pattern as SMS export) ---
    file_path: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Đường dẫn PDF trên đĩa (private_exports/letters/...)",
    )
    sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 hex của file để verify toàn vẹn khi download",
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Kích thước file (bytes)",
    )

    # --- Audit + retention ---
    generated_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Người phát giấy (admin/manager/officer)",
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Thời điểm phát giấy",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Hạn giữ file trên đĩa (retention cleanup)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # --- Relationships ---
    profile: Mapped["AdmissionProfile"] = relationship(  # noqa: F821
        "AdmissionProfile",
        foreign_keys=[profile_id],
    )
    generated_by: Mapped["User | None"] = relationship(  # noqa: F821
        "User",
        foreign_keys=[generated_by_id],
    )

    def __repr__(self) -> str:
        return (
            f"<EnrollmentLetter id={self.id} profile_id={self.profile_id} "
            f"generated_at={self.generated_at}>"
        )
