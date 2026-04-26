"""Integration tests for v5 Step 12 — link service ↔ preference sync.

Verify that ``zalo_bot_link_service.verify_and_link`` and
``unlink`` actually persist ``zalo_bot_enabled`` after the column
landed in Step 11. Pre-v5 the link service swallowed errors via
``hasattr`` to allow the column to land later — that guard is now
removed and persistence is mandatory.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_preference import NotificationPreference
from app.services import zalo_bot_link_service
from app.services.notification_preference_service import (
    filter_users_by_group,
    get_group_preference,
)


@pytest.mark.integration
class TestPreferenceSyncOnLink:
    @pytest.mark.asyncio
    async def test_verify_and_link_flips_pref_true(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        # GETDEL returns the user_id our code stored in Redis — patched
        # because we never touched Redis here, just the link flow.
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            ok, _ = await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_alpha", "Officer A"
            )
        assert ok is True
        await db.commit()

        pref = (
            await db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id
                )
            )
        ).scalar_one()
        assert pref.zalo_bot_enabled is True

    @pytest.mark.asyncio
    async def test_unlink_flips_pref_false(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_alpha", None
            )
        await db.commit()

        ok, _ = await zalo_bot_link_service.unlink(db, user_id)
        assert ok is True
        await db.commit()

        pref = (
            await db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id
                )
            )
        ).scalar_one()
        assert pref.zalo_bot_enabled is False


@pytest.mark.integration
class TestFilterUsersByGroupZaloBot:
    @pytest.mark.asyncio
    async def test_global_disabled_blocks(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        # Default zalo_bot_enabled is False even when the row exists.
        pref = NotificationPreference(user_id=user_id, browser_enabled=True)
        db.add(pref)
        await db.commit()

        result = await filter_users_by_group(db, [user_id], "lead", "zalo_bot")
        assert result == []

    @pytest.mark.asyncio
    async def test_global_enabled_plus_group_optin_passes(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        pref = NotificationPreference(
            user_id=user_id,
            browser_enabled=True,
            zalo_bot_enabled=True,
            type_preferences={"lead": {"zalo_bot": True}},
        )
        db.add(pref)
        await db.commit()

        result = await filter_users_by_group(db, [user_id], "lead", "zalo_bot")
        assert result == [user_id]

    @pytest.mark.asyncio
    async def test_global_enabled_without_group_optin_still_blocked(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        # v5 Finding 1 + Step 12: even with global toggle on, missing
        # per-group entry falls back to DEFAULT_GROUP_CHANNELS which is
        # False for zalo_bot in every group.
        user_id = officer_user_in_db["id"]
        pref = NotificationPreference(
            user_id=user_id,
            browser_enabled=True,
            zalo_bot_enabled=True,
            type_preferences=None,
        )
        db.add(pref)
        await db.commit()

        result = await filter_users_by_group(db, [user_id], "lead", "zalo_bot")
        assert result == []


@pytest.mark.unit
class TestDefaultGroupPrefForZaloBotIsFalse:
    """Pure-logic check that complements the contract test in
    ``test_zalo_bot_phase4_contracts.py`` — exercises the resolver
    function for every group rather than the static dict."""

    def test_every_group_zalo_bot_default_false(self):
        from app.core.event_groups import DEFAULT_GROUP_CHANNELS

        for group in DEFAULT_GROUP_CHANNELS.keys():
            assert (
                get_group_preference(None, group.value, "zalo_bot") is False
            ), f"{group.value} default for zalo_bot must be False"
