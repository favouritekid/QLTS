# tests/security/test_session_revocation.py
# -*- coding: utf-8 -*-
"""
✅ TARGETED REVOCATION TESTS (PHASE 6)

Verifies that revoking a specific session only affects that session's Socket.IO connection
while other sessions for the same user remain connected.
"""
import asyncio
import logging
import pytest
import pytest_asyncio
import socketio
from httpx import AsyncClient

from app.config import settings
from .test_websocket_security import test_server, get_user_auth, HttpxClientWrapper
from ..fixtures.constants import AuthURLs

log = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_targeted_revocation_flow(test_server, client, regular_user_in_db, test_redis_client):
    """
    Test Scenario:
    1. User logs in twice (creating 2 sessions)
    2. Both sessions connect to Socket.IO
    3. Revoke Session A only
    4. Client A should be forced to logout
    5. Client B should remain connected
    """
    import aiohttp
    
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]
    
    # --- Step 1: Login twice to create 2 sessions ---
    # Login A (using the shared client fixture to get cookies for API calls)
    token_a, cookies_a = await get_user_auth(client, username, password)
    log.info(f"✅ Session A created, token={token_a[:20]}...")
    
    # Login B (second login, same user, different session)
    token_b, cookies_b = await get_user_auth(client, username, password)
    log.info(f"✅ Session B created, token={token_b[:20]}...")

    # --- Step 2: Connect both sessions to Socket.IO ---
    session_a = aiohttp.ClientSession()
    sio_a = socketio.AsyncClient(http_session=session_a)
    
    session_b = aiohttp.ClientSession()
    sio_b = socketio.AsyncClient(http_session=session_b)

    try:
        await sio_a.connect(test_server, auth={"token": token_a}, transports=["websocket"])
        await sio_b.connect(test_server, auth={"token": token_b}, transports=["websocket"])
        
        assert sio_a.connected and sio_b.connected
        log.info("✅ Both Socket.IO clients connected successfully")

        # Setup event listeners
        logout_a = asyncio.Event()
        logout_b = asyncio.Event()

        @sio_a.on("force_logout_batch")
        def on_logout_a(data):
            log.info(f"Client A received force_logout_batch: {data}")
            logout_a.set()

        @sio_b.on("force_logout_batch")
        def on_logout_b(data):
            log.info(f"Client B received force_logout_batch: {data}")
            logout_b.set()

        # --- Step 3: Get session IDs and revoke Session A ---
        # Use client with cookies from login A to get login history
        # The `client` fixture is in-memory (ASGITransport), API calls work fine
        sessions_res = await client.get("/api/security/login-history")
        assert sessions_res.status_code == 200, f"Failed to get login-history: {sessions_res.text}"

        history = sessions_res.json()["history"]
        log.info(f"Login history contains {len(history)} entries")
        
        # Find the most recent session (first in list) - this is Session B (last login)
        # We want to revoke Session A (second in list) instead
        assert len(history) >= 2, f"Expected at least 2 sessions, got {len(history)}"
        
        # Session B is current (most recent), Session A is not current
        session_a_entry = None
        for s in history:
            if not s.get("is_current"):
                session_a_entry = s
                break
        
        assert session_a_entry, "Could not find Session A (non-current session)"
        session_a_id = session_a_entry["id"]
        log.info(f"Found Session A: id={session_a_id}")

        # --- Step 4: Revoke Session A ---
        revoke_res = await client.post(f"/api/security/revoke-session/{session_a_id}")
        assert revoke_res.status_code == 200, f"Failed to revoke: {revoke_res.text}"
        log.info(f"✅ Revoked Session A (id={session_a_id})")

        # --- Step 5: Verify targeted logout ---
        # Client A should receive logout event
        try:
            await asyncio.wait_for(logout_a.wait(), timeout=5)
            log.info("✅ Client A correctly received targeted logout event")
        except asyncio.TimeoutError:
            pytest.fail("Client A did NOT receive logout event (TIMEOUT)")

        # Client B should NOT receive any logout event
        await asyncio.sleep(1.5)  # Wait to ensure no stray event
        assert not logout_b.is_set(), "❌ BUG: Client B received logout event but shouldn't have!"
        assert sio_b.connected, "❌ BUG: Client B was unexpectedly disconnected!"
        log.info("✅ Client B remains connected - Targeted Revocation VERIFIED!")

    finally:
        if sio_a.connected:
            await sio_a.disconnect()
        if sio_b.connected:
            await sio_b.disconnect()
        await session_a.close()
        await session_b.close()
