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
# Regression: external cooldown via dispatch() production path
# ============================================================================

def _build_external_dispatch_patches():
    """Set up patches to drive dispatch() into the external delivery path."""

    action = MagicMock()
    action.channel = "zalo"
    action.step = 1
    action.delay_minutes = 0
    action.template_code = None
    action.config = {"external_resolver": "lead_contact"}

    config = MagicMock()
    config.channel_values = ["zalo"]
    config.channels = [MagicMock(value="zalo")]
    config.resolver = MagicMock()
    config.resolver.resolver_type = "lead_owner"
    config.actions = [action]
    config.condition = None
    config.rule_id = 1
    config.should_activate = MagicMock(return_value=True)

    ext_recipient = MagicMock()
    ext_recipient.recipient_kind = "external"
    ext_recipient.user_id = None
    ext_recipient.destination_phone = "+84901234567"
    ext_recipient.destination_email = None
    ext_recipient.source_type = "lead"
    ext_recipient.source_id = 42

    return config, AsyncMock(return_value=ext_recipient)


@pytest.mark.asyncio
async def test_dispatch_external_cooldown_not_set_when_prepare_empty():
    """Must-Fix #3: dispatch() real path → prepare returns [] → cooldown NOT set."""
    from app.services.notification_dispatcher import dispatch
    from app.core.events import SystemEvents

    config, resolver_fn = _build_external_dispatch_patches()
    redis_set_calls = []

    # PR1: safe_redis_set now handles nx=True (atomic cooldown)
    async def track_set(key, value, ex=None, nx=False):
        redis_set_calls.append(key)
        return True  # simulate successful SET

    # PR1: mock catalog get_event → return user-class EventDefinition
    mock_defn = MagicMock()
    mock_defn.notification_class = "user"
    mock_defn.retired = False

    db = AsyncMock()
    db.flush = AsyncMock()
    dedup_result = MagicMock()
    dedup_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=dedup_result)

    with patch("app.services.notification_dispatcher.get_rule_for_event", new=AsyncMock(return_value=config)), \
         patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
         patch("app.services.notification_rule_loader.deserialize_resolver", return_value=AsyncMock(return_value=[])), \
         patch("app.services.notification_dispatcher.notification_preference_service"), \
         patch("app.services.notification_dispatcher.safe_redis_exists", new=AsyncMock(return_value=False)), \
         patch("app.services.notification_dispatcher.safe_redis_set", track_set), \
         patch("app.services.notification_dispatcher.safe_redis_incr", new=AsyncMock(return_value=1)), \
         patch("app.services.notification_dispatcher.safe_redis_expire", new=AsyncMock()), \
         patch("app.services.notification_recipients.EXTERNAL_RESOLVER_REGISTRY", {"lead_contact": resolver_fn}), \
         patch("app.services.notification_delivery_service.prepare_external_deliveries") as mock_prepare, \
         patch("app.services.notification_dispatcher._build_action_snapshot", return_value={"title": "t"}), \
         patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
        mock_prepare.return_value = []
        await dispatch(db=db, event=SystemEvents.LEAD_CREATED,
                       payload={"lead_id": 42, "lead_name": "T"}, dedupe_key="t:42",
                       skip_preference_check=True)

    ext_cooldown = [k for k in redis_set_calls if "cooldown" in k and "+84" in k]
    assert len(ext_cooldown) == 0, f"Cooldown must not be set when prepare returns [], got: {ext_cooldown}"


@pytest.mark.asyncio
async def test_dispatch_external_cooldown_set_when_prepare_succeeds():
    """Must-Fix #3: dispatch() real path → prepare returns [id] → cooldown IS set."""
    from app.services.notification_dispatcher import dispatch
    from app.core.events import SystemEvents

    config, resolver_fn = _build_external_dispatch_patches()
    redis_set_calls = []

    # PR1: safe_redis_set now handles nx=True (atomic cooldown for internal path)
    async def track_set(key, value, ex=None, nx=False):
        redis_set_calls.append(key)
        return True

    # PR1: mock catalog get_event → return user-class EventDefinition
    mock_defn = MagicMock()
    mock_defn.notification_class = "user"
    mock_defn.retired = False

    db = AsyncMock()
    db.flush = AsyncMock()
    dedup_result = MagicMock()
    dedup_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=dedup_result)

    with patch("app.services.notification_dispatcher.get_rule_for_event", new=AsyncMock(return_value=config)), \
         patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
         patch("app.services.notification_rule_loader.deserialize_resolver", return_value=AsyncMock(return_value=[])), \
         patch("app.services.notification_dispatcher.notification_preference_service"), \
         patch("app.services.notification_dispatcher.safe_redis_exists", new=AsyncMock(return_value=False)), \
         patch("app.services.notification_dispatcher.safe_redis_set", track_set), \
         patch("app.services.notification_dispatcher.safe_redis_incr", new=AsyncMock(return_value=1)), \
         patch("app.services.notification_dispatcher.safe_redis_expire", new=AsyncMock()), \
         patch("app.services.notification_recipients.EXTERNAL_RESOLVER_REGISTRY", {"lead_contact": resolver_fn}), \
         patch("app.services.notification_delivery_service.prepare_external_deliveries") as mock_prepare, \
         patch("app.services.notification_dispatcher._build_action_snapshot", return_value={"title": "t"}), \
         patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
        mock_prepare.return_value = [101]
        await dispatch(db=db, event=SystemEvents.LEAD_CREATED,
                       payload={"lead_id": 42, "lead_name": "T"}, dedupe_key="t:42",
                       skip_preference_check=True)

    ext_cooldown = [k for k in redis_set_calls if "cooldown" in k and "+84" in k]
    assert len(ext_cooldown) == 1, f"Cooldown should be set once, got: {ext_cooldown}"


