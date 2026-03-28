# tests/integration/test_registry_fallback_dispatch.py
"""
Integration test: force dispatch() through the registry fallback path.

Step 0 hotfix verification — mock get_rule_for_event() → None so the
dispatcher MUST use in-memory NotificationConfig from NOTIFICATION_REGISTRY.
This is where the original bug (missing .actions) would crash with
AttributeError.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.notification_dispatcher import dispatch


@pytest.mark.asyncio
@pytest.mark.integration
class TestRegistryFallbackDispatch:

    async def test_dispatch_via_registry_fallback_creates_notification(
        self,
        db: AsyncSession,
        officer_user: models.User,
        seeded_dependencies: dict,
        mocker,
    ):
        """
        Dispatch LEAD_ASSIGNED with DB rule returning None.
        Verifies registry path reaches config.actions without AttributeError
        and creates a notification for the resolved recipients.
        """
        # ---- Force registry fallback ----
        mocker.patch(
            "app.services.notification_dispatcher.get_rule_for_event",
            new_callable=AsyncMock,
            return_value=None,
        )

        # ---- Mock side-effects so test doesn't need Redis/Socket.IO ----
        mocker.patch(
            "app.services.notification_dispatcher._emit_domain_event",
            new_callable=AsyncMock,
        )
        mock_result = MagicMock(sent_count=1, failed_ids=[], success=True)
        mocker.patch(
            "app.services.notification_dispatcher._send_via_channel",
            new_callable=AsyncMock,
            return_value=("browser", mock_result, None),
        )

        # LEAD_ASSIGNED uses LeadOwnerResolver → resolves officer_id from payload
        payload = {
            "lead_id": 9999,
            "lead_name": "Registry Fallback Test Lead",
            "lead_phone": "0900000000",
            "officer_id": officer_user.id,
            "unit_id": seeded_dependencies["unit_id"],
            "actor_id": 0,
            "actor_name": "System",
            "offering_name": "N/A",
        }

        # ---- Act ----
        notification_ids, callback = await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNED,
            payload=payload,
        )
        await db.commit()
        if callback:
            await callback()

        # ---- Assert ----
        # If we reached here, dispatch() did NOT raise AttributeError
        # on config.actions for the registry NotificationConfig.

        # Verify notification was actually created for the officer
        assert notification_ids, (
            "dispatch() returned empty list — registry fallback path "
            "did not create a notification for the resolved recipient"
        )
        stmt = select(models.Notification).where(
            models.Notification.id.in_(notification_ids)
        )
        result = await db.execute(stmt)
        notifications = result.scalars().all()
        assert len(notifications) >= 1
        notif = notifications[0]
        assert "Lead" in notif.title or "Assigned" in notif.title
        assert notif.user_id == officer_user.id

    async def test_dispatch_via_registry_fallback_no_attribute_error(
        self,
        db: AsyncSession,
        mocker,
    ):
        """
        Minimal test: dispatch an event with no recipients to confirm
        config.actions is accessed without error on the registry path.
        Even if no notification is created, the absence of AttributeError
        proves the hotfix.
        """
        # Force registry fallback
        mocker.patch(
            "app.services.notification_dispatcher.get_rule_for_event",
            new_callable=AsyncMock,
            return_value=None,
        )
        mocker.patch(
            "app.services.notification_dispatcher._emit_domain_event",
            new_callable=AsyncMock,
        )

        # UnitManagersResolver with unit_id=0 → empty list → no crash
        payload = {
            "lead_id": 1,
            "unit_id": 0,
            "lead_name": "Test",
            "source": "test",
            "actor_id": 0,
            "actor_name": "System",
        }

        # MUST NOT raise AttributeError: 'NotificationConfig' has no attribute 'actions'
        notification_ids, callback = await dispatch(
            db=db,
            event=SystemEvents.LEAD_CREATED,
            payload=payload,
        )

        # No recipients → empty result, but NO crash
        assert isinstance(notification_ids, list)
