"""phase1_08a: rename JSONB key apply_subject_bonus -> apply_object_bonus

Revision ID: phase1_08a
Revises: qae2e02
Create Date: 2026-05-17

#184 Q9 #07 Wave A — Foundation rename for Priority Bonus System.

Background
----------

``BonusRuleOverride`` Pydantic schema (``app/schemas/admission_path.py``)
shipped in phase1_02 with field ``apply_subject_bonus`` whose docstring
already said "Apply per-subject bonus (priority objects 01..07)" — the
intent was UT đối tượng (priority objects per Thông tư 05/2021-BLĐTBXH
Phụ lục 01) but the field name said ``subject``. PR1 of Q9 #07 corrects
this naming bug across the schema + JSONB key.

Why a migration at all
----------------------

Verified via SSH on prod 2026-05-17:
  - admission_method.default_bonus_rule:  0 rows non-null, 0 with old key
  - admission_path.bonus_rule_override:   52 rows non-null but all are
                                          JSON null literal — 0 with key

So **this migration is a no-op on production today**. It ships anyway
as a DEFENSIVE forward-compat shim: between when this PR merges and
when prod deploys, an admin could conceivably set ``bonus_rule_override``
via the path config UI using the old key. The migration runs at
``alembic upgrade head`` during the deploy entrypoint and converts any
such row before the Pydantic schema (extra="forbid") tries to load it.

Idempotency
-----------

The WHERE clause ``... ? 'apply_subject_bonus'`` is the JSONB key-exists
operator. Re-running the migration is a no-op once the key has been
renamed, because the predicate no longer matches. Both upgrade and
downgrade are guarded the same way.

Down-revision chain: ``qae2e02 -> phase1_08a``.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "phase1_08a"
down_revision: Union[str, None] = "qae2e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename JSONB key apply_subject_bonus -> apply_object_bonus on both
    # tables that carry the BonusRule shape. The expression is:
    #   (jsonb - 'old_key') || jsonb_build_object('new_key', jsonb->'old_key')
    # which strips the old key and adds the new key with the same value
    # in one atomic JSONB rebuild. The WHERE clause makes the operation
    # idempotent and safe to re-run.
    op.execute(
        """
        UPDATE admission_method
        SET default_bonus_rule =
            (default_bonus_rule - 'apply_subject_bonus')
            || jsonb_build_object(
                'apply_object_bonus',
                default_bonus_rule -> 'apply_subject_bonus'
            )
        WHERE default_bonus_rule IS NOT NULL
          AND default_bonus_rule ? 'apply_subject_bonus'
        """
    )
    op.execute(
        """
        UPDATE admission_path
        SET bonus_rule_override =
            (bonus_rule_override - 'apply_subject_bonus')
            || jsonb_build_object(
                'apply_object_bonus',
                bonus_rule_override -> 'apply_subject_bonus'
            )
        WHERE bonus_rule_override IS NOT NULL
          AND bonus_rule_override ? 'apply_subject_bonus'
        """
    )


def downgrade() -> None:
    # Inverse rename — apply_object_bonus -> apply_subject_bonus.
    op.execute(
        """
        UPDATE admission_method
        SET default_bonus_rule =
            (default_bonus_rule - 'apply_object_bonus')
            || jsonb_build_object(
                'apply_subject_bonus',
                default_bonus_rule -> 'apply_object_bonus'
            )
        WHERE default_bonus_rule IS NOT NULL
          AND default_bonus_rule ? 'apply_object_bonus'
        """
    )
    op.execute(
        """
        UPDATE admission_path
        SET bonus_rule_override =
            (bonus_rule_override - 'apply_object_bonus')
            || jsonb_build_object(
                'apply_subject_bonus',
                bonus_rule_override -> 'apply_object_bonus'
            )
        WHERE bonus_rule_override IS NOT NULL
          AND bonus_rule_override ? 'apply_object_bonus'
        """
    )
