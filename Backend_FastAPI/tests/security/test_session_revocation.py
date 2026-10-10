# tests/security/test_session_revocation.py
# -*- coding: utf-8 -*-
"""
✅ TARGETED REVOCATION TESTS (PHASE 6)

Verifies that revoking a specific session only affects that session's Socket.IO connection
while other sessions for the same user remain connected.
"""
import asyncio
import inspect
import logging
import uuid
from contextlib import ExitStack, asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
import pytest_asyncio
import socketio
from aiobreaker import CircuitBreaker, CircuitBreakerState
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from user_agents import parse as parse_user_agent

from app import database as db_module
from app import models, security, socket_manager
from app.config import settings
from app.database import AsyncSessionLocal
from app.services import session_service
from .socket_test_helpers import assert_redis_sach, get_user_auth

log = logging.getLogger(__name__)

# Select these Socket.IO revocation tests under `-m security`.
pytestmark = pytest.mark.security

# Hai lượt đăng nhập PHẢI tạo ra hai dấu vân tay repository khác nhau — khác ít
# nhất một trong `device_type`, `browser` hoặc `os` — nếu không phiên thứ hai
# giết phiên thứ nhất trước khi test kịp đo bất cứ điều gì: `session_service` gọi
# `_revoke_previous_sessions_on_device(user_id, device_type, browser, os)` ở
# mỗi lượt đăng nhập, và `SessionRepository.get_active_on_device` thu hồi những
# phiên có cùng dấu vân tay thiết bị do repository định nghĩa: trùng đồng thời
# `device_type`, `browser` và `os`. Bản test cũ đăng nhập hai lần từ CÙNG một
# httpx client — cùng User-Agent ⇒ trùng cả ba ⇒ phiên A bị thu hồi ngay lúc
# đăng nhập B, và lời gọi API tiếp theo trả `401 Session revoked or expired`.
# Tiền đề "người dùng có hai phiên sống" của ca test khi ấy không hề tồn tại.
UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 "
    "Safari/604.1"
)


@pytest_asyncio.fixture(autouse=True)
async def _socket_redis_isolation(clear_redis_keys, test_redis_client):
    """
    Socket.IO tests write session/presence keys into the shared FakeRedis
    server. `clear_redis_keys` flushes on setup AND teardown; this fixture
    depends on it, so its own teardown runs FIRST and can assert the test
    left Redis clean before the flush wipes the evidence.
    """
    yield
    await assert_redis_sach(test_redis_client)


def _r_jti(access_token: str, nhan: str) -> str:
    """Rút `r_jti` — jti của refresh token — ra khỏi access token.

    `r_jti` là thứ định danh PHIÊN: nó vừa là khoá room `session_room_{r_jti}`
    mà handler connect tham gia, vừa là `UserSession.refresh_jti` trong CSDL.
    Nhờ vậy một access token đủ để ghép phiên ở cả ba tầng (JWT ↔ room ↔ hàng
    CSDL) mà không cần đọc refresh cookie.
    """
    payload = jwt.decode(
        access_token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    gia_tri = payload.get("r_jti")
    assert gia_tri, f"Không rút được r_jti từ access token của {nhan}"
    return gia_tri


def _kiem_ua_phan_loai_dong() -> None:
    """Chứng minh hai chuỗi UA thật sự được `user_agents` xếp khác loại.

    Không tin cái tên `UA_DESKTOP`/`UA_MOBILE`: `session_service` phân loại bằng
    thư viện, và một chuỗi bị sửa/hỏng vẫn giữ nguyên tên hằng trong khi rơi về
    `unknown` cho CẢ HAI — lúc đó `device_type` lại bằng nhau và ta quay về đúng
    lỗi cũ, chỉ khác là bây giờ nó im lặng. Kiểm ngay ở đây để hỏng thì hỏng tại
    dòng này, không phải sau ba mươi giây dựng Socket.IO.

    Kiểm đủ ba cờ chứ không chỉ cờ mong đợi: app quyết định bằng một chuỗi
    `if/elif` có THỨ TỰ (`is_mobile` → `is_tablet` → `is_pc`), nên một chuỗi vừa
    `is_pc` vừa `is_mobile` sẽ ra "mobile" dù `is_pc` đúng.
    """
    desktop = parse_user_agent(UA_DESKTOP)
    mobile = parse_user_agent(UA_MOBILE)

    assert (desktop.is_pc, desktop.is_mobile, desktop.is_tablet) == (True, False, False), (
        "UA_DESKTOP không được `user_agents` xếp là PC: "
        f"is_pc={desktop.is_pc} is_mobile={desktop.is_mobile} "
        f"is_tablet={desktop.is_tablet} browser={desktop.browser.family} "
        f"os={desktop.os.family}"
    )
    assert (mobile.is_mobile, mobile.is_tablet) == (True, False), (
        "UA_MOBILE không được `user_agents` xếp là mobile: "
        f"is_pc={mobile.is_pc} is_mobile={mobile.is_mobile} "
        f"is_tablet={mobile.is_tablet} browser={mobile.browser.family} "
        f"os={mobile.os.family}"
    )


def _theo_jti(danh_sach: list) -> dict:
    """Lập bảng tra phiên theo `refresh_jti`.

    Ghép theo KHOÁ chứ không theo THỨ TỰ: `get_active_sessions` không hứa hẹn
    thứ tự nào, và ca test cũ chọn "phiên A" bằng cách quét tìm phần tử đầu tiên
    không phải `is_current` — một phép ghép đúng do may mắn, sẽ đổi nghĩa lặng lẽ
    nếu thứ tự sắp xếp đổi hoặc số phiên tăng.
    """
    bang = {}
    for phien in danh_sach:
        khoa = phien["refresh_jti"]
        assert khoa not in bang, f"refresh_jti trùng trong danh sách phiên: {khoa}"
        bang[khoa] = phien
    return bang


@pytest.mark.asyncio
async def test_targeted_revocation_flow(test_server, client, regular_user_in_db):
    """
    Test Scenario:
    1. User logs in twice — desktop + mobile — creating 2 CO-EXISTING sessions
    2. Both sessions connect to Socket.IO
    3. Revoke Session A only, via DELETE /api/sessions/{id}
    4. Client A should be forced to logout
    5. Client B should remain connected AND still revalidate as valid

    NOTE: Requires real Uvicorn server + aiohttp for Socket.IO WebSocket connections.
    A handshake/connect failure is a FAILURE, not a skip: the previous
    skip-on-any-exception swallowed every error and turned this test into a
    permanent no-op that still reported green.
    """
    import aiohttp

    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    _kiem_ua_phan_loai_dong()

    # --- Bước 1: hai lượt đăng nhập từ HAI loại thiết bị --------------------
    token_a, _ = await get_user_auth(client, username, password, user_agent=UA_DESKTOP)
    token_b, _ = await get_user_auth(client, username, password, user_agent=UA_MOBILE)

    r_jti_a = _r_jti(token_a, "phiên A (desktop)")
    r_jti_b = _r_jti(token_b, "phiên B (mobile)")
    assert r_jti_a != r_jti_b, (
        "Hai lượt đăng nhập trả về CÙNG r_jti — không có hai phiên nào cả, và "
        "mọi phép đo 'thu hồi có mục tiêu' phía dưới sẽ vô nghĩa."
    )
    log.info("✅ Session A r_jti=%s… / Session B r_jti=%s…", r_jti_a[:8], r_jti_b[:8])

    # `client` là một httpx client DÙNG CHUNG: lượt đăng nhập sau ghi đè cookie
    # của lượt trước, nên mọi lời gọi API dưới đây đi bằng thông tin của B.
    # Khẳng định điều đó thay vì giả định — nếu ai đó đảo thứ tự hai lượt đăng
    # nhập, phép này đỏ ngay, còn không thì ta sẽ đi thu hồi nhầm phiên.
    assert client.cookies.get("access_token") == token_b, (
        "Cookie access_token hiện tại không phải của phiên B — các lời gọi "
        "/api/sessions phía dưới sẽ không chạy dưới danh nghĩa B như thiết kế."
    )

    # --- Bước 2: chốt TIỀN ĐỀ trước khi đụng tới Socket.IO ------------------
    # Đo trước khi bắt tay WebSocket có chủ ý: nếu tiền đề "hai phiên sống" sai
    # thì phải đỏ TẠI ĐÂY, ở một thông điệp nói đúng nguyên nhân, chứ không phải
    # đỏ ba mươi giây sau bằng một cái timeout không giải thích được gì.
    ss_res = await client.get("/api/sessions")
    assert ss_res.status_code == 200, f"GET /api/sessions lỗi: {ss_res.text}"
    ss_body = ss_res.json()

    dang_hoat_dong = [s for s in ss_body["sessions"] if s["is_active"]]
    theo_jti = _theo_jti(dang_hoat_dong)
    assert set(theo_jti) == {r_jti_a, r_jti_b}, (
        "Tiền đề hỏng: người dùng phải có ĐÚNG hai phiên đang hoạt động "
        f"({r_jti_a[:8]}… desktop, {r_jti_b[:8]}… mobile), thực tế có "
        f"{len(dang_hoat_dong)}: {sorted(k[:8] for k in theo_jti)}. Hai lượt "
        "đăng nhập có cùng dấu vân tay thiết bị do repository định nghĩa "
        "(trùng đồng thời `device_type`, `browser` và `os`) sẽ thu hồi lẫn nhau."
    )

    phien_a, phien_b = theo_jti[r_jti_a], theo_jti[r_jti_b]
    assert phien_a["device_type"] == "desktop", (
        f"Phiên A phải là desktop, backend ghi {phien_a['device_type']!r}"
    )
    assert phien_b["device_type"] == "mobile", (
        f"Phiên B phải là mobile, backend ghi {phien_b['device_type']!r}"
    )
    assert ss_body["current_session_id"] == phien_b["id"], (
        "Phiên hiện tại phải là B (lượt đăng nhập sau cùng): backend trả "
        f"current_session_id={ss_body['current_session_id']}, B có id={phien_b['id']}"
    )

    session_a_id = phien_a["id"]
    session_b_id = phien_b["id"]
    log.info(
        "✅ Hai phiên sống song song: A id=%s desktop, B id=%s mobile (current)",
        session_a_id,
        session_b_id,
    )

    # --- Bước 3: nối cả hai phiên vào Socket.IO ----------------------------
    session_a = aiohttp.ClientSession()
    sio_a = socketio.AsyncClient(http_session=session_a)

    session_b = aiohttp.ClientSession()
    sio_b = socketio.AsyncClient(http_session=session_b)

    try:
        # No `except` here on purpose. A handshake/connect error must surface
        # as FAILED; the `finally` block below still disconnects both clients
        # and closes both aiohttp sessions, so nothing leaks.
        await sio_a.connect(test_server, auth={"token": token_a}, transports=["websocket"])
        await sio_b.connect(test_server, auth={"token": token_b}, transports=["websocket"])

        assert sio_a.connected and sio_b.connected
        log.info("✅ Both Socket.IO clients connected successfully")

        logout_a = asyncio.Event()
        logout_b = asyncio.Event()
        nhan_a: list = []
        nhan_b: list = []

        @sio_a.on("force_logout_batch")
        def on_logout_a(data):
            log.info(f"Client A received force_logout_batch: {data}")
            nhan_a.append(data)
            logout_a.set()

        @sio_b.on("force_logout_batch")
        def on_logout_b(data):
            log.info(f"Client B received force_logout_batch: {data}")
            nhan_b.append(data)
            logout_b.set()

        # --- Bước 4: thu hồi phiên A, bằng đúng đường người dùng đi --------
        # `DELETE /api/sessions/{id}` là endpoint quản lý phiên thật sự
        # (`revoke_session` → callback dispatch `USER_FORCE_LOGOUT`).
        #
        # Bản cũ gọi `POST /api/security/revoke-session/{id}` — một endpoint
        # KHÔNG TỒN TẠI: router `security` chỉ khai login-history,
        # suspicious-logins, confirm-login, secure-account và trusted-devices.
        # Nó lại lấy `id` từ `/api/security/login-history`, tức bảng LỊCH SỬ
        # ĐĂNG NHẬP chứ không phải `user_session`. Ca test cũ vì thế hỏng ở HAI
        # tầng độc lập, và chữa riêng chuyện hai phiên cùng thiết bị không đủ
        # để nó xanh.
        revoke_res = await client.delete(f"/api/sessions/{session_a_id}")
        assert revoke_res.status_code == 204, (
            f"DELETE /api/sessions/{session_a_id} phải trả 204, nhận "
            f"{revoke_res.status_code}: {revoke_res.text}"
        )
        log.info(f"✅ Revoked Session A (id={session_a_id})")

        # --- Bước 5: A phải bị đá, và đá vì ĐÚNG phiên của nó -------------
        try:
            await asyncio.wait_for(logout_a.wait(), timeout=10)
        except asyncio.TimeoutError:
            pytest.fail(
                "Client A KHÔNG nhận force_logout_batch sau 10s. "
                f"`emit_force_logout` bắn vào room session_room_{r_jti_a}; "
                "A không nhận nghĩa là nó không ở trong room đó, hoặc callback "
                "hậu-commit của revoke_session đã không chạy."
            )
        assert nhan_a == [{"revoked_jtis": [r_jti_a]}], (
            "Payload A nhận phải nêu ĐÚNG r_jti của phiên A. Một sự kiện "
            "`revoked_jtis: []` là lệnh đăng xuất TOÀN BỘ phiên — đúng cái mà "
            f"thu hồi có mục tiêu phải tránh. Thực nhận: {nhan_a}"
        )
        log.info("✅ Client A correctly received targeted logout event")

        # --- Bước 6: B không được hề hấn gì -------------------------------
        await asyncio.sleep(1.5)  # Wait to ensure no stray event
        assert not logout_b.is_set(), (
            "❌ BUG: Client B nhận force_logout_batch dù phiên B không bị thu "
            f"hồi. Payload: {nhan_b}"
        )
        assert sio_b.connected, "❌ BUG: Client B was unexpectedly disconnected!"

        # Còn kết nối chưa chứng minh còn HỢP LỆ: socket đứt hay không là việc
        # của tầng vận chuyển. `revalidate_auth` là phép kiểm phía server, đi qua
        # cả ba tầng — Redis `session:{jti}`, `user_blacklist:{user_id}`, và một
        # hàng CSDL khớp ĐÚNG jti — nên nó phân biệt được "B còn sống" với "B đã
        # bị thu hồi nhưng socket chưa kịp rụng".
        ack_b = await sio_b.call("revalidate_auth", timeout=10)
        assert ack_b == {"valid": True}, (
            f"revalidate_auth của B phải trả valid=True, thực nhận: {ack_b}"
        )
        log.info(
            "✅ Client B remains connected AND revalidates — Targeted Revocation VERIFIED!"
        )

        # --- Bước 7: sổ phiên phía server cũng phải khớp -------------------
        sau_res = await client.get("/api/sessions")
        assert sau_res.status_code == 200, f"GET /api/sessions lỗi: {sau_res.text}"
        sau_body = sau_res.json()
        con_lai = [s for s in sau_body["sessions"] if s["is_active"]]
        assert [s["refresh_jti"] for s in con_lai] == [r_jti_b], (
            "Sau thu hồi, chỉ phiên B được còn hoạt động. Thực tế: "
            f"{[(s['id'], s['device_type'], s['refresh_jti'][:8]) for s in con_lai]}"
        )
        assert sau_body["current_session_id"] == session_b_id, (
            "current_session_id sau thu hồi phải vẫn là B "
            f"(id={session_b_id}), backend trả {sau_body['current_session_id']}"
        )

    finally:
        if sio_a.connected:
            await sio_a.disconnect()
        if sio_b.connected:
            await sio_b.disconnect()
        await session_a.close()
        await session_b.close()


# =============================================================================
# /auth/refresh KHÔNG được hồi sinh phiên đã chết trong CSDL
# =============================================================================
#
# Sự cố (đã đo bằng probe trên nền 876be1a4): logout khi lệnh GHI Redis lỗi thì
# `safe_redis_delete` nuốt lỗi và `safe_redis_set` ném nhưng logout nuốt tiếp ⇒
# `/auth/logout` trả 204, hàng `user_session` ĐÃ `revoked`, nhưng khoá
# `session:{jti}` còn nguyên và không có `blacklist:{jti}`. Redis hồi thì
# `/auth/refresh` trả 200 và XOAY chính hàng đã thu hồi, vì
# `update_session_activity` tra hàng bằng `get_by_jti` — không lọc
# `revoked_at`, không lọc hết hạn.
#
# Tầng chủ sở hữu bất biến "chỉ xoay phiên còn sống": repository
# (`get_live_by_refresh_jti_for_update`, dùng chung vị từ với
# `get_by_refresh_jti_and_user` của deps.py STEP 4b). Service chỉ phân loại
# hàng chết (401 INVALID_TOKEN) với hàng không có (desync, 401 thường).
#
# Chính sách với hàng chết — KHUYẾN NGHỊ của bản preview, CHỜ owner chốt (các ca
# ghim nó mang hậu tố `OWNER_DECISION`): 401 `INVALID_TOKEN` y như mọi refresh bị
# từ chối, nhưng KHÔNG tăng `refresh_fail`, KHÔNG gọi `invalidate_all_sessions`
# và KHÔNG gửi lệnh Redis nào. Khoá `session:{jti}` sót lại được để yên: mọi nơi
# đọc nó (refresh, deps STEP 4b, socket connect, `revalidate_auth`) đều tra lại
# hàng CSDL, và nó hết hạn cùng token. Router phân biệt bằng lỗi miền
# `RefreshSessionNotLive`, bắt TRƯỚC các nhánh `InvalidToken` chung.

LOGIN_URL = "/api/auth/login"
LOGOUT_URL = "/api/auth/logout"
REFRESH_URL = "/api/auth/refresh"
CHECK_STATUS_URL = "/api/auth/check-status"

# Lệnh GHI của redis-py mà logout/refresh có thể chạm. Lệnh ĐỌC để nguyên — đúng
# kiểu sự cố probe đã đo: Redis trả lời GET/EXISTS nhưng mọi lệnh ghi đều lỗi.
_REDIS_WRITE_COMMANDS = ("set", "delete", "expire", "incr", "getdel", "eval", "setex")


def _new_breaker() -> CircuitBreaker:
    """Breaker mới, đóng, đếm lỗi = 0 (cùng tham số với `app/database.py`)."""
    return CircuitBreaker(fail_max=5, timeout_duration=timedelta(seconds=60))


@pytest.fixture
def fresh_breaker(monkeypatch):
    """Mỗi ca một circuit breaker RIÊNG — ca này cố ý làm Redis lỗi.

    `redis_breaker` là singleton cấp module (`fail_max=5`); dùng chung thì lỗi
    tiêm ở đây có thể mở breaker và làm đỏ ca KHÁC. `safe_redis_*` tra
    `redis_breaker` như biến toàn cục của module lúc gọi, nên thay ở đây là đủ.
    Gọi giá trị trả về = "Redis hồi": breaker đóng, sạch bộ đếm lỗi.
    """
    monkeypatch.setattr(db_module, "redis_breaker", _new_breaker())

    def _recover():
        monkeypatch.setattr(db_module, "redis_breaker", _new_breaker())

    return _recover


@contextmanager
def _redis_writes_down():
    """Mọi lệnh GHI của client Redis dùng chung với app đều ném ConnectionError."""

    async def _down(*args, **kwargs):
        raise RedisConnectionError("tiêm lỗi: Redis từ chối lệnh ghi")

    with ExitStack() as stack:
        for name in _REDIS_WRITE_COMMANDS:
            stack.enter_context(patch.object(db_module.redis_client, name, _down))
        yield


async def _post_with_cookies(client, url: str, **cookies):
    """POST chỉ mang ĐÚNG các cookie truyền vào (như FE: không có Bearer header)."""
    client.cookies.clear()
    try:
        return await client.post(
            url,
            headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())},
        )
    finally:
        client.cookies.clear()


