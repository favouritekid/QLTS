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
from types import SimpleNamespace
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
from app.core import deps
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

    `r_jti` là `UserSession.refresh_jti` HIỆN HÀNH của phiên trong CSDL (và là
    thứ payload `force_logout_batch` nêu). Nó KHÔNG còn là khoá room: từ F103
    room thu hồi khoá theo `UserSession.id` (`socket_manager.session_room`), vì
    /auth/refresh xoay `refresh_jti` trên cùng hàng còn `id` thì không đổi.
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
                "`emit_force_logout` bắn vào room "
                f"{socket_manager.session_room(session_a_id)}; A không nhận "
                "nghĩa là nó không ở trong room đó, hoặc callback hậu-commit của "
                "revoke_session đã không chạy."
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
async def test_socket_revalidate_after_refresh_rotation_stays_valid(
    fault, test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """Ô b8 (ĐẢO CHIỀU ở F103): socket nối TRƯỚC khi /refresh xoay vẫn `valid: True`
    sau xoay, Redis trả lời `session:` hay không.

    Trước F103 ca này GHIM lỗi: `connect` lưu `r_jti` lúc bắt tay vào phiên
    socket, /refresh xoá `session:{cũ}` và đổi jti của hàng ⇒ revalidate luôn
    `Session revoked` ⇒ frontend đăng xuất (đo trên prod 26-10). Nay phiên socket
    mang `session_id` = `UserSession.id`, KHÔNG mang jti; revalidate tra jti HIỆN
    HÀNH của hàng ấy rồi mới hỏi Redis/CSDL. Bằng chứng là chính lượt đọc cache:
    lỗi tiêm chạm `session:{MỚI}`, không phải `session:{cũ}`.
    """
    user = regular_user_in_db
    access, refresh, jti_old = await _login_as(client, user)
    session_id = (await _row_by_jti(jti_old)).id
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert await sio.call("revalidate_auth", timeout=10) == {"valid": True}, (
            "đối chứng hỏng: revalidate phải hợp lệ trước khi xoay"
        )
        sid = sio.get_sid("/")
        phien_socket = await socket_manager.sio.get_session(sid)
        assert phien_socket.get("session_id") == session_id, phien_socket
        assert "jti" not in phien_socket, f"phiên socket còn giữ jti: {phien_socket}"

        _, jti_new = await _rotate(client, refresh)
        assert jti_new != jti_old
        assert await _row_by_jti(jti_old) is None, "tiền đề: hàng CSDL phải đã mang jti mới"
        assert (await _row_by_jti(jti_new)).id == session_id, "tiền đề: xoay giữ đúng hàng"
        assert not await test_redis_client.exists(f"session:{jti_old}")
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), ExitStack() as stack:
            hit = _unanswered_unless(fault, stack, "session:")
            verdict = await socket_manager.revalidate_auth(sid)
        still_served = socket_manager.sio.manager.is_connected(sid, "/")

    assert verdict == {"valid": True}, verdict
    assert still_served, "server đã ngắt socket của một phiên còn sống"
    assert hit == ([] if fault == "answered" else [f"session:{jti_new}"]), hit
    logs = _logs(caplog, "app.socket_manager")
    assert not any("Revalidation failed" in m for m in logs), logs


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
    commit. Phép đối chiếu hàng SỐNG (exact-jti) không được hỏi — nó không được
    quyết thay `user_blacklist`; từ F103, bước tra jti hiện hành theo
    `UserSession.id` (`get_refresh_jti_for_share`) chạy TRƯỚC, nhưng chỉ để biết
    hỏi Redis khoá nào, không phán hợp lệ. Sự cố không thu hồi gì, không xoá khoá nào.

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
    assert db_reads == [], f"hàng SỐNG không được quyết thay user_blacklist: {db_reads}"
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
# F103 (đo trên prod `4e5707e0`, 26-10): socket bám refresh jti của LÚC BẮT TAY.
# Client refresh chủ động (~phút 12) ⇒ /auth/refresh xoá `session:{cũ}` và đổi
# `refresh_jti` của hàng ⇒ lượt `revalidate_auth` phút 15 thấy khoá vắng ⇒ server
# ngắt trước khi ACK ⇒ client "io server disconnect" ⇒ `useAuthStore.logout()`.
# Room thu hồi cũng khoá theo jti ấy ⇒ sau refresh, thu hồi phiên bắn vào room
# của jti MỚI mà socket chưa từng vào.
#
# Nay socket bám `UserSession.id` — định danh ổn định do server đặt lúc đăng nhập
# — cho CẢ `revalidate_auth` (tra jti hiện hành của hàng ấy, giữ `FOR SHARE`)
# LẪN room thu hồi (`socket_manager.session_room`). Mỗi ca vi phạm MỘT bất biến,
# khẳng định nằm trong thân ca; mọi socket nối TRƯỚC lần xoay đầu tiên.
# -----------------------------------------------------------------------------


async def _rotate(client, refresh_token: str) -> tuple:
    """Một /auth/refresh THẬT chỉ mang cookie refresh; trả (refresh mới, jti mới)."""
    res = await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_token)
    assert res.status_code == 200, res.text
    new_refresh = res.cookies.get("refresh_token")
    assert new_refresh, "refresh không phát cookie refresh mới"
    new_jti = jwt.decode(
        new_refresh, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )["jti"]
    return new_refresh, new_jti


def _ghi_force_logout(sio) -> tuple:
    """Ghi mọi `force_logout_batch` socket nhận; trả (danh sách payload, cờ đã nhận)."""
    nhan: list = []
    co = asyncio.Event()

    def _on(data):
        nhan.append(data)
        co.set()

    sio.on("force_logout_batch", _on)
    return nhan, co


def _cho_ngat(sio) -> asyncio.Event:
    """Cờ bật khi CLIENT thấy socket bị ngắt (gói DISCONNECT của server tới nơi)."""
    ngat = asyncio.Event()
    sio.on("disconnect", lambda *args: ngat.set())
    return ngat


@contextmanager
def _session_jti_lookup_unreadable():
    """CSDL không trả lời bước tra jti theo `UserSession.id`; trả các lượt gọi."""
    from app.repositories import SessionRepository

    calls: list = []

    async def _down(self, session_id, user_id):
        calls.append((session_id, user_id))
        raise OperationalError("SELECT", {}, Exception("tiêm lỗi: CSDL không trả lời"))

    with patch.object(SessionRepository, "get_refresh_jti_for_share", _down):
        yield calls


@contextmanager
def _refresh_pauses_after_redis_rotate():
    """/auth/refresh THẬT dừng ngay SAU pipeline Redis xoay (STEP 7), TRƯỚC COMMIT
    (STEP 8): hàng phiên đang bị refresh giữ `FOR UPDATE`, Redis đã có
    `session:{mới}` và mất `session:{cũ}`, còn CSDL đã commit vẫn mang jti CŨ.

    Trả (rotated, release): chờ ``rotated``; đặt ``release`` để refresh đi tiếp.
    """
    from app.routers import auth as auth_router

    original = auth_router.safe_redis_pipeline
    rotated, release = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def _pipeline(*args, **kwargs):
        async with original(*args, **kwargs) as pipe:
            execute = pipe.execute

            async def _execute_then_pause(*a, **k):
                out = await execute(*a, **k)
                rotated.set()
                await release.wait()
                return out

            pipe.execute = _execute_then_pause
            yield pipe

    with patch.object(auth_router, "safe_redis_pipeline", _pipeline):
        yield rotated, release


