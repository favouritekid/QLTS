"""phase1_19c5: lowercase ADMISSION_* notification_rule.event (chain integrity fix)

Inserted 2026-05-25 between ``phase1_19c`` (UPPERCASE seed) and ``phase1_16``
to close the recurring class of bugs documented in:

* memory ``worktree-stack-bootstrap`` — fresh alembic fails phase3_01
* memory ``migration-systemevents-value-case`` — enum case canon rule
* PR #263 hotfix (2026-05-12) — phase3_01 prod deploy fail + auto-rollback
* PR #330 nightly-regression CI failure cycle (2026-05-25)

ROOT CAUSE
----------
``phase1_19c`` seeds 12 ADMISSION_* events into ``notification_rule`` with
**UPPERCASE** enum NAMES (legacy convention). The modern canonical form is
``SystemEvents.X.value`` lowercase (memory
``migration-systemevents-value-case``). ``phase3_01`` (Phase 3 PR-3A) has
a pre-flight assertion requiring 5 specific events in LOWERCASE and
hard-aborts the migration if not found::

    RuntimeError: Pre-flight fail: 0/5 system-critical events found
    trong notification_rule.

Production accumulated both cases over time because ``sync_notification_rules``
(entrypoint, runs after alembic each deploy) inserts the lowercase variants
on every startup. PR #263 hotfixed phase3_01 to expect LOWERCASE — but the
ROOT CAUSE (chain has no step that produces lowercase before phase3_01
runs from a fresh DB) was left unfixed. Result: prod deploys work after
the first successful deploy (lowercase rows persist in DB across deploys),
but **fresh DB scenarios remain broken**:

* Fresh CI nightly-regression (this PR's verify runs #3 + #4)
* Worktree bootstrap from clean alembic chain
* Disaster recovery from backups predating the first successful phase3_01
  run

THIS MIGRATION
--------------
A single UPDATE that converts all ``notification_rule.event`` values
matching ``'^ADMISSION_'`` (UPPERCASE) to lowercase. Idempotent — safe to
run on prod (currently 0 UPPERCASE rows per SSH verify 2026-05-25
``SELECT COUNT(*)... event != lower(event)`` = 0; UPDATE matches 0 rows).

NOT touched (out of scope):
* ``notification_template.template_code`` — prod has 0 ``tpl_admission%``
  templates anyway (PR #327 cleanup deleted them); admin Config workflow
  re-seeds via different mechanism.
* ``notification_action.template_code`` — 2 orphan UPPERCASE rows exist
  on prod (CONFIRMATION_REMINDER series) but reference templates that
  no longer exist; that's an independent cleanup task, not in
  phase3_01's pre-flight assertion.

Per memory ``migration-predicate-safety``: predicate is strict
(``event ~ '^ADMISSION_'`` — case-sensitive regex anchored to start) so
this never touches non-target rows even if other event namespaces start
with ``admission_``.

DOWNGRADE
---------
Reverse to UPPERCASE for rollback. Idempotent — matches 0 rows on
already-uppercase state.

Revision ID: phase1_19c5
Revises: phase1_19c
Create Date: 2026-05-25
"""
from typing import Sequence, Union

from alembic import op


revision: str = "phase1_19c5"
down_revision: Union[str, None] = "phase1_19c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE notification_rule
        SET event = lower(event),
            updated_at = NOW()
        WHERE event ~ '^ADMISSION_'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE notification_rule
        SET event = upper(event),
            updated_at = NOW()
        WHERE event ~ '^admission_'
        """
    )
