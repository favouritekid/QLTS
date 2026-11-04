# -*- coding: utf-8 -*-
"""API văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1, lượt E2) — REQUEST THẬT qua app thật
(``fastapi_app`` + lifespan + Casbin + middleware), CSDL test, DỮ LIỆU GIẢ, MẪU GIẢ.

Khoá (mỗi ca một bất biến — CLAUDE.md §3):

* Quyền theo VAI qua Casbin (subject ``role:<user.role>``; người dùng test KHÔNG có dòng gán
  vai theo người — M26): admin mọi route; manager chỉ ba route ĐỌC bộ văn bản; officer /
  accountant bị chặn ở mọi route (403) và route ghi không ghi gì.
* IDOR (``deps.get_council_document_set_for_user``) cả HAI chiều đơn vị: manager chỉ bộ của
  đơn vị mình; bộ ``unit_id`` NULL chỉ admin; ngoài phạm vi ⇒ 404 (cả metadata lẫn tải tệp).
* Tạo bộ qua API ⇒ tải từng tệp = bytes ĐÃ LƯU (không dựng lại), ``Content-Disposition`` an
  toàn với tên có dấu, ``Cache-Control: no-store``.
* Đóng băng: request THẬT tới mọi route GHI của module (lấy từ bảng route thật) ⇒ 503; route
  đọc vẫn 200 như mọi route đọc khác của tiền tố.
* Lỗi 422: log THẬT (``caplog``) không chứa CCCD gửi lên; mọi route của module khớp vị từ;
  log chỉ nhận bản ĐÃ CHUẨN HOÁ (``type`` + ``loc`` an toàn) — khoá thừa cấp đầu / lồng, lỗi
  có ``ctx``, route SMS (F217, lượt E3).
* Bất biến giao dịch đo QUA ĐƯỜNG API (F218); lớp chặn phụ của phạm vi gọi thẳng
  dependency (F219).
* Một lần dựng cùng lúc: hai phiên CSDL thật — lần thứ hai ⇒ 409, không đọc / dựng / ghi.
* Không URL tĩnh / mount nào trả được bytes mẫu hay tệp sinh.
"""
import ast
import asyncio
import hashlib
import io
import logging
import os
import re
import threading
import types
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import docx
import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from sqlalchemy import text
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

import app.database as csdl
from app import models
from app.config import settings
from app.core import deps
from app.database import AsyncSessionLocal
from app.main import fastapi_app
from app.middleware import exception_handlers as eh
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.routers import council_documents as rt
from app.services import council_document_render_service as bo_dung
from app.services import council_document_set_service as bo_vb
from app.services import council_document_template_service as kho_mau
from app.utils.exceptions import ConflictError, PermissionDeniedError
from tests.fixtures.constants import AuthURLs, TestUsers
from tests.fixtures.hoi_dong_seed import ma_gia, seed_hoi_dong
from tests.fixtures.users import create_user_with_role, get_auth_headers
from tests.unit.test_council_document_render_service import (
    _mau_bien_ban,
    _mau_danh_sach,
    _mau_quyet_dinh,
)

pytestmark = pytest.mark.integration

P = "/api/admission-config/council-documents"
MAU_GIA = {
    "bien_ban": _mau_bien_ban(),
    "quyet_dinh": _mau_quyet_dinh(),
    "danh_sach": _mau_danh_sach(),
}
KIEU_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Hồ sơ giả dựng được, CÙNG đơn vị u1 ⇒ bộ thuộc u1.
HO_SO_U1 = ["dia_chi_rong", "nhieu_nv_khoang_trang", "loai_hinh_chinh_quy"]
TS = {
    "so_quyet_dinh": "99",
    "ngay_quyet_dinh": "2026-09-08",
    "dot_so": "1",
    "dot_thang": 9,
}


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await seed_hoi_dong(conn)


# Mật khẩu + hash bcrypt TÍNH SẴN của bộ test (``TestUsers.DEFAULT``): bcrypt của app 15 vòng
# ⇒ băm lại cho mỗi người dùng mỗi ca tốn vài giây.
MAT_KHAU = TestUsers.DEFAULT["password"]
_HASH_SAN = TestUsers.DEFAULT["real_hash"]
VAI = {
    "admin": ("admin", None),
    "ql_u1": ("manager", "u1"),
    "ql_u2": ("manager", "u2"),
    "ql_khong_dv": ("manager", None),
    "can_bo": ("officer", "u1"),
    "ke_toan": ("accountant", "u1"),
}


async def _nguoi(ten, vai, unit_id):
    # KHÔNG chèn dòng Casbin ``g, user:<id>, role:…`` (CasbinRule=None): quyền chỉ đến từ
    # cột ``user.role`` ⇒ ``role:<vai>`` — không dựa vào gán vai theo người (M26).
    return await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": "gia_e2_" + ten,
            "email": "gia_e2_%s@example.invalid" % ten,
            "password": MAT_KHAU,
            "role": vai,
            "status": "active",
        },
        casbin_role="role:" + vai,
        unit_id=unit_id,
        models=models,
        get_password_hash=lambda _mk: _HASH_SAN,
        CasbinRule=None,
        app=fastapi_app,
    )


