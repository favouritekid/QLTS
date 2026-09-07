# tests/security/test_websocket_security.py
# -*- coding: utf-8 -*-
"""
WEBSOCKET SECURITY TESTS (FIX-3 / FIX-5)

Tests for WebSocket authentication security improvements:
- User blacklist check (parity with HTTP auth)
- Periodic revalidation mechanism
- Force logout events
- httpOnly cookie-based Socket.io authentication (FIX-5)

SECURITY ISSUE FIXED:
- Before: WebSocket only checked session validity
- After: WebSocket checks user blacklist + periodic revalidation
- FIX-5: WebSocket reads auth from httpOnly cookies (XSS protection)
  - Priority: HTTP_COOKIE header > auth dict (backwards compatibility)
  - Prevents token theft via XSS attacks

Created: 2025-11-07
Updated: 2025-11-09 - httpOnly cookie migration
Updated: 2026-09-07 - reliability pass

RELIABILITY PASS (2026-09-07) — what changed and why:

1. `test_server` moved to `tests/security/conftest.py`; the login helpers
   (`get_user_auth` / `get_user_token`) moved to
   `tests/security/socket_test_helpers.py`. One copy, one owner.

2. Every test that creates a `user_blacklist:*` key now deletes it inside a
   `finally`. The autouse `_socket_redis_isolation` fence is a LAST DITCH,
   not the cleanup mechanism: `invalidate_all_sessions()` writes
   `user_blacklist:{id}` with a ~30 DAY ttl, so one leaked key poisons every
   later test of the same user until something flushes the DB.

3. A refused connection is evidence of a working guard ONLY IF the server is
   known to answer. Tests that could not tell "blocked correctly" from
   "server never came up" now prove liveness first — either by connecting
   successfully with the very same token before the guard is armed, or by an
   Engine.IO handshake against the running test server.

NOTE: These tests require python-socketio[asyncio_client].
"""
import asyncio
import logging
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio

# Socket.IO async client
try:
    import socketio
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    socketio = None

from app.config import settings

# Import constants
try:
    from ..fixtures.constants import AuthURLs
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

from .socket_test_helpers import assert_redis_sach, get_user_auth, get_user_token

log = logging.getLogger(__name__)


# Skip all tests if socketio client not available
pytestmark = [
    pytest.mark.security,
    pytest.mark.skipif(
        not SOCKETIO_AVAILABLE,
        reason=(
            "python-socketio not installed. "
            "Install with: pip install python-socketio[asyncio_client]"
        ),
    ),
]


# ============================================
# FIXTURES
# ============================================


@pytest_asyncio.fixture(autouse=True)
async def _socket_redis_isolation(clear_redis_keys, test_redis_client):
    """
    Hàng rào CUỐI cho rác Redis của module này.

    `clear_redis_keys` dọn trước/sau mỗi ca; `assert_redis_sach` chạy TRƯỚC
    lần flush teardown đó (đã kiểm thực nghiệm thứ tự này), nên nó nhìn thấy
    đúng những khoá mà ca test để lại.

    ĐÂY KHÔNG PHẢI cơ chế dọn dẹp. Mỗi ca tự xoá khoá của mình trong
    `finally`. Hàng rào này chỉ để một ca quên dọn thì ĐỎ ngay tại ca đó,
    thay vì làm hỏng một ca khác chạy sau.
    """
    yield
    await assert_redis_sach(test_redis_client)


@pytest_asyncio.fixture
async def sio_client(client):
    """
    Create Socket.IO async client for testing.

    IMPORTANT: httpx has no WebSocket client API (`ws_connect`), so the
    socket.io client rides on aiohttp.ClientSession instead. The main test
    client (httpx) stays for REST API calls.
    """
    if not SOCKETIO_AVAILABLE:
        pytest.skip("socketio not available")

    import aiohttp
    aio_session = aiohttp.ClientSession()
    sio = socketio.AsyncClient(http_session=aio_session)
    yield sio

    # Cleanup
    if sio.connected:
        await sio.disconnect()
    if not aio_session.closed:
        await aio_session.close()


