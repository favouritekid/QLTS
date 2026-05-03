"""phase1_02: add bonus_rule JSONB to admission_method + admission_path

Revision ID: phase1_02
Revises: phase1_01
Create Date: 2026-05-03

#184 Wave 1 PR-1A — second migration in Phase 1 Schema chain
(PLAN §4 line 2632-2634). Two nullable JSONB columns ship together:

* ``admission_method.default_bonus_rule`` — method-level default
  for area / subject bonus calculation. Schema (PLAN line 768-773)::

      {
          "apply_area_bonus": true,
          "apply_subject_bonus": true,
          "max_total_bonus": 2.75
      }

* ``admission_path.bonus_rule_override`` — path-level override
  above the method default. Same JSONB shape; precedence per PLAN
  line 787-789::

      effective_bonus_rule =
          path.bonus_rule_override
          ?? path.admission_method.default_bonus_rule
          ?? {"apply_area_bonus": false, "apply_subject_bonus": false}

The two columns ship in the same migration because they are one
semantic unit (method default + path override) and the PLAN file
title spells them as a pair: ``add_bonus_rule_to_method_and_path``.

No backfill — both columns are nullable from day one. Existing
rows keep ``NULL`` (= bonus disabled per the precedence fallback).
Admin UI populates them once the engine consumer is wired (later
PR; this migration is pure schema additive).

Down-revision chain: ``phase1_19b → phase1_01 → phase1_02``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "phase1_02"
down_revision: Union[str, None] = "phase1_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. AdmissionMethod.default_bonus_rule — method-level default.
    #    JSONB nullable; existing rows stay NULL (= bonus disabled
    #    fallback per the precedence rule).
    op.add_column(
        "admission_method",
        sa.Column(
            "default_bonus_rule",
            JSONB(),
            nullable=True,
            comment=(
                'Method-level default bonus rule. Schema: '
                '{"apply_area_bonus": bool, "apply_subject_bonus": bool, '
                '"max_total_bonus": float}. NULL = bonus disabled fallback. '
                'Path-level override via admission_path.bonus_rule_override.'
            ),
        ),
    )

    # 2. AdmissionPath.bonus_rule_override — path-level override.
    #    Same JSONB shape; NULL = inherit from method default.
    op.add_column(
        "admission_path",
        sa.Column(
            "bonus_rule_override",
            JSONB(),
            nullable=True,
            comment=(
                "Path-level bonus rule override above the method default. "
                "Same JSONB shape as admission_method.default_bonus_rule. "
                "NULL = inherit from admission_method.default_bonus_rule."
            ),
        ),
    )


def downgrade() -> None:
    # Inverse order — drop path override first, then method default.
    op.drop_column("admission_path", "bonus_rule_override")
    op.drop_column("admission_method", "default_bonus_rule")
