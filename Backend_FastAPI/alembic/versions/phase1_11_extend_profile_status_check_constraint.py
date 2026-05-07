"""Wave 3-A / M-1-11 — extend ``admission_profile.status`` CHECK 10 → 14 state ⚠ ONE-WAY.

Adds 4 milestone states to the existing CHECK constraint
(``ck_admission_profile_status``):

* ``reviewing``         — profile is under manager review (post-submit, pre-decision)
* ``result_published``  — score published before per-candidate decision
* ``admitted``          — choice-engine admit decision (replaces ``approved`` for
                          choice-engine profiles per PLAN §3.3.b workflow remap)
* ``waitlisted``        — choice-engine waitlist decision

10 legacy states are preserved verbatim — additive only:
``draft / submitted / approved / rejected / confirmed / enrolled /
resubmitted / overridden / revision_requested / withdrawn``.

ONE-WAY rationale + downgrade guard
-----------------------------------

After this migration ships, the application will start writing rows with the
4 new state values via the choice-engine workflow. Reverting the CHECK to 10
values would invalidate those rows — Postgres rejects ``ADD CHECK`` if any
existing row violates the predicate, so the downgrade path defensively
inspects current data:

* If 0 rows hold a new-state value → safe rollback, recreate 10-state CHECK.
* If ≥1 row holds a new-state value → ``RuntimeError`` with a clear message;
  ops must restore from snapshot, not downgrade.

Coupled deploy items (not in this migration; ship in Wave 3 atomic deploy)
-------------------------------------------------------------------------

* ``app/models/admission.py:48-50`` — ``CheckConstraint`` declaration string
  must be updated to 14 states so test DB (``Base.metadata.create_all()``)
  matches the prod schema. Updated in this PR (model + migration are the BE
  half of "BE+FE Zod 14 state strict atomic deploy" per PLAN line 3471).
* ``app/services/lead_admission_sync.py`` — already covers the 4 new states
  per ``#15`` workflow remap (memory ``project_184_phase1_schema_wave_plan``
  prerequisites).
* FE Stage 3 strict Z.enum 14-state lock — separate sub-PR (3-B).

Live prod baseline (dev DB post-import 2026-05-05)
---------------------------------------------------

Smoke verified 0 break risk: ``SELECT status, COUNT(*) FROM
admission_profile GROUP BY status`` → ``draft=8, submitted=1`` (9 profiles
total, none in any new-state). Upgrade is purely additive, downgrade is
trivially safe today.

Idempotent guards
-----------------

A CHECK constraint must be DROPPED + RECREATED in one statement pair
(Postgres does not support ``ALTER CHECK``). Idempotency is achieved at the
constraint level:

* ``upgrade()`` — drop current constraint, recreate with 14 values. Safe to
  re-run; the second run drops the (already-14) constraint and recreates
  with the same 14.
* ``downgrade()`` — defensive guard runs ``SELECT COUNT`` for new-state
  rows. If safe, drop + recreate with 10 values.

Revision ID: phase1_11
Revises: phase1_19e
Create Date: 2026-05-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "phase1_11"
down_revision: Union[str, None] = "phase1_19e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "ck_admission_profile_status"
TABLE = "admission_profile"

# Existing 10-state baseline — verified live 2026-05-05 against prod-cloned
# dev DB (constraint def + GROUP BY status both confirm).
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
)

# 4 milestone states added in Wave 3 — choice-engine workflow per PLAN
# §3.3.b workflow remap.
NEW_STATES: tuple[str, ...] = (
    "reviewing",
    "result_published",
    "admitted",
    "waitlisted",
)

ALL_STATES: tuple[str, ...] = OLD_STATES + NEW_STATES  # 14


def _check_predicate(states: tuple[str, ...]) -> str:
    """Build the SQL CHECK predicate from a state tuple.

    Quoted with ``repr`` so SQL injection via state name is impossible
    (states come from this module's own constants, not user input — but
    using ``repr`` is the principled shape regardless)."""
    return "status IN (" + ", ".join(repr(s) for s in states) + ")"


def upgrade() -> None:
    """Replace 10-state CHECK with 14-state CHECK. Pure additive — every
    row that satisfied the old CHECK still satisfies the new one."""
    op.drop_constraint(CONSTRAINT_NAME, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE,
        _check_predicate(ALL_STATES),
    )


def downgrade() -> None:
    """⚠ ONE-WAY guard — reject downgrade if any row holds a new-state
    value. Otherwise recreate 10-state CHECK."""
    bind = op.get_bind()
    new_state_count = bind.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {TABLE} "
            f"WHERE {_check_predicate(NEW_STATES)}"
        )
    ).scalar()
    if new_state_count and new_state_count > 0:
        raise RuntimeError(
            f"Cannot downgrade phase1_11: {new_state_count} row(s) in "
            f"{TABLE} hold a new-state value "
            f"({', '.join(NEW_STATES)}). This is a ONE-WAY migration — "
            f"restore from a pre-Wave-3 snapshot instead of running "
            f"`alembic downgrade`."
        )
    op.drop_constraint(CONSTRAINT_NAME, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE,
        _check_predicate(OLD_STATES),
    )