class _TaiKhoan:
    """Đăng nhập LƯỜI — chỉ tạo + đăng nhập vai mà ca cần; trả headers ``Authorization``.

    ``_pick_access_token`` ưu tiên COOKIE hơn header ⇒ để cookie của lần đăng nhập cuối
    trong client thì MỌI request chạy dưới vai người đăng nhập cuối. Xoá cookie sau mỗi lần
    đăng nhập: mỗi request chỉ mang đúng header của vai được chọn."""

    def __init__(self, client, hs):
        self.client, self.d, self.h = client, hs["_danh_muc"], {}

    async def __call__(self, ten):
        if ten not in self.h:
            vai, dv = VAI[ten]
            info = await _nguoi(ten, vai, self.d[dv] if dv else None)
            self.h[ten] = await get_auth_headers(self.client, info, AuthURLs.LOGIN)
            self.client.cookies.clear()
        return self.h[ten]


@pytest_asyncio.fixture
async def tk(client, hs):
    """``await tk("admin" | "ql_u1" | "ql_u2" | "ql_khong_dv" | "can_bo" | "ke_toan")``."""
    return _TaiKhoan(client, hs)


async def _dem():
    async with csdl.engine.connect() as c:
        return tuple(
            (
                await c.execute(
                    text(
                        "SELECT (SELECT count(*) FROM council_document_template), "
                        "(SELECT count(*) FROM council_document_set), "
                        "(SELECT count(*) FROM council_document_set_file)"
                    )
                )
            ).one()
        )


async def _dem_vet():
    """(số vết xoá, số dòng nhật ký tải) — hai bảng vết của lượt E3."""
    async with csdl.engine.connect() as c:
        return tuple(
            (
                await c.execute(
                    text(
                        "SELECT (SELECT count(*) FROM council_document_set_deletion), "
                        "(SELECT count(*) FROM council_document_download_log)"
                    )
                )
            ).one()
        )


async def _chen_bo(unit_id, nhan):
    """Một bộ + một tệp chèn THẲNG (bytes giả riêng từng bộ) — đo quyền, không cần dựng."""
    b = ("GIA-TEP-" + nhan).encode()
    async with csdl.engine.begin() as c:
        sid = (
            await c.execute(
                text(
                    "INSERT INTO council_document_set (moc_chup, unit_id, trinh_do, so_ho_so, "
                    "so_tep, kich_thuoc_tong, ma_ho_so_dau_vao, snapshot_dto, "
                    "thong_tin_dung) VALUES (now(), :u, 'Cao đẳng', 1, 1, :n, "
                    "'[\"GIA1\"]', '[{}]', '{\"nam_hoc\": 2026}') RETURNING id"
                ),
                {"u": unit_id, "n": len(b)},
            )
        ).scalar_one()
        await c.execute(
            text(
                "INSERT INTO council_document_set_file (set_id, thu_tu, path, sha256, "
                "kich_thuoc, noi_dung) VALUES (:s, 1, :p, :h, :n, :b)"
            ),
            {
                "s": sid,
                "p": "HoiDong/%s.docx" % nhan,
                "h": hashlib.sha256(b).hexdigest(),
                "n": len(b),
                "b": b,
            },
        )
    return sid, b


@pytest_asyncio.fixture
async def ba_bo(hs):
    d = hs["_danh_muc"]
    return {
        "u1": await _chen_bo(d["u1"], "u1"),
        "u2": await _chen_bo(d["u2"], "u2"),
        "null": await _chen_bo(None, "null"),
    }


async def _tai_ba_mau_api(client, h, ngay="2026-01-01"):
    out = {}
    for loai, b in MAU_GIA.items():
        r = await client.post(
            P + "/templates",
            data={"loai": loai, "hieu_luc_tu": ngay},
            files={"file": ("mau-%s.docx" % loai, b, KIEU_DOCX)},
            headers=h,
        )
        assert r.status_code == 201, r.text
        out[loai] = r.json()
    return out


DAU_VET = b"GIA-DAU-VET-E2"


def _danh_dau(b):
    """Bản sao gói zip ``b`` mang chú thích zip ``DAU_VET`` (nội dung các mục giữ nguyên)."""
    o = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(b)) as z, zipfile.ZipFile(o, "w") as w:
        for i in z.infolist():
            w.writestr(i, z.read(i))
        w.comment = DAU_VET
    return o.getvalue()


def _than_tao(hs, nhan=HO_SO_U1, **them):
    return dict(
        {
            "ma_ho_so": [hs[n][0] for n in nhan],
            "academic_year": 2026,
            "tham_so_quyet_dinh": TS,
        },
        **them,
    )


# ═══════════════════════════════ quyền theo VAI (Casbin) ═══════════════════════════════
ROUTE_GHI = [("POST", "/templates"), ("POST", "/sets")]
ROUTE_DOC_BO = [
    ("GET", "/sets"),
    ("GET", "/sets/{u1}"),
    ("GET", "/sets/{u1}/files/1"),
]


async def _goi(client, method, duong, h, ba_bo=None, hs=None, goc=P):
    """Gọi ``goc + duong``; ``goc=""`` ⇒ ``duong`` là đường ĐẦY ĐỦ (lấy từ bảng route)."""
    if ba_bo is not None:
        duong = duong.replace("{u1}", str(ba_bo["u1"][0]))
        duong = duong.replace("{set_id}", str(ba_bo["u1"][0]))
    if method == "GET":
        return await client.get(goc + duong, headers=h)
    if method == "DELETE":
        return await client.request(
            "DELETE", goc + duong, json={"ly_do": "GIA ly do xoa"}, headers=h
        )
    if duong.endswith("/templates"):
        return await client.post(
            goc + duong,
            data={"loai": "bien_ban", "hieu_luc_tu": "2026-01-01"},
            files={"file": ("m.docx", MAU_GIA["bien_ban"], KIEU_DOCX)},
            headers=h,
        )
    return await client.post(goc + duong, json=_than_tao(hs), headers=h)


