# -*- coding: utf-8 -*-
"""Lượt G — cổng dựng bộ qua REQUEST THẬT ``POST /sets`` (app + lifespan + Casbin + deps), CSDL
test, DỮ LIỆU GIẢ: nối dây của F228 (409 cần admin xác nhận / 400 chặn), quyền xác nhận do
``deps.get_council_document_confirm_right`` tính (chỉ admin), vết xác nhận đọc lại được qua
``GET /sets/{id}``; quản lý (Casbin GIẢ cho phép ``POST /sets``) bị từ chối kèm số đếm, gửi xác
nhận ⇒ 403; không ghi gì ở mọi nhánh từ chối. Mỗi ca một bất biến (CLAUDE.md §3).
"""
import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from sqlalchemy import text

import app.database as csdl
from app.core import deps
from app.main import fastapi_app
from app.routers import council_documents as rt
from tests.api import test_council_documents_api as api
from tests.fixtures.hoi_dong_seed import seed_hoi_dong

pytestmark = pytest.mark.integration

P, _dem = api.P, api._dem


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await seed_hoi_dong(conn)


@pytest_asyncio.fixture
async def tk(client, hs):
    return api._TaiKhoan(client, hs)


@pytest_asyncio.fixture
async def mau(client, tk):
    return await api._tai_ba_mau_api(client, await tk("admin"))


def _than(hs, nhan, **them):
    return dict({"ma_ho_so": [hs[n][0] for n in nhan], "academic_year": 2026}, **them)


async def _dat_trang_thai(hs, nhan, s):
    """Đổi trạng thái MỘT hồ sơ sạch của dữ liệu giả (mọi nguồn khác giữ nguyên ⇒ đúng một bất
    biến bị chạm)."""
    async with csdl.engine.begin() as c:
        await c.execute(
            text("UPDATE admission_profile SET status = :s WHERE id = :p"),
            {"s": s, "p": hs[nhan][1]},
        )


SACH = ["dia_chi_rong", "nhieu_nv_khoang_trang", "loai_hinh_chinh_quy"]


async def test_route_tao_bo_noi_quyen_xac_nhan(hs):
    # Nối dây: route POST /sets có ĐÚNG dependency tính quyền xác nhận của deps.py.
    r = [
        x
        for x in fastapi_app.routes
        if isinstance(x, APIRoute) and x.endpoint is rt.create_council_document_set
    ]
    assert len(r) == 1
    goi = deps._ham_trong_cay_dependency(r[0].dependant)
    assert deps.get_council_document_confirm_right in goi


async def test_admin_canh_bao_chua_xac_nhan_thi_409_kem_so_dem_va_dong(
    client, tk, hs, mau
):
    await _dat_trang_thai(hs, "loai_hinh_chinh_quy", "reviewing")
    truoc = await _dem()
    r = await client.post(
        P + "/sets", json=_than(hs, SACH), headers=(await tk("admin"))
    )
    assert r.status_code == 409, r.text
    p = r.json()["kiem_tra_dung_bo"]
    assert p["muc"] == "can_xac_nhan" and p["chan"] == []
    assert p["canh_bao"] == {
        "so_ho_so_theo_trang_thai": {"reviewing": 1},
        "dong_theo_trang_thai": {"reviewing": [3]},
    }
    assert p["can_admin_xac_nhan"] is True and p["nguoi_goi_duoc_xac_nhan"] is True
    assert not any(hs[n][0] in r.text for n in SACH)  # không mã hồ sơ trong phản hồi
    assert await _dem() == truoc


async def test_admin_xac_nhan_dung_thi_201_va_vet_doc_lai_duoc(client, tk, hs, mau):
    await _dat_trang_thai(hs, "loai_hinh_chinh_quy", "reviewing")
    h = await tk("admin")
    r = await client.post(
        P + "/sets",
        json=_than(hs, SACH, xac_nhan_trang_thai={"reviewing": 1}),
        headers=h,
    )
    assert r.status_code == 201, r.text
    ct = await client.get(P + "/sets/%d" % r.json()["id"], headers=h)
    tt = ct.json()["thong_tin_dung"]
    vet = tt["xac_nhan_canh_bao_trang_thai"]
    assert vet["so_ho_so_theo_trang_thai"] == {"reviewing": 1}
    assert vet["dong_theo_trang_thai"] == {"reviewing": [3]}
    assert vet["nguoi_xac_nhan_id"] == r.json()["nguoi_tao_id"] is not None
    assert vet["luc"] and tt["trang_thai_ho_so"] == {"approved": 2, "reviewing": 1}


