# tests/unit/test_finance_events.py
"""
Unit Tests for Finance Domain Events and Idempotent Handler.

Test Categories:
1. Domain Event Tests - Event creation, serialization, registry
2. Idempotent Handler Tests - Idempotency, retries, concurrent processing
3. Event Schema Tests - Pydantic validation

Run: pytest tests/unit/test_finance_events.py -v
"""

import pytest
from datetime import datetime, date, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.core.finance_events import (
    DomainEvent,
    FeeCalculated,
    FeeFullyPaid,
    FeeWaived,
    InvoiceIssued,
    PaymentVerified,
    PaymentRejected,
    RefundProcessed,
    PeriodClosed,
    OverpaymentDetected,
    EVENT_REGISTRY,
    get_event_class,
    register_handler,
    get_handlers,
    emit_event,
    event_handler,
)
from app.core.idempotent_handler import (
    IdempotentEventHandler,
    ProcessingResult,
    idempotent_handler,
)
from app.schemas.finance_events import (
    FeeCalculatedSchema,
    PaymentVerifiedSchema,
    ProcessedEventResponse,
    EVENT_SCHEMA_REGISTRY,
    get_event_schema,
)
from app.utils.exceptions import ConflictError


# =============================================================================
# DOMAIN EVENT TESTS
# =============================================================================

class TestDomainEvent:
    """Tests for base DomainEvent class."""

    def test_event_creates_unique_id(self):
        """Each event should have a unique event_id."""
        event1 = FeeCalculated()
        event2 = FeeCalculated()

        assert event1.event_id != event2.event_id
        assert len(event1.event_id) == 36  # UUID format

    def test_event_has_timestamp(self):
        """Events should have occurred_at timestamp."""
        before = datetime.now(timezone.utc)
        event = FeeCalculated()
        after = datetime.now(timezone.utc)

        assert before <= event.occurred_at <= after

    def test_event_type_property(self):
        """event_type should return class name."""
        event = FeeCalculated()
        assert event.event_type == "FeeCalculated"

        event2 = PaymentVerified()
        assert event2.event_type == "PaymentVerified"

    def test_event_to_dict(self):
        """to_dict should serialize event properly."""
        event = FeeCalculated(
            fee_id=123,
            admission_profile_id=456,
            fee_type="tuition",
            base_amount=Decimal("10000000"),
            total_discount=Decimal("1000000"),
            final_amount=Decimal("9000000"),
            installment_count=3,
            academic_year=2025,
        )

        data = event.to_dict()

        assert data["fee_id"] == 123
        assert data["admission_profile_id"] == 456
        assert data["fee_type"] == "tuition"
        assert data["base_amount"] == "10000000"
        assert data["final_amount"] == "9000000"
        assert data["installment_count"] == 3
        assert "event_id" in data
        assert "occurred_at" in data

    def test_event_with_correlation_id(self):
        """Events can have correlation_id for tracing."""
        correlation = str(uuid4())
        event = FeeCalculated(correlation_id=correlation)

        assert event.correlation_id == correlation


class TestFeeCalculatedEvent:
    """Tests for FeeCalculated event."""

    def test_fee_calculated_defaults(self):
        """FeeCalculated should have proper defaults."""
        event = FeeCalculated()

        assert event.fee_id == 0
        assert event.admission_profile_id == 0
        assert event.fee_type == ""
        assert event.base_amount == Decimal("0")
        assert event.final_amount == Decimal("0")
        assert event.installment_count == 1
        assert event.applied_discounts == []

    def test_fee_calculated_with_discounts(self):
        """FeeCalculated can include discount details."""
        discounts = [
            {"policy_id": 1, "name": "Ưu đãi sớm", "amount": Decimal("500000")},
            {"policy_id": 2, "name": "Ưu đãi anh chị em", "amount": Decimal("300000")},
        ]

        event = FeeCalculated(
            fee_id=1,
            applied_discounts=discounts,
        )

        assert len(event.applied_discounts) == 2


class TestFeeFullyPaidEvent:
    """Tests for FeeFullyPaid event."""

    def test_fee_fully_paid_critical_event(self):
        """FeeFullyPaid is critical for enrollment eligibility."""
        event = FeeFullyPaid(
            fee_id=1,
            admission_profile_id=100,
            fee_type="tuition",
            total_paid=Decimal("9000000"),
        )

        assert event.fee_type == "tuition"
        assert event.total_paid == Decimal("9000000")


class TestPaymentVerifiedEvent:
    """Tests for PaymentVerified event."""

    def test_payment_verified_tracks_remaining(self):
        """PaymentVerified tracks remaining amounts."""
        event = PaymentVerified(
            payment_id=1,
            invoice_id=10,
            fee_id=100,
            amount=Decimal("3000000"),
            remaining_on_invoice=Decimal("0"),
            remaining_on_fee=Decimal("6000000"),
            invoice_fully_paid=True,
            fee_fully_paid=False,
            verified_by_id=5,
        )

        assert event.invoice_fully_paid is True
        assert event.fee_fully_paid is False
        assert event.remaining_on_fee == Decimal("6000000")


