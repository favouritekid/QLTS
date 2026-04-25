"""Atomic notification bundle helper (Path C / Arch-3).

Provides a service-layer primitive for dispatching paired (or N-tuple)
notification events as a single atomic persistence unit, plus a
helper that composes multiple post-commit callbacks into one.

Why this exists
---------------
The plain ``dispatch()`` API at ``notification_dispatcher.dispatch``
treats each call as an independent transaction-scoped persistence:
the caller commits when ready, then awaits the post-commit callback.
For paired admission events (``APPLICATION_STATUS_CHANGED`` +
``LEAD_STATUS_CHANGED``), two back-to-back ``safe_dispatch()`` calls
in the router are not atomic — if the second one fails after the
first one has already succeeded, the notification side-effect is
half-delivered.

``dispatch_bundle()`` wraps N intents in a SAVEPOINT
(``db.begin_nested()``), so the persistence of every notification
record in the bundle is atomic at the savepoint level. The outer
business transaction is unaffected; if the bundle rolls back, the
service still returns its business result and the router still
commits the business mutation. The bundle just contributes ``None``
to the post-commit callback chain.

Each ``dispatch()`` call inside the bundle runs with ``strict=True``
so that a persistence failure re-raises instead of calling the
dispatcher's internal ``db.rollback()``. Without this, a bulk-insert
error inside ``_bulk_create_notifications`` would issue a full
rollback on the shared session and wipe the outer admission mutation
as a side effect, contradicting the "outer txn stays alive" promise.

This complements rather than replaces ``safe_dispatch()`` — that
helper remains the right tool for genuinely fire-and-forget
post-commit notifications (alerts, single-event flows). Use a
bundle only when two or more events should land or fail together.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, List, Literal, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.events import SystemEvents
from .notification_dispatcher import dispatch

log = structlog.get_logger(__name__)

PostCommitCallback = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class NotificationIntent:
    """One event to dispatch as part of a bundle.

    Mirrors the shape of ``dispatch()`` arguments so the bundle helper
    can apply each intent without further translation. Frozen + slots
    so callers can build a list of intents at the top of a service
    method without worrying about accidental mutation downstream.

    Fields
    ------
    rooms: Optional Socket.IO rooms for the realtime domain emit. Required
           for sensitive events (admission/lead/finance/user PII) when
           ``settings.SOCKET_SCOPED_EMIT=True`` — a sensitive intent without
           rooms will be blocked by the fail-closed guard in
           ``_emit_domain_event``. Build via
           ``_rooms_for_admission(profile)`` / ``_rooms_for_lead(lead)`` /
           ``_rooms_for_user(user_id)`` helpers at the call site.
    """

    event: SystemEvents
    payload: dict
    dedupe_key: Optional[str] = None
    skip_preference_check: bool = False
    rooms: Optional[List[str]] = None


@dataclass(frozen=True, slots=True)
class BundleDispatchResult:
    """Outcome of one ``dispatch_bundle()`` call.

    ``persist_status`` is the queryable bit:
    - ``"ok"``: every intent was persisted inside the savepoint
    - ``"rolled_back"``: at least one ``dispatch()`` raised; the
      savepoint was rolled back and ``notification_ids`` is empty

    ``persist_status="ok"`` does NOT imply user-visible delivery —
    recipient filters, cooldowns, and channel handlers still run
    post-commit via the composed ``callback``.

    Redis side-effect caveat (rolled_back case)
    -------------------------------------------
    The SAVEPOINT covers **DB rows only** (Notification, Delivery,
    etc.). Redis cooldown and rate-limit keys acquired by earlier
    intents inside the bundle — via ``safe_redis_set(nx=True)`` at
    ``notification_dispatcher.py:~683`` — are **NOT** released when
    the savepoint rolls back. A caller that retries the same dedupe
    key within ``NOTIFICATION_COOLDOWN_SECONDS`` will find those
    users suppressed, producing a small no-notification window.

    Fixing this would require moving cooldown acquisition to the
    post-commit callback (a larger dispatch refactor); deferred to
    a follow-up. For now, callers should treat ``rolled_back`` as
    "DB atomically rolled back; Redis state may still reflect the
    failed attempt".
    """

    bundle_label: str
    intent_events: tuple[str, ...]
    notification_ids: list[int]
    persist_status: Literal["ok", "rolled_back"]
    callback: Optional[PostCommitCallback]


def compose_post_commit_callbacks(
    *,
    label: str,
    callbacks: Iterable[Optional[PostCommitCallback]],
) -> Optional[PostCommitCallback]:
    """Combine N callbacks into one.

    Filters out ``None`` entries. If the resulting list is empty,
    returns ``None`` so the caller can ``if cb: await cb()`` cheaply.
    A single non-None callback is returned as-is (no wrapping
    overhead).

    Multi-callback case: returned function runs each child in order,
    swallows individual exceptions so a failure in one does not
    starve the rest, and emits one ``notification_bundle_callback_*``
    log line summarizing outcomes. The outer awaiter never sees an
    exception — post-commit side effects are best-effort by design.
    """
    real = [cb for cb in callbacks if cb is not None]
    if not real:
        return None
    if len(real) == 1:
        return real[0]

    async def _run_all() -> None:
        failed_indexes: list[int] = []
        for i, cb in enumerate(real):
            try:
                await cb()
            except Exception as exc:  # noqa: BLE001 — best-effort, log and continue
                failed_indexes.append(i)
                log.warning(
                    "notification_bundle_callback_child_failed",
                    extra={
                        "event": "notification_bundle_callback_child_failed",
                        "bundle_label": label,
                        "callback_index": i,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
        if failed_indexes:
            log.warning(
                "notification_bundle_callback_partial_failure",
                extra={
                    "event": "notification_bundle_callback_partial_failure",
                    "bundle_label": label,
                    "callback_count": len(real),
                    "failed_callback_count": len(failed_indexes),
                    "failed_callback_indexes": failed_indexes,
                },
            )
        else:
            log.info(
                "notification_bundle_callback_completed",
                extra={
                    "event": "notification_bundle_callback_completed",
                    "bundle_label": label,
                    "callback_count": len(real),
                    "failed_callback_count": 0,
                },
            )

    return _run_all


async def dispatch_bundle(
    db: AsyncSession,
    *,
    bundle_label: str,
    intents: List[NotificationIntent],
) -> BundleDispatchResult:
    """Dispatch N intents inside one savepoint.

    Contract:
    - Caller passes ``intents`` non-empty. Empty list raises
      ``ValueError`` — that is a caller bug, not a graceful path.
      Services that conditionally skip dispatch (e.g. when
      ``profile.lead_id is None``) MUST guard before calling.
    - Opens ``async with db.begin_nested()``. Inside the savepoint,
      each intent is forwarded to ``dispatch()`` in order; the
      returned ``notification_ids`` and child callbacks accumulate.
    - If any ``dispatch()`` raises, the savepoint auto-rolls back on
      ``with`` exit. The exception is caught here; this function
      returns a ``rolled_back`` result instead of propagating, so
      the outer business transaction stays alive.
    - On success, returns the composed callback (or ``None`` if no
      child produced one).

    The caller commits the outer transaction and awaits the returned
    callback per the standard V3 pattern.
    """
    if not intents:
        raise ValueError(
            "dispatch_bundle requires at least one NotificationIntent — "
            "guard with `if profile.lead_id:` (or equivalent) before calling."
        )

    intent_events = tuple(intent.event.value for intent in intents)

    notification_ids: list[int] = []
    child_callbacks: list[Optional[PostCommitCallback]] = []
    failed_event: Optional[str] = None
    failed_exc: Optional[Exception] = None

    try:
        async with db.begin_nested():
            for intent in intents:
                try:
                    # strict=True: persistence failure re-raises instead of
                    # triggering dispatch()'s internal db.rollback(). The
                    # surrounding savepoint absorbs the rollback so the
                    # outer business transaction (admission mutation)
                    # survives per the bundle contract.
                    ids, child_cb = await dispatch(
                        db=db,
                        event=intent.event,
                        payload=intent.payload,
                        dedupe_key=intent.dedupe_key,
                        skip_preference_check=intent.skip_preference_check,
                        strict=True,
                        rooms=intent.rooms,
                    )
                except Exception as exc:
                    failed_event = intent.event.value
                    failed_exc = exc
                    raise
                notification_ids.extend(ids or [])
                child_callbacks.append(child_cb)
    except Exception as exc:  # noqa: BLE001 — savepoint already rolled back
        # ``failed_event`` / ``failed_exc`` populated by inner handler;
        # belt-and-braces fallback in case the raise came from outside
        # the inner try (e.g. begin_nested itself).
        if failed_exc is None:
            failed_exc = exc
        log.warning(
            "notification_bundle_rolled_back",
            extra={
                "event": "notification_bundle_rolled_back",
                "bundle_label": bundle_label,
                "intent_events": list(intent_events),
                "failed_event": failed_event,
                "persist_status": "rolled_back",
                "error_type": type(failed_exc).__name__,
                "error_message": str(failed_exc),
            },
        )
        return BundleDispatchResult(
            bundle_label=bundle_label,
            intent_events=intent_events,
            notification_ids=[],
            persist_status="rolled_back",
            callback=None,
        )

    composed = compose_post_commit_callbacks(
        label=bundle_label,
        callbacks=child_callbacks,
    )
    log.info(
        "notification_bundle_persisted",
        extra={
            "event": "notification_bundle_persisted",
            "bundle_label": bundle_label,
            "intent_events": list(intent_events),
            "persist_status": "ok",
            "persisted_notification_count": len(notification_ids),
            "callback_count": sum(1 for cb in child_callbacks if cb is not None),
        },
    )
    return BundleDispatchResult(
        bundle_label=bundle_label,
        intent_events=intent_events,
        notification_ids=notification_ids,
        persist_status="ok",
        callback=composed,
    )
