# -*- coding: utf-8 -*-
"""Vòng giao diện — đợt 2 phần máy chủ (đặc tả 3.4–3.6, 3.8, 3.9, 5.1, 5.7) qua REQUEST THẬT, CSDL test, DỮ LIỆU GIẢ.

* ``GET /sets`` / ``GET /sets/{id}``: tình trạng (bốn luật đặc tả 3.4, MỘT câu SQL cho cả hai), Quyết định {id, goc,
  khoá cũ}, lượt gửi chờ CHỈ admin thấy, bộ lọc, KHÔNG N+1 (đếm câu SQL);
* ``GET /nguoi-tao-bo``: người tạo phân biệt trong phạm vi;
* ``GET /sets/{id}/tai-ca-bo``: zip = đúng bytes đã lưu + tên = path; MỘT dòng nhật ký mỗi tệp ghi bền; tệp hỏng ⇒ 500,
  0 dòng nhật ký; Quản lý: bộ đơn vị mình 200, đơn vị khác 404 (y hệt tải lẻ);
* tên người trong nhật ký tải / vết xoá; ``GET /decisions`` lọc ``loai`` / ``trang_thai``;
* chi tiết hồ sơ: ô ``quyet_dinh_trung_tuyen`` (lý do huỷ ghi nhận CHỈ admin; dấu AppSheet tách riêng);
* dòng danh sách hồ sơ có ``academic_year``.

Mỗi ca một bất biến (CLAUDE.md §3); trạng thái CSDL đo bằng SQL từ kết nối khác (CLAUDE.md §10).
"""
import io
import zipfile

import pytest
import pytest_asyncio
from sqlalchemy import event, text

import app.database as csdl
from app.models.council_document import DAU_APPSHEET_TIEN_TO
from tests.api import test_council_decisions_api as qd
from tests.api import test_council_documents_api as api
from tests.fixtures.hoi_dong_seed import seed_hoi_dong

pytestmark = pytest.mark.integration

P = api.P
SACH = qd.SACH


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await seed_hoi_dong(conn)


@pytest_asyncio.fixture
async def tk(client, hs):
    return api._TaiKhoan(client, hs)


@pytest_asyncio.fixture
async def ad(client, tk):
    h = await tk("admin")
    await api._tai_ba_mau_api(client, h)
    return h


async def _ten(vai):
    return await qd._q1(
        'SELECT COALESCE(NULLIF(btrim(full_name), \'\'), username) FROM "user" WHERE username = :u',
        u="gia_e2_" + vai,
    )


async def _id(vai):
    return await qd._q1('SELECT id FROM "user" WHERE username = :u', u="gia_e2_" + vai)