# =============================================================================
# EVENT REGISTRY TESTS
# =============================================================================

class TestEventRegistry:
    """Tests for event registry."""

    def test_all_events_registered(self):
        """All event types should be in registry."""
        expected_events = [
            "FeeCalculated",
            "FeeWaived",
            "FeeCancelled",
            "FeeFullyPaid",
            "InvoiceIssued",
            "InvoicePaid",
            "InvoiceOverdue",
            "InvoiceCancelled",
            "PaymentReceived",
            "PaymentVerified",
            "PaymentRejected",
            "RefundRequested",
            "RefundApproved",
            "RefundProcessed",
            "PeriodOpened",
            "PeriodClosed",
            "OverpaymentDetected",
            "OverpaymentResolved",
        ]

        for event_name in expected_events:
            assert event_name in EVENT_REGISTRY, f"Missing: {event_name}"

    def test_get_event_class(self):
        """get_event_class should return correct class."""
        assert get_event_class("FeeCalculated") == FeeCalculated
        assert get_event_class("PaymentVerified") == PaymentVerified
        assert get_event_class("NonExistent") is None


# =============================================================================
# EVENT HANDLER TESTS
# =============================================================================

class TestEventHandlers:
    """Tests for event handler registration and emission."""

    def test_register_handler(self):
        """Handlers can be registered for event types."""
        # Clear existing handlers
        from app.core import finance_events
        finance_events._event_handlers = {}

        handler_called = []

        async def test_handler(event):
            handler_called.append(event)

        register_handler(FeeCalculated, test_handler)

        handlers = get_handlers("FeeCalculated")
        assert len(handlers) == 1
        assert handlers[0] == test_handler

    @pytest.mark.asyncio
    async def test_emit_event_calls_handlers(self):
        """emit_event should call all registered handlers."""
        from app.core import finance_events
        finance_events._event_handlers = {}

        results = []

        async def handler1(event):
            results.append(("handler1", event.event_id))

        async def handler2(event):
            results.append(("handler2", event.event_id))

        register_handler(FeeCalculated, handler1)
        register_handler(FeeCalculated, handler2)

        event = FeeCalculated(fee_id=1)
        await emit_event(event)

        assert len(results) == 2
        assert ("handler1", event.event_id) in results
        assert ("handler2", event.event_id) in results

    @pytest.mark.asyncio
    async def test_emit_event_handles_handler_errors(self):
        """emit_event should continue if handler fails."""
        from app.core import finance_events
        finance_events._event_handlers = {}

        results = []

        async def failing_handler(event):
            raise ValueError("Handler failed")

        async def success_handler(event):
            results.append(event.event_id)

        register_handler(FeeCalculated, failing_handler)
        register_handler(FeeCalculated, success_handler)

        event = FeeCalculated(fee_id=1)
        await emit_event(event)  # Should not raise

        assert len(results) == 1  # Second handler still ran

    def test_event_handler_decorator(self):
        """@event_handler decorator should register handler."""
        from app.core import finance_events
        finance_events._event_handlers = {}

        @event_handler(PaymentVerified)
        async def on_payment_verified(event: PaymentVerified):
            pass

        handlers = get_handlers("PaymentVerified")
        assert len(handlers) == 1


# =============================================================================
# IDEMPOTENT HANDLER TESTS
# =============================================================================

