# app/services/notification_quota_service.py
"""
Phase D1: Quota management service.

Redis cache for fast quota check → DB fallback → sync from provider.
"""
import structlog
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.config import settings
from app.repositories.notification_quota_repository import NotificationQuotaRepository

log = structlog.get_logger(__name__)

# Redis cache key pattern (matches cooldown pattern from dispatcher)
_QUOTA_CACHE_KEY = "notif:quota:{channel}:{date}"
_QUOTA_CACHE_TTL = 300  # 5 minutes


async def check_quota(
    db: AsyncSession,
    channel: str,
    provider: str = "default",
) -> bool:
    """
    Check if channel has available quota. Returns True if OK to send.

    The period (daily vs monthly) and limit are resolved per-channel by
    ``get_channel_quota_config`` — zalo_bot is MONTHLY, zalo (ZNS) is daily.
    Channels with no configured quota are unlimited.

    Fast path: Redis cache. Slow path: DB lookup.
    """
    cfg = get_channel_quota_config(channel)
    if cfg is None:
        return True  # No quota configured for this channel = unlimited

    period, period_start, _limit = cfg
    # Cache key is scoped to the period_start, so a monthly channel caches
    # per-month and a daily channel per-day without key collisions.
    cache_key = _QUOTA_CACHE_KEY.format(channel=channel, date=period_start.isoformat())

    # Fast path: check Redis cache
    try:
        redis = await database.get_redis()
        cached = await redis.get(cache_key)
        if cached is not None:
            return cached != "blocked"
    except Exception as e:
        log.warning(
            "Redis quota cache read failed, falling through to DB", error=str(e)
        )

    # Slow path: DB check
    repo = NotificationQuotaRepository(db)
    over = await repo.is_over_quota(
        channel, provider, period=period, period_start=period_start
    )

    # Cache result
    try:
        redis = await database.get_redis()
        value = "blocked" if over else "ok"
        await redis.set(cache_key, value, ex=_QUOTA_CACHE_TTL)
    except Exception as e:
        log.warning("Redis quota cache write failed", error=str(e))

    return not over


async def record_send(
    db: AsyncSession,
    channel: str,
    provider: str = "default",
) -> None:
    """Record a successful send, incrementing quota_used for the channel's period."""
    cfg = get_channel_quota_config(channel)
    if cfg is None:
        return  # No quota configured for this channel

    period, period_start, limit = cfg
    repo = NotificationQuotaRepository(db)

    # Ensure quota row exists for the current period
    quota = await repo.get_current_quota(
        channel, provider, period=period, period_start=period_start
    )
    if quota is None:
        # Auto-create with configured limit for this period
        await repo.upsert_quota(
            channel=channel,
            provider=provider,
            period=period,
            period_start=period_start,
            quota_limit=limit,
            quota_used=1,
        )
        return

    updated = await repo.increment_used(
        channel, provider, period=period, period_start=period_start
    )
    if updated and updated.quota_used >= updated.quota_limit:
        # Block and invalidate cache
        updated.blocked = True
        await db.flush()
        await _invalidate_quota_cache(channel, period_start)
        log.warning(
            "Channel quota exhausted",
            channel=channel,
            provider=provider,
            period=period,
            used=updated.quota_used,
            limit=updated.quota_limit,
        )


async def sync_zalo_quota(
    db: AsyncSession,
    quota_remaining: Optional[int],
) -> None:
    """
    Sync Zalo quota from provider response.
    Called after successful Zalo send with ZaloSendResult.quota_remaining.
    """
    if quota_remaining is None:
        return

    today = date.today()
    limit = settings.ZALO_DAILY_QUOTA_LIMIT
    used = max(0, limit - quota_remaining)

    repo = NotificationQuotaRepository(db)
    blocked = quota_remaining <= 0

    await repo.upsert_quota(
        channel="zalo",
        provider="zalo_zns",
        period="daily",
        period_start=today,
        quota_limit=limit,
        quota_used=used,
        quota_remaining=quota_remaining,
        blocked=blocked,
    )

    # Update cache
    try:
        redis = await database.get_redis()
        cache_key = _QUOTA_CACHE_KEY.format(channel="zalo", date=today.isoformat())
        value = "blocked" if blocked else "ok"
        await redis.set(cache_key, value, ex=_QUOTA_CACHE_TTL)
    except Exception:
        pass

    log.info(
        "Zalo quota synced",
        remaining=quota_remaining,
        used=used,
        limit=limit,
        blocked=blocked,
    )