async def _task_waits_on_row_lock(task: "asyncio.Task", timeout: float = 15.0) -> bool:
    """True khi một backend CHỜ KHOÁ trong CSDL test lúc ``task`` CHƯA xong.

    False nếu ``task`` xong trước (nó không chờ gì) hoặc hết giờ. Mỗi lượt hỏi
    một kết nối mới (cùng lý do với `_wait_for_lock_waiter`).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if task.done():
            return False
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
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.asyncio
async def test_f103_revalidate_valid_across_consecutive_refreshes(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(1) Ba lần /refresh LIÊN TIẾP; sau MỖI lần, `revalidate_auth` qua ACK thật
    vẫn `valid: True` và socket còn nối.

    Tiền đề kiểm sau mỗi lần xoay — jti đổi, vẫn đúng hàng, `session:{cũ}` đã xoá —
    để ca không xanh vì refresh thôi xoay.
    """
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    session_id = (await _row_by_jti(jti)).id
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert await sio.call("revalidate_auth", timeout=10) == {"valid": True}, (
            "đối chứng hỏng: revalidate phải hợp lệ trước khi xoay"
        )
        da_thay = [jti]
        for lan in (1, 2, 3):
            refresh, jti = await _rotate(client, refresh)
            assert jti not in da_thay, f"tiền đề: lần xoay {lan} không đổi jti"
            assert (await _row_by_jti(jti)).id == session_id, "tiền đề: xoay giữ đúng hàng"
            assert not await test_redis_client.exists(f"session:{da_thay[-1]}"), (
                f"tiền đề: lần xoay {lan} không xoá khoá session: cũ"
            )
            da_thay.append(jti)

            ack = await sio.call("revalidate_auth", timeout=10)

            assert ack == {"valid": True}, f"sau lần xoay {lan}: {ack}"
            assert sio.connected, f"sau lần xoay {lan}: socket bị ngắt"