@pytest.mark.parametrize("vai", ["ql_u1", "can_bo", "ke_toan"])
@pytest.mark.parametrize("method, duong", ROUTE_GHI)
async def test_route_ghi_chi_admin(client, tk, hs, vai, method, duong):
    r = await _goi(client, method, duong, (await tk(vai)), hs=hs)
    assert r.status_code == 403, r.text
    assert r.json()["error_code"] == "PERMISSION_DENIED"
    assert await _dem() == (0, 0, 0)  # không ghi gì


@pytest.mark.parametrize("vai", ["can_bo", "ke_toan"])
@pytest.mark.parametrize("method, duong", ROUTE_DOC_BO + [("GET", "/templates")])
async def test_can_bo_ke_toan_bi_chan_o_route_doc(
    client, tk, ba_bo, vai, method, duong
):
    r = await _goi(client, method, duong, (await tk(vai)), ba_bo=ba_bo)
    assert r.status_code == 403, r.text


async def test_quan_ly_khong_xem_kho_mau(client, tk):
    r = await client.get(P + "/templates", headers=(await tk("ql_u1")))
    assert r.status_code == 403, r.text


# ═══════════════════════════════ IDOR — phạm vi đơn vị ═════════════════════════════════
@pytest.mark.parametrize(
    "vai, cua_minh, khac", [("ql_u1", "u1", "u2"), ("ql_u2", "u2", "u1")]
)
async def test_quan_ly_chi_bo_cua_don_vi_minh_hai_chieu(
    client, tk, ba_bo, vai, cua_minh, khac
):
    h = await tk(vai)
    sid, b = ba_bo[cua_minh]
    r = await client.get(P + "/sets", headers=h)
    assert r.status_code == 200 and [x["id"] for x in r.json()] == [sid]
    assert (await client.get(P + "/sets/%d" % sid, headers=h)).status_code == 200
    r = await client.get(P + "/sets/%d/files/1" % sid, headers=h)
    assert r.status_code == 200 and r.content == b
    sid_khac, _ = ba_bo[khac]
    for duong in ("/sets/%d" % sid_khac, "/sets/%d/files/1" % sid_khac):
        r = await client.get(P + duong, headers=h)
        assert r.status_code == 404, (duong, r.text)  # 404, KHÔNG 403
        assert r.json()["detail"] == "Không có bộ văn bản này."


@pytest.mark.parametrize("duong", ["/sets/{null}", "/sets/{null}/files/1"])
@pytest.mark.parametrize("vai", ["ql_u1", "ql_u2"])
async def test_bo_khong_don_vi_chi_admin(client, tk, ba_bo, vai, duong):
    duong = duong.replace("{null}", str(ba_bo["null"][0]))
    r = await client.get(P + duong, headers=(await tk(vai)))
    assert r.status_code == 404, r.text
    assert ba_bo["null"][0] not in [
        x["id"] for x in (await client.get(P + "/sets", headers=(await tk(vai)))).json()
    ]
    r = await client.get(P + duong, headers=(await tk("admin")))
    assert r.status_code == 200, r.text


async def test_admin_thay_moi_bo_va_404_khi_khong_co(client, tk, ba_bo):
    r = await client.get(P + "/sets", headers=(await tk("admin")))
    assert sorted(x["id"] for x in r.json()) == sorted(v[0] for v in ba_bo.values())
    for sid, b in ba_bo.values():
        r = await client.get(P + "/sets/%d/files/1" % sid, headers=(await tk("admin")))
        assert r.status_code == 200 and r.content == b
    khong_co = max(v[0] for v in ba_bo.values()) + 1000
    assert (
        await client.get(P + "/sets/%d" % khong_co, headers=(await tk("admin")))
    ).status_code == 404
    assert (
        await client.get(
            P + "/sets/%d/files/9" % ba_bo["u1"][0], headers=(await tk("admin"))
        )
    ).status_code == 404


async def test_quan_ly_chua_gan_don_vi_bi_chan(client, tk, ba_bo):
    # Không bao giờ hiểu "không có đơn vị" thành "mọi đơn vị".
    h = await tk("ql_khong_dv")
    assert (await client.get(P + "/sets", headers=h)).status_code == 403
    r = await client.get(P + "/sets/%d" % ba_bo["null"][0], headers=h)
    assert r.status_code in (403, 404) and "GIA" not in r.text


