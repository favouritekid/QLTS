"""audit: CHECK constraints, dob date, student updated_at, server defaults

Revision ID: zn3t4u5v6w7x8
Revises: zm2s3t4u5v6w7
Create Date: 2026-03-15 12:00:00.000000

Consolidated migration for audit findings:
- 6 CHECK constraints (#28, #29, #30, #32, #46, #48)
- dob DateTime -> Date (#33)
- student.updated_at column (#45)
- admission_profile.status/version server defaults (#13)
- admission_path.application_fee server_default NULL (#47)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'zn3t4u5v6w7x8'
down_revision: Union[str, None] = 'zm2s3t4u5v6w7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # 1. CHECK CONSTRAINTS
    # =========================================================================

    # #28: admission_profile.status
    op.create_check_constraint(
        "ck_admission_profile_status",
        "admission_profile",
        "status IN ('draft','submitted','approved','rejected','confirmed','enrolled','resubmitted','overridden','revision_requested','withdrawn')"
    )

    # #46: admission_profile.confirmed_via
    op.create_check_constraint(
        "ck_admission_profile_confirmed_via",
        "admission_profile",
        "confirmed_via IN ('magic_link','admin_override','officer') OR confirmed_via IS NULL"
    )

    # #29: profile_document.status
    op.create_check_constraint(
        "ck_profile_document_status",
        "profile_document",
        "status IN ('missing','uploaded','verified','rejected','paper_submitted')"
    )

    # #32: profile_subject_score.score range
    op.create_check_constraint(
        "ck_profile_subject_score_range",
        "profile_subject_score",
        "score >= 0 AND score <= 10"
    )

    # #48: document_audit_log.action
    op.create_check_constraint(
        "ck_document_audit_log_action",
        "document_audit_log",
        "action IN ('uploaded','verified','rejected','reset','paper_submitted','deleted')"
    )

    # #30: admission_path.status
    op.create_check_constraint(
        "ck_admission_path_status",
        "admission_path",
        "status IN ('draft','active','inactive','archived')"
    )

    # =========================================================================
    # 2. DOB: DateTime -> Date (#33)
    # =========================================================================
    op.execute(
        "ALTER TABLE admission_profile "
        "ALTER COLUMN dob TYPE DATE USING dob::date"
    )

    # =========================================================================
    # 3. STUDENT: add updated_at column (#45)
    # =========================================================================
    op.add_column(
        'student',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment='Last update time (UTC)'
        )
    )

    # =========================================================================
    # 4. ADMISSION_PROFILE: Ensure server_default for status + version (#13)
    # These were set in original migrations, but re-apply for idempotency
    # =========================================================================
    op.alter_column(
        'admission_profile',
        'status',
        server_default=sa.text("'draft'"),
    )
    op.alter_column(
        'admission_profile',
        'version',
        server_default=sa.text("1"),
    )

    # =========================================================================
    # 5. ADMISSION_PATH: application_fee default NULL instead of 0 (#47)
    # =========================================================================
    op.alter_column(
        'admission_path',
        'application_fee',
        server_default=None,
    )


def downgrade() -> None:
    # 5. Restore application_fee default to '0'
    op.alter_column(
        'admission_path',
        'application_fee',
        server_default='0',
    )

    # 4. Server defaults - leave as-is on downgrade (they existed before this migration)

    # 3. Drop student.updated_at
    op.drop_column('student', 'updated_at')

    # 2. Revert dob back to DateTime
    op.execute(
        "ALTER TABLE admission_profile "
        "ALTER COLUMN dob TYPE TIMESTAMP WITHOUT TIME ZONE USING dob::timestamp"
    )

    # 1. Drop CHECK constraints (reverse order)
    op.drop_constraint("ck_admission_path_status", "admission_path", type_="check")
    op.drop_constraint("ck_document_audit_log_action", "document_audit_log", type_="check")
    op.drop_constraint("ck_profile_subject_score_range", "profile_subject_score", type_="check")
    op.drop_constraint("ck_profile_document_status", "profile_document", type_="check")
    op.drop_constraint("ck_admission_profile_confirmed_via", "admission_profile", type_="check")
    op.drop_constraint("ck_admission_profile_status", "admission_profile", type_="check")