async def _check_access(client, access_token: str):
    """Một request cần đăng nhập, chỉ mang cookie access_token."""
    client.cookies.clear()
    try:
        return await client.get(
            CHECK_STATUS_URL, headers={"Cookie": f"access_token={access_token}"}
        )
    finally:
        client.cookies.clear()


async def _login_as(client, user: dict, ua: str | None = None):
    """Đăng nhập, trả (access_token, refresh_token, refresh_jti)."""
    client.cookies.clear()
    try:
        res = await client.post(
            LOGIN_URL,
            data={"username": user["username"], "password": user["password"]},
            headers={"User-Agent": ua} if ua else None,
        )
    finally:
        client.cookies.clear()
    assert res.status_code == 200, res.text
    access = res.cookies.get("access_token")
    refresh = res.cookies.get("refresh_token")
    assert access and refresh, "login phải đặt cả hai cookie"
    jti = jwt.decode(
        refresh, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )["jti"]
    return access, refresh, jti


async def _row_by_id(row_id: int):
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.UserSession).where(models.UserSession.id == row_id)
            )
        ).scalar_one()


async def _row_by_jti(jti: str):
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.UserSession).where(models.UserSession.refresh_jti == jti)
            )
        ).scalar_one_or_none()


def _issued_token_cookies(res) -> list:
    """Các Set-Cookie PHÁT token mới (access/refresh có giá trị khác rỗng).

    Cookie xoá (giá trị rỗng) không tính: một 401 xoá cookie là hợp lệ, một 401
    phát token mới thì không.
    """
    issued = []
    for raw in res.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        value = rest.split(";", 1)[0].strip().strip('"')
        if name.strip() in ("access_token", "refresh_token") and value:
            issued.append(raw)
    return issued


async def _logout_during_redis_write_outage(
    client, test_redis_client, user: dict, access: str, refresh: str, jti: str, recover
):
    """Logout trong lúc Redis từ chối lệnh ghi; Redis hồi. Trả hàng CSDL sau logout.

    Kiểm TIỀN ĐỀ ngay tại đây — không có chúng thì ca kiểm phía sau xanh/đỏ
    chẳng chứng minh gì: logout 204, hàng CSDL đã thu hồi, khoá `session:` còn
    nguyên, không có blacklist.
    """
    with _redis_writes_down():
        out = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )
    recover()

    assert out.status_code == 204, out.text
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, (
        "tiền đề: logout phải ghi được revoked_at vào CSDL"
    )
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "tiền đề: lệnh ghi Redis phải hỏng thật — khoá session: còn nguyên"
    )
    assert not await test_redis_client.exists(f"blacklist:{jti}"), (
        "tiền đề: không có blacklist cho refresh jti"
    )
    return row


async def _kill_session_during_redis_write_outage(
    client, test_redis_client, user: dict, recover, ua: str | None = None
):
    """Đăng nhập rồi logout trong lúc Redis từ chối lệnh ghi (tiền đề: hàm trên)."""
    access, refresh, jti = await _login_as(client, user, ua)
    row = await _logout_during_redis_write_outage(
        client, test_redis_client, user, access, refresh, jti, recover
    )
    return access, refresh, jti, row


async def _dead_session(
    kind: str, client, test_redis_client, user: dict, recover, ua: str | None = None
):
    """Một phiên CHẾT trong CSDL mà khoá `session:{jti}` còn nguyên — hai cách chết.

    * ``revoked``: logout trong lúc Redis từ chối lệnh ghi (sự cố probe đã đo).
    * ``expired``: `expires_at` đã qua, chưa ai thu hồi.
    """
    if kind == "revoked":
        return await _kill_session_during_redis_write_outage(
            client, test_redis_client, user, recover, ua=ua
        )
    assert kind == "expired", kind
    access, refresh, jti = await _login_as(client, user, ua)
    row = await _expire_row_in_db_only(test_redis_client, user, jti)
    return access, refresh, jti, row


async def _expire_row_in_db_only(
    test_redis_client, user: dict, jti: str, ago: timedelta = timedelta(minutes=1)
):
    """Hàng CSDL của ``jti`` HẾT HẠN (`expires_at` đã qua ``ago``), CHƯA bị thu hồi;
    khoá `session:{jti}` còn nguyên. Trả hàng sau khi sửa.

    Không phải trạng thái dựng: /refresh xoay giữ `expires_at` TUYỆT ĐỐI của
    phiên (`test_refresh_rotation_keeps_absolute_session_expiry`) nhưng đặt
    `session:{jti mới}` với trọn TTL của refresh token mới — khoá sống lâu hơn
    hàng. ``ago`` nhỏ thì một "ân hạn" lén thêm vào vị từ cũng bị thấy.
    """
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(models.UserSession)
            .where(models.UserSession.refresh_jti == jti)
            .values(expires_at=datetime.now(timezone.utc) - ago)
        )
        await s.commit()
    row = await _row_by_jti(jti)
    assert row.revoked_at is None and row.expires_at <= datetime.now(timezone.utc), (
        "tiền đề: hàng phải hết hạn và CHƯA bị thu hồi"
    )
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "tiền đề: khoá session: còn nguyên"
    )
    return row


def _refresh_fail_key(user: dict) -> str:
    return f"refresh_fail:{user['username']}"


