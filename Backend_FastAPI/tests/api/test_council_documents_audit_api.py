# -*- coding: utf-8 -*-
"""Lượt E3 — ba yêu cầu owner 04-11 (``Y-TUONG-…`` J1 dòng 29–31) qua REQUEST THẬT (app thật +
lifespan + Casbin + middleware), CSDL test, DỮ LIỆU GIẢ:

* **Xoá bộ** (dòng 29) — ``DELETE /sets/{set_id}``: chỉ admin; lý do bắt buộc; VẾT XOÁ (id bộ,
  số hồ sơ, danh sách tệp + sha, người, lúc, lý do — không CCCD, không DTO) ghi CÙNG giao dịch
  với lệnh xoá: hỏng ở bất kỳ câu nào ⇒ không xoá gì, không vết.
* **Danh sách mã đầu vào** (dòng 30) — ``GET /sets/{set_id}/ma-ho-so``: chỉ admin, đúng thứ
  tự, ``no-store``; quản lý của ĐÚNG đơn vị ⇒ 403.
* **Nhật ký tải** (dòng 31) — mỗi lần CẤP một tệp ghi một dòng, COMMIT TRƯỚC khi gửi bytes
  (đo bằng một kết nối KHÁC ngay lúc gửi); ghi lỗi ⇒ không bytes; xoá bộ ⇒ nhật ký tải + vết
  xoá còn nguyên, vẫn truy được bộ / tệp / sha (Codex lần 5 câu 4). Xem nhật ký: chỉ admin.

Mỗi ca một bất biến (CLAUDE.md §3). Đóng băng của route xoá: ``test_council_documents_api.py``
(request THẬT ⇒ 503) + kiểm kê ``tests/middleware/test_admission_freeze.py``.
"""
import hashlib
import logging

import pytest
import pytest_asyncio
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.database as csdl
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.routers import council_documents as rt
from tests.api import test_council_documents_api as api
from tests.fixtures.hoi_dong_seed import ma_gia, seed_hoi_dong

pytestmark = pytest.mark.integration

P, _dem, _dem_vet = api.P, api._dem, api._dem_vet


# Ba fixture như ``test_council_documents_api.py`` (cùng dữ liệu giả, cùng vai) — khai lại ở đây
# thay vì import tên fixture (flake8 F811 ở mọi tham số test).
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


LY_DO = "GIA dựng nhầm danh sách, dựng lại bộ khác"
TIEU_DE_KHONG_LUU = {
    "cache-control": "no-store",
    "pragma": "no-cache",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
}


def _sha(b):
    return hashlib.sha256(b).hexdigest()


async def _xoa(client, sid, h, than=None):
    return await client.request(
        "DELETE",
        P + "/sets/%d" % sid,
        json={"ly_do": LY_DO} if than is None else than,
        headers=h,
    )


async def _id_nguoi(ten):
    async with csdl.engine.connect() as c:
        return (
            await c.execute(
                text('SELECT id FROM "user" WHERE username = :u'),
                {"u": "gia_e2_" + ten},
            )
        ).scalar_one()


def _loi_csdl_gia(*a, **k):
    raise DBAPIError("GIA", None, Exception("GIA loi csdl"))


async def _loi_csdl_gia_async(*a, **k):
    _loi_csdl_gia()


# ═══════════════════════════════ xoá bộ — chỉ admin, lý do, vết độc lập ════════════════════
async def test_admin_xoa_bo_ghi_vet_doc_lap_khong_cccd(client, tk, ba_bo):
    h = await tk("admin")
    sid, b = ba_bo["u1"]
    r = await _xoa(client, sid, h)
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["set_id"], v["so_ho_so"], v["so_tep"], v["ly_do"]) == (sid, 1, 1, LY_DO)
    assert v["nguoi_xoa_id"] == await _id_nguoi("admin")
    assert v["danh_sach_tep"] == [
        {
            "thu_tu": 1,
            "path": "HoiDong/u1.docx",
            "sha256": _sha(b),
            "kich_thuoc": len(b),
        }
    ]
    assert "GIA1" not in r.text  # mã hồ sơ đầu vào của bộ KHÔNG vào vết
    assert await _dem() == (0, 2, 2)  # bộ + tệp của nó đã xoá, hai bộ khác còn
    assert await _dem_vet() == (1, 0)  # vết xoá còn SAU khi bộ đã xoá (không cascade)
    assert (await client.get(P + "/sets/%d" % sid, headers=h)).status_code == 404


