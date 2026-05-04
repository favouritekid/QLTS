"""phase1_08: add uses_choice_engine flag to admission_profile

Revision ID: phase1_08
Revises: phase1_07b
Create Date: 2026-05-04

#184 Wave 1 PR-1D — eighth migration in Phase 1 Schema chain
(PLAN §4 line 2695-2697 + line 821-826). Single-column add,
pure additive.

Schema
------
* ``admission_profile.uses_choice_engine`` BOOLEAN NOT NULL
  DEFAULT false. Server default backfills every existing row to
  ``false`` at ALTER time (PG fast path on default, no row-by-row
  UPDATE). Stays NOT NULL post-migration so the state machine
  router never has to handle a NULL flag.

Semantic
--------
Per PLAN line 821-826:

* ``false`` → state machine cũ (legacy single-NV profile flow).
  Legacy ``ProfileSubjectScore`` writes are valid; profile uses
  the 10-state legacy lifecycle.
* ``true`` → state machine mới (multi-NV choice engine).
  Profile must use ``AdmissionProfileChoice`` + ``ProfileChoiceScore``;
  legacy single-NV writes are rejected.

Why a flag instead of count(choices) check
------------------------------------------
PLAN line 824-826: backfill in Phase 3 will create one
``AdmissionProfileChoice`` per existing profile so the choice
table is populated for every row. After that, count(choices) >= 1
for ALL profiles, so it cannot distinguish legacy from new.
``uses_choice_engine`` is the explicit flag.

Down-revision chain: ``phase1_07b → phase1_08``.

Idempotency
-----------
``server_default="false"`` ensures alembic ALTER is the canonical
backfill — no separate UPDATE statement, no idempotency guard
needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "phase1_08"
down_revision: Union[str, None] = "phase1_07b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admission_profile",
        sa.Column(
            "uses_choice_engine",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment=(
                "Phase 3 multi-NV gate. false = legacy single-NV "
                "ProfileSubjectScore flow; true = AdmissionProfileChoice "
                "+ ProfileChoiceScore flow."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("admission_profile", "uses_choice_engine")