@pytest.mark.asyncio
async def test_refresh_after_logout_during_redis_write_outage_is_refused(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Phiên đã thu hồi trong CSDL ⇒ refresh 401 INVALID_TOKEN, dù Redis còn khoá."""
    _, refresh, _, _ = await _kill_session_during_redis_write_outage(
        client, test_redis_client, regular_user_in_db, fresh_breaker
    )

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    assert res.status_code == 401, res.text
    assert res.json().get("error_code") == "INVALID_TOKEN", res.text


@pytest.mark.asyncio
async def test_refused_dead_session_refresh_writes_no_new_redis_session(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """CSDL quyết TRƯỚC khi ghi xoay: không có khoá `session:` MỚI nào sau 401."""
    _, refresh, jti, _ = await _kill_session_during_redis_write_outage(
        client, test_redis_client, regular_user_in_db, fresh_breaker
    )

    await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    session_keys = set(await test_redis_client.keys("session:*"))
    assert session_keys <= {f"session:{jti}"}, (
        f"refresh bị từ chối vẫn ghi xoay vào Redis: {sorted(session_keys)}"
    )


@pytest.mark.asyncio
async def test_refused_dead_session_refresh_issues_no_new_cookies(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Không phát cookie token mới cho phiên đã chết."""
    _, refresh, _, _ = await _kill_session_during_redis_write_outage(
        client, test_redis_client, regular_user_in_db, fresh_breaker
    )

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    assert _issued_token_cookies(res) == [], (
        f"status={res.status_code} vẫn phát token: {_issued_token_cookies(res)}"
    )


@pytest.mark.asyncio
async def test_refused_dead_session_refresh_leaves_db_row_untouched(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Hàng đã thu hồi giữ nguyên refresh_jti, last_activity_at, revoked_at."""
    _, refresh, jti, before = await _kill_session_during_redis_write_outage(
        client, test_redis_client, regular_user_in_db, fresh_breaker
    )

    await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.last_activity_at, after.revoked_at) == (
        jti,
        before.last_activity_at,
        before.revoked_at,
    ), "hàng đã thu hồi bị xoay/chạm tới"


# Lệnh GHI (kể cả `pipeline`, cửa vào MULTI/EXEC) mà app có thể gửi qua client
# Redis dùng chung. Rộng hơn `_REDIS_WRITE_COMMANDS` có chủ ý: ở đây ta GHI LẠI
# chứ không tiêm lỗi, và một lệnh sót khỏi danh sách là một lệnh ghi lọt máy đo.
_REDIS_WRITE_SPY = (
    "set", "setex", "psetex", "setnx", "getset", "getdel", "getex",
    "delete", "unlink", "expire", "pexpire", "expireat", "persist",
    "incr", "incrby", "decr", "decrby", "eval", "evalsha",
    "hset", "hdel", "sadd", "srem", "zadd", "zrem", "lpush", "rpush",
    "publish", "pipeline",
)


@contextmanager
def _record_redis_writes():
    """Ghi lại (tên lệnh, 16 ký tự đầu của khoá — `session:` + tiền tố JTI, không
    in nguyên JTI) MỌI lệnh ghi app gửi qua client Redis dùng chung; lệnh vẫn
    được chuyển tiếp thật."""
    calls: list = []

    def _spy(name, real):
        if inspect.iscoroutinefunction(real):
            async def _recorded(*args, **kwargs):
                calls.append((name, str(args[0])[:16] if args else ""))
                return await real(*args, **kwargs)
        else:
            def _recorded(*args, **kwargs):
                calls.append((name, str(args[0])[:16] if args else ""))
                return real(*args, **kwargs)
        return _recorded

    with ExitStack() as stack:
        for name in _REDIS_WRITE_SPY:
            real = getattr(db_module.redis_client, name, None)
            if real is not None:
                stack.enter_context(
                    patch.object(db_module.redis_client, name, _spy(name, real))
                )
        yield calls


@pytest.mark.asyncio
async def test_refused_dead_session_refresh_sends_no_redis_write(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Nhánh hàng chết không gửi lệnh GHI Redis nào: không dọn khoá, không
    blacklist, không đếm `refresh_fail`. CSDL đã quyết; một lệnh Redis ở đây chỉ
    có thể đổi 401 thành lỗi (breaker mở) hoặc thành một kết cục khác."""
    _, refresh, _, _ = await _kill_session_during_redis_write_outage(
        client, test_redis_client, regular_user_in_db, fresh_breaker
    )

    with _record_redis_writes() as writes:
        # Máy đo phải bắt được lệnh ghi đi qua ĐÚNG đường app dùng, nếu không
        # "0 lệnh ghi" bên dưới chẳng chứng minh gì.
        await db_module.safe_redis_set("p1c:spy-probe", "1", ex=5)
        assert writes == [("set", "p1c:spy-probe")], f"máy đo hỏng: {writes}"
        writes.clear()

        res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)
    await test_redis_client.delete("p1c:spy-probe")

    assert res.status_code == 401, res.text
    assert writes == [], f"refresh bị từ chối vẫn ghi Redis: {writes}"


@pytest.mark.asyncio
async def test_refused_dead_session_refresh_leaves_stale_session_key_in_place(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Khoá `session:{jti}` sót lại KHÔNG bị dọn hay sửa, dù refresh lặp nhiều lần.

    Để yên là chủ đích: nó không cấp gì (xem nhóm ca "khoá cũ còn mà không cấp
    quyền" phía dưới) và tự hết hạn cùng token.
    """
    user = regular_user_in_db
    _, refresh, jti, _ = await _kill_session_during_redis_write_outage(
        client, test_redis_client, user, fresh_breaker
    )
    key = f"session:{jti}"
    ttl_before = await test_redis_client.ttl(key)
    try:
        for _ in range(settings.REFRESH_MAX_FAILURES + 1):
            await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

        assert await test_redis_client.get(key) == str(user["id"]), (
            "khoá session: cũ bị xoá/sửa sau khi CSDL đã từ chối"
        )
        assert 0 < await test_redis_client.ttl(key) <= ttl_before, "TTL khoá cũ bị đổi"
    finally:
        # Bản dọn khoá + đếm (đối chứng âm) chạm ngưỡng ⇒ user_blacklist; dọn để
        # ca đỏ vì ĐÚNG một lý do, không kèm lỗi teardown `assert_redis_sach`.
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


@pytest.mark.asyncio
async def test_repeated_dead_session_refresh_does_not_revoke_other_sessions_OWNER_DECISION(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Cookie của MỘT phiên chết gửi lại quá ngưỡng `REFRESH_MAX_FAILURES` vẫn
    không kéo theo `invalidate_all_sessions`: không `user_blacklist`, phiên KHÁC
    của cùng người dùng còn sống và còn refresh được."""
    _kiem_ua_phan_loai_dong()
    user = regular_user_in_db
    _, refresh_dead, _, _ = await _kill_session_during_redis_write_outage(
        client, test_redis_client, user, fresh_breaker, ua=UA_DESKTOP
    )
    _, refresh_live, jti_live = await _login_as(client, user, ua=UA_MOBILE)
    try:
        for _ in range(settings.REFRESH_MAX_FAILURES + 1):
            await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_dead)

        assert not await test_redis_client.exists(f"user_blacklist:{user['id']}"), (
            "phiên chết kéo theo user_blacklist cho cả người dùng"
        )
        assert (await _row_by_jti(jti_live)).revoked_at is None
        live = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_live)
        assert live.status_code == 200, (
            f"phiên còn sống của cùng người dùng bị kéo chết theo: {live.text}"
        )
    finally:
        # Ca đỏ không được để rác làm đỏ ca KHÁC (hàng rào `assert_redis_sach`).
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["revoked", "expired"])
async def test_repeated_dead_session_refresh_is_not_counted_OWNER_DECISION(
    kind, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Hàng chết KHÔNG được đếm là lạm dụng: gửi lại quá ngưỡng, lần nào cũng 401
    `INVALID_TOKEN` (không bao giờ 429 `REFRESH_ABUSE_LOCKED`), `refresh_fail`
    vắng mặt từ đầu tới cuối."""
    user = regular_user_in_db
    _, refresh, _, _ = await _dead_session(
        kind, client, test_redis_client, user, fresh_breaker
    )
    lan = settings.REFRESH_MAX_FAILURES + 1
    try:
        answers = []
        for _ in range(lan):
            res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)
            answers.append((res.status_code, res.json().get("error_code")))

        assert answers == [(401, "INVALID_TOKEN")] * lan, answers
        assert await test_redis_client.get(_refresh_fail_key(user)) is None
    finally:
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


@pytest.mark.asyncio
async def test_refresh_refuses_expired_session_row(
    client, regular_user_in_db, fresh_breaker
):
    """Hàng hết hạn (`expires_at` đã qua) không được xoay, dù JWT và Redis còn hạn.

    deps.py STEP 4b đã từ chối access token của hàng hết hạn; trước bản vá,
    refresh vẫn xoay nó và phát token mà deps sẽ từ chối ngay sau đó.
    """
    _, refresh, jti = await _login_as(client, regular_user_in_db)
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(models.UserSession)
            .where(models.UserSession.refresh_jti == jti)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await s.commit()

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    assert res.status_code == 401, res.text
    assert res.json().get("error_code") == "INVALID_TOKEN", res.text


@pytest.mark.asyncio
async def test_refresh_does_not_rotate_row_owned_by_another_user(
    client, regular_user_in_db, fresh_breaker
):
    """Hàng mang jti của token nhưng thuộc người dùng KHÁC ⇒ không xoay (401)."""
    _, refresh, jti = await _login_as(client, regular_user_in_db)
    async with AsyncSessionLocal() as s:
        other = models.User(
            username="p1_other_session_owner",
            email="p1_other_session_owner@test.com",
            password_hash="x",
            role="user",
            status="active",
        )
        s.add(other)
        await s.flush()
        await s.execute(
            update(models.UserSession)
            .where(models.UserSession.refresh_jti == jti)
            .values(user_id=other.id)
        )
        await s.commit()

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    assert res.status_code == 401, res.text
    assert (await _row_by_jti(jti)) is not None, "hàng của người khác bị xoay mất jti"


@pytest.mark.asyncio
async def test_refresh_with_no_db_row_for_jti_is_uncounted_desync_401(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Redis `session:{jti}` matches the user but NO DB row carries the jti
    (desync) ⇒ the plain re-login 401 (`HTTP_401`, not the dead-row
    `INVALID_TOKEN`), not counted in `refresh_fail`, no token cookie issued."""
    user = regular_user_in_db
    _, refresh, jti = await _login_as(client, user)
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(models.UserSession)
            .where(models.UserSession.refresh_jti == jti)
            .values(refresh_jti=str(uuid.uuid4()))
        )
        await s.commit()
    assert await _row_by_jti(jti) is None, "tiền đề: không hàng nào còn mang jti"
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "tiền đề: khoá session: còn nguyên, khớp người dùng"
    )

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    outcome = (
        res.status_code,
        res.json().get("error_code"),
        await test_redis_client.get(_refresh_fail_key(user)),
    )
    assert outcome == (401, "HTTP_401", None), res.text
    assert _issued_token_cookies(res) == [], _issued_token_cookies(res)


@pytest.mark.asyncio
async def test_refresh_rotation_keeps_absolute_session_expiry(
    client, regular_user_in_db, fresh_breaker
):
    """A successful refresh rotates the row's `refresh_jti` but never moves
    `expires_at`: the session keeps the absolute deadline set at login."""
    _, refresh, jti = await _login_as(client, regular_user_in_db)
    before = await _row_by_jti(jti)

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)
    after = await _row_by_id(before.id)

    assert res.status_code == 200, res.text
    assert after.refresh_jti != jti, "tiền đề: hàng phải được xoay"
    assert after.expires_at == before.expires_at, (
        f"refresh dời hạn phiên: {before.expires_at} -> {after.expires_at}"
    )


async def _wait_for_lock_waiter(timeout: float = 15.0) -> None:
    """Chờ tới khi có một backend đang CHỜ KHOÁ trong CSDL test.

    Mỗi lượt hỏi một kết nối mới: `pg_stat_activity` bị chụp một lần mỗi giao
    dịch, hỏi lại trong cùng giao dịch sẽ không thấy gì mới.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        async with AsyncSessionLocal() as s:
            waiting = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                    )
                )
            ).scalar()
        if waiting:
            return
        await asyncio.sleep(0.05)
    pytest.fail("refresh không hề chờ khoá hàng user_session — tiền đề ca kiểm hỏng")


@pytest.mark.asyncio
async def test_refresh_waits_for_inflight_revoke_then_refuses(
    client, regular_user_in_db, fresh_breaker
):
    """Revoke đang bay (đã UPDATE, chưa COMMIT) thắng refresh đến sau.

    `FOR UPDATE` bắt refresh chờ khoá hàng; PostgreSQL kiểm lại vị từ trên bản
    đã commit ⇒ hàng đã thu hồi ⇒ 401. Thiếu khoá: refresh đọc bản cũ (chưa thu
    hồi), xoay, rồi ghi đè lên đúng hàng vừa bị thu hồi ⇒ 200.
    """
    _, refresh, jti = await _login_as(client, regular_user_in_db)
    row = await _row_by_jti(jti)

    blocker = AsyncSessionLocal()
    try:
        await blocker.execute(
            update(models.UserSession)
            .where(models.UserSession.id == row.id)
            .values(revoked_at=datetime.now(timezone.utc))
        )
        pending = asyncio.create_task(
            _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)
        )
        try:
            await _wait_for_lock_waiter()
        finally:
            await blocker.commit()
        res = await asyncio.wait_for(pending, timeout=30)
    finally:
        await blocker.close()

    assert res.status_code == 401, res.text


# -----------------------------------------------------------------------------
# Breaker mở GIỮA lúc đọc `session:{jti}` thành công và lúc CSDL từ chối: nhánh
# hàng chết không gọi Redis nên kết cục vẫn là 401. Ca này là CHUÔNG cho ai thêm
# lại một lệnh Redis vào nhánh chết: `safe_redis_*` chỉ nuốt
# ConnectionError/TimeoutError, `CircuitBreakerError` đi xuyên qua và rơi vào
# `except Exception` của router ⇒ 500.
# -----------------------------------------------------------------------------

_DEAD_ROW_REFUSAL = ("INVALID_TOKEN", "Invalid or expired refresh token")


async def _assert_refused_like_plain_dead_row(res, test_redis_client, jti, before):
    """Kết cục của refresh bằng hàng chết khi Redis trục trặc phải trùng ca thường."""
    assert res.status_code == 401, res.text
    body = res.json()
    assert (body.get("error_code"), body.get("detail")) == _DEAD_ROW_REFUSAL, res.text
    assert not {"access_token", "refresh_token", "token_type", "user"} & set(body), (
        f"401 mà thân phản hồi mang token/phiên: {res.text}"
    )
    assert "eyJ" not in res.text, f"thân phản hồi chứa chuỗi dạng JWT: {res.text}"
    assert _issued_token_cookies(res) == [], (
        f"status={res.status_code} vẫn phát token: {_issued_token_cookies(res)}"
    )
    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.revoked_at, after.last_activity_at) == (
        jti,
        before.revoked_at,
        before.last_activity_at,
    ), "hàng đã thu hồi bị xoay/chạm tới"
    session_keys = set(await test_redis_client.keys("session:*"))
    assert session_keys <= {f"session:{jti}"}, (
        f"refresh bị từ chối vẫn ghi xoay vào Redis: {sorted(session_keys)}"
    )


@pytest.mark.asyncio
async def test_dead_session_refresh_stays_401_when_breaker_opens_after_session_read(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Breaker mở ngay sau phép GET khoá phiên (tải đồng thời) ⇒ vẫn 401 như thường."""
    _, refresh, jti, before = await _kill_session_during_redis_write_outage(
        client, test_redis_client, regular_user_in_db, fresh_breaker
    )
    real_get = db_module.redis_client.get
    tripped_after = []

    async def _get_then_trip_breaker(key, *args, **kwargs):
        value = await real_get(key, *args, **kwargs)
        if key == f"session:{jti}":
            db_module.redis_breaker.open()
            tripped_after.append(key)
        return value

    with patch.object(db_module.redis_client, "get", _get_then_trip_breaker):
        res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    # Tiền đề: lỗi đã được tiêm THẬT — breaker mở ngay sau phép đọc khoá phiên.
    assert tripped_after == [f"session:{jti}"]
    assert db_module.redis_breaker.current_state == CircuitBreakerState.OPEN

    await _assert_refused_like_plain_dead_row(res, test_redis_client, jti, before)