# ═══════════════════════════════ tạo bộ qua API ⇒ tải bytes ĐÃ LƯU ═════════════════════
async def test_tao_bo_qua_api_tai_tung_tep_la_bytes_da_luu(client, tk, hs, monkeypatch):
    h = await tk("admin")
    mau = await _tai_ba_mau_api(client, h)
    r = await client.get(P + "/templates", headers=h)
    assert r.status_code == 200 and len(r.json()) == 3
    assert all("noi_dung" not in m for m in r.json())  # danh sách KHÔNG trả bytes
    assert (
        {m["sha256"] for m in r.json()}
        == {hashlib.sha256(b).hexdigest() for b in MAU_GIA.values()}
        == {m["sha256"] for m in mau.values()}
    )

    r = await client.post(P + "/sets", json=_than_tao(hs), headers=h)
    assert r.status_code == 201, r.text
    bo = r.json()
    d = hs["_danh_muc"]
    assert (bo["unit_id"], bo["so_ho_so"], bo["nam_hoc"]) == (d["u1"], 3, 2026)
    assert bo["tham_so_quyet_dinh"]["so_quyet_dinh"] == "99"
    assert "ma_ho_so_dau_vao" not in bo and "snapshot_dto" not in bo  # PII không ra API
    for n in HO_SO_U1:
        assert hs[n][0] not in r.text  # không mã hồ sơ nào trong phản hồi
    assert bo["thong_tin_dung"]["phien_ban_ma"] == bo_vb.PHIEN_BAN_MA
    assert [t["thu_tu"] for t in bo["tep"]] == list(range(1, bo["so_tep"] + 1))

    # Tải lại KHÔNG dựng lại: bộ dựng bị chặn hẳn từ đây.
    monkeypatch.setattr(
        bo_dung, "render_council_documents", lambda *a, **k: pytest.fail("dựng lại")
    )
    # Đóng DẤU VẾT vào bytes đã lưu (chú thích zip — tệp vẫn mở được như cũ): không cách dựng
    # lại nào (python-docx mở + lưu lại, dựng từ ảnh chụp) tái tạo được dấu vết ⇒ tải tệp PHẢI
    # trả đúng bytes trong CSDL. Không có bước này thì "mở + lưu lại" chỉ lộ khi đồng hồ qua
    # mốc 2 giây của dấu giờ zip (kiểm ngược D1a: lần xanh, lần đỏ).
    async with csdl.engine.begin() as c:
        cu = (
            await c.execute(
                text(
                    "SELECT thu_tu, noi_dung FROM council_document_set_file "
                    "WHERE set_id = :s"
                ),
                {"s": bo["id"]},
            )
        ).all()
        for row in cu:
            b = _danh_dau(bytes(row.noi_dung))
            await c.execute(
                text(
                    "UPDATE council_document_set_file SET noi_dung = :b, sha256 = :h, "
                    "kich_thuoc = :n WHERE set_id = :s AND thu_tu = :t"
                ),
                {
                    "b": b,
                    "h": hashlib.sha256(b).hexdigest(),
                    "n": len(b),
                    "s": bo["id"],
                    "t": row.thu_tu,
                },
            )
    async with csdl.engine.connect() as c:
        luu = {
            row.thu_tu: (row.path, bytes(row.noi_dung), row.sha256)
            for row in (
                await c.execute(
                    text(
                        "SELECT thu_tu, path, noi_dung, sha256 FROM "
                        "council_document_set_file WHERE set_id = :s"
                    ),
                    {"s": bo["id"]},
                )
            ).all()
        }
    assert len(luu) == bo["so_tep"]
    for t in bo["tep"]:
        r = await client.get(
            P + "/sets/%d/files/%d" % (bo["id"], t["thu_tu"]), headers=h
        )
        assert r.status_code == 200
        path, b, sha = luu[t["thu_tu"]]
        assert r.content == b and hashlib.sha256(r.content).hexdigest() == sha
        assert DAU_VET in r.content  # đúng bytes ĐÃ LƯU (có dấu vết), không dựng lại
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-content-type-options"] == "nosniff"
        cd = r.headers["content-disposition"]
        assert cd.startswith("attachment;") and "filename*=UTF-8''" in cd
        assert unquote(cd.split("filename*=UTF-8''", 1)[1]) == path.rsplit("/", 1)[-1]
        if path.endswith(".docx"):
            assert r.headers["content-type"] == KIEU_DOCX
            docx.Document(io.BytesIO(r.content))  # mở được như Word
    # Quản lý đơn vị u1 tải được, đơn vị u2 thì 404.
    url = P + "/sets/%d/files/1" % bo["id"]
    assert (await client.get(url, headers=(await tk("ql_u1")))).status_code == 200
    assert (await client.get(url, headers=(await tk("ql_u2")))).status_code == 404


async def test_tao_bo_loi_mien_khong_lo_ma_ho_so(client, tk, hs):
    h = await tk("admin")
    await _tai_ba_mau_api(client, h)
    than = _than_tao(hs)
    than["ma_ho_so"] = than["ma_ho_so"] + [ma_gia(999)]
    r = await client.post(P + "/sets", json=than, headers=h)
    assert r.status_code == 400 and "dòng 4 không có hồ sơ" in r.json()["detail"]
    assert not any(m in r.text for m in than["ma_ho_so"])
    assert await _dem() == (3, 0, 0)


def test_content_disposition_an_toan_voi_ten_co_dau():
    ten = 'Biên bản "xét"\r\nX: y.docx'
    cd = rt.content_disposition_tai_ve("HoiDong/" + ten)
    cd.encode("latin-1")  # tiêu đề HTTP mã hoá được
    assert "\r" not in cd and "\n" not in cd and cd.count('"') == 2
    assert unquote(cd.split("filename*=UTF-8''", 1)[1]) == ten
    assert 'filename="Bien_ban__xet___X__y.docx"' in cd


# ═══════════════════════════════ đóng băng — request THẬT ══════════════════════════════
def _route_cua_module():
    return [
        (m, r.path)
        for r in fastapi_app.routes
        if isinstance(r, APIRoute) and r.endpoint.__module__ == rt.__name__
        for m in r.methods
    ]


