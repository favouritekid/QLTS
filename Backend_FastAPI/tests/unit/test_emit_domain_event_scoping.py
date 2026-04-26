"""Runtime guard tests for ``_emit_domain_event`` socket scoping.

Complements the static contract test ``test_socket_scoping_contract``:
that one walks dispatch call sites, this one exercises the emitter
itself. Together they cover both sides of the scoping contract.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.events import SystemEvents
from app.services.notification_dispatcher import _emit_domain_event


@pytest.mark.asyncio
async def test_sensitive_event_without_rooms_is_blocked():
    """Fail-closed: sensitive event with rooms=None must NOT emit."""
    with patch("app.socket_manager.sio") as mock_sio:
        mock_sio.emit = AsyncMock()
        with patch("app.config.settings.SOCKET_SCOPED_EMIT", True):
            await _emit_domain_event(
                SystemEvents.LEAD_CREATED,
                {"lead_id": 1, "full_name": "Nguyen Van A"},
                rooms=None,
            )
        assert mock_sio.emit.call_count == 0, (
            "Fail-closed guard should have blocked the emit; "
            "sensitive LEAD_CREATED without rooms must not reach sio.emit."
        )


@pytest.mark.asyncio
async def test_sensitive_event_with_empty_rooms_is_blocked():
    """Empty list is treated the same as None — fail closed."""
    with patch("app.socket_manager.sio") as mock_sio:
        mock_sio.emit = AsyncMock()
        with patch("app.config.settings.SOCKET_SCOPED_EMIT", True):
            await _emit_domain_event(
                SystemEvents.APPLICATION_STATUS_CHANGED,
                {"admission_profile_id": 42},
                rooms=[],
            )
        assert mock_sio.emit.call_count == 0


@pytest.mark.asyncio
async def test_sensitive_event_with_rooms_emits_once_per_room():
    """Scoped emit: each room receives exactly one event."""
    with patch("app.socket_manager.sio") as mock_sio:
        mock_sio.emit = AsyncMock()
        with patch("app.config.settings.SOCKET_SCOPED_EMIT", True):
            await _emit_domain_event(
                SystemEvents.LEAD_CREATED,
                {"lead_id": 1},
                rooms=["role_admin", "unit_5", "user_room_99"],
            )
        assert mock_sio.emit.call_count == 3
        target_rooms = {call.kwargs["room"] for call in mock_sio.emit.await_args_list}
        assert target_rooms == {"role_admin", "unit_5", "user_room_99"}


@pytest.mark.asyncio
async def test_sensitive_event_deduplicates_rooms():
    """Duplicate rooms in the list must fire once — no double-delivery."""
    with patch("app.socket_manager.sio") as mock_sio:
        mock_sio.emit = AsyncMock()
        with patch("app.config.settings.SOCKET_SCOPED_EMIT", True):
            await _emit_domain_event(
                SystemEvents.LEAD_CREATED,
                {"lead_id": 1},
                rooms=["role_admin", "unit_5", "role_admin"],
            )
        assert mock_sio.emit.call_count == 2


@pytest.mark.asyncio
async def test_public_event_without_rooms_broadcasts_globally():
    """Public events are allowed to broadcast (no room kwarg on sio.emit)."""
    with patch("app.socket_manager.sio") as mock_sio:
        mock_sio.emit = AsyncMock()
        with patch("app.config.settings.SOCKET_SCOPED_EMIT", True):
            await _emit_domain_event(
                SystemEvents.PIPELINE_CONFIG_UPDATED,
                {"config_type": "pipeline_stage", "operation": "create"},
                rooms=None,
            )
        assert mock_sio.emit.call_count == 1
        call = mock_sio.emit.await_args_list[0]
        assert "room" not in call.kwargs, "Public event should emit globally, not to a room"


@pytest.mark.asyncio
async def test_legacy_flag_off_bypasses_scoping():
    """SOCKET_SCOPED_EMIT=False → legacy global broadcast regardless of rooms."""
    with patch("app.socket_manager.sio") as mock_sio:
        mock_sio.emit = AsyncMock()
        with patch("app.config.settings.SOCKET_SCOPED_EMIT", False):
            await _emit_domain_event(
                SystemEvents.LEAD_CREATED,
                {"lead_id": 1},
                rooms=None,  # would be blocked in scoped mode
            )
        assert mock_sio.emit.call_count == 1
        call = mock_sio.emit.await_args_list[0]
        assert "room" not in call.kwargs


# ---------------------------------------------------------------------------
# _all_role_rooms helper — derives room list from UserRole enum so adding a
# new role auto-picks up everywhere the helper is used (vs hardcoded list
# drift). Memory: project_admission_audit_followups.md item #3.
# ---------------------------------------------------------------------------


def test_all_role_rooms_covers_every_userrole_value():
    """Helper must return one ``role_<value>`` per UserRole enum entry —
    no missing role, no stale entry, no extra junk."""
    from app.core.constants import UserRole
    from app.services.notification_dispatcher import _all_role_rooms

    rooms = _all_role_rooms()
    expected = {f"role_{role.value}" for role in UserRole}

    assert set(rooms) == expected, (
        f"Mismatch: rooms={rooms!r}, expected={expected!r}"
    )
    # No duplicates — each role appears exactly once.
    assert len(rooms) == len(set(rooms))


def test_all_role_rooms_includes_collaborator():
    """Regression for memory finding: hardcoded list at
    routers/admin/system.py:88 historically had 5 entries (admin /
    manager / officer / accountant / user) but UserRole gained
    COLLABORATOR — silent broadcast gap.

    Helper must include collaborator so SYSTEM_ALERT reaches them.
    """
    from app.services.notification_dispatcher import _all_role_rooms

    assert "role_collaborator" in _all_role_rooms()


def test_all_role_rooms_room_format_matches_socket_manager_join():
    """Room name format must mirror socket_manager.connect's auto-join
    pattern (``f\"role_{user.role}\"``). If the helper used a different
    prefix, dispatched events would land in rooms no SID is in →
    silent failure.
    """
    from app.services.notification_dispatcher import _all_role_rooms

    for room in _all_role_rooms():
        assert room.startswith("role_"), f"Unexpected format: {room!r}"
        # Suffix must be a non-empty role name (no spaces, no upper).
        suffix = room[len("role_"):]
        assert suffix and suffix.islower() and " " not in suffix