# -----------------------------------------------------------------------------
# Không đếm ≠ không ghi nhận: từ chối vì hàng chết vẫn là một sự kiện bảo mật,
# và log của nó chỉ mang TIỀN TỐ JTI.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dead_session_refusal_is_logged_as_security_event(
    client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Đúng MỘT sự kiện `REFRESH_DEAD_SESSION`, mang tiền tố JTI và id hàng."""
    _, refresh, jti, before = await _kill_session_during_redis_write_outage(
        client, test_redis_client, regular_user_in_db, fresh_breaker
    )
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app"):
        res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    assert res.status_code == 401, res.text
    events = [
        r.getMessage()
        for r in caplog.records
        if r.name == "app.services.session_service"
        and "REFRESH_DEAD_SESSION" in r.getMessage()
    ]
    assert len(events) == 1, events
    assert f'"old_refresh_jti":"{jti[:8]}"' in events[0], events[0]
    assert f'"session_id":{before.id}' in events[0], events[0]


@pytest.mark.asyncio
async def test_dead_session_refusal_logs_never_carry_the_full_jti(
    client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Không log nào của app (mọi mức, mọi module) trên đường từ chối hàng chết
    in NGUYÊN refresh JTI của phiên."""
    _, refresh, jti, _ = await _kill_session_during_redis_write_outage(
        client, test_redis_client, regular_user_in_db, fresh_breaker
    )
    caplog.clear()

    with caplog.at_level(logging.DEBUG, logger="app"):
        await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    app_logs = [r.getMessage() for r in caplog.records if r.name.startswith("app")]
    assert app_logs, "máy đo hỏng: không bắt được log nào của app"
    lo = [m[:200] for m in app_logs if jti in m]
    assert lo == [], f"log in nguyên JTI của phiên: {lo}"


# -----------------------------------------------------------------------------
# Khoá `session:{jti}` cũ CÒN mà không cấp gì. Mỗi nơi đọc khoá ấy tự tra hàng
# CSDL: refresh (ở trên), deps.py STEP 4b (HTTP), socket connect
# (`_get_user_from_token`) và `revalidate_auth`. Mỗi ca có ĐỐI CHỨNG: cùng token,
# lúc hàng còn sống, được nhận — nên thứ duy nhất đổi giữa hai lần là hàng CSDL.
# -----------------------------------------------------------------------------


@asynccontextmanager
async def _sio():
    """Một Socket.IO client riêng (aiohttp), luôn đóng sạch."""
    import aiohttp

    http = aiohttp.ClientSession()
    sio = socketio.AsyncClient(http_session=http)
    try:
        yield sio
    finally:
        if sio.connected:
            await sio.disconnect()
        await http.close()


@pytest.mark.asyncio
async def test_stale_session_key_does_not_authenticate_http_request(
    client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Access token của phiên đã chết: khoá `session:` còn, deps STEP 4b từ chối."""
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    assert (await _check_access(client, access)).status_code == 200, (
        "đối chứng hỏng: token phải được nhận khi hàng còn sống"
    )
    before = await _logout_during_redis_write_outage(
        client, test_redis_client, user, access, refresh, jti, fresh_breaker
    )
    access_jti = jwt.decode(
        access, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )["jti"]
    assert not await test_redis_client.exists(f"blacklist:{access_jti}"), (
        "tiền đề: access token không bị blacklist"
    )
    assert not await test_redis_client.exists(f"user_blacklist:{user['id']}")
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app"):
        res = await _check_access(client, access)

    assert (res.status_code, res.json().get("error_code")) == (401, "INVALID_TOKEN"), (
        res.text
    )
    assert _issued_token_cookies(res) == [], _issued_token_cookies(res)
    assert any(
        "no non-revoked DB row" in r.getMessage()
        for r in caplog.records
        if r.name == "app.core.deps"
    ), "401 không đến từ phép đối chiếu CSDL của deps STEP 4b"
    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.revoked_at, after.last_activity_at) == (
        jti,
        before.revoked_at,
        before.last_activity_at,
    )


@pytest.mark.asyncio
async def test_stale_session_key_does_not_open_socket_connection(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Socket connect (`_get_user_from_token`) bằng access token của phiên chết:
    khoá `session:` còn, CSDL từ chối, kết nối bị khước."""
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert sio.connected, "đối chứng hỏng: phải kết nối được khi hàng còn sống"

    before = await _logout_during_redis_write_outage(
        client, test_redis_client, user, access, refresh, jti, fresh_breaker
    )
    assert not await test_redis_client.exists(f"user_blacklist:{user['id']}")
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app"):
        async with _sio() as sio:
            with pytest.raises(socketio.exceptions.ConnectionError):
                await sio.connect(
                    test_server, auth={"token": access}, transports=["websocket"]
                )
            assert not sio.connected

    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "khoá session: phải CÒN — thứ khước từ là CSDL, không phải Redis"
    )
    assert any(
        "no non-revoked DB session" in r.getMessage()
        for r in caplog.records
        if r.name == "app.socket_manager"
    ), "khước từ không đến từ phép đối chiếu CSDL của socket connect"
    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.revoked_at, after.last_activity_at) == (
        jti,
        before.revoked_at,
        before.last_activity_at,
    )


@pytest.mark.asyncio
async def test_stale_session_key_fails_socket_revalidation(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Socket ĐANG nối, phiên bị thu hồi trong CSDL mà Redis không hay biết:
    `revalidate_auth` trả không hợp lệ dù khoá `session:` còn.

    Lần kiểm SAU chạy handler thật của server với sid thật, gọi thẳng thay vì qua
    ACK: handler ngắt kết nối TRƯỚC khi trả, nên ACK có thể rơi (cùng lý do
    test_websocket_security chấp nhận TimeoutError) — gọi thẳng thì phán quyết
    luôn đọc được.
    """
    user = regular_user_in_db
    access, _, jti = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert await sio.call("revalidate_auth", timeout=10) == {"valid": True}, (
            "đối chứng hỏng: revalidate phải hợp lệ khi hàng còn sống"
        )
        sid = sio.get_sid("/")

        async with AsyncSessionLocal() as s:
            await s.execute(
                update(models.UserSession)
                .where(models.UserSession.refresh_jti == jti)
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await s.commit()
        before = await _row_by_jti(jti)
        assert await test_redis_client.get(f"session:{jti}") == str(user["id"])
        assert not await test_redis_client.exists(f"user_blacklist:{user['id']}")
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"):
            verdict = await socket_manager.revalidate_auth(sid)

    assert verdict == {"valid": False, "reason": "Session revoked"}, verdict
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "khoá session: phải CÒN — thứ khước từ là CSDL, không phải Redis"
    )
    # Bộ render JSON của log thoát "/" thành "\/" — so phần KHÔNG có "/".
    assert any(
        "in DB (exact jti)" in r.getMessage()
        for r in caplog.records
        if r.name == "app.socket_manager"
    ), "phán quyết không đến từ phép đối chiếu CSDL của revalidate_auth"
    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.revoked_at, after.last_activity_at) == (
        jti,
        before.revoked_at,
        before.last_activity_at,
    )


# -----------------------------------------------------------------------------
# LOGOUT: 204 CHỈ KHI HÀNG CSDL ĐÃ THU HỒI VÀ ĐÃ COMMIT. Hàng CSDL là thứ mọi
# đường đọc phiên tin (deps STEP 4b, socket, `/refresh`); lệnh ghi Redis chỉ là
# lối nhanh — Redis hỏng một mình thì hàng CSDL vẫn khước từ (nhóm ca "khoá cũ
# còn mà không cấp quyền" ngay trên). Khi chính hàng CSDL không được commit, 204
# là lời nói dối: client (`useAuth.ts`) đọc nó là "backend xác nhận phiên chết".
# -----------------------------------------------------------------------------


@contextmanager
def _request_db_commit_fails():
    """Session CSDL của request có `commit()` ném `OperationalError`; mọi thứ khác
    thật. Trả danh sách lượt COMMIT đã thử — để ca kiểm chứng minh lỗi tiêm tới
    được đúng chỗ, không xanh vì COMMIT chưa từng được gọi."""
    from app.main import fastapi_app

    attempts: list = []

    async def _get_db_commit_fails():
        async with AsyncSessionLocal() as s:
            async def _commit():
                attempts.append("commit")
                raise OperationalError(
                    "COMMIT", {}, Exception("tiêm lỗi: CSDL từ chối COMMIT")
                )

            s.commit = _commit
            yield s

    fastapi_app.dependency_overrides[db_module.get_db] = _get_db_commit_fails
    try:
        yield attempts
    finally:
        fastapi_app.dependency_overrides.pop(db_module.get_db, None)


def _status_and_code(res) -> tuple:
    """(status, error_code) — `error_code` là None khi thân rỗng (204)."""
    return res.status_code, (res.json().get("error_code") if res.content else None)


def _deleted_auth_cookies(res) -> set:
    """(tên, path) các cookie token mà phản hồi XOÁ (`Max-Age=0`)."""
    deleted = set()
    for raw in res.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        attrs = {}
        for part in rest.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            attrs[key.lower()] = value
        if name.strip() in ("access_token", "refresh_token") and attrs.get("max-age") == "0":
            deleted.add((name.strip(), attrs.get("path")))
    return deleted


@pytest.mark.asyncio
async def test_logout_is_not_204_when_db_revoke_is_not_committed(
    client, regular_user_in_db, test_redis_client
):
    """COMMIT hỏng, Redis lành ⇒ 500 `SESSION_REVOCATION_ERROR`, không phải 204.

    Tiền đề đo ngay trong ca: lệnh ghi Redis đã chạy (khoá `session:` mất) mà
    hàng CSDL — đọc bằng session MỚI — vẫn sống. Redis lành không cứu được: nguồn
    chuẩn vẫn ghi phiên này là đang sống.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)

    with _request_db_commit_fails() as commits:
        res = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )

    assert commits, "tiền đề: logout phải thử COMMIT"
    assert not await test_redis_client.exists(f"session:{jti}"), (
        "tiền đề: lệnh ghi Redis của logout phải đã chạy"
    )
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, (
        "tiền đề: hàng CSDL phải còn sống sau COMMIT hỏng"
    )
    assert _status_and_code(res) == (500, "SESSION_REVOCATION_ERROR"), (
        f"logout báo {res.status_code} trong khi hàng CSDL chưa thu hồi: {res.text!r}"
    )


@pytest.mark.asyncio
async def test_logout_is_not_204_when_neither_redis_nor_db_revoked_the_session(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Redis từ chối lệnh ghi VÀ COMMIT hỏng ⇒ không 204.

    Không tầng nào thu hồi: Redis hồi lại thì access token cũ vẫn được nhận như
    chưa hề logout. Tiền đề ấy đo TRƯỚC, để thấy một 204 ở đây nói ngược hẳn sự
    thật.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)

    with _redis_writes_down(), _request_db_commit_fails() as commits:
        res = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )
    fresh_breaker()

    assert commits, "tiền đề: logout phải thử COMMIT"
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "tiền đề: lệnh ghi Redis phải hỏng thật — khoá session: còn nguyên"
    )
    assert (await _check_access(client, access)).status_code == 200, (
        "tiền đề: phiên phải còn nguyên — access token cũ vẫn được nhận"
    )
    assert _status_and_code(res) == (500, "SESSION_REVOCATION_ERROR"), (
        f"logout báo {res.status_code} trong khi phiên còn sống: {res.text!r}"
    )


@pytest.mark.asyncio
async def test_logout_failure_response_still_clears_auth_cookies(
    client, regular_user_in_db
):
    """Logout thất bại vẫn XOÁ hai cookie token, đúng path như nhánh 204:
    trình duyệt áp `Set-Cookie` ở mọi mã trạng thái, và client đằng nào cũng đã
    dọn trạng thái cục bộ."""
    access, refresh, _ = await _login_as(client, regular_user_in_db)

    with _request_db_commit_fails() as commits:
        res = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )

    assert commits, "tiền đề: logout phải thử COMMIT"
    assert _deleted_auth_cookies(res) == {("access_token", "/"), ("refresh_token", "/api")}, (
        res.status_code,
        res.headers.get_list("set-cookie"),
    )


# -----------------------------------------------------------------------------
# ĐỐI CHỨNG: thứ KHÔNG phải hàng chết vẫn đếm như cũ. Nhánh không-đếm phải hẹp
# đúng một lỗi miền; nới nó ra là mất bộ đếm chống lạm dụng của mọi ca khác.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blacklisted_refresh_token_is_still_counted(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """`blacklist:{jti}` (token đã xoay/đã logout) ⇒ 401 VÀ `refresh_fail` = 1."""
    user = regular_user_in_db
    _, refresh, jti = await _login_as(client, user)
    await test_redis_client.set(f"blacklist:{jti}", "rotated", ex=300)

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    assert (res.status_code, res.json().get("error_code")) == (401, "INVALID_TOKEN"), (
        res.text
    )
    assert await test_redis_client.get(_refresh_fail_key(user)) == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["revoked", "expired"])
async def test_dead_session_token_already_blacklisted_is_still_counted(
    kind, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Nhánh không-đếm HẸP: chỉ hàng chết do CSDL phán quyết SAU STEP 2. CÙNG
    token của phiên chết mà đã có `blacklist:{jti}` bị chặn NGAY ở STEP 2 và giữ
    chính sách đếm cũ: 401 `INVALID_TOKEN`, `refresh_fail` = 1 (replay token đã
    blacklist vẫn là tín hiệu lạm dụng)."""
    user = regular_user_in_db
    _, refresh, jti, _ = await _dead_session(
        kind, client, test_redis_client, user, fresh_breaker
    )
    await test_redis_client.set(f"blacklist:{jti}", "revoked", ex=300)
    try:
        res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

        assert (res.status_code, res.json().get("error_code")) == (
            401,
            "INVALID_TOKEN",
        ), res.text
        assert await test_redis_client.get(_refresh_fail_key(user)) == "1"
    finally:
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


@pytest.mark.asyncio
async def test_session_miss_refresh_is_still_counted(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Không có `session:{jti}` trong Redis (dấu hiệu dùng lại) ⇒ 401 VÀ đếm.

    Ca này đi qua nhánh `except InvalidToken` BÊN TRONG savepoint — đúng chỗ
    nhánh `RefreshSessionNotLive` được chèn ngay phía trước."""
    user = regular_user_in_db
    _, refresh, jti = await _login_as(client, user)
    await test_redis_client.delete(f"session:{jti}")

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)

    assert (res.status_code, res.json().get("error_code")) == (401, "INVALID_TOKEN"), (
        res.text
    )
    assert await test_redis_client.get(_refresh_fail_key(user)) == "1"


