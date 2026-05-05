"""Wave 3-C / M-1-12 — backfill ``admission_profile.selected_subject_group_id`` ⚠ ONE-WAY.

Backfills the column that Phase 0 (``admstrict01``) added but left NULL on
all historical profiles. Phase 3 multi-NV needs a non-NULL value to know
which subject group a candidate competed under so that
``AdmissionProfileChoice`` can be created with the correct group reference.

This migration ONLY backfills — it does NOT add the column. Phase 0 owns
the DDL; running this migration before Phase 0 fails fast with a clear
error pointing back at Phase 0.

Decision tree (3 rules per PLAN line 394 + line 3122-3242 SQL spec)
------------------------------------------------------------------

* **Rule (a)** — auto-map: path has exactly 1 ``criteria_subject_group``
  row → there is no ambiguity, every profile attached to that path
  picks the sole group.

* **Rule (b)** — infer from scores SCOPED to path: a profile may have
  ``ProfileSubjectScore`` rows that complete exactly ONE of the path's
  allowed groups. Match that group iff:
  * profile has scores for EVERY subject in the candidate group, AND
  * exactly ONE such complete group exists in the path's allowed set.

  Both criteria are required. The "≥1 score in group" weak match would
  flag every candidate with a single score that happens to share a
  subject with multiple groups; "complete coverage" forces unambiguous
  selection.

* **Rule (c)** — exception report (no auto-create choice): two distinct
  exception types so admin queue UX can route them to different fixes:
  * ``AMBIGUOUS_SELECTED_GROUP`` — profile has data (path + scores) but
    ≥2 complete groups match. Admin picks one via UI.
  * ``INSUFFICIENT_DATA_FOR_BACKFILL`` — profile is active (status ∉
    {draft, withdrawn}) but missing path id, or path id non-numeric, or
    no scores at all. Admin fixes the upstream data first.

  Both exception types skip ``draft`` / ``withdrawn`` profiles — those
  are not on the choice-engine critical path; flooding the admin queue
  with abandoned drafts dilutes the signal.

ONE-WAY rationale + downgrade contract
--------------------------------------

Once Phase 3 multi-NV starts creating ``AdmissionProfileChoice`` rows
keyed off ``selected_subject_group_id``, reverting the backfill (setting
column back to NULL) breaks the FK reference inside choice rows. Even
without Phase 3 yet, downgrading would force every backfilled profile to
re-enter the "needs admin review" state — pure regression. Downgrade is
intentionally a no-op with a clear message; restore from snapshot is the
correct ops path.

Idempotent
----------

* Each rule's UPDATE is guarded by ``WHERE selected_subject_group_id IS
  NULL`` — re-running skips already-populated profiles.
* Exception INSERTs use ``ON CONFLICT (profile_id, exception_type) DO
  NOTHING`` — duplicates blocked by the unique constraint from
  ``phase1_07b``.

Live cold cutover rehearsal (dev DB w/ prod data 2026-05-05)
------------------------------------------------------------

Pre-flight verified: 9/9 admission_profile rows have NULL
``selected_subject_group_id``; all 9 have ``admission_path_id`` in
``applied_rules`` JSONB; 8/9 have ProfileSubjectScore rows; status
distribution 8 draft + 1 submitted. Rule (c) scope (status NOT IN
draft/withdrawn) means only 1 profile is candidate for exception
reporting.

Revision ID: phase1_12
Revises: phase1_11
Create Date: 2026-05-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "phase1_12"
down_revision: Union[str, None] = "phase1_11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backfill ``selected_subject_group_id`` via 3-rule decision tree.

    Pre-flight check: column must exist (Phase 0 ``admstrict01`` is the
    DDL owner). Fail fast with hint if missing — running this migration
    before Phase 0 is a chain misuse.
    """
    bind = op.get_bind()

    # Pre-flight: column owned by Phase 0. If missing, the chain has been
    # applied out of order — surface the hint instead of letting the
    # backfill UPDATEs raise a cryptic "column does not exist".
    column_exists = bind.execute(
        sa.text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'admission_profile'
              AND column_name = 'selected_subject_group_id'
            """
        )
    ).scalar()
    if not column_exists:
        raise RuntimeError(
            "phase1_12 pre-flight: column "
            "`admission_profile.selected_subject_group_id` not found. "
            "Phase 0 migration `admstrict01` is the DDL owner — apply "
            "the chain from base if the column is missing."
        )

    # Rule (a) — auto-map for paths with exactly 1 criteria_subject_group.
    # CTE splits the eligible-profile filter (numeric guard + cast) from
    # the path/group lookup so Postgres cannot reorder the cast before
    # the regex predicate.
    op.execute(
        sa.text(
            """
            WITH eligible_profiles_a AS (
                SELECT p.id AS profile_id,
                       (p.applied_rules->>'admission_path_id')::int AS admission_path_id_int
                FROM admission_profile p
                WHERE p.selected_subject_group_id IS NULL
                  AND p.applied_rules ? 'admission_path_id'
                  AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
            ),
            single_group_paths AS (
                SELECT ap.id AS path_id, MAX(csg.subject_group_id) AS group_id
                FROM admission_path ap
                JOIN criteria_subject_group csg ON csg.criteria_id = ap.criteria_id
                GROUP BY ap.id
                HAVING COUNT(*) = 1
            )
            UPDATE admission_profile p
            SET selected_subject_group_id = sgp.group_id
            FROM eligible_profiles_a ep
            JOIN single_group_paths sgp ON sgp.path_id = ep.admission_path_id_int
            WHERE p.id = ep.profile_id
              AND p.selected_subject_group_id IS NULL;
            """
        )
    )

    # Rule (b) — infer SCOPED to the path's allowed group set, gated by
    # complete-coverage check (every subject in the candidate group has a
    # ProfileSubjectScore row), and accept only when exactly ONE complete
    # group remains.
    op.execute(
        sa.text(
            """
            WITH eligible_profiles AS (
                SELECT p.id AS profile_id,
                       (p.applied_rules->>'admission_path_id')::int AS admission_path_id_int
                FROM admission_profile p
                WHERE p.selected_subject_group_id IS NULL
                  AND p.applied_rules ? 'admission_path_id'
                  AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
            ),
            path_allowed_groups AS (
                SELECT ep.profile_id, csg.subject_group_id
                FROM eligible_profiles ep
                JOIN admission_path ap ON ap.id = ep.admission_path_id_int
                JOIN criteria_subject_group csg ON csg.criteria_id = ap.criteria_id
            ),
            group_completeness AS (
                SELECT pag.profile_id,
                       pag.subject_group_id,
                       (SELECT COUNT(*) FROM subject_group_subject sgs
                        WHERE sgs.subject_group_id = pag.subject_group_id) AS required_count,
                       (SELECT COUNT(*) FROM subject_group_subject sgs
                        JOIN profile_subject_score pss
                          ON pss.subject_id = sgs.subject_id
                          AND pss.profile_id = pag.profile_id
                        WHERE sgs.subject_group_id = pag.subject_group_id) AS matched_count
                FROM path_allowed_groups pag
            ),
            complete_groups_per_profile AS (
                SELECT profile_id, subject_group_id
                FROM group_completeness
                WHERE matched_count = required_count
                  AND required_count > 0
            ),
            unique_complete_groups AS (
                SELECT profile_id,
                       MAX(subject_group_id) AS sole_group_id,
                       COUNT(*) AS complete_group_count
                FROM complete_groups_per_profile
                GROUP BY profile_id
                HAVING COUNT(*) = 1
            )
            UPDATE admission_profile p
            SET selected_subject_group_id = ucg.sole_group_id
            FROM unique_complete_groups ucg
            WHERE ucg.profile_id = p.id
              AND p.selected_subject_group_id IS NULL;
            """
        )
    )

    # Rule (c) — Exception 1: AMBIGUOUS — profile has full data but
    # multiple complete groups satisfy. Admin picks one via UI.
    op.execute(
        sa.text(
            """
            INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
            SELECT p.id, 'AMBIGUOUS_SELECTED_GROUP',
                   jsonb_build_object(
                       'applied_rules_groups', p.applied_rules->'subject_groups',
                       'score_count', (SELECT count(*) FROM profile_subject_score WHERE profile_id = p.id)
                   )
            FROM admission_profile p
            WHERE p.selected_subject_group_id IS NULL
              AND p.status NOT IN ('draft', 'withdrawn')
              AND p.applied_rules ? 'admission_path_id'
              AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
              AND EXISTS (SELECT 1 FROM profile_subject_score WHERE profile_id = p.id)
            ON CONFLICT (profile_id, exception_type) DO NOTHING;
            """
        )
    )

    # Rule (c) — Exception 2: INSUFFICIENT_DATA — profile is active but
    # missing path id, non-numeric path id, or no scores. Different fix
    # workflow than ambiguous, so different exception_type.
    op.execute(
        sa.text(
            """
            INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
            SELECT p.id, 'INSUFFICIENT_DATA_FOR_BACKFILL',
                   jsonb_build_object(
                       'has_path_id', p.applied_rules ? 'admission_path_id',
                       'has_scores', EXISTS (SELECT 1 FROM profile_subject_score WHERE profile_id = p.id),
                       'status', p.status
                   )
            FROM admission_profile p
            WHERE p.selected_subject_group_id IS NULL
              AND p.status NOT IN ('draft', 'withdrawn')
              AND (
                  NOT (p.applied_rules ? 'admission_path_id')
                  OR (p.applied_rules->>'admission_path_id') !~ '^[0-9]+$'
                  OR NOT EXISTS (SELECT 1 FROM profile_subject_score WHERE profile_id = p.id)
              )
            ON CONFLICT (profile_id, exception_type) DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    """⚠ ONE-WAY — backfill is forward-only.

    Phase 3 multi-NV (post-cutover) creates ``AdmissionProfileChoice``
    rows keyed off ``selected_subject_group_id``. Setting the column
    back to NULL would dangle Phase 3 FK references. Even pre-Phase-3,
    the backfill represents an admin-decision-equivalent for each
    profile — clearing it forces the queue to re-process every row.

    Restore from a pre-Wave-3 snapshot if a real rollback is needed.
    """
    raise RuntimeError(
        "Cannot downgrade phase1_12: backfill is ONE-WAY. Reverting "
        "selected_subject_group_id to NULL would dangle Phase 3 "
        "AdmissionProfileChoice FKs and force re-review of every "
        "backfilled profile. Restore from a pre-Wave-3 snapshot if a "
        "real rollback is required."
    )
