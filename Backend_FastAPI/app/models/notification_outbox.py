# app/models/notification_outbox.py
"""B2.2 — `NotificationOutbox` table for guaranteed-delivery dispatch.

The 7 events flagged ``requires_outbox=True`` in ``app/core/event_catalog.py``
are critical milestones (admission decisions, broadcasts) where post-commit
fanout cannot afford a process crash to drop the event. Service layer
``dispatch_event()`` (B2.3 sub-PR) INSERTs a row here in the same transaction
as the state change. The Celery beat task ``dispatch_pending_outbox`` (T0-4a
skeleton today, T0-4b real worker via B2.4) claims pending rows in batches
and does the actual fanout out-of-band.

Schema mirrors PLAN §3.3.e + §3.3.f. The migration
``alembic/versions/phase1_19a_create_notification_outbox.py`` is the DDL
half; ``tests/unit/test_notification_outbox_model.py`` locks ORM ⇄ migration
parity.

Worker contract (T0-4b will rely on these):

* ``ix_outbox_pending`` — partial index on ``created_at`` WHERE
  ``dispatched_at IS NULL``. Covers the worker's "find work" query.
* ``ix_outbox_claim`` — partial index on ``claimed_until`` WHERE
  ``dispatched_at IS NULL``. Covers the claim filter so two workers don't
  re-pick the same row mid-lease.
* ``idempotency_key`` UNIQUE — guards double-INSERT from retried service
  callers. The dispatcher SDK (Zalo / email) is also expected to honor
  this key end-to-end so re-dispatch never duplicates fanout to the
  recipient.
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from .base import Base


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    event_code = Column(
        String(64),
        nullable=False,
        comment="SystemEvents.value at INSERT time (e.g. admission_profile_submitted).",
    )
    payload = Column(
        JSONB,
        nullable=False,
        comment="Event-specific data; dispatcher parses per template_codes_by_channel.",
    )
    idempotency_key = Column(
        String(128),
        nullable=False,
        comment=(
            "End-to-end dedupe key, e.g. 'ADMITTED:profile_42:choice_1'. "
            "Service callers that retry must use the same key. UNIQUE "
            "constraint blocks double-INSERT; dispatcher SDK is expected "
            "to honor it downstream so the recipient never sees duplicate "
            "fanout."
        ),
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    dispatched_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set by the worker after fanout succeeds; NULL = still pending.",
    )

    attempts = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Worker retry counter; cap at 5 → manual review (DLQ).",
    )
    last_error = Column(
        Text,
        nullable=True,
        comment="Truncated error message from the most recent failed attempt.",
    )

    claimed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Worker-side claim timestamp; cleared on finalize.",
    )
    claimed_until = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Lease expiry. Another worker may re-claim once this is in the "
            "past (handles crash-after-claim). Cleared to NULL on dispatch "
            "ok / fail."
        ),
    )

    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_notification_outbox_idempotency_key",
        ),
        Index(
            "ix_outbox_pending",
            "created_at",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
        Index(
            "ix_outbox_claim",
            "claimed_until",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationOutbox id={self.id} event={self.event_code!r} "
            f"attempts={self.attempts} dispatched_at={self.dispatched_at}>"
        )
