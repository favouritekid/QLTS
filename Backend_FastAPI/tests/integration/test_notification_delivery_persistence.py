# tests/integration/test_notification_delivery_persistence.py
"""
Phase B12: Integration tests for notification delivery persistence.

Tests end-to-end flow: dispatch creates Notification + NotificationDelivery rows,
status transitions work correctly, and external recipients don't crash.
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
from app.repositories.notification_consent_repository import NotificationConsentRepository
from app.services import notification_delivery_service

log = logging.getLogger(__name__)


@pytest.mark.asyncio
@pytest.mark.integration
class TestDeliveryPersistence:
    """Integration tests for delivery record lifecycle."""

    async def test_create_and_query_delivery(self, db: AsyncSession, admin_user):
        """Create a delivery record and query it back."""
        repo = NotificationDeliveryRepository(db)

        delivery = await repo.create_delivery(
            event="lead_assigned",
            channel="browser",
            recipient_kind="internal",
            user_id=admin_user.id,
            source_type="lead",
            source_id=1,
            status="queued",
            payload_snapshot={"title": "Test", "message": "Hello"},
        )
        await db.flush()

        # Query back
        record = await repo.get_by_id(delivery.id)
        assert record is not None
        assert record.event == "lead_assigned"
        assert record.channel == "browser"
        assert record.status == "queued"
        assert record.payload_snapshot == {"title": "Test", "message": "Hello"}

    async def test_update_status_to_sent(self, db: AsyncSession, admin_user):
        """Update delivery status from queued to sent."""
        repo = NotificationDeliveryRepository(db)

        delivery = await repo.create_delivery(
            event="test_event",
            channel="email",
            recipient_kind="internal",
            user_id=admin_user.id,
            status="queued",
        )
        await db.flush()

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        await repo.update_status(delivery.id, "sent", sent_at=now)
        await db.flush()

        record = await repo.get_by_id(delivery.id)
        assert record.status == "sent"
        assert record.sent_at is not None

    async def test_update_status_to_failed(self, db: AsyncSession, admin_user):
        """Update delivery status from queued to failed with error reason."""
        repo = NotificationDeliveryRepository(db)

        delivery = await repo.create_delivery(
            event="test_event",
            channel="email",
            recipient_kind="internal",
            user_id=admin_user.id,
            status="queued",
        )
        await db.flush()

        await repo.update_status(delivery.id, "failed", error_reason="SMTP timeout")
        await db.flush()

        record = await repo.get_by_id(delivery.id)
        assert record.status == "failed"
        assert record.error_reason == "SMTP timeout"

    async def test_list_deliveries_filter(self, db: AsyncSession, admin_user):
        """List deliveries with filters returns correct results."""
        repo = NotificationDeliveryRepository(db)

        # Create mixed deliveries
        await repo.create_delivery(
            event="lead_assigned", channel="browser",
            recipient_kind="internal", user_id=admin_user.id, status="sent",
        )
        await repo.create_delivery(
            event="lead_assigned", channel="email",
            recipient_kind="internal", user_id=admin_user.id, status="failed",
        )
        await repo.create_delivery(
            event="profile_submitted", channel="browser",
            recipient_kind="internal", user_id=admin_user.id, status="queued",
        )
        await db.flush()

        # Filter by event
        records, total = await repo.list_deliveries(event="lead_assigned")
        assert total == 2
        assert all(r.event == "lead_assigned" for r in records)

        # Filter by channel + status
        records, total = await repo.list_deliveries(channel="browser", status="sent")
        assert total == 1
        assert records[0].status == "sent"

    async def test_external_recipient_delivery_no_crash(self, db: AsyncSession):
        """External delivery (no user_id) creates record without error."""
        repo = NotificationDeliveryRepository(db)

        delivery = await repo.create_delivery(
            event="lead_created",
            channel="zalo",
            recipient_kind="external",
            user_id=None,
            source_type="lead",
            source_id=42,
            destination="84901234567",
            status="queued",
        )
        await db.flush()

        record = await repo.get_by_id(delivery.id)
        assert record is not None
        assert record.recipient_kind == "external"
        assert record.user_id is None
        assert record.destination == "84901234567"


@pytest.mark.asyncio
@pytest.mark.integration
class TestConsentPersistence:
    """Integration tests for consent record lifecycle."""

    async def test_upsert_grant_then_revoke(self, db: AsyncSession, admin_user):
        """Consent upsert: granted -> revoked -> granted."""
        repo = NotificationConsentRepository(db)

        # Grant
        result = await repo.upsert_latest({
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 1,
            "consent_status": "granted",
            "consent_source": "manual",
            "granted_by": admin_user.id,
        })
        await db.flush()
        assert result.consent_status == "granted"

        # Revoke (same unique key)
        result = await repo.upsert_latest({
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 1,
            "consent_status": "revoked",
            "consent_source": "manual",
            "granted_by": admin_user.id,
        })
        await db.flush()
        assert result.consent_status == "revoked"

        # Re-grant
        result = await repo.upsert_latest({
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 1,
            "consent_status": "granted",
            "consent_source": "manual",
            "granted_by": admin_user.id,
        })
        await db.flush()
        assert result.consent_status == "granted"

        # Only one row should exist
        records, total = await repo.list_consents(
            channel="zalo", source_type="lead"
        )
        matching = [r for r in records if r.source_id == 1]
        assert len(matching) == 1

    async def test_is_consent_granted(self, db: AsyncSession, admin_user):
        """is_consent_granted returns correct boolean."""
        repo = NotificationConsentRepository(db)

        # No record = no consent
        assert await repo.is_consent_granted("zalo", "lead", 999) is False

        # Grant
        await repo.upsert_latest({
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 999,
            "consent_status": "granted",
            "consent_source": "manual",
            "granted_by": admin_user.id,
        })
        await db.flush()
        assert await repo.is_consent_granted("zalo", "lead", 999) is True

        # Revoke
        await repo.upsert_latest({
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 999,
            "consent_status": "revoked",
            "consent_source": "manual",
            "granted_by": admin_user.id,
        })
        await db.flush()
        assert await repo.is_consent_granted("zalo", "lead", 999) is False

    async def test_bulk_upsert_summary(self, db: AsyncSession, admin_user):
        """Bulk upsert returns correct summary counts."""
        repo = NotificationConsentRepository(db)

        rows = [
            {
                "channel": "zalo", "source_type": "lead", "source_id": 10,
                "consent_status": "granted", "consent_source": "csv_import",
                "granted_by": admin_user.id,
            },
            {
                "channel": "zalo", "source_type": "lead", "source_id": 11,
                "consent_status": "revoked", "consent_source": "csv_import",
                "granted_by": admin_user.id,
            },
            {
                "channel": "zalo", "source_type": "lead", "source_id": 12,
                "consent_status": "granted", "consent_source": "csv_import",
                "granted_by": admin_user.id,
            },
        ]

        summary = await repo.bulk_upsert(rows)
        assert summary["processed"] == 3
        assert summary["granted"] == 2
        assert summary["revoked"] == 1
