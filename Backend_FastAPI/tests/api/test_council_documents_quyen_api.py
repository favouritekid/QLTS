# -*- coding: utf-8 -*-
"""Lượt F — cờ quyền GIAO DIỆN của văn bản Hội đồng (``GET /quyen``) qua REQUEST THẬT (app thật +
lifespan + Casbin + middleware), CSDL test, DỮ LIỆU GIẢ.

Bất biến chính: **cờ bật ⇔ gọi route thật KHÔNG bị 403 / 404** — so cho từng cờ (mỗi cờ đúng một
route của module) với từng vai: admin · quản lý có đơn vị · quản lý chưa gán đơn vị · cán bộ ·
kế toán. Hành vi thật đo bằng chính route (bộ trong phạm vi người gọi; route ghi gọi với đầu vào
bị service từ chối SAU các cổng — 400 — nên không ghi gì). Vai không có dòng Casbin cho ``/quyen``
(cán bộ, kế toán) nhận 403 ở route cờ ⇒ giao diện coi là "mọi cờ tắt"; với các vai ấy phép tính
cờ còn được gọi THẲNG (``deps.quyen_van_ban_hoi_dong``) và cũng phải khớp hành vi.

Hai kịch bản Casbin GIẢ (enforcer của app bị thay ``enforce``): Casbin CHO quản lý mọi route của
module ⇒ cờ vẫn theo lớp phụ chỉ-admin / phạm vi; Casbin TỪ CHỐI admin ⇒ mọi cờ tắt. Cổng lạ
trong cây dependency ⇒ cờ tắt (fail-closed). Migration ``hdts20261105`` (dòng Casbin của manager
cho route cờ): chạy ĐÚNG SQL ``upgrade()`` / ``downgrade()`` trong giao dịch ROLLBACK (như F220).

Mỗi ca một bất biến (CLAUDE.md §3).
"""
import importlib.util
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from sqlalchemy import text
from starlette.requests import Request

import app.database as csdl
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from app import models
from app.core import deps
from app.database import AsyncSessionLocal
from app.main import fastapi_app
from app.routers import council_documents as rt
from app.schemas.council_document import CouncilDocumentPermissions
from tests.api import test_council_documents_api as api
from tests.fixtures.hoi_dong_seed import ma_gia, seed_hoi_dong

pytestmark = pytest.mark.integration

P, _dem, _dem_vet = api.P, api._dem, api._dem_vet
CO = tuple(CouncilDocumentPermissions.model_fields)
NAM_VAI = ["admin", "ql_u1", "ql_khong_dv", "can_bo", "ke_toan"]


# Ba fixture như ``test_council_documents_api.py`` — khai lại tại chỗ (flake8 F811).
@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await seed_hoi_dong(conn)


@pytest_asyncio.fixture
async def tk(client, hs):
    return api._TaiKhoan(client, hs)


@pytest_asyncio.fixture
async def ba_bo(hs):
    d = hs["_danh_muc"]
    return {
        "u1": await api._chen_bo(d["u1"], "u1"),
        "u2": await api._chen_bo(d["u2"], "u2"),
        "null": await api._chen_bo(None, "null"),
    }


async def _goi_that(client, co, h, sid):
    """Gọi ĐÚNG route của cờ ``co`` dưới headers ``h`` (bộ ``sid`` thuộc phạm vi người gọi).
    Route ghi: đầu vào bị SERVICE từ chối (400) — tức đã qua mọi cổng — nên không ghi gì."""
    b = P + "/sets/%d" % sid
    if co == "xem_mau":
        return await client.get(P + "/templates", headers=h)
    if co == "tai_mau_len":  # không phải gói zip ⇒ 400 sau các cổng, không lưu mẫu
        return await client.post(
            P + "/templates",
            data={"loai": "bien_ban", "hieu_luc_tu": "2026-01-01"},
            files={"file": ("m.docx", b"GIA-khong-phai-zip", api.KIEU_DOCX)},
            headers=h,
        )
    if co == "xem_danh_sach_bo":
        return await client.get(P + "/sets", headers=h)
    if co == "tao_bo":  # mã đúng định dạng nhưng không khớp hồ sơ nào ⇒ 400, không dựng
        return await client.post(
            P + "/sets",
            json={"ma_ho_so": [ma_gia(990001)], "academic_year": 2026},
            headers=h,
        )
    if co == "xem_chi_tiet_bo":
        return await client.get(b, headers=h)
    if co == "tai_tep":
        return await client.get(b + "/files/1", headers=h)
    if co == "xoa_bo":  # lý do rỗng ⇒ 400 sau các cổng, không xoá
        return await client.request("DELETE", b, json={"ly_do": ""}, headers=h)
    if co == "xem_ma_ho_so":
        return await client.get(b + "/ma-ho-so", headers=h)
    if co == "xem_nhat_ky_tai":
        return await client.get(P + "/nhat-ky-tai", headers=h)
    if co == "xem_nhat_ky_xoa":
        return await client.get(P + "/nhat-ky-xoa", headers=h)
    raise AssertionError("cờ chưa có cách gọi: " + co)


