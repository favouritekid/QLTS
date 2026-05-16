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

# Phase 3 PR-3B Sub-2: pair lookup `Tuple[str, str]` cho source-aware events
# (vd T10 waitlisted→admitted fires WAITLIST_PROMOTED, NOT generic ADMITTED).

import structlog

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.events import SystemEvents
from ..utils.exceptions import BusinessRuleViolation
from .admission_state_machine import validate_transition

if TYPE_CHECKING:
    from ..models import AdmissionProfile, User

log = structlog.get_logger(__name__)


def _resolve_status_history_actor(
    actor: Optional["User"],
    source: str,
    profile_lead_id: int,
) -> Dict[str, Any]:
    """Resolve the 5 actor-related fields on
    ``AdmissionProfileStatusHistory`` per ``ck_status_history_actor
    _consistency``.

    Three valid combinations:

    * ``system`` — both FKs NULL (cron, scheduler, automated cleanup).
    * ``officer`` / ``admin`` — ``transitioned_by_user_id`` set, lead
      FK NULL (staff actions via API).
    * ``candidate`` — ``transitioned_by_lead_id`` set, user FK NULL
      (magic-link confirm / withdraw via public route).

    Per PLAN line 1062 v2.9 contract — the legacy
    ``transitioned_by_role`` ENUM has only 4 values; ``manager`` and
    ``accountant`` (which exist on the modern 6-value
    ``actor_actual_role`` ENUM) fold to the closest legacy bucket
    (manager → admin, accountant → officer). The 6-value
    ``actor_actual_role`` retains the original role for audit-of-truth
    queries; ``effective_transition_role`` (4 values) mirrors RBAC
    elevation (manager → admin scope, accountant → officer scope).
    """
    if actor is None:
        if source == "magic_link":
            # Candidate transition (no User row, has Lead row).
            return {
                "transitioned_by_role": "candidate",
                "actor_actual_role": "candidate",
                "effective_transition_role": "candidate",
                "transitioned_by_user_id": None,
                "transitioned_by_lead_id": profile_lead_id,
            }
        # System transition (cron / scheduler / boot-time backfill).
        return {
            "transitioned_by_role": "system",
            "actor_actual_role": "system",
            "effective_transition_role": "system",
            "transitioned_by_user_id": None,
            "transitioned_by_lead_id": None,
        }

    actual_role = (getattr(actor, "role", None) or "officer").lower()

    if actual_role == "admin":
        legacy_role = "admin"
        effective_role = "admin"
    elif actual_role == "manager":
        # Manager elevated to admin scope for status transitions
        # (override / approve at scope). Audit-of-truth keeps
        # actor_actual_role='manager'.
        legacy_role = "admin"
        effective_role = "admin"
    elif actual_role == "accountant":
        # Accountant rarely transitions a profile (RBAC normally
        # blocks); defensive fold to officer-equivalent buckets so
        # the row is still well-formed if a fee-payment hook ever
        # triggers a transition.
        legacy_role = "officer"
        effective_role = "officer"
    else:
        # 'officer' (default) and any unknown role string.
        legacy_role = "officer"
        effective_role = "officer"

    return {
        "transitioned_by_role": legacy_role,
        "actor_actual_role": actual_role,
        "effective_transition_role": effective_role,
        "transitioned_by_user_id": actor.id,
        "transitioned_by_lead_id": None,
    }


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
event=SystemEvents.ADMISSION_RESULT_PUBLISHED             T6 (admin batch publish, Phase 3 PR-3B)
event=SystemEvents.ADMISSION_DECISION_ADMITTED            T7 (approved + overridden + admitted multi-NV)
event=SystemEvents.ADMISSION_DECISION_WAITLISTED          T8 (choice-engine, Phase 3 PR-3B)
event=SystemEvents.ADMISSION_DECISION_REJECTED            T9
event=SystemEvents.ADMISSION_WAITLIST_PROMOTED            T10 (source-aware: waitlisted→admitted, Phase 3 PR-3B)
event=SystemEvents.ADMISSION_WAITLIST_REJECTED            T11 (source-aware: waitlisted→rejected, Wave 5 ship 2026-05-16)
event=SystemEvents.ADMISSION_CONFIRMED                    T12
event=SystemEvents.ADMISSION_ENROLLED                     T13
event=SystemEvents.ADMISSION_WITHDRAWN                    T14/T15/T16
event=SystemEvents.ADMISSION_ROLLED_BACK                  T17 (source-aware: any non-final state → draft, Phase 3 PR-3C Sub-3.5)
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
    # Phase 3 PR-3B Sub-2 — wire 3 new events (multi-NV path)
    "result_published":   SystemEvents.ADMISSION_RESULT_PUBLISHED,         # T6
    "admitted":           SystemEvents.ADMISSION_DECISION_ADMITTED,        # T7 (multi-NV alias for "approved")
    "waitlisted":         SystemEvents.ADMISSION_DECISION_WAITLISTED,      # T8
}


