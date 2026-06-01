# app/services/notification_alert_service.py
"""
Phase D3: Automated alerting for notification delivery health.

4 check functions, Redis dedup to prevent alert storms. The fired alerts are
dispatched by the ``check_notification_alerts`` Celery task via the admin-only
``NOTIFICATION_HEALTH_ALERT`` event (browser + email, all_admins) — info-
severity alerts are logged but not dispatched.
"""
import structlog
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.config import settings
from app.core.events import SystemEvents
from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
from app.services.notification_circuit_breaker import get_all_breaker_states

log = structlog.get_logger(__name__)

# Redis dedup key pattern
_ALERT_DEDUP_KEY = "notif:alert:dedup:{alert_type}"
_ALERT_DEDUP_TTL = 3600  # 1 hour

# Operational events the health checks must NOT measure — the health task
# itself dispatches NOTIFICATION_HEALTH_ALERT, so counting its own deliveries
# in the failure-rate / backlog windows would let a single fan-out re-trigger
# the failure_rate_high alert next cycle (self-feeding loop). We exclude ONLY
# the self-referential event — NOT system_alert, which (after Approach Y) is a
# real admin broadcast whose delivery failures we still want to surface.
_OPERATIONAL_ALERT_EVENTS = [SystemEvents.NOTIFICATION_HEALTH_ALERT.value]


async def check_failure_rate_alert(db: AsyncSession) -> Optional[Dict]:
    """Check if failure rate exceeds threshold in last 30 minutes."""
    repo = NotificationDeliveryRepository(db)
    rate = await repo.get_failure_rate(
        minutes=30, exclude_events=_OPERATIONAL_ALERT_EVENTS
    )

    if rate is not None and rate > settings.ALERT_FAILURE_RATE_THRESHOLD:
        return {
            "alert_type": "failure_rate_high",
            "severity": "warning",
            "message": f"Notification failure rate is {rate:.1%} (threshold: {settings.ALERT_FAILURE_RATE_THRESHOLD:.0%})",
            "details": {"failure_rate": rate, "threshold": settings.ALERT_FAILURE_RATE_THRESHOLD},
        }
    return None


async def check_backlog_alert(db: AsyncSession) -> Optional[Dict]:
    """Check if queued backlog exceeds threshold."""
    repo = NotificationDeliveryRepository(db)
    backlog = await repo.get_queued_backlog_count(
        exclude_events=_OPERATIONAL_ALERT_EVENTS
    )

    if backlog > settings.ALERT_BACKLOG_THRESHOLD:
        return {
            "alert_type": "backlog_high",
            "severity": "warning",
            "message": f"Notification backlog: {backlog} queued (threshold: {settings.ALERT_BACKLOG_THRESHOLD})",
            "details": {"backlog_count": backlog, "threshold": settings.ALERT_BACKLOG_THRESHOLD},
        }
    return None


async def check_webhook_lag_alert(db: AsyncSession) -> Optional[Dict]:
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


async def run_all_checks(db: AsyncSession) -> List[Dict]:
    """Run all alert checks and return fired alerts (after dedup).

    The 3 DB-touching checks must run SEQUENTIALLY on the shared session.
    SQLAlchemy AsyncSession is stateful and cannot be shared between
    concurrent tasks — running `asyncio.gather(check_a(db), check_b(db), ...)`
    on the same session raises `InvalidRequestError: This session is
    provisioning a new connection; concurrent operations are not permitted`
    (https://sqlalche.me/e/20/isce). See Issue #104.

    Sequential cost is ~30ms total (3 × <10ms COUNT queries on a small
    notification_delivery table); parallel execution would save ~20ms at
    the price of correctness, which is not worth the trade-off.

    Each check is wrapped in its own try/except so that a failure in one
    check doesn't block the others. The circuit breaker check does not
    touch the DB and runs after the DB checks.
    """
    alerts: List[Dict] = []

    # 1. Sequential DB checks on the shared session (safe).
    db_checks = [
        ("failure_rate", check_failure_rate_alert),
        ("backlog", check_backlog_alert),
        ("webhook_lag", check_webhook_lag_alert),
    ]
    for name, check_fn in db_checks:
        try:
            result = await check_fn(db)
        except Exception as e:
            log.error(
                "Alert check raised exception",
                check=name,
                error=str(e),
                exc_type=type(e).__name__,
            )
            continue
        if result is None:
            continue
        # Atomic dedup: SET NX (set-if-not-exists)
        if not await _try_set_dedup(result["alert_type"]):
            continue  # Already fired within dedup window
        alerts.append(result)

    # 2. Circuit breaker check — no DB access, runs after DB checks.
    try:
        breaker_result = await check_breaker_alert()
    except Exception as e:
        log.error(
            "Alert check raised exception",
            check="breaker",
            error=str(e),
            exc_type=type(e).__name__,
        )
        breaker_result = None
    if breaker_result is not None:
        if await _try_set_dedup(breaker_result["alert_type"]):
            alerts.append(breaker_result)

    return alerts


async def _try_set_dedup(alert_type: str) -> bool:
    """
    Atomic dedup: SET key NX EX ttl. Returns True if set succeeded (not deduped).
    Uses Redis SET NX for race-condition safety.
    """
    try:
        redis = await database.get_redis()
        key = _ALERT_DEDUP_KEY.format(alert_type=alert_type)
        # SET NX returns True if key was set (not existing), False if already exists
        was_set = await redis.set(key, "1", ex=_ALERT_DEDUP_TTL, nx=True)
        return bool(was_set)
    except Exception:
        return True  # Redis down → allow alert through
