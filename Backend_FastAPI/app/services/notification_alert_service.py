# app/services/notification_alert_service.py
"""
Phase D3: Automated alerting for notification delivery health.

4 check functions, Redis dedup to prevent alert storms, dispatches via SYSTEM_ALERT.
"""
import structlog
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app import database
from app.config import settings
from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
from app.services.notification_circuit_breaker import get_all_breaker_states

log = structlog.get_logger(__name__)

# Redis dedup key pattern
_ALERT_DEDUP_KEY = "notif:alert:dedup:{alert_type}"
_ALERT_DEDUP_TTL = 3600  # 1 hour


async def check_failure_rate_alert(db) -> Optional[Dict]:
    """Check if failure rate exceeds threshold in last 30 minutes."""

    repo = NotificationDeliveryRepository(db)
    rate = await repo.get_failure_rate(minutes=30)

    if rate is not None and rate > settings.ALERT_FAILURE_RATE_THRESHOLD:
        return {
            "alert_type": "failure_rate_high",
            "severity": "warning",
            "message": f"Notification failure rate is {rate:.1%} (threshold: {settings.ALERT_FAILURE_RATE_THRESHOLD:.0%})",
            "details": {"failure_rate": rate, "threshold": settings.ALERT_FAILURE_RATE_THRESHOLD},
        }
    return None


async def check_backlog_alert(db) -> Optional[Dict]:
    """Check if queued backlog exceeds threshold."""

    repo = NotificationDeliveryRepository(db)
    backlog = await repo.get_queued_backlog_count()

    if backlog > settings.ALERT_BACKLOG_THRESHOLD:
        return {
            "alert_type": "backlog_high",
            "severity": "warning",
            "message": f"Notification backlog: {backlog} queued (threshold: {settings.ALERT_BACKLOG_THRESHOLD})",
            "details": {"backlog_count": backlog, "threshold": settings.ALERT_BACKLOG_THRESHOLD},
        }
    return None


async def check_webhook_lag_alert(db) -> Optional[Dict]:
    """Check for stale sent deliveries without webhook confirmation."""

    repo = NotificationDeliveryRepository(db)
    stale = await repo.get_stale_sent_count(lag_minutes=settings.ALERT_WEBHOOK_LAG_MINUTES)

    if stale > 0:
        return {
            "alert_type": "webhook_lag",
            "severity": "info",
            "message": f"{stale} deliveries sent >{settings.ALERT_WEBHOOK_LAG_MINUTES}min without webhook confirmation",
            "details": {"stale_count": stale, "lag_minutes": settings.ALERT_WEBHOOK_LAG_MINUTES},
        }
    return None


async def check_breaker_alert() -> Optional[Dict]:
    """Check if any circuit breaker is open."""

    states = get_all_breaker_states()
    open_channels = [s["channel"] for s in states if s["state"] == "open"]

    if open_channels:
        return {
            "alert_type": "breaker_open",
            "severity": "error",
            "message": f"Circuit breaker OPEN for channels: {', '.join(open_channels)}",
            "details": {"open_channels": open_channels},
        }
    return None


async def run_all_checks(db) -> List[Dict]:
    """Run all alert checks and return fired alerts (after dedup)."""
    alerts = []

    checks = [
        check_failure_rate_alert(db),
        check_backlog_alert(db),
        check_webhook_lag_alert(db),
        check_breaker_alert(),
    ]

    for coro in checks:
        try:
            result = await coro
            if result:
                # Dedup check
                deduped = await _is_deduped(result["alert_type"])
                if not deduped:
                    alerts.append(result)
                    await _set_dedup(result["alert_type"])
        except Exception as e:
            log.error("Alert check failed", error=str(e))

    return alerts


async def _is_deduped(alert_type: str) -> bool:
    """Check if alert was already fired within dedup window."""
    try:

        redis = await database.get_redis()
        key = _ALERT_DEDUP_KEY.format(alert_type=alert_type)
        return await redis.exists(key)
    except Exception:
        return False  # Redis down → allow alert through


async def _set_dedup(alert_type: str) -> None:
    """Mark alert type as fired for dedup window."""
    try:

        redis = await database.get_redis()
        key = _ALERT_DEDUP_KEY.format(alert_type=alert_type)
        await redis.set(key, "1", ex=_ALERT_DEDUP_TTL)
    except Exception:
        pass
