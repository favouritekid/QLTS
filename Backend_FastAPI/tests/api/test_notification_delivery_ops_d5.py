# tests/api/test_notification_delivery_ops_d5.py
"""
D5 E2E: API tests for D1-D5 delivery ops endpoints.

Covers: stats, failures, time-series, top-events, latency, health,
        quotas, circuit-breakers, reset, replay.
"""
import logging
from datetime import date, datetime, timezone, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock, MagicMock

from app import models
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)

URL = "/api/notification-deliveries"


# ============================================
# FIXTURES
# ============================================

@pytest_asyncio.fixture
async def seeded(admin_token_headers, client):
    """Seed deliveries + quota. Admin-only tests."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        deliveries = [
            models.NotificationDelivery(
                event="lead_assigned", channel="email", recipient_kind="internal",
                source_type="lead", source_id=1, status="sent",
                created_at=now - timedelta(hours=2), sent_at=now - timedelta(hours=1, minutes=50),
            ),
            models.NotificationDelivery(
                event="lead_assigned", channel="browser", recipient_kind="internal",
                source_type="lead", source_id=1, status="sent",
                created_at=now - timedelta(hours=1), sent_at=now - timedelta(minutes=55),
            ),
            models.NotificationDelivery(
                event="lead_assigned", channel="email", recipient_kind="internal",
                source_type="lead", source_id=2, status="failed",
                error_reason="SMTP timeout", created_at=now - timedelta(hours=1),
            ),
            models.NotificationDelivery(
                event="profile_submitted", channel="browser", recipient_kind="internal",
                status="failed", error_reason="channel_unavailable",
                created_at=now - timedelta(minutes=30),
            ),
            models.NotificationDelivery(
                event="profile_submitted", channel="zalo", recipient_kind="external",
                source_type="lead", source_id=3, status="queued",
                created_at=now - timedelta(minutes=10),
            ),
        ]
        db.add_all(deliveries)

        quota = models.NotificationQuota(
            channel="zalo", provider="zalo_zns", period="daily",
            period_start=date.today(), quota_limit=500, quota_used=42,
            quota_remaining=458, blocked=False,
        )
        db.add(quota)
        await db.commit()
        for d in deliveries:
            await db.refresh(d)
        return {
            "headers": admin_token_headers,
            "failed_id": deliveries[2].id,
            "sent_id": deliveries[0].id,
        }


# ============================================
# STATS
# ============================================

@pytest.mark.asyncio
async def test_stats_returns_aggregates(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats", headers=seeded["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 5
    assert "by_status" in data
    assert "by_channel" in data
    assert "success_rate" in data


@pytest.mark.asyncio
async def test_stats_filter_by_channel(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats", headers=seeded["headers"], params={"channel": "email"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 2


@pytest.mark.asyncio
async def test_stats_filter_by_event(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats", headers=seeded["headers"], params={"event": "lead_assigned"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 3


# ============================================
# FAILURES
# ============================================

@pytest.mark.asyncio
async def test_failures_returns_grouped(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/failures", headers=seeded["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_failures"] >= 2
    assert len(data["by_reason"]) >= 1


@pytest.mark.asyncio
async def test_failures_limit(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/failures", headers=seeded["headers"], params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()["by_reason"]) <= 1


# ============================================
# TIME SERIES
# ============================================

@pytest.mark.asyncio
async def test_time_series_hour(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats/time-series", headers=seeded["headers"], params={"interval": "hour"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["interval"] == "hour"
    assert "buckets" in data


@pytest.mark.asyncio
async def test_time_series_day(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats/time-series", headers=seeded["headers"], params={"interval": "day"})
    assert resp.status_code == 200
    assert resp.json()["interval"] == "day"


@pytest.mark.asyncio
async def test_time_series_has_data(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats/time-series", headers=seeded["headers"])
    total = sum(b["total"] for b in resp.json()["buckets"])
    assert total >= 5


# ============================================
# TOP EVENTS
# ============================================

@pytest.mark.asyncio
async def test_top_events_sorted(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats/top-events", headers=seeded["headers"])
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) >= 2
    totals = [e["total"] for e in events]
    assert totals == sorted(totals, reverse=True)


@pytest.mark.asyncio
async def test_top_events_limit(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats/top-events", headers=seeded["headers"], params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()["events"]) <= 1


@pytest.mark.asyncio
async def test_top_events_fail_rate(client: AsyncClient, seeded):
    """`fail_rate` is a ratio (0..1), matching `get_failure_rate` and the
    frontend `TopEventsTable`/`AlertBanner` consumers (which apply ×100
    themselves). Pin both bounds AND the actual ratios from the seed
    fixture so a regression to "percent" output (which would render as
    "5000.0%") fails this test instead of slipping past `<= 100.0`.
    """
    resp = await client.get(f"{URL}/stats/top-events", headers=seeded["headers"])
    events = {ev["event"]: ev for ev in resp.json()["events"]}
    for ev in events.values():
        assert "fail_rate" in ev
        assert 0.0 <= ev["fail_rate"] <= 1.0, (
            f"fail_rate must be a ratio (0..1), got {ev['fail_rate']} for {ev['event']}"
        )
    # Seed: lead_assigned = 1 failed / 3 total ≈ 0.3333
    if "lead_assigned" in events:
        assert events["lead_assigned"]["total"] == 3
        assert events["lead_assigned"]["failed"] == 1
        assert abs(events["lead_assigned"]["fail_rate"] - (1 / 3)) < 0.01
    # Seed: profile_submitted = 1 failed / 2 total = 0.5
    if "profile_submitted" in events:
        assert events["profile_submitted"]["total"] == 2
        assert events["profile_submitted"]["failed"] == 1
        assert abs(events["profile_submitted"]["fail_rate"] - 0.5) < 0.01


# ============================================
# LATENCY (admin-only)
# ============================================

@pytest.mark.asyncio
async def test_latency_returns_percentiles(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/stats/latency", headers=seeded["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert "p50_seconds" in data
    assert "p95_seconds" in data
    assert data["sample_count"] >= 2


# ============================================
# HEALTH
# ============================================

@pytest.mark.asyncio
async def test_health_returns_channels(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/health", headers=seeded["headers"])
    assert resp.status_code == 200
    data = resp.json()
    channels = {c["channel"] for c in data["channels"]}
    assert {"browser", "email", "zalo", "sms"}.issubset(channels)
    assert "total_queued" in data


@pytest.mark.asyncio
async def test_health_reflects_queued(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/health", headers=seeded["headers"])
    assert resp.json()["total_queued"] >= 1


# ============================================
# QUOTAS
# ============================================

@pytest.mark.asyncio
async def test_quotas_returns_data(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/quotas", headers=seeded["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert "quotas" in data
    assert len(data["quotas"]) >= 1
    zalo = next((q for q in data["quotas"] if q["channel"] == "zalo"), None)
    assert zalo is not None
    assert zalo["quota_used"] == 42
    assert zalo["quota_limit"] == 500


# ============================================
# CIRCUIT BREAKERS
# ============================================

@pytest.mark.asyncio
async def test_breakers_returns_4_channels(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/circuit-breakers", headers=seeded["headers"])
    assert resp.status_code == 200
    channels = {b["channel"] for b in resp.json()["breakers"]}
    assert {"browser", "email", "zalo", "sms"}.issubset(channels)


@pytest.mark.asyncio
async def test_breakers_default_closed(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/circuit-breakers", headers=seeded["headers"])
    for b in resp.json()["breakers"]:
        assert b["state"] in ("closed", "half_open")


# ============================================
# RESET BREAKER
# ============================================

@pytest.mark.asyncio
async def test_reset_breaker_returns_closed(client: AsyncClient, seeded):
    resp = await client.post(f"{URL}/circuit-breakers/email/reset", headers=seeded["headers"])
    assert resp.status_code == 200
    assert resp.json()["state"] == "closed"


# ============================================
# REPLAY
# ============================================

@pytest.mark.asyncio
async def test_replay_failed_delivery(client: AsyncClient, seeded):
    failed_id = seeded["failed_id"]
    with patch("app.tasks.delivery_tasks.execute_notification_delivery") as mock_task:
        mock_task.apply_async = MagicMock()
        resp = await client.post(f"{URL}/{failed_id}/replay", headers=seeded["headers"])
    assert resp.status_code == 200
    assert resp.json()["replayed"] is True


@pytest.mark.asyncio
async def test_replay_enqueue_failure_still_returns_200(client: AsyncClient, seeded):
    """Enqueue failure after commit is best-effort — NOT a 400/500 error.
    Delivery state is already reset to queued; sweep will pick it up."""
    failed_id = seeded["failed_id"]
    with patch("app.tasks.delivery_tasks.execute_notification_delivery") as mock_task:
        mock_task.apply_async = MagicMock(side_effect=ConnectionError("Celery down"))
        resp = await client.post(f"{URL}/{failed_id}/replay", headers=seeded["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["replayed"] is True
    assert "deferred" in body["message"].lower() or "sweep" in body["message"].lower()


@pytest.mark.asyncio
async def test_replay_sent_returns_400(client: AsyncClient, seeded):
    sent_id = seeded["sent_id"]
    resp = await client.post(f"{URL}/{sent_id}/replay", headers=seeded["headers"])
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_replay_nonexistent_returns_404(client: AsyncClient, seeded):
    resp = await client.post(f"{URL}/999999/replay", headers=seeded["headers"])
    assert resp.status_code == 404


# ============================================
# HEALTH SUMMARY — failure rate contract pin (Wave 2 #8)
# ============================================
# Pin the contract that `failure_rate_30m` and per-channel
# `failure_rate_24h` are RATIOS in [0..1] — the FE
# (`ChannelHealthPanel.tsx`, `AlertBanner.tsx`) multiplies by 100 to
# render. Catches a regression to "percent" output (which would render
# as "5000.0%") matching the protection PR #144 added for
# `top_events.fail_rate`.

@pytest.mark.asyncio
async def test_health_failure_rates_are_ratios(client: AsyncClient, seeded):
    resp = await client.get(f"{URL}/health", headers=seeded["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    fr_30m = body.get("failure_rate_30m")
    if fr_30m is not None:
        assert 0.0 <= fr_30m <= 1.0, (
            f"failure_rate_30m must be a ratio in [0..1], got {fr_30m}. "
            f"Did the repository start returning percent output again?"
        )

    for ch in body.get("channels", []):
        fr_24h = ch.get("failure_rate_24h")
        if fr_24h is None:
            continue
        assert 0.0 <= fr_24h <= 1.0, (
            f"channel '{ch['channel']}'.failure_rate_24h must be a ratio "
            f"in [0..1], got {fr_24h}"
        )


@pytest.mark.asyncio
async def test_health_schema_rejects_out_of_range(client: AsyncClient, seeded):
    """Pydantic schema constraints must reject any future code path that
    accidentally writes a percent (e.g. 50.0) into these fields. Verify
    the schema-level guard exists by parsing manually.
    """
    from pydantic import ValidationError

    from app.schemas.notification_delivery import (
        HealthSummaryResponse,
        ChannelHealthItem,
    )

    # Boundaries pass
    HealthSummaryResponse(failure_rate_30m=0.0)
    HealthSummaryResponse(failure_rate_30m=1.0)
    ChannelHealthItem(channel="email", failure_rate_24h=0.0)
    ChannelHealthItem(channel="email", failure_rate_24h=1.0)

    # Out-of-range rejected
    with pytest.raises(ValidationError):
        HealthSummaryResponse(failure_rate_30m=1.5)
    with pytest.raises(ValidationError):
        HealthSummaryResponse(failure_rate_30m=50.0)  # percent leak
    with pytest.raises(ValidationError):
        ChannelHealthItem(channel="email", failure_rate_24h=100.0)
    with pytest.raises(ValidationError):
        ChannelHealthItem(channel="email", failure_rate_24h=-0.1)

# NOTE: Admin-only permission checks (officer denied) are in test_notification_delivery_idor.py