@pytest.mark.asyncio
async def test_access_token_presented_as_refresh_is_still_counted(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Sai loại token (access token trong cookie refresh) ⇒ 401 VÀ đếm."""
    user = regular_user_in_db
    access, _, _ = await _login_as(client, user)

    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=access)

    assert (res.status_code, res.json().get("error_code")) == (401, "INVALID_TOKEN"), (
        res.text
    )
    assert await test_redis_client.get(_refresh_fail_key(user)) == "1"


@pytest.mark.asyncio
async def test_counted_failures_still_revoke_all_sessions_at_threshold(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """`REFRESH_MAX_FAILURES` lần lỗi ĐƯỢC ĐẾM ⇒ vẫn `invalidate_all_sessions`:
    có `user_blacklist`, phiên khác của người dùng hết refresh được."""
    _kiem_ua_phan_loai_dong()
    user = regular_user_in_db
    _, refresh_bad, jti_bad = await _login_as(client, user, ua=UA_DESKTOP)
    _, refresh_live, _ = await _login_as(client, user, ua=UA_MOBILE)
    await test_redis_client.set(f"blacklist:{jti_bad}", "rotated", ex=300)
    try:
        for _ in range(settings.REFRESH_MAX_FAILURES):
            await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_bad)

        assert await test_redis_client.exists(f"user_blacklist:{user['id']}"), (
            "ngưỡng lạm dụng không còn kích hoạt invalidate_all_sessions"
        )
        # Cổng M4 khoá theo USERNAME nên phiên kia nhận 429 REFRESH_ABUSE_LOCKED
        # (hoặc 401 nếu cổng ấy đổi) — điều ca này canh là: KHÔNG còn xoay được.
        live = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_live)
        assert live.status_code != 200 and _issued_token_cookies(live) == [], live.text
    finally:
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


# -----------------------------------------------------------------------------
# NGƯỠNG LẠM DỤNG: `invalidate_all_sessions` chỉ flush — router phải COMMIT. Nhánh
# ngưỡng từng không commit: hàng CSDL quay lui khi session của request đóng, còn
# phía Redis (`user_blacklist`, `session:*`) đã ghi — trạng thái tách đôi. Mọi
# phép đọc CSDL ở đây dùng session MỚI, không phải session của request.
# -----------------------------------------------------------------------------


async def _live_session_jtis(user_id: int) -> list:
    """`refresh_jti` các hàng CHƯA thu hồi của người dùng (session CSDL mới)."""
    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.UserSession.refresh_jti).where(
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None),
            )
        )
        return sorted(rows.scalars().all())


async def _two_live_sessions_one_blacklisted(client, test_redis_client, user: dict):
    """Hai phiên sống (desktop + mobile); refresh token phiên desktop đã blacklist."""
    _kiem_ua_phan_loai_dong()
    _, refresh_bad, jti_bad = await _login_as(client, user, ua=UA_DESKTOP)
    _, _, jti_live = await _login_as(client, user, ua=UA_MOBILE)
    await test_redis_client.set(f"blacklist:{jti_bad}", "rotated", ex=300)
    assert await _live_session_jtis(user["id"]) == sorted([jti_bad, jti_live]), (
        "tiền đề: hai hàng phiên phải cùng sống trước khi chạm ngưỡng"
    )
    return refresh_bad, jti_bad, jti_live


@pytest.mark.asyncio
async def test_refresh_abuse_threshold_revocation_is_committed(
    client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Chạm `REFRESH_MAX_FAILURES` ⇒ mọi hàng phiên của người dùng đã thu hồi VÀ
    đã commit — đọc bằng session CSDL mới sau khi request kết thúc.

    Tiền đề: phía Redis của `invalidate_all_sessions` đã chạy (`user_blacklist`);
    thiếu nó thì "hàng còn sống" có thể chỉ vì nhánh ngưỡng không chạy.
    """
    user = regular_user_in_db
    refresh_bad, _, _ = await _two_live_sessions_one_blacklisted(
        client, test_redis_client, user
    )
    try:
        for _ in range(settings.REFRESH_MAX_FAILURES):
            await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_bad)

        assert await test_redis_client.exists(f"user_blacklist:{user['id']}"), (
            "tiền đề: nhánh ngưỡng phải chạy invalidate_all_sessions"
        )
        live = await _live_session_jtis(user["id"])
        assert live == [], (
            f"Redis đã thu hồi mà {len(live)} hàng phiên vẫn sống trong CSDL"
        )
    finally:
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


@pytest.mark.asyncio
async def test_refresh_abuse_threshold_commit_failure_is_still_401(
    client, regular_user_in_db, test_redis_client, fresh_breaker, monkeypatch, caplog
):
    """COMMIT của nhánh ngưỡng hỏng ⇒ vẫn 401 `INVALID_TOKEN` như mọi lần đếm,
    không 500, và lỗi được ghi log. Hàng phiên khi ấy còn sống: đó là trạng thái
    tách đôi duy nhất còn lại, và nó hiện trong log thay vì im lặng."""
    from app.services import user_service

    user = regular_user_in_db
    refresh_bad, _, _ = await _two_live_sessions_one_blacklisted(
        client, test_redis_client, user
    )
    real_invalidate = user_service.invalidate_all_sessions
    commits: list = []

    async def _invalidate_then_break_commit(db, target, **kwargs):
        await real_invalidate(db, target, **kwargs)

        async def _commit():
            commits.append("commit")
            raise OperationalError("COMMIT", {}, Exception("tiêm lỗi: CSDL từ chối COMMIT"))

        db.commit = _commit

    try:
        for _ in range(settings.REFRESH_MAX_FAILURES - 1):
            await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_bad)
        monkeypatch.setattr(
            user_service, "invalidate_all_sessions", _invalidate_then_break_commit
        )
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="app"):
            res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_bad)

        assert commits, "tiền đề: nhánh ngưỡng phải thử COMMIT"
        assert (res.status_code, res.json().get("error_code")) == (401, "INVALID_TOKEN"), (
            res.text
        )
        assert any(
            "Failed to revoke sessions after refresh abuse" in r.getMessage()
            for r in caplog.records
            if r.name == "app.routers.auth"
        ), "COMMIT hỏng mà không có dòng log nào"
    finally:
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


@pytest.mark.asyncio
async def test_concurrent_threshold_crossings_commit_one_consistent_revocation(
    client, regular_user_in_db, test_redis_client, fresh_breaker, monkeypatch, caplog
):
    """Hai refresh hỏng CÙNG vượt ngưỡng ⇒ hai `invalidate_all_sessions` + COMMIT
    song song: cả hai 401 (không 500), không kẹt khoá, trạng thái cuối nhất quán
    — mọi hàng đã thu hồi (session CSDL mới), có `user_blacklist`, hết `session:`.

    Hai rào ép đúng kịch bản thay vì trông vào lập lịch: cả hai request đọc bộ
    đếm ở cổng M4 TRƯỚC khi request nào ghi nó (nên cả hai qua cổng và cùng chạm
    ngưỡng — đúng chỗ đếm GET→SET không nguyên tử), rồi cả hai vào
    `invalidate_all_sessions` cùng lúc (nên hai `SELECT … FOR UPDATE` tranh nhau
    thật). Rào hết giờ ⇒ đỏ ở tiền đề, không treo.
    """
    from app.routers import auth as auth_router
    from app.services import user_service

    user = regular_user_in_db
    fail_key = _refresh_fail_key(user)
    refresh_bad, jti_bad, jti_live = await _two_live_sessions_one_blacklisted(
        client, test_redis_client, user
    )
    await test_redis_client.set(fail_key, str(settings.REFRESH_MAX_FAILURES - 1), ex=300)

    gate = asyncio.Barrier(2)
    revoke = asyncio.Barrier(2)
    gate_reads: list = []
    passed_gate: list = []
    entered_revoke: list = []
    real_get = auth_router.safe_redis_get
    real_invalidate = user_service.invalidate_all_sessions

    async def _get(key, *args, **kwargs):
        value = await real_get(key, *args, **kwargs)
        if key == fail_key and len(gate_reads) < 2:
            gate_reads.append(value)
            await asyncio.wait_for(gate.wait(), 10)
            passed_gate.append(value)
        return value

    async def _invalidate(db, target, **kwargs):
        await asyncio.wait_for(revoke.wait(), 10)
        entered_revoke.append(target.id)
        return await real_invalidate(db, target, **kwargs)

    monkeypatch.setattr(auth_router, "safe_redis_get", _get)
    monkeypatch.setattr(user_service, "invalidate_all_sessions", _invalidate)

    async def _refresh():
        return await client.post(
            REFRESH_URL, headers={"Cookie": f"refresh_token={refresh_bad}"}
        )

    try:
        client.cookies.clear()
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="app"):
            results = await asyncio.wait_for(asyncio.gather(_refresh(), _refresh()), 60)
        client.cookies.clear()

        assert passed_gate == [str(settings.REFRESH_MAX_FAILURES - 1)] * 2, (
            "tiền đề: cả hai phải đọc bộ đếm ở cổng trước khi nó bị ghi",
            gate_reads,
            passed_gate,
        )
        assert entered_revoke == [user["id"]] * 2, (
            "tiền đề: cả hai phải cùng vào invalidate_all_sessions",
            entered_revoke,
        )
        assert [r.status_code for r in results] == [401, 401], [r.text for r in results]
        failures = [
            r.getMessage()
            for r in caplog.records
            if r.name == "app.routers.auth"
            and "Failed to revoke sessions after refresh abuse" in r.getMessage()
        ]
        assert failures == [], failures
        assert await _live_session_jtis(user["id"]) == [], (
            "hàng phiên vẫn sống trong CSDL sau hai lần thu hồi"
        )
        assert await test_redis_client.exists(f"user_blacklist:{user['id']}")
        assert (
            await test_redis_client.exists(f"session:{jti_bad}", f"session:{jti_live}") == 0
        )
    finally:
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


# -----------------------------------------------------------------------------
# LOGOUT KHÔNG PHỤ THUỘC REDIS. `get_current_user` trả 503 khi Redis không trả
# lời lượt đọc `user_blacklist` — đúng cho mọi endpoint CẤP quyền. `/logout` chỉ
# HUỶ phiên, không cấp gì, nên đi đường riêng (`deps.get_logout_target`): chữ ký
# của access token + hàng CSDL của CHÍNH user đó. Hàng CSDL quyết định kết quả;
# lệnh ghi Redis chỉ là lối nhanh, và chỉ chạm jti đã được xác nhận là của user.
# -----------------------------------------------------------------------------

_REDIS_READ_COMMANDS = ("get", "exists", "ttl")


@contextmanager
def _redis_unreachable(fault: str):
    """Redis không trả lời, hai trạng thái của một sự cố thật.

    * ``connection``: mọi lệnh ĐỌC lẫn GHI của client dùng chung ném
      ConnectionError, breaker còn CLOSED (sự cố vừa bắt đầu).
    * ``breaker_open``: breaker OPEN (sự cố đã ổn định) — lệnh không tới Redis.

    Cần fixture ``fresh_breaker`` (breaker riêng mỗi ca) và gọi nó sau khối này.
    """
    if fault == "breaker_open":
        db_module.redis_breaker.open()
        yield
        return
    assert fault == "connection", fault

    async def _down(*args, **kwargs):
        raise RedisConnectionError("tiêm lỗi: Redis không trả lời")

    with ExitStack() as stack:
        for name in _REDIS_READ_COMMANDS + _REDIS_WRITE_COMMANDS:
            stack.enter_context(patch.object(db_module.redis_client, name, _down))
        yield


