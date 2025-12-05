"""add admission_profile and student tables

Revision ID: a4b5c6d7e8f9
Revises: j6k7l8m9n0o1
Create Date: 2025-12-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'j6k7l8m9n0o1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== STEP 1: Add admission_rules column to program_offering ==========
    op.add_column(
        'program_offering',
        sa.Column(
            'admission_rules',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Admission rules JSON: {min_gpa, mandatory_docs[], admission_method}'
        )
    )

    # ========== STEP 2: Create admission_profile table ==========
    op.create_table(
        'admission_profile',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'lead_id',
            sa.Integer(),
            nullable=False,
            comment='Link to Lead (IDOR check point: lead.unit_id)'
        ),
        sa.Column(
            'citizen_id',
            sa.String(length=12),
            nullable=True,
            comment='CCCD/CMND number (12 digits)'
        ),
        sa.Column(
            'status',
            sa.String(length=20),
            nullable=False,
            server_default='draft',
            comment='State: draft | approved | rejected | enrolled'
        ),
        sa.Column(
            'applied_rules',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment='Snapshot of admission rules: {min_gpa, mandatory_docs[], admission_method}'
        ),
        sa.Column(
            'family_info',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Array of family members'
        ),
        sa.Column(
            'academic_history',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Array of academic records (schools attended)'
        ),
        sa.Column(
            'admission_scores',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Scores for admission evaluation'
        ),
        sa.Column(
            'documents_checklist',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Array of required documents with upload status'
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment='Profile creation time (UTC)'
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment='Last update time (UTC)'
        ),
        sa.ForeignKeyConstraint(
            ['lead_id'],
            ['lead.id'],
            name='fk_admission_profile_lead_id',
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lead_id', name='uq_admission_profile_lead_id'),
        sa.UniqueConstraint('citizen_id', name='uq_admission_profile_citizen_id')
    )

    # Create indexes for admission_profile
    op.create_index(
        'ix_admission_profile_id',
        'admission_profile',
        ['id'],
        unique=False
    )
    op.create_index(
        'ix_admission_profile_lead_id',
        'admission_profile',
        ['lead_id'],
        unique=True
    )
    op.create_index(
        'ix_admission_profile_citizen_id',
        'admission_profile',
        ['citizen_id'],
        unique=True
    )
    op.create_index(
        'ix_admission_profile_status',
        'admission_profile',
        ['status'],
        unique=False
    )

    # ========== STEP 3: Create student table ==========
    op.create_table(
        'student',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'admission_profile_id',
            sa.Integer(),
            nullable=False,
            comment='Link to AdmissionProfile'
        ),
        sa.Column(
            'student_code',
            sa.String(length=20),
            nullable=False,
            comment='Student code (SV + year + 4-digit random)'
        ),
        sa.Column(
            'enrollment_date',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment='Official enrollment date (UTC)'
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment='Record creation time (UTC)'
        ),
        sa.ForeignKeyConstraint(
            ['admission_profile_id'],
            ['admission_profile.id'],
            name='fk_student_admission_profile_id',
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('admission_profile_id', name='uq_student_admission_profile_id'),
        sa.UniqueConstraint('student_code', name='uq_student_student_code')
    )

    # Create indexes for student
    op.create_index(
        'ix_student_id',
        'student',
        ['id'],
        unique=False
    )
    op.create_index(
        'ix_student_admission_profile_id',
        'student',
        ['admission_profile_id'],
        unique=True
    )
    op.create_index(
        'ix_student_student_code',
        'student',
        ['student_code'],
        unique=True
    )

    # ========== STEP 4: Create student_document table ==========
    op.create_table(
        'student_document',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'student_id',
            sa.Integer(),
            nullable=False,
            comment='Link to Student'
        ),
        sa.Column(
            'doc_type',
            sa.String(length=50),
            nullable=False,
            comment='Document code (HOC_BA, CCCD, BANG_TN, etc.)'
        ),
        sa.Column(
            'file_path',
            sa.String(length=512),
            nullable=False,
            comment='S3 path or local file path'
        ),
        sa.Column(
            'is_verified',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Verification status (True = verified, False = pending/rejected)'
        ),
        sa.Column(
            'reviewer_note',
            sa.Text(),
            nullable=True,
            comment='Officer notes (especially for rejected documents)'
        ),
        sa.Column(
            'uploaded_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment='Upload time (copied from documents_checklist)'
        ),
        sa.Column(
            'verified_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Verification time (when officer marks is_verified)'
        ),
        sa.ForeignKeyConstraint(
            ['student_id'],
            ['student.id'],
            name='fk_student_document_student_id',
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for student_document
    op.create_index(
        'ix_student_document_id',
        'student_document',
        ['id'],
        unique=False
    )
    op.create_index(
        'ix_student_document_student_id',
        'student_document',
        ['student_id'],
        unique=False
    )
    op.create_index(
        'ix_student_document_is_verified',
        'student_document',
        ['is_verified'],
        unique=False
    )

    # ========== STEP 5: Add admission_profile relationship to Lead (handled by SQLAlchemy) ==========
    # No ALTER TABLE needed - relationship is defined in models via foreign key on admission_profile.lead_id


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign key dependencies)
    op.drop_index('ix_student_document_is_verified', table_name='student_document')
    op.drop_index('ix_student_document_student_id', table_name='student_document')
    op.drop_index('ix_student_document_id', table_name='student_document')
    op.drop_table('student_document')

    op.drop_index('ix_student_student_code', table_name='student')
    op.drop_index('ix_student_admission_profile_id', table_name='student')
    op.drop_index('ix_student_id', table_name='student')
    op.drop_table('student')

    op.drop_index('ix_admission_profile_status', table_name='admission_profile')
    op.drop_index('ix_admission_profile_citizen_id', table_name='admission_profile')
    op.drop_index('ix_admission_profile_lead_id', table_name='admission_profile')
    op.drop_index('ix_admission_profile_id', table_name='admission_profile')
    op.drop_table('admission_profile')

    op.drop_column('program_offering', 'admission_rules')
