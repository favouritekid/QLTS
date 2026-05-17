# app/models/vn_locality.py
"""ORM models for Vietnam locality dictionaries (Q9 #07 PR1).

Two read-mostly reference tables imported in PR4:

* ``VnCommuneAreaMap`` — maps a Vietnam commune (province + district +
  ward) to its KV (khu vực) area_code. ~11k rows when imported.
  Source: TT 06/2026/BNV (post commune-merge 2025).

* ``VnHighSchool`` — dictionary of Vietnam high schools (~3k rows)
  with denormalized ``kv_code`` for fast resolution in C2 hybrid flow.
  Source: MOET public school list.

Both ship empty in PR1. PR4 imports CSV. PR5 candidate FE uses these
for searchable dropdowns. PR2 engine uses them for KV auto-resolve.

Soft-delete pattern on ``VnHighSchool``
---------------------------------------

``vn_high_school.is_active`` enables admins to "hide" duplicate or
closed-school rows without losing the audit trail. FK
``admission_profile.high_school_id`` uses ``ondelete=RESTRICT`` so a
hard DELETE is blocked while profiles reference the row; admins must
use the soft-delete path instead. This matches the existing convention
in 10+ QLTS models (offering_admission_round, major_program, etc.).

Temporal versioning on both tables
----------------------------------

Both tables carry ``effective_from`` / ``effective_to`` so commune-merge
and school-merge events create new rows instead of mutating. Partial
UNIQUE on ``vn_commune_area_map.commune_code`` (WHERE effective_to IS
NULL) defined in ``phase1_08b`` migration enforces "at most one active
mapping per commune code".

See ``alembic/versions/phase1_08b_priority_demographics_gdnn.py`` for
DDL + CHECK constraints (area_code / kv_code regex).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VnCommuneAreaMap(Base):
    """Commune (province + district + ward) -> KV area_code mapping.

    Lookup pattern (PR5 candidate FE backup case, PR2 engine):
        SELECT area_code
        FROM vn_commune_area_map
        WHERE commune_code = :code
          AND effective_from <= CURRENT_DATE
          AND (effective_to IS NULL OR effective_to > CURRENT_DATE)
    """

    __tablename__ = "vn_commune_area_map"
    __table_args__ = (
        # Mirror of phase1_08b CHECK — see PriorityAreaConfig note.
        CheckConstraint(
            "area_code ~ '^KV[1-9](-NT)?$'",
            name="ck_vn_commune_area_map_area_code_format",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    commune_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="BNV commune code (partial UNIQUE WHERE effective_to IS NULL)",
    )
    province: Mapped[str] = mapped_column(String(100), nullable=False)
    district: Mapped[str] = mapped_column(String(100), nullable=False)
    ward: Mapped[str] = mapped_column(String(100), nullable=False)
    area_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Canonical: KV1 / KV2-NT / KV2 / KV3 (hyphen, per TT 05/2021)",
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        server_default=sa.text("CURRENT_DATE"),
    )
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<VnCommuneAreaMap id={self.id} code={self.commune_code!r} "
            f"area={self.area_code} ward={self.ward!r}>"
        )


class VnHighSchool(Base):
    """High school dictionary with denormalized KV for fast resolution.

    Lookup pattern (PR5 candidate FE primary case, PR2 engine):
        SELECT kv_code
        FROM vn_high_school
        WHERE id = :hs_id
          AND is_active = true
          AND effective_from <= CURRENT_DATE
          AND (effective_to IS NULL OR effective_to > CURRENT_DATE)
    """

    __tablename__ = "vn_high_school"
    __table_args__ = (
        # Mirror of phase1_08b CHECK — kv_code is nullable but if set must match.
        CheckConstraint(
            "kv_code IS NULL OR kv_code ~ '^KV[1-9](-NT)?$'",
            name="ck_vn_high_school_kv_code_format",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    province: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    district: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ward: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    kv_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Denormalized from vn_commune_area_map for fast lookup",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa.text("true"),
        comment=(
            "Soft-delete flag; FK admission_profile.high_school_id RESTRICT "
            "prevents hard DELETE while profiles reference row"
        ),
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        server_default=sa.text("CURRENT_DATE"),
    )
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<VnHighSchool id={self.id} name={self.name!r} "
            f"kv={self.kv_code} active={self.is_active}>"
        )