@pytest.mark.asyncio
async def test_f103_every_tab_of_session_valid_after_refresh(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(2) HAI socket (hai tab) của CÙNG một phiên — cùng access token — nối trước
    khi xoay; sau một /refresh, CẢ HAI `revalidate_auth` đều `valid: True`."""
    user = regular_user_in_db
    access, refresh, jti_old = await _login_as(client, user)
    async with _sio() as tab_1, _sio() as tab_2:
        for tab in (tab_1, tab_2):
            await tab.connect(test_server, auth={"token": access}, transports=["websocket"])
        assert tab_1.get_sid("/") != tab_2.get_sid("/"), "tiền đề: hai socket riêng"
        _, jti_new = await _rotate(client, refresh)
        assert jti_new != jti_old

        ack_1 = await tab_1.call("revalidate_auth", timeout=10)
        ack_2 = await tab_2.call("revalidate_auth", timeout=10)

        assert ack_1 == {"valid": True}, f"tab 1: {ack_1}"
        assert ack_2 == {"valid": True}, f"tab 2: {ack_2}"
        assert tab_1.connected and tab_2.connected, "một tab bị ngắt"


@pytest.mark.asyncio
async def test_f103_revoked_after_refresh_refused_and_server_disconnects(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """(3a) Sau xoay, hàng phiên bị THU HỒI trong CSDL (khoá `session:{mới}` còn —
    chỉ CSDL nói "chết") ⇒ `Session revoked` từ đối chiếu exact-jti trên jti MỚI,
    và SERVER tự ngắt: handler được gọi thẳng phía server, không qua client."""
    user = regular_user_in_db
    access, refresh, _ = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        sid = sio.get_sid("/")
        ngat = _cho_ngat(sio)
        _, jti_new = await _rotate(client, refresh)
        await _revoke_row_in_db_only(test_redis_client, user, jti_new)
        assert socket_manager.sio.manager.is_connected(sid, "/"), "tiền đề: socket đang được phục vụ"
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), _spy_session_row_reads() as db_reads:
            verdict = await socket_manager.revalidate_auth(sid)

        assert verdict == {"valid": False, "reason": "Session revoked"}, verdict
        assert db_reads == [(jti_new, user["id"])], f"không đối chiếu jti MỚI: {db_reads}"
        assert any(_SOCKET_DB_REFUSAL in m for m in _logs(caplog, "app.socket_manager"))
        assert not socket_manager.sio.manager.is_connected(sid, "/"), (
            "server KHÔNG tự ngắt socket của phiên đã thu hồi"
        )
        await asyncio.wait_for(ngat.wait(), timeout=10)


@pytest.mark.asyncio
async def test_f103_expired_after_refresh_refused_and_server_disconnects(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """(3b) Như (3a) nhưng hàng HẾT HẠN (chưa thu hồi; khoá `session:{mới}` còn)."""
    user = regular_user_in_db
    access, refresh, _ = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        sid = sio.get_sid("/")
        ngat = _cho_ngat(sio)
        _, jti_new = await _rotate(client, refresh)
        await _expire_row_in_db_only(test_redis_client, user, jti_new, ago=_A3_EXPIRED_AGO)
        assert socket_manager.sio.manager.is_connected(sid, "/"), "tiền đề: socket đang được phục vụ"
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), _spy_session_row_reads() as db_reads:
            verdict = await socket_manager.revalidate_auth(sid)

        assert verdict == {"valid": False, "reason": "Session revoked"}, verdict
        assert db_reads == [(jti_new, user["id"])], f"không đối chiếu jti MỚI: {db_reads}"
        assert any(_SOCKET_DB_REFUSAL in m for m in _logs(caplog, "app.socket_manager"))
        assert not socket_manager.sio.manager.is_connected(sid, "/"), (
            "server KHÔNG tự ngắt socket của phiên đã hết hạn"
        )
        await asyncio.wait_for(ngat.wait(), timeout=10)


@pytest.mark.asyncio
async def test_f103_other_live_session_does_not_rescue_revoked_one(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """(4) Phiên A (socket nối, đã xoay) bị thu hồi trong CSDL; phiên B của CÙNG
    người dùng SỐNG (đăng nhập sau, thiết bị khác). Socket của A ⇒ `Session
    revoked` từ đối chiếu exact-jti của CHÍNH A — B sống không cứu được A."""
    _kiem_ua_phan_loai_dong()
    user = regular_user_in_db
    access_a, refresh_a, _ = await _login_as(client, user, ua=UA_DESKTOP)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access_a}, transports=["websocket"])
        sid = sio.get_sid("/")
        _, jti_a = await _rotate(client, refresh_a)
        _, _, jti_b = await _login_as(client, user, ua=UA_MOBILE)
        assert await _live_session_jtis(user["id"]) == sorted([jti_a, jti_b]), (
            "tiền đề: A (đã xoay) và B cùng sống"
        )
        await _revoke_row_in_db_only(test_redis_client, user, jti_a)
        assert await _live_session_jtis(user["id"]) == [jti_b], "tiền đề: B còn sống"
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), _spy_session_row_reads() as db_reads:
            verdict = await socket_manager.revalidate_auth(sid)

        assert verdict == {"valid": False, "reason": "Session revoked"}, verdict
        assert db_reads == [(jti_a, user["id"])], f"không hỏi đúng hàng của A: {db_reads}"
        assert any(_SOCKET_DB_REFUSAL in m for m in _logs(caplog, "app.socket_manager"))
        assert not socket_manager.sio.manager.is_connected(sid, "/")


@pytest.mark.asyncio
async def test_f103_redis_down_after_refresh_is_auth_state_unavailable(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(5a) Sau xoay, Redis không trả lời CẢ `session:` lẫn `user_blacklist:` ⇒
    `Auth state unavailable` và server ngắt — hợp đồng fail-closed của b4, nay
    trên jti MỚI (lượt đọc cache chạm `session:{mới}`)."""
    user = regular_user_in_db
    access, refresh, _ = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        sid = sio.get_sid("/")
        _, jti_new = await _rotate(client, refresh)

        with _reads_unanswered("connection", "session:", "user_blacklist:") as hit:
            verdict = await socket_manager.revalidate_auth(sid)

        assert verdict == {"valid": False, "reason": "Auth state unavailable"}, verdict
        assert hit == [f"session:{jti_new}", f"user_blacklist:{user['id']}"], hit
        assert not socket_manager.sio.manager.is_connected(sid, "/")


@pytest.mark.asyncio
async def test_f103_session_row_unreadable_is_validation_error(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(5b) CSDL không trả lời bước tra jti theo `UserSession.id` ⇒ `Validation
    error` và server ngắt (hợp đồng của mọi lỗi CSDL trong revalidate)."""
    user = regular_user_in_db
    access, refresh, jti = await _login_as(client, user)
    session_id = (await _row_by_jti(jti)).id
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        sid = sio.get_sid("/")
        await _rotate(client, refresh)

        with _session_jti_lookup_unreadable() as calls:
            verdict = await socket_manager.revalidate_auth(sid)

        assert verdict == {"valid": False, "reason": "Validation error"}, verdict
        assert calls == [(session_id, user["id"])], calls
        assert not socket_manager.sio.manager.is_connected(sid, "/")


@pytest.mark.asyncio
async def test_f103_revalidate_waits_for_inflight_refresh_then_valid(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(6) /refresh ĐANG BAY — Redis đã xoay, CSDL chưa COMMIT — đúng lúc socket
    revalidate. Đọc thường thấy jti CŨ đã commit mà `session:{cũ}` đã xoá ⇒
    "Session revoked" GIẢ ⇒ đăng xuất (cùng triệu chứng F103). `FOR SHARE` bắt
    revalidate CHỜ COMMIT rồi đọc jti MỚI ⇒ `valid: True`."""
    user = regular_user_in_db
    access, refresh, jti_old = await _login_as(client, user)
    async with _sio() as sio:
        await sio.connect(test_server, auth={"token": access}, transports=["websocket"])
        sid = sio.get_sid("/")
        pending_verdict = None
        with _refresh_pauses_after_redis_rotate() as (rotated, release):
            pending_refresh = asyncio.create_task(
                _post_with_cookies(client, REFRESH_URL, refresh_token=refresh)
            )
            try:
                await asyncio.wait_for(rotated.wait(), timeout=10)
                assert not await test_redis_client.exists(f"session:{jti_old}"), (
                    "tiền đề: Redis phải đã xoay"
                )
                assert await _row_by_jti(jti_old) is not None, (
                    "tiền đề: CSDL đã commit phải còn mang jti cũ"
                )
                pending_verdict = asyncio.create_task(socket_manager.revalidate_auth(sid))
                waited = await _task_waits_on_row_lock(pending_verdict)
            finally:
                release.set()
            res = await asyncio.wait_for(pending_refresh, timeout=30)
        verdict = await asyncio.wait_for(pending_verdict, timeout=30)

    assert res.status_code == 200, res.text
    assert waited, f"revalidate không chờ refresh đang bay; phán quyết: {verdict}"
    assert verdict == {"valid": True}, verdict


@pytest.mark.asyncio
async def test_f103_revoke_after_refresh_reaches_every_tab_of_session(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(7) Nhánh anh em — room thu hồi. Hai tab của phiên A nối TRƯỚC khi A xoay;
    B thu hồi A qua `DELETE /api/sessions/{id}` ⇒ CẢ HAI tab nhận
    `force_logout_batch` nêu jti HIỆN HÀNH của A. Room khoá theo jti lúc bắt tay
    thì lệnh thu hồi sau xoay rơi vào room của jti MỚI, không socket nào nghe."""
    user = regular_user_in_db
    h = await _hai_phien_song(client, user)
    async with _sio() as tab_1, _sio() as tab_2:
        nhan_1, co_1 = _ghi_force_logout(tab_1)
        nhan_2, co_2 = _ghi_force_logout(tab_2)
        for tab in (tab_1, tab_2):
            await tab.connect(test_server, auth={"token": h["access_a"]}, transports=["websocket"])
        _, jti_a_new = await _rotate(client, h["refresh_a"])

        client.cookies.clear()
        try:
            res = await client.delete(
                f"/api/sessions/{h['id_a']}",
                headers={"Cookie": f"access_token={h['access_b']}"},
            )
        finally:
            client.cookies.clear()
        assert res.status_code == 204, res.text
        await asyncio.wait_for(asyncio.gather(co_1.wait(), co_2.wait()), timeout=10)

    assert nhan_1 == [{"revoked_jtis": [jti_a_new]}], nhan_1
    assert nhan_2 == [{"revoked_jtis": [jti_a_new]}], nhan_2


@pytest.mark.asyncio
async def test_f103_revoke_all_after_refresh_reaches_other_session_tab(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(8) Nhánh anh em thứ hai — `POST /api/sessions/revoke-all` (giữ phiên B đang
    gọi, thu hồi A). Socket của A nối TRƯỚC khi A xoay vẫn nhận `force_logout_batch`
    nêu jti HIỆN HÀNH của A."""
    user = regular_user_in_db
    h = await _hai_phien_song(client, user)
    async with _sio() as tab_a:
        nhan_a, co_a = _ghi_force_logout(tab_a)
        await tab_a.connect(test_server, auth={"token": h["access_a"]}, transports=["websocket"])
        _, jti_a_new = await _rotate(client, h["refresh_a"])

        res = await _revoke_all(client, h["access_b"])
        assert res.status_code == 204, res.text
        await asyncio.wait_for(co_a.wait(), timeout=10)

    assert nhan_a == [{"revoked_jtis": [jti_a_new]}], nhan_a


# -----------------------------------------------------------------------------
# F108 (review 26-10): thu hồi có mục tiêu từng chỉ PHÁT `force_logout_batch` —
# client bỏ qua sự kiện và không gọi `revalidate_auth` thì giữ socket mãi. Nay
# chính thao tác thu hồi CƯỠNG CHẾ ngắt phía server qua kênh liên worker sẵn có
# (`socket:force_disconnect`, lệnh `sessions` nhắm `session_room(id)`), ACK từ MỌI
# worker sống; không xác nhận được thì ghi là CHƯA xác nhận, thu hồi trong CSDL
# vẫn đứng. Mỗi ca vi phạm MỘT bất biến.
# -----------------------------------------------------------------------------


async def _delete_session_as(client, access_token: str, session_id: int):
    """`DELETE /api/sessions/{id}` chỉ mang cookie ``access_token`` (như FE)."""
    client.cookies.clear()
    try:
        return await client.delete(
            f"/api/sessions/{session_id}",
            headers={"Cookie": f"access_token={access_token}"},
        )
    finally:
        client.cookies.clear()


@asynccontextmanager
async def _worker_thu_hai(test_redis_client, *, ack: bool):
    """Một worker THỨ HAI giả lập (không giữ socket nào): đăng ký vào
    `socket:workers` với heartbeat sống — nên bên phát BẮT BUỘC chờ nó ACK — và
    nghe kênh `socket:force_disconnect`. ``ack=True``: ACK như worker thật;
    ``ack=False``: nhận lệnh mà không ACK (worker treo). Trả các lệnh đã nhận."""
    import json

    wid = f"w-thu-hai-{uuid.uuid4().hex[:8]}"
    await test_redis_client.set(socket_manager._WORKER_HB_PREFIX + wid, "1", ex=60)
    await test_redis_client.sadd(socket_manager._WORKERS_SET, wid)
    nhan: list = []
    pubsub = test_redis_client.pubsub()
    await pubsub.subscribe(socket_manager.FORCE_DISCONNECT_CHANNEL)

    async def _nghe():
        async for msg in pubsub.listen():
            if not msg or msg.get("type") != "message":
                continue
            lenh = json.loads(msg["data"])
            nhan.append(lenh)
            if ack:
                await test_redis_client.sadd(
                    socket_manager._ACK_PREFIX + lenh["command_id"], wid
                )

    task = asyncio.create_task(_nghe())
    try:
        yield nhan
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await pubsub.unsubscribe(socket_manager.FORCE_DISCONNECT_CHANNEL)
        await pubsub.aclose()
        await test_redis_client.srem(socket_manager._WORKERS_SET, wid)
        await test_redis_client.delete(socket_manager._WORKER_HB_PREFIX + wid)


@contextmanager
def _spy_enforcement():
    """Ghi kết quả THẬT của `_enforce_session_revocation` (True = mọi worker ACK)."""
    original = socket_manager._enforce_session_revocation
    ket_qua: list = []

    async def _spy(*args, **kwargs):
        out = await original(*args, **kwargs)
        ket_qua.append(out)
        return out

    with patch.object(socket_manager, "_enforce_session_revocation", _spy):
        yield ket_qua


@pytest.mark.asyncio
async def test_f108_revoke_cuts_every_tab_of_session_even_if_client_ignores(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(Q1 — ca quyết định) Hai tab của phiên A (ĐÃ refresh) và một tab của phiên
    B. Tab A KHÔNG nghe `force_logout_batch` và KHÔNG gọi `revalidate_auth` —
    client cố tình bỏ qua. B thu hồi A ⇒ lúc `DELETE` trả 204, SERVER đã ngắt
    CẢ HAI tab A (`manager.is_connected` False; client nhận DISCONNECT); tab B
    vẫn được phục vụ."""
    user = regular_user_in_db
    h = await _hai_phien_song(client, user)
    async with _sio() as a_1, _sio() as a_2, _sio() as b_1:
        for tab, access in ((a_1, h["access_a"]), (a_2, h["access_a"]), (b_1, h["access_b"])):
            await tab.connect(test_server, auth={"token": access}, transports=["websocket"])
        ngat_1, ngat_2 = _cho_ngat(a_1), _cho_ngat(a_2)
        sids = {"tab A1": a_1.get_sid("/"), "tab A2": a_2.get_sid("/"), "tab B": b_1.get_sid("/")}
        await _rotate(client, h["refresh_a"])

        res = await _delete_session_as(client, h["access_b"], h["id_a"])

        assert res.status_code == 204, res.text
        dang_phuc_vu = {
            ten: socket_manager.sio.manager.is_connected(sid, "/") for ten, sid in sids.items()
        }
        assert dang_phuc_vu == {"tab A1": False, "tab A2": False, "tab B": True}, (
            f"server không ngắt đúng phiên A khi thu hồi: {dang_phuc_vu}"
        )
        await asyncio.wait_for(asyncio.gather(ngat_1.wait(), ngat_2.wait()), timeout=10)
        assert b_1.connected, "tab B bị ngắt dù phiên B không bị thu hồi"


@pytest.mark.asyncio
async def test_f108_revoke_is_enforced_through_inter_worker_channel(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker
):
    """(Q1 — đa worker) Một worker THỨ HAI nghe `socket:force_disconnect` và ACK
    như worker thật. Thu hồi A (đã refresh) ⇒ worker ấy nhận ĐÚNG MỘT lệnh, nêu
    đúng phiên A (id + jti HIỆN HÀNH), không có `user_ids`; việc ngắt chỉ được
    xác nhận vì CẢ HAI worker đã ACK."""
    user = regular_user_in_db
    h = await _hai_phien_song(client, user)
    async with _sio() as a_1:
        await a_1.connect(test_server, auth={"token": h["access_a"]}, transports=["websocket"])
        _, jti_a = await _rotate(client, h["refresh_a"])

        with _spy_enforcement() as ket_qua:
            async with _worker_thu_hai(test_redis_client, ack=True) as nhan:
                res = await _delete_session_as(client, h["access_b"], h["id_a"])

    assert res.status_code == 204, res.text
    khong_ma_lenh = [{k: v for k, v in lenh.items() if k != "command_id"} for lenh in nhan]
    assert khong_ma_lenh == [{"sessions": [[h["id_a"], jti_a]]}], (
        f"lệnh trên kênh liên worker sai đích: {nhan}"
    )
    assert ket_qua == [True], f"ngắt không được xác nhận dù mọi worker ACK: {ket_qua}"


@pytest.mark.asyncio
async def test_f108_unacked_worker_reported_unconfirmed_revoke_stands(
    test_server, client, regular_user_in_db, test_redis_client, fresh_breaker, caplog
):
    """(Q1 — nhánh không xác nhận) Worker thứ hai NHẬN lệnh mà KHÔNG ACK. Thu hồi
    A ⇒ vẫn 204, hàng A đã thu hồi trong CSDL (nguồn sự thật); việc ngắt được ghi
    là CHƯA xác nhận — không bao giờ báo là đã ngắt."""
    user = regular_user_in_db
    h = await _hai_phien_song(client, user)
    async with _sio() as a_1:
        await a_1.connect(test_server, auth={"token": h["access_a"]}, transports=["websocket"])
        await _rotate(client, h["refresh_a"])
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="app"), _spy_enforcement() as ket_qua:
            async with _worker_thu_hai(test_redis_client, ack=False) as nhan:
                res = await _delete_session_as(client, h["access_b"], h["id_a"])

    assert res.status_code == 204, res.text
    assert len(nhan) == 1, f"tiền đề: worker thứ hai phải NHẬN lệnh: {nhan}"
    assert ket_qua == [False], f"ngắt chưa xác nhận mà bị báo là xong: {ket_qua}"
    assert any(
        "socket disconnect NOT confirmed" in m for m in _logs(caplog, "app.socket_manager")
    ), _logs(caplog, "app.socket_manager")
    assert (await _row_by_id(h["id_a"])).revoked_at is not None, "thu hồi trong CSDL không đứng"


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


def _resign(token: str, *, exp_offset: int = -60, key: str | None = None, **overrides) -> str:
    """Ký lại ĐÚNG claims của ``token`` (chữ ký khoá thật trừ khi ``key``), chỉ đổi ``exp`` và các trường ``overrides``."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False},
    )
    payload["exp"] = int(datetime.now(timezone.utc).timestamp()) + exp_offset
    payload.update(overrides)
    return jwt.encode(payload, key or settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def _refresh_with(client, refresh_token: str):
    return await _post_with_cookies(client, REFRESH_URL, refresh_token=refresh_token)


def _issued_token_names(res) -> list:
    """Tên cookie token được phát mới — CHỈ tên: assertion đỏ in giá trị so sánh ra log (CI của kho public)."""
    return [raw.partition("=")[0].strip() for raw in _issued_token_cookies(res)]


@pytest.mark.asyncio
async def test_f62_logout_fresh_token_revokes_and_blocks_refresh(client, regular_user_in_db):
    """Đối chứng: access còn hạn ⇒ 204, hàng thu hồi, cookie refresh không mở lại được phiên."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=access, refresh_token=refresh)

    assert res.status_code == 204, res.text
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, "phiên còn sống sau logout"
    again = await _refresh_with(client, refresh)
    assert again.status_code == 401, (again.status_code, again.text)
    assert _issued_token_names(again) == [], "refresh sau logout phát token mới"


@pytest.mark.asyncio
async def test_f62_logout_expired_access_same_session_revokes(client, regular_user_in_db):
    """F62: access HẾT HẠN (đúng chữ ký) + cookie refresh CÙNG phiên ⇒ 204, hàng thu hồi, cookie xoá, refresh 401."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)
    expired = _resign(access)

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=expired, refresh_token=refresh)

    assert res.status_code == 204, f"logout với access hết hạn trả {res.status_code}: {res.text!r}"
    assert _deleted_auth_cookies(res) == _AUTH_COOKIES_CLEARED, "logout không xoá đủ cookie token"
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, "phiên còn sống sau logout (F62)"
    again = await _refresh_with(client, refresh)
    assert again.status_code == 401, (
        f"phiên mở lại được bằng cookie refresh sau logout: {again.status_code} {again.text!r}"
    )
    assert _issued_token_names(again) == [], "refresh sau logout phát token mới (F62)"


@pytest.mark.asyncio
async def test_f62_expired_access_without_refresh_cookie_401(client, regular_user_in_db):
    """Access hết hạn, KHÔNG có cookie refresh ⇒ 401, không thu hồi gì (token hết hạn một mình không đủ)."""
    access, _refresh, jti = await _login_as(client, regular_user_in_db)

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=_resign(access))

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên chỉ bằng access token hết hạn"


@pytest.mark.asyncio
async def test_f62_expired_access_with_other_session_cookie_401(client, regular_user_in_db):
    """Access hết hạn của phiên 1 + cookie refresh của phiên 2 (cùng user) ⇒ 401, KHÔNG phiên nào bị thu hồi.

    Với token CÒN hạn, logout kết thúc cả hai (ca ``..._ends_both_sessions_...``); token hết hạn thì cookie phải trỏ
    ĐÚNG phiên mà token cưỡi."""
    user = regular_user_in_db
    access_1, _r1, jti_1 = await _login_as(client, user, ua=UA_DESKTOP)
    _a2, refresh_2, jti_2 = await _login_as(client, user, ua=UA_MOBILE)

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=_resign(access_1), refresh_token=refresh_2)

    assert res.status_code == 401, (res.status_code, res.text)
    for jti in (jti_1, jti_2):
        row = await _row_by_jti(jti)
        assert row is not None and row.revoked_at is None, f"phiên {jti[:8]} bị thu hồi"


@pytest.mark.asyncio
async def test_f62_expired_access_wrong_signature_401(client, regular_user_in_db):
    """Access hết hạn ký bằng KHOÁ KHÁC + cookie refresh đúng phiên ⇒ 401, phiên còn sống."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)
    forged = _resign(access, key=settings.JWT_SECRET_KEY + "-wrong-key")

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=forged, refresh_token=refresh)

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên bằng token sai chữ ký"


@pytest.mark.asyncio
async def test_f62_expired_refresh_type_token_as_access_401(client, regular_user_in_db):
    """Token HẾT HẠN đúng chữ ký nhưng ``type=refresh`` đặt vào chỗ access + cookie refresh đúng phiên ⇒ 401."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)

    res = await _post_with_cookies(
        client, LOGOUT_URL, access_token=_resign(access, type="refresh"), refresh_token=refresh
    )

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên bằng token sai loại"


@pytest.mark.asyncio
async def test_f62_decode_expired_token_only_accepts_expired(client, regular_user_in_db):
    """``decode_expired_token`` chỉ nhận token ĐÃ hết hạn (đúng chữ ký): token còn hạn ⇒ None — bên gọi phải dùng ``decode_token``."""
    access, _refresh, _jti = await _login_as(client, regular_user_in_db)
    # So trên bool/jti, không đưa ``access`` vào biểu thức assert — pytest in đối số khi đỏ.
    accepted_fresh = security.decode_expired_token(access) is not None
    expected_jti = jwt.decode(access, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])["jti"]
    payload = security.decode_expired_token(_resign(access))

    assert not accepted_fresh, "nhận token còn hạn ở nhánh hết hạn"
    assert payload is not None and payload["jti"] == expected_jti, "token hết hạn đúng chữ ký phải trả đúng payload"