@pytest.mark.parametrize(
    "ly_do",
    ["", "   ", "GIA" + chr(0x202E) + "x", "x" * 1001],
    ids=["rong", "khoang_trang", "ky_tu_vo_hinh", "qua_tran_1001"],
)
async def test_xoa_bo_ly_do_khong_hop_le_thi_khong_xoa(client, tk, ba_bo, ly_do):
    r = await _xoa(client, ba_bo["u1"][0], await tk("admin"), {"ly_do": ly_do})
    assert r.status_code == 400, r.text
    assert await _dem() == (0, 3, 3) and await _dem_vet() == (0, 0)


@pytest.mark.parametrize(
    "than", [{}, {"ly_do": LY_DO, "x": 1}, {"ly_do": 5}], ids=["thieu", "thua", "so"]
)
async def test_xoa_bo_than_sai_dang_thi_422_khong_xoa(client, tk, ba_bo, than):
    r = await _xoa(client, ba_bo["u1"][0], await tk("admin"), than)
    assert r.status_code == 422, r.text
    assert await _dem() == (0, 3, 3) and await _dem_vet() == (0, 0)


async def test_xoa_bo_ly_do_dung_tran_ky_thuat_thi_nhan(client, tk, ba_bo):
    ly_do = "  " + "x" * 1000 + "  "  # 1.000 ký tự sau khi bỏ khoảng trắng hai đầu
    r = await _xoa(client, ba_bo["u1"][0], await tk("admin"), {"ly_do": ly_do})
    assert r.status_code == 200, r.text
    assert r.json()["ly_do"] == "x" * 1000


@pytest.mark.parametrize("vai", ["ql_u1", "can_bo", "ke_toan"])
async def test_xoa_bo_chi_admin(client, tk, ba_bo, vai):
    # ql_u1 là quản lý của ĐÚNG đơn vị bộ u1 — vẫn không xoá được.
    r = await _xoa(client, ba_bo["u1"][0], await tk(vai))
    assert r.status_code == 403, r.text
    assert await _dem() == (0, 3, 3) and await _dem_vet() == (0, 0)


async def test_xoa_bo_khong_co_thi_404(client, tk, ba_bo):
    khong_co = max(v[0] for v in ba_bo.values()) + 1000
    r = await _xoa(client, khong_co, await tk("admin"))
    assert r.status_code == 404, r.text
    assert await _dem_vet() == (0, 0)


async def test_xoa_bo_loi_o_cau_xoa_thi_khong_xoa_khong_vet(
    client, tk, ba_bo, monkeypatch
):
    # Vết đã flush, câu XOÁ hỏng ⇒ SAVEPOINT hoàn tác cả vết: không xoá gì, không vết mồ côi.
    h = await tk("admin")
    monkeypatch.setattr(CouncilDocumentRepository, "xoa_bo", _loi_csdl_gia_async)
    r = await _xoa(client, ba_bo["u1"][0], h)
    assert r.status_code == 500, r.text
    assert "GIA loi csdl" not in r.text
    assert await _dem() == (0, 3, 3) and await _dem_vet() == (0, 0)


async def test_xoa_bo_loi_ghi_vet_thi_khong_xoa(client, tk, ba_bo, monkeypatch):
    h = await tk("admin")
    monkeypatch.setattr(CouncilDocumentRepository, "them_vet_xoa", _loi_csdl_gia_async)
    r = await _xoa(client, ba_bo["u1"][0], h)
    assert r.status_code == 500, r.text
    assert await _dem() == (0, 3, 3) and await _dem_vet() == (0, 0)


