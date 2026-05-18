"""phase1_09: Priority KV temporal multi-school redesign (Q9 #07 PR5 redesign)

Revision ID: phase1_09
Revises: phase1_08b
Create Date: 2026-05-17

#184 Q9 #07 Wave B — Redesign per TT 05/2021/TT-BLĐTBXH Phụ lục 01.

Why redesign
------------

PR1 (phase1_08b) shipped với 1 ``high_school_id`` field duy nhất. Sau khi
audit TT 05/2021 Phụ lục 01:

    "Nếu trong 3 năm học trung học phổ thông có chuyển trường thì thời
     gian học ở khu vực nào lâu hơn được hưởng ưu tiên theo khu vực đó."

    "Khi mỗi năm học một trường thuộc các khu vực có mức ưu tiên khác
     nhau hoặc nửa thời gian học ở trường này, nửa thời gian học ở
     trường kia thì tốt nghiệp ở khu vực nào, hưởng ưu tiên theo khu
     vực đó."

→ KV resolution cần multi-school history với weighted resolution +
graduation-school tiebreak. Single field không đủ.

Plus slowly-changing dimensions:
* Tên trường có thể đổi (sát nhập)
* KV của trường có thể đổi qua năm (TT mới, sáp nhập xã)
* Schema phải lookup KV THEO THỜI ĐIỂM HỌC (academic_year), không current

Changes
-------

DROP (PR1 empty placeholders — 0 prod rows):
* ``vn_high_school`` table
* ``admission_profile.high_school_id``
* ``admission_profile.high_school_kv_resolved``
* ``admission_profile.area_resolution_reason`` (canonical moved to
  ``priority_resolution_snapshot.manual_override_reason``)

CREATE (new temporal schema):
* ``vn_school`` — master directory (THCS / THPT / THCS_THPT liên cấp /
  TRUNG_HOC_NGHE future / OTHER)
* ``vn_school_name_history`` — slowly-changing tên trường
* ``vn_school_kv_assignment`` — KV theo năm, support TT update mid-period

ADD columns trên ``admission_profile``:

* ``cultural_education_level`` VARCHAR(30) NULL — Trình độ văn hóa
  candidate đã hoàn thành/tốt nghiệp. Values: ``completed_thcs`` |
  ``graduated_thcs`` | ``completed_thpt`` | ``graduated_thpt`` |
  ``graduated_gdtx``. CHECK constraint enforce enum.

* ``vocational_qualification`` VARCHAR(30) NOT NULL DEFAULT 'none' —
  Trình độ chuyên môn (nghề nghiệp) đã tốt nghiệp. Values: ``none`` |
  ``so_cap`` | ``trung_cap`` | ``cao_dang``. CHECK enforce enum.

* ``priority_resolution_snapshot`` JSONB: shape ``{kv_resolved,
  rule_applied, pathway, breakdown, frozen_at, frozen_at_status,
  manual_override_reason}``. Frozen at submit T1 + re-frozen at
  engine T6 (per Q-P3-11 snapshot pattern).

2-field parallel design (v1.3 2026-05-18) per VN admission convention
(Luật GDNN 2014/2025 + TT 05/2021 Điều 4). Cultural = phổ thông,
vocational = nghề nghiệp; both dimensions độc lập. KV basis derivation
matrix dispatches on combination.

KEEP (unchanged):
* ``vn_commune_area_map`` — still needed for TC pathway B
* ``admission_profile.permanent_commune_code``
* ``admission_profile.area_resolution_basis``
* ``admission_profile.priority_object_codes``
* ``admission_profile.priority_object_evidence``
* ``admission_profile_choice.priority_*_snapshot`` (3 cols)

Data safety
-----------

PR1 schema deployed but 0 prod rows in any of the dropped tables/columns
(verified 2026-05-17). Drop operations safe + reversible via downgrade.

Down-revision chain: ``phase1_08b -> phase1_09``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "phase1_09"
down_revision: Union[str, None] = "phase1_08b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """Idempotency guard — true if table already in DB."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    """Idempotency guard — true if column already on table.
    Same pattern as phase1_08b._column_exists for partial-fail re-run."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) Drop PR1 placeholder columns + table (empty, 0 prod rows)
    # ------------------------------------------------------------------
    if _column_exists("admission_profile", "high_school_id"):
        # FK constraint on this column → SQLAlchemy auto-drops FK with column
        op.drop_column("admission_profile", "high_school_id")
    if _column_exists("admission_profile", "high_school_kv_resolved"):
        op.drop_column("admission_profile", "high_school_kv_resolved")
    if _column_exists("admission_profile", "area_resolution_reason"):
        # Canonical reason now lives in priority_resolution_snapshot.manual_override_reason
        op.drop_column("admission_profile", "area_resolution_reason")

    if _table_exists("vn_high_school"):
        # Drop indexes first (created by phase1_08b)
        op.drop_index("ix_vn_high_school_location_active", table_name="vn_high_school")
        op.drop_index("ix_vn_high_school_name", table_name="vn_high_school")
        op.drop_table("vn_high_school")

    # ------------------------------------------------------------------
    # 2) vn_school — master directory (THCS + THPT + liên cấp + OTHER)
    # ------------------------------------------------------------------
    if not _table_exists("vn_school"):
        op.create_table(
            "vn_school",
            sa.Column("id", sa.BigInteger, primary_key=True),
            sa.Column(
                "moet_school_code",
                sa.String(10),
                nullable=False,
                comment="MOET school code (per Bộ GD-ĐT Apr 2025 directory)",
            ),
            sa.Column(
                "moet_province_code",
                sa.String(3),
                nullable=False,
                comment="MOET province code — composite unique với moet_school_code",
            ),
            sa.Column("moet_district_code", sa.String(5), nullable=True),
            sa.Column(
                "name",
                sa.String(255),
                nullable=False,
                comment="Canonical current name; historical via vn_school_name_history",
            ),
            sa.Column("address", sa.Text, nullable=True),
            sa.Column("province", sa.String(100), nullable=False),
            sa.Column("district", sa.String(100), nullable=True),
            sa.Column("ward", sa.String(100), nullable=True),
            sa.Column(
                "level",
                sa.String(20),
                nullable=False,
                comment=(
                    "THCS | THPT | THCS_THPT (liên cấp 2-3) | "
                    "TRUNG_HOC_NGHE (dự thảo TT 2026) | OTHER"
                ),
            ),
            sa.Column(
                "is_dtnt",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("false"),
                comment="Trường PT Dân tộc Nội trú — flag for special case bypass",
            ),
            sa.Column(
                "is_active",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("true"),
                comment=(
                    "Soft-delete flag. Admin 'xoá' = is_active=false; "
                    "FK from admission_profile uses RESTRICT to preserve audit."
                ),
            ),
            sa.Column(
                "merged_into_id",
                sa.BigInteger,
                sa.ForeignKey("vn_school.id"),
                nullable=True,
                comment="If school merged, points to surviving school. KV lookup vẫn theo school_id gốc + năm gốc.",
            ),
            sa.Column("merge_effective_date", sa.Date, nullable=True),
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
                "level IN ('THCS', 'THPT', 'THCS_THPT', 'TRUNG_HOC_NGHE', 'OTHER')",
                name="ck_vn_school_level",
            ),
        )
        # Composite unique per active row — handles "same MOET code but
        # school inactive after sát nhập" by partial UNIQUE.
        op.create_index(
            "uq_vn_school_moet_code_active",
            "vn_school",
            ["moet_province_code", "moet_school_code"],
            unique=True,
            postgresql_where=sa.text("is_active = true"),
        )
        op.create_index(
            "ix_vn_school_name",
            "vn_school",
            ["name"],
        )
        op.create_index(
            "ix_vn_school_location",
            "vn_school",
            ["province", "district"],
            postgresql_where=sa.text("is_active = true"),
        )
        op.create_index(
            "ix_vn_school_level_active",
            "vn_school",
            ["level"],
            postgresql_where=sa.text("is_active = true"),
        )

    # ------------------------------------------------------------------
    # 3) vn_school_name_history — slowly-changing name tracking
    # ------------------------------------------------------------------
    if not _table_exists("vn_school_name_history"):
        op.create_table(
            "vn_school_name_history",
            sa.Column("id", sa.BigInteger, primary_key=True),
            sa.Column(
                "school_id",
                sa.BigInteger,
                sa.ForeignKey("vn_school.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("effective_from", sa.Date, nullable=False),
            sa.Column("effective_to", sa.Date, nullable=True),
            sa.Column(
                "notes",
                sa.Text,
                nullable=True,
                comment="vd 'Sát nhập với Trường X' hoặc 'Đổi tên theo QĐ Y'",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "school_id", "effective_from",
                name="uq_vn_school_name_history_school_effective",
            ),
        )
        op.create_index(
            "ix_vn_school_name_history_lookup",
            "vn_school_name_history",
            ["school_id", "effective_from"],
        )

    # ------------------------------------------------------------------
    # 4) vn_school_kv_assignment — KV theo năm (temporal)
    # ------------------------------------------------------------------
    if not _table_exists("vn_school_kv_assignment"):
        op.create_table(
            "vn_school_kv_assignment",
            sa.Column("id", sa.BigInteger, primary_key=True),
            sa.Column(
                "school_id",
                sa.BigInteger,
                sa.ForeignKey("vn_school.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "kv_code",
                sa.String(20),
                nullable=False,
                comment="KV1 / KV2-NT / KV2 / KV3 (hyphen canonical per TT 05/2021)",
            ),
            sa.Column(
                "effective_from_year",
                sa.Integer,
                nullable=False,
                comment="Năm bắt đầu hiệu lực, vd 2025 = năm học 2025-2026",
            ),
            sa.Column(
                "effective_to_year",
                sa.Integer,
                nullable=True,
                comment="Năm kết thúc (inclusive). NULL = ongoing.",
            ),
            sa.Column(
                "source",
                sa.String(50),
                nullable=False,
                comment="moet_2024 | moet_2025 | qd_861 | manual_admin | qd_ubnd_<tinh>",
            ),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column(
                "created_by",
                sa.Integer,
                sa.ForeignKey("user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "kv_code ~ '^KV[1-9](-NT)?$'",
                name="ck_vn_school_kv_assignment_kv_code_format",
            ),
            sa.CheckConstraint(
                "effective_to_year IS NULL OR effective_to_year >= effective_from_year",
                name="ck_vn_school_kv_assignment_year_range_valid",
            ),
            # M3 review fix: NO EXCLUDE GiST constraint. Overlap check at
            # service-layer (priority_service.add_kv_assignment) — simpler
            # ORM compat + test DB create_all friendly per memory
            # ``migration-predicate-safety``.
        )
        op.create_index(
            "ix_vn_school_kv_lookup",
            "vn_school_kv_assignment",
            ["school_id", "effective_from_year"],
            postgresql_using="btree",
        )

    # ------------------------------------------------------------------
    # 5) admission_profile — Trình độ văn hóa + Trình độ chuyên môn (v1.3)
    # 2-field parallel design per VN admission convention (Luật GDNN +
    # TT 05/2021 Điều 4). Drives KV basis derivation matrix.
    # ------------------------------------------------------------------
    if not _column_exists("admission_profile", "cultural_education_level"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "cultural_education_level",
                sa.String(30),
                nullable=True,
                comment=(
                    "Trình độ văn hóa (phổ thông): completed_thcs | "
                    "graduated_thcs | completed_thpt | graduated_thpt | "
                    "graduated_gdtx. Nullable cho draft state — candidate "
                    "có thể chưa khai. Required tại submit T1."
                ),
            ),
        )
        # CHECK constraint enforce enum at DB layer
        op.create_check_constraint(
            "ck_admission_profile_cultural_education_level",
            "admission_profile",
            (
                "cultural_education_level IS NULL OR "
                "cultural_education_level IN ("
                "'completed_thcs', 'graduated_thcs', "
                "'completed_thpt', 'graduated_thpt', 'graduated_gdtx'"
                ")"
            ),
        )

    if not _column_exists("admission_profile", "vocational_qualification"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "vocational_qualification",
                sa.String(30),
                nullable=False,
                server_default=sa.text("'none'"),
                comment=(
                    "Trình độ chuyên môn (nghề nghiệp): none | so_cap | "
                    "trung_cap | cao_dang. NOT NULL DEFAULT 'none' — auto "
                    "fill cho legacy 315 + new profiles."
                ),
            ),
        )
        op.create_check_constraint(
            "ck_admission_profile_vocational_qualification",
            "admission_profile",
            (
                "vocational_qualification IN ("
                "'none', 'so_cap', 'trung_cap', 'cao_dang'"
                ")"
            ),
        )

    # ------------------------------------------------------------------
    # 6) admission_profile.priority_resolution_snapshot — NEW JSONB
    # ------------------------------------------------------------------
    if not _column_exists("admission_profile", "priority_resolution_snapshot"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "priority_resolution_snapshot",
                JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment=(
                    "Frozen KV resolution at submit T1 + re-frozen at engine T6 "
                    "(Q-P3-11 pattern). Shape: {kv_resolved, rule_applied, "
                    "pathway, breakdown, frozen_at, frozen_at_status, "
                    "manual_override_reason}. Empty dict {} = not resolved yet "
                    "(draft state — service computes real-time)."
                ),
            ),
        )


def downgrade() -> None:
    """Reverse — drop new schema + restore PR1 placeholder columns.

    Note: cannot restore PR1 vn_high_school content (was empty), so we
    just recreate the empty table shape for chain compatibility. Same for
    the 3 admission_profile columns — they were empty in prod when
    phase1_09 ran.
    """
    # 1) Drop snapshot column + 2 cultural/vocational columns (v1.3)
    if _column_exists("admission_profile", "priority_resolution_snapshot"):
        op.drop_column("admission_profile", "priority_resolution_snapshot")

    if _column_exists("admission_profile", "vocational_qualification"):
        op.drop_constraint(
            "ck_admission_profile_vocational_qualification",
            "admission_profile",
            type_="check",
        )
        op.drop_column("admission_profile", "vocational_qualification")

    if _column_exists("admission_profile", "cultural_education_level"):
        op.drop_constraint(
            "ck_admission_profile_cultural_education_level",
            "admission_profile",
            type_="check",
        )
        op.drop_column("admission_profile", "cultural_education_level")

    # 2) Drop new tables in reverse FK order
    if _table_exists("vn_school_kv_assignment"):
        op.drop_index("ix_vn_school_kv_lookup", table_name="vn_school_kv_assignment")
        op.drop_table("vn_school_kv_assignment")

    if _table_exists("vn_school_name_history"):
        op.drop_index(
            "ix_vn_school_name_history_lookup",
            table_name="vn_school_name_history",
        )
        op.drop_table("vn_school_name_history")

    if _table_exists("vn_school"):
        op.drop_index("ix_vn_school_level_active", table_name="vn_school")
        op.drop_index("ix_vn_school_location", table_name="vn_school")
        op.drop_index("ix_vn_school_name", table_name="vn_school")
        op.drop_index("uq_vn_school_moet_code_active", table_name="vn_school")
        op.drop_table("vn_school")

    # 3) Restore PR1 columns (empty shape for chain compat)
    if not _column_exists("admission_profile", "area_resolution_reason"):
        op.add_column(
            "admission_profile",
            sa.Column("area_resolution_reason", sa.Text, nullable=True),
        )

    # 4) Restore PR1 vn_high_school placeholder table
    if not _table_exists("vn_high_school"):
        op.create_table(
            "vn_high_school",
            sa.Column("id", sa.BigInteger, primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("province", sa.String(100), nullable=True),
            sa.Column("district", sa.String(100), nullable=True),
            sa.Column("ward", sa.String(100), nullable=True),
            sa.Column("kv_code", sa.String(20), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("true"),
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
        op.create_index("ix_vn_high_school_name", "vn_high_school", ["name"])
        op.create_index(
            "ix_vn_high_school_location_active",
            "vn_high_school",
            ["province", "district"],
            postgresql_where=sa.text("is_active = true"),
        )

    if not _column_exists("admission_profile", "high_school_id"):
        op.add_column(
            "admission_profile",
            sa.Column(
                "high_school_id",
                sa.BigInteger,
                sa.ForeignKey("vn_high_school.id", ondelete="RESTRICT"),
                nullable=True,
            ),
        )
    if not _column_exists("admission_profile", "high_school_kv_resolved"):
        op.add_column(
            "admission_profile",
            sa.Column("high_school_kv_resolved", sa.String(20), nullable=True),
        )
