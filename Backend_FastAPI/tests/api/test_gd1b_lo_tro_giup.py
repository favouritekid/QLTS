"""Trợ giúp chung cho test lô duyệt giấy / duyệt chéo GĐ1b (agent lô). KHÔNG có ca kiểm nào ở tệp này.

- ``lo_routers``: trả ứng dụng THẬT (router + Casbin đã đăng ký ở ``app/main.py`` / ``policy_templates.py`` khi tích hợp) +
  đặt hai tham số chưa đo (N, ``lock_timeout``) bằng monkeypatch.
- ``lo_config``: đường xét tự đủ với 3 giấy bản giấy bắt buộc (A, B, D), 1 giấy bản giấy tuỳ chọn (C), 1 giấy tải tệp (U).
- ``tao_ho_so_cho_xet``: hồ sơ có giấy đã nhận bản giấy (người nhận = cán bộ phụ trách), rồi đưa sang ``submitted``.
- ``Diem`` / ``boc``: điểm dừng (phiên tới điểm ⇒ báo ``toi`` rồi CHỜ ``di``), dừng ở lần gọi thứ ``lan``.

Mỗi người thao tác một ``AsyncClient`` riêng khi chạy song song (ứng dụng ưu tiên cookie).
"""
from __future__ import annotations

import asyncio
import contextvars
import itertools
import time
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text

import app.database as csdl
from app import models
from app.database import AsyncSessionLocal
from tests.api.test_admission_doc_mutations_response_parity import _create_profile  # noqa: F401
from tests.fixtures.constants import AuthURLs

ADMISSIONS = "/api/admissions"
BULK = f"{ADMISSIONS}/documents/bulk-verify"
CROSS = f"{ADMISSIONS}/cross-review"

#: Dòng Casbin của lô / duyệt chéo: MỘT nguồn ở ``app/casbin_config/policy_templates.py`` (``GD1B_*_OBJECTS``) + migration
#: ``gd1b20261117`` (seed production) — khoá bằng nhau ở ``tests/api/test_gd1b_tich_hop_dang_ky.py``. Test KHÔNG tự thêm dòng.

#: Tham số dùng trong test (số THẬT do Claude điền sau V3 — test không phụ thuộc giá trị cụ thể).
N_TEST = 50
LOCK_TIMEOUT_MS_TEST = 3000


@pytest_asyncio.fixture
async def lo_routers(client, monkeypatch):
    """Từ khi tích hợp (bổ sung hợp đồng bản 5 A4): router do ``app/main.py`` đăng ký, dòng Casbin do ``policy_templates.py``
    seed — fixture KHÔNG tự đăng ký / thêm dòng nữa (tự đăng ký thì test xanh cả khi ``main.py`` sai thứ tự hay thiếu dòng
    Casbin — CLAUDE.md §10). Chỉ đặt hai tham số chưa đo (N, ``lock_timeout``) bằng monkeypatch."""
    from app.main import fastapi_app
    from app.services import document_bulk_verify_service as svc

    monkeypatch.setattr(svc, "BULK_VERIFY_MAX_DOCUMENTS", N_TEST)
    monkeypatch.setattr(svc, "BULK_VERIFY_LOCK_TIMEOUT_MS", LOCK_TIMEOUT_MS_TEST)
    yield fastapi_app


