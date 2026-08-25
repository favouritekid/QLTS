"""Hai race MFA — REPRODUCER chạy được trên CẢ cây cũ lẫn cây mới.

Vì sao tệp này tách riêng: nó **không import một symbol nào mới**. Chỉ dùng
``mfa_service.verify_mfa_code`` và endpoint ``POST /api/auth/verify-mfa`` —
hai thứ đã có từ trước bản vá. Nhờ vậy nó collect và chạy được nguyên vẹn trên
commit cha (``e84e0cd8``), nơi nó ĐỎ, và trên cây đã vá, nơi nó XANH.

Các tệp guard kia (``test_mfa_single_use_atomic*.py``) import
``KetQuaChiem``/``safe_redis_*`` mới nên KHÔNG collect được trên cây cũ — chúng
là guard hồi quy, không phải bằng chứng tái hiện. Đừng trích chúng khi nói
"đỏ trên base"; trích tệp này.

Đo được trên ``e84e0cd8``:

    A) AssertionError: 2/2 request cùng được chấp nhận cho MỘT mã TOTP
    B) AssertionError: _complete_login_flow chạy 2 lần cho MỘT mfa_token

An toàn: khoá riêng theo id ngẫu nhiên, xoá trong ``finally``. Không FLUSHDB.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace

import pyotp
import pytest
import pytest_asyncio
from fastapi.responses import JSONResponse

from app import database as db_mod
from app.routers import auth as auth_router
from app.services import mfa_service
from tests.fixtures.redis import _original_from_url_async

pytestmark = pytest.mark.asyncio


def _redis_url() -> str:
    return os.getenv("REDIS_URL") or "redis://localhost:6379/0"


def _thong_bao_an_toan(pha: str, exc: BaseException) -> str:
    """Thông báo lỗi KHÔNG mang credential (REDIS_URL có user:password)."""
    return (
        f"Không {pha} được Redis thật ({type(exc).__name__}). "
        "Kiểm biến môi trường REDIS_URL và service redis của cổng CI."
    )


@pytest_asyncio.fixture
async def redis_that():
    """Redis THẬT, dựng bằng callable gốc đã lưu trước lúc patch FakeRedis."""
    try:
        client = _original_from_url_async(_redis_url(), decode_responses=True)
    except Exception as exc:  # pragma: no cover - lỗi cấu hình
        pytest.fail(_thong_bao_an_toan("dựng client", exc))

    assert "fakeredis" not in (type(client).__module__ or ""), (
        "Client vẫn là FakeRedis — tệp này mất ý nghĩa trên bản giả."
    )
    try:
        assert await client.ping() is True
    except Exception as exc:
        await client.aclose()
        pytest.fail(_thong_bao_an_toan("kết nối", exc))

    try:
        yield client
    finally:
        await client.aclose()


class TestTaiHienRaceTotp:
    async def test_hai_request_cung_ma_totp_chi_mot_lan_duoc_chap_nhan(
        self, redis_that, monkeypatch
    ):
        """Bằng chứng cho race A. ĐỎ trên e84e0cd8, XANH sau bản vá."""
        monkeypatch.setattr(db_mod, "redis_client", redis_that)
        secret = pyotp.random_base32()
        monkeypatch.setattr(mfa_service, "decrypt_secret", lambda _c: secret)

        user = SimpleNamespace(
            id=900_000_000_000 + (uuid.uuid4().int % 10_000_000),
            totp_secret_encrypted="khong-dung-den-vi-decrypt-bi-patch",
            backup_codes_hashed=None,
        )
        code = pyotp.TOTP(secret).now()
        key = f"totp_used:{user.id}"

        try:
            ket_qua = await asyncio.gather(
                mfa_service.verify_mfa_code(None, user, code),
                mfa_service.verify_mfa_code(None, user, code),
            )
            so_nhan = sum(1 for k in ket_qua if k)
            assert so_nhan == 1, (
                f"{so_nhan}/2 request cùng được chấp nhận cho MỘT mã TOTP. "
                f"Đọc-rồi-ghi không nguyên tử thì cả hai cùng thấy 'chưa dùng'. "
                f"Kết quả: {ket_qua}"
            )
        finally:
            await redis_that.delete(key)
            assert await redis_that.exists(key) == 0


class TestTaiHienRaceMfaToken:
    async def test_hai_request_cung_token_chi_mot_lan_hoan_tat_dang_nhap(
        self, client, test_user_in_db, clear_redis_keys, monkeypatch
    ):
        """Bằng chứng cho race B. ĐỎ trên e84e0cd8, XANH sau bản vá.

        Phép đo là SỐ LẦN ``_complete_login_flow`` chạy, không phải mã trạng
        thái: mã trạng thái không phân biệt được "bị chặn" với "hỏng vì lý do
        khác".
        """
        token = mfa_service.create_mfa_token(
            test_user_in_db["username"], test_user_in_db["id"]
        )

        async def _verify_ok(db, user, code):
            await asyncio.sleep(0)  # để hai request thật sự đan vào nhau
            return True

        monkeypatch.setattr(mfa_service, "verify_mfa_code", _verify_ok)

        so_lan = {"n": 0}

        async def _fake_complete(user, request, db):
            so_lan["n"] += 1
            return JSONResponse(status_code=200, content={"ok": True})

        monkeypatch.setattr(auth_router, "_complete_login_flow", _fake_complete)

        await asyncio.gather(
            client.post(
                "/api/auth/verify-mfa", json={"mfa_token": token, "code": "123456"}
            ),
            client.post(
                "/api/auth/verify-mfa", json={"mfa_token": token, "code": "123456"}
            ),
        )

        assert so_lan["n"] == 1, (
            f"_complete_login_flow chạy {so_lan['n']} lần cho MỘT mfa_token. "
            "Một bằng chứng MFA đã đổi được hai phiên đăng nhập."
        )