def _route_ghi_cua_module():
    return sorted(
        (m, p)
        for m, p in _route_cua_module()
        if m in {"POST", "PUT", "PATCH", "DELETE"}
    )


@pytest.fixture
def dong_bang(monkeypatch):
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", True)


async def test_dong_bang_chan_moi_route_ghi_cua_module(
    client, tk, hs, ba_bo, dong_bang
):
    ghi = _route_ghi_cua_module()
    # Bảng route THẬT — module có đúng ba route ghi: xoá bộ (E3) + tải mẫu + dựng bộ.
    assert [m for m, _ in ghi] == ["DELETE", "POST", "POST"]
    assert await _dem() == (0, 3, 3)  # ba bộ có sẵn (ba_bo)
    for m, duong in ghi:
        # Gọi ĐÚNG đường của bảng route — KHÔNG ghép lại từ hằng P: router bị dời ra ngoài
        # tiền tố đóng băng thì ca này phải ĐỎ (kiểm ngược F1 lần đầu: ghép từ P làm ca XANH).
        r = await _goi(client, m, duong, (await tk("admin")), ba_bo=ba_bo, hs=hs, goc="")
        assert r.status_code == 503, (m, duong, r.status_code, r.text)
        assert r.json()["code"] == "ADMISSION_FROZEN"
    assert await _dem() == (0, 3, 3)  # không tải mẫu, không dựng, KHÔNG xoá
    assert await _dem_vet() == (0, 0)


async def test_dong_bang_van_cho_route_doc(client, tk, ba_bo, dong_bang):
    # Mọi route ĐỌC của module (bảng route thật) vẫn 200 khi đóng băng — như mọi route đọc
    # khác của tiền tố (middleware chỉ chặn POST / PUT / PATCH / DELETE).
    doc = sorted(p for m, p in _route_cua_module() if m == "GET")
    assert len(doc) == 7  # E2: 4 + E3: danh sách mã, nhật ký tải, vết xoá
    for duong in doc:
        url = duong.replace("{set_id}", str(ba_bo["u1"][0])).replace("{thu_tu}", "1")
        r = await client.get(url, headers=(await tk("admin")))
        assert r.status_code == 200, (url, r.text)


def test_khoi_dong_bang_nginx_phu_moi_route_ghi_cua_module():
    mau = (
        Path(__file__).resolve().parents[3]
        / "nginx"
        / "templates"
        / "default.conf.template"
    ).read_text(encoding="utf-8")
    regex = re.search(r"location ~ (\^/api/\(admissions\|[^ ]*\$) \{", mau).group(1)
    for _, duong in _route_ghi_cua_module():
        assert re.match(regex, re.sub(r"\{[^}]+\}", "1", duong)), duong


# ═══════════════════════════════ lỗi 422 không ghi CCCD vào log ════════════════════════
CCCD_GIA = ["099999000E21", "099999000E22"]


async def test_loi_422_khong_ghi_cccd_vao_log(client, tk, caplog):
    caplog.set_level(logging.INFO, logger=eh.__name__)
    than = {"ma_ho_so": CCCD_GIA, "tham_so_quyet_dinh": None}  # THIẾU academic_year
    r = await client.post(P + "/sets", json=than, headers=(await tk("admin")))
    assert r.status_code == 422, r.text
    ban_ghi = [
        x for x in caplog.records if "Request validation error" in x.getMessage()
    ]
    assert len(ban_ghi) == 1  # đo đúng bản ghi của lỗi này (không xanh vì không có log)
    loi = ban_ghi[0].errors
    assert loi and all("input" not in e for e in loi)
    assert ("body", "academic_year") in {tuple(e["loc"]) for e in loi}
    toan_bo = repr([x.__dict__ for x in caplog.records]) + caplog.text
    assert not any(c in toan_bo for c in CCCD_GIA)


def test_moi_route_cua_module_khop_vi_tu_bo_input_422():
    duong = {p for _, p in _route_cua_module()}
    # /templates, /sets, /sets/{id}, /sets/{id}/files/{thu_tu} + E3: /sets/{id}/ma-ho-so,
    # /nhat-ky-tai, /nhat-ky-xoa (DELETE dùng chung /sets/{id}).
    assert len(duong) == 7
    assert all(eh._khong_log_input_422(p) for p in duong)
    assert not eh._khong_log_input_422("/api/admission-config/council-documentsX")
    assert not eh._khong_log_input_422("/api/admission-config/criteria")


# ═══════════════════════════════ một lần dựng cùng lúc — hai phiên CSDL thật ═══════════
async def _tai_ba_mau_service(hs):
    async with AsyncSessionLocal() as db:
        for loai, b in MAU_GIA.items():
            await kho_mau.tai_mau_len(
                db,
                loai=loai,
                hieu_luc_tu=date(2026, 1, 1),
                noi_dung=b,
                nguoi_tai_id=None,
            )
        await db.commit()


async def _dung(db, hs):
    return await bo_vb.tao_bo_van_ban(
        db,
        csdl.engine,
        ma_ho_so=[hs[n][0] for n in HO_SO_U1],
        academic_year=2026,
        tham_so=None,
        nguoi_tao_id=None,
    )


