from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_zalo_quota_check_and_record_use_zalo_zns_provider():
    """B2 fix: check_quota and record_send for zalo channel use 'zalo_zns' provider,
    matching sync_zalo_quota. Previously they used 'default', creating two DB rows."""
    from app.services.notification_quota_service import (
        check_quota,
        record_send,
        sync_zalo_quota,
    )

    mock_db = AsyncMock()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    existing_quota = MagicMock()
    existing_quota.quota_used = 10
    existing_quota.quota_limit = 500

    incremented_quota = MagicMock()
    incremented_quota.quota_used = 11
    incremented_quota.quota_limit = 500

    with patch(
        "app.services.notification_quota_service.NotificationQuotaRepository"
    ) as MockRepo, patch(
        "app.services.notification_quota_service.database"
    ) as mock_database, patch(
        "app.services.notification_quota_service.settings"
    ) as mock_settings:
        mock_settings.ZALO_DAILY_QUOTA_LIMIT = 500
        mock_database.get_redis = AsyncMock(return_value=mock_redis)

        repo = AsyncMock()
        repo.is_over_quota = AsyncMock(return_value=False)
        repo.get_current_quota = AsyncMock(return_value=existing_quota)
        repo.increment_used = AsyncMock(return_value=incremented_quota)
        MockRepo.return_value = repo

        # All three operations should use "zalo_zns" provider for zalo channel
        await check_quota(mock_db, "zalo", provider="zalo_zns")
        await record_send(mock_db, "zalo", provider="zalo_zns")
        await sync_zalo_quota(mock_db, quota_remaining=350)

    # All use same provider "zalo_zns" — no more mismatch
    assert repo.is_over_quota.await_args.args[1] == "zalo_zns"
    assert repo.get_current_quota.await_args.args[1] == "zalo_zns"
    assert repo.increment_used.await_args.args[1] == "zalo_zns"
    assert repo.upsert_quota.await_args.kwargs["provider"] == "zalo_zns"


def test_delivery_failure_increments_attempt_count_exactly_once():
    """B1 fix: Single transient failure increments attempt_count from 0 to 1, not 2.
    Previously line 190 incremented before execution AND mark_for_retry incremented again."""
    from app.services.notification_channels.base import ChannelResult
    from app.tasks.delivery_tasks import execute_notification_delivery

    delivery = MagicMock()
    delivery.id = 1
    delivery.status = "queued"
    delivery.channel = "email"
    delivery.attempt_count = 0
    delivery.max_retries = 5
    delivery.scheduled_for = None
    delivery.recipient_kind = "internal"
    delivery.user_id = 101
    delivery.event = "LEAD_ASSIGNED"
    delivery.source_type = None
    delivery.source_id = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=delivery)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_task_db_session():
        yield session

    channel = MagicMock()
    channel.execute_delivery = AsyncMock(
        return_value=ChannelResult(
            success=False,
            sent_count=0,
            failed_ids=[delivery.user_id],
            error_message="timeout",
            delivery_id=delivery.id,
        )
    )

    with patch(
        "app.tasks.delivery_tasks.task_db_session", fake_task_db_session
    ), patch(
        "app.services.notification_delivery_service.check_delivery_eligibility",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.notification_channels.get_channel", return_value=channel
    ), patch(
        "app.services.notification_circuit_breaker.check_channel_health",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.notification_circuit_breaker.record_failure",
        new=AsyncMock(),
    ):
        result = execute_notification_delivery.run(1)

    assert result["status"] == "retry_scheduled"
    # B1 fix: exactly 1, not 2
    assert delivery.attempt_count == 1


def test_quota_exhausted_at_max_retries_dead_letters():
    """Must-Fix #2: quota_exhausted at max_retries → dead_lettered, not retry."""
    from app.tasks.delivery_tasks import execute_notification_delivery

    delivery = MagicMock()
    delivery.id = 1
    delivery.status = "failed"
    delivery.channel = "zalo"
    delivery.attempt_count = 5  # already at max
    delivery.max_retries = 5
    delivery.scheduled_for = None
    delivery.recipient_kind = "external"
    delivery.user_id = None
    delivery.event = "LEAD_CREATED"
    delivery.source_type = None
    delivery.source_id = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=delivery)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_task_db_session():
        yield session

    with patch(
        "app.tasks.delivery_tasks.task_db_session", fake_task_db_session
    ), patch(
        "app.services.notification_delivery_service.check_delivery_eligibility",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.notification_quota_service.check_quota",
        new=AsyncMock(return_value=False),  # quota exhausted
    ), patch(
        "app.services.notification_delivery_service.mark_dead_lettered",
        new=AsyncMock(return_value=1),
    ) as mock_dead_letter:
        result = execute_notification_delivery.run(1)

    assert result["status"] == "dead_lettered"


