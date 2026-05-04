"""phase1_09a: add eligibility scalars + backfill gpa_overall + graduation_year

Revision ID: phase1_09a
Revises: phase1_13
Create Date: 2026-05-04

#184 Wave 2 PR-2A first migration. Add 4 nullable eligibility
scalar columns on ``admission_profile`` + backfill 2 of them
(``gpa_overall`` + ``graduation_year``) from
``academic_history`` JSON. ``conduct`` + ``health_category`` stay
NULL — no source in JSON, admin manual review qua UI Phase 1+2.

PLAN refs
---------
* §4 P1 #09a (line 2699-2824) — column add + 2-field backfill body.
* PLAN P2 fix #6 (line 398) — backfill scope = gpa + grad_year only.
* PLAN P2 fix #10 (line 327) — cheat sheet wording fix; column adds
  4 fields, backfill only 2.
* PLAN line 818-820 — column types + lock-after-draft semantic.
  Lock trigger ``phase1_09b`` is DEFERRED Q1/2027 per Q9 chốt
  2026-05-01.

Schema
------

* ``conduct_grade`` ENUM (3 values): ``TB`` (Trung bình), ``KHA``
  (Khá), ``TOT`` (Tốt). Created BEFORE column add.

* ``admission_profile.gpa_overall numeric(4,2) nullable`` — overall
  GPA (0.00..10.00 scale). Backfilled from
  ``academic_history`` JSON via LATERAL + WITH ORDINALITY.

* ``admission_profile.conduct conduct_grade nullable`` — đạo đức.
  STAYS NULL — no source in JSON. Admin reviews qua UI Phase 1+2.

* ``admission_profile.health_category smallint nullable`` — phân
  loại sức khỏe (1..4 — 1 tốt nhất). STAYS NULL — admin review UI.

* ``admission_profile.graduation_year smallint nullable`` — năm tốt
  nghiệp. Backfilled from MAX(year_to) of academic_history records.

Backfill semantics
------------------

**gpa_overall**: pick GPA from the academic_history record with
the HIGHEST ordinality (= latest year) that has a numeric GPA.
NOT just the last record — last record may have NULL gpa but a
prior record has a value. Length-bounded regex + range guard
[0, 10] prevents overflow + clamps invalid data into the
exception sink.

**graduation_year**: pick MAX(year_to) from academic_history
records where year_to is a 4-digit number in sane range
(1900..2100 per PLAN line 2795). Out-of-range values land in
``INVALID_GRADUATION_YEAR`` exception sink. Profile with
``graduation_type`` set but malformed/missing year_to lands in
``MISSING_GRADUATION_YEAR`` exception sink (PLAN line 2799-2811).

**conduct + health_category**: stay NULL. NO backfill. Admin
reviews via UI Phase 1+2 (Phase 4 admin maintenance flow with
GUC bypass — see DEFERRED phase1_09b body).

Idempotency
-----------
* All UPDATEs gated by ``WHERE <field> IS NULL`` per-row guard.
* Exception inserts use ``ON CONFLICT (profile_id, exception_type)
  DO NOTHING`` against ``_admission_backfill_exceptions``
  (created in phase1_07b).
* Re-running upgrade after partial failure leaves valid rows
  alone + skips already-backfilled exceptions.

Down-revision chain: ``phase1_13 → phase1_09a``. Note slot
``phase1_09a`` (a) is intentional — phase1_09b (lock trigger) is
DEFERRED so the chain runs straight to phase1_10 next.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "phase1_09a"
down_revision: Union[str, None] = "phase1_13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ENUM values per PLAN line 818. Frozen here as the migration is
# the source-of-truth; SQLAlchemy model mirrors via
# ``postgresql.ENUM(name=..., create_type=False)``.
CONDUCT_GRADE_VALUES: tuple[str, ...] = ("TB", "KHA", "TOT")


def upgrade() -> None:
    # 1. Create the conduct_grade ENUM type.
    conduct_enum = postgresql.ENUM(
        *CONDUCT_GRADE_VALUES,
        name="conduct_grade",
        create_type=False,
    )
    conduct_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add 4 nullable columns. All nullable so backfill can
    #    populate selectively without violating constraints.
    op.add_column(
        "admission_profile",
        sa.Column(
            "gpa_overall",
            sa.Numeric(precision=4, scale=2),
            nullable=True,
            comment="Overall GPA (0.00..10.00). Backfilled from academic_history JSON.",
        ),
    )
    op.add_column(
        "admission_profile",
        sa.Column(
            "conduct",
            conduct_enum,
            nullable=True,
            comment=(
                "Đạo đức (TB/KHA/TOT). STAYS NULL post-migration — no "
                "source in academic_history JSON; admin reviews qua UI "
                "Phase 1+2 (PLAN line 2813)."
            ),
        ),
    )
    op.add_column(
        "admission_profile",
        sa.Column(
            "health_category",
            sa.SmallInteger(),
            nullable=True,
            comment=(
                "Phân loại sức khỏe (1..4 — 1 tốt nhất). STAYS NULL — "
                "admin reviews qua UI Phase 1+2 (PLAN line 2814)."
            ),
        ),
    )
    op.add_column(
        "admission_profile",
        sa.Column(
            "graduation_year",
            sa.SmallInteger(),
            nullable=True,
            comment=(
                "Năm tốt nghiệp (1900..2100). Backfilled from MAX(year_to) "
                "of academic_history records."
            ),
        ),
    )

    # 3. Backfill gpa_overall — single statement with CTE chain.
    #    Migration runs under ``isolation_level=AUTOCOMMIT`` (see
    #    alembic env.py:57) so each ``op.execute`` opens a fresh
    #    connection — TEMP TABLEs don't survive between calls.
    #    Inline the staging via CTE so the parse + range filter +
    #    DISTINCT ON pick run in ONE statement.
    op.execute(
        sa.text(
            """
            WITH staging AS (
                SELECT
                    p.id AS profile_id,
                    rec.ord AS ord,
                    rec.value->>'gpa' AS gpa_text,
                    (rec.value->>'gpa')::numeric AS gpa_value_wide
                FROM admission_profile p,
                     LATERAL jsonb_array_elements(p.academic_history)
                         WITH ORDINALITY AS rec(value, ord)
                WHERE p.gpa_overall IS NULL
                  AND p.academic_history IS NOT NULL
                  AND rec.value->>'gpa' ~ '^[0-9]{1,3}(\\.[0-9]{1,4})?$'
            ),
            in_range AS (
                SELECT profile_id, ord,
                       gpa_value_wide::numeric(4,2) AS gpa_value
                FROM staging
                WHERE gpa_value_wide >= 0 AND gpa_value_wide <= 10
            ),
            picked AS (
                SELECT DISTINCT ON (profile_id) profile_id, gpa_value
                FROM in_range
                ORDER BY profile_id, ord DESC
            )
            UPDATE admission_profile p
            SET gpa_overall = picked.gpa_value
            FROM picked
            WHERE p.id = picked.profile_id
              AND p.gpa_overall IS NULL
            """
        )
    )

    # INSERT exception sink for out-of-range GPA values — admin
    # queue picks these up post-cutover. Re-runs the LATERAL parse
    # (cheap on small dev DB; staging table not survivable across
    # autocommit statements anyway).
    op.execute(
        sa.text(
            """
            WITH staging AS (
                SELECT
                    p.id AS profile_id,
                    rec.value->>'gpa' AS gpa_text,
                    (rec.value->>'gpa')::numeric AS gpa_value_wide
                FROM admission_profile p,
                     LATERAL jsonb_array_elements(p.academic_history)
                         AS rec(value)
                WHERE p.gpa_overall IS NULL
                  AND p.academic_history IS NOT NULL
                  AND rec.value->>'gpa' ~ '^[0-9]{1,3}(\\.[0-9]{1,4})?$'
            )
            INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
            SELECT
                profile_id,
                'INVALID_GPA_VALUE',
                jsonb_build_object(
                    'gpa_text', MIN(gpa_text),
                    'gpa_value_wide', MAX(gpa_value_wide)::text,
                    'rule', 'gpa must be in [0, 10]'
                )
            FROM staging
            WHERE gpa_value_wide < 0 OR gpa_value_wide > 10
            GROUP BY profile_id
            ON CONFLICT (profile_id, exception_type) DO NOTHING
            """
        )
    )

    # 4. Backfill graduation_year — MAX(year_to) where year_to is
    #    a 4-digit number in sane range [1900, 2100] per PLAN line
    #    2795. Tighter bounds (1990..2030) would reject legitimate
    #    older graduations + future-dated international transfers.
    op.execute(
        sa.text(
            """
            WITH year_staging AS (
                SELECT
                    p.id AS profile_id,
                    (rec.value->>'year_to')::int AS year_to_int
                FROM admission_profile p,
                     LATERAL jsonb_array_elements(p.academic_history)
                         AS rec(value)
                WHERE p.graduation_year IS NULL
                  AND p.academic_history IS NOT NULL
                  AND rec.value->>'year_to' ~ '^[0-9]{4}$'
                  AND (rec.value->>'year_to')::int BETWEEN 1900 AND 2100
            ),
            picked AS (
                SELECT profile_id, MAX(year_to_int) AS year_to_max
                FROM year_staging
                GROUP BY profile_id
            )
            UPDATE admission_profile p
            SET graduation_year = picked.year_to_max
            FROM picked
            WHERE p.id = picked.profile_id
              AND p.graduation_year IS NULL
            """
        )
    )

    # 4b. Exception sink for INVALID_GRADUATION_YEAR (PLAN line 2791-
    #     2797) — year_to numeric but outside [1900, 2100]. Aggregates
    #     all out-of-range years per profile so admin queue can
    #     review the full set.
    op.execute(
        sa.text(
            """
            WITH year_staging AS (
                SELECT
                    p.id AS profile_id,
                    (rec.value->>'year_to')::int AS year_to_int
                FROM admission_profile p,
                     LATERAL jsonb_array_elements(p.academic_history)
                         AS rec(value)
                WHERE p.graduation_year IS NULL
                  AND p.academic_history IS NOT NULL
                  AND rec.value->>'year_to' ~ '^[0-9]{4}$'
            )
            INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
            SELECT
                profile_id,
                'INVALID_GRADUATION_YEAR',
                jsonb_build_object(
                    'out_of_range_years', array_agg(year_to_int),
                    'rule', 'graduation_year must be in [1900, 2100]'
                )
            FROM year_staging
            WHERE year_to_int NOT BETWEEN 1900 AND 2100
            GROUP BY profile_id
            ON CONFLICT (profile_id, exception_type) DO NOTHING
            """
        )
    )

    # 4c. Exception sink for MISSING_GRADUATION_YEAR (PLAN line 2801-
    #     2811) — profile has at least one academic_history record
    #     with ``graduation_type`` set, but no parseable ``year_to``,
    #     so we can't backfill graduation_year. Admin queue picks
    #     these up post-cutover for manual entry.
    op.execute(
        sa.text(
            """
            INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
            SELECT
                p.id,
                'MISSING_GRADUATION_YEAR',
                jsonb_build_object(
                    'academic_history', p.academic_history,
                    'rule', 'graduation_type set but year_to missing/malformed'
                )
            FROM admission_profile p
            WHERE p.graduation_year IS NULL
              AND p.academic_history IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(p.academic_history) AS rec(value)
                  WHERE rec.value->>'graduation_type' IS NOT NULL
              )
            ON CONFLICT (profile_id, exception_type) DO NOTHING
            """
        )
    )

    # 5. Insert exception sink for profiles with NULL gpa_overall
    #    after backfill (data nguồn lỗi). Only for status NOT IN
    #    ('draft', 'revision_requested') — drafts haven't submitted
    #    yet so missing data is expected and not actionable.
    op.execute(
        sa.text(
            """
            INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
            SELECT
                id,
                'MISSING_GPA_OVERALL',
                jsonb_build_object(
                    'academic_history', academic_history,
                    'rule', 'gpa_overall NULL after backfill on submitted+ profile'
                )
            FROM admission_profile
            WHERE gpa_overall IS NULL
              AND status NOT IN ('draft', 'revision_requested')
            ON CONFLICT (profile_id, exception_type) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # Inverse — drop exception rows scoped to this migration's
    # exception_types FIRST (else CASCADE on profile won't fire),
    # then columns, then ENUM type.
    op.execute(
        sa.text(
            """
            DELETE FROM _admission_backfill_exceptions
            WHERE exception_type IN (
                'INVALID_GPA_VALUE', 'MISSING_GPA_OVERALL',
                'INVALID_GRADUATION_YEAR', 'MISSING_GRADUATION_YEAR'
            )
            """
        )
    )

    op.drop_column("admission_profile", "graduation_year")
    op.drop_column("admission_profile", "health_category")
    op.drop_column("admission_profile", "conduct")
    op.drop_column("admission_profile", "gpa_overall")

    conduct_enum = postgresql.ENUM(
        *CONDUCT_GRADE_VALUES,
        name="conduct_grade",
        create_type=False,
    )
    conduct_enum.drop(op.get_bind(), checkfirst=True)
