# app/services/admission_state_service.py
"""
Admission State Service — single mutation point for ``profile.status``
(Cold Cutover Task #16).

Every legal write to ``AdmissionProfile.status`` MUST flow through
``transition()`` here. The AST lint script
``app/scripts/check_status_assignment.py`` enforces this invariant
across ``app/services/``; the only allow-listed module is this one.

Responsibilities (kept narrow on purpose)
-----------------------------------------
1. Validate the legacy → next-state edge via
   ``admission_state_machine.validate_transition``; convert
   ``ValueError`` → ``BusinessRuleViolation`` so router layers map to
   400 without code duplication.
2. Capture ``old_status`` BEFORE the write (so the audit log records
   the actual prior value, not the post-write ``new_status``).
3. Apply the canonical write triple — ``status`` + ``version += 1`` +
   ``updated_at`` — plus any caller-supplied ``extra_fields`` (e.g.
   ``approved_at`` / ``approved_by_id`` / ``rejection_reason``) in
   the same atomic batch.
4. Log the audit row via ``audit_service.log_status_change``.
5. Dispatch the matching ADMISSION_* event through the B2.3
   ``dispatch_event()`` wrapper. Returns the post-commit callback
   (``None`` for outbox events; ``Awaitable`` for best-effort).

NOT inside ``transition()`` (caller still owns)
-----------------------------------------------
* Pre-write validation (quota gates, IDOR, permission, optimistic
  lock) — they belong in the caller alongside other business rules.
* Pipeline milestone consultation (``_create_admission_milestone
  _consultation``) — uses caller-specific ``actor`` / ``fallback
  _officer_id`` pairs that vary per call site.
* Lead sync via ``sync_lead_from_admission`` — keeps the sync explicit
  in caller flow + lets caller pass a tailored ``reason`` string.
* Mutation-response field population (``_populate_response_fields``).
* Legacy notification bundle (``APPLICATION_STATUS_CHANGED`` +
  ``LEAD_STATUS_CHANGED``) — kept side-by-side with the new
  ``ADMISSION_*`` dispatch in #16; Phase 3 will retire the legacy
  bundle in a separate task.

Deferred ADMISSION_* events (4 of 12)
-------------------------------------
The B2.1 catalog ships 12 ``ADMISSION_*`` events; #16 wires only the
8 with a current legacy writer. The four below have no legacy write
site and therefore no ``LEGACY_STATUS_TO_EVENT`` row; they will get
their dispatch sites when the choice-engine writers ship in Phase 3:

* ``ADMISSION_RESULT_PUBLISHED`` (T6) — admin batch broadcast.
* ``ADMISSION_DECISION_WAITLISTED`` (T8) — choice-engine waitlist.
* ``ADMISSION_WAITLIST_PROMOTED`` (T10) — admin promote-from-waitlist.
* ``ADMISSION_ROLLED_BACK`` (T17) — admin rollback (NOT the same as
  legacy ``overridden`` — overridden is force-approve, T17 is undo).

The coverage script (``check_notification_event_coverage.py``)
exposes these via the ``--allow-deferred`` flag added in #16; the
``DEFERRED_ADMISSION_EVENTS`` constant below is the single source of
truth and is locked by
``tests/unit/test_check_notification_event_coverage_deferred.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, TYPE_CHECKING

import structlog

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.events import SystemEvents
from ..utils.exceptions import BusinessRuleViolation
from .admission_state_machine import validate_transition

if TYPE_CHECKING:
    from ..models import AdmissionProfile, User

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Coverage-script dispatch anchors
# ---------------------------------------------------------------------------
#
# ``app/scripts/check_notification_event_coverage.py`` greps for the literal
# pattern ``event=SystemEvents.<NAME>`` to count dispatch sites; the grep
# skips ``#``-comment lines but DOES scan triple-quoted string bodies.
# ``transition()`` below resolves the event from ``LEGACY_STATUS_TO_EVENT``
# at runtime, so the actual call reads ``event=event`` (a variable) and
# the grep can't see the resolved enum.
#
# This module-level docstring is the explicit dispatch anchor — each
# ``event=SystemEvents.<NAME>`` line below is what the grep counts. Keep
# in sync with ``LEGACY_STATUS_TO_EVENT`` (parity locked by
# ``tests/unit/test_admission_state_service_event_mapping.py``). Do NOT
# delete a line without removing the matching mapping row, or the
# coverage script will keep reporting ``ok`` for an event whose runtime
# dispatch was actually removed.
_DISPATCH_ANCHORS = """
event=SystemEvents.ADMISSION_PROFILE_SUBMITTED            T1
event=SystemEvents.ADMISSION_REVISION_REQUESTED           T3/T4
event=SystemEvents.ADMISSION_RESUBMITTED                  T5
event=SystemEvents.ADMISSION_DECISION_ADMITTED            T7 (approved + overridden)
event=SystemEvents.ADMISSION_DECISION_REJECTED            T9
event=SystemEvents.ADMISSION_CONFIRMED                    T12
event=SystemEvents.ADMISSION_ENROLLED                     T13
event=SystemEvents.ADMISSION_WITHDRAWN                    T14/T15/T16
"""


# ---------------------------------------------------------------------------
# Legacy status → ADMISSION_* event mapping (8 distinct events from 9 entries)
# ---------------------------------------------------------------------------
#
# 9 entries / 8 distinct events — ``approved`` and ``overridden`` both
# fire ``ADMISSION_DECISION_ADMITTED`` (T7); the override case carries
# ``override=True`` in payload metadata so consumers can branch on the
# admin-force-approve vs normal-approve path.
#
# The 4 missing entries (T6 / T8 / T10 / T17) are tracked explicitly
# in ``DEFERRED_ADMISSION_EVENTS`` below.
LEGACY_STATUS_TO_EVENT: Dict[str, SystemEvents] = {
    "submitted":          SystemEvents.ADMISSION_PROFILE_SUBMITTED,        # T1
    "revision_requested": SystemEvents.ADMISSION_REVISION_REQUESTED,       # T3/T4
    "resubmitted":        SystemEvents.ADMISSION_RESUBMITTED,              # T5
    "approved":           SystemEvents.ADMISSION_DECISION_ADMITTED,        # T7
    "overridden":         SystemEvents.ADMISSION_DECISION_ADMITTED,        # T7 + override=True
    "rejected":           SystemEvents.ADMISSION_DECISION_REJECTED,        # T9
    "confirmed":          SystemEvents.ADMISSION_CONFIRMED,                # T12
    "enrolled":           SystemEvents.ADMISSION_ENROLLED,                 # T13
    "withdrawn":          SystemEvents.ADMISSION_WITHDRAWN,                # T14/T15/T16
}


# Events tracked by the B2.1 catalog but with no current legacy
# writer. The coverage script's ``--allow-deferred`` flag accepts
# this exact set and prints them in the summary so operators know
# the gap is intentional, not a missed wire.
DEFERRED_ADMISSION_EVENTS: frozenset[str] = frozenset({
    "ADMISSION_RESULT_PUBLISHED",     # T6 — admin batch broadcast
    "ADMISSION_DECISION_WAITLISTED",  # T8 — choice-engine waitlist
    "ADMISSION_WAITLIST_PROMOTED",    # T10 — promote-from-waitlist
    "ADMISSION_ROLLED_BACK",          # T17 — admin rollback (≠ overridden)
})


# ---------------------------------------------------------------------------
# transition() — THE single mutation point
# ---------------------------------------------------------------------------


async def transition(
    db: AsyncSession,
    profile: "AdmissionProfile",
    new_status: str,
    *,
    actor: Optional["User"] = None,
    reason: Optional[str] = None,
    source: str = "api",
    extra_fields: Optional[Dict[str, Any]] = None,
    event_metadata: Optional[Dict[str, Any]] = None,
    skip_audit: bool = False,
    skip_dispatch: bool = False,
) -> Tuple["AdmissionProfile", Optional[Callable[[], Awaitable[None]]]]:
    """Apply ``profile.status = new_status`` atomically with audit + dispatch.

    Args:
        db: Caller's async DB session. Service flushes? No — caller
            still owns flush/commit per architecture V3. The audit
            row + outbox row (if any) land in the caller's session.
        profile: ``AdmissionProfile`` to mutate. Status field is read
            BEFORE write to capture ``old_status``.
        new_status: Target status string. MUST be a value the state
            machine recognises and reachable from ``profile.status``;
            otherwise raises ``BusinessRuleViolation``.
        actor: User performing the transition (officer / manager /
            admin). ``None`` for system / public flows (e.g. magic-
            link confirm has no authenticated actor).
        reason: Free-text reason logged on the audit row + forwarded
            to lead-sync if the caller routes through it later.
        source: Audit source tag (``"api"`` / ``"magic_link"`` /
            ``"system"`` / ``"bulk"`` / ``"override"``). Caller picks.
        extra_fields: Per-status timestamps + IDs the caller wants
            applied in the same atomic write — e.g. ``approved_at`` /
            ``approved_by_id`` / ``rejection_reason``. Each key must
            be a valid column on ``AdmissionProfile`` (validated by
            ORM at flush time, not here).
        event_metadata: Extra payload keys forwarded to the
            ``ADMISSION_*`` dispatch (e.g. ``{"override": True}`` for
            the overridden → T7 path so consumers can distinguish).
            Merged INTO the base payload; do not pass keys that
            collide with the canonical fields below.
        skip_audit: Bypass the ``audit_service.log_status_change``
            call. Use when the caller already writes a richer audit
            row via ``audit_service.log_changes`` (e.g. ``override
            _profile`` per ADM-014 captures status + version +
            override_reason + bypass_rules in a single change-set
            row, so a second log_status_change row would just be
            duplicate noise). Production callers should set this
            ONLY when an alternative audit row is written in the
            same transaction.
        skip_dispatch: Bypass the ``dispatch_event()`` call. Reserved
            for tests + maintenance scripts that mutate status
            without firing notifications, plus the ``submit_and
            _evaluate`` flow which returns a plain dict (no callback
            channel) and dispatches the matching event from the
            router after commit. Production code MUST NOT set this
            outside those two cases.

    Returns:
        ``(profile, post_commit_callback)`` per the V3 service
        contract. ``post_commit_callback`` is the value
        ``dispatch_event()`` returned: ``None`` for outbox events
        (worker drains later), ``Callable`` for best-effort events
        (router awaits after ``db.commit()``).

    Raises:
        BusinessRuleViolation: If ``validate_transition(profile.status,
                               new_status)`` rejects the edge. Wraps
                               the state machine's ``ValueError``
                               with the same message.

    Notes:
        * No ``await db.flush()`` here — caller flushes when ready,
          typically after pipeline-sync + lead-sync + bundle dispatch.
        * The legacy notification bundle (APPLICATION_STATUS_CHANGED
          + LEAD_STATUS_CHANGED) stays in the caller for #16; Phase 3
          will retire it.
    """
    # 1. Validate transition via the state machine.
    try:
        validate_transition(profile.status, new_status)
    except ValueError as e:
        raise BusinessRuleViolation(str(e))

    # 2. Capture old status BEFORE the write — required for the audit
    #    row and the dispatch payload's ``old_status`` field.
    old_status = profile.status

    # 3. Canonical write triple + caller-supplied extras.
    now = datetime.now(timezone.utc)
    profile.status = new_status
    profile.version += 1
    profile.updated_at = now

    if extra_fields:
        for field_name, value in extra_fields.items():
            setattr(profile, field_name, value)

    # 4. Audit log — single source of truth for status-change history,
    # except when caller writes a richer log_changes row (override).
    if not skip_audit:
        from . import audit_service
        await audit_service.log_status_change(
            db,
            "AdmissionProfile",
            profile.id,
            old_status=old_status,
            new_status=new_status,
            actor_user_id=actor.id if actor else None,
            reason=reason,
            source=source,
        )

    # 5. ADMISSION_* event dispatch via B2.3 wrapper.
    callback: Optional[Callable[[], Awaitable[None]]] = None
    if not skip_dispatch:
        event = LEGACY_STATUS_TO_EVENT.get(new_status)
        if event is not None:
            payload: Dict[str, Any] = {
                "application_id": profile.id,
                "lead_id": profile.lead_id,
                "old_status": old_status,
                "new_status": new_status,
                "actor_id": actor.id if actor else None,
            }
            if event_metadata:
                # Caller-supplied metadata wins on conflict (e.g.
                # override=True for overridden → T7), but the canonical
                # keys above stay authoritative for downstream consumers.
                payload = {**payload, **event_metadata}

            # Dedupe key: ``admission:{id}:{new_status}`` — distinct per
            # transition, even when two new_status values map to the
            # same event (approved + overridden both → T7 but get
            # distinct dedupe rows so neither suppresses the other).
            from .notification_dispatcher import dispatch_event
            callback = await dispatch_event(
                db,
                event=event,
                payload=payload,
                dedupe_key=f"admission:{profile.id}:{new_status}",
            )

    # ``event`` is structlog's internal positional kwarg name (it
    # holds the log message), so the dispatched-event identifier is
    # logged under ``dispatched_event`` to avoid the name clash.
    _logged_event = LEGACY_STATUS_TO_EVENT.get(new_status)
    log.info(
        "admission_state_service.transition",
        profile_id=profile.id,
        old_status=old_status,
        new_status=new_status,
        actor_id=actor.id if actor else None,
        source=source,
        dispatched_event=_logged_event.name if (not skip_dispatch and _logged_event is not None) else None,
        outbox_routed=callback is None and not skip_dispatch and _logged_event is not None,
    )

    return profile, callback


__all__ = [
    "DEFERRED_ADMISSION_EVENTS",
    "LEGACY_STATUS_TO_EVENT",
    "transition",
]