async def _hanh_vi_that(client, h, sid):
    """``{cờ: route KHÔNG trả 403 / 404}`` + kiểm route ghi không ghi gì."""
    out = {}
    for co in CO:
        r = await _goi_that(client, co, h, sid)
        assert r.status_code < 500, (co, r.status_code, r.text)
        out[co] = r.status_code not in (403, 404)
    assert await _dem() == (0, 3, 3)  # không tải mẫu, không dựng, không xoá
    assert (await _dem_vet())[0] == 0  # không vết xoá
    return out


async def _co_qua_http(client, h):
    """Cờ như GIAO DIỆN thấy: 200 ⇒ ``permissions``; 403 ⇒ mọi cờ tắt."""
    r = await client.get(P + "/quyen", headers=h)
    if r.status_code == 403:
        return {co: False for co in CO}
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"permissions"}
    return r.json()["permissions"]


async def _co_goi_thang(ten):
    """Phép tính cờ gọi THẲNG (không qua route ``/quyen``) cho người dùng ``ten``."""
    async with AsyncSessionLocal() as db:
        uid = (
            await db.execute(
                text('SELECT id FROM "user" WHERE username = :u'),
                {"u": "gia_e2_" + ten},
            )
        ).scalar_one()
        nguoi = await db.get(models.User, uid)
        yeu_cau = Request({"type": "http", "app": fastapi_app, "headers": []})
        return await deps.quyen_van_ban_hoi_dong(yeu_cau, nguoi, rt.ENDPOINT_THEO_CO)


# ═══════════════════════════ hợp đồng: mỗi route của module đúng một cờ ════════════════
def test_moi_route_cua_module_co_dung_mot_co():
    route = [
        r
        for r in fastapi_app.routes
        if isinstance(r, APIRoute) and r.endpoint.__module__ == rt.__name__
    ]
    ham_co = [r.endpoint for r in route if r.path == P + "/quyen"]
    assert len(ham_co) == 1  # route cờ không tự có cờ
    con_lai = [r.endpoint for r in route if r.endpoint is not ham_co[0]]
    assert len(con_lai) == len(set(con_lai)) == 10  # mỗi hàm đúng MỘT route
    assert set(rt.ENDPOINT_THEO_CO.values()) == set(con_lai)
    assert len(set(rt.ENDPOINT_THEO_CO.values())) == len(rt.ENDPOINT_THEO_CO)
    assert tuple(rt.ENDPOINT_THEO_CO) == CO  # tên trường schema = khoá bảng cờ, cùng thứ tự
    assert all(len(r.methods) == 1 for r in route)


# ═══════════════════════════ cờ = hành vi thật, năm vai ═════════════════════════════════
@pytest.mark.parametrize("vai", NAM_VAI)
async def test_co_qua_route_khop_hanh_vi_that(client, tk, ba_bo, vai):
    h = await tk(vai)
    co = await _co_qua_http(client, h)
    assert co == await _hanh_vi_that(client, h, ba_bo["u1"][0])


@pytest.mark.parametrize("vai", NAM_VAI)
async def test_ham_tinh_co_goi_thang_khop_hanh_vi_that(client, tk, ba_bo, vai):
    h = await tk(vai)
    hanh_vi = await _hanh_vi_that(client, h, ba_bo["u1"][0])
    assert await _co_goi_thang(vai) == hanh_vi


# Neo (không phải bất biến chính): hành vi thật đúng J1 dòng 9, 29–31 — để phép so "cờ = hành
# vi" ở trên không xanh RỖNG (vd fixture hỏng làm mọi route 403 và mọi cờ tắt).
_DOC_BO = {"xem_danh_sach_bo", "xem_chi_tiet_bo", "tai_tep"}
DUOC_PHEP_THEO_J1 = {
    "admin": set(CO),
    "ql_u1": _DOC_BO,
    "ql_khong_dv": set(),
    "can_bo": set(),
    "ke_toan": set(),
}


@pytest.mark.parametrize("vai", NAM_VAI)
async def test_neo_hanh_vi_that_dung_j1(client, tk, ba_bo, vai):
    hanh_vi = await _hanh_vi_that(client, await tk(vai), ba_bo["u1"][0])
    assert {c for c, duoc in hanh_vi.items() if duoc} == DUOC_PHEP_THEO_J1[vai]


async def test_route_co_chi_admin_va_quan_ly(client, tk):
    for vai, mong in (
        ("admin", 200),
        ("ql_u1", 200),
        ("ql_khong_dv", 200),
        ("can_bo", 403),
        ("ke_toan", 403),
    ):
        r = await client.get(P + "/quyen", headers=(await tk(vai)))
        assert r.status_code == mong, (vai, r.text)