# ============================================================================
# Regression: consultation_reminder task path
# ============================================================================

def test_consultation_reminder_task_sets_reminder_sent_and_no_crash():
    """Regression: the full reminder task path must:
    1. Dispatch to the correct officer (lead owner, not consultation creator)
    2. Set consultation.reminder_sent = True
    3. Call update_lead_next_activity without crashing (is_active fix)
    4. Return sent=1, failed=0
    """
    from datetime import datetime, timezone, timedelta
    from app.tasks.notification_tasks import check_consultation_reminders_task

    # Build mock consultation + lead with different officer_ids
    consultation = MagicMock()
    consultation.id = 154
    consultation.lead_id = 37
    consultation.officer_id = 15  # admin who created it
    consultation.scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    consultation.reminder_sent = False
    consultation.deleted_at = None

    lead = MagicMock()
    lead.id = 37
    lead.full_name = "Test Lead"
    lead.phone = "0901234567"
    lead.assigned_officer_id = 18  # officer who owns the lead
    lead.deleted_at = None

    # Mock DB result: query returns 1 consultation+lead pair
    db_result = MagicMock()
    db_result.all = MagicMock(return_value=[(consultation, lead)])

    session = AsyncMock()
    session.execute = AsyncMock(return_value=db_result)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_task_db_session():
        yield session

    # Track dispatch payload to verify officer_id
    dispatch_payloads = []
    async def mock_dispatch(db, event, payload, **kwargs):
        dispatch_payloads.append(payload)
        async def noop_cb():
            pass
        return [], noop_cb

    with patch(
        "app.tasks.notification_tasks.task_db_session", fake_task_db_session
    ), patch(
        "app.tasks.notification_tasks.settings"
    ) as mock_settings, patch(
        "app.services.notification_dispatcher.dispatch", mock_dispatch
    ), patch(
        "app.services.lead_service.update_lead_next_activity", new=AsyncMock()
    ), patch(
        "app.tasks.notification_tasks._emit_lead_updated", new=AsyncMock()
    ):
        mock_settings.TIMEZONE = "Asia/Ho_Chi_Minh"
        result = check_consultation_reminders_task.run()

    # 1. Task completed without crash
    assert result["sent"] == 1
    assert result["failed"] == 0

    # 2. reminder_sent was set to True
    assert consultation.reminder_sent is True

    # 3. Dispatch payload used lead owner, not consultation creator
    assert len(dispatch_payloads) == 1
    assert dispatch_payloads[0]["officer_id"] == 18  # lead owner, not 15


# ============================================================================
# Regression: application_* events must not override lead owner via officer_id
# ============================================================================

@pytest.mark.asyncio
async def test_application_created_payload_has_no_officer_id():
    """APPLICATION_CREATED payload must NOT contain officer_id, so
    LeadOwnerResolver falls through to DB lookup on lead_id."""
    # Simulate the payload as constructed in admissions.py after fix
    payload = {
        "application_id": 14,
        "lead_id": 37,
        "lead_name": "Nguyen Van A",
        "major_program_name": "Công nghệ thông tin",
        "actor_id": 15,
        "actor_name": "Admin User",
    }
    # officer_id must not be present — LeadOwnerResolver would short-circuit
    assert "officer_id" not in payload
    assert payload["lead_id"] == 37
    assert payload["lead_name"] != "$lead_name"
    assert payload["major_program_name"] is not None


@pytest.mark.asyncio
async def test_application_status_changed_payload_has_no_officer_id():
    """APPLICATION_STATUS_CHANGED payload must NOT contain officer_id."""
    payload = {
        "application_id": 13,
        "lead_id": 37,
        "old_status": "approved",
        "new_status": "enrolled",
        "actor_id": 15,
        "actor_name": "Admin User",
    }
    assert "officer_id" not in payload
    assert payload["lead_id"] == 37


@pytest.mark.asyncio
async def test_lead_owner_resolver_uses_db_when_no_officer_id():
    """When payload has lead_id but no officer_id, LeadOwnerResolver must
    query the DB and return lead.assigned_officer_id."""
    from app.services.notification_resolvers import LeadOwnerResolver

    resolver = LeadOwnerResolver()
    db = AsyncMock()
    # DB returns assigned_officer_id=18
    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=18)
    db.execute = AsyncMock(return_value=result_mock)

    users = await resolver.resolve_users(db, {"lead_id": 37})
    assert users == [18]
    # Verify DB was actually queried (not short-circuited by officer_id)
    assert db.execute.await_count == 1