# F64: access hết hạn ĐÚNG phiên + cookie refresh mang ĐÚNG jti của phiên ấy, nhưng
# cookie hỏng đúng MỘT thuộc tính — chữ ký, hạn, hoặc loại. ``jti`` khớp ``r_jti``
# không đủ: cookie phải là refresh token hợp lệ thì mới chứng minh được phiên.


@pytest.mark.asyncio
async def test_f62_expired_access_refresh_cookie_wrong_signature_401(client, regular_user_in_db):
    """Cookie refresh đúng jti, CÒN hạn, đúng loại nhưng ký bằng KHOÁ KHÁC ⇒ 401, phiên còn sống."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)
    forged_refresh = _resign(refresh, exp_offset=3600, key=settings.JWT_SECRET_KEY + "-wrong-key")

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=_resign(access), refresh_token=forged_refresh)

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên bằng cookie refresh sai chữ ký"


@pytest.mark.asyncio
async def test_f62_expired_access_expired_refresh_cookie_401(client, regular_user_in_db):
    """Cookie refresh đúng jti, đúng chữ ký, đúng loại nhưng ĐÃ HẾT HẠN ⇒ 401, phiên còn sống."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)

    res = await _post_with_cookies(
        client, LOGOUT_URL, access_token=_resign(access), refresh_token=_resign(refresh, exp_offset=-60)
    )

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên bằng cookie refresh đã hết hạn"


