"""Wave 5-C / M-1-19e — notification rule seed marker (scope absorbed by phase1_19c).

PLAN deviation (chốt 2026-05-05 Codex round 21 — Wave 5-C scope review)
======================================================================

The spec slot ``phase1_19d_seed_notification_rules`` (renamed to
``phase1_19e`` per Q2 cascade chốt 2026-05-03 — see §8 line 4513
deviation log) was originally scoped as "owner channel routing rules per
audience" per PLAN line 3816. After Codex round 18 chốt scope b2,
``phase1_19c`` (Wave 5-A, PR #213 squash ``9af7510b``) was promoted to
ship the FULL rule set instead of just ``notification_rule`` shells:

* 12 ``notification_rule`` rows — one per ``ADMISSION_*`` milestone
  event with resolver routing (11 ``lead_owner`` for candidate-facing
  events, 1 ``specific_users`` for ``ADMISSION_REVISION_REQUESTED``
  staff queue).
* 12 ``notification_template`` rows — one per event with
  ``supported_channels`` JSONB array carrying the per-channel routing.
* 29 ``notification_action`` rows — per-channel step entries
  (``2 channels × 7 events + 3 channels × 5 events = 29``) which IS
  the "channel routing rules per audience" surface that the spec slot
  was reserving for. Each action row enumerates ``rule_id, step,
  channel, template_code`` so the dispatcher can fan out to
  browser/email/zalo per audience without a second seed pass.

The 12 events seeded by ``phase1_19c``:

1. ADMISSION_PROFILE_SUBMITTED
2. ADMISSION_REVISION_REQUESTED
3. ADMISSION_RESUBMITTED
4. ADMISSION_RESULT_PUBLISHED
5. ADMISSION_DECISION_ADMITTED
6. ADMISSION_DECISION_WAITLISTED
7. ADMISSION_DECISION_REJECTED
8. ADMISSION_WAITLIST_PROMOTED
9. ADMISSION_CONFIRMED
10. ADMISSION_ENROLLED
11. ADMISSION_WITHDRAWN
12. ADMISSION_ROLLED_BACK

This migration body is a no-op marker — it locks the alembic chain
revision point (``phase1_19e`` is the last Wave 5 sub-PR per cascade)
and documents that the spec slot's payload was absorbed upstream. A
non-no-op body would attempt to INSERT the same rule rows
``phase1_19c`` already inserted, hitting the WHERE NOT EXISTS guard
and silently no-op'ing — but with the noise of a duplicate-attempt
SQL trace in alembic logs. Cleaner to ship the absorption as an
intentional empty marker than to ship a redundant SQL pass.

Future events (LEAD_*, PAYMENT_*, CONSULTATION_*, etc.) remain owned
by ``app/scripts/seed_notification_rules.py`` (catalog-driven, runs
post-deploy). Phase 1 #19 chain only seeds the 12 admission milestone
events because they are version-controlled critical-path for the cold
cutover (RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false flag during the
cutover skips the script — only what's seeded in alembic is on prod).

Wave 5 COMPLETE post-merge
==========================

* Wave 5-A ✅ ``phase1_19c`` (event_catalog seed, PR #213, squash
  ``9af7510b``) — owns 12 ADMISSION_* rule + template + action.
* Wave 5-D ✅ ``phase1_16`` (archived_admission_profile, PR #214,
  squash ``1989bd03``) — empty archive table mirror.
* Wave 5-E ✅ ``phase1_17`` (archived_outbox, PR #215, squash
  ``0b17f394``) — empty archive table mirror.
* Wave 5-B ✅ ``phase1_19d`` (beat archive task, PR #216, squash
  ``ef6a8b6d``) — Sunday 02:00 VN weekly cron + paired Celery code.
* Wave 5-C ✅ ``phase1_19e`` (this migration) — marker confirming the
  Phase 1 #19 chain reaches its terminal revision; rule seed already
  covered by Wave 5-A.

Alembic head after this migration: ``phase1_19e``. The next Phase 1
chain advance is Wave 3 ONE-WAY ⚠ (``phase1_11`` status CHECK extend +
``phase1_12`` backfill + ``phase1_15a`` lead_id UNIQUE swap +
``phase1_18`` confirmation token multi-action) which is gated on
staging clone D12-D14 readiness.

Revision ID: phase1_19e
Revises: phase1_19d
Create Date: 2026-05-05
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "phase1_19e"
down_revision: Union[str, None] = "phase1_19d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Marker — payload absorbed by ``phase1_19c`` (Wave 5-A). The 12
    ADMISSION_* notification_rule + notification_template +
    notification_action rows that this slot was reserving for are
    already in the DB after ``phase1_19c`` ran (PR #213 squash
    ``9af7510b``). See module docstring for the deviation log."""
    pass


def downgrade() -> None:
    """No-op — the rule seed itself is owned by ``phase1_19c``'s
    downgrade, not this slot."""
    pass
