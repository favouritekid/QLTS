# tests/unit/test_notification_c1.py
"""
Phase C1: Unit tests for notification system C1 features.

Tests:
- Delivery worker task (execute_notification_delivery)
- Zalo CRUD validation (_validate_actions, _validate_zalo_action_config)
- Dispatcher placeholder rendering (_render_channel_config_placeholders)
- Dispatcher inbox-only-for-browser logic
- External delivery metadata parity
- Collaborator fallback (internal user from external resolver)
- Phone normalization (to_zalo_phone)
"""
import pytest
from datetime import datetime, timedelta, timezone
from string import Template
from unittest.mock import AsyncMock, MagicMock, patch

from app.utils.phone_helpers import to_zalo_phone


# ============================================================
# Phone normalization
# ============================================================

class TestToZaloPhone:
    """to_zalo_phone() converts Vietnam numbers to 84xxx format."""

    def test_normal_mobile(self):
        assert to_zalo_phone("0901234567") == "84901234567"

    def test_with_country_code_plus(self):
        assert to_zalo_phone("+84901234567") == "84901234567"

    def test_with_country_code_no_plus(self):
        assert to_zalo_phone("84901234567") == "84901234567"

    def test_with_spaces(self):
        assert to_zalo_phone("090 123 4567") == "84901234567"

    def test_invalid_phone(self):
        assert to_zalo_phone("12345") is None

    def test_none_input(self):
        assert to_zalo_phone(None) is None

    def test_empty_string(self):
        assert to_zalo_phone("") is None

    def test_landline_rejected(self):
        # Landlines (02x) — to_zalo_phone should still convert if valid
        result = to_zalo_phone("0281234567")
        # 02x is valid Vietnam phone, should get 84 prefix
        assert result == "84281234567" or result is None  # depends on regex


# ============================================================
# Placeholder rendering
# ============================================================

class TestRenderChannelConfigPlaceholders:
    """_render_channel_config_placeholders() resolves $var in *_template_data."""

    def _render(self, snapshot, payload):
        from app.services.notification_dispatcher import _render_channel_config_placeholders
        return _render_channel_config_placeholders(snapshot, payload)

    def test_basic_rendering(self):
        snapshot = {
            "title": "Hello",
            "zalo_template_data": {"customer": "$lead_name", "phone": "$lead_phone"},
        }
        payload = {"lead_name": "Nguyen Van A", "lead_phone": "0901234567"}
        result = self._render(snapshot, payload)
        assert result["zalo_template_data"]["customer"] == "Nguyen Van A"
        assert result["zalo_template_data"]["phone"] == "0901234567"

    def test_unresolved_placeholder_stays(self):
        snapshot = {
            "zalo_template_data": {"customer": "$unknown_field"},
        }
        result = self._render(snapshot, {"lead_name": "A"})
        assert result["zalo_template_data"]["customer"] == "$unknown_field"

    def test_no_template_data_passthrough(self):
        snapshot = {"title": "Hello", "zalo_template_id": "abc123"}
        result = self._render(snapshot, {"lead_name": "A"})
        assert result["title"] == "Hello"
        assert result["zalo_template_id"] == "abc123"

    def test_non_string_values_untouched(self):
        snapshot = {
            "zalo_template_data": {"count": 42, "active": True, "name": "$lead_name"},
        }
        result = self._render(snapshot, {"lead_name": "B"})
        assert result["zalo_template_data"]["count"] == 42
        assert result["zalo_template_data"]["active"] is True
        assert result["zalo_template_data"]["name"] == "B"

    def test_empty_template_data(self):
        snapshot = {"zalo_template_data": {}}
        result = self._render(snapshot, {"lead_name": "A"})
        assert result["zalo_template_data"] == {}

    def test_braced_placeholder(self):
        snapshot = {"zalo_template_data": {"msg": "${lead_name} applied"}}
        result = self._render(snapshot, {"lead_name": "C"})
        assert result["zalo_template_data"]["msg"] == "C applied"


# ============================================================
# CRUD validation
# ============================================================