async def _ds(client, h, **loc):
    r = await client.get(P + "/sets", params=loc, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _mot(ds, sid):
    (x,) = [b for b in ds if b["id"] == sid]
    return x


# ═══════════════════════════════ GET /sets — tình trạng + Quyết định ═════════════════════════
async def test_bo_moi_chua_ghi_nhan_roi_con_hieu_luc(client, hs, ad):
    bo = await qd._bo_ok(client, ad, hs, SACH)
    x = _mot(await _ds(client, ad), bo["id"])
    assert (x["tinh_trang"], x["quyet_dinh"], x["luot_gui_cho"]) == ("chua_ghi_nhan", None, None)
    assert x["nguoi_tao_ten"] == await _ten("admin")
    van_ban = await qd._ghi_ok(client, ad, bo["id"], so="501", so_hs=3)
    x = _mot(await _ds(client, ad), bo["id"])
    assert x["tinh_trang"] == "con_hieu_luc"
    assert x["quyet_dinh"] == {
        "id": van_ban["id"],
        "loai": "trung_tuyen",
        "trang_thai": "hieu_luc",
        "so_quyet_dinh": "501",
        "ngay_ky": qd._ngay().isoformat(),
        "so_ho_so": 3,
        "goc": None,
    }


async def test_luot_cho_lam_chua_xac_dinh_va_chi_admin_thay_ma(client, hs, ad, tk):
    bo = await qd._bo_ok(client, ad, hs, SACH)
    ma = await qd._mo_luot(client, ad, bo["id"])
    assert ma
    x = _mot(await _ds(client, ad), bo["id"])
    assert x["tinh_trang"] == "chua_xac_dinh" and x["luot_gui_cho"]["ma"] == ma
    # Quản lý cùng đơn vị: thấy "Chưa xác định" nhưng KHÔNG thấy mã lượt (chỉ người có quyền ghi nhận).
    y = _mot(await _ds(client, await tk("ql_u1")), bo["id"])
    assert y["tinh_trang"] == "chua_xac_dinh" and y["luot_gui_cho"] is None
    r = await client.get(P + "/sets/%d" % bo["id"], headers=await tk("ql_u1"))
    assert r.status_code == 200 and r.json()["luot_gui_cho"] is None
    r = await client.get(P + "/sets/%d" % bo["id"], headers=ad)
    assert r.json()["luot_gui_cho"]["ma"] == ma and r.json()["tinh_trang"] == "chua_xac_dinh"


async def test_huy_ghi_nhan_thi_da_huy_va_khong_con_quyet_dinh(client, hs, ad):
    bo, van_ban = await qd._qd_cua_bo(client, ad, hs, SACH, "501")
    r = await qd._huy_ghi_nhan(client, ad, van_ban["id"], "501")
    assert r.status_code == 200, r.text
    x = _mot(await _ds(client, ad), bo["id"])
    assert (x["tinh_trang"], x["quyet_dinh"]) == ("da_huy_ghi_nhan", None)


async def test_huy_hieu_luc_thi_het_hieu_luc(client, hs, ad):
    bo, van_ban = await qd._qd_cua_bo(client, ad, hs, SACH, "501")
    r = await qd._huy_hieu_luc(client, ad, van_ban["id"], "502")
    assert r.status_code in (200, 201), r.text
    x = _mot(await _ds(client, ad), bo["id"])
    assert x["tinh_trang"] == "het_hieu_luc" and x["quyet_dinh"]["trang_thai"] == "het_hieu_luc"


async def test_loc_so_quyet_dinh_nam_tinh_trang_nguoi_tao(client, hs, ad, tk):
    await tk("ql_u1")  # tạo tài khoản quản lý (người dùng KHÔNG tạo bộ nào) trước khi hỏi id
    bo1, _ = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
    bo2 = await qd._bo_ok(client, ad, hs, SACH[1:2])
    assert [b["id"] for b in await _ds(client, ad, so_quyet_dinh="501")] == [bo1["id"]]
    assert [b["id"] for b in await _ds(client, ad, tinh_trang="chua_ghi_nhan")] == [bo2["id"]]
    assert await _ds(client, ad, nam_hoc=2027) == []
    assert {b["id"] for b in await _ds(client, ad, nam_hoc=2026)} == {bo1["id"], bo2["id"]}
    assert {b["id"] for b in await _ds(client, ad, nguoi_tao_id=await _id("admin"))} == {bo1["id"], bo2["id"]}
    assert await _ds(client, ad, nguoi_tao_id=await _id("ql_u1")) == []
    r = await client.get(P + "/sets", params={"so_quyet_dinh": "50a"}, headers=ad)
    assert r.status_code == 422


async def test_danh_sach_mot_so_cau_sql_khong_doi_theo_so_bo(client, hs, ad):
    # Đặc tả 3.4 — KHÔNG N+1: số câu SQL của GET /sets không phụ thuộc số bộ (đếm ở engine thật).
    dem = []

    def nghe(*_a, **_k):
        dem.append(1)

    async def so_cau():
        dem.clear()
        event.listen(csdl.engine.sync_engine, "before_cursor_execute", nghe)
        try:
            await _ds(client, ad)
        finally:
            event.remove(csdl.engine.sync_engine, "before_cursor_execute", nghe)
        return len(dem)

    await qd._bo_ok(client, ad, hs, SACH[:1])
    mot = await so_cau()
    await qd._bo_ok(client, ad, hs, SACH[1:2])
    await qd._bo_ok(client, ad, hs, SACH[2:3])
    assert len(await _ds(client, ad)) == 3
    assert await so_cau() == mot


# ═══════════════════════════════ người tạo bộ ══════════════════════════════════════════════════
async def test_nguoi_tao_bo_phan_biet_trong_pham_vi(client, hs, ad, tk):
    await qd._bo_ok(client, ad, hs, SACH[:1])
    await qd._bo_ok(client, ad, hs, SACH[1:2])
    r = await client.get(P + "/nguoi-tao-bo", headers=ad)
    assert r.status_code == 200 and r.json() == [{"id": await _id("admin"), "ten": await _ten("admin")}]
    # Quản lý đơn vị 2: không bộ nào của đơn vị mình ⇒ rỗng.
    r = await client.get(P + "/nguoi-tao-bo", headers=await tk("ql_u2"))
    assert r.status_code == 200 and r.json() == []


# ═══════════════════════════════ tải cả bộ ═════════════════════════════════════════════════════
async def test_tai_ca_bo_dung_byte_da_luu_va_mot_dong_nhat_ky_moi_tep(client, hs, ad):
    bo = await qd._bo_ok(client, ad, hs, SACH)
    r = await client.get(P + "/sets/%d/tai-ca-bo" % bo["id"], headers=ad)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="bo-%d.zip"' % bo["id"]
    assert r.headers["cache-control"] == "no-store"
    luu = await qd._q(
        "SELECT thu_tu, path, noi_dung FROM council_document_set_file WHERE set_id = :s ORDER BY thu_tu", s=bo["id"]
    )
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert z.namelist() == [p for _, p, _ in luu]
        assert all(z.read(p) == bytes(b) for _, p, b in luu)
    nk = await qd._q(
        "SELECT thu_tu, nguoi_tai_id FROM council_document_download_log WHERE set_id = :s ORDER BY thu_tu",
        s=bo["id"],
    )
    assert nk == [(t, await _id("admin")) for t, _, _ in luu]


async def test_tai_ca_bo_tep_hong_thi_500_khong_nhat_ky(client, hs, ad, monkeypatch):
    # Tầng chủ sở hữu tính toàn vẹn tệp là CSDL (CHECK ``ck_council_document_set_file_sha256_noi_dung`` — sửa bytes bằng SQL
    # bị chặn ngay). Lớp PHỤ của route (so sha từng tệp trước khi trả) đo bằng cách GIẢ bản ĐỌC RA hỏng một byte (hỏng
    # trên đường đọc): trả bản sao thường, KHÔNG sửa đối tượng ORM (phiên sẽ tự ghi ngược ⇒ đỏ vì CHECK, sai lý do).
    from types import SimpleNamespace

    from app.repositories.council_document_repository import CouncilDocumentRepository as Kho

    bo = await qd._bo_ok(client, ad, hs, SACH)
    goc = Kho.tep_cua_bo_kem_noi_dung

    async def doc_hong(self, set_id):
        ds = await goc(self, set_id)
        out = []
        for x in ds:
            b = bytearray(bytes(x.noi_dung))
            if x.thu_tu == 2:
                b[100] ^= 1
            out.append(SimpleNamespace(thu_tu=x.thu_tu, path=x.path, sha256=x.sha256, noi_dung=bytes(b)))
        return out

    monkeypatch.setattr(Kho, "tep_cua_bo_kem_noi_dung", doc_hong)
    r = await client.get(P + "/sets/%d/tai-ca-bo" % bo["id"], headers=ad)
    assert r.status_code == 500 and r.headers.get("content-type") != "application/zip", r.text
    assert await qd._q1(
        "SELECT count(*) FROM council_document_download_log WHERE set_id = :s", s=bo["id"]
    ) == 0


async def test_tai_ca_bo_quan_ly_nhu_tai_le(client, hs, ad, tk):
    bo = await qd._bo_ok(client, ad, hs, SACH)  # hồ sơ đơn vị 1 ⇒ bộ đơn vị 1
    r = await client.get(P + "/sets/%d/tai-ca-bo" % bo["id"], headers=await tk("ql_u1"))
    assert r.status_code == 200, r.text
    r = await client.get(P + "/sets/%d/tai-ca-bo" % bo["id"], headers=await tk("ql_u2"))
    assert r.status_code == 404, r.text


# ═══════════════════════════════ tên người trong nhật ký ═══════════════════════════════════════
async def test_nhat_ky_tai_va_vet_xoa_co_ten_nguoi(client, hs, ad):
    bo = await qd._bo_ok(client, ad, hs, SACH)
    assert (await client.get(P + "/sets/%d/files/1" % bo["id"], headers=ad)).status_code == 200
    r = await client.get(P + "/nhat-ky-tai", params={"set_id": bo["id"]}, headers=ad)
    assert r.status_code == 200 and r.json()[0]["nguoi_tai_ten"] == await _ten("admin")
    r = await client.request("DELETE", P + "/sets/%d" % bo["id"], json={"ly_do": "GIA xoa thu"}, headers=ad)
    assert r.status_code in (200, 204), r.text
    r = await client.get(P + "/nhat-ky-xoa", headers=ad)
    assert r.status_code == 200 and r.json()[0]["nguoi_xoa_ten"] == await _ten("admin")


# ═══════════════════════════════ GET /decisions lọc ════════════════════════════════════════════
async def test_danh_sach_van_ban_loc_loai_trang_thai(client, hs, ad):
    _, a = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
    _, b = await qd._qd_cua_bo(client, ad, hs, SACH[1:2], "502")
    assert (await qd._huy_ghi_nhan(client, ad, b["id"], "502")).status_code == 200

    async def ids(**loc):
        r = await client.get(P + "/decisions", params=loc, headers=ad)
        assert r.status_code == 200, r.text
        return {x["id"] for x in r.json()}

    assert await ids(trang_thai="hieu_luc") == {a["id"]}
    assert await ids(trang_thai="huy_ghi_nhan") == {b["id"]}
    assert await ids(loai="trung_tuyen") == {a["id"], b["id"]}
    assert await ids(loai="dieu_chinh") == set()
    r = await client.get(P + "/decisions", params={"trang_thai": "khong_co"}, headers=ad)
    assert r.status_code == 422


# ═══════════════════════════════ ô Quyết định trên trang hồ sơ ═════════════════════════════════
async def _o(client, h, pid):
    r = await client.get("/api/admissions/%d" % pid, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["quyet_dinh_trung_tuyen"]


async def test_o_quyet_dinh_chua_co_roi_hieu_luc(client, hs, ad):
    pid = hs[SACH[0]][1]
    assert await _o(client, ad, pid) == {
        "tinh_trang": "chua_co_qd",
        "van_ban": None,
        "ly_do_huy_ghi_nhan": None,
        "dau_appsheet": False,
        "dau_appsheet_so_qd": None,
    }
    bo, van_ban = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
    o = await _o(client, ad, pid)
    assert o["tinh_trang"] == "co_qd_hieu_luc"
    assert o["van_ban"] == {
        "id": van_ban["id"],
        "loai": "trung_tuyen",
        "so_quyet_dinh": "501",
        "ngay_ky": qd._ngay().isoformat(),
        "trang_thai": "hieu_luc",
        "set_id": bo["id"],
    }


async def test_o_quyet_dinh_ly_do_huy_chi_admin(client, hs, ad, tk):
    pid = hs[SACH[0]][1]
    _, van_ban = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
    assert (await qd._huy_ghi_nhan(client, ad, van_ban["id"], "501")).status_code == 200
    assert (await _o(client, ad, pid))["ly_do_huy_ghi_nhan"] == "GIA nhap nham"
    o = await _o(client, await tk("ql_u1"), pid)
    assert o["van_ban"]["trang_thai"] == "huy_ghi_nhan" and o["ly_do_huy_ghi_nhan"] is None


async def test_o_quyet_dinh_dau_appsheet_tach_rieng(client, hs, ad):
    pid = hs[SACH[0]][1]
    await qd._sql(
        "UPDATE admission_profile SET revision_reason = :r WHERE id = :p",
        r=DAU_APPSHEET_TIEN_TO + "1234 ngày 01/03/2026",
        p=pid,
    )
    o = await _o(client, ad, pid)
    assert (o["dau_appsheet"], o["dau_appsheet_so_qd"], o["van_ban"]) == (True, "1234", None)


# ═══════════════════════════════ dòng danh sách hồ sơ ══════════════════════════════════════════
async def test_dong_danh_sach_ho_so_co_nam_hoc(client, hs, ad):
    r = await client.get("/api/admissions", params={"academic_year": 2026, "page_size": 5}, headers=ad)
    assert r.status_code == 200, r.text
    ds = r.json()["profiles"]
    assert ds and all(x["academic_year"] == 2026 for x in ds)
