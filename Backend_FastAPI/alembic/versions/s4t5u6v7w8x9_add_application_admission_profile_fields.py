"""add application admission profile fields

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2025-11-17 10:00:00.000000

This migration adds new fields to the Application table to support the
"Hồ sơ Tuyển sinh" (Admission Profile) feature:

CHANGES:
1. Add major_program_id column (FK to major_program)
2. Add program_offering_id column (FK to program_offering)
3. Add criterion_id column (stores AdmissionCriterion.id from JSON)
4. Update status column default from 'submitted' to 'pending'
5. Make officer_id nullable (not required on creation)
6. Add created_at and updated_at timestamps
7. Add indexes for performance

FIELD DESCRIPTIONS:
- major_program_id: Links to MajorProgram (Tier 1) - Ngành đào tạo
- program_offering_id: Links to ProgramOffering (Tier 2) - Loại hình đào tạo
- criterion_id: ID of selected AdmissionCriterion from OfferingAcademicInfo.admission_criteria
- documents: JSON field for storing scores and checklist
- status: Application status (pending, missing_documents, completed, passed, failed)

ROLLBACK:
- Downgrade removes new columns and restores original structure
- Note: Data in new columns will be lost on downgrade
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 's4t5u6v7w8x9'
down_revision: Union[str, None] = 'r3s4t5u6v7w8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add admission profile fields to Application table.
    """

    print("\n" + "=" * 80)
    print("MIGRATION: Add Application Admission Profile Fields")
    print("=" * 80)

    # =========================================================================
    # STEP 1: Add new columns to application table
    # =========================================================================
    print("\n[STEP 1/4] Adding new columns to application table...")

    # Add major_program_id (FK to major_program)
    op.add_column(
        'application',
        sa.Column(
            'major_program_id',
            sa.Integer(),
            sa.ForeignKey('major_program.id', ondelete='SET NULL'),
            nullable=True,
            comment="FK to MajorProgram (Tier 1) - Ngành đào tạo"
        )
    )

    # Add program_offering_id (FK to program_offering)
    op.add_column(
        'application',
        sa.Column(
            'program_offering_id',
            sa.Integer(),
            sa.ForeignKey('program_offering.id', ondelete='SET NULL'),
            nullable=True,
            comment="FK to ProgramOffering (Tier 2) - Loại hình đào tạo"
        )
    )

    # Add criterion_id (string - stores AdmissionCriterion.id from JSON)
    op.add_column(
        'application',
        sa.Column(
            'criterion_id',
            sa.String(length=100),
            nullable=True,
            comment="ID of AdmissionCriterion from OfferingAcademicInfo.admission_criteria"
        )
    )

    # Add timestamps
    op.add_column(
        'application',
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment="Timestamp when application was created"
        )
    )

    op.add_column(
        'application',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment="Timestamp when application was last updated"
        )
    )

    print("   ✓ New columns added")

    # =========================================================================
    # STEP 2: Modify existing columns
    # =========================================================================
    print("\n[STEP 2/4] Modifying existing columns...")

    # Make officer_id nullable (not required on creation)
    op.alter_column(
        'application',
        'officer_id',
        existing_type=sa.Integer(),
        nullable=True,
        comment="Legacy field - officer who created the application"
    )

    # Update status column default and add comment
    # Note: We can't change default on existing column, so we'll add a comment
    op.alter_column(
        'application',
        'status',
        existing_type=sa.String(length=50),
        server_default='pending',  # Change from 'submitted' to 'pending'
        comment="Status: pending, missing_documents, completed, passed, failed"
    )

    # Add comment to documents column
    op.alter_column(
        'application',
        'documents',
        existing_type=postgresql.JSON(),
        comment='JSON: {scores: {subject: score}, checklist: [{code, label, status, submission_type, notes}]}'
    )

    print("   ✓ Existing columns modified")

    # =========================================================================
    # STEP 3: Create indexes for performance
    # =========================================================================
    print("\n[STEP 3/4] Creating indexes...")

    op.create_index(
        'ix_application_id',
        'application',
        ['id']
    )

    op.create_index(
        'ix_application_lead_id',
        'application',
        ['lead_id']
    )

    op.create_index(
        'ix_application_major_program_id',
        'application',
        ['major_program_id']
    )

    op.create_index(
        'ix_application_program_offering_id',
        'application',
        ['program_offering_id']
    )

    op.create_index(
        'ix_application_criterion_id',
        'application',
        ['criterion_id']
    )

    op.create_index(
        'ix_application_status',
        'application',
        ['status']
    )

    print("   ✓ Indexes created")

    # =========================================================================
    # STEP 4: Update existing data (if needed)
    # =========================================================================
    print("\n[STEP 4/4] Updating existing data...")

    # Update existing applications to have 'pending' status if they have 'submitted'
    op.execute(
        sa.text("UPDATE application SET status = 'pending' WHERE status = 'submitted'")
    )

    print("   ✓ Existing data updated")

    print("\n" + "=" * 80)
    print("MIGRATION COMPLETE: Application Admission Profile Fields Added")
    print("=" * 80 + "\n")


def downgrade() -> None:
    """
    Remove admission profile fields from Application table.

    WARNING: This will drop the new columns and their data!
    """

    print("\n" + "=" * 80)
    print("ROLLBACK: Removing Application Admission Profile Fields")
    print("=" * 80)

    # Drop indexes
    print("\n[STEP 1/3] Dropping indexes...")
    op.drop_index('ix_application_status', 'application')
    op.drop_index('ix_application_criterion_id', 'application')
    op.drop_index('ix_application_program_offering_id', 'application')
    op.drop_index('ix_application_major_program_id', 'application')
    op.drop_index('ix_application_lead_id', 'application')
    op.drop_index('ix_application_id', 'application')
    print("   ✓ Indexes dropped")

    # Restore officer_id to NOT NULL
    print("\n[STEP 2/3] Restoring officer_id to NOT NULL...")
    # Note: This might fail if there are NULL values
    # You may need to set a default officer_id before this step
    op.alter_column(
        'application',
        'officer_id',
        existing_type=sa.Integer(),
        nullable=False
    )

    # Restore status default
    op.alter_column(
        'application',
        'status',
        existing_type=sa.String(length=50),
        server_default='submitted'
    )
    print("   ✓ Columns restored")

    # Drop new columns
    print("\n[STEP 3/3] Dropping new columns...")
    op.drop_column('application', 'updated_at')
    op.drop_column('application', 'created_at')
    op.drop_column('application', 'criterion_id')
    op.drop_column('application', 'program_offering_id')
    op.drop_column('application', 'major_program_id')
    print("   ✓ New columns dropped")

    print("\n" + "=" * 80)
    print("ROLLBACK COMPLETE: Application table restored to original state")
    print("=" * 80 + "\n")