def test_circuit_breaker_open_at_max_retries_dead_letters():
    """Must-Fix #2: circuit_breaker_open at max_retries → dead_lettered."""
    from app.tasks.delivery_tasks import execute_notification_delivery

    delivery = MagicMock()
    delivery.id = 1
    delivery.status = "failed"
    delivery.channel = "email"
    delivery.attempt_count = 5  # already at max
    delivery.max_retries = 5
    delivery.scheduled_for = None
    delivery.recipient_kind = "internal"
    delivery.user_id = 101
    delivery.event = "LEAD_ASSIGNED"
    delivery.source_type = None
    delivery.source_id = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=delivery)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_task_db_session():
        yield session

    with patch(
        "app.tasks.delivery_tasks.task_db_session", fake_task_db_session
    ), patch(
        "app.services.notification_delivery_service.check_delivery_eligibility",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.notification_circuit_breaker.check_channel_health",
        new=AsyncMock(return_value=False),  # breaker open
    ), patch(
        "app.services.notification_delivery_service.mark_dead_lettered",
        new=AsyncMock(return_value=1),
    ):
        result = execute_notification_delivery.run(1)

    assert result["status"] == "dead_lettered"


def test_quota_exhausted_deferral_increments_attempt_count():
    """Pre-execution deferral: quota_exhausted must increment attempt_count
    so backoff progresses and max_retries is eventually reached."""
    from app.tasks.delivery_tasks import execute_notification_delivery

    delivery = MagicMock()
    delivery.id = 1
    delivery.status = "queued"
    delivery.channel = "zalo"
    delivery.attempt_count = 0
    delivery.max_retries = 5
    delivery.scheduled_for = None
    delivery.recipient_kind = "external"
    delivery.user_id = None
    delivery.event = "LEAD_CREATED"
    delivery.source_type = None
    delivery.source_id = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=delivery)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_task_db_session():
        yield session

    with patch(
        "app.tasks.delivery_tasks.task_db_session", fake_task_db_session
    ), patch(
        "app.services.notification_delivery_service.check_delivery_eligibility",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.notification_quota_service.check_quota",
        new=AsyncMock(return_value=False),  # quota exhausted
    ):
        result = execute_notification_delivery.run(1)

    assert result["status"] == "retry_scheduled"
    assert delivery.attempt_count == 1


def test_circuit_breaker_open_deferral_increments_attempt_count():
    """Pre-execution deferral: circuit_breaker_open must increment attempt_count
    so backoff progresses and max_retries is eventually reached."""
    from app.tasks.delivery_tasks import execute_notification_delivery

    delivery = MagicMock()
    delivery.id = 1
    delivery.status = "queued"
    delivery.channel = "email"
    delivery.attempt_count = 0
    delivery.max_retries = 5
    delivery.scheduled_for = None
    delivery.recipient_kind = "internal"
    delivery.user_id = 101
    delivery.event = "LEAD_ASSIGNED"
    delivery.source_type = None
    delivery.source_id = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=delivery)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_task_db_session():
        yield session

    with patch(
        "app.tasks.delivery_tasks.task_db_session", fake_task_db_session
    ), patch(
        "app.services.notification_delivery_service.check_delivery_eligibility",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.notification_circuit_breaker.check_channel_health",
        new=AsyncMock(return_value=False),  # breaker open
    ):
        result = execute_notification_delivery.run(1)

    assert result["status"] == "retry_scheduled"
    assert delivery.attempt_count == 1


