"""Remove JSONB columns (admission_scores, documents_checklist) from admission_profile

Revision ID: p9a1b2c3d4e5
Revises: p8a1b2c3d4e5
Create Date: 2026-01-07

Per JSONB_TO_RELATIONAL_MIGRATION_PLAN.md:
- Remove admission_scores JSONB column (replaced by ProfileSubjectScore table)
- Remove documents_checklist JSONB column (replaced by ProfileDocument table)

Safety:
- Includes verification step to ensure relational data exists
- Rollback: Re-adds columns and rebuilds JSONB from relational tables

Related Tables:
- profile_subject_score (already exists)
- profile_document (already exists)
- config_document_type (already exists)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'p9a1b2c3d4e5'
down_revision: Union[str, None] = 'p8a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Remove JSONB columns from admission_profile table.

    Safety check: Verify ProfileDocument records exist for all profiles
    with documents_checklist data before dropping columns.
    """
    # Get database connection for verification
    conn = op.get_bind()

    # SAFETY CHECK 1: Verify ProfileDocument data exists for profiles with JSONB checklist
    orphan_profiles_docs = conn.execute(sa.text("""
        SELECT ap.id, ap.lead_id
        FROM admission_profile ap
        WHERE ap.documents_checklist IS NOT NULL
          AND jsonb_array_length(ap.documents_checklist) > 0
          AND NOT EXISTS (
              SELECT 1 FROM profile_document pd WHERE pd.profile_id = ap.id
          )
    """)).fetchall()

    if orphan_profiles_docs:
        profile_ids = [row[0] for row in orphan_profiles_docs]
        raise Exception(
            f"MIGRATION SAFETY ERROR: Found {len(orphan_profiles_docs)} profiles with "
            f"documents_checklist data but no ProfileDocument records! "
            f"Profile IDs: {profile_ids[:10]}... "
            f"Please run data migration script first."
        )

    # SAFETY CHECK 2: Log statistics before migration
    stats = conn.execute(sa.text("""
        SELECT
            COUNT(*) as total_profiles,
            COUNT(admission_scores) as profiles_with_scores,
            COUNT(documents_checklist) as profiles_with_docs
        FROM admission_profile
    """)).fetchone()

    print(f"📊 Migration Statistics:")
    print(f"   Total profiles: {stats[0]}")
    print(f"   Profiles with admission_scores: {stats[1]}")
    print(f"   Profiles with documents_checklist: {stats[2]}")

    # Step 1: Drop admission_scores JSONB column
    print("🗑️  Dropping admission_scores JSONB column...")
    op.drop_column('admission_profile', 'admission_scores')

    # Step 2: Drop documents_checklist JSONB column
    print("🗑️  Dropping documents_checklist JSONB column...")
    op.drop_column('admission_profile', 'documents_checklist')

    print("✅ JSONB columns removed successfully. Data preserved in relational tables:")
    print("   - admission_scores → profile_subject_score")
    print("   - documents_checklist → profile_document")


def downgrade() -> None:
    """
    Rollback: Re-add JSONB columns and rebuild data from relational tables.

    This allows safe rollback if issues are discovered after deployment.
    """
    # Step 1: Re-add admission_scores column
    print("🔄 Re-adding admission_scores JSONB column...")
    op.add_column('admission_profile',
        sa.Column('admission_scores', JSONB, nullable=True)
    )

    # Step 2: Re-add documents_checklist column
    print("🔄 Re-adding documents_checklist JSONB column...")
    op.add_column('admission_profile',
        sa.Column('documents_checklist', JSONB, nullable=True)
    )

    # Step 3: Rebuild admission_scores JSONB from profile_subject_score table
    print("🔄 Rebuilding admission_scores from profile_subject_score...")
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE admission_profile ap
        SET admission_scores = (
            SELECT jsonb_build_object(
                'subject_scores', jsonb_object_agg(s.code, pss.score)
            )
            FROM profile_subject_score pss
            JOIN subject s ON s.id = pss.subject_id
            WHERE pss.profile_id = ap.id
        )
        WHERE EXISTS (
            SELECT 1 FROM profile_subject_score pss WHERE pss.profile_id = ap.id
        )
    """))

    # Step 4: Rebuild documents_checklist JSONB from profile_document table
    print("🔄 Rebuilding documents_checklist from profile_document...")
    conn.execute(sa.text("""
        UPDATE admission_profile ap
        SET documents_checklist = (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'code', cdt.code,
                    'label', cdt.name,
                    'status', pd.status,
                    'file_path', pd.file_path,
                    'uploaded_at', to_char(pd.uploaded_at, 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
                )
                ORDER BY cdt.display_order
            )
            FROM profile_document pd
            JOIN config_document_type cdt ON cdt.id = pd.document_type_id
            WHERE pd.profile_id = ap.id
        )
        WHERE EXISTS (
            SELECT 1 FROM profile_document pd WHERE pd.profile_id = ap.id
        )
    """))

    # Step 5: Log rollback statistics
    stats = conn.execute(sa.text("""
        SELECT
            COUNT(*) as total_profiles,
            COUNT(admission_scores) as profiles_with_scores,
            COUNT(documents_checklist) as profiles_with_docs
        FROM admission_profile
    """)).fetchone()

    print(f"✅ JSONB columns restored successfully:")
    print(f"   Total profiles: {stats[0]}")
    print(f"   Profiles with admission_scores: {stats[1]}")
    print(f"   Profiles with documents_checklist: {stats[2]}")