_AUTH_COOKIES_CLEARED = {("access_token", "/"), ("refresh_token", "/api")}


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_logout_revokes_the_db_session_while_redis_does_not_answer(
    fault, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Redis không trả lời ⇒ logout vẫn thu hồi hàng CSDL, COMMIT, 204, xoá cookie.

    Tiền đề đo SAU ca: lệnh ghi Redis đã hỏng thật (khoá `session:` còn nguyên).
    204 phải là sự thật: Redis hồi, access token cũ bị khước từ ở deps STEP 4b
    chỉ nhờ hàng CSDL đã thu hồi.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)

    with _redis_unreachable(fault):
        res = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )
    fresh_breaker()

    assert res.status_code == 204, f"logout khi Redis không trả lời: {res.text!r}"
    assert _deleted_auth_cookies(res) == _AUTH_COOKIES_CLEARED, res.headers.get_list(
        "set-cookie"
    )
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, (
        "hàng CSDL phải đã thu hồi VÀ commit (đọc bằng session mới)"
    )
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "tiền đề: lệnh ghi Redis phải hỏng thật — khoá session: còn nguyên"
    )
    assert (await _check_access(client, access)).status_code == 401, (
        "Redis hồi mà access token cũ vẫn được nhận: 204 đã nói sai"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_logout_commit_failure_while_redis_does_not_answer_is_not_204(
    fault, client, regular_user_in_db, fresh_breaker
):
    """Redis không trả lời VÀ COMMIT hỏng ⇒ 500 `SESSION_REVOCATION_ERROR`, xoá cookie.

    Không tầng nào xác nhận được việc thu hồi, nên không có 204; cookie vẫn xoá
    như mọi phản hồi logout.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)

    with _redis_unreachable(fault), _request_db_commit_fails() as commits:
        res = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )
    fresh_breaker()

    assert _status_and_code(res) == (500, "SESSION_REVOCATION_ERROR"), (
        f"logout báo {res.status_code} trong khi không gì được thu hồi: {res.text!r}"
    )
    assert commits, "tiền đề: logout phải thử COMMIT"
    assert _deleted_auth_cookies(res) == _AUTH_COOKIES_CLEARED, res.headers.get_list(
        "set-cookie"
    )
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, (
        "tiền đề: hàng CSDL phải còn sống sau COMMIT hỏng"
    )


@pytest.mark.asyncio
async def test_logout_with_another_users_refresh_cookie_leaves_that_session_alone(
    client, regular_user_in_db, admin_user_in_db, test_redis_client, fresh_breaker
):
    """Access token của A + cookie refresh của B ⇒ phiên của B không bị đụng tới.

    Không thu hồi hàng CSDL của B, không xoá `session:{jti_B}`, không ghi
    `blacklist:{jti_B}`, và access token của B vẫn được nhận. Bản trước ghi Redis
    cho jti của cookie refresh TRƯỚC khi kiểm hàng phiên thuộc ai.
    """
    victim = admin_user_in_db
    victim_access, victim_refresh, victim_jti = await _login_as(client, victim)
    access, _, _ = await _login_as(client, regular_user_in_db)

    res = await _post_with_cookies(
        client, LOGOUT_URL, access_token=access, refresh_token=victim_refresh
    )

    victim_row = await _row_by_jti(victim_jti)
    assert victim_row is not None and victim_row.revoked_at is None, (
        "logout của A đã thu hồi hàng phiên của B"
    )
    assert await test_redis_client.get(f"session:{victim_jti}") == str(victim["id"]), (
        f"logout của A đã xoá khoá session: của B (status {res.status_code})"
    )
    assert not await test_redis_client.exists(f"blacklist:{victim_jti}"), (
        "logout của A đã blacklist refresh jti của B"
    )
    assert (await _check_access(client, victim_access)).status_code == 200, (
        "access token của B bị khước từ sau logout của A"
    )


@pytest.mark.asyncio
async def test_bearer_only_logout_revokes_the_session_of_the_access_token(
    client, regular_user_in_db
):
    """Không có cookie refresh (client chỉ gửi Bearer) ⇒ vẫn thu hồi phiên mà
    access token thuộc về (`r_jti`), rồi mới 204. Bản trước trả 204 mà không thu
    hồi gì — nợ A2 ghi lại."""
    access, _, jti = await _login_as(client, regular_user_in_db)

    client.cookies.clear()
    try:
        res = await client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {access}"})
    finally:
        client.cookies.clear()

    assert res.status_code == 204, res.text
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, (
        "logout chỉ-Bearer trả 204 mà hàng phiên của access token vẫn sống"
    )


_LOGOUT_DB_READS = {
    "user": "app.services.user_service.get_user_by_username",
    "session_row": (
        "app.repositories.session_repository.SessionRepository.get_by_refresh_jti_and_user"
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("read", sorted(_LOGOUT_DB_READS))
async def test_logout_db_read_failure_in_dependency_is_not_204_and_writes_nothing(
    read, client, regular_user_in_db, test_redis_client
):
    """`get_logout_target` không đọc được CSDL (tra user, hoặc tra hàng phiên) ⇒
    500 `SESSION_REVOCATION_ERROR`, xoá cả hai cookie, KHÔNG ghi Redis, hàng phiên
    vẫn sống. Không biết hàng nào của ai thì không được thu hồi gì, không được
    nói 204 (nhánh `sessions=None`).

    Redis đo bằng khoá THẬT sau request: lệnh ghi của logout sẽ xoá
    `session:{jti}` hoặc đặt `blacklist:{jti}` / `blacklist:{access_jti}`.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    access_jti = jwt.decode(
        access, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )["jti"]
    hits: list = []

    async def _db_read_fails(*args, **kwargs):
        hits.append(read)
        raise OperationalError("SELECT", {}, Exception("tiêm lỗi: CSDL không đọc được"))

    with patch(_LOGOUT_DB_READS[read], new=_db_read_fails):
        res = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )

    assert _status_and_code(res) == (500, "SESSION_REVOCATION_ERROR"), (
        f"logout báo {res.status_code} khi chưa đọc được CSDL: {res.text!r}"
    )
    assert hits, "tiền đề: lỗi phải được tiêm tới đúng lượt đọc CSDL của dependency"
    assert _deleted_auth_cookies(res) == _AUTH_COOKIES_CLEARED, res.headers.get_list(
        "set-cookie"
    )
    assert not await test_redis_client.exists(f"blacklist:{access_jti}"), (
        "logout đã blacklist access token khi chưa đọc được CSDL"
    )
    assert not await test_redis_client.exists(f"blacklist:{jti}"), (
        "logout đã blacklist refresh jti khi chưa đọc được CSDL"
    )
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "logout đã xoá khoá session: khi chưa đọc được CSDL"
    )
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, (
        "hàng phiên bị thu hồi dù CSDL không đọc được"
    )


@pytest.mark.asyncio
async def test_logout_ends_both_sessions_when_access_token_and_refresh_cookie_differ(
    client, regular_user_in_db, test_redis_client
):
    """Access token của phiên 1 + cookie refresh của phiên 2, CÙNG user ⇒ 204 và
    CẢ HAI phiên kết thúc: hai hàng CSDL thu hồi, hai khoá `session:` mất, hai
    `blacklist:` được đặt. Lựa chọn thiết kế ghi ở docstring `get_logout_target`;
    đổi thành "chỉ một phiên" thì phải sửa ca này."""
    _kiem_ua_phan_loai_dong()
    user = regular_user_in_db
    access_1, _, jti_1 = await _login_as(client, user, ua=UA_DESKTOP)
    _, refresh_2, jti_2 = await _login_as(client, user, ua=UA_MOBILE)
    sessions = {"phiên của access token": jti_1, "phiên của cookie refresh": jti_2}
    assert jti_1 != jti_2
    for label, jti in sessions.items():
        row = await _row_by_jti(jti)
        assert row is not None and row.revoked_at is None, f"tiền đề: {label} phải sống"

    res = await _post_with_cookies(
        client, LOGOUT_URL, access_token=access_1, refresh_token=refresh_2
    )

    assert res.status_code == 204, res.text
    for label, jti in sessions.items():
        row = await _row_by_jti(jti)
        assert row is not None and row.revoked_at is not None, f"{label} vẫn sống"
        assert not await test_redis_client.exists(f"session:{jti}"), (
            f"khoá session: của {label} còn"
        )
        assert await test_redis_client.get(f"blacklist:{jti}") == "revoked", (
            f"thiếu blacklist cho {label}"
        )


# -----------------------------------------------------------------------------
# TÍCH HỢP: "`session:` không trả lời ⇒ hàng CSDL quyết" (deps STEP 4/4b và
# `revalidate_auth`) GẶP logout COMMIT hỏng (A2), ngưỡng `refresh_fail` (A1) và
# refresh xoay. Để hàng CSDL quyết chỉ an toàn khi mọi thu hồi đã COMMIT vào
# hàng CSDL, hoặc khi bản ghi CHỈ Redis giữ (`blacklist:{access_jti}`) được TRẢ
# LỜI trước STEP 4. Mỗi ca chạy CHUỖI THẬT (đăng nhập → logout / ngưỡng / xoay →
# request) rồi mới tiêm lỗi đọc, để thấy TẦNG NÀO đang khước từ.
#
# `_reads_unanswered`: `connection` ném ConnectionError ở CLIENT cho GET/EXISTS
# các khoá dưới tiền tố (breaker CLOSED); `breaker_open` là breaker THẬT mở đúng
# cho lượt đọc ấy rồi đóng lại — lượt đọc đang xét là lượt DUY NHẤT Redis không
# trả lời. Cùng cơ chế với `_reads_unanswered` của
# tests/services/test_auth_security_hardening.py; bản này đọc
# `db_module.redis_breaker` lúc vào khối nên đi với `fresh_breaker`.
# -----------------------------------------------------------------------------

_UNANSWERED_READS = ("get", "exists")


def _dong_breaker(breaker) -> None:
    """Breaker về CLOSED, bộ đếm 0 (như `_reset_redis_breaker` của tệp hardening)."""
    breaker.close()
    breaker._state_storage.reset_counter()
    breaker._state_storage.opened_at = None
    assert breaker.current_state is CircuitBreakerState.CLOSED


@contextmanager
def _reads_unanswered(fault: str, *prefixes: str):
    """Redis KHÔNG trả lời GET/EXISTS các khoá dưới ``prefixes``; khoá khác vẫn được phục vụ.

    Trả danh sách khoá lỗi đã chạm — để ca kiểm chứng minh lỗi tới đúng lượt
    đọc đang xét (hoặc chứng minh lượt ấy KHÔNG được chạm).
    """
    hit: list = []
    if fault == "connection":

        def _wrap(command):
            original = getattr(db_module.redis_client, command)

            async def _command(*args, **kwargs):
                key = args[0] if args else None
                if isinstance(key, str) and key.startswith(prefixes):
                    hit.append(key)
                    raise RedisConnectionError("tiêm lỗi: Redis không trả lời lượt đọc này")
                return await original(*args, **kwargs)

            return _command

        with ExitStack() as stack:
            for command in _UNANSWERED_READS:
                stack.enter_context(
                    patch.object(db_module.redis_client, command, _wrap(command))
                )
            yield hit
        return
    assert fault == "breaker_open", fault
    breaker = db_module.redis_breaker
    original_call = breaker.call_async

    async def _call(func, *args, **kwargs):
        key = args[0] if args else None
        if (
            getattr(func, "__name__", None) in _UNANSWERED_READS
            and isinstance(key, str)
            and key.startswith(prefixes)
        ):
            hit.append(key)
            breaker.open()
            try:
                return await original_call(func, *args, **kwargs)
            finally:
                _dong_breaker(breaker)
        return await original_call(func, *args, **kwargs)

    with patch.object(breaker, "call_async", _call):
        yield hit


@contextmanager
def _spy_session_row_reads():
    """Ghi lại mọi lượt `get_by_refresh_jti_and_user` (deps STEP 4b, socket) rồi chạy thật."""
    from app.repositories import SessionRepository

    original = SessionRepository.get_by_refresh_jti_and_user
    calls: list = []

    async def _spy(self, *args, **kwargs):
        calls.append(args)
        return await original(self, *args, **kwargs)

    with patch.object(SessionRepository, "get_by_refresh_jti_and_user", _spy):
        yield calls


def _access_jti(access_token: str) -> str:
    return jwt.decode(
        access_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )["jti"]


def _logs(caplog, logger: str) -> list:
    return [r.getMessage() for r in caplog.records if r.name == logger]


