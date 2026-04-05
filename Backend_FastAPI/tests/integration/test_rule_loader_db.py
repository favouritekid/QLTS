# tests/integration/test_rule_loader_db.py
"""
PR3.5: Rule loader DB-backed integration tests.

Tests notification_rule_loader.py against real DB (not mocked).
Covers: load enabled, disabled, duplicate, template eager-load, malformed resolver.
"""
import pytest
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.notification_rule_loader import (
    get_rule_for_event,
    invalidate_rule_cache,
)


@pytest.mark.asyncio
@pytest.mark.integration
class TestRuleLoaderDB:
    """Rule loader against real database."""

    async def test_load_enabled_rule(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Enabled rule should load successfully."""
        await invalidate_rule_cache("lead_assigned")
        config = await get_rule_for_event(db, SystemEvents.LEAD_ASSIGNED)
        assert config is not None, "lead_assigned should have an enabled rule from sync"
        assert config.event == "lead_assigned"
        assert config.title_template  # non-empty

    async def test_disabled_rule_returns_none(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Disabled rule should return None."""
        # Disable the rule
        result = await db.execute(
            select(models.NotificationRule)
            .where(models.NotificationRule.event == "system_alert")
        )
        rule = result.scalar_one_or_none()
        if not rule:
            pytest.skip("No system_alert rule")

        original = rule.enabled
        rule.enabled = False
        await db.commit()
        await invalidate_rule_cache("system_alert")

        config = await get_rule_for_event(db, SystemEvents.SYSTEM_ALERT)
        assert config is None, "Disabled rule should return None"

        # Restore
        rule.enabled = original
        await db.commit()
        await invalidate_rule_cache("system_alert")

    async def test_duplicate_enabled_rules_raises_config_error(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Multiple enabled rules for same event should raise NotificationConfigError."""
        from app.utils.exceptions import NotificationConfigError

        # Create a duplicate enabled rule
        dup = models.NotificationRule(
            event="lead_assigned",
            title_template="Duplicate",
            message_template="Duplicate",
            notification_type="info",
            channels=["browser"],
            recipient_config={"resolver_type": "lead_owner", "params": {}},
            enabled=True,
        )
        db.add(dup)
        await db.commit()
        await invalidate_rule_cache("lead_assigned")

        with pytest.raises(NotificationConfigError, match="enabled rules"):
            await get_rule_for_event(db, SystemEvents.LEAD_ASSIGNED)

        # Cleanup
        await db.delete(dup)
        await db.commit()
        await invalidate_rule_cache("lead_assigned")

    async def test_malformed_resolver_raises_config_error(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Malformed recipient_config should raise NotificationConfigError."""
        from app.utils.exceptions import NotificationConfigError

        # Create rule with bad resolver
        await db.execute(
            delete(models.NotificationRule)
            .where(models.NotificationRule.event == "holiday_calendar_incomplete")
        )
        bad = models.NotificationRule(
            event="holiday_calendar_incomplete",
            title_template="Bad",
            message_template="Bad",
            notification_type="info",
            channels=["browser"],
            recipient_config={"resolver_type": "nonexistent_resolver_xyz", "params": {}},
            enabled=True,
        )
        db.add(bad)
        await db.commit()
        await invalidate_rule_cache("holiday_calendar_incomplete")

        with pytest.raises(NotificationConfigError, match="invalid recipient_config"):
            await get_rule_for_event(db, SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE)

        # Cleanup
        await db.delete(bad)
        await db.commit()
        await invalidate_rule_cache("holiday_calendar_incomplete")

    async def test_template_eager_load(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Rule with template_id should eager-load template content."""
        # Create a template
        tpl = models.NotificationTemplate(
            name="EagerLoadTest",
            template_code="TPL_EAGER_LOAD_TEST",
            title_template="Template Title: $lead_name",
            message_template="Template Msg",
            template_type="system",
        )
        db.add(tpl)
        await db.flush()
        await db.refresh(tpl)

        # Create rule referencing template
        await db.execute(
            delete(models.NotificationRule)
            .where(models.NotificationRule.event == "pipeline_config_updated")
        )
        rule = models.NotificationRule(
            event="pipeline_config_updated",
            title_template="Rule Title (should be overridden)",
            message_template="Rule Msg",
            notification_type="info",
            channels=["browser"],
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True,
            template_id=tpl.id,
        )
        db.add(rule)
        await db.commit()
        await invalidate_rule_cache("pipeline_config_updated")

        config = await get_rule_for_event(db, SystemEvents.PIPELINE_CONFIG_UPDATED)
        assert config is not None
        # Template content should override rule content
        assert "Template Title" in config.title_template

        # Cleanup
        await db.delete(rule)
        await db.delete(tpl)
        await db.commit()
        await invalidate_rule_cache("pipeline_config_updated")


@pytest.mark.asyncio
@pytest.mark.integration
class TestSyncScriptDB:
    """Sync script against real database."""

    async def test_fresh_sync_creates_all_user_rules(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """After sync (via seeded_dependencies), all user events should have rules."""
        from app.core.event_catalog import get_notifiable_events

        user_keys = {d.event.value for d in get_notifiable_events()}
        result = await db.execute(select(models.NotificationRule.event))
        db_events = {row[0] for row in result.fetchall()}

        missing = user_keys - db_events
        assert not missing, f"User events missing DB rules after sync: {missing}"

    async def test_sync_is_idempotent_in_db(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Running sync again should create 0 new rules."""
        from app.scripts.sync_notification_rules import sync_notification_rules

        result = await sync_notification_rules(db)
        assert result["created"] == 0, f"Idempotent sync created {result['created']}"
        assert result["missing_user_rules"] == 0

    async def test_orphan_rules_counted(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Orphan DB rules (events not in catalog) should be counted."""
        from app.scripts.sync_notification_rules import sync_notification_rules

        orphan = models.NotificationRule(
            event="totally_fake_orphan_event",
            title_template="Orphan",
            message_template="Orphan",
            notification_type="info",
            channels=["browser"],
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=False,
        )
        db.add(orphan)
        await db.commit()

        result = await sync_notification_rules(db)
        assert result["orphan_rules"] >= 1, "Orphan rule should be counted"

        # Cleanup
        await db.delete(orphan)
        await db.commit()