@asynccontextmanager
async def _fresh_sio_client(cookies: dict | None = None):
    """
    Một Socket.IO client ĐỘC LẬP với fixture `sio_client`.

    Dùng khi một ca cần HAI kết nối phân biệt được với nhau (ví dụ: một kết
    nối chứng minh server sống, rồi một kết nối phải bị từ chối) — tránh mọi
    nhập nhằng của việc reconnect trên cùng một client sau `disconnect()`.

    `cookies`: nếu truyền vào, client gửi cookie thay cho auth dict.
    """
    import aiohttp

    if cookies is None:
        session = aiohttp.ClientSession()
    else:
        # `unsafe=True` là BẮT BUỘC: aiohttp mặc định KHÔNG gửi cookie tới
        # host dạng địa chỉ IP, mà test server là http://127.0.0.1:<port>.
        # Thiếu cờ này thì handshake đi ra KHÔNG kèm cookie nào và ca test
        # "xác thực bằng cookie" chỉ đang đo đường auth-dict/không-token.
        jar = aiohttp.CookieJar(unsafe=True)
        jar.update_cookies(cookies)
        session = aiohttp.ClientSession(cookie_jar=jar)

    sio = socketio.AsyncClient(http_session=session)
    try:
        yield sio
    finally:
        if sio.connected:
            await sio.disconnect()
        if not session.closed:
            await session.close()


