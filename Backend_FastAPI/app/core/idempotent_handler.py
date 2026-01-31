# app/core/idempotent_handler.py
"""
Idempotent Event Handler Framework.

Ensures each event is processed exactly once per consumer, even with retries.
Uses the ProcessedEvent table to track which events have been handled.

Architecture:
- Each event has a unique event_id
- Each consumer has a unique consumer_id
- (event_id, consumer_id) forms the idempotency key
- If event already processed, return cached result
- If event fails, record failure but allow retry

Usage:
    from app.core.idempotent_handler import IdempotentEventHandler

    handler = IdempotentEventHandler(db)

    result = await handler.handle(
        event=fee_fully_paid_event,
        consumer_id="admission_service",
        processor=update_lead_status,
    )

    if result.was_skipped:
        # Event already processed
        pass
    elif result.was_successful:
        # Event processed successfully
        pass
    else:
        # Event processing failed
        pass

Security:
- Uses database transactions for atomicity
- Unique constraint prevents duplicate processing
- Failed events can be retried (not marked as permanently processed)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar
import structlog

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.finance.accounting import ProcessedEvent
from app.core.finance_events import DomainEvent
from app.utils.exceptions import ConflictError

log = structlog.get_logger(__name__)

T = TypeVar("T")


@dataclass
class ProcessingResult:
    """
    Result of idempotent event processing.

    Attributes:
        event_id: The event that was processed
        consumer_id: The consumer that processed it
        status: processing status (success, failed, skipped)
        result: Result from processor (if successful)
        error_message: Error message (if failed)
        was_cached: Whether result came from cache (already processed)
    """
    event_id: str
    consumer_id: str
    status: str  # success, failed, skipped
    result: Optional[Any] = None
    error_message: Optional[str] = None
    was_cached: bool = False

    @property
    def was_skipped(self) -> bool:
        """Check if event was skipped (already processed)."""
        return self.status == "skipped"

    @property
    def was_successful(self) -> bool:
        """Check if event was processed successfully."""
        return self.status == "success"

    @property
    def was_failed(self) -> bool:
        """Check if event processing failed."""
        return self.status == "failed"


class IdempotentEventHandler:
    """
    Handler for idempotent event processing.

    Ensures each event is processed exactly once per consumer.

    Example:
        handler = IdempotentEventHandler(db)

        async def process_fee_paid(event: FeeFullyPaid) -> dict:
            # Update lead status, send notification, etc.
            return {"lead_status": "sts10"}

        result = await handler.handle(
            event=event,
            consumer_id="lead_status_updater",
            processor=process_fee_paid,
        )
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def is_processed(
        self,
        event_id: str,
        consumer_id: str,
    ) -> bool:
        """
        Check if event has already been successfully processed.

        Args:
            event_id: Unique event identifier
            consumer_id: Consumer identifier

        Returns:
            True if event was already processed successfully
        """
        query = select(ProcessedEvent).where(
            ProcessedEvent.event_id == event_id,
            ProcessedEvent.consumer_id == consumer_id,
            ProcessedEvent.processing_result == "success",
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def get_processed_record(
        self,
        event_id: str,
        consumer_id: str,
    ) -> Optional[ProcessedEvent]:
        """
        Get the ProcessedEvent record if it exists.

        Args:
            event_id: Unique event identifier
            consumer_id: Consumer identifier

        Returns:
            ProcessedEvent record or None
        """
        query = select(ProcessedEvent).where(
            ProcessedEvent.event_id == event_id,
            ProcessedEvent.consumer_id == consumer_id,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def handle(
        self,
        event: DomainEvent,
        consumer_id: str,
        processor: Callable[[DomainEvent], Any],
        allow_retry_on_failure: bool = True,
    ) -> ProcessingResult:
        """
        Process an event idempotently.

        Steps:
        1. Check if event already processed by this consumer
        2. If yes and successful, return cached result (skipped)
        3. If yes and failed, optionally retry
        4. If no, process and record result

        Args:
            event: Domain event to process
            consumer_id: Unique identifier for this consumer
            processor: Async function to process the event
            allow_retry_on_failure: If True, retry failed events

        Returns:
            ProcessingResult with status and result

        Raises:
            ConflictError: If concurrent processing detected
        """
        event_id = event.event_id
        event_type = event.event_type

        # Check for existing processing record
        existing = await self.get_processed_record(event_id, consumer_id)

        if existing:
            if existing.processing_result == "success":
                # Already processed successfully - skip
                log.info(
                    "event_already_processed",
                    event_id=event_id,
                    event_type=event_type,
                    consumer_id=consumer_id,
                )
                return ProcessingResult(
                    event_id=event_id,
                    consumer_id=consumer_id,
                    status="skipped",
                    result=existing.event_payload.get("_result") if existing.event_payload else None,
                    was_cached=True,
                )

            if existing.processing_result == "failed" and not allow_retry_on_failure:
                # Failed and no retry allowed
                log.info(
                    "event_failed_no_retry",
                    event_id=event_id,
                    event_type=event_type,
                    consumer_id=consumer_id,
                    error=existing.error_message,
                )
                return ProcessingResult(
                    event_id=event_id,
                    consumer_id=consumer_id,
                    status="failed",
                    error_message=existing.error_message,
                    was_cached=True,
                )

            # Failed but retry allowed - delete old record and retry
            if existing.processing_result == "failed":
                log.info(
                    "event_retrying_failed",
                    event_id=event_id,
                    event_type=event_type,
                    consumer_id=consumer_id,
                )
                await self.db.delete(existing)
                await self.db.flush()

        # Process the event
        log.info(
            "event_processing_start",
            event_id=event_id,
            event_type=event_type,
            consumer_id=consumer_id,
        )

        try:
            # Execute processor
            result = await processor(event)

            # Record successful processing
            record = ProcessedEvent(
                event_id=event_id,
                event_type=event_type,
                event_version=str(event.event_version),
                consumer_id=consumer_id,
                processing_result="success",
                event_payload={
                    **event.to_dict(),
                    "_result": result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result),
                },
            )
            self.db.add(record)
            await self.db.flush()

            log.info(
                "event_processing_success",
                event_id=event_id,
                event_type=event_type,
                consumer_id=consumer_id,
            )

            return ProcessingResult(
                event_id=event_id,
                consumer_id=consumer_id,
                status="success",
                result=result,
            )

        except IntegrityError:
            # Concurrent processing - another process beat us
            await self.db.rollback()
            log.warning(
                "event_concurrent_processing",
                event_id=event_id,
                event_type=event_type,
                consumer_id=consumer_id,
            )
            raise ConflictError(
                f"Event {event_id} is being processed concurrently"
            )

        except Exception as e:
            # Processing failed - record failure
            error_message = str(e)

            record = ProcessedEvent(
                event_id=event_id,
                event_type=event_type,
                event_version=str(event.event_version),
                consumer_id=consumer_id,
                processing_result="failed",
                error_message=error_message,
                event_payload=event.to_dict(),
            )
            self.db.add(record)
            await self.db.flush()

            log.error(
                "event_processing_failed",
                event_id=event_id,
                event_type=event_type,
                consumer_id=consumer_id,
                error=error_message,
            )

            return ProcessingResult(
                event_id=event_id,
                consumer_id=consumer_id,
                status="failed",
                error_message=error_message,
            )

    async def mark_processed(
        self,
        event_id: str,
        event_type: str,
        consumer_id: str,
        result: str = "success",
        event_payload: Optional[Dict[str, Any]] = None,
    ) -> ProcessedEvent:
        """
        Manually mark an event as processed.

        Useful for marking external events (e.g., gateway callbacks)
        as processed.

        Args:
            event_id: Unique event identifier
            event_type: Type of event
            consumer_id: Consumer identifier
            result: Processing result (success, failed, skipped)
            event_payload: Optional payload to store

        Returns:
            ProcessedEvent record

        Raises:
            ConflictError: If event already processed
        """
        # Check if already processed
        existing = await self.get_processed_record(event_id, consumer_id)
        if existing:
            raise ConflictError(
                f"Event {event_id} already processed by {consumer_id}"
            )

        record = ProcessedEvent(
            event_id=event_id,
            event_type=event_type,
            consumer_id=consumer_id,
            processing_result=result,
            event_payload=event_payload or {},
        )
        self.db.add(record)
        await self.db.flush()

        log.info(
            "event_marked_processed",
            event_id=event_id,
            event_type=event_type,
            consumer_id=consumer_id,
            result=result,
        )

        return record


# =============================================================================
# DECORATOR FOR IDEMPOTENT HANDLERS
# =============================================================================

def idempotent_handler(consumer_id: str, allow_retry: bool = True):
    """
    Decorator to make an event handler idempotent.

    The decorated function must accept (db, event) as first two arguments.

    Usage:
        @idempotent_handler("lead_status_updater")
        async def update_lead_on_fee_paid(db: AsyncSession, event: FeeFullyPaid):
            # This will only run once per event
            lead = await get_lead_by_profile(event.admission_profile_id)
            lead.status = "sts10"
            return {"updated": True}

    Args:
        consumer_id: Unique identifier for this consumer
        allow_retry: Whether to retry failed events
    """
    def decorator(func: Callable):
        async def wrapper(db: AsyncSession, event: DomainEvent, *args, **kwargs):
            handler = IdempotentEventHandler(db)

            async def processor(e: DomainEvent):
                return await func(db, e, *args, **kwargs)

            return await handler.handle(
                event=event,
                consumer_id=consumer_id,
                processor=processor,
                allow_retry_on_failure=allow_retry,
            )

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator
