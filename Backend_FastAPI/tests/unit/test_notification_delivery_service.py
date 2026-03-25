# tests/unit/test_notification_delivery_service.py
"""
Phase B12: Unit tests for notification_delivery_service.

Tests pure logic functions (build_payload_snapshot) and mocked async functions.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.notification_delivery_service import (
    build_payload_snapshot,
    create_deliveries_for_dispatch,
    mark_delivery_ids_sent,
    mark_delivery_ids_failed,
    mark_delivery_ids_skipped,
    mark_channel_sent,
    mark_channel_failed,
    mark_channel_skipped,
    prepare_external_deliveries,
)


class TestBuildPayloadSnapshot:
    """Tests for build_payload_snapshot — pure function, no DB."""

    def test_basic_snapshot(self):
        result = build_payload_snapshot(title="Hello", message="World")
        assert result == {"title": "Hello", "message": "World"}

    def test_snapshot_with_link(self):
        result = build_payload_snapshot(title="T", message="M", link="/foo")
        assert result["link"] == "/foo"

    def test_snapshot_with_extra(self):
        result = build_payload_snapshot(
            title="T", message="M", extra={"lead_id": 123}
        )
        assert result["extra"] == {"lead_id": 123}

    def test_snapshot_no_link_no_extra(self):
        result = build_payload_snapshot(title="T", message="M")
        assert "link" not in result
        assert "extra" not in result


@pytest.mark.asyncio
class TestCreateDeliveriesForDispatch:
    """Tests for create_deliveries_for_dispatch with mocked repo."""

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_creates_rows_and_returns_channel_mapping(self, MockRepo):
        mock_repo = MagicMock()
        # 3 rows: browser(10), browser(20), email(10)
        mock_repo.bulk_create_deliveries = AsyncMock(return_value=[1, 2, 3])
        MockRepo.return_value = mock_repo

        db = AsyncMock()
        result = await create_deliveries_for_dispatch(
            db=db,
            event="lead_assigned",
            channel_recipient_map={"browser": [10, 20], "email": [10]},
            notification_id_map={10: 100, 20: 200},
            dedupe_key="dedup-1",
            payload_snapshot={"title": "T"},
            source_type="lead",
            source_id=42,
        )

        # Should return dict mapping channel -> delivery IDs
        assert isinstance(result, dict)
        assert result["browser"] == [1, 2]
        assert result["email"] == [3]

        # Verify bulk_create_deliveries was called with 3 rows
        call_args = mock_repo.bulk_create_deliveries.call_args
        deliveries_data = call_args[0][0]
        assert len(deliveries_data) == 3

        # Verify source_type/source_id populated
        assert all(d["source_type"] == "lead" for d in deliveries_data)
        assert all(d["source_id"] == 42 for d in deliveries_data)

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_empty_channel_map_returns_empty_dict(self, MockRepo):
        db = AsyncMock()
        result = await create_deliveries_for_dispatch(
            db=db,
            event="test_event",
            channel_recipient_map={},
            notification_id_map={},
        )
        assert result == {}
        MockRepo.return_value.bulk_create_deliveries.assert_not_called()


@pytest.mark.asyncio
class TestPrepareExternalDeliveries:
    """Tests for prepare_external_deliveries with mocked repo."""

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_creates_external_rows(self, MockRepo):
        mock_repo = MagicMock()
        mock_repo.bulk_create_deliveries = AsyncMock(return_value=[10, 11])
        MockRepo.return_value = mock_repo

        db = AsyncMock()
        recipients = [
            {"source_type": "lead", "source_id": 1, "destination": "84901234567"},
            {"source_type": "lead", "source_id": 2, "destination": "84907654321"},
        ]

        result = await prepare_external_deliveries(
            db=db,
            event="lead_created",
            channel="zalo",
            recipients=recipients,
        )

        assert result == [10, 11]
        call_args = mock_repo.bulk_create_deliveries.call_args
        deliveries_data = call_args[0][0]
        assert len(deliveries_data) == 2
        assert all(d["recipient_kind"] == "external" for d in deliveries_data)
        assert all(d["user_id"] is None for d in deliveries_data)

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_empty_recipients_returns_empty(self, MockRepo):
        db = AsyncMock()
        result = await prepare_external_deliveries(
            db=db, event="test", channel="sms", recipients=[]
        )
        assert result == []


@pytest.mark.asyncio
class TestMarkDeliveryIds:
    """Tests for ID-scoped mark_delivery_ids_* functions."""

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_mark_sent_calls_bulk_update(self, MockRepo):
        mock_repo = MagicMock()
        mock_repo.bulk_update_status = AsyncMock(return_value=3)
        MockRepo.return_value = mock_repo

        db = AsyncMock()
        updated = await mark_delivery_ids_sent(db, [1, 2, 3])

        assert updated == 3
        mock_repo.bulk_update_status.assert_called_once()
        call_args = mock_repo.bulk_update_status.call_args
        assert call_args[0][0] == [1, 2, 3]
        assert call_args[0][1] == "sent"

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_mark_failed_passes_error_reason(self, MockRepo):
        mock_repo = MagicMock()
        mock_repo.bulk_update_status = AsyncMock(return_value=2)
        MockRepo.return_value = mock_repo

        db = AsyncMock()
        updated = await mark_delivery_ids_failed(db, [4, 5], error_reason="SMTP error")

        assert updated == 2
        call_args = mock_repo.bulk_update_status.call_args
        assert call_args[1]["error_reason"] == "SMTP error"

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_mark_skipped_default_reason(self, MockRepo):
        mock_repo = MagicMock()
        mock_repo.bulk_update_status = AsyncMock(return_value=1)
        MockRepo.return_value = mock_repo

        db = AsyncMock()
        updated = await mark_delivery_ids_skipped(db, [6])

        assert updated == 1
        call_args = mock_repo.bulk_update_status.call_args
        assert call_args[1]["error_reason"] == "channel_not_live"


@pytest.mark.asyncio
class TestLegacyMarkChannel:
    """Tests for legacy mark_channel_* functions (backward compat)."""

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_mark_channel_sent_resolves_and_updates(self, MockRepo):
        mock_record_1 = MagicMock(id=1, user_id=10)
        mock_record_2 = MagicMock(id=2, user_id=20)

        mock_repo = MagicMock()
        mock_repo.list_deliveries = AsyncMock(
            return_value=([mock_record_1, mock_record_2], 2)
        )
        mock_repo.bulk_update_status = AsyncMock(return_value=1)
        MockRepo.return_value = mock_repo

        db = AsyncMock()
        updated = await mark_channel_sent(
            db=db, event="test", channel="browser", user_ids=[10]
        )

        assert updated == 1
        # Should have called bulk_update_status with just [1] (user_id=10)
        call_args = mock_repo.bulk_update_status.call_args
        assert call_args[0][0] == [1]
        assert call_args[0][1] == "sent"

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_mark_channel_failed_with_error(self, MockRepo):
        mock_record = MagicMock(id=5, user_id=10)
        mock_repo = MagicMock()
        mock_repo.list_deliveries = AsyncMock(return_value=([mock_record], 1))
        mock_repo.bulk_update_status = AsyncMock(return_value=1)
        MockRepo.return_value = mock_repo

        db = AsyncMock()
        updated = await mark_channel_failed(
            db=db, event="test", channel="email",
            user_ids=[10], error_reason="SMTP timeout"
        )

        assert updated == 1
        call_args = mock_repo.bulk_update_status.call_args
        assert call_args[1]["error_reason"] == "SMTP timeout"

    @patch("app.services.notification_delivery_service.NotificationDeliveryRepository")
    async def test_mark_channel_skipped_no_matches(self, MockRepo):
        mock_repo = MagicMock()
        mock_repo.list_deliveries = AsyncMock(return_value=([], 0))
        mock_repo.bulk_update_status = AsyncMock(return_value=0)
        MockRepo.return_value = mock_repo

        db = AsyncMock()
        updated = await mark_channel_skipped(
            db=db, event="test", channel="zalo", user_ids=[999]
        )

        assert updated == 0