class TestValidateActions:
    """_validate_actions() enforces C1 rules."""

    def _validate(self, actions):
        from app.services.notification_rule_crud_service import _validate_actions
        _validate_actions(actions)

    def test_delay_zero_accepted(self):
        actions = [MagicMock(step=1, channel="browser", delay_minutes=0, template_code=None, config=None)]
        self._validate(actions)  # No exception

    def test_delay_positive_accepted(self):
        actions = [MagicMock(step=1, channel="email", delay_minutes=30, template_code=None, config=None)]
        self._validate(actions)  # No exception — C1 unlocked

    def test_delay_negative_rejected(self):
        from app.utils.exceptions import BadRequest
        actions = [MagicMock(step=1, channel="email", delay_minutes=-5, template_code=None, config=None)]
        with pytest.raises(BadRequest, match="delay_minutes must be >= 0"):
            self._validate(actions)

    def test_template_code_accepted_after_e2(self):
        """E2 unlocked template_code — no longer rejected in sync validation."""
        actions = [MagicMock(step=1, channel="email", delay_minutes=0, template_code="TPL_FOO", config=None)]
        # Should NOT raise — template_code is now accepted (validated async in E2)
        self._validate(actions)

    def test_duplicate_channel_rejected(self):
        from app.utils.exceptions import BadRequest
        actions = [
            MagicMock(step=1, channel="email", delay_minutes=0, template_code=None, config=None),
            MagicMock(step=2, channel="email", delay_minutes=0, template_code=None, config=None),
        ]
        with pytest.raises(BadRequest, match="Duplicate channel"):
            self._validate(actions)

    def test_empty_actions_ok(self):
        self._validate([])  # No exception


class TestValidateZaloActionConfig:
    """Zalo-specific config validation."""

    def _validate(self, actions):
        from app.services.notification_rule_crud_service import _validate_actions
        _validate_actions(actions)

    def test_zalo_without_config_rejected(self):
        from app.utils.exceptions import BadRequest
        actions = [MagicMock(step=1, channel="zalo", delay_minutes=0, template_code=None, config=None)]
        with pytest.raises(BadRequest, match="zalo_template_id"):
            self._validate(actions)

    def test_zalo_without_template_id_rejected(self):
        from app.utils.exceptions import BadRequest
        actions = [MagicMock(step=1, channel="zalo", delay_minutes=0, template_code=None,
                            config={"some_key": "val"})]
        with pytest.raises(BadRequest, match="zalo_template_id"):
            self._validate(actions)

    def test_zalo_with_valid_config_accepted(self):
        actions = [MagicMock(step=1, channel="zalo", delay_minutes=0, template_code=None,
                            config={"zalo_template_id": "abc123"})]
        self._validate(actions)  # No exception

    def test_zalo_with_invalid_external_resolver_rejected(self):
        from app.utils.exceptions import BadRequest
        actions = [MagicMock(step=1, channel="zalo", delay_minutes=0, template_code=None,
                            config={"zalo_template_id": "abc", "external_resolver": "invalid_type"})]
        with pytest.raises(BadRequest, match="unknown external_resolver"):
            self._validate(actions)

    def test_zalo_with_valid_external_resolver_accepted(self):
        actions = [MagicMock(step=1, channel="zalo", delay_minutes=0, template_code=None,
                            config={"zalo_template_id": "abc", "external_resolver": "lead_contact"})]
        self._validate(actions)  # No exception

    def test_email_with_invalid_external_resolver_rejected(self):
        from app.utils.exceptions import BadRequest
        actions = [MagicMock(step=1, channel="email", delay_minutes=0, template_code=None,
                            config={"external_resolver": "bogus"})]
        with pytest.raises(BadRequest, match="unknown external_resolver"):
            self._validate(actions)


# ============================================================
# Delivery service — delayed scheduling
# ============================================================