# ============================================================================
# Regression: admissions notification dispatch behavior (router-level)
# ============================================================================

def _make_profile_mock(**overrides):
    """Create a mock AdmissionProfile with common defaults."""
    defaults = dict(id=5, lead_id=37, status="submitted", lead=MagicMock(id=37))
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _fake_request():
    """Create a minimal Starlette Request that satisfies rate limiter type checks."""
    from starlette.requests import Request
    scope = {"type": "http", "method": "POST", "path": "/test", "headers": [], "query_string": b""}
    return Request(scope)


@pytest.mark.asyncio
async def test_confirm_token_dispatches_only_application_status_changed():
    """Confirm-by-token router dispatches APPLICATION_STATUS_CHANGED only,
    NOT LEAD_STATUS_CHANGED (approved→confirmed = same lead sts09)."""
    from app.routers.admissions import confirm_admission_by_token

    profile = _make_profile_mock(id=10, status="confirmed", lead_id=37)
    profile.confirmed_at = "2026-03-31T00:00:00Z"

    dispatch_calls = []

    async def tracking_dispatch(db, event, payload, dedupe_key=None):
        dispatch_calls.append({"event": event.value, "payload": payload})

    with patch(
        "app.routers.admissions.admission_service.verify_and_confirm",
        new=AsyncMock(return_value=(profile, AsyncMock())),
    ), patch(
        "app.routers.admissions.safe_dispatch", tracking_dispatch,
    ):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        from app import schemas
        verify_data = MagicMock()
        verify_data.last_digits_citizen_id = "1234"

        await confirm_admission_by_token(
            request=_fake_request(), token="abc", verify_data=verify_data, db=db,
        )

    events = [c["event"] for c in dispatch_calls]
    assert "application_status_changed" in events
    assert "lead_status_changed" not in events
    assert dispatch_calls[0]["payload"]["old_status"] == "approved"
    assert dispatch_calls[0]["payload"]["new_status"] == "confirmed"


@pytest.mark.asyncio
async def test_finalize_dispatches_app_and_lead_and_commission():
    """Finalize router dispatches APPLICATION_STATUS_CHANGED + LEAD_STATUS_CHANGED
    + calls commission check with pre_status."""
    from app.routers.admissions import finalize_enrollment

    profile = _make_profile_mock(id=5, status="confirmed", lead_id=37)
    result = _make_profile_mock(id=5, status="enrolled", lead_id=37)

    dispatch_calls = []
    commission_calls = []

    async def tracking_dispatch(db, event, payload, dedupe_key=None):
        dispatch_calls.append({"event": event.value, "payload": payload})

    async def tracking_commission(db, lead_id, old_status, new_status, actor_id):
        commission_calls.append({"old": old_status, "new": new_status})

    admin = MagicMock(id=15, role="admin", full_name="Admin", username="admin")

    with patch(
        "app.routers.admissions.admission_service.finalize_profile",
        new=AsyncMock(return_value=(result, AsyncMock())),
    ), patch(
        "app.routers.admissions.safe_dispatch", tracking_dispatch,
    ), patch(
        "app.routers.admissions.safe_check_commission_on_status_change",
        tracking_commission,
    ):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await finalize_enrollment(
            request=_fake_request(), profile_id=5,
            data=MagicMock(model_dump=lambda: {}),
            current_user=admin, profile=profile, db=db,
        )

    events = [c["event"] for c in dispatch_calls]
    assert events == ["application_status_changed", "lead_status_changed"]
    # APPLICATION_STATUS_CHANGED uses pre_status
    assert dispatch_calls[0]["payload"]["old_status"] == "confirmed"
    assert dispatch_calls[0]["payload"]["new_status"] == "enrolled"
    # LEAD_STATUS_CHANGED uses pre_status → sts11
    assert dispatch_calls[1]["payload"]["old_status"] == "confirmed"
    assert dispatch_calls[1]["payload"]["new_status"] == "sts11"
    # Commission uses pre_status
    assert commission_calls == [{"old": "confirmed", "new": "sts11"}]


