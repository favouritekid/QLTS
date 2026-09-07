# tests/security/socket_test_helpers.py
# -*- coding: utf-8 -*-
"""Helper DÙNG CHUNG cho nhóm test Socket.IO / phiên đăng nhập trong tests/security/.

Vì sao có tệp này: trước đây `test_session_revocation.py` làm
``from .test_websocket_security import test_server, get_user_auth, HttpxClientWrapper``.
Import xuyên một module `test_*.py` kéo theo hai hệ quả:

* fixture "mượn" được chỉ vì pytest tra fixture trong namespace của module test —
  một hệ quả tình cờ, không phải giao ước. Đổi tên hay dời `test_server` ở tệp
  nguồn thì tệp đích hỏng theo cách khó truy ra;
* `import` chạy TOÀN BỘ phần module-level của tệp nguồn (`pytestmark` skipif,
  các import nặng) chỉ để lấy một hàm đăng nhập.

Nay: fixture ở `conftest.py`, hàm thuần ở đây. Không tệp test nào import từ tệp
test nào.

Tệp này KHÔNG chứa fixture và KHÔNG chứa hàm tên ``test_*`` — nó không phải
module test, và pytest không thu thập nó (`python_files = test_*.py`).
"""
import logging

import pytest

from ..fixtures.constants import AuthURLs

log = logging.getLogger(__name__)

# Tên khoá/tập hợp do app/socket_manager.py sở hữu. Chép lại ở đây thay vì import
# từ app để phép kiểm "còn rác không" vẫn đứng vững nếu ai đó ĐỔI tên biến trong
# app mà quên đổi thứ Redis thực sự chứa — khi đó test đỏ và người ta phải nhìn.
REDIS_WORKERS_SET = "socket:workers"
REDIS_USER_BLACKLIST_PATTERN = "user_blacklist:*"


# ============================================
# ĐĂNG NHẬP
# ============================================


async def get_user_auth(
    client,
    username: str,
    password: str,
    user_agent: str | None = None,
) -> tuple[str, dict]:
    """
    Helper to get auth credentials for WebSocket authentication.

    Args:
        user_agent: chuỗi User-Agent gửi kèm lượt đăng nhập. `None` (mặc định)
            KHÔNG truyền tham số `headers` nào cho httpx — hành vi giữ nguyên
            byte-đối-byte so với trước, đó là giao ước với tám ca WebSocket đang
            dùng helper này.

            Vì sao cần tham số: `session_service` suy `device_type`, `browser`
            và `os` từ chính header này (`user_agents.parse`), và
            `_revoke_previous_sessions_on_device` thu hồi phiên CŨ khi phiên mới
            có cùng dấu vân tay thiết bị do repository định nghĩa: trùng đồng
            thời `device_type`, `browser` và `os`
            (`SessionRepository.get_active_on_device`). Hai lượt đăng nhập từ
            cùng một httpx client trùng cả ba nên tự giết nhau, và mọi ca cần
            HAI phiên sống song song bắt buộc phải đăng nhập sao cho hai lượt
            tạo ra hai dấu vân tay repository khác nhau — tức khác ít nhất một
            trong `device_type`, `browser` hoặc `os`.

    Returns:
        tuple: (access_token, cookies) for backwards compatibility testing
        - access_token: For auth dict method (legacy) - extracted from cookie
        - cookies: For httpOnly cookie method (preferred, secure)

    Note: After httpOnly cookie migration, tokens are ONLY in cookies, not in
    response body.
    """
    login_data = {"username": username, "password": password}
    # Không dựng sẵn `headers={}`: truyền một dict rỗng vẫn là một đối số khác
    # với việc không truyền gì. Giữ đúng lời gọi cũ cho nhánh mặc định.
    tham_so_them = {}
    if user_agent is not None:
        tham_so_them["headers"] = {"User-Agent": user_agent}

    login_res = await client.post(AuthURLs.LOGIN, data=login_data, **tham_so_them)
    if login_res.status_code != 200:
        pytest.fail(f"Login failed: {login_res.text}")

    # Get cookies (tokens are here after httpOnly migration)
    cookies = dict(login_res.cookies)

    # After httpOnly cookie migration, tokens are ONLY in cookies.
    # Extract access_token from cookie for legacy auth dict tests.
    access_token = cookies.get("access_token", "")

    if not access_token:
        pytest.fail("access_token cookie not found after login")

    return access_token, cookies


