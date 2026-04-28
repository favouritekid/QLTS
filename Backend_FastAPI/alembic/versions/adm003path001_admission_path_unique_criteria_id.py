"""Enforce admission_path.criteria_id uniqueness; clone shared criteria.

Revision ID: adm003path001
Revises: legacy001
Create Date: 2026-04-27

ADM-003: Each ``AdmissionCriteria`` row must belong to exactly one
``AdmissionPath``. The pre-migration prod state has 32 paths sharing 2
criteria rows (the xlsx import script seeded shared FK references by
re-using a ``criteria_code`` lookup across multiple admission_path
rows). Without enforcement, mutating one path's criteria via
``PUT /paths/{id}/criteria`` silently rewrites the criteria of every
path that shares it.

Strategy
--------
1. Walk ``admission_path`` rows whose ``criteria_id`` appears more than
   once.
2. Keep the criteria attached to the path with the SMALLEST ``id``;
   clone the ``admission_criteria`` row (and its
   ``criteria_subject_group`` mappings) for every other path.
   Clone code is deterministic: ``CRIT_orig_{old_id}_path_{path_id}``
   so repeated runs are idempotent and rollback-friendly.
3. Add a UNIQUE constraint on ``admission_path.criteria_id``.
   PostgreSQL treats NULL as distinct in UNIQUE indexes, so draft paths
   without criteria continue to coexist.

Out of scope (deliberately)
---------------------------
- Cleanup of orphan ``AdmissionCriteria`` rows (criteria no longer
  linked to any path). A separate housekeeping migration can reclaim
  those if desired.

Downgrade
---------
Drops the UNIQUE constraint only. Cloned criteria + subject-group
mappings are left in place — downgrade does not undo data movement
because we do not keep a clone log to drive a precise reversal, and
re-pointing every cloned path back to the original criteria_id en
masse would silently re-introduce the bug we just removed.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "adm003path001"
down_revision: Union[str, None] = "legacy001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columns copied from admission_criteria when cloning. ``id`` is excluded
# (auto-generated). ``code`` becomes the deterministic ``CRIT_orig_*``
# value below; everything else mirrors the source row.
_CLONE_COLUMNS_SQL = """
    method_id, name, min_gpa, min_score, conditions, is_active,
    required_subject_count, subject_selection_mode, scoring_method,
    max_possible_score, min_subject_score, policy_version,
    effective_from, effective_to
"""


def upgrade() -> None:
    bind = op.get_bind()

    duplicates = bind.execute(
        text(
            """
            SELECT criteria_id, ARRAY_AGG(id ORDER BY id) AS path_ids
            FROM admission_path
            WHERE criteria_id IS NOT NULL
            GROUP BY criteria_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    for old_criteria_id, path_ids in duplicates:
        # Keep the criteria for the smallest path_id; clone for the rest.
        for path_id in path_ids[1:]:
            new_code = f"CRIT_orig_{old_criteria_id}_path_{path_id}"

            # Idempotency: a re-run of the migration must reuse the
            # clone created on the first run instead of failing on the
            # ``code`` UNIQUE constraint.
            existing_id = bind.execute(
                text("SELECT id FROM admission_criteria WHERE code = :code"),
                {"code": new_code},
            ).scalar()

            if existing_id is not None:
                new_id = existing_id
            else:
                new_id = bind.execute(
                    text(
                        f"""
                        INSERT INTO admission_criteria (
                            code, {_CLONE_COLUMNS_SQL}
                        )
                        SELECT :new_code, {_CLONE_COLUMNS_SQL}
                        FROM admission_criteria
                        WHERE id = :old_id
                        RETURNING id
                        """
                    ),
                    {"new_code": new_code, "old_id": old_criteria_id},
                ).scalar()

                # Clone subject-group mappings. ``ON CONFLICT DO NOTHING``
                # is paranoia in case the previous step inserted some of
                # them via a partial earlier run.
                bind.execute(
                    text(
                        """
                        INSERT INTO criteria_subject_group (
                            criteria_id, subject_group_id
                        )
                        SELECT :new_id, subject_group_id
                        FROM criteria_subject_group
                        WHERE criteria_id = :old_id
                        ON CONFLICT (criteria_id, subject_group_id)
                        DO NOTHING
                        """
                    ),
                    {"new_id": new_id, "old_id": old_criteria_id},
                )

            bind.execute(
                text(
                    """
                    UPDATE admission_path
                    SET criteria_id = :new_id
                    WHERE id = :path_id
                    """
                ),
                {"new_id": new_id, "path_id": path_id},
            )

    op.create_unique_constraint(
        "uq_admission_path_criteria_id",
        "admission_path",
        ["criteria_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_admission_path_criteria_id",
        "admission_path",
        type_="unique",
    )
