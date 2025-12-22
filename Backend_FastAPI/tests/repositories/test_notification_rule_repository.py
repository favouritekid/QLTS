# tests/repositories/test_notification_rule_repository.py
"""
Integration tests for NotificationRuleRepository.

Covers CRUD operations, action management, and template usage tracking.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.repositories import NotificationRuleRepository


@pytest.mark.asyncio
@pytest.mark.integration
class TestNotificationRuleRepository:
    """Integration tests for NotificationRuleRepository."""

    # =========================================================================
    # GET BY ID
    # =========================================================================

    async def test_get_by_id_returns_rule_with_actions(self, db: AsyncSession):
        """Should return rule with eager-loaded actions."""
        # Arrange - Create rule with actions
        rule = models.NotificationRule(
            event="TEST_EVENT_1",
            title_template="Test Title",
            message_template="Test Message",
            recipient_config={"resolver_type": "specific_users", "params": {}},
            enabled=True
        )
        db.add(rule)
        await db.flush()
        
        action = models.NotificationAction(
            rule_id=rule.id,
            step=1,
            channel="browser",
            delay_minutes=0
        )
        db.add(action)
        await db.commit()
        
        # Act
        repo = NotificationRuleRepository(db)
        result = await repo.get_by_id(rule.id)
        
        # Assert
        assert result is not None
        assert result.event == "TEST_EVENT_1"
        assert len(result.actions) == 1
        assert result.actions[0].channel == "browser"

    async def test_get_by_id_not_found(self, db: AsyncSession):
        """Should return None for non-existent ID."""
        repo = NotificationRuleRepository(db)
        result = await repo.get_by_id(99999)
        assert result is None

    # =========================================================================
    # GET BY EVENT
    # =========================================================================

    async def test_get_by_event_returns_matching_rule(self, db: AsyncSession):
        """Should return rule matching event type."""
        # Arrange
        rule = models.NotificationRule(
            event="UNIQUE_EVENT_123",
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True
        )
        db.add(rule)
        await db.commit()
        
        # Act
        repo = NotificationRuleRepository(db)
        result = await repo.get_by_event("UNIQUE_EVENT_123")
        
        # Assert
        assert result is not None
        assert result.id == rule.id

    async def test_get_by_event_not_found(self, db: AsyncSession):
        """Should return None for non-existent event."""
        repo = NotificationRuleRepository(db)
        result = await repo.get_by_event("NON_EXISTENT_EVENT")
        assert result is None

    # =========================================================================
    # LIST RULES
    # =========================================================================

    async def test_list_rules_pagination(self, db: AsyncSession):
        """Should respect skip and limit parameters."""
        # Arrange - Create 5 rules
        for i in range(5):
            rule = models.NotificationRule(
                event=f"LIST_EVENT_{i}",
                title_template="Title",
                message_template="Message",
                recipient_config={"resolver_type": "all_admins", "params": {}},
                enabled=True
            )
            db.add(rule)
        await db.commit()
        
        # Act
        repo = NotificationRuleRepository(db)
        rules, total = await repo.list_rules(skip=0, limit=3)
        
        # Assert
        assert len(rules) <= 3
        assert total >= 5

    async def test_list_rules_filter_by_event(self, db: AsyncSession):
        """Should filter by event type."""
        # Arrange
        rule1 = models.NotificationRule(
            event="FILTER_EVENT_A",
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True
        )
        rule2 = models.NotificationRule(
            event="FILTER_EVENT_B",
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True
        )
        db.add_all([rule1, rule2])
        await db.commit()
        
        # Act
        repo = NotificationRuleRepository(db)
        rules, total = await repo.list_rules(event="FILTER_EVENT_A")
        
        # Assert
        assert total == 1
        assert rules[0].event == "FILTER_EVENT_A"

    async def test_list_rules_filter_by_enabled(self, db: AsyncSession):
        """Should filter by enabled status."""
        # Arrange
        enabled_rule = models.NotificationRule(
            event="ENABLED_RULE_EVENT",
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True
        )
        disabled_rule = models.NotificationRule(
            event="DISABLED_RULE_EVENT",
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=False
        )
        db.add_all([enabled_rule, disabled_rule])
        await db.commit()
        
        # Act
        repo = NotificationRuleRepository(db)
        enabled_rules, _ = await repo.list_rules(enabled=True)
        disabled_rules, _ = await repo.list_rules(enabled=False)
        
        # Assert
        enabled_events = [r.event for r in enabled_rules]
        disabled_events = [r.event for r in disabled_rules]
        
        assert "ENABLED_RULE_EVENT" in enabled_events
        assert "DISABLED_RULE_EVENT" in disabled_events

    # =========================================================================
    # CREATE WITH ACTIONS
    # =========================================================================

    async def test_create_with_actions_success(self, db: AsyncSession):
        """Should create rule with associated actions."""
        # Arrange
        repo = NotificationRuleRepository(db)
        rule_data = schemas.NotificationRuleCreate(
            event="CREATE_TEST_EVENT",
            title_template="Created Title",
            message_template="Created Message",
            recipient_config=schemas.RecipientConfig(
                resolver_type="lead_owner",
                params={}
            ),
            actions=[
                schemas.NotificationActionCreate(
                    step=1,
                    channel="browser",
                    delay_minutes=0
                ),
                schemas.NotificationActionCreate(
                    step=2,
                    channel="email",
                    delay_minutes=5
                )
            ]
        )
        
        # Act
        result = await repo.create_with_actions(rule_data)
        await db.commit()
        
        # Assert
        assert result.id is not None
        assert result.event == "CREATE_TEST_EVENT"
        
        # Verify actions were created
        rule_with_actions = await repo.get_by_id(result.id)
        assert len(rule_with_actions.actions) == 2

    async def test_create_with_template_increments_usage(self, db: AsyncSession):
        """Should increment template usage_count when referencing a template."""
        # Arrange - Create template
        template = models.NotificationTemplate(
            template_code="TPL_USAGE_TEST",
            name="Usage Test Template",
            title_template="Title",
            message_template="Message",
            usage_count=0
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        
        initial_usage = template.usage_count
        
        # Act
        repo = NotificationRuleRepository(db)
        rule_data = schemas.NotificationRuleCreate(
            event="TEMPLATE_USAGE_EVENT",
            title_template="Title",
            message_template="Message",
            template_id=template.id,
            recipient_config=schemas.RecipientConfig(
                resolver_type="all_admins",
                params={}
            )
        )
        await repo.create_with_actions(rule_data)
        await db.commit()
        
        # Assert
        await db.refresh(template)
        assert template.usage_count == initial_usage + 1

    # =========================================================================
    # DELETE ACTIONS
    # =========================================================================

    async def test_delete_actions(self, db: AsyncSession):
        """Should delete all actions for a rule."""
        # Arrange
        rule = models.NotificationRule(
            event="DELETE_ACTIONS_EVENT",
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True
        )
        db.add(rule)
        await db.flush()
        
        action1 = models.NotificationAction(rule_id=rule.id, step=1, channel="browser")
        action2 = models.NotificationAction(rule_id=rule.id, step=2, channel="email")
        db.add_all([action1, action2])
        await db.commit()
        
        # Act
        repo = NotificationRuleRepository(db)
        await repo.delete_actions(rule.id)
        await db.commit()
        
        # Assert
        refreshed_rule = await repo.get_by_id(rule.id)
        assert len(refreshed_rule.actions) == 0

    # =========================================================================
    # ADD ACTIONS
    # =========================================================================

    async def test_add_actions(self, db: AsyncSession):
        """Should add new actions to existing rule."""
        # Arrange
        rule = models.NotificationRule(
            event="ADD_ACTIONS_EVENT",
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True
        )
        db.add(rule)
        await db.commit()
        
        # Act
        repo = NotificationRuleRepository(db)
        new_actions = [
            schemas.NotificationActionCreate(step=1, channel="sms"),
            schemas.NotificationActionCreate(step=2, channel="zalo", delay_minutes=10)
        ]
        await repo.add_actions(rule.id, new_actions)
        await db.commit()
        
        # Assert
        refreshed_rule = await repo.get_by_id(rule.id)
        assert len(refreshed_rule.actions) == 2
        channels = [a.channel for a in refreshed_rule.actions]
        assert "sms" in channels
        assert "zalo" in channels

    # =========================================================================
    # DELETE RULE
    # =========================================================================

    async def test_delete_rule_decrements_template_usage(self, db: AsyncSession):
        """Should decrement template usage_count when deleting rule with template."""
        # Arrange - Create template and rule
        template = models.NotificationTemplate(
            template_code="TPL_DELETE_TEST",
            name="Delete Test Template",
            title_template="Title",
            message_template="Message",
            usage_count=5
        )
        db.add(template)
        await db.flush()
        
        rule = models.NotificationRule(
            event="DELETE_RULE_EVENT",
            title_template="Title",
            message_template="Message",
            template_id=template.id,
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True
        )
        db.add(rule)
        await db.commit()
        
        initial_usage = template.usage_count
        
        # Act
        repo = NotificationRuleRepository(db)
        await repo.delete_rule(rule)
        await db.commit()
        
        # Assert
        await db.refresh(template)
        assert template.usage_count == initial_usage - 1

    # =========================================================================
    # GET FILTERED (Abstract method)
    # =========================================================================

    async def test_get_filtered(self, db: AsyncSession):
        """Should use list_rules under the hood."""
        # Arrange
        rule = models.NotificationRule(
            event="FILTERED_EVENT",
            title_template="Title",
            message_template="Message",
            recipient_config={"resolver_type": "all_admins", "params": {}},
            enabled=True
        )
        db.add(rule)
        await db.commit()
        
        # Act
        repo = NotificationRuleRepository(db)
        rules, total = await repo.get_filtered(skip=0, limit=10, event="FILTERED_EVENT")
        
        # Assert
        assert total >= 1
        assert any(r.event == "FILTERED_EVENT" for r in rules)