def test_zalo_worker_passes_zalo_zns_provider_for_quota():
    """B2 fix at worker level: delivery_tasks passes provider='zalo_zns' for zalo channel
    to both check_quota and record_send."""
    from app.services.notification_channels.base import ChannelResult
    from app.tasks.delivery_tasks import execute_notification_delivery

    delivery = MagicMock()
    delivery.id = 1
    delivery.status = "queued"
    delivery.channel = "zalo"
    delivery.attempt_count = 0
    delivery.max_retries = 5
    delivery.scheduled_for = None
    delivery.recipient_kind = "external"
    delivery.user_id = None
    delivery.event = "LEAD_CREATED"
    delivery.source_type = "lead"
    delivery.source_id = 10

    session = AsyncMock()
    session.get = AsyncMock(return_value=delivery)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_task_db_session():
        yield session

    channel = MagicMock()
    channel.execute_delivery = AsyncMock(
        return_value=ChannelResult(
            success=True,
            sent_count=1,
            failed_ids=[],
            error_message=None,
            delivery_id=delivery.id,
            provider_message_id="zalo-msg-123",
        )
    )

    mock_check_quota = AsyncMock(return_value=True)
    mock_record_send = AsyncMock()

    with patch(
        "app.tasks.delivery_tasks.task_db_session", fake_task_db_session
    ), patch(
        "app.services.notification_delivery_service.check_delivery_eligibility",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.notification_channels.get_channel", return_value=channel
    ), patch(
        "app.services.notification_circuit_breaker.check_channel_health",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.notification_circuit_breaker.record_success",
        new=AsyncMock(),
    ), patch(
        "app.services.notification_quota_service.check_quota", mock_check_quota
    ), patch(
        "app.services.notification_quota_service.record_send", mock_record_send
    ):
        result = execute_notification_delivery.run(1)

    assert result["status"] == "sent"
    # B2 fix: both calls use "zalo_zns" provider
    mock_check_quota.assert_awaited_once_with(session, "zalo", provider="zalo_zns")
    mock_record_send.assert_awaited_once_with(session, "zalo", provider="zalo_zns")


def test_retry_sweep_clears_next_retry_at_and_commits():
    """B3 fix: sweep clears next_retry_at for enqueued rows AND commits the
    transaction, so the change persists and next sweep won't re-discover them."""
    from app.tasks.delivery_tasks import sweep_retry_deliveries

    delivery = MagicMock()
    delivery.id = 42

    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    repo = MagicMock()
    repo.find_ready_for_retry = AsyncMock(return_value=[delivery])

    @asynccontextmanager
    async def fake_lock(*args, **kwargs):
        yield True

    @asynccontextmanager
    async def fake_task_db_session():
        yield session

    with patch(
        "app.utils.redis_lock.acquire_redis_lock", fake_lock
    ), patch(
        "app.tasks.delivery_tasks.task_db_session", fake_task_db_session
    ), patch(
        "app.repositories.notification_delivery_repository.NotificationDeliveryRepository",
        return_value=repo,
    ), patch(
        "app.tasks.delivery_tasks.execute_notification_delivery.apply_async"
    ) as mock_apply_async:
        result = sweep_retry_deliveries.run()

    assert result["enqueued"] == 1
    assert mock_apply_async.call_count == 1

    # Verify UPDATE was issued to clear next_retry_at
    update_calls = [
        c for c in session.execute.await_args_list
        if "UPDATE" in str(c.args[0]) or "update" in str(type(c.args[0]).__name__.lower())
    ]
    assert len(update_calls) >= 1

    # Critical: commit() must be called to persist the change
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_webhook_msg_id_direct_hit():
    """msg_id lookup succeeds on first query — no fallback needed."""
    from app.routers.zalo_webhooks import _handle_delivery_status

    delivery = MagicMock()
    delivery.id = 42
    delivery.status = "sent"

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=delivery)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    await _handle_delivery_status(db, {
        "msg_id": "provider-msg-1",
        "tracking_id": "delivery_42",
        "status": "sent",
        "error": 0,
    })

    # Only 1 query (msg_id hit), then commit
    assert db.execute.await_count == 1
    assert db.commit.await_count == 1
    assert delivery.status == "delivered"