@pytest_asyncio.fixture
async def lo_config(seed_lead_dependencies: dict):
    """Đường xét tự đủ (chép khuôn ``parity_config``): A, B, D bản giấy bắt buộc; C bản giấy tuỳ chọn; U tải tệp bắt buộc."""
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp() * 1000)}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ot = models.ConfigOfferingType(code=f"lo_{ts}", name=f"LO_{ts}", display_order=1)
            s.add(ot)
            await s.flush()
            dts = {
                k: models.ConfigDocumentType(code=f"lo_{k.lower()}_{ts}", name=f"LO_{k}_{ts}", display_order=i)
                for i, k in enumerate(("A", "B", "C", "D", "U"), start=1)
            }
            s.add_all(dts.values())
            await s.flush()
            po = models.ProgramOffering(
                offering_type=f"LO_{ts}", program_id=mpid, offering_type_id=ot.id, is_active=True, duration_semesters=6
            )
            s.add(po)
            await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=po.id, academic_year=2026, tuition_fee_per_year=5000000, annual_admission_quota=100,
                is_published=True,
            )
            s.add(ai)
            await s.flush()
            am = models.AdmissionMethod(
                code=f"lo_{ts}", name=f"LO_{ts}", requires_gpa=True, requires_subject_scores=False, is_active=True
            )
            s.add(am)
            await s.flush()
            ac = models.AdmissionCriteria(
                method_id=am.id, code=f"LOTC_{ts}", name=f"LOTC_{ts}", min_gpa=0.0, scoring_method="average",
                subject_selection_mode="fixed", policy_version="2026.1", is_active=True,
            )
            s.add(ac)
            await s.flush()
            from tests.fixtures.builders import AdmissionRoundBuilder

            round_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id, admission_round_id=round_id, criteria_id=ac.id,
                status="active", display_name=f"Lo {ts}", display_order=0, visibility="public",
            )
            s.add(ap)
            await s.flush()
            dg = models.DocumentGroup(
                offering_type_id=ot.id, admission_method_id=am.id, code=f"lodg_{ts}", name=f"LODG_{ts}", is_active=True
            )
            s.add(dg)
            await s.flush()
            cau_hinh = {"A": (True, False), "B": (True, False), "C": (False, False), "D": (True, False), "U": (True, True)}
            s.add_all(
                [
                    models.DocumentGroupItem(
                        group_id=dg.id, document_type_id=dts[k].id, is_mandatory=bb, requires_upload=tai,
                        submission_format="photo", display_order=i,
                    )
                    for i, (k, (bb, tai)) in enumerate(cau_hinh.items(), start=1)
                ]
            )
            await s.flush()
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "round_id": round_id,
        "codes": {k: dt.code for k, dt in dts.items()},
    }


#: User-Agent khác nhau ⇒ "thiết bị" khác nhau: đăng nhập lại trên CÙNG thiết bị thu hồi phiên cũ
#: (``session_service._revoke_previous_sessions_on_device``) ⇒ hai client cùng người phải khác thiết bị.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
)
_UA_LUOT = itertools.cycle(_UA)