@pytest.mark.asyncio
async def test_f62_expired_access_refresh_cookie_wrong_type_401(client, regular_user_in_db):
    """Cookie refresh đúng jti, đúng chữ ký, CÒN hạn nhưng ``type=access`` ⇒ 401, phiên còn sống."""
    access, refresh, jti = await _login_as(client, regular_user_in_db)
    wrong_type = _resign(refresh, exp_offset=3600, type="access")

    res = await _post_with_cookies(client, LOGOUT_URL, access_token=_resign(access), refresh_token=wrong_type)

    assert res.status_code == 401, (res.status_code, res.text)
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is None, "thu hồi phiên bằng cookie sai loại"


# -----------------------------------------------------------------------------
# POST /api/sessions/revoke-all — phiên GIỮ LẠI lấy từ TOKEN, không từ body.
#
# Lỗi cũ: router giữ phiên mà body `current_session_id` nêu. Client gửi id một
# phiên KHÁC của chính mình ⇒ phiên ấy được giữ, phiên đang dùng bị thu hồi.
# (Truy vấn thu hồi vẫn lọc theo user_id: chưa có bằng chứng thu hồi chéo tài
# khoản — các ca 2a/2b canh điều đó.)
#
# Hợp đồng mới: phiên giữ lại = `deps.get_current_session` — hàng SỐNG của CHÍNH
# người dùng mang `r_jti` của access token đã xác thực. Body được nhận (FE cũ vẫn
# gửi) nhưng không quyết định gì. Không xác định được phiên ⇒ thu hồi MỌI phiên.
#
# Mỗi ca canh MỘT bất biến; khẳng định nằm ngay trong thân ca (bộ chấm đột biến
# đòi khung traceback cuối là thân ca). Không `pytest.raises`, không parametrize.
# Tên ca ≤ 72 ký tự: tiêu đề khối lỗi của pytest (80 cột) mới còn ≥ 3 dấu `_`
# mỗi bên — bộ chấm đột biến tìm khối lỗi theo đúng mẫu đó.
# -----------------------------------------------------------------------------

REVOKE_ALL_URL = "/api/sessions/revoke-all"
_KHONG_BODY = object()


async def _revoke_all(client, access_token: str, body=_KHONG_BODY):
    """POST revoke-all chỉ mang cookie ``access_token`` (như FE), body JSON tuỳ chọn.

    ``_KHONG_BODY`` = không gửi body nào (không byte, không Content-Type JSON).
    """
    client.cookies.clear()
    try:
        kwargs = {} if body is _KHONG_BODY else {"json": body}
        return await client.post(
            REVOKE_ALL_URL, headers={"Cookie": f"access_token={access_token}"}, **kwargs
        )
    finally:
        client.cookies.clear()