@pytest.mark.asyncio
async def test_webhook_msg_id_miss_falls_back_to_tracking_id():
    """msg_id lookup misses → fallback to tracking_id succeeds + persists msg_id."""
    from app.routers.zalo_webhooks import _handle_delivery_status

    delivery = MagicMock()
    delivery.id = 42
    delivery.status = "queued"

    # First query (msg_id) returns None, second (tracking_id) returns delivery
    result_miss = MagicMock()
    result_miss.scalar_one_or_none = MagicMock(return_value=None)
    result_hit = MagicMock()
    result_hit.scalar_one_or_none = MagicMock(return_value=delivery)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result_miss, result_hit])
    db.commit = AsyncMock()

    await _handle_delivery_status(db, {
        "msg_id": "provider-msg-1",
        "tracking_id": "delivery_42",
        "status": "sent",
        "error": 0,
    })

    # Two queries: msg_id miss + tracking_id hit
    assert db.execute.await_count == 2
    assert db.commit.await_count == 1
    # Delivery updated
    assert delivery.status == "sent"
    # msg_id persisted via fallback path
    assert delivery.provider_message_id == "provider-msg-1"


@pytest.mark.asyncio
async def test_webhook_msg_id_miss_invalid_tracking_id_no_update():
    """msg_id lookup misses + tracking_id invalid → no delivery update."""
    from app.routers.zalo_webhooks import _handle_delivery_status

    db = AsyncMock()
    result_miss = MagicMock()
    result_miss.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=result_miss)
    db.commit = AsyncMock()

    await _handle_delivery_status(db, {
        "msg_id": "provider-msg-1",
        "tracking_id": "not-a-delivery-id",
        "status": "sent",
        "error": 0,
    })

    # Only 1 query (msg_id), no fallback (tracking_id format invalid)
    assert db.execute.await_count == 1
    assert db.commit.await_count == 0


@pytest.mark.asyncio
async def test_stale_queued_uses_created_at():
    """B5: queued stale path continues to age by created_at (default)."""
    from app.repositories.notification_delivery_repository import (
        NotificationDeliveryRepository,
    )

    db = AsyncMock()
    result = MagicMock()
    result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    db.execute = AsyncMock(return_value=result)

    repo = NotificationDeliveryRepository(db)
    await repo.find_stale_deliveries(
        status="queued",
        channels=["email", "zalo", "sms"],
        max_age_minutes=30,
    )

    where_sql = str(db.execute.await_args.args[0].whereclause)
    assert "notification_delivery.created_at" in where_sql
    assert "notification_delivery.sent_at" not in where_sql


@pytest.mark.asyncio
async def test_stale_sent_uses_sent_at():
    """B5 fix: sent stale path ages by sent_at, not created_at."""
    from app.repositories.notification_delivery_repository import (
        NotificationDeliveryRepository,
    )

    db = AsyncMock()
    result = MagicMock()
    result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    db.execute = AsyncMock(return_value=result)

    repo = NotificationDeliveryRepository(db)
    await repo.find_stale_deliveries(
        status="sent",
        channels=["zalo", "sms"],
        max_age_minutes=60,
        age_column="sent_at",
    )

    where_sql = str(db.execute.await_args.args[0].whereclause)
    assert "notification_delivery.sent_at" in where_sql
    assert "notification_delivery.created_at" not in where_sql


def test_scope_condition_includes_external_rows():
    """Must-Fix #4: scoped queries must include external rows (user_id=NULL)."""
    from app.repositories.notification_delivery_repository import _build_scope_condition
    cond = _build_scope_condition([1, 2, 3])
    sql = str(cond)
    # Must include OR condition for external rows (bind param, not literal)
    assert "recipient_kind" in sql
    assert "user_id IS NULL" in sql


@pytest.mark.asyncio
async def test_scoped_list_query_includes_external_condition():
    """Must-Fix #4: list_deliveries with allowed_user_ids generates OR clause for external."""
    from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=0)
    list_result = MagicMock()
    list_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute = AsyncMock(side_effect=[count_result, list_result])

    repo = NotificationDeliveryRepository(db)
    await repo.list_deliveries(allowed_user_ids=[1, 2])

    # Check the WHERE clause of the list query (second call)
    where_sql = str(db.execute.await_args_list[1].args[0].whereclause)
    assert "recipient_kind" in where_sql  # external OR branch present
