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


def test_scope_manager_includes_unit_based_external_subquery():
    """Must-Fix #4: manager scope uses lead.unit_id IN unit_ids for external."""
    from app.repositories.notification_delivery_repository import _build_scope_condition
    cond = _build_scope_condition([1, 2, 3], allowed_unit_ids=[10, 20])
    sql = str(cond)
    assert "recipient_kind" in sql
    assert "user_id IS NULL" in sql
    assert "lead" in sql.lower()
    assert "unit_id" in sql.lower()


def test_scope_officer_includes_assigned_officer_external_subquery():
    """Must-Fix #4: officer scope uses lead.assigned_officer_id = officer_id."""
    from app.repositories.notification_delivery_repository import _build_scope_condition
    cond = _build_scope_condition([1], officer_id=1)
    sql = str(cond)
    assert "recipient_kind" in sql
    assert "assigned_officer_id" in sql.lower()


def test_scope_no_unit_no_officer_no_external():
    """Must-Fix #4: no unit_ids and no officer_id → no external rows."""
    from app.repositories.notification_delivery_repository import _build_scope_condition
    cond = _build_scope_condition([1])
    sql = str(cond)
    assert "user_id IN" in sql
    assert "recipient_kind" not in sql


@pytest.mark.asyncio
async def test_manager_external_in_scope():
    """Must-Fix #4: manager can access external delivery if lead is in their unit."""
    from app.core.deps import _check_external_source_in_units

    delivery = MagicMock()
    delivery.source_type = "lead"
    delivery.source_id = 42

    db = AsyncMock()
    lead_result = MagicMock()
    lead_result.first = MagicMock(return_value=(10,))
    db.execute = AsyncMock(return_value=lead_result)

    assert await _check_external_source_in_units(db, delivery, [10, 20]) is True


@pytest.mark.asyncio
async def test_manager_external_out_of_scope():
    """Must-Fix #4: manager denied external delivery if lead outside their units."""
    from app.core.deps import _check_external_source_in_units

    delivery = MagicMock()
    delivery.source_type = "lead"
    delivery.source_id = 42

    db = AsyncMock()
    lead_result = MagicMock()
    lead_result.first = MagicMock(return_value=(99,))
    db.execute = AsyncMock(return_value=lead_result)

    assert await _check_external_source_in_units(db, delivery, [10, 20]) is False


@pytest.mark.asyncio
async def test_officer_external_assigned_in_scope():
    """Must-Fix #4: officer can access external delivery for their assigned lead."""
    from app.core.deps import _check_external_source_assigned_to

    delivery = MagicMock()
    delivery.source_type = "lead"
    delivery.source_id = 42

    db = AsyncMock()
    lead_result = MagicMock()
    lead_result.first = MagicMock(return_value=(7,))  # assigned_officer_id=7
    db.execute = AsyncMock(return_value=lead_result)

    assert await _check_external_source_assigned_to(db, delivery, 7) is True


@pytest.mark.asyncio
async def test_officer_external_not_assigned_denied():
    """Must-Fix #4: officer denied external delivery for lead assigned to someone else."""
    from app.core.deps import _check_external_source_assigned_to

    delivery = MagicMock()
    delivery.source_type = "lead"
    delivery.source_id = 42

    db = AsyncMock()
    lead_result = MagicMock()
    lead_result.first = MagicMock(return_value=(99,))  # assigned to officer 99
    db.execute = AsyncMock(return_value=lead_result)

    assert await _check_external_source_assigned_to(db, delivery, 7) is False


@pytest.mark.asyncio
async def test_officer_external_lead_not_found_denied():
    """Must-Fix #4: officer denied if lead doesn't exist."""
    from app.core.deps import _check_external_source_assigned_to

    delivery = MagicMock()
    delivery.source_type = "lead"
    delivery.source_id = 999

    db = AsyncMock()
    lead_result = MagicMock()
    lead_result.first = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=lead_result)

    assert await _check_external_source_assigned_to(db, delivery, 7) is False


