"""cleanup phase1_19c UPPERCASE orphan notification rows (rule + action + template)

Revision ID: cleanup_upper_notif
Revises: qa20260522_tighten_lead_denies
Create Date: 2026-05-23

PR-1 Commit 2 — surgical cleanup of dead-weight rows seeded by
``phase1_19c_seed_event_catalog_db_rows`` which used UPPERCASE event
names (``"ADMISSION_PROFILE_SUBMITTED"`` etc., see that migration's
``MILESTONE_EVENTS`` tuple lines 77-198) while ``SystemEvents.value`` —
the dispatcher key — is lowercase. ``tasks/admission_tasks.py:348`` uses
``WHERE event = event_value`` exact match → the 12 UPPERCASE rule rows +
their child notification_action rows + the 12 ``TPL_ADMISSION_*`` upper
template rows have never fired and never will. Harmless dead weight that
clutters every diagnostic SELECT.

Idempotent: each DELETE uses a strict predicate (``LIKE 'ADMISSION\\_%'``
with explicit ``ESCAPE '\\'`` so the literal underscore is not the SQL
wildcard, AND ``event != lower(event)`` to require at least one upper-
case letter). Running upgrade twice DELETEs nothing on the second run.

Scope (3 tables, in FK-safe order):

  1. notification_action — child of notification_rule (rule_id FK).
     The schema does NOT have ON DELETE CASCADE on that FK on prod;
     delete children FIRST.
  2. notification_rule — the 12 uppercase event rows.
  3. notification_template — the 12 ``TPL_ADMISSION_*`` upper template
     rows. No FK from notification_rule.template_id to template (per
     phase1_19c insert which stores ``template_id=NULL``).

downgrade is a no-op: the dead rows had no business meaning. To re-seed
the lowercase variants (the live ones), re-run phase1_19c at upgrade
head — its WHERE NOT EXISTS / ON CONFLICT guards keep that body
idempotent.

Per memory ``migration-predicate-safety``: strict predicate verified
on dev DB before merge; SSH prod preflight queries the same predicate
to confirm the orphan counts match expectations (12 rule, 12 template,
~29 action per phase1_19c's 7 channels × subset of 12 events).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cleanup_upper_notif"
down_revision: Union[str, None] = "qa20260522_tighten_lead_denies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Predicates kept as module constants so the count-query, the delete,
# and the test all reference one source of truth.
_RULE_PREDICATE = (
    "event LIKE 'ADMISSION\\_%' ESCAPE '\\' "
    "AND event != lower(event)"
)
_TEMPLATE_PREDICATE = (
    "template_code LIKE 'TPL\\_ADMISSION\\_%' ESCAPE '\\' "
    "AND template_code != lower(template_code)"
)


def upgrade() -> None:
    conn = op.get_bind()

    # --- Step 1: count what we are about to delete (logged in alembic output) ---
    rule_count = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM notification_rule WHERE {_RULE_PREDICATE}")
    ).scalar() or 0
    template_count = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM notification_template WHERE {_TEMPLATE_PREDICATE}")
    ).scalar() or 0

    # --- Step 2: collect rule IDs so children can be deleted explicitly
    # (FK does not declare ON DELETE CASCADE on prod schema) ---
    rule_ids_rows = conn.execute(
        sa.text(f"SELECT id FROM notification_rule WHERE {_RULE_PREDICATE}")
    ).fetchall()
    rule_ids = [row[0] for row in rule_ids_rows]

    action_count = 0
    if rule_ids:
        # --- Step 3: delete notification_action children first (FK) ---
        action_result = conn.execute(
            sa.text(
                "DELETE FROM notification_action WHERE rule_id = ANY(:ids)"
            ),
            {"ids": rule_ids},
        )
        action_count = action_result.rowcount or 0

        # --- Step 4: delete notification_rule parents ---
        conn.execute(
            sa.text(f"DELETE FROM notification_rule WHERE {_RULE_PREDICATE}")
        )

    # --- Step 5: delete notification_template (no FK from rule.template_id) ---
    if template_count:
        conn.execute(
            sa.text(f"DELETE FROM notification_template WHERE {_TEMPLATE_PREDICATE}")
        )

    print(
        f"cleanup_uppercase_orphan_notification_rows: "
        f"rule={rule_count} action={action_count} template={template_count}"
    )


def downgrade() -> None:
    # Intentional no-op. The deleted rows were dead weight — never matched
    # by the dispatcher (event-value comparison is case-sensitive lowercase)
    # — and re-creating them only restores the noise. If someone genuinely
    # needs the lowercase rows back, re-running phase1_19c at head is the
    # canonical idempotent route (it skips already-present rows via its
    # WHERE NOT EXISTS / ON CONFLICT guards).
    pass