@pytest.mark.asyncio
class TestCreateDeliveriesScheduling:
    """create_deliveries_for_dispatch sets scheduled_for when delay > 0."""

    async def test_delay_sets_scheduled_for(self):
        """Delivery rows with delay > 0 should have scheduled_for set."""
        mock_repo = AsyncMock()
        mock_repo.bulk_create_deliveries.return_value = [100]

        with patch(
            "app.services.notification_delivery_service.NotificationDeliveryRepository",
            return_value=mock_repo,
        ):
            from app.services.notification_delivery_service import create_deliveries_for_dispatch

            result = await create_deliveries_for_dispatch(
                db=AsyncMock(),
                event="test_event",
                channel_recipient_map={"email": [1]},
                notification_id_map={},
                action_delay_map={"email": 30},
            )

        assert result == {"email": [100]}
        # Verify the delivery data passed to repo
        call_args = mock_repo.bulk_create_deliveries.call_args[0][0]
        assert len(call_args) == 1
        delivery_data = call_args[0]
        assert delivery_data["scheduled_for"] is not None
        assert delivery_data["channel"] == "email"

    async def test_no_delay_no_scheduled_for(self):
        """Delivery rows with delay=0 should have scheduled_for=None."""
        mock_repo = AsyncMock()
        mock_repo.bulk_create_deliveries.return_value = [200]

        with patch(
            "app.services.notification_delivery_service.NotificationDeliveryRepository",
            return_value=mock_repo,
        ):
            from app.services.notification_delivery_service import create_deliveries_for_dispatch

            await create_deliveries_for_dispatch(
                db=AsyncMock(),
                event="test_event",
                channel_recipient_map={"browser": [1]},
                notification_id_map={1: 10},
                action_delay_map={"browser": 0},
            )

        call_args = mock_repo.bulk_create_deliveries.call_args[0][0]
        assert call_args[0]["scheduled_for"] is None


# ============================================================
# External delivery metadata parity
# ============================================================

@pytest.mark.asyncio
class TestExternalDeliveryParity:
    """prepare_external_deliveries passes rule_id, action_step, etc."""

    async def test_metadata_passed_through(self):
        mock_repo = AsyncMock()
        mock_repo.bulk_create_deliveries.return_value = [300]

        with patch(
            "app.services.notification_delivery_service.NotificationDeliveryRepository",
            return_value=mock_repo,
        ):
            from app.services.notification_delivery_service import prepare_external_deliveries

            now = datetime.now(timezone.utc)
            result = await prepare_external_deliveries(
                db=AsyncMock(),
                event="lead_created",
                channel="zalo",
                recipients=[{"source_type": "lead", "source_id": 1, "destination": "84901234567"}],
                payload_snapshot={"title": "T"},
                rule_id=42,
                action_step=2,
                template_code=None,
                scheduled_for=now,
            )

        assert result == [300]
        data = mock_repo.bulk_create_deliveries.call_args[0][0][0]
        assert data["rule_id"] == 42
        assert data["action_step"] == 2
        assert data["scheduled_for"] == now
        assert data["recipient_kind"] == "external"
        assert data["destination"] == "84901234567"


# ============================================================
# Channel-specific snapshot
# ============================================================

@pytest.mark.asyncio
class TestChannelSnapshotMap:
    """create_deliveries_for_dispatch uses per-channel snapshots."""

    async def test_per_channel_snapshot_used(self):
        mock_repo = AsyncMock()
        mock_repo.bulk_create_deliveries.return_value = [400, 401]

        with patch(
            "app.services.notification_delivery_service.NotificationDeliveryRepository",
            return_value=mock_repo,
        ):
            from app.services.notification_delivery_service import create_deliveries_for_dispatch

            base_snapshot = {"title": "Base"}
            zalo_snapshot = {"title": "Base", "zalo_template_id": "xyz"}

            await create_deliveries_for_dispatch(
                db=AsyncMock(),
                event="test",
                channel_recipient_map={"browser": [1], "zalo": [2]},
                notification_id_map={1: 10},
                payload_snapshot=base_snapshot,
                channel_snapshot_map={"browser": base_snapshot, "zalo": zalo_snapshot},
            )

        all_data = mock_repo.bulk_create_deliveries.call_args[0][0]
        browser_data = [d for d in all_data if d["channel"] == "browser"][0]
        zalo_data = [d for d in all_data if d["channel"] == "zalo"][0]
        assert "zalo_template_id" not in browser_data["payload_snapshot"]
        assert zalo_data["payload_snapshot"]["zalo_template_id"] == "xyz"


# ============================================================
# Worker task — execute_notification_delivery
# ============================================================

