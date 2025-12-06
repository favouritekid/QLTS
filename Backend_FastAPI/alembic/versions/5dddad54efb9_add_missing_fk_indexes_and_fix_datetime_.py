"""Add missing FK indexes and fix DateTime timezone

Revision ID: 5dddad54efb9
Revises: c6d7e8f9a0b1
Create Date: 2025-12-06 01:13:06.214646

This migration adds missing indexes to Foreign Key columns and fixes
DateTime columns to be timezone-aware in tuition_discount_policy table.

Changes:
1. DateTime timezone fix: tuition_discount_policy.created_at, updated_at
2. FK indexes (18 total):
   - HIGH priority: user.unit_id, lead.unit_id, major_program.unit_id, program_offering.program_id
   - MEDIUM priority: consultation.officer_id, consultation.consultation_status_id,
                      application.officer_id, crm_interaction.lead_id,
                      assignment_log.lead_id, assignment_log.officer_id
   - LOW priority: lead_history.*, notification_template.created_by,
                   tuition_discount_policy.created_by_user_id, updated_by_user_id,
                   user_unit_assignment.assigned_by_user_id

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5dddad54efb9'
down_revision: Union[str, Sequence[str], None] = 'c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==========================================================================
    # 1. FIX DATETIME TIMEZONE (Critical)
    # ==========================================================================
    # Convert naive datetime to timezone-aware in PostgreSQL
    op.alter_column(
        'tuition_discount_policy',
        'created_at',
        type_=sa.DateTime(timezone=True),
        postgresql_using='created_at AT TIME ZONE \'UTC\''
    )
    op.alter_column(
        'tuition_discount_policy',
        'updated_at',
        type_=sa.DateTime(timezone=True),
        postgresql_using='updated_at AT TIME ZONE \'UTC\''
    )

    # ==========================================================================
    # 2. ADD FK INDEXES - HIGH PRIORITY
    # ==========================================================================
    op.create_index('ix_user_unit_id', 'user', ['unit_id'])
    op.create_index('ix_lead_unit_id', 'lead', ['unit_id'])
    op.create_index('ix_major_program_unit_id', 'major_program', ['unit_id'])
    op.create_index('ix_program_offering_program_id', 'program_offering', ['program_id'])

    # ==========================================================================
    # 3. ADD FK INDEXES - MEDIUM PRIORITY (Lead-related tables)
    # ==========================================================================
    op.create_index('ix_consultation_officer_id', 'consultation', ['officer_id'])
    op.create_index('ix_consultation_consultation_status_id', 'consultation', ['consultation_status_id'])
    op.create_index('ix_application_officer_id', 'application', ['officer_id'])
    op.create_index('ix_crm_interaction_lead_id', 'crm_interaction', ['lead_id'])
    op.create_index('ix_assignment_log_lead_id', 'assignment_log', ['lead_id'])
    op.create_index('ix_assignment_log_officer_id', 'assignment_log', ['officer_id'])

    # ==========================================================================
    # 4. ADD FK INDEXES - LOW PRIORITY (History/Audit tables)
    # ==========================================================================
    # lead_status_history
    op.create_index('ix_lead_status_history_changed_by_user_id', 'lead_status_history', ['changed_by_user_id'])
    op.create_index('ix_lead_status_history_old_consultation_status_id', 'lead_status_history', ['old_consultation_status_id'])
    op.create_index('ix_lead_status_history_new_consultation_status_id', 'lead_status_history', ['new_consultation_status_id'])
    op.create_index('ix_lead_status_history_old_pipeline_stage_id', 'lead_status_history', ['old_pipeline_stage_id'])
    op.create_index('ix_lead_status_history_new_pipeline_stage_id', 'lead_status_history', ['new_pipeline_stage_id'])
    op.create_index('ix_lead_status_history_old_assigned_officer_id', 'lead_status_history', ['old_assigned_officer_id'])
    op.create_index('ix_lead_status_history_new_assigned_officer_id', 'lead_status_history', ['new_assigned_officer_id'])

    # notification_template
    op.create_index('ix_notification_template_created_by', 'notification_template', ['created_by'])

    # tuition_discount_policy
    op.create_index('ix_tuition_discount_policy_created_by_user_id', 'tuition_discount_policy', ['created_by_user_id'])
    op.create_index('ix_tuition_discount_policy_updated_by_user_id', 'tuition_discount_policy', ['updated_by_user_id'])

    # user_unit_assignment
    op.create_index('ix_user_unit_assignment_assigned_by_user_id', 'user_unit_assignment', ['assigned_by_user_id'])


def downgrade() -> None:
    # ==========================================================================
    # REMOVE INDEXES (Reverse order)
    # ==========================================================================
    # user_unit_assignment
    op.drop_index('ix_user_unit_assignment_assigned_by_user_id', 'user_unit_assignment')

    # tuition_discount_policy
    op.drop_index('ix_tuition_discount_policy_updated_by_user_id', 'tuition_discount_policy')
    op.drop_index('ix_tuition_discount_policy_created_by_user_id', 'tuition_discount_policy')

    # notification_template
    op.drop_index('ix_notification_template_created_by', 'notification_template')

    # lead_status_history
    op.drop_index('ix_lead_status_history_new_assigned_officer_id', 'lead_status_history')
    op.drop_index('ix_lead_status_history_old_assigned_officer_id', 'lead_status_history')
    op.drop_index('ix_lead_status_history_new_pipeline_stage_id', 'lead_status_history')
    op.drop_index('ix_lead_status_history_old_pipeline_stage_id', 'lead_status_history')
    op.drop_index('ix_lead_status_history_new_consultation_status_id', 'lead_status_history')
    op.drop_index('ix_lead_status_history_old_consultation_status_id', 'lead_status_history')
    op.drop_index('ix_lead_status_history_changed_by_user_id', 'lead_status_history')

    # MEDIUM priority
    op.drop_index('ix_assignment_log_officer_id', 'assignment_log')
    op.drop_index('ix_assignment_log_lead_id', 'assignment_log')
    op.drop_index('ix_crm_interaction_lead_id', 'crm_interaction')
    op.drop_index('ix_application_officer_id', 'application')
    op.drop_index('ix_consultation_consultation_status_id', 'consultation')
    op.drop_index('ix_consultation_officer_id', 'consultation')

    # HIGH priority
    op.drop_index('ix_program_offering_program_id', 'program_offering')
    op.drop_index('ix_major_program_unit_id', 'major_program')
    op.drop_index('ix_lead_unit_id', 'lead')
    op.drop_index('ix_user_unit_id', 'user')

    # ==========================================================================
    # REVERT DATETIME TIMEZONE
    # ==========================================================================
    op.alter_column(
        'tuition_discount_policy',
        'created_at',
        type_=sa.DateTime(),
        postgresql_using='created_at AT TIME ZONE \'UTC\''
    )
    op.alter_column(
        'tuition_discount_policy',
        'updated_at',
        type_=sa.DateTime(),
        postgresql_using='updated_at AT TIME ZONE \'UTC\''
    )
