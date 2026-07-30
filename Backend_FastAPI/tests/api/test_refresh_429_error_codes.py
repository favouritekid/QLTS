"""Contract test — hai loại 429 trên đường refresh PHẢI mang ``error_code``
top-level khác nhau, và handler PHẢI thực sự được gắn vào app.

Bối cảnh (audit prod 2026-07-30): client phân loại 429 để quyết định có đăng
xuất người dùng hay không.

* ``RATE_LIMITED`` — slowapi, quota theo IP hết. TẠM THỜI: cả trường ra
  Internet qua một IP NAT nên 32% request ``/auth/refresh`` từng bị chặn; client
  phải GIỮ phiên, nếu không officer bị đá về /login giữa lúc nhập liệu.
* ``REFRESH_ABUSE_LOCKED`` — cổng M4 ``refresh_fail:{username}``. Lần lỗi chạm
  ngưỡng đã gọi ``invalidate_all_sessions`` rồi trả 401; các lần sau mới nhận
  429 này, tức phiên ĐÃ chết → client PHẢI đăng xuất.

🔴 Bài học đắt nhất của đợt này: contract mã lỗi có thể ĐÚNG trong unit test mà
vẫn SAI ở runtime, vì ``add_exception_handler`` gọi trong ``lifespan`` không
bao giờ có hiệu lực (Starlette đã copy bảng handler khi dựng middleware stack).
Đo thực tế trên dev trước khi sửa: request thứ 21 trả
``{"detail":"20 per 1 hour","error_code":"HTTP_429"}``. Vì vậy ở đây có HAI lớp
kiểm: một test chạy 429 THẬT qua ASGI, và một test khẳng định lời gọi
``configure_rate_limiting`` nằm ở module level chứ không thụt vào trong lifespan.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core import rate_limits as rl
from app.core.rate_limits import RATE_LIMITED_ERROR_CODE
from app.routers.auth import RefreshAbuseLocked

LOGIN = "/api/auth/login"
REFRESH = "/api/auth/refresh"


@pytest.mark.asyncio
async def test_slowapi_429_carries_rate_limited_code_through_asgi(monkeypatch):
    """429 THẬT (đi qua ASGI + ExceptionMiddleware) mang ``RATE_LIMITED``.

    Test đi qua stack thật thay vì gọi handler trực tiếp: nếu handler không
    được gắn, ``RateLimitExceeded`` (kế thừa Starlette ``HTTPException``) rơi
    vào ``http_exception_handler`` và body thành ``HTTP_429`` — đúng lỗi đã xảy
    ra ở prod.
    """
    # configure_rate_limiting bỏ qua ở APP_ENV=test; tạm bật để dựng app thật.
    monkeypatch.setattr(rl.settings, "APP_ENV", "development", raising=False)

    app = FastAPI()
    assert rl.configure_rate_limiting(app) is True

    @app.get("/ping")
    @rl.limiter.limit("1/hour")
    async def ping(request: Request):  # noqa: ARG001 — slowapi cần tham số này
        return {"ok": True}

    headers = {"X-Real-IP": "10.111.222.33"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://ratelimit.test") as client:
        first = await client.get("/ping", headers=headers)
        second = await client.get("/ping", headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 429, second.text

    body = second.json()
    assert body["error_code"] == RATE_LIMITED_ERROR_CODE == "RATE_LIMITED", body
    # Không phải mã mặc định của http_exception_handler — đó chính là triệu
    # chứng của lỗi "đăng ký handler quá muộn".
    assert body["error_code"] != "HTTP_429"


def test_rate_limiting_is_configured_at_module_level():
    """Lời gọi ``configure_rate_limiting`` KHÔNG được nằm trong ``lifespan``.

    Starlette dựng middleware stack ngay ở scope lifespan và COPY bảng
    exception handler; đăng ký sau thời điểm đó là vô hiệu (im lặng). Test
    tĩnh vì runtime không phân biệt được: app vẫn chạy, chỉ có body 429 sai.
    """
    source = Path(__file__).resolve().parents[2] / "app" / "main.py"
    calls = [
        line
        for line in source.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*(if\s+)?configure_rate_limiting\(", line)
    ]

    assert calls, "main.py phải gọi configure_rate_limiting"
    for line in calls:
        indent = len(line) - len(line.lstrip())
        assert indent == 0, (
            "configure_rate_limiting bị thụt vào (khả năng cao nằm trong "
            f"lifespan hoặc một hàm) → handler 429 sẽ không có hiệu lực: {line!r}"
        )


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

    Chạy qua ``http_exception_handler``, nơi mặc định sẽ ghi ``HTTP_429`` và
    làm client hiểu sai thành "lỗi tạm thời" rồi giữ một phiên đã bị thu hồi.
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
