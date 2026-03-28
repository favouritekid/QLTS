# tests/unit/test_delivery_branch_schema.py
"""
Phase 3a: Unit tests for delivery branch schema — ActionConfig fields,
CRUD validation, repository persistence compatibility.
"""
import pytest
from pydantic import ValidationError

from app.services.notification_rule_loader import ActionConfig
from app.schemas.notification import (
    NotificationActionBase,
    NotificationActionCreate,
    NotificationAction as NotificationActionResponse,
    RecipientConfig,
)


class TestActionConfigNewFields:
    """ActionConfig dataclass accepts and round-trips Phase 3 fields."""

    def test_default_values_all_none(self):
        ac = ActionConfig(step=1, channel="browser")
        assert ac.recipient_config is None
        assert ac.content_mode is None
        assert ac.content_override is None
        assert ac.branch_key is None

    def test_with_all_fields(self):
        rc = {"resolver_type": "lead_owner", "params": {}}
        co = {"title_template": "Override", "message_template": "Override msg"}
        ac = ActionConfig(
            step=1,
            channel="email",
            recipient_config=rc,
            content_mode="inline_override",
            content_override=co,
            branch_key="officer_email",
        )
        assert ac.recipient_config == rc
        assert ac.content_mode == "inline_override"
        assert ac.content_override == co
        assert ac.branch_key == "officer_email"

    def test_legacy_action_without_new_fields(self):
        """Legacy actions (pre-Phase 3) should work with defaults."""
        ac = ActionConfig(
            step=1, channel="browser", delay_minutes=0,
            template_code=None, config=None,
        )
        assert ac.recipient_config is None
        assert ac.content_mode is None


class TestPydanticSchemaNewFields:
    """Pydantic schemas accept Phase 3 fields."""

    def test_action_base_with_recipient_config(self):
        data = {
            "step": 1,
            "channel": "browser",
            "recipient_config": {"resolver_type": "lead_owner", "params": {}},
            "content_mode": "inherit_default",
            "branch_key": "test_branch",
        }
        action = NotificationActionBase(**data)
        assert action.recipient_config is not None
        assert action.recipient_config.resolver_type == "lead_owner"
        assert action.content_mode == "inherit_default"
        assert action.branch_key == "test_branch"

    def test_action_base_defaults_to_none(self):
        data = {"step": 1, "channel": "browser"}
        action = NotificationActionBase(**data)
        assert action.recipient_config is None
        assert action.content_mode is None
        assert action.content_override is None
        assert action.branch_key is None

    def test_recipient_config_validates_structure(self):
        """RecipientConfig must have resolver_type."""
        data = {
            "step": 1,
            "channel": "browser",
            "recipient_config": {"params": {}},  # missing resolver_type
        }
        with pytest.raises(ValidationError):
            NotificationActionBase(**data)

    def test_action_create_with_branch_fields(self):
        data = {
            "step": 1,
            "channel": "email",
            "content_mode": "template_override",
            "template_code": "TPL_TEST",
            "branch_key": "officer_email",
        }
        action = NotificationActionCreate(**data)
        assert action.content_mode == "template_override"

    def test_response_validates_content_mode(self):
        """Invalid content_mode should fail validation."""
        data = {
            "id": 1,
            "rule_id": 1,
            "step": 1,
            "channel": "browser",
            "template_code": None,
            "delay_minutes": 0,
            "config": None,
            "recipient_config": None,
            "content_mode": "invalid_mode",
            "content_override": None,
            "branch_key": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with pytest.raises(ValidationError, match="Invalid content_mode"):
            NotificationActionResponse(**data)

    def test_response_allows_valid_content_modes(self):
        base = {
            "id": 1, "rule_id": 1, "step": 1, "channel": "browser",
            "template_code": None, "delay_minutes": 0, "config": None,
            "recipient_config": None, "content_override": None,
            "branch_key": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        for mode in ["inherit_default", "template_override", "inline_override", "channel_native", None]:
            resp = NotificationActionResponse(**{**base, "content_mode": mode})
            assert resp.content_mode == mode

    def test_recipient_config_model_dump(self):
        """RecipientConfig .model_dump() produces dict for JSONB storage."""
        rc = RecipientConfig(resolver_type="lead_owner", params={"user_field": "officer_id"})
        dumped = rc.model_dump()
        assert dumped == {"resolver_type": "lead_owner", "params": {"user_field": "officer_id"}}


class TestCRUDValidationRules:
    """CRUD validation for content_mode and branch_key (via _validate_actions)."""

    def test_duplicate_channel_still_rejected(self):
        """Phase 3a: duplicate channel check still active."""
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            NotificationActionCreate(step=1, channel="browser"),
            NotificationActionCreate(step=2, channel="browser"),  # duplicate
        ]
        with pytest.raises(Exception, match="[Dd]uplicate channel"):
            _validate_actions(actions)

    def test_valid_content_modes_accepted(self):
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            NotificationActionCreate(
                step=1, channel="browser",
                content_mode="inherit_default",
                branch_key="browser_default",
            ),
        ]
        # Should not raise
        _validate_actions(actions)

    def test_template_override_requires_template_code(self):
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            NotificationActionCreate(
                step=1, channel="browser",
                content_mode="template_override",
                # missing template_code
            ),
        ]
        with pytest.raises(Exception, match="template_code"):
            _validate_actions(actions)

    def test_inline_override_requires_content_override(self):
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            NotificationActionCreate(
                step=1, channel="email",
                content_mode="inline_override",
                # missing content_override
            ),
        ]
        with pytest.raises(Exception, match="content_override"):
            _validate_actions(actions)

    def test_channel_native_only_for_zalo_sms(self):
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            NotificationActionCreate(
                step=1, channel="browser",
                content_mode="channel_native",
            ),
        ]
        with pytest.raises(Exception, match="channel_native"):
            _validate_actions(actions)

    def test_channel_native_valid_for_zalo(self):
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            NotificationActionCreate(
                step=1, channel="zalo",
                content_mode="channel_native",
                config={"zalo_template_id": "ZNS_TEST"},
            ),
        ]
        # Should not raise
        _validate_actions(actions)

    def test_duplicate_branch_key_rejected(self):
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            NotificationActionCreate(step=1, channel="browser", branch_key="same_key"),
            NotificationActionCreate(step=2, channel="email", branch_key="same_key"),
        ]
        with pytest.raises(Exception, match="[Dd]uplicate branch_key"):
            _validate_actions(actions)

    def test_null_branch_keys_allowed(self):
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            NotificationActionCreate(step=1, channel="browser"),
            NotificationActionCreate(step=2, channel="email"),
        ]
        # Both have null branch_key — should not raise
        _validate_actions(actions)
