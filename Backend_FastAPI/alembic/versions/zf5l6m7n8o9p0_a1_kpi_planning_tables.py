"""A1: KPI Planning Tables

- Create tables: kpi_plan, kpi_plan_month, holiday_calendar, assignment_decision_log
- Seed holiday_calendar with VN holidays 2026
- Add FK: kpi_config.source_plan_id -> kpi_plan.id ON DELETE SET NULL
- Partial unique indexes for kpi_plan (unit plan / officer plan)

Revision ID: zf5l6m7n8o9p0
Revises: ze4k5l6m7n8o9
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

# revision identifiers
revision = "zf5l6m7n8o9p0"
down_revision = "ze4k5l6m7n8o9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. kpi_plan — Reverse-funnel planning per unit/officer per year
    # =========================================================================
    op.create_table(
        "kpi_plan",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("organization_unit.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("officer_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("annual_enrollment_target", sa.Integer(), nullable=False),
        sa.Column("sla_target", sa.Numeric(5, 2), nullable=False, server_default="85.00"),
        sa.Column("response_time_target", sa.Numeric(5, 2), nullable=False, server_default="2.00"),
        sa.Column("seasonal_weights", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        comment="KPI planning — reverse-funnel from annual target to 7 monthly KPIs + 1 annual KPI",
    )

    # Partial unique indexes for kpi_plan (NULL != NULL in PG)
    op.create_index(
        "uix_kpi_plan_active_unit",
        "kpi_plan",
        ["unit_id", "fiscal_year"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND officer_id IS NULL"),
    )
    op.create_index(
        "uix_kpi_plan_active_officer",
        "kpi_plan",
        ["unit_id", "officer_id", "fiscal_year"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND officer_id IS NOT NULL"),
    )

    # =========================================================================
    # 2. kpi_plan_month — Monthly breakdown with derived targets and actuals
    # =========================================================================
    op.create_table(
        "kpi_plan_month",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("kpi_plan.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("month", sa.Integer(), nullable=False),
        # Distributable inputs
        sa.Column("enrollment_target", sa.Integer(), nullable=False),
        sa.Column("working_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight", sa.Numeric(6, 4), nullable=False),
        # Historical factors
        sa.Column("k_factor", sa.Numeric(6, 2), nullable=False, server_default="7.00"),
        sa.Column("lead_forecast", sa.Integer(), nullable=True),
        sa.Column("close_forecast", sa.Integer(), nullable=True),
        # Derived KPI targets (nullable — NULL when not computable)
        sa.Column("consultations_daily", sa.Integer(), nullable=True),
        sa.Column("conversion_rate", sa.Numeric(6, 2), nullable=True),
        sa.Column("win_rate", sa.Numeric(6, 2), nullable=True),
        sa.Column("consultation_effectiveness", sa.Numeric(6, 2), nullable=True),
        # Per-field override tracking
        sa.Column("overridden_fields", JSONB, nullable=False, server_default="{}"),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("overridden_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
        # Actuals (filled by sync job at month end)
        sa.Column("actual_enrollments", sa.Integer(), nullable=True),
        sa.Column("actual_consultations_avg", sa.Numeric(6, 2), nullable=True),
        sa.Column("actual_conversion_rate", sa.Numeric(6, 2), nullable=True),
        sa.Column("actual_win_rate", sa.Numeric(6, 2), nullable=True),
        sa.Column("actual_consultation_effectiveness", sa.Numeric(6, 2), nullable=True),
        sa.Column("actual_sla_compliance_rate", sa.Numeric(6, 2), nullable=True),
        # Audit
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Constraints
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_kpi_plan_month_range"),
        sa.UniqueConstraint("plan_id", "month", name="uq_kpi_plan_month_plan_month"),
        comment="Monthly breakdown of KPI plan with derived targets and actuals",
    )

    # =========================================================================
    # 3. holiday_calendar — VN holidays for working days calculation
    # =========================================================================
    op.create_table(
        "holiday_calendar",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False, index=True),
        sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        comment="Holiday calendar for working days calculation (T2-T7 minus holidays)",
    )

    # Seed VN holidays 2026
    op.execute("""
        INSERT INTO holiday_calendar (date, name, year, is_recurring) VALUES
        ('2026-01-01', 'Tết Dương lịch', 2026, TRUE),
        ('2026-01-28', 'Tết Nguyên Đán (28 Tết)', 2026, FALSE),
        ('2026-01-29', 'Tết Nguyên Đán (29 Tết)', 2026, FALSE),
        ('2026-01-30', 'Tết Nguyên Đán (30 Tết)', 2026, FALSE),
        ('2026-01-31', 'Tết Nguyên Đán (Mùng 1)', 2026, FALSE),
        ('2026-02-01', 'Tết Nguyên Đán (Mùng 2)', 2026, FALSE),
        ('2026-02-02', 'Tết Nguyên Đán (Mùng 3)', 2026, FALSE),
        ('2026-04-30', 'Ngày Giải phóng', 2026, TRUE),
        ('2026-05-01', 'Ngày Quốc tế Lao động', 2026, TRUE),
        ('2026-09-02', 'Ngày Quốc khánh', 2026, TRUE),
        ('2026-09-03', 'Nghỉ bù Quốc khánh', 2026, FALSE),
        ('2026-04-07', 'Giỗ Tổ Hùng Vương', 2026, FALSE)
        ON CONFLICT (date) DO NOTHING
    """)

    # =========================================================================
    # 4. assignment_decision_log — Instrumentation for fairness v2.1
    # =========================================================================
    op.create_table(
        "assignment_decision_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("lead.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("assigned_officer_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True, index=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column("eligible_officer_ids", ARRAY(sa.Integer()), nullable=False),
        sa.Column("channel", sa.String(50), nullable=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("organization_unit.id"), nullable=True),
        sa.Column("scores_snapshot", JSONB, nullable=True),
        sa.Column("capacity_snapshot", JSONB, nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        comment="Assignment decision log for fairness analysis (v2.1 prep)",
    )

    # =========================================================================
    # 5. Add FK: kpi_config.source_plan_id -> kpi_plan.id
    # =========================================================================
    op.create_foreign_key(
        "fk_kpi_config_source_plan",
        "kpi_config",
        "kpi_plan",
        ["source_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Drop FK
    op.drop_constraint("fk_kpi_config_source_plan", "kpi_config", type_="foreignkey")

    # Drop tables in reverse order
    op.drop_table("assignment_decision_log")
    op.drop_table("holiday_calendar")
    op.drop_table("kpi_plan_month")

    # Drop indexes before table
    op.drop_index("uix_kpi_plan_active_officer", table_name="kpi_plan", if_exists=True)
    op.drop_index("uix_kpi_plan_active_unit", table_name="kpi_plan", if_exists=True)
    op.drop_table("kpi_plan")