async def _logout_commit_fails(
    client, test_redis_client, user: dict, access: str, refresh: str, jti: str
):
    """A2 theo luồng THẬT: logout mà COMMIT hỏng, Redis lành. Trả hàng CSDL sau đó.

    Kiểm TIỀN ĐỀ ngay tại đây: logout báo 500 `SESSION_REVOCATION_ERROR`; hàng
    CSDL còn SỐNG (COMMIT hỏng); lệnh ghi Redis của logout đã chạy — khoá
    `session:` mất, `blacklist:{access_jti}` đã đặt (bản ghi CHỈ Redis giữ).
    """
    with _request_db_commit_fails() as commits:
        out = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )
    assert commits, "tiền đề: logout phải thử COMMIT"
    assert _status_and_code(out) == (500, "SESSION_REVOCATION_ERROR"), out.text
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, (
        "tiền đề: hàng CSDL phải còn sống sau COMMIT hỏng"
    )
    assert not await test_redis_client.exists(f"session:{jti}"), (
        "tiền đề: logout phải đã xoá khoá session:"
    )
    assert await test_redis_client.get(f"blacklist:{_access_jti(access)}") == "revoked", (
        "tiền đề: logout phải đã blacklist access token của nó"
    )
    assert not await test_redis_client.exists(f"user_blacklist:{user['id']}")
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_logout_commit_failure_then_session_cache_unreadable_is_refused_at_step2(
    fault, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Ô b1: A2 rồi access token CŨ khi CHỈ `session:` không trả lời ⇒ 401 từ STEP 2.

    Hàng CSDL còn sống, nên nếu request tới STEP 4 thì lượt đọc `session:` không
    trả lời ⇒ hàng CSDL quyết ⇒ 200. Thứ duy nhất khước từ token này là
    `blacklist:{access_jti}` mà STEP 2 đọc và Redis TRẢ LỜI. Nguồn được đo, không
    suy: lượt đọc `session:` (STEP 4) và phép đối chiếu CSDL (STEP 4b) đều KHÔNG
    được chạm.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    assert (await _check_access(client, access)).status_code == 200, (
        "đối chứng hỏng: token phải được nhận trước logout"
    )
    await _logout_commit_fails(client, test_redis_client, user, access, refresh, jti)

    with _reads_unanswered(fault, "session:") as hit, _spy_session_row_reads() as db_reads:
        res = await _check_access(client, access)

    assert _status_and_code(res) == (401, "INVALID_TOKEN"), (
        f"access token đã logout (COMMIT hỏng) được nhận: {res.text!r}"
    )
    assert _issued_token_cookies(res) == [], _issued_token_cookies(res)
    assert hit == [], f"STEP 4 đã được chạm — từ chối không đến từ STEP 2: {hit}"
    assert db_reads == [], f"STEP 4b đã được chạm: {db_reads}"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_logout_commit_failure_then_access_blacklist_unreadable_too_is_503(
    fault, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Ô b1, biến thể: `blacklist:` CŨNG không trả lời ⇒ 503 `AUTH_STATE_UNAVAILABLE`.

    Không bao giờ 200 từ nhánh "hàng CSDL quyết": STEP 2 không có câu trả lời thì
    dừng ở 503, trước khi `session:` hay hàng CSDL được hỏi.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    await _logout_commit_fails(client, test_redis_client, user, access, refresh, jti)

    with _reads_unanswered(fault, "blacklist:", "session:") as hit, \
            _spy_session_row_reads() as db_reads:
        res = await _check_access(client, access)

    assert _status_and_code(res) == (503, "AUTH_STATE_UNAVAILABLE"), (
        f"STEP 2 không trả lời mà không phải 503: {res.status_code} {res.text!r}"
    )
    assert _issued_token_cookies(res) == [], _issued_token_cookies(res)
    assert hit == [f"blacklist:{_access_jti(access)}"], hit
    assert db_reads == [], f"STEP 4b đã được chạm: {db_reads}"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_threshold_revocation_then_relogin_old_access_token_is_refused_by_db_row(
    fault, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô b6: ngưỡng `refresh_fail` (A1) → đăng nhập lại → access token CŨ khi
    `session:` không trả lời ⇒ 401 từ STEP 4b.

    Đăng nhập lại xoá `user_blacklist` — bản ghi Redis của việc thu hồi toàn bộ;
    khoá `session:` cũ đã bị xoá nhưng lượt đọc nó không được trả lời, nên hàng
    CSDL quyết. Hàng ấy chết CHỈ vì nhánh ngưỡng đã COMMIT: thiếu COMMIT thì hàng
    quay lui về sống và token cũ được nhận (200).

    Đăng nhập lại từ THIẾT BỊ KHÁC: cùng thiết bị thì chính lượt đăng nhập thu hồi
    hàng cũ và che mất điều đang đo.
    """
    _kiem_ua_phan_loai_dong()
    user = regular_user_in_db
    access_old, refresh_old, jti_old = await _login_as(client, user, ua=UA_MOBILE)
    assert (await _check_access(client, access_old)).status_code == 200, (
        "đối chứng hỏng: token phải được nhận trước khi chạm ngưỡng"
    )
    await test_redis_client.set(f"blacklist:{jti_old}", "rotated", ex=300)
    try:
        statuses = [
            (await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_old)).status_code
            for _ in range(settings.REFRESH_MAX_FAILURES)
        ]
        assert statuses == [401] * settings.REFRESH_MAX_FAILURES, statuses
        assert await test_redis_client.exists(f"user_blacklist:{user['id']}"), (
            "tiền đề: nhánh ngưỡng phải chạy invalidate_all_sessions"
        )
        assert not await test_redis_client.exists(f"session:{jti_old}"), (
            "tiền đề: invalidate_all_sessions phải xoá khoá session: cũ"
        )

        await _login_as(client, user, ua=UA_DESKTOP)
        assert not await test_redis_client.exists(f"user_blacklist:{user['id']}"), (
            "tiền đề: đăng nhập lại phải xoá user_blacklist"
        )
        # Redis lành: miss đã trả lời khước từ ở lối nhanh, dù hàng CSDL sống
        # hay chết — đối chứng này KHÔNG phân biệt được nhánh ngưỡng có COMMIT.
        assert (await _check_access(client, access_old)).status_code == 401
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"):
            with _reads_unanswered(fault, "session:") as hit:
                res = await _check_access(client, access_old)

        assert _status_and_code(res) == (401, "INVALID_TOKEN"), (
            f"access token của phiên đã thu hồi ở ngưỡng được nhận: {res.text!r}"
        )
        assert hit == [f"session:{jti_old}"], hit
        assert any(
            "no non-revoked DB row" in m for m in _logs(caplog, "app.core.deps")
        ), "401 không đến từ phép đối chiếu CSDL của deps STEP 4b"
        row = await _row_by_jti(jti_old)
        assert row is not None and row.revoked_at is not None, (
            "hàng phiên cũ phải đã thu hồi VÀ commit"
        )
    finally:
        await test_redis_client.delete(f"user_blacklist:{user['id']}")


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_failed_logout_socket_session_unreadable_stays_valid_OWNER_DECISION(
    fault, test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """Ô b7 — GHIM một ĐÁNH ĐỔI có chủ ý, KHÔNG phải hành vi mong muốn.

    A2: logout COMMIT hỏng (client nhận 500) ⇒ hàng CSDL sống, Redis đã xoá
    `session:` và đặt `blacklist:{access_jti}`. Socket không đọc
    `blacklist:{access_jti}` (cả connect lẫn revalidate). Khi RIÊNG lượt đọc
    `session:` không được trả lời, `revalidate_auth` để hàng CSDL quyết ⇒
    `valid: True` (trước khi `session:` được đọc theo ba câu trả lời: ngắt).
    Đánh đổi ghi ở báo cáo lát S24 (§2 "Đánh đổi", §8 mục 3): nó chỉ kéo dài
    trong lúc chính lượt đọc ấy không được trả lời — Redis trả lời lại thì lối
    nhanh ngắt ngay (`test_socket_revalidate_answered_miss_is_still_revoked`).
    Đổi hành vi này (ngắt, hay đọc thêm `blacklist:{access_jti}` ở socket) là
    quyết định của owner: sửa ca này cùng lúc.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert await sio.call("revalidate_auth", timeout=10) == {"valid": True}, (
            "đối chứng hỏng: revalidate phải hợp lệ trước logout"
        )
        sid = sio.get_sid("/")
        await _logout_commit_fails(client, test_redis_client, user, access, refresh, jti)

        with _reads_unanswered(fault, "session:") as hit:
            verdict = await socket_manager.revalidate_auth(sid)

    assert hit == [f"session:{jti}"], hit
    assert verdict == {"valid": True}, verdict


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["answered", "connection", "breaker_open"])
async def test_socket_revalidate_after_refresh_rotation_is_never_valid(
    fault, test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô b8: socket nối TRƯỚC khi /refresh xoay vẫn giữ jti CŨ; revalidate với jti
    ấy không bao giờ `valid: True`, Redis trả lời hay không.

    Thiết kế hiện tại: `connect` lưu `r_jti` của access token lúc nối vào phiên
    socket; /refresh không chạm phiên socket. Sau xoay, `session:{cũ}` đã xoá ⇒
    Redis trả lời thì lối nhanh khước từ; hàng CSDL đã mang jti MỚI ⇒ Redis không
    trả lời thì phép đối chiếu exact-jti khước từ.

    Hệ quả (NỢ, ngoài lát này): frontend coi mọi `valid: false` là đăng xuất và
    không nối lại socket sau refresh (`frontend/src/lib/socket/client.ts`,
    `components/layouts/SocketHandler.tsx`) ⇒ người dùng bị đăng xuất ở lượt
    revalidate kế tiếp sau một lần xoay. Vá nợ ấy bằng cách cập nhật jti của phiên
    socket khi xoay sẽ làm đỏ TIỀN ĐỀ "phiên socket giữ jti cũ": sửa ca cùng lúc.
    """
    user = regular_user_in_db
    access, refresh, jti_old = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert await sio.call("revalidate_auth", timeout=10) == {"valid": True}, (
            "đối chứng hỏng: revalidate phải hợp lệ trước khi xoay"
        )
        sid = sio.get_sid("/")

        rotated = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)
        assert rotated.status_code == 200, rotated.text
        jti_new = jwt.decode(
            rotated.cookies.get("refresh_token"),
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )["jti"]
        assert jti_new != jti_old
        assert await _row_by_jti(jti_old) is None, "tiền đề: hàng CSDL phải đã mang jti mới"
        assert (await _row_by_jti(jti_new)).revoked_at is None
        assert not await test_redis_client.exists(f"session:{jti_old}")
        assert (await socket_manager.sio.get_session(sid))["jti"] == jti_old, (
            "tiền đề: phiên socket phải giữ jti CŨ — thiết kế đã đổi thì sửa ca này"
        )
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), ExitStack() as stack:
            hit = (
                []
                if fault == "answered"
                else stack.enter_context(_reads_unanswered(fault, "session:"))
            )
            verdict = await socket_manager.revalidate_auth(sid)

    assert verdict == {"valid": False, "reason": "Session revoked"}, verdict
    logs = _logs(caplog, "app.socket_manager")
    from_db = any("in DB (exact jti)" in m for m in logs)
    fast_path = any("Revalidation failed: Session revoked" in m for m in logs)
    if fault == "answered":
        assert hit == []
        assert fast_path and not from_db, f"khước từ không đến từ lối nhanh: {logs}"
    else:
        assert hit == [f"session:{jti_old}"], hit
        assert from_db and not fast_path, f"khước từ không đến từ phép đối chiếu CSDL: {logs}"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["answered", "connection", "breaker_open"])
async def test_old_access_token_after_refresh_rotation_is_refused(
    fault, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô b8, nửa HTTP: access token CŨ sau xoay ⇒ 401, Redis trả lời hay không.

    Xoay KHÔNG blacklist access token cũ (chỉ refresh jti cũ); token ấy sống tới
    `exp` và chỉ bị khước từ ở STEP 4: Redis trả lời ⇒ lối nhanh (`session:{cũ}`
    đã xoá); Redis không trả lời ⇒ STEP 4b (hàng CSDL đã mang jti mới).
    """
    user = regular_user_in_db
    access_old, refresh, jti_old = await _login_as(client, user)
    rotated = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)
    assert rotated.status_code == 200, rotated.text
    assert not await test_redis_client.exists(f"blacklist:{_access_jti(access_old)}"), (
        "tiền đề: xoay không blacklist access token cũ"
    )
    assert await _row_by_jti(jti_old) is None, "tiền đề: hàng CSDL phải đã mang jti mới"
    assert (await _check_access(client, rotated.cookies.get("access_token"))).status_code == 200, (
        "đối chứng hỏng: phiên sau xoay phải sống"
    )
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app"), ExitStack() as stack:
        hit = (
            []
            if fault == "answered"
            else stack.enter_context(_reads_unanswered(fault, "session:"))
        )
        res = await _check_access(client, access_old)

    assert _status_and_code(res) == (401, "INVALID_TOKEN"), (
        f"access token cũ sau xoay được nhận: {res.text!r}"
    )
    assert _issued_token_cookies(res) == [], _issued_token_cookies(res)
    logs = _logs(caplog, "app.core.deps")
    from_db = any("no non-revoked DB row" in m for m in logs)
    fast_path = any("Session not found in Redis" in m for m in logs)
    if fault == "answered":
        assert hit == []
        assert fast_path and not from_db, f"401 không đến từ lối nhanh: {logs}"
    else:
        assert hit == [f"session:{jti_old}"], hit
        assert from_db and not fast_path, f"401 không đến từ STEP 4b: {logs}"


# -----------------------------------------------------------------------------
# Ô a3 · b2 · b4 của ma trận tích hợp (lát HS), cùng helper với nhóm b1–b8 ngay
# trên (`_reads_unanswered`, `_spy_session_row_reads`, `_logs`, `_sio`).
#
# Nguồn của mỗi lời từ chối được ĐO, không suy: STEP 4b / phép đối chiếu
# exact-jti của socket để lại log riêng và lượt gọi `get_by_refresh_jti_and_user`
# (spy); lối nhanh (Redis TRẢ LỜI "không có phiên") để lại log khác và không gọi
# CSDL. Kết quả đúng mà sai nguồn là một ca ĐỎ.
# -----------------------------------------------------------------------------

_DEPS_STEP4B_REFUSAL = "no non-revoked DB row"
_DEPS_FAST_PATH_REFUSAL = "Session not found in Redis"
# Log của phép đối chiếu CSDL trong `revalidate_auth` có "/" ("revoked/expired"),
# mà bộ render JSON thoát "/" — so phần không có "/".
_SOCKET_DB_REFUSAL = "in DB (exact jti)"
_SOCKET_FAST_PATH_REFUSAL = "Revalidation failed: Session revoked"
# Ô a3: hết hạn 1 giây trước lượt đọc. Thời điểm do CÙNG tiến trình Python sinh
# (cả `expires_at` lẫn `now` của vị từ), không phải đồng hồ của PostgreSQL ⇒
# không có độ lệch đồng hồ; một ân hạn ≥ 1 giây thêm vào vị từ làm ca ĐỎ.
_A3_EXPIRED_AGO = timedelta(seconds=1)


def _unanswered_unless(fault: str, stack: ExitStack, *prefixes: str) -> list:
    """``answered`` ⇒ không tiêm lỗi (trả ``[]``); khác ⇒ ``_reads_unanswered``."""
    if fault == "answered":
        return []
    return stack.enter_context(_reads_unanswered(fault, *prefixes))


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["answered", "connection", "breaker_open"])
async def test_expired_row_is_refused_by_the_shared_predicate_whatever_session_cache_answers(
    fault, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô a3 (HTTP): hàng CSDL HẾT HẠN, chưa thu hồi, khoá `session:` còn ⇒ 401 từ STEP 4b.

    Khi `session:` không trả lời, deps để hàng CSDL quyết; hàng hết hạn chỉ bị
    khước từ vì vị từ CHUNG `_live_session_by_refresh_jti`
    (`app/repositories/session_repository.py`) đòi `expires_at > now`. Biến thể
    `revoked` đã có (`TestSessionCacheUnreadable` ở tệp hardening); đây là biến
    thể `expired`. ``answered``: khoá còn ⇒ Redis trả lời "có" ⇒ STEP 4b cũng
    quyết — cùng vị từ, đường khác.
    """
    user = regular_user_in_db
    access, _, jti = await _login_as(client, user)
    assert (await _check_access(client, access)).status_code == 200, (
        "đối chứng hỏng: token phải được nhận khi hàng còn hạn"
    )
    before = await _expire_row_in_db_only(
        test_redis_client, user, jti, ago=_A3_EXPIRED_AGO
    )
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app"), ExitStack() as stack:
        hit = _unanswered_unless(fault, stack, "session:")
        db_reads = stack.enter_context(_spy_session_row_reads())
        res = await _check_access(client, access)

    assert _status_and_code(res) == (401, "INVALID_TOKEN"), (
        f"access token của phiên HẾT HẠN được nhận: {res.text!r}"
    )
    assert _issued_token_cookies(res) == [], _issued_token_cookies(res)
    assert hit == ([] if fault == "answered" else [f"session:{jti}"]), hit
    assert db_reads == [(jti, user["id"])], f"STEP 4b không hỏi đúng hàng: {db_reads}"
    logs = _logs(caplog, "app.core.deps")
    assert any(_DEPS_STEP4B_REFUSAL in m for m in logs), f"401 không đến từ STEP 4b: {logs}"
    assert not any(_DEPS_FAST_PATH_REFUSAL in m for m in logs), f"401 đến từ lối nhanh: {logs}"
    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.revoked_at, after.expires_at) == (
        jti,
        None,
        before.expires_at,
    ), "phép kiểm quyền không được ghi vào hàng"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["answered", "connection", "breaker_open"])
async def test_socket_revalidate_expired_row_is_refused_by_the_shared_predicate(
    fault, test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô a3 (socket): socket nối khi hàng còn hạn; hàng HẾT HẠN (chưa thu hồi, khoá
    `session:` còn) ⇒ revalidate `Session revoked` từ phép đối chiếu CSDL exact-jti.

    Cùng vị từ chung với HTTP STEP 4b. Không bao giờ `valid: True`, Redis trả lời
    `session:` hay không: trả lời ⇒ "có" (khoá còn) ⇒ CSDL quyết; không trả lời ⇒
    CSDL quyết.
    """
    user = regular_user_in_db
    access, _, jti = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert await sio.call("revalidate_auth", timeout=10) == {"valid": True}, (
            "đối chứng hỏng: revalidate phải hợp lệ khi hàng còn hạn"
        )
        sid = sio.get_sid("/")
        before = await _expire_row_in_db_only(
            test_redis_client, user, jti, ago=_A3_EXPIRED_AGO
        )
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), ExitStack() as stack:
            hit = _unanswered_unless(fault, stack, "session:")
            db_reads = stack.enter_context(_spy_session_row_reads())
            verdict = await socket_manager.revalidate_auth(sid)

    assert verdict == {"valid": False, "reason": "Session revoked"}, verdict
    assert hit == ([] if fault == "answered" else [f"session:{jti}"]), hit
    assert db_reads == [(jti, user["id"])], f"socket không hỏi đúng hàng: {db_reads}"
    logs = _logs(caplog, "app.socket_manager")
    assert any(_SOCKET_DB_REFUSAL in m for m in logs) and not any(
        _SOCKET_FAST_PATH_REFUSAL in m for m in logs
    ), f"khước từ không đến từ phép đối chiếu CSDL: {logs}"
    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.revoked_at, after.expires_at) == (
        jti,
        None,
        before.expires_at,
    ), "revalidate không được ghi vào hàng"


