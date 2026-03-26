# app/tasks/delivery_tasks.py
"""
Phase C1: Celery task for executing notification deliveries.

Non-browser channels (email, zalo, sms) are executed asynchronously via this task.
The dispatcher enqueues one task per delivery_id after DB commit.

Flow:
  1. Load delivery by ID
  2. Check idempotency (skip if not queued)
  3. Re-check scheduled_for (re-enqueue if too early)
  4. Re-check consent/preference (skip if revoked/disabled)
  5. Call channel.execute_delivery(delivery, db)
  6. Update delivery status (sent/failed/skipped)
"""
import logging
from datetime import datetime, timezone

from ..celery_app import celery_app
from .utils import task_db_session, run_async_task


@celery_app.task(
    name="execute_notification_delivery",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def execute_notification_delivery(self, delivery_id: int):
    """
    Execute a single notification delivery.

    Idempotent: skips if delivery.status != 'queued'.
    Supports delayed execution via scheduled_for.
    Re-checks consent and user preference before sending.
    """
    task_name = "execute_notification_delivery"
    task_log = logging.getLogger(task_name)
    task_log.info(f"Executing delivery {delivery_id}")

    async def _run():
        from sqlalchemy import select
        from app.models.notification_delivery import NotificationDelivery
        from app.services.notification_channels import get_channel
        from app.services import notification_delivery_service

        async with task_db_session() as session:
            # 1. Load delivery
            delivery = await session.get(NotificationDelivery, delivery_id)
            if not delivery:
                task_log.warning(f"Delivery {delivery_id} not found")
                return {"status": "not_found", "delivery_id": delivery_id}

            # 2. Idempotency: skip if already processed
            if delivery.status != "queued":
                task_log.info(
                    f"Delivery {delivery_id} already {delivery.status}, skipping"
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

            # 4. Re-check consent (external recipients)
            skip_reason = await _check_delivery_eligibility(
                session, delivery
            )
            if skip_reason:
                task_log.info(
                    f"Delivery {delivery_id} skipped: {skip_reason}"
                )
                await notification_delivery_service.mark_delivery_ids_skipped(
                    session, [delivery_id], error_reason=skip_reason,
                )
                await session.commit()
                return {"status": "skipped", "reason": skip_reason, "delivery_id": delivery_id}

            # 5. Get channel adapter and execute
            channel = get_channel(delivery.channel)
            if channel is None:
                task_log.warning(
                    f"Channel '{delivery.channel}' not implemented, skipping delivery {delivery_id}"
                )
                await notification_delivery_service.mark_delivery_ids_skipped(
                    session, [delivery_id],
                    error_reason="channel_not_implemented",
                )
                await session.commit()
                return {"status": "skipped", "reason": "channel_not_implemented", "delivery_id": delivery_id}

            # Update attempt tracking
            delivery.attempt_count = (delivery.attempt_count or 0) + 1
            delivery.last_attempt_at = now
            await session.flush()

            try:
                result = await channel.execute_delivery(delivery, session)
            except NotImplementedError:
                task_log.warning(
                    f"Channel '{delivery.channel}' does not support execute_delivery, skipping"
                )
                await notification_delivery_service.mark_delivery_ids_skipped(
                    session, [delivery_id],
                    error_reason="execute_delivery_not_supported",
                )
                await session.commit()
                return {"status": "skipped", "reason": "not_supported", "delivery_id": delivery_id}

            # 6. Update delivery status based on result
            if result.success:
                await notification_delivery_service.mark_delivery_ids_sent(
                    session, [delivery_id],
                )
                # Store provider message ID if available (Zalo/SMS)
                if result.provider_message_id:
                    delivery.provider_message_id = result.provider_message_id
                    await session.flush()

                task_log.info(
                    f"Delivery {delivery_id} sent successfully via {delivery.channel}"
                )
            else:
                await notification_delivery_service.mark_delivery_ids_failed(
                    session, [delivery_id],
                    error_reason=result.error_message or "delivery_failed",
                )
                task_log.warning(
                    f"Delivery {delivery_id} failed: {result.error_message}"
                )

            await session.commit()
            return {
                "status": "sent" if result.success else "failed",
                "delivery_id": delivery_id,
                "channel": delivery.channel,
            }

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["status", "delivery_id"],
    )
    return result


async def _check_delivery_eligibility(session, delivery) -> str | None:
    """
    Re-check if delivery should proceed.

    Returns skip reason string if delivery should be skipped, None if OK.

    Checks:
    - External recipients: consent must still be granted
    - Internal recipients: user preference for this channel must be enabled
    """
    # External recipients: check consent
    if delivery.recipient_kind == "external" and delivery.source_type and delivery.source_id:
        from app.repositories.notification_consent_repository import NotificationConsentRepository
        consent_repo = NotificationConsentRepository(session)
        granted = await consent_repo.is_consent_granted(
            channel=delivery.channel,
            source_type=delivery.source_type,
            source_id=delivery.source_id,
        )
        if not granted:
            return "consent_revoked"

    # Internal recipients: check user preference
    if delivery.recipient_kind == "internal" and delivery.user_id:
        from app.services import notification_preference_service
        from app.core.events import SystemEvents
        from app.core.event_groups import get_event_group

        # Convert event string back to SystemEvents enum for group lookup
        try:
            event_enum = SystemEvents(delivery.event)
            group = get_event_group(event_enum)
            filtered = await notification_preference_service.filter_users_by_group(
                db=session,
                user_ids=[delivery.user_id],
                group=group.value,
                channel=delivery.channel,
            )
            if delivery.user_id not in filtered:
                return "preference_disabled"
        except ValueError:
            # Unknown event — skip preference check, let delivery proceed
            pass

    return None
