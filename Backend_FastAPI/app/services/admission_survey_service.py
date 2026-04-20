"""Admission survey feedback persistence (Phase E.5).

Receives the Zalo ``user_feedback`` webhook payload for ZNS template
426903 and upserts an ``AdmissionSurveyFeedback`` row. Dedupe is
unique on ``tracking_id`` — a re-delivered webhook updates rather
than inserts so Zalo retries don't create phantom duplicates.

``profile_id`` is nullable on purpose: if the tracking_id doesn't
match any profile row (ghost delivery, stale template, manual test)
we still persist the feedback for ops review. Dropping it would lose
data with no recovery path.

The service is intentionally tolerant on input shape because the Zalo
webhook body has drifted before (notably the 2026-03-16 ZBS policy
update). Missing optional fields coerce to safe defaults; a missing
required field (``rate`` / ``tracking_id``) surfaces as a DomainError
so the router can log and still return 200 to Zalo (we never want to
trigger a retry storm on malformed input — caller-side noise).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdmissionProfile, AdmissionSurveyFeedback
from app.utils.exceptions import ValidationError

log = structlog.get_logger(__name__)


def _parse_submit_time(raw: Any) -> datetime:
    """Zalo sends submit_time as epoch-ms string. Fall back to now() if
    missing or unparseable — the exact instant matters less than the
    fact we persisted the row at all."""
    if raw is None:
        return datetime.now(timezone.utc)
    try:
        ms = int(raw)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _coerce_rate(raw: Any) -> int:
    """Rate is declared as int 1..5 in the Zalo spec; CHECK constraint
    at the DB enforces the range so any garbage value surfaces as a
    ValidationError here (fail fast, caller can log and 200-ack)."""
    if isinstance(raw, bool):  # bool is an int subclass — reject early
        raise ValidationError(f"rate must be int 1..5, got bool: {raw}")
    try:
        rate = int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"rate must be int 1..5, got: {raw!r}")
    if not 1 <= rate <= 5:
        raise ValidationError(f"rate out of range 1..5: {rate}")
    return rate


async def record_feedback(
    db: AsyncSession,
    *,
    raw_payload: Dict[str, Any],
) -> AdmissionSurveyFeedback:
    """Upsert a feedback row from the ``user_feedback`` webhook body.

    Contract:
    - ``raw_payload`` is the full Zalo POST body (top-level ``event_name``,
      ``message``, ``timestamp``, ``app_id``, ``oa_id``).
    - ``tracking_id`` is the sole correlation key. PR-E1 stores a UUID on
      ``admission_profile.survey_tracking_id`` at dispatch time; Zalo
      echoes it verbatim inside ``message.tracking_id``.
    - If tracking_id matches a profile, ``profile_id`` is populated;
      otherwise the row is persisted with ``profile_id=NULL`` for ops
      review.
    - Unique constraint on tracking_id makes the upsert idempotent —
      repeat deliveries update ``note/rate/feedback_tags/received_at``
      in place without touching the original ``id`` or insertion order.

    Returns the resulting (inserted or updated) row.
    Raises ValidationError on malformed rate / missing tracking_id —
    caller should log + still 200-ack.
    """
    message = raw_payload.get("message") or {}
    if not isinstance(message, dict):
        raise ValidationError("message must be an object")

    tracking_id = message.get("tracking_id")
    if not tracking_id or not isinstance(tracking_id, str):
        raise ValidationError("tracking_id missing from message")

    rate = _coerce_rate(message.get("rate"))
    note = message.get("note") or None
    raw_tags = message.get("feedbacks") or []
    feedback_tags = [str(t) for t in raw_tags if isinstance(t, (str, int, float))]
    submit_time = _parse_submit_time(message.get("submit_time"))
    zalo_msg_id = message.get("msg_id")

    # Lookup profile by tracking_id. Nullable on no-match is the audit
    # path — we prefer a dangling feedback row over lost data because
    # the alternative (silent drop) hides upstream bugs.
    profile_id: Optional[int] = None
    profile_lookup = await db.execute(
        select(AdmissionProfile.id).where(
            AdmissionProfile.survey_tracking_id == tracking_id
        )
    )
    profile_id = profile_lookup.scalar_one_or_none()

    if profile_id is None:
        log.warning(
            "Admission survey feedback: tracking_id did not match any profile",
            tracking_id=tracking_id,
        )

    # Upsert: unique tracking_id drives ON CONFLICT. A re-delivered
    # webhook (Zalo retry, bot test, idempotency probe) updates the
    # existing row rather than raising — this is the spec contract
    # for ``uq_admission_survey_feedback_tracking_id``.
    stmt = pg_insert(AdmissionSurveyFeedback).values(
        tracking_id=tracking_id,
        profile_id=profile_id,
        zalo_msg_id=zalo_msg_id,
        rate=rate,
        note=note,
        feedback_tags=feedback_tags,
        submit_time=submit_time,
        raw_payload=raw_payload,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_admission_survey_feedback_tracking_id",
        set_={
            "profile_id": stmt.excluded.profile_id,
            "zalo_msg_id": stmt.excluded.zalo_msg_id,
            "rate": stmt.excluded.rate,
            "note": stmt.excluded.note,
            "feedback_tags": stmt.excluded.feedback_tags,
            "submit_time": stmt.excluded.submit_time,
            "raw_payload": stmt.excluded.raw_payload,
            "received_at": datetime.now(timezone.utc),
        },
    ).returning(AdmissionSurveyFeedback)

    result = await db.execute(stmt)
    row = result.scalar_one()

    log.info(
        "Admission survey feedback recorded",
        tracking_id=tracking_id,
        profile_id=profile_id,
        rate=rate,
        note_present=bool(note),
        tag_count=len(feedback_tags),
    )
    return row