async def test_phien_khac_giu_khoa_thi_lan_dung_sau_bi_tu_choi(hs, monkeypatch):
    await _tai_ba_mau_service(hs)
    dung = []
    goc = bo_dung.render_council_documents

    def gian(*a, **k):
        dung.append(1)
        return goc(*a, **k)

    monkeypatch.setattr(bo_dung, "render_council_documents", gian)
    async with AsyncSessionLocal() as a, AsyncSessionLocal() as b:
        assert await CouncilDocumentRepository(a).thu_khoa_dung() is True  # A giữ khoá
        with pytest.raises(ConflictError, match="Đang dựng một bộ văn bản khác"):
            await _dung(b, hs)
        assert dung == [] and await _dem() == (3, 0, 0)  # B không dựng, không ghi
        await b.rollback()
        await a.rollback()  # A kết thúc giao dịch ⇒ khoá tự nhả
        await _dung(b, hs)
        await b.commit()
    assert dung == [1] and (await _dem())[1] == 1


async def test_hai_lan_dung_dong_thoi_lan_thu_hai_bi_tu_choi(hs, monkeypatch):
    await _tai_ba_mau_service(hs)
    vao, tha = threading.Event(), threading.Event()
    goc = bo_dung.render_council_documents

    def cham(
        *a, **k
    ):  # chạy ở luồng của to_thread ⇒ chặn được mà không chặn event loop
        vao.set()
        assert tha.wait(30)
        return goc(*a, **k)

    monkeypatch.setattr(bo_dung, "render_council_documents", cham)
    async with AsyncSessionLocal() as a, AsyncSessionLocal() as b:
        viec_a = asyncio.create_task(_dung(a, hs))
        assert await asyncio.to_thread(vao.wait, 30)  # A ĐANG dựng (giữ khoá)
        with pytest.raises(ConflictError):
            await _dung(b, hs)
        tha.set()
        bo_a, _ = await viec_a
        await a.commit()
    assert await _dem() == (3, 1, bo_a.so_tep)


async def test_api_tao_bo_khi_dang_dung_bo_khac_tra_409(client, tk, hs):
    await _tai_ba_mau_api(client, (await tk("admin")))
    async with AsyncSessionLocal() as a:
        assert await CouncilDocumentRepository(a).thu_khoa_dung() is True
        r = await client.post(
            P + "/sets", json=_than_tao(hs), headers=(await tk("admin"))
        )
        assert r.status_code == 409 and r.json()["error_code"] == "CONFLICT", r.text
        await a.rollback()
    r = await client.post(P + "/sets", json=_than_tao(hs), headers=(await tk("admin")))
    assert r.status_code == 201, r.text


# ═══════════════════════════════ không lộ qua đường tĩnh ═══════════════════════════════
_MODULE_MA = [
    "app/routers/council_documents.py",
    "app/services/council_document_render_service.py",
    "app/services/council_document_template_service.py",
    "app/services/council_document_set_service.py",
    "app/services/council_candidate_service.py",
    "app/repositories/council_document_repository.py",
    "app/repositories/council_candidate_repository.py",
]
_GHI_DIA = {"write_bytes", "write_text", "makedirs", "mkdir", "mkstemp",
            "NamedTemporaryFile", "TemporaryDirectory", "copyfile", "copy2",
            "FileResponse", "StaticFiles"}  # fmt: skip


