# tests/integration/test_condition_dispatch.py
"""
Phase 2 integration tests: dispatch() + DB rule with condition.

Proves end-to-end:
- Rule loaded from DB (not registry)
- Condition canonicalized/evaluated at runtime
- Evaluation context built with projection + enrichment
- Dispatch creates notification when condition matches
- Dispatch skips notification when condition misses
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.notification_dispatcher import dispatch


def _mock_side_effects(mocker):
    """Mock Socket.IO + channel delivery so tests focus on condition logic."""
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


def _mock_redis_cache(mocker):
    """Bypass Redis rule cache + cooldown/rate-limit so tests focus on condition logic."""
    mocker.patch(
        "app.services.notification_rule_loader.safe_redis_get",
        new_callable=AsyncMock,
        return_value=None,
    )
    mocker.patch(
        "app.services.notification_rule_loader.safe_redis_set",
        new_callable=AsyncMock,
    )
    # Mock dispatcher Redis functions for cooldown/rate-limit
    mocker.patch(
        "app.services.notification_dispatcher.safe_redis_exists",
        new_callable=AsyncMock,
        return_value=False,
    )
    mocker.patch(
        "app.services.notification_dispatcher.safe_redis_incr",
        new_callable=AsyncMock,
        return_value=1,
    )
    mocker.patch(
        "app.services.notification_dispatcher.safe_redis_set",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "app.services.notification_dispatcher.safe_redis_expire",
        new_callable=AsyncMock,
    )


async def _seed_rule(
    db: AsyncSession, *, event: str, condition: dict | None, officer_id: int
) -> models.NotificationRule:
    """Seed a DB rule that resolves to a specific officer via lead_owner resolver."""
    template = models.NotificationTemplate(
        template_code=f"TPL_COND_{event}_{id(condition) % 10000}",
        name=f"Condition Test {event}",
        title_template="Test: ${lead_name}",
        message_template="Condition test for ${lead_name}",
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
        # lead_owner resolver: sends notification to the officer_id in payload
        recipient_config={"resolver_type": "lead_owner", "params": {}},
        condition=condition,
        enabled=True,
    )
    db.add(rule)
    await db.flush()
    return rule


@pytest.mark.asyncio
@pytest.mark.integration
class TestConditionDispatch:
    """Integration: dispatch + DB rule with condition evaluation."""

    async def test_actor_role_eq_manager_matches(
        self,
        db: AsyncSession,
        manager_user: models.User,
        seeded_dependencies: dict,
        mocker,
    ):
        """
        DB rule: actor.role eq manager → should create notification.
        Proves: evaluation context enriches actor.role via User DB lookup.
        """
        _mock_side_effects(mocker)
        _mock_redis_cache(mocker)

        # lead_owner resolver sends to officer_id in payload
        # We set officer_id = manager_user.id so they receive the notification
        await _seed_rule(
            db,
            event="lead_created",
            condition={"field": "actor.role", "operator": "eq", "value": "manager"},
            officer_id=manager_user.id,
        )
        await db.commit()

        payload = {
            "lead_id": 9999,
            "lead_name": "Condition Test Lead",
            "unit_id": seeded_dependencies["unit_id"],
            "source": "test",
            "actor_id": manager_user.id,
            "actor_name": manager_user.full_name,
            "officer_id": manager_user.id,  # resolver target
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_CREATED, payload=payload,
            skip_preference_check=True,
        )
        await db.commit()
        if callback:
            await callback()

        assert notification_ids, "Condition actor.role eq manager should match for manager user"

    async def test_event_new_status_id_matches(
        self,
        db: AsyncSession,
        officer_user: models.User,
        seeded_dependencies: dict,
        mocker,
    ):
        """
        DB rule: event.new_status_id eq <initial_status> → should match.
        Proves: event.* projection maps flat payload to nested context.
        """
        _mock_side_effects(mocker)
        _mock_redis_cache(mocker)

        status_id = seeded_dependencies["initial_status_id"]

        await _seed_rule(
            db,
            event="lead_status_changed",
            condition={"field": "event.new_status_id", "operator": "eq", "value": status_id},
            officer_id=officer_user.id,
        )
        await db.commit()

        payload = {
            "lead_id": 9999,
            "lead_name": "Status Test Lead",
            "officer_id": officer_user.id,
            "officer_name": officer_user.full_name,
            "old_status": "none",
            "new_status": status_id,  # matches condition
            "actor_id": officer_user.id,
            "actor_name": officer_user.full_name,
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_STATUS_CHANGED, payload=payload,
            skip_preference_check=True,
        )
        await db.commit()
        if callback:
            await callback()

        assert notification_ids, (
            f"Condition event.new_status_id eq '{status_id}' should match"
        )

    async def test_legacy_flat_field_and_operator_still_matches(
        self,
        db: AsyncSession,
        officer_user: models.User,
        seeded_dependencies: dict,
        mocker,
    ):
        """
        Legacy rule: new_status == <status> (symbolic op + flat field) → match.
        Proves: OPERATOR_ALIASES + FIELD_ALIASES + flat key fallback work together.
        """
        _mock_side_effects(mocker)
        _mock_redis_cache(mocker)

        status_id = seeded_dependencies["initial_status_id"]

        # Seed with LEGACY format
        await _seed_rule(
            db,
            event="lead_status_changed",
            condition={"field": "new_status", "operator": "==", "value": status_id},
            officer_id=officer_user.id,
        )
        await db.commit()

        payload = {
            "lead_id": 9999,
            "lead_name": "Legacy Test Lead",
            "officer_id": officer_user.id,
            "officer_name": officer_user.full_name,
            "old_status": "none",
            "new_status": status_id,
            "actor_id": officer_user.id,
            "actor_name": officer_user.full_name,
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_STATUS_CHANGED, payload=payload,
            skip_preference_check=True,
        )
        await db.commit()
        if callback:
            await callback()

        assert notification_ids, (
            "Legacy rule with flat 'new_status' and '==' should match "
            "via alias + operator normalization"
        )

    async def test_condition_miss_skips_notification(
        self,
        db: AsyncSession,
        officer_user: models.User,
        seeded_dependencies: dict,
        mocker,
    ):
        """
        DB rule: event.new_status_id eq "nonexistent" → should NOT match.
        Proves: dispatch skips notification when condition evaluates False.
        """
        _mock_side_effects(mocker)
        _mock_redis_cache(mocker)

        await _seed_rule(
            db,
            event="lead_status_changed",
            condition={"field": "event.new_status_id", "operator": "eq", "value": "nonexistent"},
            officer_id=officer_user.id,
        )
        await db.commit()

        payload = {
            "lead_id": 9999,
            "lead_name": "Miss Test Lead",
            "officer_id": officer_user.id,
            "officer_name": officer_user.full_name,
            "old_status": "none",
            "new_status": seeded_dependencies["initial_status_id"],  # != "nonexistent"
            "actor_id": officer_user.id,
            "actor_name": officer_user.full_name,
        }

        notification_ids, callback = await dispatch(
            db=db, event=SystemEvents.LEAD_STATUS_CHANGED, payload=payload,
            skip_preference_check=True,
        )
        await db.commit()
        if callback:
            await callback()

        assert notification_ids == [], (
            "Condition miss should skip notification"
        )