class TestIdempotentHandler:
    """Tests for idempotent event handler."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.delete = AsyncMock()
        db.rollback = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_first_processing_succeeds(self, mock_db):
        """First processing of event should succeed."""
        # Mock no existing record
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        handler = IdempotentEventHandler(mock_db)

        async def processor(event):
            return {"processed": True}

        event = FeeCalculated(fee_id=1)
        result = await handler.handle(
            event=event,
            consumer_id="test_consumer",
            processor=processor,
        )

        assert result.was_successful
        assert result.result == {"processed": True}
        assert not result.was_cached
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_processing_skipped(self, mock_db):
        """Duplicate event should be skipped."""
        # Mock existing successful record
        existing_record = MagicMock()
        existing_record.processing_result = "success"
        existing_record.event_payload = {"_result": {"already": "processed"}}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_db.execute.return_value = mock_result

        handler = IdempotentEventHandler(mock_db)

        async def processor(event):
            return {"should_not_run": True}

        event = FeeCalculated(fee_id=1)
        result = await handler.handle(
            event=event,
            consumer_id="test_consumer",
            processor=processor,
        )

        assert result.was_skipped
        assert result.was_cached
        assert result.result == {"already": "processed"}

    @pytest.mark.asyncio
    async def test_failed_processing_recorded(self, mock_db):
        """Failed processing should be recorded."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        handler = IdempotentEventHandler(mock_db)

        async def failing_processor(event):
            raise ValueError("Processing failed")

        event = FeeCalculated(fee_id=1)
        result = await handler.handle(
            event=event,
            consumer_id="test_consumer",
            processor=failing_processor,
        )

        assert result.was_failed
        assert "Processing failed" in result.error_message
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_event_can_be_retried(self, mock_db):
        """Failed events can be retried if allowed."""
        # First call returns failed record, second call returns None
        failed_record = MagicMock()
        failed_record.processing_result = "failed"
        failed_record.error_message = "Previous failure"

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = failed_record

        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_result1, mock_result2]

        handler = IdempotentEventHandler(mock_db)

        async def processor(event):
            return {"retried": True}

        event = FeeCalculated(fee_id=1)
        result = await handler.handle(
            event=event,
            consumer_id="test_consumer",
            processor=processor,
            allow_retry_on_failure=True,
        )

        # Should delete old record and process again
        mock_db.delete.assert_called_once()
        assert result.was_successful

    @pytest.mark.asyncio
    async def test_is_processed_check(self, mock_db):
        """is_processed should check for successful processing."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_db.execute.return_value = mock_result

        handler = IdempotentEventHandler(mock_db)
        is_processed = await handler.is_processed("event-123", "consumer-1")

        assert is_processed is True


class TestIdempotentHandlerDecorator:
    """Tests for @idempotent_handler decorator."""

    @pytest.mark.asyncio
    async def test_decorator_wraps_function(self):
        """Decorator should wrap function with idempotency."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        @idempotent_handler("test_consumer")
        async def process_event(db, event):
            return {"processed": True}

        event = FeeCalculated(fee_id=1)
        result = await process_event(mock_db, event)

        assert result.was_successful
        assert result.consumer_id == "test_consumer"


# =============================================================================
# EVENT SCHEMA TESTS
# =============================================================================

class TestEventSchemas:
    """Tests for Pydantic event schemas."""

    def test_fee_calculated_schema_validation(self):
        """FeeCalculatedSchema should validate correctly."""
        data = {
            "event_id": str(uuid4()),
            "event_type": "FeeCalculated",
            "event_version": 1,
            "occurred_at": datetime.now(timezone.utc),
            "fee_id": 1,
            "admission_profile_id": 100,
            "fee_type": "tuition",
            "base_amount": Decimal("10000000"),
            "total_discount": Decimal("1000000"),
            "final_amount": Decimal("9000000"),
            "installment_count": 3,
            "academic_year": 2025,
        }

        schema = FeeCalculatedSchema(**data)

        assert schema.fee_id == 1
        assert schema.final_amount == Decimal("9000000")

    def test_processed_event_response(self):
        """ProcessedEventResponse should serialize correctly."""
        data = {
            "id": 1,
            "event_id": "evt-123",
            "event_type": "FeeCalculated",
            "event_version": "1",
            "consumer_id": "admission_service",
            "processed_at": datetime.now(timezone.utc),
            "processing_result": "success",
        }

        schema = ProcessedEventResponse(**data)

        assert schema.event_id == "evt-123"
        assert schema.processing_result == "success"

    def test_event_schema_registry(self):
        """All events should have corresponding schemas."""
        for event_type in EVENT_REGISTRY:
            schema = get_event_schema(event_type)
            assert schema is not None, f"Missing schema for {event_type}"

    def test_get_event_schema(self):
        """get_event_schema should return correct schema."""
        assert get_event_schema("FeeCalculated") == FeeCalculatedSchema
        assert get_event_schema("PaymentVerified") == PaymentVerifiedSchema
        assert get_event_schema("NonExistent") is None


# =============================================================================
# PROCESSING RESULT TESTS
# =============================================================================

class TestProcessingResult:
    """Tests for ProcessingResult dataclass."""

    def test_successful_result(self):
        """Successful result properties."""
        result = ProcessingResult(
            event_id="evt-1",
            consumer_id="consumer-1",
            status="success",
            result={"data": "value"},
        )

        assert result.was_successful
        assert not result.was_skipped
        assert not result.was_failed

    def test_skipped_result(self):
        """Skipped result properties."""
        result = ProcessingResult(
            event_id="evt-1",
            consumer_id="consumer-1",
            status="skipped",
            was_cached=True,
        )

        assert result.was_skipped
        assert not result.was_successful
        assert result.was_cached

    def test_failed_result(self):
        """Failed result properties."""
        result = ProcessingResult(
            event_id="evt-1",
            consumer_id="consumer-1",
            status="failed",
            error_message="Something went wrong",
        )

        assert result.was_failed
        assert not result.was_successful
        assert "Something went wrong" in result.error_message