# ═══════════════════════════ Casbin GIẢ: cờ vẫn theo cổng thật ══════════════════════════
async def test_casbin_cho_quan_ly_moi_route_thi_co_van_theo_lop_phu(
    client, tk, ba_bo, monkeypatch
):
    h = await tk("ql_u1")
    enf = fastapi_app.state.enforcer
    goc, da_cho = enf.enforce, []

    def enforce(sub, obj, act, *them):
        if sub == "role:manager" and obj.startswith(P):
            da_cho.append(obj)
            return True
        return goc(sub, obj, act, *them)

    monkeypatch.setattr(enf, "enforce", enforce)
    co = await _co_qua_http(client, h)
    hanh_vi = await _hanh_vi_that(client, h, ba_bo["u1"][0])
    assert da_cho, "Casbin giả không được hỏi — phép đo không hợp lệ"
    # Lớp phụ chỉ-admin (deps) vẫn chặn bốn route; ba route chỉ có cổng Casbin thì mở.
    assert {c for c, duoc in hanh_vi.items() if not duoc} == {
        "xoa_bo",
        "xem_ma_ho_so",
        "xem_nhat_ky_tai",
        "xem_nhat_ky_xoa",
    }
    assert co == hanh_vi


async def test_casbin_tu_choi_admin_thi_moi_co_tat(client, tk, ba_bo, monkeypatch):
    h = await tk("admin")
    enf = fastapi_app.state.enforcer
    goc, da_tu_choi = enf.enforce, []

    def enforce(sub, obj, act, *them):
        if sub == "role:admin" and obj.startswith(P) and obj != P + "/quyen":
            da_tu_choi.append(obj)
            return False
        return goc(sub, obj, act, *them)

    monkeypatch.setattr(enf, "enforce", enforce)
    co = await _co_qua_http(client, h)
    hanh_vi = await _hanh_vi_that(client, h, ba_bo["u1"][0])
    assert da_tu_choi, "Casbin giả không được hỏi — phép đo không hợp lệ"
    assert not any(hanh_vi.values())
    assert co == hanh_vi


async def test_cong_la_trong_cay_dependency_thi_co_tat(client, tk, monkeypatch):
    # Bỏ trống tập "không phải cổng" ⇒ mọi dependency (CSDL, xác thực…) thành cổng LẠ ⇒ cờ tắt
    # dù admin gọi được mọi route (fail-closed khi phép tính cờ không hiểu cổng của route).
    h = await tk("admin")
    assert all((await _co_qua_http(client, h)).values())  # đối chứng: admin mọi cờ bật
    monkeypatch.setattr(deps, "_KHONG_PHAI_CONG_VAN_BAN_HOI_DONG", frozenset())
    assert not any((await _co_qua_http(client, h)).values())


# ═══════════════════════════ migration hdts20261105 — chạy ĐÚNG SQL ══════════════════════
_GOC_MIG = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _nap_mig():
    spec = importlib.util.spec_from_file_location(
        "hdts20261105_f", _GOC_MIG / "hdts20261105_council_document_flags_casbin.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _nap_mig()
DUONG_CO = P + "/quyen"


def _chay(sync_conn, ham):
    ctx = MigrationContext.configure(connection=sync_conn)
    with Operations.context(ctx):
        getattr(MIG, ham)()


async def _dong_route_co(conn):
    return sorted(
        tuple(r)
        for r in (
            await conn.execute(
                text(
                    "SELECT ptype, v0, v1, v2, v3, template_id FROM casbin_rule "
                    "WHERE v1 = :d"
                ),
                {"d": DUONG_CO},
            )
        ).all()
    )


async def test_migration_co_upgrade_chen_dung_mot_dong(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            # Như production TRƯỚC migration: chưa có dòng nào cho route cờ.
            await conn.execute(
                text("DELETE FROM casbin_rule WHERE v1 = :d"), {"d": DUONG_CO}
            )
            await conn.run_sync(_chay, "upgrade")
            assert await _dong_route_co(conn) == [
                ("p", "role:manager", DUONG_CO, "GET", "allow", MIG.TEMPLATE_ID)
            ]
        finally:
            await gd.rollback()


async def test_migration_co_upgrade_khong_chen_trung(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await conn.execute(
                text("DELETE FROM casbin_rule WHERE v1 = :d"), {"d": DUONG_CO}
            )
            await conn.execute(
                text(
                    "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id) VALUES "
                    "('p', 'role:manager', :d, 'GET', 'allow', 'gia_template_khac')"
                ),
                {"d": DUONG_CO},
            )
            await conn.run_sync(_chay, "upgrade")
            assert await _dong_route_co(conn) == [
                ("p", "role:manager", DUONG_CO, "GET", "allow", "gia_template_khac")
            ]
        finally:
            await gd.rollback()


async def test_migration_co_downgrade_chi_xoa_dong_cua_minh(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await conn.execute(
                text("DELETE FROM casbin_rule WHERE v1 = :d"), {"d": DUONG_CO}
            )
            await conn.run_sync(_chay, "upgrade")
            await conn.execute(
                text(
                    "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id) VALUES "
                    "('p', 'role:officer', :d, 'GET', 'allow', 'gia_template_khac')"
                ),
                {"d": DUONG_CO},
            )
            await conn.run_sync(_chay, "downgrade")
            assert await _dong_route_co(conn) == [
                ("p", "role:officer", DUONG_CO, "GET", "allow", "gia_template_khac")
            ]
        finally:
            await gd.rollback()
