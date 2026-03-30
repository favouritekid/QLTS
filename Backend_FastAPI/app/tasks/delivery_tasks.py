# app/tasks/delivery_tasks.py
"""
Phase C1+C2: Celery tasks for executing notification deliveries.

C1: execute_notification_delivery — worker for non-browser channels
C2: exponential backoff retry, permanent/transient error classification,
    dead-letter pipeline, sweep_retry_deliveries Beat task

Flow:
  1. Load delivery by ID
  2. Check idempotency (skip if not in queued/failed)
  3. Re-check scheduled_for (re-enqueue if too early)
  4. Re-check consent/preference (permanent skip if revoked)
  5. Call channel.execute_delivery(delivery, db)
  6. On success: mark_sent
  7. On failure: classify error → transient (retry w/ backoff) or permanent (dead-letter)
"""
import logging
from datetime import datetime, timedelta, timezone

from ..celery_app import celery_app
from .utils import task_db_session, run_async_task


# =============================================================================
# Error classification
# =============================================================================

PERMANENT_ERRORS = frozenset({
    "consent_revoked",
    "consent_not_granted",
    "preference_disabled",
    "user_not_found",
    "no_email",
    "no_phone",
    "invalid_phone",
    "channel_not_implemented",
    "execute_delivery_not_supported",
    # Zalo permanent errors
    "Zalo error -216",   # Template không tồn tại
    "Zalo error -230",   # SĐT không dùng Zalo
    "Zalo error -202",   # App không có quyền
    "Zalo error -204",   # OA bị khoá
})
# -217 (template chưa duyệt) = TRANSIENT — template có thể được duyệt sau
# -210 (quota hết) = TRANSIENT — quota reset theo ngày
# All other errors = transient → retry

RETRY_BACKOFF_BASE = 60      # seconds
RETRY_BACKOFF_MAX = 3600     # cap at 1 hour


def _is_permanent_error(error_reason: str) -> bool:
    """Check if error is permanent (no point retrying)."""
    if not error_reason:
        return False
    for pe in PERMANENT_ERRORS:
        if pe in error_reason:
            return True
    return False


def _calculate_next_retry(attempt_count: int) -> datetime:
    """Exponential backoff: 60s * 2^attempt, capped at 1 hour."""
    delay = min(RETRY_BACKOFF_BASE * (2 ** attempt_count), RETRY_BACKOFF_MAX)
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


# =============================================================================
# Main delivery execution task
# =============================================================================