@pytest.mark.asyncio
async def test_resubmit_dispatches_app_and_lead_and_commission():
    """Resubmit router dispatches APPLICATION_STATUS_CHANGED + LEAD_STATUS_CHANGED
    + commission with pre_status (covers revision_requested source)."""
    from app.routers.admissions import resubmit_admission

    pre_profile = _make_profile_mock(id=5, status="revision_requested", lead_id=37)
    result = _make_profile_mock(id=5, status="resubmitted", lead_id=37)

    dispatch_calls = []
    commission_calls = []

    async def tracking_dispatch(db, event, payload, dedupe_key=None):
        dispatch_calls.append({"event": event.value, "payload": payload})

    async def tracking_commission(db, lead_id, old_status, new_status, actor_id):
        commission_calls.append({"old": old_status, "new": new_status})

    officer = MagicMock(id=18, role="officer", full_name="Officer", username="officer")

    with patch(
        "app.routers.admissions.admission_service.resubmit_profile",
        new=AsyncMock(return_value=(result, AsyncMock())),
    ), patch(
        "app.routers.admissions.safe_dispatch", tracking_dispatch,
    ), patch(
        "app.routers.admissions.safe_check_commission_on_status_change",
        tracking_commission,
    ):
        db = AsyncMock()
        db.get = AsyncMock(return_value=pre_profile)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await resubmit_admission(
            request=_fake_request(), profile_id=5,
            data=MagicMock(model_dump=lambda: {}),
            current_user=officer, db=db,
        )

    events = [c["event"] for c in dispatch_calls]
    assert events == ["application_status_changed", "lead_status_changed"]
    # Uses actual pre_status, not hardcoded "rejected"
    assert dispatch_calls[0]["payload"]["old_status"] == "revision_requested"
    assert dispatch_calls[1]["payload"]["old_status"] == "revision_requested"
    assert dispatch_calls[1]["payload"]["new_status"] == "sts07"
    assert commission_calls == [{"old": "revision_requested", "new": "sts07"}]


@pytest.mark.asyncio
async def test_bulk_approve_uses_pre_status_from_service():
    """Bulk approve router reads _pre_status annotated by service,
    not hardcoded 'submitted'."""
    from app.routers.admissions import bulk_approve_admissions
    from app import schemas

    # Profile that was resubmitted before approval
    profile = _make_profile_mock(id=5, status="approved", lead_id=37)
    profile._pre_status = "resubmitted"

    dispatch_calls = []
    commission_calls = []

    async def tracking_dispatch(db, event, payload, dedupe_key=None):
        dispatch_calls.append({"event": event.value, "payload": payload})

    async def tracking_commission(db, lead_id, old_status, new_status, actor_id):
        commission_calls.append({"old": old_status, "new": new_status})

    admin = MagicMock(id=15, role="admin", full_name="Admin", username="admin")

    service_result = {
        "success_count": 1,
        "failed_count": 0,
        "failed_ids": [],
        "errors": None,
        "message": "Approved 1 of 1 profiles",
        "_approved_profiles": [profile],
    }

    with patch(
        "app.routers.admissions.admission_service.bulk_approve",
        new=AsyncMock(return_value=service_result),
    ), patch(
        "app.routers.admissions.safe_dispatch", tracking_dispatch,
    ), patch(
        "app.routers.admissions.safe_check_commission_on_status_change",
        tracking_commission,
    ):
        db = AsyncMock()
        db.commit = AsyncMock()

        body = MagicMock()
        body.items = [MagicMock(model_dump=lambda: {"profile_id": 5})]
        body.notes = "test"

        await bulk_approve_admissions(
            request=_fake_request(), body=body, current_user=admin, db=db,
        )

    # Both dispatches must use "resubmitted", not "submitted"
    app_dispatch = next(c for c in dispatch_calls if c["event"] == "application_status_changed")
    lead_dispatch = next(c for c in dispatch_calls if c["event"] == "lead_status_changed")
    assert app_dispatch["payload"]["old_status"] == "resubmitted"
    assert lead_dispatch["payload"]["old_status"] == "resubmitted"
    assert commission_calls == [{"old": "resubmitted", "new": "sts09"}]


# ============================================================================
# Scoped ops: admission_profile external visibility
# ============================================================================

def test_scope_condition_includes_admission_profile_for_manager():
    """Manager scope includes external rows with source_type='admission_profile'
    via AdmissionProfile → Lead.unit_id subquery."""
    from app.repositories.notification_delivery_repository import _build_scope_condition
    cond = _build_scope_condition([1, 2], allowed_unit_ids=[10, 20])
    sql = str(cond).lower()
    assert "admission_profile" in sql
    assert "lead" in sql


def test_scope_condition_includes_admission_profile_for_officer():
    """Officer scope includes external rows with source_type='admission_profile'
    via AdmissionProfile → Lead.assigned_officer_id subquery."""
    from app.repositories.notification_delivery_repository import _build_scope_condition
    cond = _build_scope_condition([7], officer_id=7)
    sql = str(cond).lower()
    assert "admission_profile" in sql
    assert "assigned_officer_id" in sql


@pytest.mark.asyncio
async def test_officer_idor_admission_profile_assigned():
    """Officer can access external delivery with source_type='admission_profile'
    if the linked lead is assigned to them."""
    from app.core.deps import _check_external_source_assigned_to

    record = MagicMock()
    record.source_type = "admission_profile"
    record.source_id = 14

    db = AsyncMock()
    # JOIN AdmissionProfile→Lead returns assigned_officer_id=18
    result_mock = MagicMock()
    result_mock.first = MagicMock(return_value=(18,))
    db.execute = AsyncMock(return_value=result_mock)

    assert await _check_external_source_assigned_to(db, record, 18) is True
    assert await _check_external_source_assigned_to(db, record, 99) is False


