"""A0: KPI Planning Foundation

- KpiConfig.target_value: INTEGER -> NUMERIC(12,2)
- KpiTarget/KpiConfig kpi_code renames: enrollments -> enrollments_annual, response_time -> response_time_hours
- KpiConfig: add effective_month, effective_year, source_plan_id columns
- Drop old unique indexes, create new partial unique + lookup indexes

Revision ID: ze4k5l6m7n8o9
Revises: zd3j4k5l6m7n8
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "ze4k5l6m7n8o9"
down_revision = "zd3j4k5l6m7n8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. KpiConfig.target_value: INTEGER -> NUMERIC(12,2)
    # =========================================================================
    op.alter_column(
        "kpi_config",
        "target_value",
        type_=sa.Numeric(12, 2),
        existing_type=sa.Integer(),
        existing_nullable=False,
        postgresql_using="target_value::numeric(12,2)",
    )

    # =========================================================================
    # 2. Rename legacy kpi_codes (data migration)
    # =========================================================================
    # KpiTarget: enrollments -> enrollments_annual
    op.execute(
        "UPDATE kpi_target SET kpi_code = 'enrollments_annual' "
        "WHERE kpi_code = 'enrollments'"
    )
    # KpiConfig: response_time -> response_time_hours
    op.execute(
        "UPDATE kpi_config SET kpi_code = 'response_time_hours' "
        "WHERE kpi_code = 'response_time'"
    )

    # =========================================================================
    # 3. Add new columns to kpi_config for temporal resolution
    # =========================================================================
    op.add_column(
        "kpi_config",
        sa.Column("effective_month", sa.Integer(), nullable=True,
                  comment="Month this target applies to (NULL = evergreen/legacy)"),
    )
    op.add_column(
        "kpi_config",
        sa.Column("effective_year", sa.Integer(), nullable=True,
                  comment="Year this target applies to (NULL = evergreen/legacy)"),
    )
    op.add_column(
        "kpi_config",
        sa.Column("source_plan_id", sa.Integer(), nullable=True,
                  comment="FK to kpi_plan (added in A1 migration after table creation)"),
    )

    # =========================================================================
    # 4. Drop old unique indexes that block multi-month records
    # =========================================================================
    # From original migration q1r2s3t4u5v6
    op.drop_index("uq_kpi_config_scope", table_name="kpi_config", if_exists=True)
    # From perf migration perf20260126001
    op.drop_index("ix_kpi_config_unique_combo", table_name="kpi_config", if_exists=True)

    # =========================================================================
    # 5. Create new partial unique indexes
    # =========================================================================
    # Evergreen records (legacy, effective_month IS NULL): 1 per scope
    op.create_index(
        "uq_kpi_config_scope_evergreen",
        "kpi_config",
        ["unit_id", "officer_id", "kpi_code", "period_type"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND effective_month IS NULL"),
    )
    # Monthly records (from planning sync): 1 per scope per month
    op.create_index(
        "uq_kpi_config_scope_monthly",
        "kpi_config",
        ["unit_id", "officer_id", "kpi_code", "period_type",
         "effective_year", "effective_month"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND effective_month IS NOT NULL"),
    )
    # Lookup index for get_kpi_target() performance
    op.create_index(
        "idx_kpi_config_effective_lookup",
        "kpi_config",
        ["kpi_code", "unit_id", "officer_id", "effective_year", "effective_month"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    # Drop new indexes
    op.drop_index("idx_kpi_config_effective_lookup", table_name="kpi_config", if_exists=True)
    op.drop_index("uq_kpi_config_scope_monthly", table_name="kpi_config", if_exists=True)
    op.drop_index("uq_kpi_config_scope_evergreen", table_name="kpi_config", if_exists=True)

    # Recreate old indexes
    op.create_index(
        "uq_kpi_config_scope",
        "kpi_config",
        ["unit_id", "officer_id", "kpi_code", "period_type"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index(
        "ix_kpi_config_unique_combo",
        "kpi_config",
        ["kpi_code", "unit_id", "officer_id", "period_type"],
        unique=True,
        postgresql_where=sa.text("(is_active = true)"),
    )

    # Drop new columns
    op.drop_column("kpi_config", "source_plan_id")
    op.drop_column("kpi_config", "effective_year")
    op.drop_column("kpi_config", "effective_month")

    # Reverse kpi_code renames
    op.execute(
        "UPDATE kpi_target SET kpi_code = 'enrollments' "
        "WHERE kpi_code = 'enrollments_annual'"
    )
    op.execute(
        "UPDATE kpi_config SET kpi_code = 'response_time' "
        "WHERE kpi_code = 'response_time_hours'"
    )

    # Revert target_value to INTEGER
    op.alter_column(
        "kpi_config",
        "target_value",
        type_=sa.Integer(),
        existing_type=sa.Numeric(12, 2),
        existing_nullable=False,
        postgresql_using="target_value::integer",
    )
