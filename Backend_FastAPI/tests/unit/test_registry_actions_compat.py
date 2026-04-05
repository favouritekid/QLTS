# tests/unit/test_registry_actions_compat.py
"""
Registry actions compatibility tests — Step 0 hotfix verification.

Verifies that NotificationConfig.actions property works correctly so
dispatch() can access config.actions for both DatabaseRuleConfig and
registry-based NotificationConfig.
"""
import pytest

from app.services.notification_registry import NOTIFICATION_REGISTRY, NotificationConfig
from app.core.event_groups import NotificationEventGroup, NotificationChannel
from app.services.notification_rule_loader import ActionConfig


class TestNotificationConfigActions:
    """NotificationConfig must expose .actions for dispatch() compatibility."""

    def test_actions_property_returns_list(self):
        """actions must return a List[ActionConfig]."""
        config = NotificationConfig(
            group=NotificationEventGroup.LEAD,
            resolver=None,
            template=("Title", "Message"),
            channels=(NotificationChannel.BROWSER,),
        )
        actions = config.actions
        assert isinstance(actions, list)
        assert len(actions) == 1
        assert isinstance(actions[0], ActionConfig)

    def test_actions_match_channels(self):
        """Each channel should produce one ActionConfig."""
        config = NotificationConfig(
            group=NotificationEventGroup.LEAD,
            resolver=None,
            template=("Title", "Message"),
            channels=(NotificationChannel.BROWSER, NotificationChannel.EMAIL),
        )
        actions = config.actions
        assert len(actions) == 2
        channels = {a.channel for a in actions}
        assert channels == {"browser", "email"}

    def test_actions_step_sequence(self):
        """ActionConfig steps should be sequential starting from 1."""
        config = NotificationConfig(
            group=NotificationEventGroup.LEAD,
            resolver=None,
            template=("Title", "Message"),
            channels=(NotificationChannel.BROWSER, NotificationChannel.EMAIL),
        )
        steps = [a.step for a in config.actions]
        assert steps == [1, 2]

    def test_actions_default_delay(self):
        """Synthesized actions should have delay_minutes=0."""
        config = NotificationConfig(
            group=NotificationEventGroup.LEAD,
            resolver=None,
            template=("Title", "Message"),
            channels=(NotificationChannel.BROWSER,),
        )
        assert config.actions[0].delay_minutes == 0


class TestAllRegistryEntriesHaveActions:
    """Legacy: Every entry in NOTIFICATION_REGISTRY must have accessible .actions.

    NOTE: Dispatcher no longer reads from NOTIFICATION_REGISTRY (PR1).
    These tests guard the deprecated module until full removal.
    See TestCatalogParity in test_notification_parity.py for runtime source of truth.
    """

    def test_every_registry_entry_actions_accessible(self):
        """Verifies dispatch() will not AttributeError on config.actions."""
        errors = []
        for event, config in NOTIFICATION_REGISTRY.items():
            try:
                actions = config.actions
                if not isinstance(actions, list):
                    errors.append(f"{event.value}: .actions is not a list")
                if len(actions) == 0:
                    errors.append(f"{event.value}: .actions is empty")
            except Exception as e:
                errors.append(f"{event.value}: {e}")

        assert not errors, f"Registry entries with broken .actions:\n" + "\n".join(errors)

    def test_every_registry_entry_actions_have_channel(self):
        """Each ActionConfig must have a .channel attribute."""
        for event, config in NOTIFICATION_REGISTRY.items():
            for action in config.actions:
                assert hasattr(action, "channel"), (
                    f"{event.value}: ActionConfig missing .channel"
                )
                assert isinstance(action.channel, str), (
                    f"{event.value}: ActionConfig.channel is not str"
                )
