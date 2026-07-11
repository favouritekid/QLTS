"""PR-B — extend ``admission_profile.status`` CHECK 14 → 15 state ⚠ ONE-WAY.

Adds the intermediate ``withdrawal_pending`` ("Chờ hoàn để rút") state to the
existing CHECK constraint (``ck_admission_profile_status``). It sits between an
in-progress state and terminal ``withdrawn``, held while a refund is processed
so the profile only settles to ``withdrawn`` once the money is actually returned.

14 existing states are preserved verbatim — additive only:
``draft / submitted / approved / rejected / confirmed / enrolled / resubmitted /
overridden / revision_requested / withdrawn / reviewing / result_published /
admitted / waitlisted``.

ONE-WAY rationale + downgrade guard
-----------------------------------

Once this ships the app starts writing rows with ``withdrawal_pending`` via the
withdraw orchestrator. Reverting the CHECK to 14 values would invalidate those
rows — Postgres rejects ``ADD CHECK`` if any existing row violates the
predicate, so the downgrade path defensively inspects current data:

* 0 rows hold ``withdrawal_pending`` → safe rollback, recreate 14-state CHECK.
* ≥1 row holds it → ``RuntimeError``; ops must restore from snapshot, not
  downgrade (a pending withdrawal must be finalized or cancelled first).

Coupled deploy items (BE+FE atomic — Zod strict enum)
-----------------------------------------------------

* ``app/models/admission.py`` ``CheckConstraint`` declaration → 15 states
  (updated in this PR so test DB ``Base.metadata.create_all()`` matches prod).
* ``app/services/admission_state_machine.py`` — ``WITHDRAWAL_PENDING`` enum
  member + transitions.
* FE ``lib/zod/admissions.ts`` strict ``z.enum`` → must include
  ``withdrawal_pending`` BEFORE the BE writes it, or admission list parse fails.

Revision ID: wpend20260710
Revises: assignlogidx20260711
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "wpend20260710"
# Rebased onto assignlogidx20260711 (#473, merged after this branch was cut) so
# the two migrations chain linearly instead of forking two heads off
# zbmonthlyseed20260706 → prevents "Multiple head revisions" at deploy.
down_revision: Union[str, None] = "assignlogidx20260711"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "ck_admission_profile_status"
TABLE = "admission_profile"

# Existing 14-state baseline (10 legacy + 4 Wave-3 milestone) — see
# ``phase1_11_extend_profile_status_check_constraint.py``.
OLD_STATES: tuple[str, ...] = (
    "draft",
    "submitted",
    "approved",
    "rejected",
    "confirmed",
    "enrolled",
    "resubmitted",
    "overridden",
    "revision_requested",
    "withdrawn",
    "reviewing",
    "result_published",
    "admitted",
    "waitlisted",
)

# PR-B intermediate refund-pending state.
NEW_STATES: tuple[str, ...] = (
    "withdrawal_pending",
)

ALL_STATES: tuple[str, ...] = OLD_STATES + NEW_STATES  # 15


def _check_predicate(states: tuple[str, ...]) -> str:
    """Build the SQL CHECK predicate from a state tuple.

    Quoted with ``repr`` so a state name can never break out of the literal
    (states come from this module's own constants, not user input)."""
    return "status IN (" + ", ".join(repr(s) for s in states) + ")"


def upgrade() -> None:
    """Replace 14-state CHECK with 15-state CHECK. Pure additive — every row
    that satisfied the old CHECK still satisfies the new one."""
    op.drop_constraint(CONSTRAINT_NAME, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE,
        _check_predicate(ALL_STATES),
    )


def downgrade() -> None:
    """⚠ ONE-WAY guard — reject downgrade if any row holds
    ``withdrawal_pending``. Otherwise recreate the 14-state CHECK."""
    bind = op.get_bind()
    new_state_count = bind.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {TABLE} "
            f"WHERE {_check_predicate(NEW_STATES)}"
        )
    ).scalar()
    if new_state_count and new_state_count > 0:
        raise RuntimeError(
            f"Cannot downgrade wpend20260710: {new_state_count} row(s) in "
            f"{TABLE} hold 'withdrawal_pending'. This is a ONE-WAY migration — "
            f"finalize/cancel those pending withdrawals or restore from a "
            f"snapshot instead of running `alembic downgrade`."
        )
    op.drop_constraint(CONSTRAINT_NAME, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE,
        _check_predicate(OLD_STATES),
    )