def test_ma_van_ban_hoi_dong_khong_ghi_dia():
    # Bytes mẫu + tệp sinh CHỈ ở CSDL (bytea): không có lời gọi ghi tệp / phục vụ tệp nào.
    goc = Path(__file__).resolve().parents[2]
    vi_pham = []
    for f in _MODULE_MA:
        for n in ast.walk(ast.parse((goc / f).read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            ten = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if ten in _GHI_DIA:
                vi_pham.append((f, n.lineno, ten))
            if ten == "open" and any(
                isinstance(a, ast.Constant)
                and isinstance(a.value, str)
                and set(a.value) & set("wax+")
                for a in list(n.args[1:])
                + [k.value for k in n.keywords if k.arg == "mode"]
            ):
                vi_pham.append((f, n.lineno, "open ghi"))
    assert vi_pham == []


async def test_khong_url_tinh_nao_tra_bytes_mau_hay_tep_sinh(client, tk, hs):
    h = await tk("admin")
    await _tai_ba_mau_api(client, h)
    r = await client.post(P + "/sets", json=_than_tao(hs), headers=h)
    assert r.status_code == 201, r.text
    bo = r.json()
    da_luu = {hashlib.sha256(b).hexdigest() for b in MAU_GIA.values()} | {
        t["sha256"] for t in bo["tep"]
    }
    # (1) mọi mount tệp tĩnh của app: không tệp nào trong thư mục của nó là một bytes đã lưu
    tinh = [
        r_
        for r_ in fastapi_app.routes
        if isinstance(r_, Mount) and isinstance(r_.app, StaticFiles)
    ]
    for m in tinh:
        for thu_muc in m.app.all_directories:
            for goc_, _, ten in os.walk(thu_muc):
                for t in ten:
                    with open(os.path.join(goc_, t), "rb") as fh:
                        assert hashlib.sha256(fh.read()).hexdigest() not in da_luu
    # (2) request THẬT tới các đường tĩnh / tải lên quen thuộc với tên tệp đã lưu ⇒ không 200
    for t in bo["tep"]:
        ten = t["path"].rsplit("/", 1)[-1]
        for tien_to in ("/static/", "/static/uploads/", "/uploads/", "/"):
            for duong in (tien_to + ten, tien_to + t["path"]):
                r = await client.get(duong)
                assert (
                    r.status_code != 200
                    or hashlib.sha256(r.content).hexdigest() not in da_luu
                )
    # (3) nginx chỉ phục vụ tệp tĩnh từ hai thư mục cố định, không thư mục nào của mã văn bản
    mau = (
        Path(__file__).resolve().parents[3]
        / "nginx"
        / "templates"
        / "default.conf.template"
    ).read_text(encoding="utf-8")
    thu_muc_nginx = set(re.findall(r"^\s*(?:alias|root)\s+([^;]+);", mau, re.M))
    assert thu_muc_nginx == {"/var/www/certbot", "/app/static/uploads/"}


# ═══════════════════ F217 — log 422 chỉ ghi bản ĐÃ CHUẨN HOÁ (type + loc an toàn) ════════════
# Mỗi ca: một mã giả DẠNG CCCD (sinh lúc chạy) nằm ở MỘT chỗ của thân request; kiểm TOÀN BỘ
# bản ghi log (``repr(record.__dict__)`` mọi bản ghi + ``caplog.text``, mọi logger ở INFO).
def _ban_ghi_422(caplog):
    return [x for x in caplog.records if "Request validation error" in x.getMessage()]


def _toan_bo_log(caplog):
    return repr([x.__dict__ for x in caplog.records]) + caplog.text


async def test_422_khoa_thua_cap_dau_la_ma_gia_khong_vao_log(client, tk, hs, caplog):
    h = await tk("admin")
    caplog.set_level(logging.INFO)
    ma = ma_gia(811)
    than = dict(_than_tao(hs), **{ma: "GIA"})  # khoá JSON thừa = một "CCCD"
    r = await client.post(P + "/sets", json=than, headers=h)
    assert r.status_code == 422, r.text
    assert [e["loc"] for e in r.json()["errors"]] == [["body", ma]]  # phản hồi giữ nguyên
    bg = _ban_ghi_422(caplog)
    assert len(bg) == 1  # đo đúng bản ghi của lỗi này (không xanh vì không có log)
    assert bg[0].errors == [
        {"type": "extra_forbidden", "loc": ["body", eh.NHAN_LOC_KHONG_KHAI]}
    ]
    toan_bo = _toan_bo_log(caplog)
    assert ma not in toan_bo
    assert not any(m in toan_bo for m in than["ma_ho_so"])


async def test_422_khoa_thua_long_trong_tham_so_khong_vao_log(client, tk, hs, caplog):
    h = await tk("admin")
    caplog.set_level(logging.INFO)
    khoa = "x" + ma_gia(812)  # dạng TÊN ĐỊNH DANH hợp lệ — vẫn không phải tên trường khai
    than = _than_tao(hs, tham_so_quyet_dinh=dict(TS, **{khoa: 1}))
    r = await client.post(P + "/sets", json=than, headers=h)
    assert r.status_code == 422, r.text
    assert any(e["loc"][-1] == khoa for e in r.json()["errors"])
    bg = _ban_ghi_422(caplog)
    assert len(bg) == 1
    assert bg[0].errors == [
        {
            "type": "extra_forbidden",
            "loc": ["body", "tham_so_quyet_dinh", eh.NHAN_LOC_KHONG_KHAI],
        }
    ]
    assert khoa not in _toan_bo_log(caplog)


async def test_422_loi_co_ctx_chi_ghi_type_va_loc(client, tk, hs, caplog):
    h = await tk("admin")
    caplog.set_level(logging.INFO)
    ma = ma_gia(813)  # 12 chữ số ⇒ sai mẫu ^[0-9]{1,6}$ ⇒ lỗi có ``ctx``
    than = _than_tao(hs, tham_so_quyet_dinh=dict(TS, so_quyet_dinh=ma))
    r = await client.post(P + "/sets", json=than, headers=h)
    assert r.status_code == 422, r.text
    (loi,) = r.json()["errors"]
    assert loi["ctx"] and loi["input"] == ma and loi["msg"]  # người gửi vẫn nhận đủ
    bg = _ban_ghi_422(caplog)
    assert len(bg) == 1
    assert bg[0].errors == [
        {
            "type": "string_pattern_mismatch",
            "loc": ["body", "tham_so_quyet_dinh", "so_quyet_dinh"],
        }
    ]
    assert ma not in _toan_bo_log(caplog)


async def test_422_route_sms_qua_cung_mot_cho_chuan_hoa(client, caplog):
    caplog.set_level(logging.INFO)
    ma_bi_mat = "GIA-SMS-" + "k" * 60  # 68 ký tự > 64 ⇒ string_too_long (có ctx)
    r = await client.post("/api/public/sms/opt-out", json={"code": ma_bi_mat})
    assert r.status_code == 422, r.text
    bg = _ban_ghi_422(caplog)
    assert len(bg) == 1
    assert bg[0].errors == [{"type": "string_too_long", "loc": ["body", "code"]}]
    assert ma_bi_mat not in _toan_bo_log(caplog)


def test_chuan_hoa_422_khong_co_route_thi_moi_chuoi_thanh_nhan():
    # Không biết route (scope thiếu "route") ⇒ fail-closed: chỉ giữ nơi tham số + số.
    loi = {
        "type": "missing",
        "loc": ("body", "academic_year", 0),
        "msg": "GIA",
        "input": {"GIA": 1},
        "ctx": {"error": "GIA"},
    }
    assert eh._loi_422_an_toan_de_log([loi], None) == [
        {"type": "missing", "loc": ["body", eh.NHAN_LOC_KHONG_KHAI, 0]}
    ]


# ═══════════════════ F218 — bất biến giao dịch đo QUA ĐƯỜNG API (POST /sets thật) ═══════════
async def test_qua_api_doc_o_giao_dich_rieng_da_dong_truoc_khi_dung(
    client, tk, hs, monkeypatch
):
    # Bất biến (Codex lần 5): đọc ở giao dịch RIÊNG REPEATABLE READ READ ONLY, KẾT THÚC trước
    # khi bộ dựng chạy; ghi ở giao dịch KHÁC (của request — đã mở từ bước xác thực, không bị
    # đóng giữa chừng); câu ghi chạy SAU khi dựng.
    h = await tk("admin")
    await _tai_ba_mau_api(client, h)
    bat = {}
    loop = asyncio.get_running_loop()

    goc_doc = bo_vb.doc_ho_so_theo_ma

    async def gian_doc(*a, **k):
        anh = await goc_doc(*a, **k)
        bat["doc"] = anh.giao_dich
        return anh

    async def _giao_dich_cua(pid):
        # Kết nối KHÁC của pool. ``xact_start`` của pg_stat_activity = transaction_timestamp()
        # của giao dịch đang chạy trên tiến trình ấy (NULL nếu không có giao dịch nào).
        async with csdl.engine.connect() as c:
            xs = (
                await c.execute(
                    text("SELECT xact_start FROM pg_stat_activity WHERE pid = :p"),
                    {"p": pid},
                )
            ).scalar_one_or_none()
            luc = (await c.execute(text("SELECT clock_timestamp()"))).scalar_one()
        return xs, luc

    goc_dung = bo_dung.render_council_documents

    def gian_dung(*a, **k):  # luồng của to_thread: hỏi CSDL qua event loop chính
        fut = asyncio.run_coroutine_threadsafe(
            _giao_dich_cua(bat["doc"].backend_pid), loop
        )
        bat["xact_doc_luc_dung"], bat["luc_dung"] = fut.result(30)
        return goc_dung(*a, **k)

    goc_ghi = CouncilDocumentRepository.them_bo

    async def gian_ghi(self, bo, tep):
        bat["ghi"] = (
            await self.db.execute(
                text(
                    "SELECT pg_backend_pid() AS pid, transaction_timestamp() AS ts, "
                    "statement_timestamp() AS st, "
                    "current_setting('transaction_read_only') AS ro"
                )
            )
        ).one()
        return await goc_ghi(self, bo, tep)

    monkeypatch.setattr(bo_vb, "doc_ho_so_theo_ma", gian_doc)
    monkeypatch.setattr(bo_dung, "render_council_documents", gian_dung)
    monkeypatch.setattr(CouncilDocumentRepository, "them_bo", gian_ghi)
    r = await client.post(P + "/sets", json=_than_tao(hs), headers=h)
    assert r.status_code == 201, r.text
    doc, ghi = bat["doc"], bat["ghi"]
    assert (doc.transaction_isolation, doc.transaction_read_only) == (
        "repeatable read",
        "on",
    )
    assert ghi.ro == "off"
    # (1) giao dịch đọc ≠ giao dịch ghi
    assert (doc.backend_pid, doc.moc_chup) != (ghi.pid, ghi.ts)
    # (2) lúc bộ dựng chạy, tiến trình của giao dịch đọc KHÔNG còn ở giao dịch ấy
    assert bat["xact_doc_luc_dung"] != doc.moc_chup
    # (3) câu ghi chạy SAU khi bộ dựng bắt đầu
    assert ghi.st > bat["luc_dung"]


# ═══════════════════ F219 — lớp chặn phụ của phạm vi (gọi THẲNG dependency) ═════════════════
def _nguoi_gia(vai, unit_id=7):
    return types.SimpleNamespace(id=1, role=vai, unit_id=unit_id)


@pytest.mark.parametrize("vai", ["officer", "accountant", "user", "collaborator"])
async def test_lop_phu_pham_vi_chan_vai_khac_admin_va_quan_ly(vai):
    # Vai lọt Casbin (cấu hình sai) — KỂ CẢ khi đã gán đơn vị — vẫn bị chặn ở đây.
    with pytest.raises(PermissionDeniedError, match="Chỉ admin hoặc quản lý đơn vị"):
        await deps.get_council_document_scope(current_user=_nguoi_gia(vai))


async def test_lop_phu_pham_vi_admin_tat_ca_quan_ly_chi_don_vi_minh():
    S = deps.CouncilDocumentScope
    assert await deps.get_council_document_scope(
        current_user=_nguoi_gia("admin")
    ) == S(True, None)
    assert await deps.get_council_document_scope(
        current_user=_nguoi_gia("manager", 7)
    ) == S(False, 7)
    with pytest.raises(PermissionDeniedError, match="chưa được gán đơn vị"):
        await deps.get_council_document_scope(current_user=_nguoi_gia("manager", None))


async def test_lop_phu_route_chi_admin_chan_moi_pham_vi_khong_phai_tat_ca():
    S = deps.CouncilDocumentScope
    with pytest.raises(PermissionDeniedError, match="Chỉ admin được"):
        await deps.require_council_document_admin(scope=S(False, 7))
    assert await deps.require_council_document_admin(scope=S(True, None)) == S(
        True, None
    )