@celery_app.task(
    name="execute_notification_delivery",
    bind=True,
    max_retries=0,  # C2: manual retry management, no Celery autoretry
    acks_late=True,
)
def execute_notification_delivery(self, delivery_id: int):
    """
    Execute a single notification delivery.

    C2 changes:
    - No autoretry — retry managed via next_retry_at + sweep task
    - Exponential backoff: 60s, 120s, 240s, ... cap 1h
    - Permanent errors → dead-letter immediately
    - Transient errors → schedule retry if under max_retries
    """
    task_name = "execute_notification_delivery"
    task_log = logging.getLogger(task_name)
    task_log.info(f"Executing delivery {delivery_id}")

    async def _run():
        from app.models.notification_delivery import NotificationDelivery
        from app.services.notification_channels import get_channel
        from app.services import notification_delivery_service

        async with task_db_session() as session:
            # 1. Load delivery
            delivery = await session.get(NotificationDelivery, delivery_id)
            if not delivery:
                task_log.warning(f"Delivery {delivery_id} not found")
                return {"status": "not_found", "delivery_id": delivery_id}

            # 2. Idempotency: only process queued or failed (retry)
            if delivery.status not in ("queued", "failed"):
                task_log.info(
                    f"Delivery {delivery_id} status={delivery.status}, skipping"
                )
                return {"status": "skipped_idempotent", "delivery_id": delivery_id}

            # 3. Check scheduled_for: re-enqueue if too early
            now = datetime.now(timezone.utc)
            if delivery.scheduled_for and delivery.scheduled_for > now:
                seconds_until = (delivery.scheduled_for - now).total_seconds()
                task_log.info(
                    f"Delivery {delivery_id} scheduled for {delivery.scheduled_for}, "
                    f"re-enqueueing in {seconds_until:.0f}s"
                )
                execute_notification_delivery.apply_async(
                    args=[delivery_id],
                    countdown=seconds_until,
                )
                return {"status": "re_enqueued", "delivery_id": delivery_id}

            # 4. Re-check eligibility (consent/preference)
            # M10: Import from service (not local) to avoid import cycle
            from app.services.notification_delivery_service import check_delivery_eligibility
            skip_reason = await check_delivery_eligibility(session, delivery)
            if skip_reason:
                if _is_permanent_error(skip_reason):
                    # Permanent: dead-letter
                    await notification_delivery_service.mark_dead_lettered(
                        session, [delivery_id], error_reason=skip_reason,
                    )
                else:
                    await notification_delivery_service.mark_delivery_ids_skipped(
                        session, [delivery_id], error_reason=skip_reason,
                    )
                await session.commit()
                task_log.info(f"Delivery {delivery_id} skipped: {skip_reason}")
                return {"status": "skipped", "reason": skip_reason, "delivery_id": delivery_id}

            # 4b. Check quota (D1) — external channels, fail fast
            if delivery.channel in ("zalo", "sms"):
                from app.services import notification_quota_service
                quota_provider = "zalo_zns" if delivery.channel == "zalo" else "default"
                quota_ok = await notification_quota_service.check_quota(
                    session, delivery.channel, provider=quota_provider
                )
                if not quota_ok:
                    next_retry = _calculate_next_retry(delivery.attempt_count or 0)
                    from app.services import notification_delivery_service as nds
                    await nds.mark_for_retry(
                        session, delivery_id,
                        next_retry_at=next_retry,
                        error_reason="quota_exhausted",
                        increment_attempt=True,
                    )
                    await session.commit()
                    task_log.warning(
                        f"Delivery {delivery_id} deferred — {delivery.channel} quota exhausted"
                    )
                    return {"status": "retry_scheduled", "delivery_id": delivery_id}

            # 4c. Check circuit breaker (D2)
            from app.services import notification_circuit_breaker
            breaker_ok = await notification_circuit_breaker.check_channel_health(delivery.channel)
            if not breaker_ok:
                next_retry = _calculate_next_retry(delivery.attempt_count or 0)
                from app.services import notification_delivery_service as nds2
                await nds2.mark_for_retry(
                    session, delivery_id,
                    next_retry_at=next_retry,
                    error_reason="circuit_breaker_open",
                    increment_attempt=True,
                )
                await session.commit()
                task_log.warning(
                    f"Delivery {delivery_id} deferred — {delivery.channel} breaker open"
                )
                return {"status": "retry_scheduled", "delivery_id": delivery_id}

            # 5. Get channel adapter
            channel = get_channel(delivery.channel)
            if channel is None:
                await notification_delivery_service.mark_dead_lettered(
                    session, [delivery_id],
                    error_reason="channel_not_implemented",
                )
                await session.commit()
                return {"status": "dead_lettered", "reason": "channel_not_implemented", "delivery_id": delivery_id}

            # Update attempt tracking
            delivery.attempt_count = (delivery.attempt_count or 0) + 1
            delivery.last_attempt_at = now
            await session.flush()

            # 6. Execute (M4: try-finally for symmetric breaker recording)
            error_msg = None  # M3: explicit init instead of 'in dir()'
            try:
                result = await channel.execute_delivery(delivery, session)
            except NotImplementedError:
                await notification_delivery_service.mark_dead_lettered(
                    session, [delivery_id],
                    error_reason="execute_delivery_not_supported",
                )
                await session.commit()
                return {"status": "dead_lettered", "reason": "not_supported", "delivery_id": delivery_id}
            except Exception as e:
                # Unexpected exception — treat as transient
                error_msg = f"Unexpected error: {str(e)}"
                task_log.error(f"Delivery {delivery_id} exception: {e}", exc_info=True)
                result = None  # Will be handled in failure path below

            # 7. Process result
            if result and result.success:
                await notification_delivery_service.mark_delivery_ids_sent(
                    session, [delivery_id],
                )
                if result.provider_message_id:
                    delivery.provider_message_id = result.provider_message_id
                    await session.flush()

                # D1: Record send for quota tracking
                if delivery.channel in ("zalo", "sms"):
                    from app.services import notification_quota_service
                    quota_provider = "zalo_zns" if delivery.channel == "zalo" else "default"
                    await notification_quota_service.record_send(
                        session, delivery.channel, provider=quota_provider
                    )

                # D2: Record success for circuit breaker
                try:
                    await notification_circuit_breaker.record_success(delivery.channel)
                except Exception as breaker_err:
                    task_log.warning(f"Breaker record_success failed: {breaker_err}")

                await session.commit()
                task_log.info(f"Delivery {delivery_id} sent via {delivery.channel}")
                return {"status": "sent", "delivery_id": delivery_id, "channel": delivery.channel}

            # --- Failure path ---
            # D2: Record failure for circuit breaker (M4: wrapped in try)
            try:
                await notification_circuit_breaker.record_failure(delivery.channel)
            except Exception as breaker_err:
                task_log.warning(f"Breaker record_failure failed: {breaker_err}")

            error_reason = ""
            if result:
                error_reason = result.error_message or "delivery_failed"
            else:
                error_reason = error_msg or "unknown_error"

            if _is_permanent_error(error_reason):
                # Permanent failure → dead-letter immediately
                await notification_delivery_service.mark_dead_lettered(
                    session, [delivery_id], error_reason=error_reason,
                )
                await session.commit()
                task_log.warning(f"Delivery {delivery_id} dead-lettered: {error_reason}")
                return {"status": "dead_lettered", "delivery_id": delivery_id}

            # Transient failure → retry with backoff or dead-letter if max exceeded
            max_retries = delivery.max_retries or 5
            if delivery.attempt_count >= max_retries:
                await notification_delivery_service.mark_dead_lettered(
                    session, [delivery_id],
                    error_reason=f"max_retries_exceeded ({max_retries}): {error_reason}",
                )
                await session.commit()
                task_log.warning(
                    f"Delivery {delivery_id} dead-lettered after {delivery.attempt_count} attempts"
                )
                return {"status": "dead_lettered", "delivery_id": delivery_id}

            # Schedule retry
            next_retry = _calculate_next_retry(delivery.attempt_count)
            await notification_delivery_service.mark_for_retry(
                session, delivery_id,
                next_retry_at=next_retry,
                error_reason=error_reason,
            )
            await session.commit()
            task_log.info(
                f"Delivery {delivery_id} failed, retry scheduled at {next_retry.isoformat()} "
                f"(attempt {delivery.attempt_count}/{max_retries})"
            )
            return {"status": "retry_scheduled", "delivery_id": delivery_id}

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["status", "delivery_id"],
    )
    return result


