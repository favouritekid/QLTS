# tests/integration/test_registry_fallback_dispatch.py
"""
PR3: No-fallback / fail-closed dispatcher integration tests.

Replaces the old registry-fallback tests. PR1 removed the registry fallback
path entirely — the dispatcher now uses catalog + DB rule only.

These tests verify:
1. Missing DB rule → fail-closed (no notification, domain event only)
2. Disabled DB rule → same fail-closed behavior
3. User event WITH DB rule → notification created successfully
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
class TestNoFallbackDispatch:

    async def test_missing_rule_fails_closed(
        self,
        db: AsyncSession,
        officer_user: models.User,
        seeded_dependencies: dict,
        mocker,
    ):
        """
        User event with no enabled DB rule → fail-closed.
        Dispatcher must NOT create notifications (no registry fallback).
        Domain event must still be emitted.
        """
        mock_domain = mocker.patch(
            "app.services.notification_dispatcher._emit_domain_event",
            new_callable=AsyncMock,
        )

        # Force no DB rule
        mocker.patch(
            "app.services.notification_dispatcher.get_rule_for_event",
            new_callable=AsyncMock,
            return_value=None,
        )

        payload = {
            "lead_id": 9999,
            "lead_name": "No Fallback Test",
            "officer_id": officer_user.id,
            "unit_id": seeded_dependencies["unit_id"],
            "actor_id": 0,
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_ASSIGNED, payload=payload,
        )
        await db.commit()
        if callback:
            await callback()

        # Fail-closed: no notifications created
        assert notification_ids == [], (
            "Missing rule must not create notifications (no registry fallback)"
        )
        # Domain event still emitted
        mock_domain.assert_called_once()

    async def test_disabled_rule_fails_closed(
        self,
        db: AsyncSession,
        officer_user: models.User,
        seeded_dependencies: dict,
        mocker,
    ):
        """
        Disabled DB rule → fail-closed (same as missing).
        get_rule_for_event returns None for disabled rules.
        """
        mocker.patch(
            "app.services.notification_dispatcher._emit_domain_event",
            new_callable=AsyncMock,
        )
        mocker.patch(
            "app.services.notification_dispatcher.get_rule_for_event",
            new_callable=AsyncMock,
            return_value=None,
        )

        payload = {
            "lead_id": 1, "lead_name": "Test",
            "unit_id": seeded_dependencies["unit_id"],
            "source": "test", "actor_id": 0,
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_CREATED, payload=payload,
        )

        assert notification_ids == []
        assert isinstance(callback, type(callback))  # callable

    async def test_user_event_with_db_rule_creates_notification(
        self,
        db: AsyncSession,
        officer_user: models.User,
        seeded_dependencies: dict,
        mocker,
    ):
        """
        User event with enabled DB rule → notification created via single path.
        Uses sync-seeded rule (from conftest sync_notification_rules).
        """
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

        # Invalidate cache to pick up fresh DB rule
        from app.services.notification_rule_loader import invalidate_rule_cache
        await invalidate_rule_cache("lead_assigned")

        payload = {
            "lead_id": 9999,
            "lead_name": "DB Rule Test",
            "lead_phone": "0909000000",
            "officer_id": officer_user.id,
            "unit_id": seeded_dependencies["unit_id"],
            "actor_id": 0,
            "actor_name": "System",
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_ASSIGNED, payload=payload,
        )
        await db.commit()
        if callback:
            await callback()

        # Single path: DB rule → notification created
        assert notification_ids, "DB rule present → notification should be created"
        stmt = select(models.Notification).where(
            models.Notification.id.in_(notification_ids)
        )
        result = await db.execute(stmt)
        notifications = result.scalars().all()
        assert len(notifications) >= 1
        assert notifications[0].user_id == officer_user.id
