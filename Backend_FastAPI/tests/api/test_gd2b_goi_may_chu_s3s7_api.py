# tests/api/test_gd2b_goi_may_chu_s3s7_api.py
"""Gói máy chủ nhỏ sau giao diện GĐ2-B (24-11) qua REQUEST THẬT (router → deps → dịch vụ → CSDL thật):

* **S3** — họ tên người thao tác (``created_by_full_name``, ``cancelled_by_full_name``, ``updated_by_full_name``,
  ``requested_by_full_name``) ở E1–E8, thay cho chỉ số id (thiết kế giao diện §4.3, KT-2);
* **S7** — ``RowOut.unit_name`` ở E9 (thiết kế §4.4 S7; đính chính 1 §5 "E9: cột Đơn vị cần nguồn tên đơn vị").

Nguồn hợp đồng: phụ lục ``gd2\\gd2b\\may-chu-s3s7\\PHU-LUC-HOP-DONG-S3-S7-2026-11-24.md`` (thêm trường phản hồi — loại "không phá"
HĐ4 §1.8). Hai Admin GIẢ có họ tên KHÁC nhau (A = Admin của conftest, B = Admin thứ hai) để phân biệt "tên của người ĐÃ thao tác" với
"tên của người ĐANG xem": trong mọi ca kiểm tên, người xem KHÁC người thao tác. Tên mong đợi gõ TAY. Mỗi ca MỘT bất biến (luật chung
§3). Dữ liệu GIẢ.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import AsyncClient

import app.database as csdl
from tests.api.gd2b_lan_xet_tro_giup import NAM, P, ho_so_xet, nen_lan_xet, sql

pytestmark = pytest.mark.integration

TEN_A = "Quản Trị Giả Một"
TEN_B = "Quản Trị Giả Hai"
#: Tên đơn vị của ``tests.fixtures.hoi_dong_seed.danh_muc`` (``d["u1"]``, ``d["u2"]``) — gõ TAY.
DON_VI_1 = "Đơn vị giả 1"
DON_VI_2 = "Đơn vị giả 2"


@pytest_asyncio.fixture
async def nen(setup_test_database):
    """Cấu hình lần xét năm 2026 + MỘT hồ sơ (đơn vị ``u1``) để lượt kiểm có dòng."""
    async with csdl.engine.begin() as conn:
        d = await nen_lan_xet(conn)
        d["hs"] = await ho_so_xet(conn, d, 41_001)
    return d


@pytest_asyncio.fixture
async def hai_admin(client: AsyncClient, admin_user_in_db, admin_token_headers):
    """A = Admin của conftest (họ tên ``TEN_A``), B = Admin thứ hai (họ tên ``TEN_B``), kèm token của cả hai."""
    from tests.conftest import _create_user_and_role, _get_token_headers

    b = await _create_user_and_role(
        {"username": "gd2b_s3_admin_hai", "email": "gd2b_s3_admin_hai@example.com", "password": "QuanTriHai!2468",
         "role": "admin", "status": "active"},
        "role:admin",
    )
    await sql('UPDATE "user" SET full_name = :t WHERE id = :u', t=TEN_A, u=admin_user_in_db["id"])
    await sql('UPDATE "user" SET full_name = :t WHERE id = :u', t=TEN_B, u=b["id"])
    hb = await _get_token_headers(client, b)
    # Đăng nhập đặt cookie ``access_token`` vào ``client`` DÙNG CHUNG, và cookie THẮNG header (``deps._pick_access_token``) ⇒ không
    # xoá thì mọi request — kể cả request mang token của A — chạy dưới tên B (lượt đầu 24-11: 3 ca đỏ vì thế). Xoá để mỗi request
    # chạy đúng người của header nó mang (khuôn ``gd1b_lo_tro_giup.py``).
    client.cookies.clear()
    return SimpleNamespace(a=admin_user_in_db, ha=admin_token_headers, b=b, hb=hb)


async def _tao_va_luu_san(client: AsyncClient, h, d) -> int:
    """E1 + E4 (version 1 → 2) bởi người của ``h``."""
    r = await client.post(P, headers=h, json={"academic_year": NAM, "admission_round_id": d["vong"]})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = await client.put(f"{P}/{sid}/floors", headers=h, json={"version": 1, "floors": [
        {"offering_academic_info_id": d["ai"]["oto_cd"], "floor_score": "12.50"},
    ]})
    assert r.status_code == 200, r.text
    return sid


async def _chay(client: AsyncClient, h, sid: int, phien_ban: int = 2) -> dict:
    r = await client.post(f"{P}/{sid}/runs", headers=h, json={"kind": "evaluate", "session_version": phien_ban})
    assert r.status_code == 202, r.text
    return r.json()


async def _dong(client: AsyncClient, h, sid: int, rid: int) -> list:
    r = await client.get(f"{P}/{sid}/runs/{rid}/rows", headers=h, params={"page_size": 200})
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ══════════════════════════════════════════ S3 — họ tên người thao tác ══════════════════════════════════════════
async def test_s3_e3_nguoi_tao_va_nguoi_luu_san_la_ten_nguoi_thao_tac_khong_phai_nguoi_xem(
    client: AsyncClient, hai_admin, nen
):
    """A tạo + lưu sàn; B xem E3 ⇒ tên người tạo và người lưu sàn là A (không phải B — người đang xem); chưa huỷ ⇒ tên người huỷ
    ``null``."""
    x = hai_admin
    sid = await _tao_va_luu_san(client, x.ha, nen)
    e3 = (await client.get(f"{P}/{sid}", headers=x.hb)).json()
    assert (e3["created_by_user_id"], e3["created_by_full_name"]) == (x.a["id"], TEN_A)
    assert [(f["updated_by_user_id"], f["updated_by_full_name"]) for f in e3["floors"]] == [(x.a["id"], TEN_A)]
    assert (e3["cancelled_by_user_id"], e3["cancelled_by_full_name"]) == (None, None)


async def test_s3_e5_ten_nguoi_huy_la_nguoi_huy_khac_nguoi_tao(client: AsyncClient, hai_admin, nen):
    """A tạo; B huỷ ⇒ phản hồi E5 (B xem) và E3 (A xem) cùng trả: người tạo = A, người huỷ = B (hai cột không lẫn nhau)."""
    x = hai_admin
    sid = await _tao_va_luu_san(client, x.ha, nen)
    r = await client.post(f"{P}/{sid}/cancel", headers=x.hb, json={"version": 2, "reason": "Lý do giả huỷ"})
    assert r.status_code == 200, r.text
    e3 = (await client.get(f"{P}/{sid}", headers=x.ha)).json()
    for than in (r.json(), e3):
        assert (than["created_by_full_name"], than["cancelled_by_user_id"], than["cancelled_by_full_name"]) == (
            TEN_A, x.b["id"], TEN_B
        )


async def test_s3_e2_ten_nguoi_tao_va_nguoi_chay_luot_moi_nhat(client: AsyncClient, hai_admin, nen):
    """A tạo; B chạy kiểm; A xem E2 ⇒ dòng lần xét: người tạo = A, ``latest_run`` người chạy = B."""
    x = hai_admin
    sid = await _tao_va_luu_san(client, x.ha, nen)
    await _chay(client, x.hb, sid)
    r = await client.get(P, headers=x.ha)
    assert r.status_code == 200, r.text
    (muc,) = r.json()["items"]
    assert (muc["id"], muc["created_by_full_name"]) == (sid, TEN_A)
    assert (muc["latest_run"]["requested_by_user_id"], muc["latest_run"]["requested_by_full_name"]) == (x.b["id"], TEN_B)


async def test_s3_e6_e7_e8_e3_ten_nguoi_chay(client: AsyncClient, hai_admin, nen):
    """B chạy kiểm (E6); A xem E7, E8, E3 ⇒ người chạy = B ở cả ba (và ở chính phản hồi 202 của E6)."""
    x = hai_admin
    sid = await _tao_va_luu_san(client, x.ha, nen)
    run = await _chay(client, x.hb, sid)
    e7 = (await client.get(f"{P}/{sid}/runs", headers=x.ha)).json()["items"]
    e8 = (await client.get(f"{P}/{sid}/runs/{run['id']}", headers=x.ha)).json()
    e3 = (await client.get(f"{P}/{sid}", headers=x.ha)).json()["latest_run"]
    assert [(t["id"], t["requested_by_full_name"]) for t in (run, e7[0], e8, e3)] == [(run["id"], TEN_B)] * 4


async def test_s3_nguoi_chua_khai_ho_ten_tra_null_khong_thay_bang_ten_dang_nhap(client: AsyncClient, hai_admin, nen):
    """B chưa khai họ tên (``user.full_name`` NULL); B tạo; A xem E3 ⇒ ``created_by_full_name`` = ``null`` (không thay bằng tên đăng
    nhập hay chuỗi rỗng), id vẫn là B."""
    x = hai_admin
    await sql('UPDATE "user" SET full_name = NULL WHERE id = :u', u=x.b["id"])
    r = await client.post(P, headers=x.hb, json={"academic_year": NAM, "admission_round_id": nen["vong"]})
    assert r.status_code == 201, r.text
    e3 = (await client.get(f"{P}/{r.json()['id']}", headers=x.ha)).json()
    assert (e3["created_by_user_id"], e3["created_by_full_name"]) == (x.b["id"], None)


async def test_s3_ho_ten_doc_luc_get_doi_ten_thi_e8_tra_ten_moi_con_lai_giu_nguyen(client: AsyncClient, hai_admin, nen):
    """Họ tên người chạy đọc LÚC GET (phụ lục: không bất biến, như ``RowOut.full_name``): B đổi họ tên sau khi chạy ⇒ E8 trả tên MỚI;
    mọi trường khác của E8 giữ nguyên."""
    x = hai_admin
    sid = await _tao_va_luu_san(client, x.ha, nen)
    run = await _chay(client, x.hb, sid)
    truoc = (await client.get(f"{P}/{sid}/runs/{run['id']}", headers=x.ha)).json()
    await sql('UPDATE "user" SET full_name = :t WHERE id = :u', t="Quản Trị Giả Hai Đã Đổi", u=x.b["id"])
    sau = (await client.get(f"{P}/{sid}/runs/{run['id']}", headers=x.ha)).json()
    assert (truoc["requested_by_full_name"], sau["requested_by_full_name"]) == (TEN_B, "Quản Trị Giả Hai Đã Đổi")
    bo = "requested_by_full_name"
    assert {k: v for k, v in sau.items() if k != bo} == {k: v for k, v in truoc.items() if k != bo}


# ══════════════════════════════════════════ S7 — tên đơn vị của dòng kết quả ══════════════════════════════════════════
async def test_s7_e9_unit_name_la_ten_cua_chinh_don_vi_unit_id(client: AsyncClient, admin_token_headers, nen):
    h, d = admin_token_headers, nen
    sid = await _tao_va_luu_san(client, h, d)
    (dong,) = await _dong(client, h, sid, (await _chay(client, h, sid))["id"])
    assert (dong["profile_id"], dong["unit_id"], dong["unit_name"]) == (d["hs"], d["u1"], DON_VI_1)


async def test_s7_doi_don_vi_sau_khi_chay_unit_id_va_unit_name_cung_doi(client: AsyncClient, admin_token_headers, nen):
    """Đơn vị đọc LÚC GET: chuyển lead của hồ sơ sang ``u2`` SAU khi chạy ⇒ E9 trả ``unit_id`` = u2 và ``unit_name`` = tên u2 — tên
    luôn của CHÍNH đơn vị đang trả, không lệch id."""
    h, d = admin_token_headers, nen
    sid = await _tao_va_luu_san(client, h, d)
    rid = (await _chay(client, h, sid))["id"]
    await sql(
        "UPDATE lead SET unit_id = :u WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)", u=d["u2"], p=d["hs"]
    )
    (dong,) = await _dong(client, h, sid, rid)
    assert (dong["unit_id"], dong["unit_name"]) == (d["u2"], DON_VI_2)


async def test_s7_don_vi_ngung_hoat_dong_van_tra_ten(client: AsyncClient, admin_token_headers, nen):
    """Đơn vị đã ngừng (``organization_unit.is_active`` = false — xoá mềm) vẫn trả tên, như ``unit_id`` vẫn trả id [ĐX phụ lục]."""
    h, d = admin_token_headers, nen
    sid = await _tao_va_luu_san(client, h, d)
    rid = (await _chay(client, h, sid))["id"]
    await sql("UPDATE organization_unit SET is_active = false WHERE id = :u", u=d["u1"])
    (dong,) = await _dong(client, h, sid, rid)
    assert (dong["unit_id"], dong["unit_name"]) == (d["u1"], DON_VI_1)
