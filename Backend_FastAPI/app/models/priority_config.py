# app/models/priority_config.py
"""ORM models for priority bonus configuration (Q9 #07 PR1).

Two admin-editable, year-scoped tables that drive the priority bonus
calculation in PR2's ``priority_service.py``:

* ``PriorityAreaConfig`` — KV (khu vực) rates per academic_year.
  Default seed in PR3 matches TT 05/2021 Phụ lục 01:
  KV1=0.75 / KV2-NT=0.5 / KV2=0.25 / KV3=0.

* ``PriorityObjectConfig`` — UT (đối tượng) rates per academic_year +
  sub_code. Default seed in PR3 matches TT 05/2021 Phụ lục 01:
  UT1 group (sub_codes 01-04) = 2.0, UT2 group (sub_codes 05-07) = 1.0.
  Multi-UT calculation rule (max of verified codes) lives in PR2 engine.

Temporal versioning
-------------------

Both tables carry ``effective_from`` / ``effective_to`` so a regulation
change mid-year creates a new row instead of mutating the old one.
Partial UNIQUE indexes (``WHERE effective_to IS NULL``) defined in
``phase1_08b`` migration enforce "at most one active row per
(year, code)" while allowing history rows to coexist.

See ``alembic/versions/phase1_08b_priority_demographics_gdnn.py`` for
DDL + CHECK constraints (area_code/group_code/sub_code regex).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PriorityAreaConfig(Base):
    """KV (khu vực) bonus rate, scoped per academic_year.

    Lookup pattern (PR2 engine):
        SELECT bonus_points
        FROM priority_area_config
        WHERE academic_year = :year
          AND area_code = :kv_code
          AND effective_from <= CURRENT_DATE
          AND (effective_to IS NULL OR effective_to > CURRENT_DATE)
    """

    __tablename__ = "priority_area_config"
    __table_args__ = (
        # Mirror of phase1_08b CHECK — catches typos at Base.metadata.create_all()
        # test DB (which doesn't run alembic). Memory test-db-schema-source.
        CheckConstraint(
            "area_code ~ '^KV[1-9](-NT)?$'",
            name="ck_priority_area_config_area_code_format",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    academic_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Year-level grouping (vd 2026)",
    )
    area_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Canonical: KV1 / KV2-NT / KV2 / KV3 (hyphen, per TT 05/2021)",
    )
    area_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bonus_points: Mapped[Decimal] = mapped_column(
        Numeric(4, 2),
        nullable=False,
        server_default="0.00",
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        server_default=sa.text("CURRENT_DATE"),
    )
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

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

    def __repr__(self) -> str:
        return (
            f"<PriorityAreaConfig id={self.id} year={self.academic_year} "
            f"code={self.area_code!r} pts={self.bonus_points}>"
        )


class PriorityObjectConfig(Base):
    """UT (đối tượng) bonus rate, scoped per academic_year + sub_code.

    Lookup pattern (PR2 engine, multi-UT max rule):
        SELECT MAX(bonus_points)
        FROM priority_object_config
        WHERE academic_year = :year
          AND sub_code = ANY(:verified_codes)
          AND effective_from <= CURRENT_DATE
          AND (effective_to IS NULL OR effective_to > CURRENT_DATE)
    """

    __tablename__ = "priority_object_config"
    __table_args__ = (
        # Mirror of phase1_08b CHECKs — see PriorityAreaConfig note.
        CheckConstraint(
            "group_code ~ '^UT[1-9]$'",
            name="ck_priority_object_config_group_code_format",
        ),
        CheckConstraint(
            "sub_code ~ '^[0-9]{2}$'",
            name="ck_priority_object_config_sub_code_format",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    academic_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Year-level grouping (vd 2026)",
    )
    group_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="UT1 / UT2 (extensible UT3+ if Bộ thêm)",
    )
    sub_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="2-digit numeric: '01'..'07' per TT 05/2021 Phụ lục 01",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="vd 'Con liệt sĩ', 'Dân tộc thiểu số hộ khẩu KV1'",
    )
    bonus_points: Mapped[Decimal] = mapped_column(
        Numeric(4, 2),
        nullable=False,
        server_default="0.00",
    )
    evidence_doc_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Gợi ý loại giấy tờ minh chứng cho thí sinh",
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        server_default=sa.text("CURRENT_DATE"),
    )
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

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

    def __repr__(self) -> str:
        return (
            f"<PriorityObjectConfig id={self.id} year={self.academic_year} "
            f"group={self.group_code} sub={self.sub_code!r} "
            f"pts={self.bonus_points}>"
        )
