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
