"""Trợ giúp chung cho test PR-B (quyền / phạm vi duyệt chéo GĐ1b). KHÔNG có ca kiểm nào ở tệp này.

- ``tao_nguoi``: người dùng thật (vai DB + dòng Casbin ``g``) — Casbin THẬT, không mock enforcer.
- ``cap`` / ``ho_so``: Admin cấp quyền chéo qua HTTP; hồ sơ chờ xét (khuôn ``gd1b_lo_tro_giup.tao_ho_so_cho_xet``).
- ``KhoaHo``: một kết nối RIÊNG giữ khoá ``FOR UPDATE`` một dòng (phiên A của phép đo hai phiên).
- ``bi_chan_boi_pid``: phiên thứ ba hỏi ``pg_blocking_pids`` — yêu cầu mang nhãn có bị ĐÚNG các PID cho trước chặn không.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Set

import pytest_asyncio
from sqlalchemy import text

import app.database as csdl
from app import models
from app.database import AsyncSessionLocal
from tests.api.gd1b_lo_tro_giup import CROSS, PidTheoNhan, dn, tao_ho_so_cho_xet

#: Thân 403 của Casbin (``deps.CASBIN_PERMISSION_DENIED_DETAIL``) — owner Q1: mọi vai khác Cán bộ nhận ĐÚNG thân này.
THAN_403 = {"detail": "You do not have permission for this action.", "error_code": "PERMISSION_DENIED"}
#: Thân 404 chung của luồng duyệt chéo (owner Q1).
THAN_404 = {"detail": "Không tìm thấy", "error_code": "RESOURCE_NOT_FOUND"}
#: Mã hồ sơ / lô chắc chắn không tồn tại (trong biên INT4).
KHONG_TON_TAI = 2_147_480_000
LO_KHONG_TON_TAI = "4f6a1c1e-2b3d-4c5e-8f70-123456789abc"


async def tao_nguoi(username: str, role: str, unit_id: Optional[int]) -> dict:
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule

    from app.main import fastapi_app
    from app.security import get_password_hash
    from tests.fixtures.users import create_user_with_role

    return await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": username,
            "email": f"{username}@example.com",
            "password": "CheoPrB@2026x",
            "role": role,
            "status": "active",
        },
        casbin_role=f"role:{role}",
        unit_id=unit_id,
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=fastapi_app,
    )


@pytest_asyncio.fixture
async def can_bo_cheo(setup_test_database, seed_other_unit):
    """Cán bộ ĐƠN VỊ KHÁC (đơn vị thứ hai) — người được cấp quyền duyệt chéo đơn vị mặc định."""
    return await tao_nguoi("prb_cheo_canbo", "officer", seed_other_unit["unit_id"])


def han(ngay: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=ngay)).isoformat()


async def cap(client, admin, grantee_id, unit_id, *, verify=False, reject=False, ngay=3.0, ly_do="Thiếu người duyệt"):
    h = await dn(client, admin)
    r = await client.post(
        f"{CROSS}/grants",
        headers=h,
        json={
            "grantee_user_id": grantee_id, "unit_id": unit_id, "allow_verify": verify, "allow_reject": reject,
            "expires_at": han(ngay), "reason": ly_do,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def ho_so(client, admin_h, officer, cfg, n=1, tien_to="prb", giay_nhan="AB", nguoi_nhan=None):
    # Ứng dụng ưu tiên cookie: xoá cookie của lần ``dn`` trước để ``admin_h`` (Admin) thật sự là người tạo lead / hồ sơ.
    client.cookies.clear()
    return [
        await tao_ho_so_cho_xet(client, admin_h, officer, cfg, f"{tien_to}{i}", giay_nhan=giay_nhan, nguoi_nhan=nguoi_nhan)
        for i in range(n)
    ]


async def mot(cau: str, **ts):
    """Một giá trị đọc từ phiên CSDL RIÊNG (không qua dịch vụ)."""
    async with AsyncSessionLocal() as s:
        return (await s.execute(text(cau), ts)).scalar_one_or_none()


async def hang(cau: str, **ts):
    async with AsyncSessionLocal() as s:
        return [dict(r) for r in (await s.execute(text(cau), ts)).mappings().all()]


class KhoaHo:
    """Phiên A: kết nối RIÊNG, mở giao dịch và giữ ``FOR UPDATE`` một dòng cho tới ``tha()``."""

    def __init__(self, cau: str, **ts):
        self.cau, self.ts = cau, ts
        self.pid: Optional[int] = None

    async def giu(self):
        self._k = await csdl.engine.connect()
        self._tx = await self._k.begin()
        self.pid = (await self._k.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        await self._k.execute(text(self.cau), self.ts)
        return self

    async def tha(self):
        if getattr(self, "_tx", None) is not None:
            await self._tx.rollback()
            self._tx = None
        if getattr(self, "_k", None) is not None:
            await self._k.close()
            self._k = None


async def bi_chan_boi_pid(viec, ghi: PidTheoNhan, nhan: str, pid_chan: Iterable[int], giay: float = 20.0) -> str:
    """``"chan"`` khi một kết nối của yêu cầu ``nhan`` đang bị (một trong) ``pid_chan`` chặn — hỏi từ phiên thứ ba
    (``pg_blocking_pids``); ``"xong"`` nếu ``viec`` kết thúc trước; ``"het_gio"``."""
    chan_set: Set[int] = set(pid_chan)
    het = time.monotonic() + giay
    while time.monotonic() < het:
        bi_pid = set(ghi.pid.get(nhan, ()))
        if bi_pid:
            async with csdl.engine.connect() as k:
                rows = (
                    await k.execute(
                        text("SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid = ANY(:p)"),
                        {"p": list(bi_pid)},
                    )
                ).all()
            if any(set(c) & chan_set for _, c in rows):
                return "chan"
        if viec.done():
            return "xong"
        await asyncio.sleep(0.1)
    return "het_gio"


def quet_gia_tri(obj, khoa_chua=None):
    """Mọi cặp (khoá, giá trị lá) trong JSON (đệ quy). ``khoa_chua``: chỉ lấy khoá có chứa chuỗi này."""
    out = []

    def di(o, k=None):
        if isinstance(o, dict):
            for kk, vv in o.items():
                di(vv, kk)
        elif isinstance(o, list):
            for vv in o:
                di(vv, k)
        elif khoa_chua is None or (k is not None and khoa_chua in k):
            out.append((k, o))

    di(obj)
    return out
