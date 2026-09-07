# tests/security/test_session_revocation.py
# -*- coding: utf-8 -*-
"""
✅ TARGETED REVOCATION TESTS (PHASE 6)

Verifies that revoking a specific session only affects that session's Socket.IO connection
while other sessions for the same user remain connected.
"""
import asyncio
import logging

import jwt
import pytest
import pytest_asyncio
import socketio
from user_agents import parse as parse_user_agent

from app.config import settings
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
