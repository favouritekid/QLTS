"""Tiện ích dùng chung cho các bước smoke — gọi API THẬT qua HTTP.

Chạy trong container backend (cùng network, gọi http://backend:8000).
"""
import asyncio
import json
import os
from decimal import Decimal

import httpx

BASE = os.environ.get("SMOKE_BASE", "http://backend:8000")
PW = "Test@12345"

_KQ = []


def ghi(muc: str, ten: str, dat: bool, chi_tiet: str = ""):
    _KQ.append({"muc": muc, "ten": ten, "pass": bool(dat), "chi_tiet": chi_tiet})
    dau = "PASS" if dat else "FAIL"
    print(f"[{dau}] {muc} — {ten}" + (f" :: {chi_tiet}" if chi_tiet else ""))
    return dat


def tong_ket(nhan: str):
    tot = sum(1 for k in _KQ if k["pass"])
    print(f"\n===== {nhan}: {tot}/{len(_KQ)} PASS =====")
    for k in _KQ:
        if not k["pass"]:
            print(f"  FAIL: {k['muc']} — {k['ten']} :: {k['chi_tiet']}")
    print("SMOKE_RESULT_JSON " + json.dumps(
        {"nhan": nhan, "tong": len(_KQ), "pass": tot,
         "fail": [k for k in _KQ if not k["pass"]]}, ensure_ascii=False))
    return tot == len(_KQ)


async def xoa_gioi_han_dang_nhap():
    """Xoá bộ đếm rate-limit + lockout trong Redis.

    Endpoint login giới hạn 5 lần/khoảng — đúng về bảo mật, nhưng kịch bản smoke
    cần đăng nhập 7 vai liên tiếp. Xoá bộ đếm là thao tác của môi trường kiểm
    thử, KHÔNG phải nới lỏng ứng dụng.
    """
    import redis.asyncio as aioredis

    for db in (0, 1, 2, 3):
        try:
            r = aioredis.from_url(f"redis://redis:6379/{db}")
            keys = []
            async for k in r.scan_iter(match="*LIMITER*"):
                keys.append(k)
            async for k in r.scan_iter(match="*lockout*"):
                keys.append(k)
            async for k in r.scan_iter(match="*login_attempt*"):
                keys.append(k)
            if keys:
                await r.delete(*keys)
            await r.aclose()
        except Exception:
            pass


async def tao_client(username: str) -> httpx.AsyncClient:
    """Client ĐÃ đăng nhập cho một vai — mỗi vai một cookie jar riêng.

    Token nằm trong cookie httpOnly (không có trong body), và mutation cần
    CSRF double-submit qua header ``X-CSRF-Token``.
    """
    c = httpx.AsyncClient(timeout=90, follow_redirects=False)
    # Endpoint dùng OAuth2PasswordRequestForm ⇒ form-data, KHÔNG phải JSON.
    for lan in range(6):
        r = await c.post(f"{BASE}/api/auth/login",
                         data={"username": username, "password": PW})
        if r.status_code != 429:
            break
        await xoa_gioi_han_dang_nhap()
        await asyncio.sleep(1 + lan)
    r.raise_for_status()
    csrf = c.cookies.get("csrf_token") or c.cookies.get("csrftoken")
    if csrf:
        c.headers["X-CSRF-Token"] = csrf
    me = await c.get(f"{BASE}/api/users/me")
    assert me.status_code == 200, f"login {username} nhưng /users/me = {me.status_code}"
    return c


def tien(x) -> Decimal:
    return Decimal(str(x))