async def get_user_token(client, username: str, password: str) -> str:
    """
    Legacy helper to get access token for WebSocket authentication.

    DEPRECATED: Use get_user_auth() instead to get both token and cookies.
    This helper is kept for backwards compatibility with existing tests.
    """
    access_token, _ = await get_user_auth(client, username, password)
    return access_token


# ============================================
# HÀNG RÀO RÁC REDIS
# ============================================


def _hien_thi(gia_tri) -> str:
    """Chuẩn hoá một khoá/thành viên Redis về str để in ra và để sắp xếp.

    `test_redis_client` hiện dựng với ``decode_responses=True`` nên đã là str,
    nhưng một client không giải mã sẽ trả bytes — trộn bytes với str thì
    ``sorted()`` ném TypeError và thông điệp lỗi biến mất. Chuẩn hoá trước.
    """
    if isinstance(gia_tri, (bytes, bytearray)):
        return gia_tri.decode("utf-8", errors="replace")
    return str(gia_tri)


def _mo_ta_ttl(ttl) -> str:
    """Diễn giải giá trị TTL của Redis. -1/-2 là hai ca KHÁC NHAU, đừng gộp."""
    if ttl == -1:
        return "-1 (KHÔNG có hạn — sẽ sống mãi cho tới khi flushdb)"
    if ttl == -2:
        return "-2 (khoá biến mất giữa lúc liệt kê và lúc hỏi TTL)"
    return f"{ttl}s"


async def assert_redis_sach(test_redis_client) -> None:
    """Hàng rào CUỐI, không phải cơ chế dọn chính.

    Ca test phải tự dọn khoá nó tạo trong `finally`; helper này chỉ bắt ca quên.
    In ĐỦ khoá tìm thấy — một thông điệp 'còn rác' không kèm danh sách là vô dụng
    lúc 2 giờ sáng.

    Kiểm hai thứ, vì đây là hai loại rác đã thật sự gây nhiễu chéo giữa các ca:

    * ``user_blacklist:*`` — một ca quên xoá thì MỌI ca sau dùng cùng user id sẽ
      bị từ chối đăng nhập/kết nối, và triệu chứng hiện ra ở ca KHÁC.
    * ``socket:workers`` — worker mồ côi ở lại tập hợp thì đường offboarding
      fail-closed sẽ chờ ACK của một tiến trình đã chết rồi timeout.

    Helper KHÔNG xoá gì cả: dọn là việc của fixture ``clear_redis_keys`` (nó
    flushdb cả trước lẫn sau mỗi ca). Nếu helper tự dọn thì vi phạm bị che đi và
    hàng rào thành vô nghĩa.

    Args:
        test_redis_client: client Redis (fakeredis) dùng chung với app.

    Raises:
        AssertionError: khi còn bất kỳ khoá/thành viên nào, kèm danh sách ĐẦY ĐỦ.
    """
    khoa_blacklist = sorted(
        _hien_thi(k) for k in await test_redis_client.keys(REDIS_USER_BLACKLIST_PATTERN)
    )
    worker_con_lai = sorted(
        _hien_thi(w) for w in await test_redis_client.smembers(REDIS_WORKERS_SET)
    )

    if not khoa_blacklist and not worker_con_lai:
        return

    dong = [
        "Redis còn rác sau khi ca test kết thúc — ca test phải tự dọn trong "
        "`finally`, `clear_redis_keys` chỉ là lưới an toàn.",
    ]

    if khoa_blacklist:
        dong.append(
            f"[{len(khoa_blacklist)}] khoá khớp `{REDIS_USER_BLACKLIST_PATTERN}` "
            "còn sót (kèm TTL):"
        )
        for khoa in khoa_blacklist:
            ttl = await test_redis_client.ttl(khoa)
            dong.append(f"    - {khoa}    TTL={_mo_ta_ttl(ttl)}")

    if worker_con_lai:
        dong.append(
            f"[{len(worker_con_lai)}] thành viên còn sót trong tập "
            f"`{REDIS_WORKERS_SET}`:"
        )
        for worker_id in worker_con_lai:
            dong.append(f"    - {worker_id}")

    raise AssertionError("\n".join(dong))
