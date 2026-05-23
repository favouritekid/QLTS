"""Option-B Commit 7 — SUSPICIOUS_LOGIN socket gating contract.

The dispatcher has multiple ``_emit_domain_event`` callsites covering
different early-exit conditions (rule missing, rule disabled, config
error, no recipients resolved, all recipients filtered, condition not
met) plus a final emit after preference filtering. Pre-PR all of them
emitted the caller-supplied ``rooms`` argument — for SUSPICIOUS_LOGIN
that was ``rooms_for_user`` = ``role_admin`` + ``user_room_<actor>``.

Problems with that pre-PR shape:
  1. ``role_admin`` broadcast made every admin's banner bump on every
     user's suspicious login — wrong audience semantics (this event
     targets the actor, not admins).
  2. The early branches fire BEFORE the per-channel preference filter
     runs, so a user who disabled the ``browser`` channel for the
     ``security`` group still got the banner bump if the dispatch path
     happened to hit an early branch.

Commit 7 fixes both:
  * Caller (``auth.py``) now passes ``rooms=None`` for SUSPICIOUS_LOGIN.
  * All 5 early branches SKIP emit entirely for SUSPICIOUS_LOGIN.
  * Final branch builds rooms from ``channel_recipient_map["browser"]``
    — preference-filtered user_room list, NO role_admin.

These tests patch ``_emit_domain_event`` to spy the ``rooms`` argument
across all branches. They seed real DB rules / preferences so the
filter pipeline runs end-to-end.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.notification_dispatcher import (
    _compute_suspicious_login_rooms,
    _is_suspicious_login_event,
    dispatch,
)


# ===========================================================================
# Helper unit tests (no DB)
# ===========================================================================


def test_is_suspicious_login_event_predicate():
    """Single predicate so the early-branch skip logic doesn't drift."""
    assert _is_suspicious_login_event(SystemEvents.SUSPICIOUS_LOGIN) is True
    assert _is_suspicious_login_event(SystemEvents.LEAD_CREATED) is False
    assert _is_suspicious_login_event(SystemEvents.SYSTEM_ALERT) is False


def test_compute_suspicious_login_rooms_filters_to_user_rooms():
    """Eligible browser users → user_room_<uid>; no role_admin."""
    rooms = _compute_suspicious_login_rooms({"browser": [16, 42]})
    assert rooms == ["user_room_16", "user_room_42"]
    assert "role_admin" not in rooms


def test_compute_suspicious_login_rooms_empty_when_no_browser_recipients():
    """No eligible users → empty list. Fail-closed guard in
    ``_emit_domain_event`` then skips the emit entirely.
    """
    assert _compute_suspicious_login_rooms({"browser": []}) == []
    assert _compute_suspicious_login_rooms({}) == []
    # Other channels (email, zalo_bot) don't pull users into the room list —
    # socket banner is browser-only.
    assert _compute_suspicious_login_rooms({"email": [16], "zalo_bot": [16]}) == []


def test_compute_suspicious_login_rooms_does_not_include_role_admin():
    """Regression guard: even when invoked with an admin user_id in the
    browser list, the function must not synthesize ``role_admin``.
    """
    rooms = _compute_suspicious_login_rooms({"browser": [1]})
    assert "role_admin" not in rooms


# ===========================================================================
# Integration tests — dispatch() pipeline with patched emit
# ===========================================================================


