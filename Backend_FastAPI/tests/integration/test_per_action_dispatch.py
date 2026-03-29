# tests/integration/test_per_action_dispatch.py
"""
Phase 3b integration tests: dispatch() with per-action recipient resolution.

Proves end-to-end:
- Multiple actions with different channels both deliver
- Per-action recipient_config uses action-specific resolver
- Legacy rules (no action recipient_config) still work
- has_external_actions prevents short-circuit
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.notification_dispatcher import dispatch


def _mock_side_effects(mocker):
    """Mock Socket.IO + channel delivery so tests focus on dispatch logic."""
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


def _mock_redis(mocker):
    """Bypass Redis cache + cooldown."""
    mocker.patch(
        "app.services.notification_rule_loader.safe_redis_get",
        new_callable=AsyncMock, return_value=None,
    )
    mocker.patch(
        "app.services.notification_rule_loader.safe_redis_set",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "app.services.notification_dispatcher.safe_redis_exists",
        new_callable=AsyncMock, return_value=False,
    )
    mocker.patch(
        "app.services.notification_dispatcher.safe_redis_incr",
        new_callable=AsyncMock, return_value=1,
    )
    mocker.patch(
        "app.services.notification_dispatcher.safe_redis_set",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "app.services.notification_dispatcher.safe_redis_expire",
        new_callable=AsyncMock,
    )


async def _seed_rule_with_actions(
    db: AsyncSession, *, event: str, actions_data: list, condition=None,
    recipient_config=None,
) -> models.NotificationRule:
    """Seed a DB rule with multiple actions."""
    template = models.NotificationTemplate(
        template_code=f"TPL_3B_{event}_{id(actions_data) % 10000}",
        name=f"Phase 3b Test {event}",
        title_template="Test: ${lead_name}",
        message_template="Per-action test for ${lead_name}",
        template_type="system",
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)

    rule = models.NotificationRule(
        event=event,
        template_id=template.id,
        title_template=template.title_template,
        message_template=template.message_template,
        channels=["browser"],
        recipient_config=recipient_config or {"resolver_type": "lead_owner", "params": {}},
        condition=condition,
        enabled=True,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)

    for action_data in actions_data:
        action = models.NotificationAction(
            rule_id=rule.id,
            **action_data,
        )
        db.add(action)
    await db.flush()
    return rule


@pytest.mark.asyncio
@pytest.mark.integration
class TestPerActionDispatch:
    """Integration: dispatch() with per-action recipients."""

    async def test_browser_plus_email_both_deliver(
        self, db: AsyncSession, officer_user: models.User,
        seeded_dependencies: dict, mocker,
    ):
        """Rule with browser + email actions, same resolver → both get delivery rows."""
        _mock_side_effects(mocker)
        _mock_redis(mocker)

        await _seed_rule_with_actions(
            db, event="lead_created",
            actions_data=[
                {"step": 1, "channel": "browser", "delay_minutes": 0},
                {"step": 2, "channel": "email", "delay_minutes": 0},
            ],
        )
        await db.commit()

        payload = {
            "lead_id": 9999, "lead_name": "Test Lead",
            "unit_id": seeded_dependencies["unit_id"], "source": "test",
            "officer_id": officer_user.id,
            "actor_id": officer_user.id, "actor_name": officer_user.full_name,
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_CREATED, payload=payload,
            skip_preference_check=True,
        )
        await db.commit()
        if callback:
            await callback()

        # Browser action should create inbox notification
        assert notification_ids, "Browser action should create inbox notification"

        # Check delivery rows exist for both channels
        from app.models.notification_delivery import NotificationDelivery
        result = await db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.event == "lead_created",
                NotificationDelivery.user_id == officer_user.id,
            )
        )
        deliveries = result.scalars().all()
        channels_delivered = {d.channel for d in deliveries}
        assert "browser" in channels_delivered, "Browser delivery row should exist"
        assert "email" in channels_delivered, "Email delivery row should exist"

    async def test_legacy_rule_backward_compat(
        self, db: AsyncSession, officer_user: models.User,
        seeded_dependencies: dict, mocker,
    ):
        """Legacy rule (no action recipient_config) still works."""
        _mock_side_effects(mocker)
        _mock_redis(mocker)

        await _seed_rule_with_actions(
            db, event="lead_assigned",
            actions_data=[
                {"step": 1, "channel": "browser", "delay_minutes": 0},
            ],
        )
        await db.commit()

        payload = {
            "lead_id": 9999, "lead_name": "Legacy Lead",
            "officer_id": officer_user.id,
            "actor_id": officer_user.id, "actor_name": officer_user.full_name,
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_ASSIGNED, payload=payload,
            skip_preference_check=True,
        )
        await db.commit()
        if callback:
            await callback()

        assert notification_ids, "Legacy rule should still create notifications"

    async def test_per_action_recipient_config_code_path(
        self, db: AsyncSession, officer_user: models.User,
        seeded_dependencies: dict, mocker,
    ):
        """Action with custom recipient_config triggers per-action resolver code path.

        Rule-level: lead_owner → officer (via officer_id)
        Action 2: lead_owner (same resolver, but via action.recipient_config path)
        Proves the deserialize_resolver + per-action resolution code path executes.
        """
        _mock_side_effects(mocker)
        _mock_redis(mocker)

        await _seed_rule_with_actions(
            db, event="lead_created",
            recipient_config={"resolver_type": "lead_owner", "params": {}},
            actions_data=[
                {"step": 1, "channel": "browser", "delay_minutes": 0},
                {
                    "step": 2, "channel": "email", "delay_minutes": 0,
                    # Per-action recipient_config — triggers action-specific resolver path
                    "recipient_config": {
                        "resolver_type": "lead_owner",
                        "params": {},
                    },
                    "branch_key": "officer_email",
                },
            ],
        )
        await db.commit()

        payload = {
            "lead_id": 9999, "lead_name": "Branch Test Lead",
            "unit_id": seeded_dependencies["unit_id"], "source": "test",
            "officer_id": officer_user.id,
            "actor_id": officer_user.id, "actor_name": officer_user.full_name,
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_CREATED, payload=payload,
            skip_preference_check=True,
        )
        await db.commit()
        if callback:
            await callback()

        from app.models.notification_delivery import NotificationDelivery
        result = await db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.event == "lead_created",
            )
        )
        deliveries = result.scalars().all()
        channels_delivered = {d.channel for d in deliveries}

        # Both actions resolve to same officer, but via different code paths
        assert "browser" in channels_delivered, "Browser delivery (rule resolver)"
        assert "email" in channels_delivered, "Email delivery (action resolver)"
        # Both point to same user (officer)
        assert all(d.user_id == officer_user.id for d in deliveries)