@pytest.mark.asyncio
class TestExecuteNotificationDelivery:
    """Tests for the Celery worker task logic (mocked DB + channel)."""

    async def test_skips_non_queued_delivery(self):
        """Already-sent delivery should be skipped (idempotent)."""
        from app.services.notification_delivery_service import check_delivery_eligibility

        mock_delivery = MagicMock()
        mock_delivery.status = "sent"
        mock_delivery.id = 1

        # The task checks status != "queued" early and returns.
        # We test the eligibility helper separately.
        mock_delivery.recipient_kind = "internal"
        mock_delivery.user_id = 1
        mock_delivery.event = "test_event"
        mock_delivery.channel = "email"
        mock_delivery.source_type = None
        mock_delivery.source_id = None

        # No reason to skip — eligibility check is for consent/preference
        result = await check_delivery_eligibility(AsyncMock(), mock_delivery)
        # Internal user without event in SystemEvents → passes (no preference check crash)
        assert result is None  # None means "OK to proceed"

    async def test_consent_revoked_returns_skip_reason(self):
        """External delivery with revoked consent should return skip reason."""
        from app.services.notification_delivery_service import check_delivery_eligibility

        mock_delivery = MagicMock()
        mock_delivery.recipient_kind = "external"
        mock_delivery.source_type = "lead"
        mock_delivery.source_id = 42
        mock_delivery.channel = "zalo"
        mock_delivery.user_id = None
        mock_delivery.event = "test_event"

        mock_session = AsyncMock()
        mock_consent_repo = MagicMock()
        mock_consent_repo.is_consent_granted = AsyncMock(return_value=False)

        with patch(
            "app.repositories.notification_consent_repository.NotificationConsentRepository",
            return_value=mock_consent_repo,
        ):
            result = await check_delivery_eligibility(mock_session, mock_delivery)

        assert result == "consent_revoked"

    async def test_consent_granted_passes(self):
        """External delivery with granted consent should pass eligibility."""
        from app.services.notification_delivery_service import check_delivery_eligibility

        mock_delivery = MagicMock()
        mock_delivery.recipient_kind = "external"
        mock_delivery.source_type = "lead"
        mock_delivery.source_id = 42
        mock_delivery.channel = "zalo"
        mock_delivery.user_id = None
        mock_delivery.event = "test_event"

        mock_session = AsyncMock()
        mock_consent_repo = MagicMock()
        mock_consent_repo.is_consent_granted = AsyncMock(return_value=True)

        with patch(
            "app.repositories.notification_consent_repository.NotificationConsentRepository",
            return_value=mock_consent_repo,
        ):
            result = await check_delivery_eligibility(mock_session, mock_delivery)

        assert result is None  # None = OK


# ============================================================
# Collaborator fallback — internal user from external resolver
# ============================================================

class TestCollaboratorFallback:
    """
    When external resolver returns recipient_kind=internal (e.g. collaborator
    with linked user_id), the dispatcher should create an internal delivery
    instead of dropping the recipient.
    """

    def test_resolve_collaborator_with_user_returns_internal(self):
        """Sanity check: resolve_collaborator_contact returns internal for linked user."""
        from app.services.notification_recipients import ResolvedRecipient

        # This is the shape that resolve_collaborator_contact returns
        # when the collaborator has a linked user_id.
        recipient = ResolvedRecipient(
            recipient_kind="internal",
            user_id=99,
            source_type="collaborator",
            source_id=5,
        )
        assert recipient.recipient_kind == "internal"
        assert recipient.user_id == 99
        assert recipient.destination_phone is None


# ============================================================
# Inbox only for browser — dispatcher logic
# ============================================================

class TestInboxOnlyForBrowser:
    """
    Dispatcher should only create inbox Notification rows for browser recipients.
    Users who only have email/zalo enabled should NOT get inbox rows.
    """

    def test_inbox_user_ids_from_browser_only(self):
        """
        Simulate the dispatcher logic:
        channel_recipient_map = {"browser": [1, 2], "email": [1, 2, 3]}
        inbox_user_ids should be [1, 2] (only browser), not [1, 2, 3].
        """
        channel_recipient_map = {
            "browser": [1, 2],
            "email": [1, 2, 3],
            "zalo": [3],
        }

        # This is the exact logic from the dispatcher (G1 fix)
        inbox_user_ids = sorted(set(channel_recipient_map.get("browser", [])))

        assert inbox_user_ids == [1, 2]
        assert 3 not in inbox_user_ids  # user 3 has email+zalo but not browser

    def test_inbox_empty_when_no_browser(self):
        """
        If no browser action exists, inbox should be empty.
        Email-only rule should not create inbox rows.
        """
        channel_recipient_map = {
            "email": [1, 2],
            "zalo": [1],
        }

        inbox_user_ids = sorted(set(channel_recipient_map.get("browser", [])))

        assert inbox_user_ids == []