# Source-aware overrides — target alone insufficient because multiple
# transitions can converge to the same target with semantically distinct
# events. Pair lookup runs BEFORE ``LEGACY_STATUS_TO_EVENT`` in
# ``transition()`` event resolution (so the pair value wins on overlap).
#
# Currently 1 entry — T10 manual promote from waitlist:
#   * (waitlisted, admitted) → ADMISSION_WAITLIST_PROMOTED, NOT
#     ADMISSION_DECISION_ADMITTED. Consumers need to distinguish first-pass
#     admit (T7 choice-engine cascade) vs second-pass promote (T10 admin
#     manual via waitlist queue UI).
#
# Future entries follow same Tuple[old, new] → event shape. Parity locked
# by ``tests/unit/test_admission_state_service_event_mapping.py``.
TRANSITION_PAIR_TO_EVENT: Dict[Tuple[str, str], SystemEvents] = {
    ("waitlisted", "admitted"): SystemEvents.ADMISSION_WAITLIST_PROMOTED,  # T10
    ("waitlisted", "rejected"): SystemEvents.ADMISSION_WAITLIST_REJECTED,  # T11 (Wave 5 ship 2026-05-16)
    # Phase 3 PR-3C Sub-3.5 T17 — admin rollback to draft fires
    # ADMISSION_ROLLED_BACK regardless of source state. Pair entries
    # for ALL 11 non-draft non-final-WITHDRAWN/ENROLLED states which
    # now have `→ DRAFT` edge in `admission_state_machine.ALLOWED_TRANSITIONS`.
    # ENROLLED + WITHDRAWN stay final per state machine — no rollback edge.
    ("submitted",          "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("reviewing",          "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("revision_requested", "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("resubmitted",        "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("result_published",   "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("admitted",           "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("waitlisted",         "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("rejected",           "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("approved",           "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("overridden",         "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    ("confirmed",          "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
}


# Events tracked by the B2.1 catalog but with no current legacy writer.
# The coverage script's ``--allow-deferred`` flag accepts this exact set
# and prints them in the summary so operators know the gap is intentional.
#
# Phase 3 PR-3B Sub-2 shrunk 4 → 1 (wired T6/T8/T10).
# Phase 3 PR-3C Sub-3.5 shrunk 1 → 0 — T17 ADMISSION_ROLLED_BACK now wired
# via TRANSITION_PAIR_TO_EVENT 11 pair entries (one per non-final source
# state). All 12 catalog events have a writer reachable from `transition()`.
#
# Empty frozenset = no deferred events. CI gate `--allow-deferred` flag
# in both deploy.yml + admission-contract-check.yml synced empty.
DEFERRED_ADMISSION_EVENTS: frozenset[str] = frozenset()


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

    # 3.5. Status history audit row — Phase 1 PLAN line 1067 / 1098
    # service contract: every status mutation MUST insert one row
    # into ``admission_profile_status_history`` in the same
    # transaction frame, with NO bypass. The override path's
    # ``skip_audit=True`` semantics target the legacy
    # ``entity_audit_log`` writer below (which would double-write
    # alongside ``audit_service.log_changes``) — they do NOT
    # extend to this purpose-built audit table.
    #
    # Phase1-Hotfix-3 (2026-05-07) — moved this writer outside
    # ``if not skip_audit`` after ultrareview / Codex audit found
    # that override transitions were silently skipping the row,
    # leaving the 3-column role audit (legacy / actual / effective)
    # incomplete for admin force-approve flows. The matching test
    # ``test_transition_skip_audit_still_writes_status_history``
    # locks this contract; ``override`` metadata flows through
    # ``event_metadata`` so the row carries the override context.
    from ..models.admission_profile_status_history import (
        AdmissionProfileStatusHistory,
    )

    actor_fields = _resolve_status_history_actor(
        actor=actor,
        source=source,
        profile_lead_id=profile.lead_id,
    )
    history_metadata: Dict[str, Any] = {"source": source}
    if event_metadata:
        # Caller-supplied audit context (e.g. ``override=True``,
        # ``rejection_reason=…``). Stored separately from the
        # ADMISSION_* dispatch payload so the audit row remains the
        # single source of truth even if dispatch is skipped or
        # legacy entity_audit_log is bypassed via ``skip_audit``.
        history_metadata.update(event_metadata)

    db.add(
        AdmissionProfileStatusHistory(
            profile_id=profile.id,
            from_status=old_status,
            to_status=new_status,
            transition_reason=reason,
            occurred_at=now,
            metadata_=history_metadata,
            **actor_fields,
        )
    )

    # 4. Audit log — legacy ``entity_audit_log`` sink. Override flows
    # set ``skip_audit=True`` because ``audit_service.log_changes``
    # already records a richer change-set row (status + version +
    # override_reason + bypass_rules) and a second
    # ``log_status_change`` would just be duplicate noise. The
    # status_history writer above runs unconditionally per PLAN
    # line 1098.
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
        # Pair lookup runs first — source-aware events (T10) override the
        # generic target mapping (which would fire ADMISSION_DECISION_ADMITTED
        # for any → admitted).
        event = TRANSITION_PAIR_TO_EVENT.get((old_status, new_status))
        if event is None:
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

            # Dedupe key: ``admission:{id}:{new_status}:v{post_version}``.
            # The ``v{...}`` suffix uses ``profile.version`` AFTER the
            # ``+= 1`` write above, so each transition gets a unique
            # idempotency key even when the same legal edge is traversed
            # repeatedly. Without the version suffix, a legal cycle like
            # ``rejected → resubmitted → rejected`` would collide on
            # ``admission:{id}:rejected`` — the second outbox INSERT
            # would suppress as a duplicate, and the second rejection
            # would fail to dispatch ADMISSION_DECISION_REJECTED.
            # Approve + overridden also stay distinct: they map to the
            # same event T7 but the version increments through the
            # transition so the keys never collide.
            from .notification_dispatcher import dispatch_event
            callback = await dispatch_event(
                db,
                event=event,
                payload=payload,
                dedupe_key=f"admission:{profile.id}:{new_status}:v{profile.version}",
            )

    # ``event`` is structlog's internal positional kwarg name (it
    # holds the log message), so the dispatched-event identifier is
    # logged under ``dispatched_event`` to avoid the name clash.
    # Mirror pair-first resolution for log accuracy (T10 logs WAITLIST_PROMOTED
    # not DECISION_ADMITTED).
    _logged_event = TRANSITION_PAIR_TO_EVENT.get((old_status, new_status))
    if _logged_event is None:
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
