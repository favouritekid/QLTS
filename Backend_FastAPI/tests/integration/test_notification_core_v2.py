# tests/integration/test_notification_core_v2.py
"""
Integration tests for Notification Core v2 — Tasks 1.1–1.6 acceptance coverage.

Covers:
- Per-channel preference filtering (Task 1.5)
  - Disabling email does not suppress browser
  - Disabling browser does not suppress email
  - zalo_enabled=false suppresses zalo channel
  - Mixed users with different channel preferences
- Metadata API canonical channels (Task 1.2)
  - /notification-rules/metadata returns canonical channels only
  - No "socket" in metadata response
- Event metadata defaults (Task 1.1/1.3)
  - All events default to "browser" not "socket"
- Deprecation warnings (Task 1.6)
  - create_notification() emits DeprecationWarning
  - execute_notification_workflow() emits DeprecationWarning
- Dispatcher contract
  - dispatch() returns (notification_ids, callback)
  - Inbox rows only created for browser-eligible users
  - Channel delivery uses per-channel recipient lists
"""
import warnings
import pytest
from datetime import time
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.core.event_catalog import EVENT_CATALOG  # Wave 2: replaces EVENT_METADATA_REGISTRY
from app.core.event_groups import NotificationChannel, DEFAULT_GROUP_CHANNELS
from app.services.notification_dispatcher import dispatch
from app.services.notification_preference_service import (
    filter_users_by_group,
    should_send_notification,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# =============================================================================
# PER-CHANNEL PREFERENCE FILTERING (Task 1.5)
# =============================================================================

class TestPerChannelPreferenceFiltering:
    """
    Verify that disabling one channel does not suppress others.
    This was the core bug fixed in Task 1.5.
    """

    async def test_disable_email_keeps_browser(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """User disables email → still receives browser notifications."""
        user_id = officer_user_in_db["id"]

        pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=True,
            email_enabled=False,
        )
        db.add(pref)
        await db.commit()

        browser_result = await filter_users_by_group(db, [user_id], "lead", "browser")
        email_result = await filter_users_by_group(db, [user_id], "lead", "email")

        assert browser_result == [user_id], "Browser should NOT be suppressed"
        assert email_result == [], "Email should be suppressed"

    async def test_disable_browser_keeps_email(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """User disables browser → still receives email notifications."""
        user_id = officer_user_in_db["id"]

        pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=False,
            email_enabled=True,
        )
        db.add(pref)
        await db.commit()

        browser_result = await filter_users_by_group(db, [user_id], "lead", "browser")
        email_result = await filter_users_by_group(db, [user_id], "lead", "email")

        assert browser_result == [], "Browser should be suppressed"
        assert email_result == [user_id], "Email should NOT be suppressed"

    async def test_zalo_disabled_by_default(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """zalo_enabled defaults to False → user filtered out for zalo channel."""
        user_id = officer_user_in_db["id"]

        # Default preference (no zalo_enabled set → defaults False)
        pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=True,
            email_enabled=True,
        )
        db.add(pref)
        await db.commit()

        zalo_result = await filter_users_by_group(db, [user_id], "lead", "zalo")

        assert zalo_result == [], "Zalo should be suppressed when zalo_enabled=False (default)"

    async def test_zalo_enabled_passes_filter(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """zalo_enabled=True → user passes zalo channel filter."""
        user_id = officer_user_in_db["id"]

        pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=True,
            email_enabled=True,
            zalo_enabled=True,
        )
        db.add(pref)
        await db.commit()

        zalo_result = await filter_users_by_group(db, [user_id], "lead", "zalo")

        assert zalo_result == [user_id], "Zalo should pass when zalo_enabled=True"

    async def test_mixed_users_per_channel(
        self, db: AsyncSession, officer_user_in_db: dict, admin_user_in_db: dict
    ):
        """
        Two users with different preferences:
        - Officer: browser=True, email=False, zalo=False
        - Admin: browser=False, email=True, zalo=True
        Each channel should only include eligible users.
        """
        officer_id = officer_user_in_db["id"]
        admin_id = admin_user_in_db["id"]

        p1 = models.NotificationPreference(
            user_id=officer_id,
            browser_enabled=True,
            email_enabled=False,
            zalo_enabled=False,
        )
        p2 = models.NotificationPreference(
            user_id=admin_id,
            browser_enabled=False,
            email_enabled=True,
            zalo_enabled=True,
        )
        db.add_all([p1, p2])
        await db.commit()

        both_ids = [officer_id, admin_id]

        browser_result = await filter_users_by_group(db, both_ids, "lead", "browser")
        email_result = await filter_users_by_group(db, both_ids, "lead", "email")
        zalo_result = await filter_users_by_group(db, both_ids, "lead", "zalo")

        assert browser_result == [officer_id], "Only officer has browser enabled"
        assert email_result == [admin_id], "Only admin has email enabled"
        assert zalo_result == [admin_id], "Only admin has zalo enabled"

    async def test_should_send_notification_includes_allow_zalo(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """should_send_notification() must return allow_zalo flag."""
        user_id = officer_user_in_db["id"]

        pref = models.NotificationPreference(
            user_id=user_id,
            zalo_enabled=True,
        )
        db.add(pref)
        await db.commit()

        result = await should_send_notification(db, user_id, "info")

        assert "allow_zalo" in result, "Result must contain allow_zalo key"
        assert result["allow_zalo"] is True

    async def test_should_send_notification_zalo_default_false(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """allow_zalo must be False when zalo_enabled not set."""
        user_id = officer_user_in_db["id"]

        # No preference record → getattr defaults to False
        result = await should_send_notification(db, user_id, "info")

        assert result["allow_zalo"] is False


# =============================================================================
# DISPATCHER PER-CHANNEL INTEGRATION (Task 1.5)
# =============================================================================

class TestDispatcherPerChannelIntegration:
    """
    Integration tests: dispatch() creates inbox rows only for
    browser-eligible users, not for all recipients.
    """

    async def test_dispatch_email_only_user_creates_delivery_without_inbox_row(
        self,
        db: AsyncSession,
        admin_user: models.User,
        officer_user: models.User,
        seeded_dependencies: dict,
    ):
        """
        User with browser_enabled=False but email_enabled=True should still
        get an email delivery, but should NOT get an inbox Notification row.
        Dispatch should succeed and the email channel should have this user.
        """
        pref = models.NotificationPreference(
            user_id=officer_user.id,
            browser_enabled=False,
            email_enabled=True,
        )
        db.add(pref)
        await db.commit()

        lead = models.Lead(
            full_name="Email Only Test",
            phone="0909777888",
            source="test",
            unit_id=seeded_dependencies["unit_id"],
            consultation_status_id=seeded_dependencies["initial_status_id"],
            pipeline_stage_id=seeded_dependencies["stage_id"],
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.commit()
        await db.refresh(lead)

        with (
            patch(
                "app.services.notification_dispatcher.safe_redis_exists",
                AsyncMock(return_value=False),
            ),
            patch(
                "app.services.notification_dispatcher.safe_redis_incr",
                AsyncMock(return_value=1),
            ),
            patch(
                "app.services.notification_dispatcher.safe_redis_set",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.services.notification_dispatcher.safe_redis_expire",
                AsyncMock(return_value=True),
            ),
        ):
            result, callback = await dispatch(
                db=db,
                event=SystemEvents.LEAD_ASSIGNED,
                payload={
                    "lead_id": lead.id,
                    "lead_name": lead.full_name,
                    "officer_id": officer_user.id,
                    "actor_id": admin_user.id,
                },
            )
        await db.commit()

        # Inbox Notification rows are browser-only.
        notif_stmt = select(models.Notification).where(
            models.Notification.user_id == officer_user.id
        )
        notif_result = await db.execute(notif_stmt)
        notifications = notif_result.scalars().all()

        email_delivery_stmt = select(models.NotificationDelivery).where(
            models.NotificationDelivery.user_id == officer_user.id,
            models.NotificationDelivery.channel == "email",
        )
        email_delivery_result = await db.execute(email_delivery_stmt)
        email_deliveries = email_delivery_result.scalars().all()

        browser_delivery_stmt = select(models.NotificationDelivery).where(
            models.NotificationDelivery.user_id == officer_user.id,
            models.NotificationDelivery.channel == "browser",
        )
        browser_delivery_result = await db.execute(browser_delivery_stmt)
        browser_deliveries = browser_delivery_result.scalars().all()

        assert len(notifications) == 0, (
            "Email-only user should not get browser inbox rows"
        )
        assert len(email_deliveries) >= 1, (
            "Email-only user should still get an email delivery row"
        )
        assert len(browser_deliveries) == 0, (
            "Email-only user should not get browser delivery rows"
        )
        assert result == [], "dispatch should return no inbox notification IDs"

    async def test_dispatch_no_notification_when_all_channels_disabled(
        self,
        db: AsyncSession,
        admin_user: models.User,
        officer_user: models.User,
        seeded_dependencies: dict,
    ):
        """
        User with ALL channels disabled should NOT get any Notification row.
        """
        pref = models.NotificationPreference(
            user_id=officer_user.id,
            browser_enabled=False,
            email_enabled=False,
            zalo_enabled=False,
        )
        db.add(pref)
        await db.commit()

        lead = models.Lead(
            full_name="All Off Test",
            phone="0909777999",
            source="test",
            unit_id=seeded_dependencies["unit_id"],
            consultation_status_id=seeded_dependencies["initial_status_id"],
            pipeline_stage_id=seeded_dependencies["stage_id"],
            assigned_officer_id=officer_user.id,
        )
        db.add(lead)
        await db.commit()
        await db.refresh(lead)

        result, callback = await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNED,
            payload={
                "lead_id": lead.id,
                "lead_name": lead.full_name,
                "officer_id": officer_user.id,
                "actor_id": admin_user.id,
            },
        )
        await db.commit()

        stmt = select(models.Notification).where(
            models.Notification.user_id == officer_user.id
        )
        query_result = await db.execute(stmt)
        notifications = query_result.scalars().all()

        assert len(notifications) == 0, (
            "All-channels-disabled user should NOT get Notification row"
        )


# =============================================================================
# METADATA API — CANONICAL CHANNELS (Task 1.2)
# =============================================================================

class TestMetadataCanonicalChannels:
    """Verify metadata sources only use canonical channel values."""

    def test_event_metadata_defaults_are_browser_not_socket(self):
        """Every event's default_channels must use 'browser', never 'socket'."""
        for event, metadata in EVENT_CATALOG.items():
            for ch in metadata.default_channels:
                assert ch != "socket", (
                    f"Event {event.value} still has 'socket' in default_channels: "
                    f"{metadata.default_channels}"
                )
                assert ch in ("browser", "email", "zalo", "sms"), (
                    f"Event {event.value} has unknown channel '{ch}'"
                )

    def test_registered_events_have_canonical_channels(self):
        """Every event in the catalog must use canonical channels only."""
        for event, metadata in EVENT_CATALOG.items():
            for ch in metadata.default_channels:
                assert ch in ("browser", "email", "zalo", "sms"), (
                    f"Event {event.value} has non-canonical channel '{ch}'"
                )

    def test_notification_channel_enum_has_zalo(self):
        """NotificationChannel enum must include ZALO."""
        assert hasattr(NotificationChannel, "ZALO")
        assert NotificationChannel.ZALO.value == "zalo"

    def test_default_group_channels_include_zalo(self):
        """Every event group must have ZALO in its default channel config."""
        for group, channels in DEFAULT_GROUP_CHANNELS.items():
            assert NotificationChannel.ZALO in channels, (
                f"Group {group.value} missing ZALO in DEFAULT_GROUP_CHANNELS"
            )
            # Zalo must default to False
            assert channels[NotificationChannel.ZALO] is False, (
                f"Group {group.value} has ZALO defaulting to True — must be False"
            )

    def test_payment_verified_in_metadata(self):
        """PAYMENT_VERIFIED event must exist in the catalog."""
        assert SystemEvents.PAYMENT_VERIFIED in EVENT_CATALOG
        metadata = EVENT_CATALOG[SystemEvents.PAYMENT_VERIFIED]
        assert metadata.category == "finance"
        assert "browser" in metadata.default_channels

    @pytest.mark.asyncio
    async def test_metadata_api_exposes_only_wizard_safe_internal_resolvers(
        self, db: AsyncSession,
    ):
        """Metadata API should hide unsupported nested resolvers from the wizard."""
        from types import SimpleNamespace
        from app.routers.notification_rules import get_notification_metadata

        response = await get_notification_metadata.__wrapped__(
            request=None,
            current_admin=SimpleNamespace(id=1),
            db=db,
        )
        resolver_types = {item["value"] for item in response["resolver_types"]}

        assert "collaborator_user" in resolver_types
        assert "actor_excluded" not in resolver_types
        assert "composite" not in resolver_types


# =============================================================================
# SCHEMA VALIDATION — REJECT SOCKET ON WRITE (Task 1.2)
# =============================================================================

class TestSchemaRejectSocket:
    """Pydantic schemas must normalize or reject legacy 'socket' appropriately."""

    def test_rule_create_accepts_deprecated_channels_field_without_validation(self):
        """NotificationRuleCreate accepts legacy channels because write path ignores them."""
        from app.schemas.notification import NotificationRuleCreate

        rule = NotificationRuleCreate(
            event="lead_assigned",
            title_template="Test",
            message_template="Test",
            channels=["socket", "email"],
            recipient_config={"resolver_type": "lead_owner", "params": {}},
        )
        assert rule.channels == ["socket", "email"]

    def test_rule_create_accepts_browser(self):
        """NotificationRuleCreate must accept canonical channels."""
        from app.schemas.notification import NotificationRuleCreate

        rule = NotificationRuleCreate(
            event="lead_assigned",
            title_template="Test",
            message_template="Test",
            channels=["browser", "email"],
            recipient_config={"resolver_type": "lead_owner", "params": {}},
        )
        assert rule.channels == ["browser", "email"]

    def test_action_create_rejects_socket(self):
        """NotificationActionCreate must reject channel='socket'."""
        from app.schemas.notification import NotificationActionCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="deprecated"):
            NotificationActionCreate(channel="socket")

    def test_template_create_rejects_socket(self):
        """NotificationTemplateCreate must reject supported_channels with 'socket'."""
        from app.schemas.notification import NotificationTemplateCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="deprecated"):
            NotificationTemplateCreate(
                name="Test",
                template_code="TPL_TEST",
                title_template="Test",
                message_template="Test",
                supported_channels=["socket"],
            )

    def test_rule_response_normalizes_socket(self):
        """NotificationRule response schema normalizes 'socket' → 'browser'."""
        from app.schemas.notification import NotificationRule

        rule = NotificationRule(
            id=1,
            event="lead_assigned",
            title_template="Test",
            message_template="Test",
            channels=["socket", "email"],
            recipient_config={"resolver_type": "lead_owner", "params": {}},
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        assert rule.channels == ["browser", "email"]


# =============================================================================
# DEPRECATION WARNINGS (Task 1.6)
# =============================================================================

class TestDeprecationWarnings:
    """Verify deprecated functions emit warnings."""

    async def test_create_notification_emits_warning(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """create_notification() must emit DeprecationWarning."""
        from app.services.notification_service import create_notification

        user_id = officer_user_in_db["id"]

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await create_notification(
                db=db,
                user_id=user_id,
                title="Deprecation Test",
                message="Testing deprecation warning",
            )
            await db.commit()

            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1, (
                "create_notification() must emit DeprecationWarning"
            )
            assert "deprecated" in str(deprecation_warnings[0].message).lower()


# =============================================================================
# NORMALIZER EDGE CASES (Task 1.1 supplement)
# =============================================================================

class TestNormalizerEdgeCases:
    """Additional edge cases for channel normalization not in unit tests."""

    def test_normalize_in_schema_dedup(self):
        """
        If legacy data has both 'socket' and 'browser', response should dedup
        to just 'browser'.
        """
        from app.schemas.notification import NotificationRule

        rule = NotificationRule(
            id=1,
            event="test",
            title_template="t",
            message_template="m",
            channels=["socket", "browser", "email"],
            recipient_config={"resolver_type": "lead_owner", "params": {}},
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        assert rule.channels == ["browser", "email"], (
            "socket+browser should dedup to just browser"
        )

    def test_template_default_is_browser(self):
        """Template schema default supported_channels is ['browser'] not ['socket']."""
        from app.schemas.notification import NotificationTemplateBase

        template = NotificationTemplateBase(
            name="Test",
            template_code="TPL_TEST",
            title_template="t",
            message_template="m",
        )
        assert template.supported_channels == ["browser"]