# ═══════════════════════════════ danh sách mã đầu vào — chỉ admin ═════════════════════════
async def _chen_bo_nhieu_ma(unit_id, ma):
    b = b"GIA-TEP-ma"
    async with csdl.engine.begin() as c:
        sid = (
            await c.execute(
                text(
                    "INSERT INTO council_document_set (moc_chup, unit_id, trinh_do, so_ho_so, "
                    "so_tep, kich_thuoc_tong, ma_ho_so_dau_vao, snapshot_dto, "
                    "thong_tin_dung) VALUES (now(), :u, 'Cao đẳng', :n, 1, :k, "
                    "CAST(:m AS jsonb), CAST(:s AS jsonb), '{}') RETURNING id"
                ),
                {
                    "u": unit_id,
                    "n": len(ma),
                    "k": len(b),
                    "m": "[%s]" % ", ".join('"%s"' % x for x in ma),
                    "s": "[%s]" % ", ".join("{}" for _ in ma),
                },
            )
        ).scalar_one()
        await c.execute(
            text(
                "INSERT INTO council_document_set_file (set_id, thu_tu, path, sha256, "
                "kich_thuoc, noi_dung) VALUES (:s, 1, 'HoiDong/ma.docx', :h, :n, :b)"
            ),
            {"s": sid, "h": _sha(b), "n": len(b), "b": b},
        )
    return sid


# KHÔNG theo thứ tự tăng dần — trả đúng thứ tự đầu vào, không sắp xếp lại.
def _ma_dau_vao():
    return [ma_gia(30), ma_gia(10), ma_gia(20, 9)]


async def test_admin_xem_danh_sach_ma_dung_thu_tu_khong_luu_dem(client, tk, hs, caplog):
    sid = await _chen_bo_nhieu_ma(hs["_danh_muc"]["u1"], _ma_dau_vao())
    h = await tk("admin")
    caplog.set_level(logging.INFO)
    r = await client.get(P + "/sets/%d/ma-ho-so" % sid, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"set_id": sid, "so_ho_so": 3, "ma_ho_so": _ma_dau_vao()}
    for k, v in TIEU_DE_KHONG_LUU.items():
        assert r.headers[k] == v, k
    toan_bo = repr([x.__dict__ for x in caplog.records]) + caplog.text
    assert not any(m in toan_bo for m in _ma_dau_vao())  # không log mã


@pytest.mark.parametrize("vai", ["ql_u1", "can_bo", "ke_toan"])
async def test_ngoai_admin_khong_xem_duoc_danh_sach_ma(client, tk, hs, vai):
    # ql_u1 = quản lý của ĐÚNG đơn vị bộ (Casbin không có dòng cho route này) ⇒ 403.
    sid = await _chen_bo_nhieu_ma(hs["_danh_muc"]["u1"], _ma_dau_vao())
    h = await tk(vai)
    r = await client.get(P + "/sets/%d/ma-ho-so" % sid, headers=h)
    assert r.status_code == 403, r.text
    assert not any(m in r.text for m in _ma_dau_vao())
    if (
        vai == "ql_u1"
    ):  # chiều kia: chính quản lý ấy VẪN xem được thông tin chung của bộ
        assert (await client.get(P + "/sets/%d" % sid, headers=h)).status_code == 200


async def test_danh_sach_ma_bo_khong_co_thi_404(client, tk, ba_bo):
    khong_co = max(v[0] for v in ba_bo.values()) + 1000
    r = await client.get(P + "/sets/%d/ma-ho-so" % khong_co, headers=await tk("admin"))
    assert r.status_code == 404, r.text


# ═══════════════════════════════ nhật ký tải — ghi bền TRƯỚC khi gửi bytes ════════════════
_SQL_NHAT_KY = (
    "SELECT set_id, thu_tu, path, sha256, nguoi_tai_id FROM "
    "council_document_download_log ORDER BY id"
)


@pytest.fixture
def do_luc_gui(monkeypatch):
    """Thay ``Response`` của router bằng lớp con: NGAY TRƯỚC khi gửi phản hồi (lúc ASGI gọi
    ``__call__``), đọc nhật ký qua một kết nối KHÁC — chỉ thấy dòng ĐÃ COMMIT."""
    luc_gui = []

    class _DoTruocKhiGui(Response):
        async def __call__(self, scope, receive, send):
            async with csdl.engine.connect() as c:
                luc_gui.append(
                    [tuple(x) for x in (await c.execute(text(_SQL_NHAT_KY))).all()]
                )
            await super().__call__(scope, receive, send)

    monkeypatch.setattr(rt, "Response", _DoTruocKhiGui)
    return luc_gui


