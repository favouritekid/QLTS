# app/models/vn_school.py
"""ORM models for Q9 #07 PR5 Redesign — Temporal multi-school KV resolution.

Replaces ``VnHighSchool`` (PR1 single-school placeholder) với 3-table family
that handles:

* Multi-level support: THCS / THPT / THCS_THPT (liên cấp) /
  TRUNG_HOC_NGHE (dự thảo TT 2026) / OTHER
* Slowly-changing dimensions: school name history + KV reassignment over time
* Per-year KV lookup theo TT 05/2021 Phụ lục 01 multi-school rule

See ``Documents/Q9_07_PR5_REDESIGN.md`` v1.3 cho design rationale +
``alembic/versions/phase1_09_priority_kv_temporal.py`` cho DDL.

3 models trong file này:

* ``VnSchool`` — master directory (PR4 imports MOET 2025 THPT list ~6,822 rows
  + admin manual entry cho TC ~100 schools + THCS audit-only)
* ``VnSchoolNameHistory`` — slowly-changing tên trường (sát nhập + đổi tên)
* ``VnSchoolKvAssignment`` — temporal KV per (school_id, year_range)
  với service-layer overlap check (M3 fix: dropped GiST EXCLUDE)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class VnSchool(Base):
    """Vietnam school master directory — supports multi-level + SCD.

    Lookup patterns (PR2 engine + PR5 candidate FE):
    * Search by name (trigram) for candidate dropdown
    * Lookup KV via ``vn_school_kv_assignment`` for academic_year

    Soft-delete via ``is_active``; FK from ``admission_profile`` (if any)
    uses RESTRICT to preserve audit trail.

    Mergers tracked via ``merged_into_id`` self-FK; KV lookup vẫn dùng
    ``school_id`` gốc + năm gốc (KHÔNG follow merger).
    """

    __tablename__ = "vn_school"
    __table_args__ = (
        # Mirror migration CHECK — Base.metadata.create_all() test DB
        # parity per memory ``test-db-schema-source``.
        CheckConstraint(
            "level IN ('THCS', 'THPT', 'THCS_THPT', 'TRUNG_HOC_NGHE', 'OTHER')",
            name="ck_vn_school_level",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # MOET reference
    moet_school_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="MOET school code (per Bộ GD-ĐT Apr 2025 directory)",
    )
    moet_province_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="MOET province code — composite unique với moet_school_code",
    )
    moet_district_code: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)

    # Khóa đối chiếu chuẩn hóa (schoolkv01) — nguồn: danh sách THPT MOET + QĐ 19/2025.
    # moet_code = Mã Tỉnh(GSO 2) + Mã Trường(3) = 5 số, duy nhất toàn quốc → khóa
    # đối chiếu CHÍNH khi cập nhật năm sau. commune_code = mã xã 5 số (QĐ 19/2025,
    # = administrative_nodes.code) → khóa PHỤ (fallback commune+tên) + nối trường→xã.
    moet_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    commune_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Canonical current info
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Canonical current name; historical via vn_school_name_history",
    )
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    province: Mapped[str] = mapped_column(String(100), nullable=False)
    district: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ward: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Level support (5 enum values)
    level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="THCS | THPT | THCS_THPT (liên cấp) | TRUNG_HOC_NGHE (dự thảo TT 2026) | OTHER",
    )

    is_dtnt: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa.text("false"),
        comment="Trường PT Dân tộc Nội trú — flag for special case bypass",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa.text("true"),
        comment="Soft-delete flag; FK from admission_profile uses RESTRICT",
    )

    # Merger tracking
    merged_into_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("vn_school.id"),
        nullable=True,
        comment="If school merged, points to surviving school. KV lookup vẫn theo school_id gốc.",
    )
    merge_effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    # Relationships
    name_history: Mapped[list["VnSchoolNameHistory"]] = relationship(
        back_populates="school",
        cascade="all, delete-orphan",
    )
    kv_assignments: Mapped[list["VnSchoolKvAssignment"]] = relationship(
        back_populates="school",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<VnSchool id={self.id} name={self.name!r} level={self.level} "
            f"active={self.is_active}>"
        )


class VnSchoolNameHistory(Base):
    """Slowly-changing name history per school.

    Lookup pattern: tên trường tại thời điểm học (vd: candidate học 2018-2021
    trước khi trường đổi tên 2023 → audit hiển thị tên cũ).

    Query example:
        SELECT name FROM vn_school_name_history
        WHERE school_id = :sid
          AND effective_from <= :date
          AND (effective_to IS NULL OR effective_to >= :date)
        ORDER BY effective_from DESC LIMIT 1;
    """

    __tablename__ = "vn_school_name_history"
    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "effective_from",
            name="uq_vn_school_name_history_school_effective",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("vn_school.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="vd 'Sát nhập với Trường X' hoặc 'Đổi tên theo QĐ Y'",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    school: Mapped["VnSchool"] = relationship(back_populates="name_history")

    def __repr__(self) -> str:
        return (
            f"<VnSchoolNameHistory school_id={self.school_id} name={self.name!r} "
            f"from={self.effective_from} to={self.effective_to}>"
        )


class VnSchoolKvAssignment(Base):
    """Per-year KV classification per school (temporal lookup).

    Service-layer overlap check (M3 fix per memory `migration-predicate-safety`):
    inserts must verify no existing row overlaps `(school_id, year_range)`.
    See ``app/services/priority_service.add_kv_assignment`` for guard.

    Query pattern (canonical KV lookup at academic_year):
        SELECT kv_code FROM vn_school_kv_assignment
        WHERE school_id = :sid
          AND :year BETWEEN effective_from_year AND COALESCE(effective_to_year, 9999)
        LIMIT 1;
    """

    __tablename__ = "vn_school_kv_assignment"
    __table_args__ = (
        CheckConstraint(
            "kv_code ~ '^KV[1-9](-NT)?$'",
            name="ck_vn_school_kv_assignment_kv_code_format",
        ),
        CheckConstraint(
            "effective_to_year IS NULL OR effective_to_year >= effective_from_year",
            name="ck_vn_school_kv_assignment_year_range_valid",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("vn_school.id", ondelete="CASCADE"),
        nullable=False,
    )
    kv_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="KV1 | KV2-NT | KV2 | KV3 (hyphen canonical per TT 05/2021)",
    )
    effective_from_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Năm bắt đầu hiệu lực (vd 2025 = năm học 2025-2026)",
    )
    effective_to_year: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Năm kết thúc (inclusive). NULL = ongoing.",
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="moet_2024 | moet_2025 | qd_861 | manual_admin | qd_ubnd_<tinh>",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    school: Mapped["VnSchool"] = relationship(back_populates="kv_assignments")

    def __repr__(self) -> str:
        return (
            f"<VnSchoolKvAssignment school_id={self.school_id} kv={self.kv_code} "
            f"year={self.effective_from_year}-{self.effective_to_year or 'now'}>"
        )