async def _seed_user(db: AsyncSession, *, username: str, role: str = "user") -> models.User:
    user = models.User(
        username=username,
        email=f"{username}@test.local",
        password_hash="x",
        role=role,
        status="active",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _seed_suspicious_login_rule(db: AsyncSession) -> models.NotificationRule:
    """Seed a minimal SUSPICIOUS_LOGIN rule with a browser action so the
    dispatch path reaches the final emit. The resolver targets the
    actor user (matches event_catalog default).
    """
    rule = models.NotificationRule(
        event=SystemEvents.SUSPICIOUS_LOGIN.value,
        title_template="⚠️ Suspicious login",
        message_template="From ${ip_address}",
        notification_type="warning",
        recipient_config={"resolver_type": "specific_users", "params": {}},
        enabled=True,
    )
    db.add(rule)
    await db.flush()
    db.add(models.NotificationAction(
        rule_id=rule.id, step=1, channel="browser",
        content_mode="inherit_default",
    ))
    await db.commit()
    await db.refresh(rule)
    return rule


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.security
async def test_happy_path_emits_user_room_no_role_admin(
    db: AsyncSession, mocker
):
    """User has security/browser preference ENABLED. Dispatch reaches
    the final emit, which calls ``_emit_domain_event`` with rooms =
    ``[user_room_<uid>]`` — NO ``role_admin``.
    """
    from app.services.notification_rule_loader import invalidate_rule_cache
    await invalidate_rule_cache(SystemEvents.SUSPICIOUS_LOGIN.value)

    user = await _seed_user(db, username="susp_happy")
    await _seed_suspicious_login_rule(db)

    spy = mocker.patch(
        "app.services.notification_dispatcher._emit_domain_event",
        new_callable=AsyncMock,
    )
    # Bypass per-channel filter (user has default-allow preference) and
    # short-circuit the channel send (no real toast / email).
    mocker.patch(
        "app.services.notification_dispatcher._send_via_channel",
        new_callable=AsyncMock,
        return_value=("browser", MagicMock(sent_count=1, failed_ids=[], success=True), None),
    )

    payload = {
        "user_id": user.id,
        "user_ids": [user.id],
        "login_history_id": 1,
        "ip_address": "10.0.0.1",
        "actor_id": user.id,
    }
    _, callback = await dispatch(db, SystemEvents.SUSPICIOUS_LOGIN, payload, rooms=None)
    if callback:
        await callback()

    assert spy.await_count >= 1, "Expected at least one _emit_domain_event call"
    last_call = spy.await_args
    actual_rooms = last_call.kwargs.get("rooms") or (
        last_call.args[2] if len(last_call.args) > 2 else None
    )
    assert actual_rooms == [f"user_room_{user.id}"], (
        f"Expected rooms=[user_room_{user.id}], got {actual_rooms!r}. "
        "Either role_admin leaked in or the eligible user wasn't included."
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.security
async def test_all_filtered_skips_emit_entirely(
    db: AsyncSession, mocker
):
    """User has security/browser preference DISABLED. Dispatch reaches
    the "all recipients filtered" early branch; emit is SKIPPED (not
    called with empty rooms — explicit skip per Plan v10 NB2.v4).
    """
    from app.services.notification_rule_loader import invalidate_rule_cache
    await invalidate_rule_cache(SystemEvents.SUSPICIOUS_LOGIN.value)

    user = await _seed_user(db, username="susp_disabled")
    await _seed_suspicious_login_rule(db)

    # Seed preference: security/browser = False so the channel filter
    # removes the user from the recipient map.
    pref = models.NotificationPreference(
        user_id=user.id,
        type_preferences={"security": {"browser": False, "email": False}},
    )
    db.add(pref)
    await db.commit()

    spy = mocker.patch(
        "app.services.notification_dispatcher._emit_domain_event",
        new_callable=AsyncMock,
    )

    payload = {
        "user_id": user.id,
        "user_ids": [user.id],
        "login_history_id": 1,
        "ip_address": "10.0.0.1",
        "actor_id": user.id,
    }
    _, callback = await dispatch(db, SystemEvents.SUSPICIOUS_LOGIN, payload, rooms=None)
    if callback:
        await callback()

    assert spy.await_count == 0, (
        f"Expected zero _emit_domain_event calls (all filtered → skip), "
        f"got {spy.await_count}. Check the SUSPICIOUS_LOGIN early-branch "
        f"skip logic in dispatch()."
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.security
async def test_rule_missing_skips_emit_for_suspicious_login(
    db: AsyncSession, mocker
):
    """No notification_rule for SUSPICIOUS_LOGIN. Dispatch hits the
    "no enabled DB rule" early branch — emit is SKIPPED for this event
    (vs the legacy behaviour which emitted ``rooms`` as-is, bypassing
    the to-be-built preference filter).
    """
    # Rule cache is Redis-backed and lives across tests in the same
    # process — invalidate it before asserting "no rule".
    from app.services.notification_rule_loader import invalidate_rule_cache
    await invalidate_rule_cache(SystemEvents.SUSPICIOUS_LOGIN.value)

    user = await _seed_user(db, username="susp_no_rule")
    # NO rule seeded.

    spy = mocker.patch(
        "app.services.notification_dispatcher._emit_domain_event",
        new_callable=AsyncMock,
    )

    payload = {"user_id": user.id, "user_ids": [user.id], "actor_id": user.id}
    _, callback = await dispatch(db, SystemEvents.SUSPICIOUS_LOGIN, payload, rooms=None)
    if callback:
        await callback()

    assert spy.await_count == 0, (
        "Expected no emit for SUSPICIOUS_LOGIN when rule is missing"
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.security
async def test_rule_disabled_skips_emit_for_suspicious_login(
    db: AsyncSession, mocker
):
    """Rule exists but ``enabled=False``. Dispatcher uses
    ``get_rule_for_event`` which only loads enabled rules — so the path
    is identical to "no rule" above. Lock the contract anyway because
    flipping ``enabled`` is the operator's first-line emergency shutoff.
    """
    from app.services.notification_rule_loader import invalidate_rule_cache
    await invalidate_rule_cache(SystemEvents.SUSPICIOUS_LOGIN.value)

    user = await _seed_user(db, username="susp_disabled_rule")
    rule = models.NotificationRule(
        event=SystemEvents.SUSPICIOUS_LOGIN.value,
        title_template="x",
        message_template="x",
        notification_type="warning",
        recipient_config={"resolver_type": "specific_users", "params": {}},
        enabled=False,  # disabled
    )
    db.add(rule)
    await db.flush()
    db.add(models.NotificationAction(
        rule_id=rule.id, step=1, channel="browser",
        content_mode="inherit_default",
    ))
    await db.commit()

    spy = mocker.patch(
        "app.services.notification_dispatcher._emit_domain_event",
        new_callable=AsyncMock,
    )

    payload = {"user_id": user.id, "user_ids": [user.id], "actor_id": user.id}
    _, callback = await dispatch(db, SystemEvents.SUSPICIOUS_LOGIN, payload, rooms=None)
    if callback:
        await callback()

    assert spy.await_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.security
async def test_regression_lead_event_emit_unchanged(
    db: AsyncSession, mocker
):
    """Other events (LEAD_CREATED here) MUST keep emitting with the
    caller-supplied ``rooms``. The SUSPICIOUS_LOGIN gating must not
    leak into the general dispatch path.
    """
    from app.services.notification_rule_loader import invalidate_rule_cache
    await invalidate_rule_cache(SystemEvents.LEAD_CREATED.value)

    user = await _seed_user(db, username="lead_regression")
    # NO rule for LEAD_CREATED — hits "no enabled DB rule" early branch.

    spy = mocker.patch(
        "app.services.notification_dispatcher._emit_domain_event",
        new_callable=AsyncMock,
    )

    payload = {"user_id": user.id, "lead_id": 999}
    caller_rooms = ["role_admin", "unit_1", "user_room_42"]
    _, callback = await dispatch(
        db, SystemEvents.LEAD_CREATED, payload, rooms=caller_rooms,
    )
    if callback:
        await callback()

    assert spy.await_count >= 1, (
        "LEAD_CREATED must keep emitting via early branch (no gating)"
    )
    last_call = spy.await_args
    actual_rooms = last_call.kwargs.get("rooms") or (
        last_call.args[2] if len(last_call.args) > 2 else None
    )
    assert actual_rooms == caller_rooms, (
        f"LEAD_CREATED rooms got rewritten: expected {caller_rooms}, "
        f"got {actual_rooms}. Gating leaked outside SUSPICIOUS_LOGIN."
    )


# ===========================================================================
# Caller-side contract — auth.py must not pass rooms_for_user
# ===========================================================================


def test_auth_router_does_not_pass_rooms_for_user_for_suspicious_login():
    """Static source-level contract: ``auth.py`` invokes ``safe_dispatch``
    with ``rooms=None`` (or omitted) for the SUSPICIOUS_LOGIN payload.
    Pre-PR it passed ``rooms_for_user(_notif_user_id)`` which contained
    ``role_admin`` — that was the bypass route that defeated the
    dispatcher's preference gating.
    """
    import inspect
    import re
    from app.routers import auth as auth_router

    src = inspect.getsource(auth_router)
    # Find the safe_dispatch call for SUSPICIOUS_LOGIN.
    match = re.search(
        r"safe_dispatch\([^)]*event=SystemEvents\.SUSPICIOUS_LOGIN[^)]*\)",
        src,
        re.DOTALL,
    )
    assert match is not None, "safe_dispatch call for SUSPICIOUS_LOGIN not found"
    block = match.group(0)
    assert "rooms_for_user" not in block, (
        "auth.py is still passing rooms_for_user(...) to the "
        "SUSPICIOUS_LOGIN dispatch. Option-B Commit 7 requires "
        "rooms=None so the dispatcher computes preference-gated rooms."
    )
    assert "rooms=None" in block, (
        "auth.py must explicitly pass rooms=None for SUSPICIOUS_LOGIN."
    )
