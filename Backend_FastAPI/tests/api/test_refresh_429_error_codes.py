"""Contract test — hai loại 429 trên đường refresh PHẢI mang ``error_code``
top-level khác nhau.

Bối cảnh (audit prod 2026-07-30): client phân loại 429 để quyết định có đăng
xuất người dùng hay không.

* ``RATE_LIMITED`` — slowapi, quota theo IP hết. TẠM THỜI: cả trường ra
  Internet qua một IP NAT nên 32% request ``/auth/refresh`` từng bị chặn; client
  phải GIỮ phiên, nếu không officer bị đá về /login giữa lúc nhập liệu.
* ``REFRESH_ABUSE_LOCKED`` — cổng M4 ``refresh_fail:{username}``. Lần lỗi chạm
  ngưỡng đã gọi ``invalidate_all_sessions`` rồi trả 401; các lần sau mới nhận
  429 này, tức phiên ĐÃ chết → client PHẢI đăng xuất.

Nếu mã bị mất (vd ai đó quay lại raise ``HTTPException`` trần, khi đó
``http_exception_handler`` trả ``HTTP_429``) thì client sẽ giữ phiên cho một
session đã bị thu hồi và lặp 401→429→401 vô hạn. Test này khoá contract đó.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.rate_limits import RATE_LIMITED_ERROR_CODE, rate_limit_exceeded_handler
from app.routers.auth import RefreshAbuseLocked

LOGIN = "/api/auth/login"
REFRESH = "/api/auth/refresh"


@pytest.mark.asyncio
async def test_slowapi_429_carries_top_level_rate_limited_code():
    """slowapi handler trả ``error_code: RATE_LIMITED`` ở TOP-LEVEL body.

    Gọi handler trực tiếp (nó là hàm module-level chính vì lý do này) — không
    cần làm cạn một bucket thật, và ``APP_ENV=test`` vốn không đăng ký handler.
    """
    injected = {}

    def _inject_headers(response, view_rate_limit):
        injected["called"] = True
        return response

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(limiter=SimpleNamespace(_inject_headers=_inject_headers))),
        state=SimpleNamespace(view_rate_limit=object()),
    )

    response = await rate_limit_exceeded_handler(request, exc=Exception("rate limited"))

    assert response.status_code == 429
    body = response.body.decode()
    assert f'"error_code":"{RATE_LIMITED_ERROR_CODE}"' in body.replace(" ", "")
    assert RATE_LIMITED_ERROR_CODE == "RATE_LIMITED"
    # Retry-After vẫn được inject qua limiter (thông tin cho client backoff).
    assert injected.get("called") is True


def test_refresh_abuse_locked_declares_its_own_error_code():
    """``RefreshAbuseLocked`` mang mã riêng và vẫn là ``HTTPException``.

    Là ``HTTPException`` mới đi qua được các tầng ``except HTTPException: raise``
    của ``refresh_access_token`` mà không bị đếm vào bộ đếm lạm dụng; một domain
    exception sẽ rơi vào ``except Exception`` gần nhất và bị nuốt.
    """
    from fastapi import HTTPException

    exc = RefreshAbuseLocked()

    assert isinstance(exc, HTTPException)
    assert exc.status_code == 429
    assert exc.error_code == "REFRESH_ABUSE_LOCKED"
    assert exc.error_code != RATE_LIMITED_ERROR_CODE


@pytest.mark.asyncio
async def test_abuse_gate_response_has_error_code_not_http_429(
    client: AsyncClient, regular_user_in_db: dict
):
    """Đi qua HTTP thật: bộ đếm đã chạm ngưỡng → 429 + ``REFRESH_ABUSE_LOCKED``.

    Đây là phép kiểm quan trọng nhất: nó chạy qua ``http_exception_handler``,
    nơi mặc định sẽ ghi ``HTTP_429`` và làm client hiểu sai thành "lỗi tạm thời".
    """
    login = await client.post(
        LOGIN,
        data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        },
    )
    assert login.status_code == 200, login.text

    # Bộ đếm lạm dụng đã vượt ngưỡng (mọi lần refresh sau đó rơi vào cổng M4).
    with patch("app.routers.auth.safe_redis_get", new=AsyncMock(return_value="99")):
        response = await client.post(REFRESH)

    assert response.status_code == 429, response.text
    body = response.json()
    assert body["error_code"] == "REFRESH_ABUSE_LOCKED", body
    assert body["error_code"] != "HTTP_429"
    assert body["error_code"] != RATE_LIMITED_ERROR_CODE