# =============================================================================
# Sweep task: pick up deliveries ready for retry
# =============================================================================

@celery_app.task(
    name="sweep_retry_deliveries",
    bind=True,
    max_retries=0,
)
def sweep_retry_deliveries(self):
    """
    Celery Beat task: find deliveries with next_retry_at <= now and enqueue them.

    Runs every 2 minutes. Uses distributed lock to prevent concurrent sweeps.
    """
    task_name = "sweep_retry_deliveries"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting retry sweep...")

    async def _run():
        from app.utils.redis_lock import acquire_redis_lock
        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

        async with acquire_redis_lock("sweep_retry_deliveries", timeout=120) as acquired:
            if not acquired:
                task_log.info("Sweep lock held by another worker, skipping")
                return {"enqueued": 0, "skipped_lock": True}

            async with task_db_session() as session:
                repo = NotificationDeliveryRepository(session)
                ready = await repo.find_ready_for_retry(limit=100)

                if not ready:
                    return {"enqueued": 0}

                enqueued = 0
                for delivery in ready:
                    execute_notification_delivery.apply_async(args=[delivery.id])
                    enqueued += 1

                task_log.info(f"Sweep enqueued {enqueued} deliveries for retry")
                return {"enqueued": enqueued}

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["enqueued"],
    )
    return result


# =============================================================================
# Reconciliation: stale delivery cleanup
# =============================================================================

