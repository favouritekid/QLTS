"""fix: schema drift remediation (report 2026-03-15)

Revision ID: zo4u5v6w7x8y9
Revises: zn3t4u5v6w7x8
Create Date: 2026-03-15 18:00:00.000000

Fixes 3 real drifts identified in docs/schema-drift-report-2026-03-15.md:

1. DROP stale unique index `ix_admission_profile_citizen_id` on citizen_id alone.
   The business rule changed to UNIQUE(citizen_id, academic_year) in migration
   q4a1b2c3d4e5, but that migration only dropped the *constraint* and missed
   the *index* created by the original migration with `unique=True, index=True`.
   Result: same CCCD could not apply in different years — violates multi-year rule.

2. ADD FK `fk_user_current_assignment` on user.current_assignment_id ->
   user_unit_assignment.id (ON DELETE SET NULL).
   Model declared this FK with use_alter=True, but no migration ever created it.
   Pre-flight: 0 non-null rows, 0 orphans.

3. ADD 2 CHECK constraints on admission_criteria:
   - ck_criteria_selection_mode: subject_selection_mode IN ('fixed','best_n','any_n')
   - ck_criteria_scoring_method: scoring_method IN ('sum','average','weighted')
   Model declares these but no migration created them.
   Pre-flight: 0 dirty rows for either column.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "zo4u5v6w7x8y9"
down_revision: Union[str, None] = "zn3t4u5v6w7x8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # FIX 1: Drop stale unique index on admission_profile.citizen_id
    # =========================================================================
    # Safety check: only drop if the index exists and is UNIQUE
    result = conn.execute(text(
        "SELECT 1 FROM pg_indexes "
        "WHERE indexname = 'ix_admission_profile_citizen_id' "
        "AND indexdef LIKE '%UNIQUE%'"
    ))
    if result.fetchone():
        op.drop_index(
            "ix_admission_profile_citizen_id",
            table_name="admission_profile",
        )
        # Re-create as a non-unique index (model has index=True but not unique)
        op.create_index(
            "ix_admission_profile_citizen_id",
            "admission_profile",
            ["citizen_id"],
            unique=False,
        )
        print("  [fix1] Dropped stale UNIQUE index, re-created as non-unique.")
    else:
        print("  [fix1] Stale unique index not found — already fixed or absent.")

    # =========================================================================
    # FIX 2: Add FK fk_user_current_assignment
    # =========================================================================
    # Safety check: only add if FK does not exist
    result = conn.execute(text(
        "SELECT 1 FROM pg_constraint "
        "WHERE conname = 'fk_user_current_assignment' "
        "AND conrelid = '\"user\"'::regclass"
    ))
    if not result.fetchone():
        # Defensive: clean any orphan references before adding FK
        conn.execute(text(
            'UPDATE "user" SET current_assignment_id = NULL '
            "WHERE current_assignment_id IS NOT NULL "
            "AND current_assignment_id NOT IN "
            "(SELECT id FROM user_unit_assignment)"
        ))
        op.create_foreign_key(
            "fk_user_current_assignment",
            "user",
            "user_unit_assignment",
            ["current_assignment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        print("  [fix2] FK fk_user_current_assignment created.")
    else:
        print("  [fix2] FK already exists — skipping.")

    # =========================================================================
    # FIX 3: Add CHECK constraints on admission_criteria
    # =========================================================================
    for ck_name, ck_expr in [
        (
            "ck_criteria_selection_mode",
            "subject_selection_mode IN ('fixed', 'best_n', 'any_n')",
        ),
        (
            "ck_criteria_scoring_method",
            "scoring_method IN ('sum', 'average', 'weighted')",
        ),
    ]:
        result = conn.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = :name"
        ).bindparams(name=ck_name))
        if not result.fetchone():
            op.create_check_constraint(ck_name, "admission_criteria", ck_expr)
            print(f"  [fix3] CHECK {ck_name} created.")
        else:
            print(f"  [fix3] CHECK {ck_name} already exists — skipping.")


def downgrade() -> None:
    # Reverse fix 3
    op.drop_constraint(
        "ck_criteria_scoring_method", "admission_criteria", type_="check"
    )
    op.drop_constraint(
        "ck_criteria_selection_mode", "admission_criteria", type_="check"
    )

    # Reverse fix 2
    op.drop_constraint("fk_user_current_assignment", "user", type_="foreignkey")

    # Reverse fix 1: restore unique index
    op.drop_index(
        "ix_admission_profile_citizen_id", table_name="admission_profile"
    )
    op.create_index(
        "ix_admission_profile_citizen_id",
        "admission_profile",
        ["citizen_id"],
        unique=True,
    )