async def get_quota_summary(
    db: AsyncSession,
    period_start: Optional[date] = None,
) -> List[Dict]:
    """Get quota summary for the current period(s) of all channels.

    When ``period_start`` is None (default), returns rows for BOTH the current
    day (daily channels) and the first of the current month (monthly channels
    like zalo_bot) so the health dashboard shows every channel's live usage.
    """
    repo = NotificationQuotaRepository(db)
    # Fetch each channel-class's CURRENT period as an exact (period, period_start)
    # window. Filtering by period_start alone would also match a stale same-date
    # row of a DIFFERENT period (e.g. a daily row created on the 1st of the
    # month), producing duplicate/conflicting rows for one channel.
    if period_start is None:
        today = date.today()
        windows = [("daily", today), ("monthly", today.replace(day=1))]
    else:
        windows = [("daily", period_start), ("monthly", period_start)]
    quotas = await repo.get_current_quotas(windows)
    return [
        {
            "id": q.id,
            "channel": q.channel,
            "provider": q.provider,
            "period": q.period,
            "period_start": q.period_start.isoformat(),
            "quota_limit": q.quota_limit,
            "quota_used": q.quota_used,
            "quota_remaining": q.quota_remaining,
            "blocked": q.blocked,
            "usage_pct": round(q.quota_used / q.quota_limit * 100, 1) if q.quota_limit and q.quota_limit > 0 else 0.0,
        }
        for q in quotas
    ]


async def get_health_summary(db: AsyncSession) -> Dict:
    """
    H1: Combined health summary — quota + breaker + backlog + failure rate.
    Extracted from router to service layer per CLAUDE.md architecture.
    """
    from app.services.notification_circuit_breaker import get_all_breaker_states
    from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

    repo = NotificationDeliveryRepository(db)

    try:
        breaker_states = get_all_breaker_states()
    except Exception:
        breaker_states = []
    breaker_map = {s["channel"]: s["state"] for s in breaker_states}

    try:
        quota_summary = await get_quota_summary(db)
    except Exception:
        quota_summary = []
    quota_map = {q["channel"]: q for q in quota_summary}

    channels = []
    for ch in ("browser", "email", "zalo", "zalo_bot", "sms"):
        item: Dict = {"channel": ch, "breaker_state": breaker_map.get(ch, "closed")}
        if ch in quota_map:
            item["quota_used"] = quota_map[ch]["quota_used"]
            item["quota_limit"] = quota_map[ch]["quota_limit"]
            item["quota_blocked"] = quota_map[ch]["blocked"]
        channels.append(item)

    backlog = await repo.get_queued_backlog_count()
    failure_rate = await repo.get_failure_rate(minutes=30)
    alerts_active = sum(1 for s in breaker_states if s["state"] == "open")

    return {
        "channels": channels,
        "total_queued": backlog,
        "failure_rate_30m": failure_rate,
        "alerts_active": alerts_active,
    }


def get_channel_quota_config(
    channel: str,
) -> Optional[Tuple[str, date, int]]:
    """Resolve ``(period, period_start, limit)`` for a channel's quota.

    Returns None for channels with no configured quota (treated as unlimited).

    - ``zalo_bot`` → **MONTHLY** (period_start = first of current month). The
      Zalo Bot Platform free tier caps at 3000 msg/MONTH with **no** hard daily
      ceiling, so a daily cap wasted the monthly budget on uneven (bursty
      admission-season) traffic. A monthly period lets quiet days' unused
      allowance carry to busy days within the same month.
    - ``zalo`` (ZNS) → daily. The ZNS provider enforces a per-day quota that we
      sync from each send response (see ``sync_zalo_quota``).
    """
    today = date.today()
    if channel == "zalo_bot":
        return ("monthly", today.replace(day=1), settings.ZALO_BOT_MONTHLY_QUOTA)
    if channel == "zalo":
        return ("daily", today, settings.ZALO_DAILY_QUOTA_LIMIT)
    return None


async def _invalidate_quota_cache(channel: str, day: date) -> None:
    """Invalidate Redis quota cache for a channel."""
    try:
        from app import database
        redis = await database.get_redis()
        cache_key = _QUOTA_CACHE_KEY.format(channel=channel, date=day.isoformat())
        await redis.delete(cache_key)
    except Exception:
        pass