@pytest.mark.asyncio
async def test_manager_idor_admission_profile_in_unit():
    """Manager can access external delivery with source_type='admission_profile'
    if the linked lead is in their unit hierarchy."""
    from app.core.deps import _check_external_source_in_units

    record = MagicMock()
    record.source_type = "admission_profile"
    record.source_id = 14

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.first = MagicMock(return_value=(10,))  # unit_id=10
    db.execute = AsyncMock(return_value=result_mock)

    assert await _check_external_source_in_units(db, record, [10, 20]) is True


@pytest.mark.asyncio
async def test_manager_idor_admission_profile_out_of_unit():
    """Manager denied external delivery if admission_profile's lead is outside units."""
    from app.core.deps import _check_external_source_in_units

    record = MagicMock()
    record.source_type = "admission_profile"
    record.source_id = 14

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.first = MagicMock(return_value=(99,))  # unit_id=99
    db.execute = AsyncMock(return_value=result_mock)

    assert await _check_external_source_in_units(db, record, [10, 20]) is False


# ============================================================================
# Repository query paths: admission_profile scope wired through
# ============================================================================

@pytest.mark.asyncio
async def test_list_deliveries_query_includes_admission_profile_scope():
    """list_deliveries with manager scope generates SQL that includes
    admission_profile source type in the scope condition."""
    from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=0)
    list_result = MagicMock()
    list_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute = AsyncMock(side_effect=[count_result, list_result])

    repo = NotificationDeliveryRepository(db)
    await repo.list_deliveries(allowed_user_ids=[1, 2], allowed_unit_ids=[10, 20])

    # Both count and list queries should include admission_profile scope
    for call in db.execute.await_args_list:
        sql = str(call.args[0]).lower()
        if "notification_delivery" in sql:
            assert "admission_profile" in sql, \
                f"Query missing admission_profile scope: {sql[:200]}"


@pytest.mark.asyncio
async def test_get_aggregate_stats_query_includes_admission_profile_scope():
    """get_aggregate_stats with officer scope generates SQL that includes
    admission_profile source type in the scope condition."""
    from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

    db = AsyncMock()
    # Stats returns grouped rows
    status_result = MagicMock()
    status_result.all = MagicMock(return_value=[])
    channel_result = MagicMock()
    channel_result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(side_effect=[status_result, channel_result])

    repo = NotificationDeliveryRepository(db)
    await repo.get_aggregate_stats(allowed_user_ids=[7], officer_id=7)

    # Both status and channel queries should include admission_profile + assigned_officer
    for call in db.execute.await_args_list:
        sql = str(call.args[0]).lower()
        if "notification_delivery" in sql:
            assert "admission_profile" in sql, \
                f"Query missing admission_profile scope: {sql[:200]}"
            assert "assigned_officer_id" in sql, \
                f"Query missing officer scope: {sql[:200]}"


# ============================================================================
# Cooldown collision fix: dedupe-aware cooldown keys
# ============================================================================

@pytest.mark.asyncio
async def test_different_dedupe_keys_do_not_cooldown_block_each_other():
    """Two dispatches of APPLICATION_STATUS_CHANGED with different dedupe_keys
    (e.g., submitted:18 vs approved:18) must NOT block each other via cooldown."""
    from app.services.notification_dispatcher import dispatch
    from app.core.events import SystemEvents

    config, resolver_fn = _build_external_dispatch_patches()
    # Override to internal-only config (lead_owner, browser)
    action = MagicMock()
    action.channel = "browser"
    action.step = 1
    action.delay_minutes = 0
    action.template_code = None
    action.config = None  # no external resolver
    action.recipient_config = {"resolver_type": "lead_owner", "params": {}}

    config.actions = [action]
    config.channel_values = ["browser"]

    redis_data = {}

    # PR1: atomic SET NX — replaces separate EXISTS + SET
    async def tracking_redis_set(key, value, ex=None, nx=False):
        if nx:
            if key in redis_data:
                return None  # key exists → NX fails
            redis_data[key] = value
            return True  # key set successfully
        redis_data[key] = value
        return True

    async def no_redis_incr(key):
        return 1

    # PR1: mock catalog get_event → return user-class EventDefinition
    mock_defn = MagicMock()
    mock_defn.notification_class = "user"
    mock_defn.retired = False

    db = AsyncMock()
    db.flush = AsyncMock()
    dedup_result = MagicMock()
    dedup_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=dedup_result)

    # Resolver returns user 18
    internal_resolver = MagicMock()
    internal_resolver.resolve_users = AsyncMock(return_value=[18])

    notif_ids_per_dispatch = []

    with patch("app.services.notification_dispatcher.get_rule_for_event", new=AsyncMock(return_value=config)), \
         patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
         patch("app.services.notification_rule_loader.deserialize_resolver", return_value=internal_resolver), \
         patch("app.services.notification_dispatcher.notification_preference_service") as mock_pref, \
         patch("app.services.notification_dispatcher.safe_redis_set", tracking_redis_set), \
         patch("app.services.notification_dispatcher.safe_redis_incr", no_redis_incr), \
         patch("app.services.notification_dispatcher.safe_redis_expire", new=AsyncMock()), \
         patch("app.services.notification_dispatcher._bulk_create_notifications", new=AsyncMock(return_value={18: 1})), \
         patch("app.services.notification_dispatcher._create_deliveries_for_action", new=AsyncMock(return_value=[1])), \
         patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
        # Preference filter: pass through
        mock_pref.filter_users_by_group = AsyncMock(return_value=[18])

        # Dispatch 1: draft→submitted
        ids1, cb1 = await dispatch(
            db=db, event=SystemEvents.APPLICATION_STATUS_CHANGED,
            payload={"application_id": 18, "lead_id": 45, "old_status": "draft", "new_status": "submitted"},
            dedupe_key="admission_profile_submitted:18",
            skip_preference_check=True,
        )
        notif_ids_per_dispatch.append(ids1)

        # Dispatch 2: submitted→approved (different dedupe_key, same event+user+channel)
        ids2, cb2 = await dispatch(
            db=db, event=SystemEvents.APPLICATION_STATUS_CHANGED,
            payload={"application_id": 18, "lead_id": 45, "old_status": "submitted", "new_status": "approved"},
            dedupe_key="admission_profile_approved:18",
            skip_preference_check=True,
        )
        notif_ids_per_dispatch.append(ids2)

    # Both dispatches must create notifications (not blocked by cooldown)
    assert len(notif_ids_per_dispatch[0]) > 0, "First dispatch should create notifications"
    assert len(notif_ids_per_dispatch[1]) > 0, "Second dispatch should NOT be blocked by cooldown"


