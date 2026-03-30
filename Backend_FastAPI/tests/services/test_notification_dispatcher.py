# tests/services/test_notification_dispatcher.py
"""
Integration tests for notification dispatcher.

Verifies the full dispatch pipeline:
Resolver -> Preference Filter -> Template Rendering -> DB Persistence -> Side Effects
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.notification_dispatcher import dispatch


@pytest.mark.asyncio
@pytest.mark.integration
class TestNotificationDispatcher:
    """Integration tests for notification dispatcher using real database."""

    async def test_dispatch_end_to_end_success(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict,
        mocker
    ):
        """
        Test successful end-to-end dispatch.
        """
        # Arrange
        user_id = officer_user_in_db["id"]
        # Use UNIT_CREATED for success test
        event = SystemEvents.SYSTEM_ALERT
        
        # 1. Seed reusable template
        # FIX: Use ${} for string.Template compatibility
        template = models.NotificationTemplate(
            template_code="TPL_SUCCESS",
            name="Success Template",
            title_template="Unit Created: ${unit_name}",
            message_template="New unit ${unit_name} created.",
            template_type="system"
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        
        # 2. Seed rule
        rule = models.NotificationRule(
            event=event.value,
            template_id=template.id,
            title_template=template.title_template,
            message_template=template.message_template,
            channels=["browser"],
            recipient_config={"resolver_type": "specific_users", "params": {}},
            enabled=True
        )
        db.add(rule)
        await db.commit()
        
        # 3. Mocks for NOTIFICATION 2.0 side effects
        mock_domain_emit = mocker.patch(
            "app.services.notification_dispatcher._emit_domain_event", 
            new_callable=AsyncMock
        )
        # Mock _send_via_channel which returns (channel_name, result, error)
        # result should be an object with sent_count, failed_ids, etc.
        mock_result = MagicMock()
        mock_result.sent_count = 1
        mock_result.failed_ids = []
        mock_result.success = True
        
        mock_channel_send = mocker.patch(
            "app.services.notification_dispatcher._send_via_channel", 
            new_callable=AsyncMock,
            return_value=("browser", mock_result, None)
        )
        
        # Act
        payload = {"user_id": user_id, "unit_name": "Test Unit"}
        notification_ids, callback = await dispatch(db, event, payload)
        
        # Manually trigger the callback (as a real router would after commit)
        if callback:
            await callback()
        
        # Assert
        assert len(notification_ids) == 1
        
        # Verify persistence and rendering
        notification = await db.get(models.Notification, notification_ids[0])
        assert notification is not None
        assert notification.title == "Unit Created: Test Unit"
        assert "New unit Test Unit created." in notification.message
        
        # Verify side effects
        mock_domain_emit.assert_called_once()
        mock_channel_send.assert_called_once()

    async def test_dispatch_deduplication(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict,
        mocker
    ):
        """Should not create duplicate notifications if dedupe_key matches existing data."""
        # Arrange
        user_id = officer_user_in_db["id"]
        # Use UNIT_UPDATED for dedupe test
        event = SystemEvents.SYSTEM_ALERT
        dedupe_key = "unique_dedupe_123"
        
        # Seed Rule
        rule = models.NotificationRule(
            event=event.value,
            title_template="Dedupe Title",
            message_template="Dedupe Message",
            recipient_config={"resolver_type": "specific_users", "params": {}},
            enabled=True
        )
        db.add(rule)
        
        # Create existing notification with SAME dedupe_key in 'data' JSON
        existing_notif = models.Notification(
            user_id=user_id,
            title="Earlier",
            message="Earlier",
            data={"dedupe_key": dedupe_key}
        )
        db.add(existing_notif)
        await db.commit()
        
        # Act
        payload = {"user_id": user_id, "dedupe_key": dedupe_key}
        # Pass dedupe_key to dispatch
        notification_ids, _ = await dispatch(db, event, payload, dedupe_key=dedupe_key)
        
        # Assert
        # Should be empty since it was deduplicated
        assert len(notification_ids) == 0

    async def test_dispatch_disabled_rule(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict
    ):
        """Should skip processing if rule is disabled."""
        # Arrange
        user_id = officer_user_in_db["id"]
        # Use UNIT_DELETED for disabled rule test
        event = SystemEvents.UNIT_DELETED
        
        rule = models.NotificationRule(
            event=event.value,
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "specific_users", "params": {}},
            enabled=False  # DISABLED
        )
        db.add(rule)
        await db.commit()
        
        # Act
        notification_ids, _ = await dispatch(db, event, {"user_id": user_id})
        
        # Assert
        assert len(notification_ids) == 0

    async def test_dispatch_disabled_database_rule_suppresses_registry_fallback(
        self,
        db: AsyncSession,
        officer_user_in_db: dict,
        mocker,
    ):
        """
        If a DB rule exists but is disabled, dispatch() must NOT fall back to
        the hardcoded registry config for the same event.
        """
        user_id = officer_user_in_db["id"]
        event = SystemEvents.SYSTEM_ALERT

        rule = models.NotificationRule(
            event=event.value,
            title_template="Disabled",
            message_template="Disabled",
            recipient_config={"resolver_type": "specific_users", "params": {}},
            enabled=False,
        )
        db.add(rule)
        await db.commit()

        mock_domain_emit = mocker.patch(
            "app.services.notification_dispatcher._emit_domain_event",
            new_callable=AsyncMock,
        )

        notification_ids, callback = await dispatch(
            db,
            event,
            {"user_id": user_id, "severity": "warning", "message": "Registry should stay suppressed"},
        )
        await db.commit()
        if callback:
            await callback()

        result = await db.execute(
            select(models.Notification).where(models.Notification.user_id == user_id)
        )

        assert notification_ids == []
        assert result.scalars().all() == []
        mock_domain_emit.assert_called_once()

    async def test_dispatch_preference_filtering(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict,
        mocker
    ):
        """Should respect user preferences during dispatch."""
        # Arrange
        user_id = officer_user_in_db["id"]
        # Use PROGRAM_CREATED for preference test
        event = SystemEvents.SYSTEM_ALERT
        
        # Disable browser notifications globally for this user
        pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=False
        )
        db.add(pref)
        
        # Rule with browser channel
        rule = models.NotificationRule(
            event=event.value,
            title_template="Title",
            message_template="Message",
            channels=["browser"],
            recipient_config={"resolver_type": "specific_users", "params": {}},
            enabled=True
        )
        db.add(rule)
        await db.commit()
        
        # Act
        notification_ids, _ = await dispatch(db, event, {"user_id": user_id})
        
        # Assert
        # Should be empty because preference filtered out the only channel
        assert len(notification_ids) == 0