async def _hai_phien_song(client, user: dict) -> dict:
    """Hai phiên SỐNG của cùng người dùng: A (desktop) và B (mobile).

    Khác dấu vân tay thiết bị — nếu không, lượt đăng nhập B thu hồi A ngay (xem
    chú thích ở `UA_DESKTOP`).
    """
    _kiem_ua_phan_loai_dong()
    access_a, refresh_a, jti_a = await _login_as(client, user, ua=UA_DESKTOP)
    access_b, _, jti_b = await _login_as(client, user, ua=UA_MOBILE)
    assert await _live_session_jtis(user["id"]) == sorted([jti_a, jti_b]), (
        "tiền đề: hai phiên A và B phải cùng sống"
    )
    return {
        "access_a": access_a,
        "refresh_a": refresh_a,
        "jti_a": jti_a,
        "id_a": (await _row_by_jti(jti_a)).id,
        "access_b": access_b,
        "jti_b": jti_b,
        "id_b": (await _row_by_jti(jti_b)).id,
    }


async def _revoke_row_in_db_only(test_redis_client, user: dict, jti: str):
    """Hàng CSDL của ``jti`` bị THU HỒI; khoá `session:{jti}` còn nguyên (CSDL quyết)."""
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(models.UserSession)
            .where(models.UserSession.refresh_jti == jti)
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await s.commit()
    row = await _row_by_jti(jti)
    assert row is not None and row.revoked_at is not None, (
        "tiền đề: hàng phải đã bị thu hồi"
    )
    assert await test_redis_client.get(f"session:{jti}") == str(user["id"]), (
        "tiền đề: khoá session: còn nguyên"
    )
    return row


async def _get_current_session_for(user_id: int, refresh_jti: str):
    """Gọi THẲNG `deps.get_current_session` như FastAPI gọi sau `get_current_user`.

    `get_current_user` chỉ cho qua `r_jti` có hàng sống của chính người dùng, nên
    qua HTTP các nhánh "jti của người khác / hàng đã chết" của dependency không
    với tới được — chúng chỉ mở ra khi có request thu hồi khác COMMIT xen giữa.
    Gọi thẳng để canh từng điều kiện của vị từ.
    """
    async with AsyncSessionLocal() as s:
        return await deps.get_current_session(
            request=SimpleNamespace(state=SimpleNamespace(refresh_jti=refresh_jti)),
            current_user=SimpleNamespace(id=user_id),
            db=s,
        )


@pytest.mark.asyncio
async def test_revoke_all_keeps_token_session_not_body_session(client, regular_user_in_db):
    """Ca 1 — access token của phiên A, body nêu ID phiên B (của CHÍNH mình) ⇒
    còn sống ĐÚNG phiên A; B bị thu hồi.

    Bản cũ giữ phiên body nêu: B sống, phiên đang dùng A bị thu hồi.
    """
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)

    res = await _revoke_all(client, p["access_a"], {"current_session_id": p["id_b"]})

    assert res.status_code == 204, res.text
    assert await _live_session_jtis(user["id"]) == [p["jti_a"]], (
        "phiên còn sống sau revoke-all phải ĐÚNG là phiên của access token (A), "
        f"không phải phiên body nêu (B, id={p['id_b']})"
    )


@pytest.mark.asyncio
async def test_revoke_all_with_other_users_session_id_leaves_that_user_untouched(
    client, regular_user_in_db, admin_user_in_db
):
    """Ca 2a — body nêu ID phiên của NGƯỜI KHÁC ⇒ mọi phiên của người ấy không đổi:
    hàng CSDL còn sống và access token của họ vẫn được nhận."""
    victim = admin_user_in_db
    victim_access, _, victim_jti = await _login_as(client, victim)
    victim_session_id = (await _row_by_jti(victim_jti)).id
    access, _, _ = await _login_as(client, regular_user_in_db)

    res = await _revoke_all(client, access, {"current_session_id": victim_session_id})

    assert res.status_code == 204, res.text
    assert await _live_session_jtis(victim["id"]) == [victim_jti], (
        "revoke-all của một người dùng đã thu hồi phiên của người khác"
    )
    assert (await _check_access(client, victim_access)).status_code == 200, (
        "access token của người kia bị khước từ sau revoke-all của người dùng khác"
    )


@pytest.mark.asyncio
async def test_revoke_all_with_other_users_session_id_still_keeps_token_session(
    client, regular_user_in_db, admin_user_in_db
):
    """Ca 2b — body nêu ID phiên của NGƯỜI KHÁC ⇒ body bị bỏ qua: phiên A (của
    token) vẫn được giữ, phiên B của chính mình bị thu hồi.

    Bản cũ dùng ID lạ làm phiên giữ lại ⇒ không phiên nào của người gọi khớp ⇒
    cả phiên đang dùng cũng bị thu hồi.
    """
    _, _, victim_jti = await _login_as(client, admin_user_in_db)
    victim_session_id = (await _row_by_jti(victim_jti)).id
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)

    res = await _revoke_all(client, p["access_a"], {"current_session_id": victim_session_id})

    assert res.status_code == 204, res.text
    assert await _live_session_jtis(user["id"]) == [p["jti_a"]], (
        "body nêu phiên của người khác đã làm mất phiên của access token (A)"
    )


@pytest.mark.asyncio
async def test_revoke_all_without_body_keeps_token_session(client, regular_user_in_db):
    """Ca 3a — KHÔNG gửi body ⇒ 204, còn sống ĐÚNG phiên A (lấy từ token).

    Bản cũ bắt buộc body ⇒ 422 và không thu hồi gì.
    """
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)

    res = await _revoke_all(client, p["access_a"])

    assert res.status_code == 204, res.text
    assert await _live_session_jtis(user["id"]) == [p["jti_a"]], (
        "revoke-all không body phải giữ ĐÚNG phiên của access token"
    )


@pytest.mark.asyncio
async def test_revoke_all_with_empty_body_keeps_token_session(client, regular_user_in_db):
    """Ca 3b — body rỗng ``{}`` ⇒ còn sống ĐÚNG phiên A (lấy từ token).

    Bản cũ hiểu "không nêu phiên" là "không giữ phiên nào" ⇒ thu hồi cả A.
    """
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)

    res = await _revoke_all(client, p["access_a"], {})

    assert res.status_code == 204, res.text
    assert await _live_session_jtis(user["id"]) == [p["jti_a"]], (
        "revoke-all với body rỗng phải giữ ĐÚNG phiên của access token"
    )


@pytest.mark.asyncio
async def test_revoke_all_with_null_session_id_keeps_token_session(client, regular_user_in_db):
    """Ca 3c — ``{"current_session_id": null}`` ⇒ còn sống ĐÚNG phiên A (lấy từ token).

    Đây là đúng body FE gửi khi chưa biết phiên hiện tại (`sessions.ts`).
    """
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)

    res = await _revoke_all(client, p["access_a"], {"current_session_id": None})

    assert res.status_code == 204, res.text
    assert await _live_session_jtis(user["id"]) == [p["jti_a"]], (
        "revoke-all với current_session_id=null phải giữ ĐÚNG phiên của access token"
    )


@pytest.mark.asyncio
async def test_revoke_all_by_revoked_session_is_401_and_revokes_nothing(
    client, regular_user_in_db, test_redis_client
):
    """Ca 4a — phiên A đã bị THU HỒI trong CSDL (khoá `session:` còn) ⇒
    `get_current_user` khước từ 401 trước khi vào endpoint; phiên B không bị đụng.

    Đo thật: ở tầng HTTP, "phiên hiện tại đã chết" không bao giờ tới được router.
    """
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    await _revoke_row_in_db_only(test_redis_client, user, p["jti_a"])

    res = await _revoke_all(client, p["access_a"], {"current_session_id": p["id_a"]})

    assert res.status_code == 401, (res.status_code, res.text)
    row_b = await _row_by_jti(p["jti_b"])
    assert row_b is not None and row_b.revoked_at is None, (
        "access token của một phiên ĐÃ THU HỒI đã điều khiển được revoke-all"
    )


