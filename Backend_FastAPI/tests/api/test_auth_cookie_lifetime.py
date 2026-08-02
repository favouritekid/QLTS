"""Contract test — cookie ``access_token`` phải sống LÂU HƠN token nó chứa.

Bối cảnh (prod): officer rời máy >15 phút rồi F5 thì bị đá về ``/login`` và mất
form đang nhập, dù ``refresh_token`` còn sống hàng tuần.

Nguyên nhân là cookie chết cùng token. Khi ``max_age`` của cookie
``access_token`` bằng đúng TTL của token (15 phút), trình duyệt XOÁ cookie ngay
khi token hết hạn. Request kế tiếp tới middleware không còn cookie nào, và hai
tình huống hoàn toàn khác nhau trở nên không phân biệt được:

* "chưa từng đăng nhập" — phải về ``/login``;
* "phiên còn sống 30 ngày, chỉ mỗi access token cũ" — chỉ cần làm mới im lặng.

Middleware buộc phải đoán, và nó đoán sai theo hướng đắt nhất.

Bất biến được khoá ở đây: **cookie sống theo refresh token, TOKEN vẫn 15 phút**.
Vế sau quan trọng ngang vế trước — ta kéo dài thứ giúp middleware quyết định,
KHÔNG kéo dài quyền truy cập. Một bản vá nới ``ACCESS_TOKEN_EXPIRE_MINUTES``
cũng làm triệu chứng biến mất nhưng là lỗ hổng, nên test phải phân biệt được
hai cách sửa đó.
"""
from __future__ import annotations

import http.cookies
import time

import jwt
import pytest
from httpx import AsyncClient

from app.config import settings

LOGIN = "/api/auth/login"
REFRESH = "/api/auth/refresh"


def _set_cookies(response) -> dict[str, http.cookies.Morsel]:
    """Mọi cookie trong các header ``Set-Cookie`` của response.

    Đọc từ HEADER chứ không từ cookie jar của client: jar chỉ giữ giá trị, còn
    thứ đang kiểm ở đây là thuộc tính ``Max-Age`` — đúng phần bị mất khi đọc qua
    jar.
    """
    jar: dict[str, http.cookies.Morsel] = {}
    for raw in response.headers.get_list("set-cookie"):
        parsed = http.cookies.SimpleCookie()
        parsed.load(raw)
        for name, morsel in parsed.items():
            jar[name] = morsel
    return jar


def _token_seconds_left(token: str) -> int:
    """Số giây còn lại tới ``exp`` của một JWT (không verify chữ ký)."""
    payload = jwt.decode(token, options={"verify_signature": False})
    return int(payload["exp"]) - int(time.time())


def _assert_cookie_outlives_token(jar: dict[str, http.cookies.Morsel], where: str):
    assert "access_token" in jar, f"{where}: thiếu cookie access_token"
    assert "refresh_token" in jar, f"{where}: thiếu cookie refresh_token"

    access_max_age = int(jar["access_token"]["max-age"])
    refresh_max_age = int(jar["refresh_token"]["max-age"])
    token_lifetime = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # 1. Cookie access sống đúng bằng cookie refresh (chênh vài giây do hai lần
    #    decode khác thời điểm).
    assert abs(access_max_age - refresh_max_age) <= 5, (
        f"{where}: Max-Age cookie access ({access_max_age}s) phải bằng cookie "
        f"refresh ({refresh_max_age}s) — nếu không, cookie biến mất trước khi "
        f"middleware kịp dùng nó"
    )

    # 2. …và dài hơn HẲN tuổi thọ token bên trong. Bất biến 1 một mình chưa đủ:
    #    nếu ai đó hạ REFRESH_TOKEN_EXPIRE_DAYS xuống 15 phút thì nó vẫn xanh.
    assert access_max_age > token_lifetime * 10, (
        f"{where}: Max-Age cookie access ({access_max_age}s) không dài hơn hẳn "
        f"TTL token ({token_lifetime}s) — cookie sẽ lại chết cùng token"
    )

    # 3. TOKEN vẫn ngắn. Đây là vế phân biệt "kéo dài cookie" (đúng) với "kéo
    #    dài quyền truy cập" (lỗ hổng).
    remaining = _token_seconds_left(jar["access_token"].value)
    assert 0 < remaining <= token_lifetime + 5, (
        f"{where}: access token còn {remaining}s, vượt TTL {token_lifetime}s — "
        f"bản vá phải nới tuổi thọ COOKIE, không nới tuổi thọ TOKEN"
    )


@pytest.mark.asyncio
async def test_login_sets_access_cookie_that_outlives_its_token(
    client: AsyncClient, regular_user_in_db: dict
):
    """Nhánh login."""
    response = await client.post(
        LOGIN,
        data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        },
    )
    assert response.status_code == 200, response.text

    _assert_cookie_outlives_token(_set_cookies(response), where="login")


@pytest.mark.asyncio
async def test_refresh_sets_access_cookie_that_outlives_its_token(
    client: AsyncClient, regular_user_in_db: dict
):
    """Nhánh refresh — mỗi lần rotate đều phải giữ nguyên bất biến.

    Nhánh này dễ bị bỏ sót: sửa mỗi ``login`` thì phiên vẫn mất sau lần refresh
    đầu tiên, mà lần đó xảy ra trong vòng 15 phút kể từ khi đăng nhập.
    """
    login = await client.post(
        LOGIN,
        data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        },
    )
    assert login.status_code == 200, login.text

    response = await client.post(REFRESH)
    assert response.status_code == 200, response.text

    _assert_cookie_outlives_token(_set_cookies(response), where="refresh")
