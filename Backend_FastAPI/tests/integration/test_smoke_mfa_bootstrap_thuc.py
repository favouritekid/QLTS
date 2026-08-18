"""Bootstrap MFA chạy trên DB THẬT — không phải quét mã nguồn.

Vì sao tệp này tồn tại
======================

`tests/unit/test_smoke_bootstrap_personas.py` tự khai ngay ở docstring rằng phần
chạm DB "không kiểm được ở đây". Hệ quả đo được: toàn bộ ca MFA ở đó chỉ **quét
văn bản mã nguồn**, nên chúng xác nhận được "có gọi `enable_mfa`" nhưng **không**
xác nhận được điều gì xảy ra sau lời gọi ấy.

Và đúng chỗ đó có một lỗ thật, lọt qua 351 ca xanh:

    mfa_service.enable_mfa(..., current_session_id=None)

`mfa_service.py:241` chỉ thu hồi phiên khi ``if current_session_id:``. Truyền
``None`` ⇒ **không phiên nào bị thu hồi**. Mà ``get_current_active_user`` chỉ kiểm
CỜ ``mfa_enabled``, nên một phiên đăng nhập TRƯỚC khi bật MFA vẫn đi qua cổng sau
đó, chưa từng trả lời một challenge TOTP nào.

Hậu quả không phải "kém đẹp": lượt smoke kế tiếp sẽ *chứng minh* FIN-09 chạy được
bằng đúng một phiên chưa qua MFA. Bằng chứng sai, và sai theo hướng dễ tin nhất.

Một bộ test quét chuỗi không bao giờ bắt được lớp lỗi này. Phải chạy thật.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _goc_backend() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts").is_dir() and (goc / "tests").is_dir():
            return goc
    pytest.fail("không xác định được gốc Backend_FastAPI")


_GOC = _goc_backend()
_TEP = _GOC / "scripts" / "smoke_bootstrap_personas.py"
if str(_GOC) not in sys.path:
    sys.path.insert(0, str(_GOC))

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _nap_bootstrap():
    assert _TEP.is_file(), f"thiếu {_TEP}"
    spec = importlib.util.spec_from_file_location("smoke_bootstrap_thuc", _TEP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _khoa_mfa(monkeypatch):
    """Khoá Fernet dùng-một-lần cho ca test — không đụng cấu hình thật."""
    from cryptography.fernet import Fernet
    from app.config import settings

    khoa = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", khoa, raising=False)
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", khoa)
    monkeypatch.setenv("DEVICE_FINGERPRINT_SALT", "muoi-test-du-dai-16")
    return khoa


async def _tao_phien(db, user_id: int, jti: str):
    """Một phiên ACTIVE, giống hệt thứ `create_session` để lại sau khi đăng nhập."""
    from app import models

    now = datetime.now(timezone.utc)
    s = models.UserSession(
        user_id=user_id,
        refresh_jti=jti,
        expires_at=now + timedelta(days=30),
        created_at=now,
        last_activity_at=now,
    )
    db.add(s)
    await db.flush()
    return s


async def test_ca_kiem_nay_co_du_manh_khong(setup_test_database, manager_user_in_db):
    """Vô nghĩa nếu phiên dựng sẵn không thật sự ACTIVE trước khi bật MFA."""
    from app.database import AsyncSessionLocal
    from app.repositories.session_repository import SessionRepository

    async with AsyncSessionLocal() as db:
        await _tao_phien(db, manager_user_in_db["id"], "jti-truoc-mfa-manh")
        await db.commit()
        con = await SessionRepository(db).get_active_by_user(manager_user_in_db["id"])
        assert len(con) >= 1, (
            "không dựng nổi một phiên active — mọi ca dưới đây sẽ xanh vì không có "
            "gì để thu hồi, chứ không phải vì bản vá đúng"
        )


async def test_bat_mfa_thu_hoi_MOI_phien_cu(setup_test_database, manager_user_in_db):
    """Đây là ca đáng lẽ phải đỏ khi `current_session_id=None` không được bù.

    Trước bản vá: `enable_mfa` bỏ qua nhánh thu hồi ⇒ phiên cũ VẪN active ⇒ ca đỏ.
    Sau bản vá: `bat_mfa` gọi thẳng `revoke_all_other_sessions(except=None)`.
    """
    from app.database import AsyncSessionLocal
    from app.repositories.session_repository import SessionRepository

    mod = _nap_bootstrap()
    uid = manager_user_in_db["id"]

    async with AsyncSessionLocal() as db:
        await _tao_phien(db, uid, "jti-truoc-mfa-1")
        await _tao_phien(db, uid, "jti-truoc-mfa-2")
        await db.commit()

    async with AsyncSessionLocal() as db:
        from app import models
        from sqlalchemy import select

        u = (
            await db.execute(select(models.User).where(models.User.id == uid))
        ).scalars().first()
        assert u is not None and not u.mfa_enabled

        ket = await mod.bat_mfa(db, u)
        await db.commit()

    assert ket.startswith("vua_bat"), ket

    async with AsyncSessionLocal() as db:
        con_lai = await SessionRepository(db).get_active_by_user(uid)
        assert con_lai == [] or len(con_lai) == 0, (
            f"còn {len(con_lai)} phiên ACTIVE sau khi bật MFA — phiên đăng nhập "
            "TRƯỚC khi bật vẫn đi qua `get_current_active_user` (chỉ kiểm cờ "
            "mfa_enabled) mà chưa hề trả lời challenge TOTP nào. FIN-09 sẽ được "
            "'chứng minh' bằng một phiên chưa qua MFA."
        )


async def test_bat_mfa_ghi_secret_giai_ma_duoc(setup_test_database, manager_user_in_db):
    """Cờ bật mà secret rỗng là trạng thái tệ hơn chưa bật — nó trông như xong."""
    from sqlalchemy import select
    from app import models
    from app.database import AsyncSessionLocal
    from app.services import mfa_service

    mod = _nap_bootstrap()
    uid = manager_user_in_db["id"]

    async with AsyncSessionLocal() as db:
        u = (
            await db.execute(select(models.User).where(models.User.id == uid))
        ).scalars().first()
        await mod.bat_mfa(db, u)
        await db.commit()

    async with AsyncSessionLocal() as db:
        u = (
            await db.execute(select(models.User).where(models.User.id == uid))
        ).scalars().first()
        assert u.mfa_enabled is True
        assert u.totp_secret_encrypted, "bật cờ mà không có secret"

        # giải mã THẬT rồi sinh mã — chứng minh persona đăng nhập được
        import pyotp
        secret = mfa_service.decrypt_secret(u.totp_secret_encrypted)
        ma = pyotp.TOTP(secret).now()
        assert len(ma) == 6 and ma.isdigit(), ma
        assert mfa_service.verify_totp(secret, ma), (
            "mã sinh từ secret đã ghi KHÔNG verify được — persona sẽ không đăng "
            "nhập nổi dù cờ đã bật"
        )


async def test_bat_mfa_idempotent_tren_DB(setup_test_database, manager_user_in_db):
    """Lượt hai không được ném, không được đổi secret."""
    from sqlalchemy import select
    from app import models
    from app.database import AsyncSessionLocal

    mod = _nap_bootstrap()
    uid = manager_user_in_db["id"]

    async with AsyncSessionLocal() as db:
        u = (
            await db.execute(select(models.User).where(models.User.id == uid))
        ).scalars().first()
        await mod.bat_mfa(db, u)
        await db.commit()
        secret_1 = u.totp_secret_encrypted

    async with AsyncSessionLocal() as db:
        u = (
            await db.execute(select(models.User).where(models.User.id == uid))
        ).scalars().first()
        ket2 = await mod.bat_mfa(db, u)
        await db.commit()

    assert ket2 == "da_bat", ket2

    async with AsyncSessionLocal() as db:
        u = (
            await db.execute(select(models.User).where(models.User.id == uid))
        ).scalars().first()
        assert u.totp_secret_encrypted == secret_1, (
            "lượt hai ghi đè secret — người dùng mất thiết bị đã ghép"
        )


async def test_ma_totp_khong_tra_ve_secret(setup_test_database, manager_user_in_db):
    """`ma_totp` chỉ được trả mã 6 số, không trả secret."""
    from sqlalchemy import select
    from app import models
    from app.database import AsyncSessionLocal
    from app.services import mfa_service

    mod = _nap_bootstrap()
    uid = manager_user_in_db["id"]
    ten = manager_user_in_db["username"]

    async with AsyncSessionLocal() as db:
        u = (
            await db.execute(select(models.User).where(models.User.id == uid))
        ).scalars().first()
        await mod.bat_mfa(db, u)
        await db.commit()
        secret = mfa_service.decrypt_secret(u.totp_secret_encrypted)

    async with AsyncSessionLocal() as db:
        ra = await mod.ma_totp(db, ten)

    assert len(ra) == 6 and ra.isdigit(), ra
    assert secret not in ra and ra != secret
