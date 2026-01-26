"""add missing FSM columns to consultation_status

Revision ID: fsm20260125003
Revises: fsm20260125002
Create Date: 2026-01-25 18:00:00.000000

This migration adds the remaining FSM columns that were defined in the model
but not yet present in the database:
- code: Machine-readable status code
- is_final: Whether this is a final status (replaces is_final_status)
- status_type: transition/activity/system
- selectable_mode: user/role/system (replaces selectable_by_user)
- counts_for_funnel: Whether counted in funnel analytics (replaces counts_for_kpi)
- description: Optional description
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fsm20260125003'
down_revision = 'fsm20260125002'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add missing FSM columns to consultation_status table.

    Strategy:
    1. Create new enum types
    2. Add new columns with defaults
    3. Backfill data from deprecated columns
    4. Create indexes
    """

    # Step 1: Create StatusTypeEnum
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'status_type_enum') THEN
                CREATE TYPE status_type_enum AS ENUM ('transition', 'activity', 'system');
            END IF;
        END $$;
    """)

    # Step 2: Create SelectableModeEnum
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'selectable_mode_enum') THEN
                CREATE TYPE selectable_mode_enum AS ENUM ('user', 'role', 'system');
            END IF;
        END $$;
    """)

    # Step 3: Add 'code' column
    op.add_column('consultation_status',
        sa.Column('code',
                  sa.String(50),
                  nullable=True,
                  comment="Machine-readable code (e.g., NOT_CONTACTED, ENROLLED)")
    )

    # Step 4: Add 'is_final' column (replaces is_final_status)
    op.add_column('consultation_status',
        sa.Column('is_final',
                  sa.Boolean(),
                  nullable=False,
                  server_default='false',
                  comment="Whether this status marks end of lead lifecycle")
    )

    # Step 5: Add 'status_type' column
    op.add_column('consultation_status',
        sa.Column('status_type',
                  sa.Enum('transition', 'activity', 'system',
                          name='status_type_enum', create_type=False),
                  nullable=False,
                  server_default='transition',
                  comment="Status type: transition/activity/system")
    )

    # Step 6: Add 'selectable_mode' column (replaces selectable_by_user)
    op.add_column('consultation_status',
        sa.Column('selectable_mode',
                  sa.Enum('user', 'role', 'system',
                          name='selectable_mode_enum', create_type=False),
                  nullable=False,
                  server_default='user',
                  comment="Who can select: user/role/system")
    )

    # Step 7: Add 'counts_for_funnel' column (replaces counts_for_kpi)
    op.add_column('consultation_status',
        sa.Column('counts_for_funnel',
                  sa.Boolean(),
                  nullable=False,
                  server_default='true',
                  comment="True if counted in funnel analytics")
    )

    # Step 8: Add 'description' column
    op.add_column('consultation_status',
        sa.Column('description',
                  sa.Text(),
                  nullable=True,
                  comment="Optional description for status")
    )

    # Step 9: Backfill data from deprecated columns
    # is_final <- is_final_status
    op.execute("""
        UPDATE consultation_status
        SET is_final = COALESCE(is_final_status, false)
        WHERE is_final_status IS NOT NULL
    """)

    # counts_for_funnel <- counts_for_kpi
    op.execute("""
        UPDATE consultation_status
        SET counts_for_funnel = COALESCE(counts_for_kpi, true)
        WHERE counts_for_kpi IS NOT NULL
    """)

    # selectable_mode <- selectable_by_user (map string to enum)
    op.execute("""
        UPDATE consultation_status
        SET selectable_mode =
            CASE
                WHEN selectable_by_user = 'user' THEN 'user'::selectable_mode_enum
                WHEN selectable_by_user = 'role' THEN 'role'::selectable_mode_enum
                WHEN selectable_by_user = 'system' THEN 'system'::selectable_mode_enum
                ELSE 'user'::selectable_mode_enum
            END
        WHERE selectable_by_user IS NOT NULL
    """)

    # status_type: derive from is_universal
    op.execute("""
        UPDATE consultation_status
        SET status_type =
            CASE
                WHEN is_universal = true THEN 'activity'::status_type_enum
                ELSE 'transition'::status_type_enum
            END
    """)

    # code: generate from id (uppercase, replace sts with empty)
    op.execute("""
        UPDATE consultation_status
        SET code = UPPER(REPLACE(id, 'sts', 'STATUS_'))
        WHERE code IS NULL
    """)

    # Step 10: Create unique constraint on code
    op.create_unique_constraint('uq_consultation_status_code', 'consultation_status', ['code'])

    # Step 11: Create indexes
    op.create_index('ix_consultation_status_status_type', 'consultation_status', ['status_type'])
    op.create_index('ix_consultation_status_selectable_mode', 'consultation_status', ['selectable_mode'])
    op.create_index('ix_consultation_status_phase', 'consultation_status', ['phase'])


def downgrade():
    """Remove FSM columns from consultation_status table."""
    # Drop indexes
    op.drop_index('ix_consultation_status_phase', table_name='consultation_status')
    op.drop_index('ix_consultation_status_selectable_mode', table_name='consultation_status')
    op.drop_index('ix_consultation_status_status_type', table_name='consultation_status')

    # Drop unique constraint
    op.drop_constraint('uq_consultation_status_code', 'consultation_status', type_='unique')

    # Drop columns
    op.drop_column('consultation_status', 'description')
    op.drop_column('consultation_status', 'counts_for_funnel')
    op.drop_column('consultation_status', 'selectable_mode')
    op.drop_column('consultation_status', 'status_type')
    op.drop_column('consultation_status', 'is_final')
    op.drop_column('consultation_status', 'code')

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS selectable_mode_enum")
    op.execute("DROP TYPE IF EXISTS status_type_enum")
