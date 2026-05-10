"""Phase 2 v8.2 PR-2E — widen score precision Numeric(8,2)

Score precision expansion for V-ACT/DGNL methods (max 1200 points)
plus relaxed profile_subject_score CHECK constraint.

Changes:
- ALTER ``admission_criteria.min_score`` Numeric(4,1) → Numeric(8,2)
- ALTER ``admission_criteria.max_possible_score`` Numeric(5,2) → Numeric(8,2)
- ALTER ``admission_criteria.min_subject_score`` Numeric(3,1) → Numeric(8,2)
- ALTER ``profile_subject_score.score`` Numeric(3,1) → Numeric(8,2)
- DROP CHECK ``ck_profile_subject_score_range`` (score 0-10) → relaxed CHECK
  ``ck_profile_subject_score_non_negative`` (score >= 0)

KHÔNG touch ``admission_criteria.min_gpa`` Numeric(3,1) — GPA scale 0-10
unchanged Phase 2.

Revision ID: phase2_04
Revises: phase2_02b_v2
Create Date: 2026-05-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "phase2_04"
down_revision: Union[str, None] = "phase2_02b_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen admission_criteria score columns
    op.alter_column(
        "admission_criteria",
        "min_score",
        existing_type=sa.Numeric(precision=4, scale=1),
        type_=sa.Numeric(precision=8, scale=2),
        existing_nullable=True,
    )
    op.alter_column(
        "admission_criteria",
        "max_possible_score",
        existing_type=sa.Numeric(precision=5, scale=2),
        type_=sa.Numeric(precision=8, scale=2),
        existing_nullable=True,
    )
    op.alter_column(
        "admission_criteria",
        "min_subject_score",
        existing_type=sa.Numeric(precision=3, scale=1),
        type_=sa.Numeric(precision=8, scale=2),
        existing_nullable=True,
    )

    # Widen profile_subject_score.score + relax CHECK
    op.alter_column(
        "profile_subject_score",
        "score",
        existing_type=sa.Numeric(precision=3, scale=1),
        type_=sa.Numeric(precision=8, scale=2),
        existing_nullable=False,
    )
    op.drop_constraint(
        "ck_profile_subject_score_range",
        "profile_subject_score",
        type_="check",
    )
    op.create_check_constraint(
        "ck_profile_subject_score_non_negative",
        "profile_subject_score",
        "score >= 0",
    )


def downgrade() -> None:
    """Downgrade — pre-check guard prevents narrowing với data overflow.

    Numeric(8,2) → Numeric(3,1) requires score < 100. If any existing
    row has score >= 100 (post V-ACT/DGNL ship), narrowing will raise
    overflow. Pre-check raises informative error.
    """
    bind = op.get_bind()

    # Pre-check: profile_subject_score.score < 10 cho original 0-10 CHECK
    overflow_count = bind.execute(
        text(
            "SELECT COUNT(*) FROM profile_subject_score "
            "WHERE score < 0 OR score > 10"
        )
    ).scalar() or 0
    if overflow_count > 0:
        raise RuntimeError(
            f"PR-2E downgrade abort: {overflow_count} profile_subject_score "
            f"rows have score outside 0-10 range. Cannot restore old CHECK. "
            f"Manual data cleanup required."
        )

    # Pre-check: criteria score columns fit Numeric(4,1) max 999.9
    crit_overflow = bind.execute(
        text(
            "SELECT COUNT(*) FROM admission_criteria "
            "WHERE min_score >= 1000 OR max_possible_score >= 1000 "
            "   OR min_subject_score >= 1000"
        )
    ).scalar() or 0
    if crit_overflow > 0:
        raise RuntimeError(
            f"PR-2E downgrade abort: {crit_overflow} admission_criteria rows "
            f"have score columns >= 1000. Cannot narrow Numeric(8,2) → Numeric(4,1)."
        )

    # Restore CHECK constraint
    op.drop_constraint(
        "ck_profile_subject_score_non_negative",
        "profile_subject_score",
        type_="check",
    )
    op.create_check_constraint(
        "ck_profile_subject_score_range",
        "profile_subject_score",
        "score >= 0 AND score <= 10",
    )

    # Narrow column types back
    op.alter_column(
        "profile_subject_score",
        "score",
        existing_type=sa.Numeric(precision=8, scale=2),
        type_=sa.Numeric(precision=3, scale=1),
        existing_nullable=False,
    )
    op.alter_column(
        "admission_criteria",
        "min_subject_score",
        existing_type=sa.Numeric(precision=8, scale=2),
        type_=sa.Numeric(precision=3, scale=1),
        existing_nullable=True,
    )
    op.alter_column(
        "admission_criteria",
        "max_possible_score",
        existing_type=sa.Numeric(precision=8, scale=2),
        type_=sa.Numeric(precision=5, scale=2),
        existing_nullable=True,
    )
    op.alter_column(
        "admission_criteria",
        "min_score",
        existing_type=sa.Numeric(precision=8, scale=2),
        type_=sa.Numeric(precision=4, scale=1),
        existing_nullable=True,
    )