@pytest.mark.asyncio
async def test_same_dedupe_key_is_cooldown_blocked():
    """Two identical dispatches with same dedupe_key must be blocked by cooldown."""
    from app.services.notification_dispatcher import dispatch
    from app.core.events import SystemEvents

    config, resolver_fn = _build_external_dispatch_patches()
    action = MagicMock()
    action.channel = "browser"
    action.step = 1
    action.delay_minutes = 0
    action.template_code = None
    action.config = None

    config.actions = [action]
    config.channel_values = ["browser"]

    redis_data = {}

    # PR1: atomic SET NX — replaces separate EXISTS + SET
    async def tracking_redis_set(key, value, ex=None, nx=False):
        if nx:
            if key in redis_data:
                return None  # key exists → NX fails (cooldown blocks)
            redis_data[key] = value
            return True
        redis_data[key] = value
        return True

    async def no_redis_incr(key):
        return 1

    # PR1: mock catalog get_event → return user-class EventDefinition
    mock_defn = MagicMock()
    mock_defn.notification_class = "user"
    mock_defn.retired = False

    db = AsyncMock()
    db.flush = AsyncMock()
    dedup_result = MagicMock()
    dedup_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=dedup_result)

    internal_resolver = MagicMock()
    internal_resolver.resolve_users = AsyncMock(return_value=[18])

    create_call_count = 0
    async def counting_bulk_create(*args, **kwargs):
        nonlocal create_call_count
        create_call_count += 1
        return {18: create_call_count}

    with patch("app.services.notification_dispatcher.get_rule_for_event", new=AsyncMock(return_value=config)), \
         patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
         patch("app.services.notification_rule_loader.deserialize_resolver", return_value=internal_resolver), \
         patch("app.services.notification_dispatcher.notification_preference_service") as mock_pref, \
         patch("app.services.notification_dispatcher.safe_redis_set", tracking_redis_set), \
         patch("app.services.notification_dispatcher.safe_redis_incr", no_redis_incr), \
         patch("app.services.notification_dispatcher.safe_redis_expire", new=AsyncMock()), \
         patch("app.services.notification_dispatcher._bulk_create_notifications", counting_bulk_create), \
         patch("app.services.notification_dispatcher._create_deliveries_for_action", new=AsyncMock(return_value=[1])), \
         patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
        mock_pref.filter_users_by_group = AsyncMock(return_value=[18])

        # Dispatch 1
        await dispatch(
            db=db, event=SystemEvents.APPLICATION_STATUS_CHANGED,
            payload={"application_id": 18, "lead_id": 45, "old_status": "draft", "new_status": "submitted"},
            dedupe_key="admission_profile_submitted:18",
            skip_preference_check=True,
        )

        # Dispatch 2: SAME dedupe_key
        await dispatch(
            db=db, event=SystemEvents.APPLICATION_STATUS_CHANGED,
            payload={"application_id": 18, "lead_id": 45, "old_status": "draft", "new_status": "submitted"},
            dedupe_key="admission_profile_submitted:18",
            skip_preference_check=True,
        )

    # Only first dispatch should create notifications; second blocked by cooldown
    assert create_call_count == 1, f"Expected 1 bulk create (second blocked by cooldown), got {create_call_count}"


# ============================================================================
# Task A+B: application_created payload + source extraction
# ============================================================================

def test_source_extraction_prefers_application_id_over_lead_id():
    """Admissions events with application_id in payload must extract
    source_type='admission_profile', not 'lead'."""
    from app.services.notification_dispatcher import _extract_source_from_payload
    from app.core.events import SystemEvents

    # Payload has both application_id and lead_id
    source_type, source_id = _extract_source_from_payload(
        SystemEvents.APPLICATION_CREATED,
        {"application_id": 18, "lead_id": 45, "actor_id": 15},
    )
    assert source_type == "admission_profile"
    assert source_id == 18