@pytest.mark.asyncio
async def test_revoke_all_by_expired_session_is_401_and_revokes_nothing(
    client, regular_user_in_db, test_redis_client
):
    """Ca 4b — phiên A đã HẾT HẠN trong CSDL (chưa thu hồi, khoá `session:` còn) ⇒
    401 trước khi vào endpoint; phiên B không bị đụng."""
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    await _expire_row_in_db_only(test_redis_client, user, p["jti_a"])

    res = await _revoke_all(client, p["access_a"], {"current_session_id": p["id_a"]})

    assert res.status_code == 401, (res.status_code, res.text)
    row_b = await _row_by_jti(p["jti_b"])
    assert row_b is not None and row_b.revoked_at is None, (
        "access token của một phiên ĐÃ HẾT HẠN đã điều khiển được revoke-all"
    )


@pytest.mark.asyncio
async def test_revoke_all_when_current_session_unresolved_is_401_revokes_nothing(
    client, app_instance, regular_user_in_db
):
    """Ca 4c — `get_current_user` đã cho qua nhưng `get_current_session` trả None
    (hàng bị thu hồi/hết hạn XEN GIỮA STEP 4b và lượt tra — dựng bằng override)
    ⇒ 401 và KHÔNG thu hồi phiên nào (review F27, owner 11-10): không biết phiên cần
    giữ thì không mở rộng thao tác phá huỷ; body KHÔNG được dùng làm phương án dự
    phòng, kể cả khi nó nêu đúng phiên của token."""
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)

    async def _khong_xac_dinh_duoc():
        return None

    app_instance.dependency_overrides[deps.get_current_session] = _khong_xac_dinh_duoc
    try:
        res = await _revoke_all(client, p["access_a"], {"current_session_id": p["id_a"]})
    finally:
        app_instance.dependency_overrides.pop(deps.get_current_session, None)

    assert res.status_code == 401, res.text
    assert sorted(await _live_session_jtis(user["id"])) == sorted([p["jti_a"], p["jti_b"]]), (
        "không xác định được phiên hiện tại mà vẫn thu hồi phiên"
    )


@pytest.mark.asyncio
async def test_current_session_dependency_ignores_other_users_session(
    client, regular_user_in_db, admin_user_in_db
):
    """Guard user_id — `get_current_session` với `r_jti` là phiên SỐNG của người
    KHÁC ⇒ None (không trả hàng của người kia)."""
    _, _, victim_jti = await _login_as(client, admin_user_in_db)
    user = regular_user_in_db
    _, _, own_jti = await _login_as(client, user)
    own = await _get_current_session_for(user["id"], own_jti)
    assert own is not None and own.refresh_jti == own_jti, (
        "đối chứng hỏng: jti sống của chính mình phải ra đúng hàng"
    )

    found = await _get_current_session_for(user["id"], victim_jti)

    assert found is None, (
        f"get_current_session trả phiên của người dùng khác (user_id={found.user_id})"
    )


@pytest.mark.asyncio
async def test_current_session_dependency_ignores_revoked_own_session(
    client, regular_user_in_db, test_redis_client
):
    """Guard "chưa thu hồi" — `r_jti` là phiên của chính mình nhưng ĐÃ THU HỒI ⇒ None."""
    user = regular_user_in_db
    _, _, jti = await _login_as(client, user)
    own = await _get_current_session_for(user["id"], jti)
    assert own is not None and own.refresh_jti == jti, (
        "đối chứng hỏng: jti sống của chính mình phải ra đúng hàng"
    )
    await _revoke_row_in_db_only(test_redis_client, user, jti)

    found = await _get_current_session_for(user["id"], jti)

    assert found is None, "get_current_session trả một phiên ĐÃ THU HỒI"


@pytest.mark.asyncio
async def test_current_session_dependency_ignores_expired_own_session(
    client, regular_user_in_db, test_redis_client
):
    """Guard "chưa hết hạn" — `r_jti` là phiên của chính mình nhưng ĐÃ HẾT HẠN ⇒ None."""
    user = regular_user_in_db
    _, _, jti = await _login_as(client, user)
    own = await _get_current_session_for(user["id"], jti)
    assert own is not None and own.refresh_jti == jti, (
        "đối chứng hỏng: jti sống của chính mình phải ra đúng hàng"
    )
    await _expire_row_in_db_only(test_redis_client, user, jti)

    found = await _get_current_session_for(user["id"], jti)

    assert found is None, "get_current_session trả một phiên ĐÃ HẾT HẠN"


@pytest.mark.asyncio
async def test_revoke_all_after_refresh_rotation_keeps_the_rotated_session(
    client, regular_user_in_db
):
    """Ca 5a — đăng nhập → /refresh (xoay jti trên CÙNG hàng A) → revoke-all bằng
    access token MỚI ⇒ còn sống đúng hàng A (mang jti mới); B bị thu hồi."""
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    rotated = await _post_with_cookies(client, REFRESH_URL, refresh_token=p["refresh_a"])
    assert rotated.status_code == 200, rotated.text
    access_moi = rotated.cookies.get("access_token")
    jti_moi = jwt.decode(
        rotated.cookies.get("refresh_token"),
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )["jti"]
    row_a = await _row_by_jti(jti_moi)
    assert access_moi and jti_moi != p["jti_a"] and row_a is not None and row_a.id == p["id_a"], (
        "tiền đề: /refresh phải xoay jti trên CHÍNH hàng A và phát access token mới"
    )

    res = await _revoke_all(client, access_moi)

    assert res.status_code == 204, res.text
    assert await _live_session_jtis(user["id"]) == [jti_moi], (
        "revoke-all bằng access token sau xoay phải giữ ĐÚNG hàng A (jti mới)"
    )


@pytest.mark.asyncio
async def test_revoke_all_by_pre_rotation_token_is_401_and_revokes_nothing(
    client, regular_user_in_db
):
    """Ca 5b — sau /refresh, access token CŨ (mang jti trước xoay) gọi revoke-all,
    body nêu đúng hàng A ⇒ 401; không phiên nào bị thu hồi. jti cũ không chọn
    được phiên nào để giữ hay để thu hồi."""
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    rotated = await _post_with_cookies(client, REFRESH_URL, refresh_token=p["refresh_a"])
    assert rotated.status_code == 200, rotated.text
    jti_moi = jwt.decode(
        rotated.cookies.get("refresh_token"),
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )["jti"]
    assert jti_moi != p["jti_a"], "tiền đề: /refresh phải xoay jti"

    res = await _revoke_all(client, p["access_a"], {"current_session_id": p["id_a"]})

    assert res.status_code == 401, (res.status_code, res.text)
    assert await _live_session_jtis(user["id"]) == sorted([jti_moi, p["jti_b"]]), (
        "access token CŨ (trước xoay) đã thu hồi được phiên"
    )


# -----------------------------------------------------------------------------
# Anh em của revoke-all: secure-account và MFA-enable (hợp đồng owner 12-10)
#
# Cả hai dùng CHUNG `deps.get_current_session` (r_jti của access token đã xác
# thực), không còn tự giải mã cookie refresh. Hành vi khi KHÔNG xác định được
# phiên là RIÊNG từng thao tác:
#   * secure-account: thu hồi TOÀN BỘ phiên (kể cả phiên này), xoá cookie xác
#     thực, trả `relogin_required=true` — bảo mật tài khoản không được bỏ dở.
#   * MFA-enable: 401 TRƯỚC mọi thay đổi CSDL/Redis — `enable_mfa` với
#     `current_session_id=None` bật MFA mà KHÔNG thu hồi phiên nào.
# -----------------------------------------------------------------------------