async def _logout_while_redis_does_not_answer(
    fault, client, test_redis_client, user: dict, access: str, refresh: str, jti: str, recover
):
    """B2 theo luồng THẬT: logout qua `get_logout_target` trong lúc Redis không trả
    lời (``fault``), rồi Redis hồi. Trả hàng CSDL sau đó.

    Kiểm TIỀN ĐỀ ngay tại đây: 204; hàng CSDL đã thu hồi VÀ commit (đọc bằng
    session mới); mọi lệnh ghi Redis của logout đã hỏng — khoá `session:` còn,
    `blacklist:{access_jti}` KHÔNG có, nên STEP 2 không có gì để khước từ.
    """
    with _redis_unreachable(fault):
        out = await _post_with_cookies(
            client, LOGOUT_URL, access_token=access, refresh_token=refresh
        )
    recover()

    assert out.status_code == 204, f"tiền đề: logout khi Redis không trả lời: {out.text!r}"
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, (
        "tiền đề: logout phải thu hồi VÀ commit hàng CSDL"
    )
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "tiền đề: lệnh ghi Redis phải hỏng thật — khoá session: còn nguyên"
    )
    assert not await test_redis_client.exists(f"blacklist:{_access_jti(access)}"), (
        "tiền đề: access token KHÔNG bị blacklist (STEP 2 sẽ trả lời 'không')"
    )
    assert not await test_redis_client.exists(f"user_blacklist:{user['id']}")
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_logout_during_redis_outage_then_session_cache_unreadable_is_refused_by_db_row(
    fault, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô b2 (HTTP): logout B2 khi Redis không trả lời (204, hàng CSDL thu hồi, khoá
    `session:` còn, KHÔNG blacklist access token) ⇒ Redis hồi, trừ lượt đọc
    `session:` ⇒ access token cũ ⇒ 401 từ STEP 4b.

    STEP 2 và STEP 3 được Redis TRẢ LỜI "không"; lượt đọc `session:` không trả lời
    ⇒ hàng CSDL quyết. Hàng ấy chết CHỈ vì logout B2 đã COMMIT việc thu hồi mà
    không cần Redis; 204 của nó phải là sự thật cả khi lượt đọc `session:` sau đó
    không có câu trả lời.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    assert (await _check_access(client, access)).status_code == 200, (
        "đối chứng hỏng: token phải được nhận trước logout"
    )
    before = await _logout_while_redis_does_not_answer(
        fault, client, test_redis_client, user, access, refresh, jti, fresh_breaker
    )
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app"), \
            _reads_unanswered(fault, "session:") as hit, \
            _spy_session_row_reads() as db_reads:
        res = await _check_access(client, access)

    assert _status_and_code(res) == (401, "INVALID_TOKEN"), (
        f"access token đã logout (204) được nhận: {res.text!r}"
    )
    assert _issued_token_cookies(res) == [], _issued_token_cookies(res)
    assert hit == [f"session:{jti}"], hit
    assert db_reads == [(jti, user["id"])], f"STEP 4b không hỏi đúng hàng: {db_reads}"
    logs = _logs(caplog, "app.core.deps")
    assert any(_DEPS_STEP4B_REFUSAL in m for m in logs), f"401 không đến từ STEP 4b: {logs}"
    assert not any(_DEPS_FAST_PATH_REFUSAL in m for m in logs), f"401 đến từ lối nhanh: {logs}"
    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.revoked_at) == (jti, before.revoked_at)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_socket_revalidate_after_logout_during_redis_outage_is_refused_by_db_row(
    fault, test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô b2 (socket): socket nối TRƯỚC logout; logout B2 khi Redis không trả lời ⇒
    Redis hồi, trừ lượt đọc `session:` ⇒ revalidate `Session revoked` từ phép đối
    chiếu CSDL exact-jti, không bao giờ `valid: True`.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert await sio.call("revalidate_auth", timeout=10) == {"valid": True}, (
            "đối chứng hỏng: revalidate phải hợp lệ trước logout"
        )
        sid = sio.get_sid("/")
        before = await _logout_while_redis_does_not_answer(
            fault, client, test_redis_client, user, access, refresh, jti, fresh_breaker
        )
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), \
                _reads_unanswered(fault, "session:") as hit, \
                _spy_session_row_reads() as db_reads:
            verdict = await socket_manager.revalidate_auth(sid)

    assert verdict == {"valid": False, "reason": "Session revoked"}, verdict
    assert hit == [f"session:{jti}"], hit
    assert db_reads == [(jti, user["id"])], f"socket không hỏi đúng hàng: {db_reads}"
    logs = _logs(caplog, "app.socket_manager")
    assert any(_SOCKET_DB_REFUSAL in m for m in logs) and not any(
        _SOCKET_FAST_PATH_REFUSAL in m for m in logs
    ), f"khước từ không đến từ phép đối chiếu CSDL: {logs}"
    after = await _row_by_id(before.id)
    assert (after.refresh_jti, after.revoked_at) == (jti, before.revoked_at)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["connection", "breaker_open"])
async def test_socket_revalidate_total_outage_disconnects_as_auth_state_unavailable(
    fault, test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô b4: CẢ HAI lượt đọc Redis của revalidate (`session:` rồi `user_blacklist:`)
    không trả lời, hàng CSDL SỐNG ⇒ ngắt với lý do `Auth state unavailable`.

    Không bao giờ `valid: True`: hàng CSDL sống nhưng không ai trả lời được
    `user_blacklist`, bản ghi CHỈ Redis giữ khi `invalidate_all_sessions` chưa
    commit. Hàng CSDL không được hỏi; sự cố không thu hồi gì, không xoá khoá nào.

    Ghim cả LÝ DO, không chỉ `valid: False`: lý do này là thứ duy nhất phân biệt
    "không xác định được" với "đã thu hồi" (`Session revoked`) hay lỗi lạ
    (`Validation error`) — hai lý do mà sự cố này từng cho ra trước khi `session:`
    được đọc theo ba câu trả lời. Frontend hiện đăng xuất với MỌI `valid: false`
    (`frontend/src/lib/socket/client.ts`); muốn đổi điều đó thì phải dựa vào lý do này.
    """
    user = regular_user_in_db
    access, _, jti = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert await sio.call("revalidate_auth", timeout=10) == {"valid": True}, (
            "đối chứng hỏng: revalidate phải hợp lệ khi Redis lành"
        )
        sid = sio.get_sid("/")
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), \
                _reads_unanswered(fault, "session:", "user_blacklist:") as hit, \
                _spy_session_row_reads() as db_reads:
            verdict = await socket_manager.revalidate_auth(sid)

    assert verdict == {"valid": False, "reason": "Auth state unavailable"}, verdict
    assert hit == [f"session:{jti}", f"user_blacklist:{user['id']}"], hit
    assert db_reads == [], f"hàng CSDL không được quyết thay user_blacklist: {db_reads}"
    assert any(
        "Revalidation deferred: user blacklist unreadable" in m
        for m in _logs(caplog, "app.socket_manager")
    ), _logs(caplog, "app.socket_manager")
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "sự cố Redis đã thu hồi phiên"
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "sự cố Redis đã xoá khoá session:"
    )


# -----------------------------------------------------------------------------
# F62 (S24 sau deploy, 10-10): đăng xuất khi ACCESS TOKEN ĐÃ HẾT HẠN nhưng phiên
# refresh còn sống. Cookie `access_token` sống bằng refresh (max_age = refresh_ttl)
# nên trình duyệt VẪN gửi token hết hạn cùng cookie refresh. Đo trên prod: logout
# 401, phiên không bị thu hồi, lượt tải sau làm mới được ⇒ người dùng tưởng đã
# thoát. Hợp đồng: token hết hạn CHỈ được chấp nhận khi đúng chữ ký, đúng loại
# `access`, và cookie refresh có chữ ký hợp lệ trỏ ĐÚNG phiên mà token ấy cưỡi
# (`jti` cookie == `r_jti` token) — quyền sở hữu vẫn do
# `get_by_refresh_jti_and_user` quyết. Mỗi ca phá MỘT bất biến.
# -----------------------------------------------------------------------------


def _ky_lai(token: str, *, exp_cach_nay: int = -60, khoa: str | None = None, **sua) -> str:
    """Ký lại ĐÚNG claims của ``token`` (chữ ký khoá thật trừ khi ``khoa``), chỉ đổi ``exp`` và các trường ``sua``."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False},
    )
    payload["exp"] = int(datetime.now(timezone.utc).timestamp()) + exp_cach_nay
    payload.update(sua)
    return jwt.encode(payload, khoa or settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def _refresh_lai(client, refresh_token: str):
    return await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_token)


@pytest.mark.asyncio
async def test_f62_logout_token_con_han_thu_hoi_va_khong_refresh_lai(client, regular_user_in_db):
    """Đối chứng: access còn hạn ⇒ 204, hàng thu hồi, cookie refresh không mở lại được phiên."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=access, refresh_token=refresh)

    assert res.status_code == 204, res.text
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, "phiên còn sống sau logout"
    lai = await _refresh_lai(client, refresh)
    assert lai.status_code == 401 and _issued_token_cookies(lai) == [], (lai.status_code, lai.text)


@pytest.mark.asyncio
async def test_f62_logout_access_het_han_cung_phien_thu_hoi(client, regular_user_in_db):
    """F62: access HẾT HẠN (đúng chữ ký) + cookie refresh CÙNG phiên ⇒ 204, hàng thu hồi, cookie xoá, refresh 401."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)
    het_han = _ky_lai(access)

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=het_han, refresh_token=refresh)

    assert res.status_code == 204, f"logout với access hết hạn trả {res.status_code}: {res.text!r}"
    assert _deleted_auth_cookies(res) == _AUTH_COOKIES_CLEARED, res.headers.get_list("set-cookie")
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, "phiên còn sống sau logout (F62)"
    lai = await _refresh_lai(client, refresh)
    assert lai.status_code == 401 and _issued_token_cookies(lai) == [], (
        f"phiên mở lại được bằng cookie refresh sau logout: {lai.status_code} {lai.text!r}"
    )


@pytest.mark.asyncio
async def test_f62_access_het_han_khong_cookie_refresh_401(client, regular_user_in_db):
    """Access hết hạn, KHÔNG có cookie refresh ⇒ 401, không thu hồi gì (token hết hạn một mình không đủ)."""
    access, _refresh, jti = await _login_as(client, regular_user_in_db)

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=_ky_lai(access))

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên chỉ bằng access token hết hạn"


@pytest.mark.asyncio
async def test_f62_access_het_han_cookie_refresh_phien_khac_401(client, regular_user_in_db):
    """Access hết hạn của phiên 1 + cookie refresh của phiên 2 (cùng user) ⇒ 401, KHÔNG phiên nào bị thu hồi.

    Với token CÒN hạn, logout kết thúc cả hai (ca ``..._ends_both_sessions_...``); token hết hạn thì cookie phải trỏ
    ĐÚNG phiên mà token cưỡi."""
    user = regular_user_in_db
    access_1, _r1, jti_1 = await _login_as(client, user, ua=UA_DESKTOP)
    _a2, refresh_2, jti_2 = await _login_as(client, user, ua=UA_MOBILE)

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=_ky_lai(access_1), refresh_token=refresh_2)

    assert res.status_code == 401, (res.status_code, res.text)
    for jti in (jti_1, jti_2):
        row = await _row_by_jti(jti)
        assert row is not None and row.revoked_at is None, f"phiên {jti[:8]} bị thu hồi"


@pytest.mark.asyncio
async def test_f62_access_het_han_sai_chu_ky_401(client, regular_user_in_db):
    """Access hết hạn ký bằng KHOÁ KHÁC + cookie refresh đúng phiên ⇒ 401, phiên còn sống."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)
    gia = _ky_lai(access, khoa=settings.JWT_SECRET_KEY + "-khoa-gia")

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=gia, refresh_token=refresh)

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên bằng token sai chữ ký"


@pytest.mark.asyncio
async def test_f62_token_loai_refresh_het_han_o_cho_access_401(client, regular_user_in_db):
    """Token HẾT HẠN đúng chữ ký nhưng ``type=refresh`` đặt vào chỗ access + cookie refresh đúng phiên ⇒ 401."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)

    res = await _post_with_cookies(
        client, LOGOUT_URL, access_token=_ky_lai(access, type="refresh"), refresh_token=refresh
    )

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên bằng token sai loại"
