"""Phase 2 v8.2 PR-2B v2: admission_path 4 cols + 4-task backfill (Option A)

Adds ``admission_round_id`` FK (RESTRICT per Q7 v8.2) + path-level quota
fields (``round_quota``, ``admit_quota``, ``submission_count``) trên
``admission_path``. Round entity (PR-2A v2) năm-level globally; admission
path nest dưới (round, academic_info, method) — UNIQUE 3-col swap defer
PR-2C v2 (⚠ ONE-WAY).

Backfill pipeline (4 tasks):
- Task 1: ADD COLUMN nullable initially (PR-2C swap NOT NULL after soak)
- Task 2: backfill ``admission_path.admission_round_id`` từ
  ``offering_admission_round`` round_code='DOT_1' qua year join với
  ``offering_academic_info``
- Task 3: backfill ``admission_profile.applied_rules.admission_round_id``
  qua jsonb_set, DISABLE/ENABLE trigger ``enforce_applied_rules_immutability``
  (precedent ``aa1i2j3k4l5m_pr6_allow_unverified_submission.py:65-92``).
  EXISTS guard + regex ``^[0-9]+$`` (P0-2 v8.1 + Concern B v4)
- Task 4: backfill ``admission_path.submission_count`` per-path high-watermark
  từ admission_profile.applied_rules.admission_path_id (status != 'draft').
  CTE ``safe_profiles`` wrapper với regex + EXISTS guard (P0-3 v8.1)

Audit guards at end:
- 0 NULL admission_round_id rows trên admission_path
- 0 admission_profile có applied_rules.admission_path_id nhưng thiếu
  applied_rules.admission_round_id

Revision ID: phase2_02_v2
Revises: phase2_01_v2
Create Date: 2026-05-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "phase2_02_v2"
down_revision: Union[str, None] = "phase2_01_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # Task 1: ADD COLUMN nullable initially
    # ============================================================
    # admission_round_id nullable=True initially → PR-2C v2 (⚠ ONE-WAY)
    # swaps to NOT NULL after 1-day soak (Q2 deviation từ SPEC 1 week,
    # solo dev compressed cycle).
    op.add_column(
        "admission_path",
        sa.Column(
            "admission_round_id",
            sa.Integer,
            sa.ForeignKey(
                "offering_admission_round.id",
                ondelete="RESTRICT",  # Q7 v8.2 — soft-archive lifecycle preserved
                name="fk_admission_path_admission_round_id",
            ),
            nullable=True,
            comment=(
                "FK to offering_admission_round (year-level, Phase 2 v8.2 "
                "Option A). NOT NULL post PR-2C v2 swap."
            ),
        ),
    )
    op.create_index(
        "ix_admission_path_admission_round_id",
        "admission_path",
        ["admission_round_id"],
    )

    # round_quota — per-path submission cap (overflow buffer per Q2)
    op.add_column(
        "admission_path",
        sa.Column(
            "round_quota",
            sa.Integer,
            nullable=True,
            comment=(
                "Per-path submission cap. NULL = unbounded. Path-level "
                "invariant: admit_quota ≤ round_quota nếu cả 2 set."
            ),
        ),
    )

    # admit_quota — per-path admit cap (Tier 1 chain root per Q2)
    op.add_column(
        "admission_path",
        sa.Column(
            "admit_quota",
            sa.Integer,
            nullable=True,
            comment=(
                "Per-path admit cap. Tier 1 chain root (Q2 v8.2): "
                "∑(path.admit_quota WHERE academic_info_id=X) ≤ "
                "academic_info[X].annual_admission_quota."
            ),
        ),
    )

    # submission_count — atomic per-path counter
    op.add_column(
        "admission_path",
        sa.Column(
            "submission_count",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment=(
                "Atomic per-path submission counter. Increment qua "
                "candidate submit SPEC §4.1 SQL pattern."
            ),
        ),
    )

    # ============================================================
    # Task 2: backfill admission_path.admission_round_id
    # ============================================================
    # Resolve DOT_1 of each path's academic_year qua academic_info join.
    # Year-level lookup (Option A) — KHÔNG phụ thuộc academic_info_id
    # FK trên round (round không có column này).
    op.execute(
        """
        UPDATE admission_path ap
        SET admission_round_id = (
            SELECT oar.id
            FROM offering_admission_round oar
            JOIN offering_academic_info oai
              ON oai.academic_year = oar.academic_year
            WHERE oai.id = ap.academic_info_id
              AND oar.round_code = 'DOT_1'
            LIMIT 1
        )
        WHERE ap.admission_round_id IS NULL;
        """
    )

    # ============================================================
    # Task 3: backfill applied_rules.admission_round_id
    # ============================================================
    # P0-2 v8.1: DISABLE/ENABLE trigger ``enforce_applied_rules_immutability``
    # wrap try/finally per precedent
    # ``aa1i2j3k4l5m_pr6_allow_unverified_submission.py:65-92``.
    # Concern B v4: EXISTS guard cho path.admission_round_id IS NOT NULL.
    # Concern v8.1: regex ``^[0-9]+$`` cho int cast safety.
    op.execute(
        "ALTER TABLE admission_profile "
        "DISABLE TRIGGER enforce_applied_rules_immutability"
    )
    try:
        op.execute(
            """
            UPDATE admission_profile p
            SET applied_rules = jsonb_set(
                p.applied_rules,
                '{admission_round_id}',
                to_jsonb((
                    SELECT ap.admission_round_id
                    FROM admission_path ap
                    WHERE ap.id = (p.applied_rules->>'admission_path_id')::int
                ))
            )
            WHERE p.applied_rules ? 'admission_path_id'
              AND NOT (p.applied_rules ? 'admission_round_id')
              AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
              AND EXISTS (
                  SELECT 1 FROM admission_path ap
                  WHERE ap.id = (p.applied_rules->>'admission_path_id')::int
                    AND ap.admission_round_id IS NOT NULL
              );
            """
        )
    finally:
        op.execute(
            "ALTER TABLE admission_profile "
            "ENABLE TRIGGER enforce_applied_rules_immutability"
        )

    # ============================================================
    # Task 4: backfill admission_path.submission_count
    # ============================================================
    # P0-3 v8.1: CTE ``safe_profiles`` wrapper với regex + EXISTS guard
    # parity Task 3. 1 malformed applied_rules.admission_path_id (non-
    # numeric or NULL) sẽ crash migration nếu thiếu guard.
    # Status != 'draft' filter excludes pre-submit profiles từ counter.
    op.execute(
        """
        WITH safe_profiles AS (
            SELECT
                (p.applied_rules->>'admission_path_id')::int AS path_id
            FROM admission_profile p
            WHERE p.applied_rules ? 'admission_path_id'
              AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
              AND p.status != 'draft'
              AND EXISTS (
                  SELECT 1 FROM admission_path ap
                  WHERE ap.id = (p.applied_rules->>'admission_path_id')::int
              )
        )
        UPDATE admission_path ap
        SET submission_count = (
            SELECT COUNT(*) FROM safe_profiles sp WHERE sp.path_id = ap.id
        );
        """
    )

    # ============================================================
    # Audit guards
    # ============================================================
    # Pre-condition cho PR-2C v2 NOT NULL swap. Migration abort nếu
    # backfill leak NULL or missing applied_rules.admission_round_id.
    op.execute(
        """
        DO $$
        DECLARE
            null_path INT;
            null_profile INT;
        BEGIN
            SELECT COUNT(*) INTO null_path
            FROM admission_path
            WHERE admission_round_id IS NULL;
            IF null_path > 0 THEN
                RAISE EXCEPTION 'Migration audit: % paths missing '
                    'admission_round_id post-backfill (PR-2B v2 Task 2)', null_path;
            END IF;

            SELECT COUNT(*) INTO null_profile
            FROM admission_profile
            WHERE applied_rules ? 'admission_path_id'
              AND (
                  NOT (applied_rules ? 'admission_round_id')
                  OR applied_rules->>'admission_round_id' IS NULL
              );
            IF null_profile > 0 THEN
                RAISE EXCEPTION 'Migration audit: % profiles missing or '
                    'NULL applied_rules.admission_round_id (PR-2B v2 Task 3)', null_profile;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Drop columns + index. submission_count downgrade lossy (counter
    # data lost) — acceptable cho dev rollback; prod path qua manual
    # rollback playbook (Documents/PHASE2_ROLLBACK_PLAYBOOK_V8.md).
    op.drop_index(
        "ix_admission_path_admission_round_id", table_name="admission_path"
    )
    op.drop_column("admission_path", "submission_count")
    op.drop_column("admission_path", "admit_quota")
    op.drop_column("admission_path", "round_quota")
    op.drop_column("admission_path", "admission_round_id")