async def test_admin_xac_nhan_lech_thi_409_khong_ghi(client, tk, hs, mau):
    await _dat_trang_thai(hs, "loai_hinh_chinh_quy", "reviewing")
    truoc = await _dem()
    r = await client.post(
        P + "/sets",
        json=_than(hs, SACH, xac_nhan_trang_thai={"submitted": 1}),
        headers=(await tk("admin")),
    )
    assert r.status_code == 409, r.text
    assert r.json()["kiem_tra_dung_bo"]["muc"] == "xac_nhan_lech"
    assert await _dem() == truoc


async def test_chan_thi_400_xac_nhan_khong_go_duoc(client, tk, hs, mau):
    await _dat_trang_thai(hs, "loai_hinh_chinh_quy", "reviewing")
    await _dat_trang_thai(hs, "dia_chi_rong", "withdrawn")
    truoc = await _dem()
    r = await client.post(
        P + "/sets",
        json=_than(hs, SACH, xac_nhan_trang_thai={"reviewing": 1}),
        headers=(await tk("admin")),
    )
    assert r.status_code == 400, r.text
    p = r.json()["kiem_tra_dung_bo"]
    assert p["muc"] == "chan"
    assert [(c["ma"], c["trang_thai"], c["dong"]) for c in p["chan"]] == [
        ("trang_thai_chan", "withdrawn", [1])
    ]
    assert p["canh_bao"]["dong_theo_trang_thai"] == {"reviewing": [3]}
    assert await _dem() == truoc


def _casbin_cho_quan_ly_tao_bo(monkeypatch):
    """Casbin GIẢ: cho ``role:manager`` ``POST /sets`` (cấu hình sai / mở quyền sau này) — đo
    lớp quyền XÁC NHẬN, không phải Casbin."""
    enf = fastapi_app.state.enforcer
    goc, da_cho = enf.enforce, []

    def enforce(sub, obj, act, *them):
        if sub == "role:manager" and obj == P + "/sets" and act == "POST":
            da_cho.append(obj)
            return True
        return goc(sub, obj, act, *them)

    monkeypatch.setattr(enf, "enforce", enforce)
    return da_cho


async def test_quan_ly_dung_bo_co_canh_bao_thi_409_kem_so_dem_can_admin(
    client, tk, hs, mau, monkeypatch
):
    await _dat_trang_thai(hs, "loai_hinh_chinh_quy", "reviewing")
    da_cho = _casbin_cho_quan_ly_tao_bo(monkeypatch)
    truoc = await _dem()
    r = await client.post(
        P + "/sets", json=_than(hs, SACH), headers=(await tk("ql_u1"))
    )
    assert da_cho, "Casbin giả không được hỏi — phép đo không hợp lệ"
    assert r.status_code == 409, r.text
    p = r.json()["kiem_tra_dung_bo"]
    assert p["canh_bao"]["so_ho_so_theo_trang_thai"] == {"reviewing": 1}
    assert p["canh_bao"]["dong_theo_trang_thai"] == {"reviewing": [3]}
    assert p["can_admin_xac_nhan"] is True and p["nguoi_goi_duoc_xac_nhan"] is False
    assert "cần admin xác nhận" in r.json()["detail"]
    assert await _dem() == truoc


async def test_quan_ly_gui_xac_nhan_thi_403_khong_ghi(client, tk, hs, mau, monkeypatch):
    await _dat_trang_thai(hs, "loai_hinh_chinh_quy", "reviewing")
    da_cho = _casbin_cho_quan_ly_tao_bo(monkeypatch)
    truoc = await _dem()
    r = await client.post(
        P + "/sets",
        json=_than(hs, SACH, xac_nhan_trang_thai={"reviewing": 1}),
        headers=(await tk("ql_u1")),
    )
    assert da_cho and r.status_code == 403, r.text
    assert "kiem_tra_dung_bo" not in r.json()
    assert await _dem() == truoc


async def test_quan_ly_khong_canh_bao_van_dung_duoc_khi_casbin_cho(
    client, tk, hs, mau, monkeypatch
):
    # Đối chứng: lớp quyền xác nhận KHÔNG chặn quản lý khi không có gì cần xác nhận.
    _casbin_cho_quan_ly_tao_bo(monkeypatch)
    r = await client.post(
        P + "/sets", json=_than(hs, SACH), headers=(await tk("ql_u1"))
    )
    assert r.status_code == 201, r.text
