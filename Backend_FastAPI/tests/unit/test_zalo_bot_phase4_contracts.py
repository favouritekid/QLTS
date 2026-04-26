"""Contract tests for v5 Step 10/11/15/16 wiring.

These are pure-Python unit tests — no DB, no Redis. They lock the
following invariants so they cannot drift silently:

- ``NotificationChannel.ZALO_BOT`` exists with value ``"zalo_bot"``.
- ``DEFAULT_GROUP_CHANNELS`` ships ``ZALO_BOT=False`` for every group.
- ``CANONICAL_CHANNELS`` (registry) and breaker ``_CANONICAL_CHANNELS``
  both include ``"zalo_bot"``.
- The Pydantic ``NotificationPreferenceUpdate`` schema deliberately
  does **not** expose ``zalo_bot_enabled`` so generic clients cannot
  flip the flag without going through the link service.
- Rule CRUD validation rejects ``channel="zalo_bot"`` combined with
  ``external_resolver`` (Step 16).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.event_groups import (
    DEFAULT_GROUP_CHANNELS,
    NotificationChannel,
)
from app.schemas.notification_preference import (
    NotificationPreferenceBase,
    NotificationPreferenceUpdate,
)
from app.services.notification_channels import CANONICAL_CHANNELS
from app.services.notification_circuit_breaker import _CANONICAL_CHANNELS
from app.services.notification_rule_crud_service import _validate_actions
from app.utils.exceptions import BadRequest


@pytest.mark.unit
class TestEnumAndDefaults:
    def test_enum_has_zalo_bot(self):
        assert NotificationChannel.ZALO_BOT.value == "zalo_bot"

    def test_every_group_defaults_zalo_bot_false(self):
        # ORGANIZATION is intentionally excluded from DEFAULT_GROUP_CHANNELS;
        # everything else must ship ZALO_BOT=False so a link record alone
        # never starts firing notifications for arbitrary groups.
        assert len(DEFAULT_GROUP_CHANNELS) > 0
        for group, channels in DEFAULT_GROUP_CHANNELS.items():
            assert NotificationChannel.ZALO_BOT in channels, (
                f"{group} missing ZALO_BOT default — fail-closed contract broken"
            )
            assert channels[NotificationChannel.ZALO_BOT] is False, (
                f"{group} ships ZALO_BOT=True — must opt in per group"
            )


@pytest.mark.unit
class TestCanonicalChannelRegistration:
    def test_registry_canonical_includes_zalo_bot(self):
        assert "zalo_bot" in CANONICAL_CHANNELS

    def test_breaker_canonical_includes_zalo_bot(self):
        assert "zalo_bot" in _CANONICAL_CHANNELS


@pytest.mark.unit
class TestPreferenceSchemaSurface:
    def test_base_exposes_zalo_bot_enabled(self):
        # Reading user prefs must reflect the flag — UI surfaces the
        # link state via this field even when the user is unlinked
        # (then ``False``).
        fields = NotificationPreferenceBase.model_fields
        assert "zalo_bot_enabled" in fields
        assert fields["zalo_bot_enabled"].annotation is bool
        assert fields["zalo_bot_enabled"].default is False

    def test_update_schema_does_not_expose_zalo_bot_enabled(self):
        # Writes must go through zalo_bot_link_service so we can keep
        # the link table in sync. If a client could PATCH the preference
        # directly, dispatch would fire to a chat_id we don't know.
        assert "zalo_bot_enabled" not in NotificationPreferenceUpdate.model_fields, (
            "NotificationPreferenceUpdate must NOT accept zalo_bot_enabled — "
            "only zalo_bot_link_service may flip this column"
        )


def _action(*, step: int, channel: str, config=None):
    return SimpleNamespace(
        step=step,
        channel=channel,
        delay_minutes=0,
        config=config,
        content_mode=None,
        template_code=None,
        content_override=None,
        branch_key=None,
    )


@pytest.mark.unit
class TestRuleValidationStep16:
    def test_zalo_bot_with_external_resolver_rejected(self):
        actions = [
            _action(
                step=1,
                channel="zalo_bot",
                config={"external_resolver": "lead_contact"},
            )
        ]
        with pytest.raises(BadRequest) as exc_info:
            _validate_actions(actions)
        msg = str(exc_info.value)
        assert "zalo_bot" in msg
        assert "internal-only" in msg.lower()

    def test_zalo_bot_internal_action_passes(self):
        # No external_resolver in config → internal recipient action,
        # which is exactly the supported case.
        actions = [_action(step=1, channel="zalo_bot", config=None)]
        _validate_actions(actions)  # must not raise

        actions = [_action(step=1, channel="zalo_bot", config={})]
        _validate_actions(actions)

        actions = [_action(step=1, channel="zalo_bot", config={"foo": "bar"})]
        _validate_actions(actions)