async def test_tai_tep_ghi_nhat_ky_ben_truoc_khi_gui_bytes(
    client, tk, ba_bo, do_luc_gui
):
    sid, b = ba_bo["u1"]
    h = await tk("admin")  # tạo + đăng nhập TRƯỚC khi đọc id người dùng
    dong = (sid, 1, "HoiDong/u1.docx", _sha(b), await _id_nguoi("admin"))
    r = await client.get(P + "/sets/%d/files/1" % sid, headers=h)
    assert r.status_code == 200 and r.content == b
    assert do_luc_gui == [[dong]]  # dòng đã COMMIT trước lúc gửi bytes


async def test_quan_ly_tai_tep_cung_ghi_nhat_ky_dung_nguoi(
    client, tk, ba_bo, do_luc_gui
):
    sid, b = ba_bo["u1"]
    r = await client.get(P + "/sets/%d/files/1" % sid, headers=await tk("ql_u1"))
    assert r.status_code == 200 and r.content == b
    assert do_luc_gui == [
        [(sid, 1, "HoiDong/u1.docx", _sha(b), await _id_nguoi("ql_u1"))]
    ]


async def test_ghi_nhat_ky_loi_thi_khong_tra_bytes(client, tk, ba_bo, monkeypatch):
    sid, b = ba_bo["u1"]
    h = await tk("admin")
    monkeypatch.setattr(
        CouncilDocumentRepository, "them_nhat_ky_tai", _loi_csdl_gia_async
    )
    r = await client.get(P + "/sets/%d/files/1" % sid, headers=h)
    assert r.status_code == 500, r.text
    assert b not in r.content
    assert await _dem_vet() == (0, 0)


async def test_tep_khong_co_thi_khong_ghi_nhat_ky(client, tk, ba_bo):
    r = await client.get(
        P + "/sets/%d/files/9" % ba_bo["u1"][0], headers=await tk("admin")
    )
    assert r.status_code == 404, r.text
    assert await _dem_vet() == (0, 0)  # máy chủ không cấp tệp nào ⇒ không có dòng


async def test_xoa_bo_nhat_ky_tai_va_vet_con_nguyen_van_truy_duoc(client, tk, ba_bo):
    # Codex lần 5 câu 4: sau khi xoá bộ, vẫn truy được bộ / tệp / sha — hai bảng vết không có
    # khoá ngoại tới bộ.
    h = await tk("admin")
    sid, b = ba_bo["u1"]
    assert (
        await client.get(P + "/sets/%d/files/1" % sid, headers=h)
    ).status_code == 200
    assert (
        await client.get(P + "/sets/%d/files/1" % sid, headers=await tk("ql_u1"))
    ).status_code == 200
    assert (await _xoa(client, sid, h)).status_code == 200
    assert (
        await client.get(P + "/sets/%d/files/1" % sid, headers=h)
    ).status_code == 404
    tai = (await client.get(P + "/nhat-ky-tai?set_id=%d" % sid, headers=h)).json()
    assert len(tai) == 2
    assert {(x["set_id"], x["thu_tu"], x["path"], x["sha256"]) for x in tai} == {
        (sid, 1, "HoiDong/u1.docx", _sha(b))
    }
    assert {x["nguoi_tai_id"] for x in tai} == {
        await _id_nguoi("admin"),
        await _id_nguoi("ql_u1"),
    }
    (vet,) = (await client.get(P + "/nhat-ky-xoa", headers=h)).json()
    assert vet["set_id"] == sid
    assert [(t["path"], t["sha256"]) for t in vet["danh_sach_tep"]] == [
        (x["path"], x["sha256"]) for x in tai[:1]
    ]
    # Lọc theo bộ KHÁC ⇒ không lẫn dòng của bộ đã xoá.
    khac = (
        await client.get(P + "/nhat-ky-tai?set_id=%d" % ba_bo["u2"][0], headers=h)
    ).json()
    assert khac == []


@pytest.mark.parametrize("duong", ["/nhat-ky-tai", "/nhat-ky-xoa"])
@pytest.mark.parametrize("vai", ["ql_u1", "can_bo", "ke_toan"])
async def test_xem_nhat_ky_chi_admin(client, tk, vai, duong):
    r = await client.get(P + duong, headers=await tk(vai))
    assert r.status_code == 403, r.text
