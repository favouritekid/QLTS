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
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(models.UserSession)
            .where(models.UserSession.refresh_jti == jti)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await s.commit()
    row = await _row_by_jti(jti)
    assert row.revoked_at is None and row.expires_at <= datetime.now(timezone.utc), (
        "tiền đề: hàng phải hết hạn và CHƯA bị thu hồi"
    )
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "tiền đề: khoá session: còn nguyên"
    )
    return access, refresh, jti, row


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