@celery_app.task(
    name="reconcile_stale_deliveries",
    bind=True,
    max_retries=0,
)
def reconcile_stale_deliveries(self):
    """
    Celery Beat task: find and resolve stale deliveries.

    1. Queued stale (external channels, >30min): re-enqueue or dead-letter
    2. Sent stale (external channels, >60min, no webhook): mark as delivered (assume success)

    Runs every 15 minutes with distributed lock.
    """
    task_name = "reconcile_stale_deliveries"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting delivery reconciliation...")

    async def _run():
        from app.utils.redis_lock import acquire_redis_lock
        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        from app.services import notification_delivery_service

        async with acquire_redis_lock("reconcile_stale_deliveries", timeout=300) as acquired:
            if not acquired:
                return {"queued_resolved": 0, "sent_resolved": 0, "skipped_lock": True}

            async with task_db_session() as session:
                repo = NotificationDeliveryRepository(session)
                queued_resolved = 0
                sent_resolved = 0

                # 1. Queued stale: external channels stuck >30min
                stale_queued = await repo.find_stale_deliveries(
                    status="queued",
                    channels=["email", "zalo", "sms"],
                    max_age_minutes=30,
                    limit=50,
                )
                for delivery in stale_queued:
                    max_retries = delivery.max_retries or 5
                    if (delivery.attempt_count or 0) >= max_retries:
                        await notification_delivery_service.mark_dead_lettered(
                            session, [delivery.id],
                            error_reason="reconcile: queued_stale_max_retries",
                        )
                    else:
                        execute_notification_delivery.apply_async(args=[delivery.id])
                    queued_resolved += 1

                # 2. Sent stale: external channels sent >60min without webhook confirm
                stale_sent = await repo.find_stale_deliveries(
                    status="sent",
                    channels=["zalo", "sms"],
                    max_age_minutes=60,
                    limit=50,
                )
                for delivery in stale_sent:
                    # Assume delivered if no negative callback after 60min
                    await notification_delivery_service.mark_delivery_ids_delivered(
                        session, [delivery.id],
                    )
                    sent_resolved += 1

                if queued_resolved or sent_resolved:
                    await session.commit()

                task_log.info(
                    f"Reconciliation done: {queued_resolved} queued, {sent_resolved} sent resolved"
                )
                return {"queued_resolved": queued_resolved, "sent_resolved": sent_resolved}

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["queued_resolved", "sent_resolved"],
    )
    return result


# =============================================================================
# Eligibility check (shared by execute task)
# =============================================================================

# _check_delivery_eligibility moved to notification_delivery_service.py (M10 fix)


# =============================================================================
# D1: Quota sync task
# =============================================================================

@celery_app.task(
    name="sync_notification_quotas",
    bind=True,
    max_retries=0,
)
def sync_notification_quotas(self):
    """
    Celery Beat task: sync quota records (create today's row if missing).

    Runs every 6 hours. Ensures daily quota rows exist for configured channels.
    """
    task_name = "sync_notification_quotas"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting quota sync...")

    async def _run():
        from datetime import date as date_type
        from app.utils.redis_lock import acquire_redis_lock
        from app.repositories.notification_quota_repository import NotificationQuotaRepository
        from app.config import settings

        async with acquire_redis_lock("sync_notification_quotas", timeout=60) as acquired:
            if not acquired:
                return {"synced": 0, "skipped_lock": True}

            async with task_db_session() as session:
                repo = NotificationQuotaRepository(session)
                today = date_type.today()
                synced = 0

                # Ensure Zalo quota row exists for today
                zalo_quota = await repo.get_current_quota(
                    "zalo", "zalo_zns", "daily", today,
                )
                if zalo_quota is None and settings.ZALO_ENABLED:
                    await repo.upsert_quota(
                        channel="zalo",
                        provider="zalo_zns",
                        period="daily",
                        period_start=today,
                        quota_limit=settings.ZALO_DAILY_QUOTA_LIMIT,
                    )
                    synced += 1
                    await session.commit()

                task_log.info(f"Quota sync done: {synced} rows created")
                return {"synced": synced}

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["synced"],
    )
    return result


# =============================================================================
# D3: Alert check task
# =============================================================================

@celery_app.task(
    name="check_notification_alerts",
    bind=True,
    max_retries=0,
)
def check_notification_alerts(self):
    """
    Celery Beat task: run all notification alert checks.

    Runs every 5 minutes. Dispatches SYSTEM_ALERT for any fired alerts.
    Redis dedup prevents alert storms (same alert type within 1 hour).
    """
    task_name = "check_notification_alerts"
    task_log = logging.getLogger(task_name)
    task_log.info("Running notification alert checks...")

    async def _run():
        from app.services.notification_alert_service import run_all_checks

        async with task_db_session() as session:
            alerts = await run_all_checks(session)

            if not alerts:
                return {"fired": 0}

            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents

            for alert in alerts:
                try:
                    await safe_dispatch(
                        db=session,
                        event=SystemEvents.SYSTEM_ALERT,
                        payload={
                            "severity": alert.get("severity", "warning"),
                            "message": alert["message"],
                        },
                    )
                except Exception as e:
                    task_log.error(f"Failed to dispatch alert: {e}")

            await session.commit()
            task_log.info(f"Notification alerts fired: {len(alerts)}")
            return {"fired": len(alerts), "types": [a["alert_type"] for a in alerts]}

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["fired"],
    )
    return result