SECURE_ACCOUNT_URL = "/api/security/secure-account"
MFA_SETUP_URL = "/api/auth/mfa/setup"
MFA_ENABLE_URL = "/api/auth/mfa/enable"


async def _post_cookies_json(client, url: str, cookies: dict, body=None):
    """POST chỉ mang ĐÚNG các cookie truyền vào (như FE), body JSON tuỳ chọn."""
    client.cookies.clear()
    try:
        kwargs = {} if body is None else {"json": body}
        return await client.post(
            url,
            headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())},
            **kwargs,
        )
    finally:
        client.cookies.clear()


async def _login_id_moi_nhat(user_id: int) -> int:
    """Một hàng `login_history` của chính người dùng (session CSDL mới)."""
    async with AsyncSessionLocal() as s:
        row = await s.execute(
            select(models.LoginHistory.id)
            .where(models.LoginHistory.user_id == user_id)
            .order_by(models.LoginHistory.id.desc())
            .limit(1)
        )
        login_id = row.scalar_one_or_none()
    assert login_id is not None, "tiền đề: người dùng phải có lịch sử đăng nhập"
    return login_id


async def _secure_account(client, cookies: dict, login_id: int):
    return await _post_cookies_json(
        client, f"{SECURE_ACCOUNT_URL}?login_id={login_id}", cookies
    )


@contextmanager
def _phien_khong_xac_dinh(app_instance):
    """`get_current_user` đã cho qua nhưng `get_current_session` trả None (hàng bị
    thu hồi/hết hạn XEN GIỮA STEP 4b và lượt tra — dựng bằng override)."""

    async def _khong_xac_dinh_duoc():
        return None

    app_instance.dependency_overrides[deps.get_current_session] = _khong_xac_dinh_duoc
    try:
        yield
    finally:
        app_instance.dependency_overrides.pop(deps.get_current_session, None)


def _cookie_bi_xoa(res, ten: str) -> bool:
    """Phản hồi có `Set-Cookie` xoá cookie ``ten`` (Max-Age=0 hoặc hết hạn quá khứ)."""
    for h in res.headers.get_list("set-cookie"):
        dau = h.split(";", 1)[0].strip()
        if dau.split("=", 1)[0] == ten and (
            "max-age=0" in h.lower() or "1970" in h
        ):
            return True
    return False


@pytest.mark.asyncio
async def test_secure_account_unresolved_session_revokes_every_session(
    client, app_instance, regular_user_in_db
):
    """Không xác định được phiên ⇒ thu hồi TOÀN BỘ, kể cả phiên của request."""
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    login_id = await _login_id_moi_nhat(user["id"])

    with _phien_khong_xac_dinh(app_instance):
        res = await _secure_account(client, {"access_token": p["access_a"]}, login_id)

    assert res.status_code == 200, res.text
    assert await _live_session_jtis(user["id"]) == [], (
        "secure-account không xác định được phiên mà vẫn để phiên sống"
    )


@pytest.mark.asyncio
async def test_secure_account_unresolved_session_forces_relogin(
    client, app_instance, regular_user_in_db
):
    """Không xác định được phiên ⇒ báo `relogin_required` VÀ xoá cookie xác thực."""
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    login_id = await _login_id_moi_nhat(user["id"])

    with _phien_khong_xac_dinh(app_instance):
        res = await _secure_account(client, {"access_token": p["access_a"]}, login_id)

    assert res.status_code == 200, res.text
    bao = res.json().get("relogin_required")
    xoa = {t: _cookie_bi_xoa(res, t) for t in ("access_token", "refresh_token")}
    assert bao is True and all(xoa.values()), (
        f"chưa buộc đăng nhập lại: relogin_required={bao}, cookie bị xoá={xoa}"
    )


@pytest.mark.asyncio
async def test_secure_account_keeps_token_session_without_refresh_cookie(
    client, regular_user_in_db
):
    """Chỉ mang cookie access (không cookie refresh) ⇒ giữ ĐÚNG phiên của token."""
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    login_id = await _login_id_moi_nhat(user["id"])

    res = await _secure_account(client, {"access_token": p["access_a"]}, login_id)

    assert res.status_code == 200, res.text
    assert await _live_session_jtis(user["id"]) == [p["jti_a"]], (
        "secure-account phải giữ phiên của access token, thu hồi phiên còn lại"
    )


@pytest.mark.asyncio
async def test_secure_account_ignores_refresh_cookie_of_other_session(
    client, regular_user_in_db
):
    """Cookie refresh nêu phiên B, access token của phiên A ⇒ giữ A, không giữ B."""
    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    _, refresh_b, jti_b = await _login_as(client, user, ua=UA_MOBILE)
    login_id = await _login_id_moi_nhat(user["id"])

    res = await _secure_account(
        client, {"access_token": p["access_a"], "refresh_token": refresh_b}, login_id
    )

    assert res.status_code == 200, res.text
    assert await _live_session_jtis(user["id"]) == [p["jti_a"]], (
        "secure-account giữ phiên do cookie refresh nêu thay vì phiên của token"
    )


async def _mfa_setup(client, access_token: str) -> str:
    res = await _post_cookies_json(client, MFA_SETUP_URL, {"access_token": access_token})
    assert res.status_code == 200, res.text
    return res.json()["secret"]


async def _mfa_trang_thai(user_id: int) -> bool:
    async with AsyncSessionLocal() as s:
        return bool((await s.get(models.User, user_id)).mfa_enabled)


@pytest.mark.asyncio
async def test_mfa_enable_unresolved_session_is_401_changes_nothing(
    client, app_instance, regular_user_in_db, test_redis_client
):
    """Không xác định được phiên ⇒ 401 và KHÔNG đổi gì: MFA vẫn tắt, khoá
    `mfa_setup:` còn, hai phiên vẫn sống."""
    import pyotp

    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    secret = await _mfa_setup(client, p["access_a"])
    ma = pyotp.TOTP(secret).now()

    with _phien_khong_xac_dinh(app_instance):
        res = await _post_cookies_json(
            client, MFA_ENABLE_URL, {"access_token": p["access_a"]}, {"code": ma}
        )

    con_khoa = await test_redis_client.get(f"mfa_setup:{user['id']}") is not None
    sau = {
        "status": res.status_code,
        "mfa_enabled": await _mfa_trang_thai(user["id"]),
        "mfa_setup_con": con_khoa,
        "phien_song": await _live_session_jtis(user["id"]),
    }
    assert sau == {
        "status": 401,
        "mfa_enabled": False,
        "mfa_setup_con": True,
        "phien_song": sorted([p["jti_a"], p["jti_b"]]),
    }, f"MFA-enable không xác định được phiên mà vẫn đổi trạng thái: {sau}"


@pytest.mark.asyncio
async def test_mfa_enable_keeps_token_session_not_refresh_cookie_one(
    client, regular_user_in_db, test_redis_client
):
    """Cookie refresh nêu phiên B, access token của phiên A ⇒ bật MFA, giữ A."""
    import pyotp

    user = regular_user_in_db
    p = await _hai_phien_song(client, user)
    _, refresh_b, _ = await _login_as(client, user, ua=UA_MOBILE)
    secret = await _mfa_setup(client, p["access_a"])

    res = await _post_cookies_json(
        client,
        MFA_ENABLE_URL,
        {"access_token": p["access_a"], "refresh_token": refresh_b},
        {"code": pyotp.TOTP(secret).now()},
    )

    assert res.status_code == 200, res.text
    assert await _live_session_jtis(user["id"]) == [p["jti_a"]], (
        "MFA-enable giữ phiên do cookie refresh nêu thay vì phiên của token"
    )
