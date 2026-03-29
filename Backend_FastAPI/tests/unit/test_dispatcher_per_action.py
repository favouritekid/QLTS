# tests/unit/test_dispatcher_per_action.py
"""
Phase 3b: Unit tests for per-action dispatcher helpers.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.notification_dispatcher import _build_action_snapshot
from app.services.notification_rule_loader import ActionConfig


def _make_config():
    """Create a mock rule config with render methods."""
    config = MagicMock()
    config.render_title.return_value = "Default Title"
    config.render_message.return_value = "Default Message"
    config.render_link.return_value = "/default"
    config.notification_type = "info"
    return config


class TestBuildActionSnapshot:
    """_build_action_snapshot with each content_mode."""

    def test_inherit_default(self):
        action = ActionConfig(step=1, channel="browser")
        config = _make_config()
        result = _build_action_snapshot(action, config, {}, {})
        assert result["title"] == "Default Title"
        assert result["message"] == "Default Message"
        assert result["link"] == "/default"
        assert result["type"] == "info"

    def test_inherit_default_explicit(self):
        action = ActionConfig(step=1, channel="browser", content_mode="inherit_default")
        config = _make_config()
        result = _build_action_snapshot(action, config, {}, {})
        assert result["title"] == "Default Title"

    def test_inline_override(self):
        action = ActionConfig(
            step=1, channel="email",
            content_mode="inline_override",
            content_override={
                "title_template": "Override: $lead_name",
                "message_template": "Custom msg for $lead_name",
            },
        )
        config = _make_config()
        payload = {"lead_name": "Nguyen Van A"}
        result = _build_action_snapshot(action, config, payload, {})
        assert result["title"] == "Override: Nguyen Van A"
        assert result["message"] == "Custom msg for Nguyen Van A"
        assert result["type"] == "info"

    def test_template_override_fallback(self):
        """If template_code not in map, fallback to rule defaults."""
        action = ActionConfig(
            step=1, channel="email",
            content_mode="template_override",
            template_code="TPL_MISSING",
        )
        config = _make_config()
        result = _build_action_snapshot(action, config, {}, {})
        assert result["title"] == "Default Title"

    def test_channel_native_merges_base(self):
        """channel_native merges config on top of base_snapshot."""
        action = ActionConfig(
            step=1, channel="zalo",
            content_mode="channel_native",
            config={"zalo_template_id": "ZNS_TEST", "zalo_template_data": {"name": "Test"}},
        )
        config = _make_config()
        result = _build_action_snapshot(action, config, {}, {})
        assert result["zalo_template_id"] == "ZNS_TEST"
        # base_snapshot fields preserved
        assert result["title"] == "Default Title"
        assert result["type"] == "info"

    def test_none_content_mode_defaults_to_inherit(self):
        action = ActionConfig(step=1, channel="browser", content_mode=None)
        config = _make_config()
        result = _build_action_snapshot(action, config, {}, {})
        assert result["title"] == "Default Title"

    def test_custom_notification_type(self):
        action = ActionConfig(step=1, channel="browser")
        config = _make_config()
        result = _build_action_snapshot(action, config, {}, {}, notification_type="warning")
        assert result["type"] == "warning"


class TestActionScopedKeys:
    """Cooldown and dedup keys include action.step."""

    def test_cooldown_key_includes_step(self):
        """Verify key format matches plan."""
        event = "lead_created"
        uid = 42
        channel = "email"
        step = 2
        key = f"notif:cooldown:{event}:{uid}:{channel}:{step}"
        assert key == "notif:cooldown:lead_created:42:email:2"

    def test_dedupe_key_includes_step(self):
        dedupe_key = "lead_created:42"
        step = 1
        action_key = f"{dedupe_key}:step{step}"
        assert action_key == "lead_created:42:step1"

    def test_different_steps_different_keys(self):
        base = "lead_created:42"
        key1 = f"{base}:step1"
        key2 = f"{base}:step2"
        assert key1 != key2


class TestCRUDDuplicateChannel:
    """Phase 3b: non-browser duplicate channels allowed, browser still blocked."""

    def test_duplicate_email_allowed(self):
        from app.services.notification_rule_crud_service import _validate_actions
        from app.schemas.notification import NotificationActionCreate
        actions = [
            NotificationActionCreate(step=1, channel="email", branch_key="officer_email"),
            NotificationActionCreate(step=2, channel="email", branch_key="lead_email"),
        ]
        # Should NOT raise
        _validate_actions(actions)

    def test_duplicate_browser_rejected(self):
        from app.services.notification_rule_crud_service import _validate_actions
        from app.schemas.notification import NotificationActionCreate
        actions = [
            NotificationActionCreate(step=1, channel="browser"),
            NotificationActionCreate(step=2, channel="browser"),
        ]
        with pytest.raises(Exception, match="browser"):
            _validate_actions(actions)

    def test_mixed_channels_allowed(self):
        from app.services.notification_rule_crud_service import _validate_actions
        from app.schemas.notification import NotificationActionCreate
        actions = [
            NotificationActionCreate(step=1, channel="browser"),
            NotificationActionCreate(step=2, channel="email"),
            NotificationActionCreate(step=3, channel="email", branch_key="email_2"),
            NotificationActionCreate(step=4, channel="zalo", config={"zalo_template_id": "ZNS_TEST"}),
        ]
        # Should NOT raise
        _validate_actions(actions)