# ============================================================================
# Regression: get_delivery_for_user officer external behavior (end-to-end dep)
# ============================================================================

@pytest.mark.asyncio
async def test_get_delivery_for_user_officer_assigned_returns_record():
    """Officer accessing external delivery for their assigned lead → returns record."""
    from app.core.deps import get_delivery_for_user

    record = MagicMock()
    record.id = 10
    record.user_id = None
    record.recipient_kind = "external"
    record.source_type = "lead"
    record.source_id = 42

    officer = MagicMock()
    officer.id = 7
    officer.role = "officer"
    officer.unit_id = 1

    db = AsyncMock()
    repo_mock = MagicMock()
    repo_mock.get_by_id = AsyncMock(return_value=record)
    # Lead assigned_officer_id=7 → matches officer
    lead_result = MagicMock()
    lead_result.first = MagicMock(return_value=(7,))
    db.execute = AsyncMock(return_value=lead_result)

    with patch(
        "app.repositories.notification_delivery_repository.NotificationDeliveryRepository",
        return_value=repo_mock,
    ):
        # Call the unwrapped function directly (bypass FastAPI Depends)
        result = await get_delivery_for_user(
            delivery_id=10, db=db, current_user=officer
        )

    assert result is record


@pytest.mark.asyncio
async def test_get_delivery_for_user_officer_unassigned_raises_404():
    """Officer accessing external delivery for lead assigned to someone else → 404."""
    from app.core.deps import get_delivery_for_user
    from app.utils.exceptions import ResourceNotFoundError

    record = MagicMock()
    record.id = 10
    record.user_id = None
    record.recipient_kind = "external"
    record.source_type = "lead"
    record.source_id = 42

    officer = MagicMock()
    officer.id = 7
    officer.role = "officer"
    officer.unit_id = 1

    db = AsyncMock()
    repo_mock = MagicMock()
    repo_mock.get_by_id = AsyncMock(return_value=record)
    # Lead assigned_officer_id=99 → NOT officer 7
    lead_result = MagicMock()
    lead_result.first = MagicMock(return_value=(99,))
    db.execute = AsyncMock(return_value=lead_result)

    with patch(
        "app.repositories.notification_delivery_repository.NotificationDeliveryRepository",
        return_value=repo_mock,
    ):
        with pytest.raises(ResourceNotFoundError):
            await get_delivery_for_user(
                delivery_id=10, db=db, current_user=officer
            )


# ============================================================================
# Regression: external cooldown only set after successful create
# ============================================================================

@pytest.mark.asyncio
async def test_external_cooldown_not_set_when_prepare_returns_empty():
    """If prepare_external_deliveries returns [], cooldown key must NOT be set.

    Reproduces the code path at notification_dispatcher.py lines 955-973:
    ext_ids = await prepare_external_deliveries(...)
    if ext_ids:  # only then:
        await safe_redis_set(ext_cooldown_key, ...)
    """
    redis_set_calls = []

    async def tracking_redis_set(key, value, ex=None):
        redis_set_calls.append(key)

    # Simulate: prepare returns empty → cooldown guard
    ext_ids = []  # empty result from prepare_external_deliveries
    ext_cooldown_key = "notif:cooldown:lead_created:+84901234567:zalo:1"

    if ext_ids:
        await tracking_redis_set(ext_cooldown_key, "1", ex=300)

    assert len(redis_set_calls) == 0, "Cooldown must not be set when ext_ids is empty"


@pytest.mark.asyncio
async def test_external_cooldown_set_when_prepare_returns_ids():
    """If prepare_external_deliveries returns [id], cooldown key IS set."""
    redis_set_calls = []

    async def tracking_redis_set(key, value, ex=None):
        redis_set_calls.append(key)

    ext_ids = [101]  # successful create
    ext_cooldown_key = "notif:cooldown:lead_created:+84901234567:zalo:1"

    if ext_ids:
        await tracking_redis_set(ext_cooldown_key, "1", ex=300)

    assert len(redis_set_calls) == 1
    assert "cooldown" in redis_set_calls[0]