async def _assert_socketio_server_alive(base_url: str) -> None:
    """
    Chứng minh test server CÒN SỐNG *và* Socket.IO còn được mount.

    Vì sao cần: `socketio.exceptions.ConnectionError` được ném ra cho CẢ HAI
    trường hợp "server từ chối vì guard" và "server đã chết / chưa kịp lên".
    Một ca chỉ bắt ConnectionError là ca không phân biệt được hai thứ đó.

    Cách đo: gọi thẳng handshake Engine.IO qua transport polling. Nó trả
    200 kèm gói OPEN chứa `sid` mà KHÔNG chạm vào handler `connect` của
    namespace, nên không tiêu tốn hạn mức rate-limit và không cần token.
    """
    import aiohttp

    handshake_url = f"{base_url}/socket.io/?EIO=4&transport=polling"
    async with aiohttp.ClientSession() as probe:
        async with probe.get(
            handshake_url, timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            status = resp.status
            body = await resp.text()

    assert status == 200, (
        f"Test server KHÔNG trả lời handshake Engine.IO (HTTP {status}). "
        "Mọi kết luận 'kết nối bị từ chối vì bảo mật' sau đây đều vô giá trị."
    )
    assert '"sid"' in body, (
        "Handshake Engine.IO trả 200 nhưng không có gói OPEN chứa sid — "
        f"Socket.IO có thể chưa được mount. Body: {body[:200]!r}"
    )


# ============================================
# FIX-3: USER BLACKLIST CHECK TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix3_websocket_auth_checks_user_blacklist(
    test_server, client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    FIX-3: WebSocket connection is refused for blacklisted users.

    HAI PHA — pha 1 là thứ làm ca test có nghĩa:

      Pha 1 (TRƯỚC blacklist): CHÍNH token đó phải kết nối THÀNH CÔNG, rồi
             ngắt. Chứng minh server sống, Socket.IO mount đúng, token hợp lệ.
      Pha 2 (SAU blacklist):   CHÍNH token đó phải bị TỪ CHỐI.

    Không có pha 1 thì một test server chết cho ra kết quả y hệt một guard
    blacklist hoạt động hoàn hảo — ca test xanh mà không đo gì cả.
    """
    log.info("--- Running: test_fix3_websocket_auth_checks_user_blacklist ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    access_token = await get_user_token(client, username, password)
    blacklist_key = f"user_blacklist:{user_id}"

    # --- Pha 1: cùng token, CHƯA blacklist → phải kết nối được ---
    async with _fresh_sio_client() as probe:
        await probe.connect(
            test_server,
            auth={"token": access_token},
            transports=["websocket"],
        )
        assert probe.connected, (
            "Pha 1 thất bại: token hợp lệ mà không kết nối được. "
            "Pha 2 dưới đây sẽ không chứng minh được điều gì."
        )
        await probe.disconnect()
    log.info("Pha 1 OK: server sống, token hợp lệ kết nối được")

    # --- Pha 2: cùng token, ĐÃ blacklist → phải bị từ chối ---
    try:
        await test_redis_client.set(
            blacklist_key, "password_changed", ex=3600
        )
        log.info("User %s blacklisted in Redis", user_id)

        connect_error = None
        try:
            await sio_client.connect(
                test_server,
                auth={"token": access_token},
                transports=["websocket"],
            )
        except (
            socketio.exceptions.ConnectionRefusedError,
            socketio.exceptions.ConnectionError,
        ) as e:
            connect_error = e
            log.info("Connection correctly refused: %s", e)

        assert connect_error is not None, (
            "SECURITY ISSUE: WebSocket connected despite user blacklist!"
        )
        assert not sio_client.connected, "Client should not be connected"

    finally:
        # Bắt buộc: khoá này do CA NÀY tạo ra. Ca đỏ giữa chừng cũng phải
        # dọn, nếu không mọi ca sau dùng cùng user đều hỏng theo.
        await test_redis_client.delete(blacklist_key)

    log.info("--- Finished: test_fix3_websocket_auth_checks_user_blacklist ---")


@pytest.mark.asyncio
async def test_fix3_websocket_auth_with_valid_user(
    test_server, client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    FIX-3: WebSocket connection succeeds for non-blacklisted users.

    Happy path — ensures the fix doesn't break normal connections. Uses the
    legacy auth dict method for backwards compatibility verification.
    """
    log.info("--- Running: test_fix3_websocket_auth_with_valid_user ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    access_token = await get_user_token(client, username, password)

    try:
        await sio_client.connect(
            test_server,
            auth={"token": access_token},  # Legacy auth dict method
            transports=["websocket"],
        )

        assert sio_client.connected, "Client should be connected"
        log.info("WebSocket connected for valid user (auth dict method)")

    finally:
        if sio_client.connected:
            await sio_client.disconnect()

    log.info("--- Finished: test_fix3_websocket_auth_with_valid_user ---")


@pytest.mark.asyncio
async def test_fix5_websocket_auth_with_httponly_cookies(
    test_server, client, regular_user_in_db: dict
):
    """
    FIX-5: WebSocket authenticates from httpOnly cookies (no auth dict).

    SECURITY IMPROVEMENT:
    - Before: token in auth dict (readable by JS → XSS)
    - After: token in httpOnly cookies, backend reads HTTP_COOKIE header

    ⚠️ KHÔNG bọc `except Exception` quanh `connect()` ở đây. Bản cũ nuốt mọi
    lỗi kết nối rồi `log.warning(...)`, nên ca test xanh kể cả khi xác thực
    bằng cookie hoàn toàn không hoạt động — tức là nó không kiểm cái tên nó
    nói nó kiểm. Lỗi connect BẮT BUỘC làm ca này ĐỎ.
    """
    log.info("--- Running: test_fix5_websocket_auth_with_httponly_cookies ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    _access_token, cookies = await get_user_auth(client, username, password)
    assert "access_token" in cookies, (
        f"Login không trả cookie access_token; có: {list(cookies.keys())}"
    )

    # Không truyền auth dict — token PHẢI đi qua header Cookie.
    async with _fresh_sio_client(cookies=cookies) as sio_cookie:
        await sio_cookie.connect(test_server, transports=["websocket"])
        assert sio_cookie.connected, (
            "WebSocket không kết nối được bằng httpOnly cookie "
            "(không có auth dict) — đường xác thực bằng cookie đang hỏng."
        )
        log.info("WebSocket connected using httpOnly cookies (no auth dict)")

    log.info("--- Finished: test_fix5_websocket_auth_with_httponly_cookies ---")


# ============================================
# FIX-3: PERIODIC REVALIDATION TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix3_websocket_revalidation_success(
    test_server, client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    FIX-3: Periodic revalidation with a valid session returns {"valid": True}.
    """
    log.info("--- Running: test_fix3_websocket_revalidation_success ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    access_token = await get_user_token(client, username, password)

    await sio_client.connect(
        test_server,
        auth={"token": access_token},
        transports=["websocket"],
    )
    assert sio_client.connected

    response = await sio_client.call("revalidate_auth", timeout=5)

    assert isinstance(response, dict), "Response should be a dict"
    assert response.get("valid") is True, f"Expected valid=True, got {response}"
    log.info("Revalidation successful")

    await sio_client.disconnect()

    log.info("--- Finished: test_fix3_websocket_revalidation_success ---")


@pytest.mark.asyncio
async def test_fix3_websocket_revalidation_detects_blacklist(
    test_server, client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    FIX-3: Revalidation detects the user blacklist and drops the socket.

    Test Flow:
    1. Connect WebSocket (proves the server is alive before the guard is armed)
    2. Blacklist user (simulate password change)
    3. Call revalidate_auth
    4. Expect {"valid": False} and a disconnect

    This is the MAIN security feature: catching missed force_logout events.
    """
    log.info("--- Running: test_fix3_websocket_revalidation_detects_blacklist ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]
    blacklist_key = f"user_blacklist:{user_id}"

    access_token = await get_user_token(client, username, password)

    await sio_client.connect(
        test_server,
        auth={"token": access_token},
        transports=["websocket"],
    )
    assert sio_client.connected
    log.info("WebSocket connected")

    try:
        # Simulate password change (blacklist user)
        await test_redis_client.set(
            blacklist_key, "password_changed", ex=3600
        )
        log.info("User %s blacklisted", user_id)

        try:
            response = await sio_client.call("revalidate_auth", timeout=5)

            assert isinstance(response, dict), "Response should be a dict"
            assert response.get("valid") is False, (
                "SECURITY ISSUE: Revalidation passed despite blacklist! "
                f"Response: {response}"
            )
            assert "reason" in response
            reason = response["reason"].lower()
            assert "invalidated" in reason or "blacklist" in reason

            log.info("Revalidation correctly detected blacklist: %s", response)

        except socketio.exceptions.TimeoutError:
            # Server may disconnect us before the ack is delivered.
            log.info("Server disconnected before response (also acceptable)")

        # Wait for disconnect
        await asyncio.sleep(0.5)

        assert not sio_client.connected, (
            "SECURITY ISSUE: Client still connected after revalidation failure!"
        )

    finally:
        await test_redis_client.delete(blacklist_key)

    log.info("--- Finished: test_fix3_websocket_revalidation_detects_blacklist ---")


# ============================================
# FIX-3: FORCE LOGOUT EVENTS TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix3_force_logout_batch_event(
    test_server, client, sio_client, regular_user_in_db: dict
):
    """
    FIX-3: Client thật sự NHẬN được `force_logout_batch` với payload đúng.

    ĐƯỜNG PHÁT ĐƯỢC CHỌN: `dispatcher.dispatch(TransportEvents.USER_FORCE_LOGOUT,
    ...)` — đúng lời gọi mà `session_service.revoke_session()`,
    `revoke_all_other_sessions()` và `user_service.invalidate_all_sessions()`
    đều dùng. Nó đi qua đăng ký `dispatcher.register(USER_FORCE_LOGOUT,
    emit_force_logout)` ở `app/socket_manager.py`, rồi vào chính
    `emit_force_logout()`, rồi ra room `session_room_{jti}` mà handler
    `connect` đã cho socket này vào.

    Vì sao KHÔNG đi qua HTTP API ở đây: đường API thật
    (`DELETE /api/sessions/{id}`) đã được
    `test_session_revocation.py::test_targeted_revocation_flow` phủ, kèm cả
    phần "client kia KHÔNG được nhận". Ca này giữ đúng phần vận chuyển:
    đăng ký handler + chọn room + hình dạng payload — thứ mà mọi đường
    nghiệp vụ đều phụ thuộc.

    Bản cũ chỉ đăng ký handler rồi tự nhận xét "full integration test
    requires server hooks": không có sự kiện nào được phát, không có gì
    được chờ, và ca test xanh kể cả khi `emit_force_logout` bị gỡ hẳn.
    """
    log.info("--- Running: test_fix3_force_logout_batch_event ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    access_token = await get_user_token(client, username, password)

    # r_jti là khoá room `session_room_{r_jti}` mà handler connect dùng.
    import jwt
    payload = jwt.decode(
        access_token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    r_jti = payload.get("r_jti")
    assert r_jti, "Could not extract r_jti from token"

    logout_event_received = asyncio.Event()
    received: list = []

    @sio_client.on("force_logout_batch")
    async def on_force_logout(data):
        received.append(data)
        logout_event_received.set()
        log.info("Received force_logout_batch: %s", data)

    await sio_client.connect(
        test_server,
        auth={"token": access_token},
        transports=["websocket"],
    )
    assert sio_client.connected

    try:
        from app.core.events import TransportEvents, dispatcher
        from app.socket_manager import emit_force_logout

        # Nếu handler không còn được đăng ký thì `dispatch` im lặng không
        # làm gì và ca test sẽ chỉ timeout — một thông báo lỗi vô nghĩa.
        # Kiểm điều kiện đó tường minh để lỗi nói ra được nguyên nhân.
        handlers = dispatcher._handlers.get(TransportEvents.USER_FORCE_LOGOUT, [])
        assert emit_force_logout in handlers, (
            "emit_force_logout KHÔNG được đăng ký cho "
            f"'{TransportEvents.USER_FORCE_LOGOUT}' — mọi đường revoke "
            "session sẽ im lặng không phát force_logout_batch."
        )

        await dispatcher.dispatch(
            TransportEvents.USER_FORCE_LOGOUT,
            user_id=user_id,
            revoked_jtis=[r_jti],
        )

        try:
            await asyncio.wait_for(logout_event_received.wait(), timeout=10)
        except asyncio.TimeoutError:
            pytest.fail(
                "Không nhận được 'force_logout_batch' trong 10s sau khi "
                f"dispatch tới session_room_{r_jti}. Sự kiện thu hồi phiên "
                "không tới được client."
            )

        assert received, "Event fired but no payload captured"
        assert received[0] == {"revoked_jtis": [r_jti]}, (
            "Payload force_logout_batch sai. Client dùng revoked_jtis để "
            f"biết phiên nào bị thu hồi. Nhận được: {received[0]!r}"
        )
        log.info("force_logout_batch received with correct payload")

    finally:
        if sio_client.connected:
            await sio_client.disconnect()

    log.info("--- Finished: test_fix3_force_logout_batch_event ---")


# ============================================
# FIX-3: INTEGRATION TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix3_websocket_end_to_end_security(
    test_server, client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    FIX-3: End-to-end WebSocket security test.

    Scenario:
    1. User connects via WebSocket
    2. User changes password (blacklist triggered THROUGH THE REAL API)
    3. Revalidation detects the blacklist and the socket is dropped
    4. User cannot reconnect with the old token

    HAI SỬA QUAN TRỌNG so với bản cũ:

    a) Bản cũ tạo `user_blacklist:{id}` QUA API (change-password →
       `invalidate_all_sessions` → `safe_redis_set(..., ex≈30 NGÀY)`) và
       KHÔNG xoá gì cả. Nay xoá tường minh trong `finally`, kèm
       `blacklist:{r_jti}` mà cùng luồng đó tạo ra.

    b) Bước 5 bản cũ chỉ bắt `ConnectionRefusedError | ConnectionError`, nên
       "bị từ chối vì blacklist" và "server đã chết" cho ra cùng một kết
       quả xanh. Nay phải chứng minh server CÒN SỐNG trước
       (`_assert_socketio_server_alive`) thì `ConnectionError` mới là bằng
       chứng. Không dùng "đăng nhập lại rồi nối bằng token MỚI" làm phép đo
       sống: `user_blacklist:{id}` chặn MỌI token của user này, kể cả token
       vừa cấp — phép đo đó sẽ luôn thất bại dù server hoàn toàn khoẻ.
    """
    log.info("--- Running: test_fix3_websocket_end_to_end_security ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]
    new_password = "NewSecurePassword!123"
    blacklist_key = f"user_blacklist:{user_id}"

    # Step 1: Connect WebSocket
    access_token = await get_user_token(client, username, password)

    import jwt
    token_payload = jwt.decode(
        access_token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    r_jti = token_payload.get("r_jti")
    assert r_jti, "Could not extract r_jti from token"

    await sio_client.connect(
        test_server,
        auth={"token": access_token},
        transports=["websocket"],
    )
    assert sio_client.connected
    log.info("Step 1: WebSocket connected")

    try:
        # Step 2: Change password (this blacklists the user)
        headers = {"Authorization": f"Bearer {access_token}"}
        change_res = await client.post(
            AuthURLs.CHANGE_PASSWORD,
            json={"old_password": password, "new_password": new_password},
            headers=headers,
        )
        assert change_res.status_code == 204
        log.info("Step 2: Password changed (user blacklisted)")

        # Step 3: Verify blacklist is set
        blacklist_exists = await test_redis_client.exists(blacklist_key)
        assert blacklist_exists == 1
        log.info("Step 3: User blacklist confirmed in Redis")

        # Step 4: Revalidation must fail
        await asyncio.sleep(0.5)  # Small delay for event propagation

        if sio_client.connected:
            try:
                response = await sio_client.call("revalidate_auth", timeout=5)
                assert response.get("valid") is False, (
                    "Revalidation should fail for blacklisted user"
                )
                log.info("Step 4: Revalidation detected blacklist")
            except (
                socketio.exceptions.TimeoutError,
                socketio.exceptions.ConnectionError,
            ):
                log.info("Step 4: Socket disconnected (also acceptable)")
        else:
            log.info("Step 4: Socket already disconnected (ideal)")

        # Step 5: Cannot reconnect with the old token.
        if sio_client.connected:
            await sio_client.disconnect()

        # 5a. Server còn sống? Nếu không, bước 5b không chứng minh gì.
        await _assert_socketio_server_alive(test_server)

        # 5b. Cùng token cũ → phải bị từ chối.
        reconnect_error = None
        try:
            await sio_client.connect(
                test_server,
                auth={"token": access_token},  # Old token
                transports=["websocket"],
            )
        except (
            socketio.exceptions.ConnectionRefusedError,
            socketio.exceptions.ConnectionError,
        ) as e:
            reconnect_error = e

        assert reconnect_error is not None, (
            "SECURITY ISSUE: Reconnected with old token after password change!"
        )
        assert not sio_client.connected, (
            "SECURITY ISSUE: Client connected with a revoked token"
        )
        log.info("Step 5: Cannot reconnect with old token (server proven alive)")

    finally:
        # Khoá do luồng change-password tạo ra, ttl ~30 NGÀY. Không được
        # trông vào `flushdb` của fixture — fixture chỉ là hàng rào cuối.
        await test_redis_client.delete(blacklist_key)
        await test_redis_client.delete(f"blacklist:{r_jti}")

    log.info("--- Finished: test_fix3_websocket_end_to_end_security ---")


# ============================================
# PERFORMANCE TESTS
# ============================================


@pytest.mark.asyncio
@pytest.mark.slow
async def test_fix3_revalidation_performance(
    test_server, client, sio_client, regular_user_in_db: dict
):
    """
    Test that periodic revalidation doesn't impact performance.

    Verifies:
    - Revalidation completes in < 100ms
    - Multiple rapid revalidations don't cause issues
    """
    log.info("--- Running: test_fix3_revalidation_performance ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    access_token = await get_user_token(client, username, password)

    await sio_client.connect(
        test_server,
        auth={"token": access_token},
        transports=["websocket"],
    )
    assert sio_client.connected

    import time
    times = []

    for i in range(10):
        start = time.perf_counter()
        response = await sio_client.call("revalidate_auth", timeout=5)
        end = time.perf_counter()

        assert response.get("valid") is True
        elapsed_ms = (end - start) * 1000
        times.append(elapsed_ms)
        log.debug("Revalidation %d: %.2fms", i + 1, elapsed_ms)

    avg_time = sum(times) / len(times)
    max_time = max(times)

    assert avg_time < 100, f"Average revalidation time too slow: {avg_time:.2f}ms"
    assert max_time < 200, f"Max revalidation time too slow: {max_time:.2f}ms"

    log.info("Performance OK: avg=%.2fms, max=%.2fms", avg_time, max_time)

    await sio_client.disconnect()

    log.info("--- Finished: test_fix3_revalidation_performance ---")
