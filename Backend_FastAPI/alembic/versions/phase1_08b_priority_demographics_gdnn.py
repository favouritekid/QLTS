"""phase1_08b: priority demographics (GDNN priority bonus system)

Revision ID: phase1_08b
Revises: phase1_08a
Create Date: 2026-05-17

#184 Q9 #07 Wave A — Foundation schema for Priority Bonus System per
Thông tư 05/2021/TT-BLĐTBXH Phụ lục 01 (giáo dục nghề nghiệp).

Pulls Q9 #07 forward from Q1/2027 (was deferred per phase1_07b
docstring) so prod compliance with TT 05/2021 is in place before the
next admission round. Future TT 2026/BGDĐT will be handled via
admin-editable per-year rates in the same tables.

Tables created
--------------

* ``priority_area_config`` (KV rates per academic_year)
* ``priority_object_config`` (UT đối tượng rates per academic_year)
* ``vn_commune_area_map`` (commune -> area_code dictionary)
* ``vn_high_school`` (high school dictionary; PR1 ships empty,
  PR4 imports MOET CSV)

Columns added
-------------

* ``admission_profile``: 7 columns (high_school_id FK + KV resolved
  snapshot + commune_code + resolution_basis + reason + UT codes JSONB +
  UT evidence JSONB)
* ``admission_profile_choice``: 3 snapshot columns (area bonus + object
  bonus + frozen config JSONB at T6 publish, matching the existing
  ``bonus_rule_snapshot`` Q-P3-11 pattern)

Design decisions baked in
-------------------------

* **Temporal versioning** (effective_from + effective_to): supports
  mid-year regulation changes and commune-merge events. Default
  ``effective_from = CURRENT_DATE`` (= row creation date, no arbitrary
  epoch). NULL ``effective_to`` = currently valid.

* **Partial UNIQUE indexes** (WHERE effective_to IS NULL): enforces
  "at most one currently active row per (year, code)" semantic while
  allowing temporal history rows to coexist. Necessary because regular
  UNIQUE(year, code) would block the "Bộ ra TT giữa năm" scenario.

* **Soft-delete via ``is_active``** on ``vn_high_school``: admin "hides"
  duplicate/closed schools without losing audit trail. FK from
  ``admission_profile.high_school_id`` uses ``ondelete=RESTRICT`` so
  hard DELETE is blocked while a profile references the row.

* **CHECK regex on area_code / group_code / sub_code**: catches admin
  typos (``"KV1_"``, ``"kv1"``, ``"KV-1"`` etc.) at DB layer while
  still allowing future ``KV4``/``UT3`` extensions. Canonical form is
  ``KV2-NT`` (hyphen) matching TT 05/2021 Phụ lục 01 text.

* **No backfill / no seed**: rates seeded by admin via PR3 CRUD UI;
  existing 315 profiles get NULL on new columns (engine treats as 0đ
  graceful) and admin fills via PR7 backfill queue.

Down-revision chain: ``phase1_08a -> phase1_08b``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "phase1_08b"
down_revision: Union[str, None] = "phase1_08a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Idempotency guard for op.add_column. Same pattern as
    ``q4a1b2c3d4e5_add_academic_year_to_admission`` — protects against
    partial-fail re-run where a previous attempt added some columns
    before crashing on another."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) priority_area_config — admin CRUD KV rates per academic_year
    # ------------------------------------------------------------------
    op.create_table(
        "priority_area_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "academic_year",
            sa.Integer,
            nullable=False,
            comment="Year-level grouping (vd 2026); matches offering_admission_round.academic_year pattern (plain Integer, no FK)",
        ),
        sa.Column(
            "area_code",
            sa.String(20),
            nullable=False,
            comment="Canonical: KV1 / KV2-NT / KV2 / KV3 (hyphen, per TT 05/2021)",
        ),
        sa.Column("area_name", sa.String(100), nullable=False),
        sa.Column(
            "bonus_points",
            sa.Numeric(4, 2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "effective_from",
            sa.Date,
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "area_code ~ '^KV[1-9](-NT)?$'",
            name="ck_priority_area_config_area_code_format",
        ),
    )
    op.create_index(
        "uq_priority_area_config_year_code_active",
        "priority_area_config",
        ["academic_year", "area_code"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    # ------------------------------------------------------------------
    # 2) priority_object_config — admin CRUD UT rates per academic_year
    # ------------------------------------------------------------------
    op.create_table(
        "priority_object_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "academic_year",
            sa.Integer,
            nullable=False,
            comment="Year-level grouping (vd 2026); matches offering_admission_round.academic_year pattern (plain Integer, no FK)",
        ),
        sa.Column(
            "group_code",
            sa.String(10),
            nullable=False,
            comment="UT1 / UT2 (extensible UT3+ if Bộ thêm)",
        ),
        sa.Column(
            "sub_code",
            sa.String(10),
            nullable=False,
            comment="2-digit numeric: '01'..'07' per TT 05/2021 Phụ lục 01",
        ),
        sa.Column(
            "description",
            sa.Text,
            nullable=False,
            comment="vd 'Con liệt sĩ', 'Dân tộc thiểu số hộ khẩu KV1'",
        ),
        sa.Column(
            "bonus_points",
            sa.Numeric(4, 2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "evidence_doc_type",
            sa.String(100),
            nullable=True,
            comment="Gợi ý loại giấy tờ minh chứng cho thí sinh",
        ),
        sa.Column(
            "effective_from",
            sa.Date,
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "group_code ~ '^UT[1-9]$'",
            name="ck_priority_object_config_group_code_format",
        ),
        sa.CheckConstraint(
            "sub_code ~ '^[0-9]{2}$'",
            name="ck_priority_object_config_sub_code_format",
        ),
    )
    op.create_index(
        "uq_priority_object_config_year_sub_active",
        "priority_object_config",
        ["academic_year", "sub_code"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    # ------------------------------------------------------------------
    # 3) vn_commune_area_map — commune -> area_code dictionary
    #    PR1 ships empty. PR4 imports BNV CSV (~11k communes).
    # ------------------------------------------------------------------
    op.create_table(
        "vn_commune_area_map",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("commune_code", sa.String(20), nullable=False),
        sa.Column("province", sa.String(100), nullable=False),
        sa.Column("district", sa.String(100), nullable=False),
        sa.Column("ward", sa.String(100), nullable=False),
        sa.Column("area_code", sa.String(20), nullable=False),
        sa.Column(
            "effective_from",
            sa.Date,
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.CheckConstraint(
            "area_code ~ '^KV[1-9](-NT)?$'",
            name="ck_vn_commune_area_map_area_code_format",
        ),
    )
    op.create_index(
        "ix_vn_commune_area_map_location",
        "vn_commune_area_map",
        ["province", "district", "ward"],
    )
    op.create_index(
        "uq_vn_commune_area_map_code_active",
        "vn_commune_area_map",
        ["commune_code"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    # ------------------------------------------------------------------
    # 4) vn_high_school — high school dictionary
    #    PR1 ships empty. PR4 imports MOET CSV (~3k schools).
    # ------------------------------------------------------------------
    op.create_table(
        "vn_high_school",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("province", sa.String(100), nullable=True),
        sa.Column("district", sa.String(100), nullable=True),
        sa.Column("ward", sa.String(100), nullable=True),
        sa.Column(
            "kv_code",
            sa.String(20),
            nullable=True,
            comment="Denormalized from vn_commune_area_map for fast lookup",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
            comment=(
                "Soft-delete flag; FK admission_profile.high_school_id "
                "RESTRICT prevents hard DELETE while profiles reference row"
            ),
        ),
        sa.Column(
            "effective_from",
            sa.Date,
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.CheckConstraint(
            "kv_code IS NULL OR kv_code ~ '^KV[1-9](-NT)?$'",
            name="ck_vn_high_school_kv_code_format",
        ),
    )
    op.create_index(
        "ix_vn_high_school_name",
        "vn_high_school",
        ["name"],
    )
    op.create_index(
        "ix_vn_high_school_location_active",
        "vn_high_school",
        ["province", "district"],
        postgresql_where=sa.text("is_active = true"),
    )

    # ------------------------------------------------------------------
    # 5) admission_profile — 7 new columns
    #    All nullable except priority_object_codes / _evidence (NOT NULL
    #    with empty JSONB default so engine never gets NULL JSONB).
    #    Wrapped in _column_exists guards for partial-fail re-run safety.
    # ------------------------------------------------------------------
    if not _column_exists("admission_profile", "high_school_id"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "high_school_id",
                sa.BigInteger,
                sa.ForeignKey("vn_high_school.id", ondelete="RESTRICT"),
                nullable=True,
                comment=(
                    "FK to vn_high_school. RESTRICT prevents hard delete; "
                    "admin must use is_active=false for soft delete instead."
                ),
            ),
        )
    if not _column_exists("admission_profile", "high_school_kv_resolved"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "high_school_kv_resolved",
                sa.String(20),
                nullable=True,
                comment="KV snapshot at submit time, computed from high_school_id",
            ),
        )
    if not _column_exists("admission_profile", "permanent_commune_code"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "permanent_commune_code",
                sa.String(20),
                nullable=True,
                comment="Loose ref to vn_commune_area_map.commune_code (no DB FK)",
            ),
        )
    if not _column_exists("admission_profile", "area_resolution_basis"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "area_resolution_basis",
                sa.String(40),
                nullable=True,
                comment=(
                    "How KV was resolved: 'high_school' | "
                    "'permanent_address_special' | 'manual_override'"
                ),
            ),
        )
    if not _column_exists("admission_profile", "area_resolution_reason"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "area_resolution_reason",
                sa.Text,
                nullable=True,
                comment="Required when area_resolution_basis='manual_override'",
            ),
        )
    if not _column_exists("admission_profile", "priority_object_codes"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "priority_object_codes",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="Array of UT sub_codes thí sinh khai: ['04','06']",
            ),
        )
    if not _column_exists("admission_profile", "priority_object_evidence"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "priority_object_evidence",
                JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment=(
                    "{'04': {'document_id': 123, 'status': "
                    "'pending|verified|rejected', 'verified_by': 45, "
                    "'verified_at': '...', 'reject_reason': null}}"
                ),
            ),
        )

    # CHECK enum on area_resolution_basis — catches typos
    # (vd: 'highschool' vs 'high_school') at DB layer instead of
    # silently corrupting downstream engine resolution.
    op.create_check_constraint(
        "ck_admission_profile_area_resolution_basis",
        "admission_profile",
        (
            "area_resolution_basis IS NULL OR area_resolution_basis IN "
            "('high_school', 'permanent_address_special', 'manual_override')"
        ),
    )

    # ------------------------------------------------------------------
    # 6) admission_profile_choice — 3 snapshot columns at T6 publish
    #    (matches existing Q-P3-11 bonus_rule_snapshot pattern)
    # ------------------------------------------------------------------
    if not _column_exists(
        "admission_profile_choice", "priority_area_bonus_snapshot"
    ):
        op.add_column(
            "admission_profile_choice",
            sa.Column(
                "priority_area_bonus_snapshot",
                sa.Numeric(4, 2),
                nullable=True,
                comment="KV bonus applied at T6, snapshot from priority_area_config",
            ),
        )
    if not _column_exists(
        "admission_profile_choice", "priority_object_bonus_snapshot"
    ):
        op.add_column(
            "admission_profile_choice",
            sa.Column(
                "priority_object_bonus_snapshot",
                sa.Numeric(4, 2),
                nullable=True,
                comment=(
                    "UT bonus applied at T6 (max of verified UT codes), snapshot "
                    "from priority_object_config"
                ),
            ),
        )
    if not _column_exists(
        "admission_profile_choice", "priority_config_snapshot"
    ):
        op.add_column(
            "admission_profile_choice",
            sa.Column(
                "priority_config_snapshot",
                JSONB,
                nullable=True,
                comment=(
                    "Frozen rates + resolution_basis + resolved_at at T6 publish "
                    "time for audit replay"
                ),
            ),
        )


def downgrade() -> None:
    # Inverse order — drop additive columns first, then new tables.

    # admission_profile_choice columns
    op.drop_column("admission_profile_choice", "priority_config_snapshot")
    op.drop_column("admission_profile_choice", "priority_object_bonus_snapshot")
    op.drop_column("admission_profile_choice", "priority_area_bonus_snapshot")

    # admission_profile CHECK constraint (drop before the column it guards)
    op.drop_constraint(
        "ck_admission_profile_area_resolution_basis",
        "admission_profile",
        type_="check",
    )

    # admission_profile columns
    op.drop_column("admission_profile", "priority_object_evidence")
    op.drop_column("admission_profile", "priority_object_codes")
    op.drop_column("admission_profile", "area_resolution_reason")
    op.drop_column("admission_profile", "area_resolution_basis")
    op.drop_column("admission_profile", "permanent_commune_code")
    op.drop_column("admission_profile", "high_school_kv_resolved")
    op.drop_column("admission_profile", "high_school_id")

    # New tables — indexes go with their tables in drop_table
    op.drop_index("ix_vn_high_school_location_active", table_name="vn_high_school")
    op.drop_index("ix_vn_high_school_name", table_name="vn_high_school")
    op.drop_table("vn_high_school")

    op.drop_index(
        "uq_vn_commune_area_map_code_active",
        table_name="vn_commune_area_map",
    )
    op.drop_index(
        "ix_vn_commune_area_map_location",
        table_name="vn_commune_area_map",
    )
    op.drop_table("vn_commune_area_map")

    op.drop_index(
        "uq_priority_object_config_year_sub_active",
        table_name="priority_object_config",
    )
    op.drop_table("priority_object_config")

    op.drop_index(
        "uq_priority_area_config_year_code_active",
        table_name="priority_area_config",
    )
    op.drop_table("priority_area_config")
