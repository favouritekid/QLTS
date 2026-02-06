"""Add composite indexes for common query patterns

Revision ID: perf20260126001
Revises: audit20260126001
Create Date: 2026-01-26

Purpose:
    Adds composite indexes to improve performance for common query patterns:
    - Lead filtering by officer, status, deleted
    - Consultation queries by lead_id and status
    - KPI config/target lookups
    - Login history security checks

Analysis Source: LEAD_ADMISSION_AUDIT_REPORT.md Issue #4
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'perf20260126001'
down_revision = 'audit20260126001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # LEAD TABLE INDEXES
    # =========================================================================

    # 1. Lead filtering by officer + status + deleted (Quick Disposition)
    # Query: get_filtered() with assigned_officer_id, status, deleted_at
    op.create_index(
        'ix_lead_officer_status_deleted_activity',
        'lead',
        ['assigned_officer_id', 'status', 'deleted_at', 'next_activity_at', 'created_at'],
        unique=False
    )

    # 2. Hot lead detection (Recommendation Engine)
    # Query: count_hot_leads_needing_attention()
    op.create_index(
        'ix_lead_officer_hot_deleted_lastconsult',
        'lead',
        ['assigned_officer_id', 'is_hot_lead', 'deleted_at', 'last_consultation_at'],
        unique=False
    )

    # 3. Stale lead detection
    # Query: get_stale_leads()
    op.create_index(
        'ix_lead_officer_deleted_updated',
        'lead',
        ['assigned_officer_id', 'deleted_at', 'updated_at'],
        unique=False
    )

    # 4. High score leads
    # Query: get_high_score_leads()
    op.create_index(
        'ix_lead_deleted_score',
        'lead',
        ['deleted_at', 'lead_score'],
        unique=False
    )

    # 5. Unit dashboard filtering
    # Query: get_filtered() with unit_id
    op.create_index(
        'ix_lead_unit_status_deleted',
        'lead',
        ['unit_id', 'status', 'deleted_at'],
        unique=False
    )

    # =========================================================================
    # CONSULTATION TABLE INDEXES
    # =========================================================================

    # 6. Next activity calculation (Critical - called frequently)
    # Query: update_next_activity(), get_consultation_aggregates()
    op.create_index(
        'ix_consultation_lead_status_deleted_scheduled',
        'consultation',
        ['lead_id', 'consultation_status_id', 'deleted_at', 'scheduled_at'],
        unique=False
    )

    # 7. Officer consultation count
    # Query: count_consultations_by_officers()
    op.create_index(
        'ix_consultation_officer_deleted',
        'consultation',
        ['officer_id', 'deleted_at'],
        unique=False
    )

    # =========================================================================
    # KPI_CONFIG TABLE INDEXES
    # =========================================================================

    # 8. KPI inheritance hierarchy lookup
    # Query: get_target_by_officer(), get_target_by_unit()
    op.create_index(
        'ix_kpi_config_officer_code_period_active',
        'kpi_config',
        ['officer_id', 'kpi_code', 'period_type', 'is_active'],
        unique=False
    )

    op.create_index(
        'ix_kpi_config_unit_code_period_active',
        'kpi_config',
        ['unit_id', 'kpi_code', 'period_type', 'is_active'],
        unique=False
    )

    # 9. KPI config duplicate check (Partial UNIQUE index - only active records)
    # Query: check_duplicate_exists()
    op.create_index(
        'ix_kpi_config_unique_combo',
        'kpi_config',
        ['kpi_code', 'unit_id', 'officer_id', 'period_type'],
        unique=True,
        postgresql_where=sa.text('(is_active = true)')
    )

    # =========================================================================
    # KPI_TARGET TABLE INDEXES
    # =========================================================================

    # 10. Annual target lookup
    # Query: get_annual_target_record()
    op.create_index(
        'ix_kpi_target_officer_code_year',
        'kpi_target',
        ['officer_id', 'kpi_code', 'fiscal_year'],
        unique=False
    )

    # 11. KPI target duplicate check (Partial UNIQUE index - only active records)
    # Query: check_duplicate_target_exists()
    op.create_index(
        'ix_kpi_target_unique_combo',
        'kpi_target',
        ['kpi_code', 'fiscal_year', 'unit_id', 'officer_id'],
        unique=True,
        postgresql_where=sa.text('(is_active = true)')
    )

    # =========================================================================
    # LOGIN_HISTORY TABLE INDEXES (Security)
    # =========================================================================

    # 12. Suspicious login detection
    # Query: get_suspicious_logins()
    op.create_index(
        'ix_login_history_user_response_loginat',
        'login_history',
        ['user_id', 'user_response', 'login_at'],
        unique=False
    )

    # 13. IP seen before check
    # Query: check_ip_seen_before()
    op.create_index(
        'ix_login_history_user_ip_response',
        'login_history',
        ['user_id', 'ip_address', 'user_response'],
        unique=False
    )

    # =========================================================================
    # ADMISSION_PROFILE TABLE INDEXES
    # =========================================================================

    # 14. Duplicate citizen check per academic year
    # Query: check_citizen_id_exists()
    op.create_index(
        'ix_admission_profile_citizen_year',
        'admission_profile',
        ['citizen_id', 'academic_year'],
        unique=False
    )


def downgrade() -> None:
    # Drop indexes in reverse order

    # Admission Profile
    op.drop_index('ix_admission_profile_citizen_year', table_name='admission_profile')

    # Login History
    op.drop_index('ix_login_history_user_ip_response', table_name='login_history')
    op.drop_index('ix_login_history_user_response_loginat', table_name='login_history')

    # KPI Target
    op.drop_index('ix_kpi_target_unique_combo', table_name='kpi_target')
    op.drop_index('ix_kpi_target_officer_code_year', table_name='kpi_target')

    # KPI Config
    op.drop_index('ix_kpi_config_unique_combo', table_name='kpi_config')
    op.drop_index('ix_kpi_config_unit_code_period_active', table_name='kpi_config')
    op.drop_index('ix_kpi_config_officer_code_period_active', table_name='kpi_config')

    # Consultation
    op.drop_index('ix_consultation_officer_deleted', table_name='consultation')
    op.drop_index('ix_consultation_lead_status_deleted_scheduled', table_name='consultation')

    # Lead
    op.drop_index('ix_lead_unit_status_deleted', table_name='lead')
    op.drop_index('ix_lead_deleted_score', table_name='lead')
    op.drop_index('ix_lead_officer_deleted_updated', table_name='lead')
    op.drop_index('ix_lead_officer_hot_deleted_lastconsult', table_name='lead')
    op.drop_index('ix_lead_officer_status_deleted_activity', table_name='lead')