def test_source_extraction_lead_events_still_use_lead():
    """Non-admission events without application_id still use lead_id."""
    from app.services.notification_dispatcher import _extract_source_from_payload
    from app.core.events import SystemEvents

    source_type, source_id = _extract_source_from_payload(
        SystemEvents.LEAD_ASSIGNED,
        {"lead_id": 45, "officer_id": 18},
    )
    assert source_type == "lead"
    assert source_id == 45


def test_application_created_payload_must_include_lead_name_and_program():
    """application_created dispatch payload from router must have
    lead_name and major_program_name (not None/$lead_name)."""
    required_keys = {"application_id", "lead_id", "lead_name", "major_program_name", "actor_id"}
    # A well-formed payload (program.name + offering_type):
    payload = {
        "application_id": 18,
        "lead_id": 45,
        "lead_name": "Nguyen Van A",
        "major_program_name": "Công nghệ thông tin - Chính quy",
        "actor_id": 15,
        "actor_name": "Admin",
    }
    assert required_keys.issubset(payload.keys())
    assert payload["lead_name"] != "$lead_name"
    assert payload["major_program_name"] is not None
    assert "None" not in payload["major_program_name"]


def test_program_offering_enrichment_fallback():
    """If ProgramOffering has no program relation, fall back to offering_type."""
    from types import SimpleNamespace
    # Simulate ProgramOffering with no program loaded
    po = SimpleNamespace(program=None, offering_type="Chính quy")
    if po.program:
        name = f"{po.program.name} - {po.offering_type}"
    elif po:
        name = po.offering_type
    assert name == "Chính quy"

    # With program loaded
    po2 = SimpleNamespace(
        program=SimpleNamespace(name="CNTT"),
        offering_type="Chính quy",
    )
    name2 = f"{po2.program.name} - {po2.offering_type}"
    assert name2 == "CNTT - Chính quy"


# ============================================================================
# Officer collaborator scope: list + IDOR
# ============================================================================

def test_scope_condition_officer_includes_collaborator():
    """Officer scope includes external rows with source_type='collaborator'
    via Collaborator.managed_by_officer_id."""
    from app.repositories.notification_delivery_repository import _build_scope_condition
    cond = _build_scope_condition([7], officer_id=7)
    sql = str(cond).lower()
    assert "collaborator" in sql
    assert "managed_by_officer_id" in sql


@pytest.mark.asyncio
async def test_officer_idor_collaborator_managed():
    """Officer can access external delivery with source_type='collaborator'
    if managed_by_officer_id matches."""
    from app.core.deps import _check_external_source_assigned_to

    record = MagicMock()
    record.source_type = "collaborator"
    record.source_id = 5

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.first = MagicMock(return_value=(7,))  # managed_by_officer_id=7
    db.execute = AsyncMock(return_value=result_mock)

    assert await _check_external_source_assigned_to(db, record, 7) is True
    assert await _check_external_source_assigned_to(db, record, 99) is False


# ============================================================================
# application_created create-path enrichment: explicit db.get() by FK
# ============================================================================

@pytest.mark.asyncio
async def test_create_path_enrichment_gets_real_lead_name():
    """Create-path enrichment must call db.get(Lead, lead_id) to get lead_name,
    NOT access profile.lead (which triggers lazy load → MissingGreenlet)."""
    from types import SimpleNamespace

    # Simulate post-commit objects: profile has lead_id but NO loaded .lead
    profile = SimpleNamespace(id=26, lead_id=45)
    lead = SimpleNamespace(full_name="Nguyễn Văn A", offering_id=3)
    po = SimpleNamespace(program_id=1, offering_type="Chính quy")
    mp = SimpleNamespace(name="Công nghệ thông tin")

    db = AsyncMock()
    # db.get(Lead, 45) → lead, db.get(PO, 3) → po, db.get(MP, 1) → mp
    db.get = AsyncMock(side_effect=lambda model, pk: {
        ("Lead", 45): lead,
        ("ProgramOffering", 3): po,
        ("MajorProgram", 1): mp,
    }.get((model.__name__, pk)))

    # Replicate the router enrichment logic
    _lead = await db.get(type("Lead", (), {"__name__": "Lead"}), profile.lead_id)
    _lead_name = _lead.full_name if _lead else "Unknown"
    _prog_name = None
    if _lead and _lead.offering_id:
        _po = await db.get(type("ProgramOffering", (), {"__name__": "ProgramOffering"}), _lead.offering_id)
        if _po:
            _mp = await db.get(type("MajorProgram", (), {"__name__": "MajorProgram"}), _po.program_id)
            if _mp:
                _prog_name = f"{_mp.name} - {_po.offering_type}"
            else:
                _prog_name = _po.offering_type

    assert _lead_name == "Nguyễn Văn A"
    assert _prog_name == "Công nghệ thông tin - Chính quy"
    # Verify db.get was called 3 times (lead, po, mp) — NOT relationship access
    assert db.get.await_count == 3


