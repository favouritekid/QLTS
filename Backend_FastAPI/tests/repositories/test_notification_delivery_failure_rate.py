"""Repository tests: NotificationDeliveryRepository.get_failure_rate /
get_queued_backlog_count ``exclude_events`` — fix/notification-alert-flood
F-metric.

The operational ``notification_health_alert`` event must be excludable from
BOTH numerator and denominator so the health task never measures its own
fan-out (the self-feeding failure-rate loop). Default arg preserves the
original behaviour exactly.

The ``db`` fixture truncates ``notification_delivery`` per test, so the rows
seeded here are the only ones in the 30-minute window — rates are exact.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.notification_delivery_repository import (
    NotificationDeliveryRepository,
)


def _delivery(event: str, status: str, *, channel: str = "email"):
    return models.NotificationDelivery(
        event=event,
        channel=channel,
        recipient_kind="internal",
        status=status,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
@pytest.mark.integration
class TestGetFailureRateExclude:
    """``notification_health_alert`` dead-letters must not inflate the rate."""

    async def _seed(self, db: AsyncSession):
        # 10 normal lead_assigned: 8 sent + 2 failed → real fail rate = 20%.
        rows = [_delivery("lead_assigned", "sent") for _ in range(8)]
        rows += [_delivery("lead_assigned", "failed") for _ in range(2)]
        # 5 health-alert deliveries ALL dead_lettered (the self-pumping rows
        # that previously drove a single fan-out above the 20% threshold).
        rows += [
            _delivery("notification_health_alert", "dead_lettered")
            for _ in range(5)
        ]
        db.add_all(rows)
        await db.flush()

    async def test_default_includes_all_events(self, db: AsyncSession):
        await self._seed(db)
        repo = NotificationDeliveryRepository(db)
        rate = await repo.get_failure_rate(minutes=30)
        # total 15, failures 7 (2 normal + 5 health) → inflated to ~46.7%.
        assert rate == pytest.approx(7 / 15)

    async def test_exclude_operational_event_yields_real_rate(
        self, db: AsyncSession
    ):
        await self._seed(db)
        repo = NotificationDeliveryRepository(db)
        rate = await repo.get_failure_rate(
            minutes=30, exclude_events=["notification_health_alert"]
        )
        # Only the normal rows count: total 10, failures 2 → 20%.
        assert rate == pytest.approx(0.2)

    async def test_exclude_strictly_lower_than_default(self, db: AsyncSession):
        await self._seed(db)
        repo = NotificationDeliveryRepository(db)
        default = await repo.get_failure_rate(minutes=30)
        excluded = await repo.get_failure_rate(
            minutes=30, exclude_events=["notification_health_alert"]
        )
        assert excluded < default, (
            "Excluding the self-referential event must lower the measured rate "
            "(that is the whole point of the F-metric fix)."
        )

    async def test_empty_exclude_list_is_no_op(self, db: AsyncSession):
        await self._seed(db)
        repo = NotificationDeliveryRepository(db)
        default = await repo.get_failure_rate(minutes=30)
        empty = await repo.get_failure_rate(minutes=30, exclude_events=[])
        # exclude_events=[] means "exclude NOTHING" → identical to default.
        # (Here the truthy guard is intentional: empty exclusion = no filter.)
        assert empty == default

    async def test_none_when_only_excluded_events_exist(self, db: AsyncSession):
        # Only health rows exist; excluding them → total 0 → None (no data).
        db.add_all(
            [
                _delivery("notification_health_alert", "dead_lettered")
                for _ in range(3)
            ]
        )
        await db.flush()
        repo = NotificationDeliveryRepository(db)
        rate = await repo.get_failure_rate(
            minutes=30, exclude_events=["notification_health_alert"]
        )
        assert rate is None


@pytest.mark.asyncio
@pytest.mark.integration
class TestGetQueuedBacklogExclude:
    async def test_backlog_excludes_operational(self, db: AsyncSession):
        db.add_all(
            [
                _delivery("lead_assigned", "queued"),
                _delivery("lead_assigned", "queued"),
                _delivery("notification_health_alert", "queued"),
            ]
        )
        await db.flush()
        repo = NotificationDeliveryRepository(db)
        assert await repo.get_queued_backlog_count() == 3
        assert (
            await repo.get_queued_backlog_count(
                exclude_events=["notification_health_alert"]
            )
            == 2
        )
