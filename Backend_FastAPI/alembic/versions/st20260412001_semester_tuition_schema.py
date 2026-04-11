"""semester tuition schema - offering_semester_tuition + fee.semester_no

Revision ID: st20260412001
Revises: b2_drop_processed_event
Create Date: 2026-04-12

Implements PR 1 of the semester_tuition epic (ADR-002, Deferred Decisions
D1-D3 + Gap A). Scope: schema foundation + mandatory runtime compatibility
patch for live tuition creation. All other runtime logic (router, admission
gate, event mapping, feature flags, discount hooks, public schema) is
untouched — those belong to PR 3/4/5/6.

Changes:
1. CREATE TABLE offering_semester_tuition (lean: id, academic_info_id,
   semester_no, amount, notes, audit columns; no is_published/window).
2. ALTER TABLE fee ADD COLUMN semester_no INTEGER NULL.
3. Backfill: every existing fee row with fee_type='tuition' gets
   semester_no = 1. Non-tuition rows stay NULL.
4. Add CHECK chk_fee_tuition_semester_no_required
   (fee_type <> 'tuition' OR (semester_no IS NOT NULL AND semester_no >= 1)).
4b. Add CHECK chk_fee_nontuition_semester_no_null
   (fee_type = 'tuition' OR semester_no IS NULL). Locks the non-tuition
   invariant that the partial indexes rely on.
5. Drop UniqueConstraint uq_fee_profile_type_year (pre-PR1 constraint).
6. Create partial UNIQUE INDEX uq_fee_profile_type_year_nontuition
   WHERE fee_type <> 'tuition'  -- preserves pre-PR1 non-tuition behavior.
7. Create partial UNIQUE INDEX uq_fee_profile_type_semester_tuition
   WHERE fee_type = 'tuition'   -- new semester-scoped uniqueness.

Compatibility patch (bundled to keep PR 1 deployable):
- fee_calculation_service.calculate_fee() now sets
  semester_no=1 when fee_type == tuition, else None. Without this
  patch, every live tuition fee creation after migration would fail
  chk_fee_tuition_semester_no_required. No other runtime logic changes
  in PR 1; semester-aware duplicate check and offering_semester_tuition
  reads are PR 3 work.

Safety:
- Backfill runs BEFORE the CHECK constraint so existing data cannot trip
  it.
- Partial indexes are installed AFTER the old constraint is dropped, so
  there is no moment at which two uniqueness rules conflict.
- Pre-backfill sanity check scans for profiles with multi-year tuition
  rows that would collide on semester_no=1 after backfill; fails loud.
- Downgrade has two guards: new table must be empty, and the pre-PR1
  unique tuple must still be unique across ALL fee types.

NOT in scope for PR 1:
- fee_calculation_service semester-aware logic beyond the minimal compat
  patch above (offering_semester_tuition reads, HK2+ creation, duplicate
  check semester-awareness — all PR 3)
- fee_repository.check_duplicate (PR 3 — still uses academic_year for
  all fee types, which remains correct under the partial-index strategy)
- admission_service.py gate logic (PR 4)
- admission_event_mapping.py projection gating (PR 5)
- Public/admin API additive fields (PR 6)
- Dropping OfferingAcademicInfo.tuition_fee_per_year (deprecated but
  still live throughout the epic)

Autogenerate warning: partial unique indexes often show spurious
drop/create proposals on `alembic revision --autogenerate` due to
whitespace/quoting differences in postgresql_where. DO NOT run autogenerate
against this migration's parent tree. Hand-written migrations only for
this epic.

References:
- Backend_FastAPI/docs/adr/ADR-002-semester-tuition-refactor.md
  (Closed Decisions > Decision 3, Gap A, Deferred Decisions D1-D3)
- Backend_FastAPI/docs/SEMESTER_TUITION_SPEC.md Section 2 and Section 3
- Backend_FastAPI/app/models/finance/fee.py (current __table_args__)
- Backend_FastAPI/app/repositories/fee_repository.py:287-321
  (check_duplicate — unchanged in PR 1, still queries by academic_year
  for all fee types)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'st20260412001'
down_revision = 'b2_drop_processed_event'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Step 1: Create offering_semester_tuition (lean canonical catalog)
    # ------------------------------------------------------------------
    op.create_table(
        'offering_semester_tuition',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'academic_info_id', sa.Integer(),
            sa.ForeignKey('offering_academic_info.id', ondelete='CASCADE'),
            nullable=False,
            comment='Link to parent OfferingAcademicInfo (program-year)',
        ),
        sa.Column(
            'semester_no', sa.Integer(), nullable=False,
            comment='Semester index within the full course, 1-based (HK1=1)',
        ),
        sa.Column(
            'amount', sa.Numeric(15, 2), nullable=False,
            comment='Tuition amount for this semester (VND)',
        ),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            'created_by_user_id', sa.Integer(),
            sa.ForeignKey('user.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'updated_by_user_id', sa.Integer(),
            sa.ForeignKey('user.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.UniqueConstraint(
            'academic_info_id', 'semester_no',
            name='uq_offering_semester_tuition_info_semester',
        ),
        sa.CheckConstraint(
            'semester_no >= 1',
            name='chk_offering_semester_tuition_semester_no_positive',
        ),
        sa.CheckConstraint(
            'amount >= 0',
            name='chk_offering_semester_tuition_amount_non_negative',
        ),
    )
    op.create_index(
        'ix_offering_semester_tuition_academic_info_id',
        'offering_semester_tuition',
        ['academic_info_id'],
    )
    op.create_index(
        'ix_offering_semester_tuition_semester_no',
        'offering_semester_tuition',
        ['semester_no'],
    )

    # ------------------------------------------------------------------
    # Step 2: Add fee.semester_no (nullable, no default)
    # ------------------------------------------------------------------
    op.add_column(
        'fee',
        sa.Column(
            'semester_no', sa.Integer(),
            nullable=True,
            comment='Semester index (1..N) for tuition fees. NULL for '
                    'non-tuition fees. See ADR-002 Gap A (v2 partial '
                    'index strategy).',
        ),
    )
    op.create_index('ix_fee_semester_no', 'fee', ['semester_no'])

    # ------------------------------------------------------------------
    # Step 3a: Pre-backfill sanity check — no multi-year tuition rows on
    # the same profile (would collide on semester_no=1 after backfill
    # and violate the new partial unique index).
    # ------------------------------------------------------------------
    bind = op.get_bind()
    dup = bind.execute(sa.text(
        """
        SELECT admission_profile_id, COUNT(*) AS c
          FROM fee
         WHERE fee_type = 'tuition'
         GROUP BY admission_profile_id
        HAVING COUNT(*) > 1
         LIMIT 5
        """
    )).fetchall()
    if dup:
        raise RuntimeError(
            "Pre-backfill check failed: profiles with multiple existing "
            "tuition fee rows would collapse to semester_no=1 after "
            "backfill and violate the new partial unique index. "
            f"Offenders: {dup}. Resolve manually (pick one row to become "
            "HK1; decide what to do with the others) before retrying."
        )

    # ------------------------------------------------------------------
    # Step 3b: Backfill existing tuition rows to semester_no = 1
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE fee
           SET semester_no = 1
         WHERE fee_type = 'tuition'
           AND semester_no IS NULL
        """
    )

    # Defensive post-backfill check: no tuition row should still be NULL
    leftover = bind.execute(sa.text(
        "SELECT COUNT(*) FROM fee "
        "WHERE fee_type='tuition' AND semester_no IS NULL"
    )).scalar()
    if leftover:
        raise RuntimeError(
            f"Backfill sanity check failed: {leftover} tuition fee row(s) "
            "still have NULL semester_no. Aborting migration."
        )

    # ------------------------------------------------------------------
    # Step 4: Add CHECK constraint — tuition rows require semester_no>=1
    # ------------------------------------------------------------------
    op.create_check_constraint(
        'chk_fee_tuition_semester_no_required',
        'fee',
        "fee_type <> 'tuition' "
        "OR (semester_no IS NOT NULL AND semester_no >= 1)",
    )

    # ------------------------------------------------------------------
    # Step 4b: Add CHECK constraint — non-tuition rows must have NULL.
    # Locks the "non-tuition = NULL" invariant that PR 3+ relies on.
    # All existing non-tuition rows are already NULL (the ADD COLUMN in
    # Step 2 added NULL for every row and Step 3 only UPDATEd tuition).
    # ------------------------------------------------------------------
    op.create_check_constraint(
        'chk_fee_nontuition_semester_no_null',
        'fee',
        "fee_type = 'tuition' OR semester_no IS NULL",
    )

    # ------------------------------------------------------------------
    # Step 5: Drop the old unified unique constraint
    # ------------------------------------------------------------------
    op.drop_constraint(
        'uq_fee_profile_type_year', 'fee', type_='unique',
    )

    # ------------------------------------------------------------------
    # Step 6: Create partial unique index for non-tuition fees.
    # Preserves the pre-PR1 (profile, fee_type, academic_year) uniqueness
    # for application / enrollment / insurance / dormitory / other.
    # ------------------------------------------------------------------
    op.create_index(
        'uq_fee_profile_type_year_nontuition',
        'fee',
        ['admission_profile_id', 'fee_type', 'academic_year'],
        unique=True,
        postgresql_where=sa.text("fee_type <> 'tuition'"),
    )

    # ------------------------------------------------------------------
    # Step 7: Create partial unique index for tuition fees.
    # Enforces the new (profile, fee_type, semester_no) uniqueness,
    # letting HK1/HK2/... coexist on the same profile in the same year.
    # ------------------------------------------------------------------
    op.create_index(
        'uq_fee_profile_type_semester_tuition',
        'fee',
        ['admission_profile_id', 'fee_type', 'semester_no'],
        unique=True,
        postgresql_where=sa.text("fee_type = 'tuition'"),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Guard A: new table must be empty. Post-upgrade inserts cannot be
    # represented in the pre-PR1 schema; losing them silently is worse
    # than failing the downgrade.
    sem_rows = bind.execute(sa.text(
        "SELECT COUNT(*) FROM offering_semester_tuition"
    )).scalar()
    if sem_rows:
        raise RuntimeError(
            f"Refusing to downgrade: offering_semester_tuition has "
            f"{sem_rows} row(s). Archive or delete them explicitly "
            "before downgrading."
        )

    # Guard B: the pre-PR1 unique tuple (profile, fee_type, academic_year)
    # must still be unique across ALL fee_types (including tuition). If
    # PR 3 has already created HK2 rows, this guard trips and forces
    # explicit operator reconciliation.
    dup_year = bind.execute(sa.text(
        """
        SELECT COUNT(*) FROM (
            SELECT admission_profile_id, fee_type, academic_year
              FROM fee
             GROUP BY admission_profile_id, fee_type, academic_year
            HAVING COUNT(*) > 1
        ) d
        """
    )).scalar()
    if dup_year:
        raise RuntimeError(
            f"Refusing to downgrade: {dup_year} duplicate "
            "(admission_profile_id, fee_type, academic_year) group(s) "
            "found. The pre-PR1 unique constraint cannot be restored. "
            "Resolve duplicates (likely HK2+ tuition rows created after "
            "PR 3 merged) before retrying."
        )

    # Step 7 reverse: drop tuition partial index
    op.drop_index(
        'uq_fee_profile_type_semester_tuition', table_name='fee',
    )

    # Step 6 reverse: drop non-tuition partial index
    op.drop_index(
        'uq_fee_profile_type_year_nontuition', table_name='fee',
    )

    # Step 5 reverse: re-create original unified unique constraint
    op.create_unique_constraint(
        'uq_fee_profile_type_year',
        'fee',
        ['admission_profile_id', 'fee_type', 'academic_year'],
    )

    # Step 4b reverse: drop the non-tuition CHECK
    op.drop_constraint(
        'chk_fee_nontuition_semester_no_null', 'fee', type_='check',
    )

    # Step 4 reverse: drop the tuition CHECK
    op.drop_constraint(
        'chk_fee_tuition_semester_no_required', 'fee', type_='check',
    )

    # Steps 2/3 reverse: drop column (backfilled values go away with it)
    op.drop_index('ix_fee_semester_no', table_name='fee')
    op.drop_column('fee', 'semester_no')

    # Step 1 reverse: drop the new table and its indexes
    op.drop_index(
        'ix_offering_semester_tuition_semester_no',
        table_name='offering_semester_tuition',
    )
    op.drop_index(
        'ix_offering_semester_tuition_academic_info_id',
        table_name='offering_semester_tuition',
    )
    op.drop_table('offering_semester_tuition')