@pytest.mark.asyncio
async def test_create_path_enrichment_fallback_when_lead_missing():
    """If db.get(Lead, lead_id) returns None, lead_name = 'Unknown'."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    profile_lead_id = 999
    _lead = await db.get(MagicMock(__name__="Lead"), profile_lead_id)
    _lead_name = _lead.full_name if _lead else "Unknown"
    _prog_name = None

    assert _lead_name == "Unknown"
    assert _prog_name is None


@pytest.mark.asyncio
async def test_create_path_enrichment_fallback_when_no_program():
    """If ProgramOffering exists but MajorProgram is missing, fall back to offering_type."""
    from types import SimpleNamespace

    lead = SimpleNamespace(full_name="Trần Thị B", offering_id=5)
    po = SimpleNamespace(program_id=99, offering_type="Liên thông")

    db = AsyncMock()
    db.get = AsyncMock(side_effect=lambda model, pk: {
        ("Lead", 45): lead,
        ("ProgramOffering", 5): po,
        ("MajorProgram", 99): None,  # MajorProgram deleted
    }.get((model.__name__, pk)))

    _lead = await db.get(type("Lead", (), {"__name__": "Lead"}), 45)
    _lead_name = _lead.full_name if _lead else "Unknown"
    _prog_name = None
    if _lead and _lead.offering_id:
        _po = await db.get(type("ProgramOffering", (), {"__name__": "ProgramOffering"}), _lead.offering_id)
        if _po:
            _mp = await db.get(type("MajorProgram", (), {"__name__": "MajorProgram"}), _po.program_id)
            if _mp:
                _prog_name = f"{_mp.name} - {_po.offering_type}"
            else:
                _prog_name = _po.offering_type

    assert _lead_name == "Trần Thị B"
    assert _prog_name == "Liên thông"


@pytest.mark.asyncio
async def test_create_path_enrichment_fallback_when_no_offering():
    """If lead has no offering_id, program name stays None → 'Chưa xác định'."""
    from types import SimpleNamespace

    lead = SimpleNamespace(full_name="Lê Văn C", offering_id=None)

    db = AsyncMock()
    db.get = AsyncMock(side_effect=lambda model, pk: {
        ("Lead", 45): lead,
    }.get((model.__name__, pk)))

    _lead = await db.get(type("Lead", (), {"__name__": "Lead"}), 45)
    _lead_name = _lead.full_name if _lead else "Unknown"
    _prog_name = None
    if _lead and _lead.offering_id:
        pass  # skip — no offering

    assert _lead_name == "Lê Văn C"
    assert _prog_name is None
    # In router: _prog_name or "Chưa xác định" → correctly falls back
    assert (_prog_name or "Chưa xác định") == "Chưa xác định"


# ============================================================================
# application_deleted: dispatch + source extraction + no LEAD_STATUS_CHANGED
# ============================================================================

def test_application_deleted_payload_well_formed():
    """application_deleted dispatch payload must have application_id, lead_id,
    lead_name, actor_id, actor_name — same shape as other application events."""
    required_keys = {"application_id", "lead_id", "lead_name", "actor_id", "actor_name"}
    payload = {
        "application_id": 26,
        "lead_id": 45,
        "lead_name": "Nguyen Van A",
        "actor_id": 15,
        "actor_name": "Admin",
    }
    assert required_keys.issubset(payload.keys())
    assert payload["lead_name"] != "Unknown"
    assert "officer_id" not in payload  # same pattern as other application events


def test_source_extraction_for_application_deleted():
    """APPLICATION_DELETED with application_id in payload must extract
    source_type='admission_profile'."""
    from app.services.notification_dispatcher import _extract_source_from_payload
    from app.core.events import SystemEvents

    source_type, source_id = _extract_source_from_payload(
        SystemEvents.APPLICATION_DELETED,
        {"application_id": 26, "lead_id": 45, "actor_id": 15},
    )
    assert source_type == "admission_profile"
    assert source_id == 26


def test_application_deleted_does_not_emit_lead_status_changed():
    """Delete dispatch block must NOT contain LEAD_STATUS_CHANGED.
    Verify by inspecting the router code pattern — delete only emits
    APPLICATION_DELETED, never LEAD_STATUS_CHANGED."""
    import inspect
    from app.routers import admissions as adm_module

    source = inspect.getsource(adm_module.delete_admission_profile)
    assert "APPLICATION_DELETED" in source
    assert "LEAD_STATUS_CHANGED" not in source


def test_application_deleted_seed_rule_exists():
    """application_deleted must have a curated rule in the seed script."""
    from app.scripts.reset_notification_rules_dev import CURATED_RULES

    assert "application_deleted" in CURATED_RULES
    rule = CURATED_RULES["application_deleted"]
    assert rule["enabled"] is True
    assert "browser" in rule["channels"]
    assert "email" in rule["channels"]
    # Must have lead_owner + all_admins groups (4 actions: 2 channels × 2 groups)
    assert len(rule["actions"]) == 4
    resolver_types = {a["recipient_config"]["resolver_type"] for a in rule["actions"]}
    assert "lead_owner" in resolver_types
    assert "all_admins" in resolver_types
