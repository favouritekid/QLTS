# tests/integration/test_notification_delivery_stale_sent_filter.py
"""Anchor test for NotificationDeliveryRepository.get_stale_sent_count.

PR-1 Commit 1 (2026-05-23) — re-add ``zalo`` to the stale-sent channel
filter after the ZBS Template Message webhook handler shipped (commit
``d357c029``). Before that commit zalo was excluded because a "sent zalo
row older than 60min" was the expected interim state. Post-d357c029 the
webhook transitions ``sent → delivered`` in ~3-10s, so a stale ``sent``
row IS now a meaningful alert.

Anchor pins:
  - Both ``sms`` AND ``zalo`` channels above the lag window count
  - ``email`` / ``browser`` are NOT counted (handler-confirmed channels
    have their own delivery webhooks; zalo/sms are the "provider
    callback uncertain" cohort)
  - Rows inside the lag window do not count

Reference: memory ``outstanding-debt`` P3-9 + ``project_zns_uid_findings``.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notification_delivery_repository import (
    NotificationDeliveryRepository,
)


@pytest.mark.asyncio
@pytest.mark.integration
class TestGetStaleSentCount:
    """Pin the stale-sent filter post-d357c029 webhook handler."""

    async def _seed_sent(
        self,
        db: AsyncSession,
        *,
        channel: str,
        minutes_ago: int,
        user_id: int,
    ) -> int:
        """Seed a ``status='sent'`` row at ``now - minutes_ago``. Returns id."""
        repo = NotificationDeliveryRepository(db)
        sent_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        delivery = await repo.create_delivery(
            event="test_stale_filter_anchor",
            channel=channel,
            recipient_kind="internal",
            user_id=user_id,
            status="sent",
            sent_at=sent_at,
        )
        return delivery.id

    async def test_counts_both_sms_and_zalo_above_lag_window(
        self, db: AsyncSession, admin_user
    ):
        """Both sms AND zalo rows older than lag count as stale."""
        await self._seed_sent(db, channel="sms", minutes_ago=90, user_id=admin_user.id)
        await self._seed_sent(db, channel="zalo", minutes_ago=90, user_id=admin_user.id)

        repo = NotificationDeliveryRepository(db)
        count = await repo.get_stale_sent_count(lag_minutes=60)

        assert count == 2, (
            f"Expected both sms+zalo to be flagged stale, got count={count}. "
            f"Post-d357c029 ZBS webhook handler shipped → zalo MUST be in filter."
        )

    async def test_zalo_within_lag_window_not_counted(
        self, db: AsyncSession, admin_user
    ):
        """Zalo row sent recently (within lag) is NOT a stale alert."""
        await self._seed_sent(db, channel="zalo", minutes_ago=30, user_id=admin_user.id)

        repo = NotificationDeliveryRepository(db)
        count = await repo.get_stale_sent_count(lag_minutes=60)

        assert count == 0, (
            f"Recent zalo (30min old < 60min lag) should NOT be flagged. "
            f"Got count={count} — filter may have flipped window comparator."
        )

    async def test_browser_and_email_channels_not_counted(
        self, db: AsyncSession, admin_user
    ):
        """browser + email have their own provider webhooks and are NOT in
        the stale-sent cohort. Only sms+zalo (provider-callback uncertain
        channels) are flagged when stuck in ``sent`` past the lag.
        """
        await self._seed_sent(db, channel="browser", minutes_ago=90, user_id=admin_user.id)
        await self._seed_sent(db, channel="email", minutes_ago=90, user_id=admin_user.id)

        repo = NotificationDeliveryRepository(db)
        count = await repo.get_stale_sent_count(lag_minutes=60)

        assert count == 0, (
            f"browser+email channels must not be in stale-sent filter. "
            f"Got count={count}."
        )