async def dang_nhap(user: dict):
    from app.main import fastapi_app

    c = AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test", headers={"User-Agent": next(_UA_LUOT)}
    )
    r = await c.post(AuthURLs.LOGIN, data={"username": user["username"], "password": user["password"]})
    assert r.status_code == 200, r.text
    return c, {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


async def dn(client: AsyncClient, user: dict) -> dict:
    """Đổi danh tính trên client chung: xoá cookie rồi đăng nhập lại (ứng dụng ưu tiên cookie)."""
    client.cookies.clear()
    r = await client.post(AuthURLs.LOGIN, data={"username": user["username"], "password": user["password"]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


async def giay(profile_id: int, code: str) -> models.ProfileDocument:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.ProfileDocument)
                .join(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
                .where(models.ProfileDocument.profile_id == profile_id, models.ConfigDocumentType.code == code)
            )
        ).scalar_one()


async def tao_ho_so_cho_xet(
    client: AsyncClient,
    admin_headers: dict,
    officer: dict,
    cfg: dict,
    suffix: str,
    *,
    giay_nhan: Iterable[str] = ("A", "B"),
    nguoi_nhan: Optional[dict] = None,
    trang_thai: str = "submitted",
) -> Dict:
    """Hồ sơ (lead của ``officer``) + nhận bản giấy các giấy ``giay_nhan`` (người nhận = ``nguoi_nhan`` hoặc cán bộ) + đổi
    trạng thái hồ sơ. Trả ``{"id", "docs": {khoá: ProfileDocument}}``."""
    prof = await _create_profile(client, admin_headers, officer, cfg, suffix)
    assert "id" in prof, prof
    pid = prof["id"]
    nguoi = nguoi_nhan or officer
    h = await dn(client, nguoi)
    for k in giay_nhan:
        r = await client.post(
            f"{ADMISSIONS}/{pid}/documents/{cfg['codes'][k]}/paper-submitted", headers=h,
            json={"actual_submission_format": "original"},
        )
        assert r.status_code in (200, 201), r.text
    client.cookies.clear()
    if trang_thai != "draft":
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(text("UPDATE admission_profile SET status = :st WHERE id = :p"), {"st": trang_thai, "p": pid})
    docs = {k: await giay(pid, cfg["codes"][k]) for k in cfg["codes"]}
    return {"id": pid, "docs": docs}


async def sql(cau: str, **ts):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await s.execute(text(cau), ts)


async def dong_lo(batch_id) -> Optional[dict]:
    async with AsyncSessionLocal() as s:
        r = (await s.execute(text("SELECT * FROM document_bulk_batch WHERE batch_id = :b"), {"b": str(batch_id)})).mappings().first()
        return dict(r) if r else None


async def dong_muc(batch_id) -> List[dict]:
    async with AsyncSessionLocal() as s:
        return [
            dict(r)
            for r in (
                await s.execute(
                    text(
                        "SELECT * FROM document_bulk_batch_item WHERE batch_id = :b ORDER BY profile_id, document_row_id"
                    ),
                    {"b": str(batch_id)},
                )
            ).mappings().all()
        ]


async def khoa_vung_lo() -> List[dict]:
    """Mọi khoá tư vấn đang có trong vùng ``ns`` của lô (mọi phiên)."""
    from app.core.advisory_lock_keys import BULK_VERIFY_BATCH_NS

    async with csdl.engine.connect() as k:
        return [
            dict(r)
            for r in (
                await k.execute(
                    text(
                        "SELECT pid, objid::bigint AS k, granted FROM pg_locks WHERE locktype = 'advisory'"
                        " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
                        " AND classid::bigint = :ns AND objsubid = 2"
                    ),
                    {"ns": BULK_VERIFY_BATCH_NS},
                )
            ).mappings().all()
        ]


async def cho_khoa_vang(ns_k: int, giay_toi_da: float = 2.0) -> bool:
    het = time.monotonic() + giay_toi_da
    while time.monotonic() < het:
        if not [x for x in await khoa_vung_lo() if x["k"] == ns_k]:
            return True
        await asyncio.sleep(0.05)
    return False


class Diem:
    """Phiên tới điểm ⇒ báo ``toi`` rồi CHỜ ``di``. Chỉ dừng ở lần gọi thứ ``lan`` (mặc định lần đầu)."""

    def __init__(self, lan: int = 1):
        self.toi = asyncio.Event()
        self.di = asyncio.Event()
        self.so_lan = 0
        self.lan = lan

    async def cho(self):
        self.so_lan += 1
        if self.so_lan == self.lan:
            self.toi.set()
            await asyncio.wait_for(self.di.wait(), 60)


def boc(monkeypatch, chu, ten, diem: Diem, *, truoc: bool = False):
    """Bọc ``chu.ten``: dừng tại ``diem`` SAU (mặc định) hoặc TRƯỚC khi gọi hàm gốc."""
    goc = getattr(chu, ten)

    async def boc_(*a, **kw):
        if truoc:
            await diem.cho()
            return await goc(*a, **kw)
        kq = await goc(*a, **kw)
        await diem.cho()
        return kq

    monkeypatch.setattr(chu, ten, boc_)
    return goc


NHAN: contextvars.ContextVar = contextvars.ContextVar("gd1b_lo_nhan", default=None)


class PidTheoNhan:
    """PID máy chủ PostgreSQL của mọi kết nối (engine chính) mà yêu cầu mang nhãn dùng (mẫu ``test_gd1b_hai_phien``)."""

    def __init__(self):
        self.pid: Dict[str, set] = {}
        self.cau: Dict[str, list] = {}

    def __enter__(self):
        event.listen(csdl.engine.sync_engine, "before_cursor_execute", self._ghi)
        return self

    def __exit__(self, *a):
        event.remove(csdl.engine.sync_engine, "before_cursor_execute", self._ghi)

    def _ghi(self, conn, cursor, statement, parameters, context, executemany):
        nhan = NHAN.get()
        if nhan:
            self.pid.setdefault(nhan, set()).add(conn.connection.driver_connection.get_server_pid())
            self.cau.setdefault(nhan, []).append(statement)


async def goi(nhan, ham):
    NHAN.set(nhan)
    return await ham()


async def bi_chan_boi(viec, ghi: PidTheoNhan, bi="B", boi="A", giay=20.0) -> str:
    het = time.monotonic() + giay
    while time.monotonic() < het:
        bi_pid, boi_pid = set(ghi.pid.get(bi, ())), set(ghi.pid.get(boi, ()))
        if bi_pid and boi_pid:
            async with csdl.engine.connect() as k:
                hang = (
                    await k.execute(
                        text("SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid = ANY(:p)"),
                        {"p": list(bi_pid)},
                    )
                ).all()
            if any(set(chan) & boi_pid for _, chan in hang):
                return "chan"
        if viec.done():
            return "xong"
        await asyncio.sleep(0.1)
    return "het_gio"
