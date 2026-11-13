# -*- coding: utf-8 -*-
"""Lượt I (F230) — ghi nhận Quyết định ĐÃ KÝ qua REQUEST THẬT (app + lifespan + Casbin + deps + middleware),
CSDL test, DỮ LIỆU GIẢ. Đặc tả ``ma-gd1/DAC-TA-TRIEN-KHAI-F230-2026-11-07.md`` (mục 2, 3, 4, 5.3, 8).

Mỗi ca một bất biến (CLAUDE.md §3); trạng thái CSDL đo bằng SQL từ kết nối khác (CLAUDE.md §10). Không mã hồ
sơ trong phản hồi lỗi. Nhóm:

* C2 — dòng bộ + sự kiện; cổng dựng bộ chặn em có Quyết định hiệu lực / chờ quyết / dấu AppSheet;
* C3 — ghi nhận: quyền, số trùng, bộ hai lần, số / ngày / mẫu theo ngày ký / ngày ký trước ngày dựng
  (giờ Việt Nam), bản ký khớp bản in, em đổi trạng thái (C3), tham số bộ đã in, hai phiên;
* C4 — huỷ hiệu lực ⇒ nhóm chờ; cho xét lại TỪNG em; huỷ ghi nhận (văn bản mới nhất; văn bản huỷ ⇒ khôi
  phục + vô hiệu nhóm chờ; xung đột U3); xoá bộ;
* C5 — điều chỉnh: bỏ / sửa thông tin em (bộ điều chỉnh nới đúng chuỗi), huỷ ghi nhận điều chỉnh bật lại dòng;
* C6 — tái dựng bản ký (F245) + so với hiện tại; bộ xét mới vẫn chặn đủ cổng (P1–P5).
"""
import ast
import asyncio
import inspect
import json
import textwrap
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

import app.database as csdl
from app.constants.admission_circular import vn_calendar_date
from app.services import council_document_set_service as bo_vb
from tests.api import test_council_documents_api as api
from tests.fixtures.hoi_dong_seed import seed_hoi_dong

pytestmark = pytest.mark.integration

P = api.P
PDF = b"%PDF-1.4\n% GIA scan F230 luot I\n" + b"0" * 64
SACH = ["dia_chi_rong", "nhieu_nv_khoang_trang", "loai_hinh_chinh_quy"]
DAU = "Đã trúng tuyển theo QĐ số 12 ngày 01/03/2026 (Biên bản 3) — KHÔNG duyệt lại, KHÔNG đưa vào lần xét mới"


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


def _ngay():
    return vn_calendar_date(datetime.now(timezone.utc))


async def _q(sql, **ts):
    async with csdl.engine.connect() as c:
        return (await c.execute(text(sql), ts)).all()


async def _q1(sql, **ts):
    return (await _q(sql, **ts))[0][0]


async def _sql(sql, **ts):
    async with csdl.engine.begin() as c:
        await c.execute(text(sql), ts)


async def _bo(client, h, hs, nhan, duong="/sets", **them):
    r = await client.post(
        P + duong,
        json=dict({"ma_ho_so": [hs[n][0] for n in nhan], "academic_year": 2026}, **them),
        headers=h,
    )
    return r


async def _bo_ok(client, h, hs, nhan, **them):
    r = await _bo(client, h, hs, nhan, **them)
    assert r.status_code == 201, r.text
    return r.json()


async def _ghi(
    client, h, set_id, *, so, so_hs, ngay=None, loai="trung_tuyen", goc_id=None, khop=True,
    xac_nhan=None, pdf=PDF, them=None,
):
    data = {
        "set_id": str(set_id),
        "loai": loai,
        "so_quyet_dinh": so,
        "ngay_ky": (ngay or _ngay()).isoformat(),
        "xac_nhan_so_ho_so": str(so_hs),
        "xac_nhan_khop_ban_in": "true" if khop else "false",
    }
    if goc_id is not None:
        data["goc_id"] = str(goc_id)
    if xac_nhan is not None:
        data["xac_nhan_trang_thai"] = json.dumps(xac_nhan)
    # Vòng giao diện (lượt gửi — đặc tả bản 2 mục 3.7): xin mã lượt NGAY trước khi gửi, như giao diện; bộ đang có lượt
    # chờ (lần gửi trước bị từ chối nghiệp vụ ⇒ lượt vẫn ``cho_gui``) ⇒ dùng lại mã ấy. Không xin được (quyền / bộ
    # không có) ⇒ gửi KHÔNG mã để route trả đúng lỗi của nó.
    if "ma_luot_gui" not in (them or {}):
        ma = await _mo_luot(client, h, set_id)
        if ma is not None:
            data["ma_luot_gui"] = ma
    data.update(them or {})
    return await client.post(
        P + "/decisions", data=data, files={"scan": ("qd.pdf", pdf, "application/pdf")}, headers=h
    )


async def _mo_luot(client, h, set_id):
    """Mã lượt gửi cho bộ ``set_id``: 201 ⇒ mã mới; 409 ``luot_dang_cho`` ⇒ mã đang chờ; khác ⇒ None."""
    r = await client.post(P + "/sets/%d/luot-ghi-nhan" % set_id, headers=h)
    if r.status_code == 201:
        return r.json()["ma"]
    if r.status_code == 409 and r.json().get("ma_loi") == "luot_dang_cho":
        return r.json()["ma"]
    return None


async def _ghi_ok(client, h, set_id, **kw):
    r = await _ghi(client, h, set_id, **kw)
    assert r.status_code == 201, r.text
    return r.json()


async def _huy_hieu_luc(client, h, qd_id, so, ngay=None):
    return await client.post(
        P + "/decisions/%d/huy-hieu-luc" % qd_id,
        data={"so_quyet_dinh": so, "ngay_ky": (ngay or _ngay()).isoformat()},
        files={"scan": ("huy.pdf", PDF, "application/pdf")},
        headers=h,
    )


async def _huy_ghi_nhan(client, h, qd_id, so, xac_nhan=None):
    return await client.post(
        P + "/decisions/%d/huy-ghi-nhan" % qd_id,
        json={"ly_do": "GIA nhap nham", "so_go_lai": so, "xac_nhan": xac_nhan},
        headers=h,
    )


async def _qd_cua_bo(client, h, hs, nhan, so):
    """Một bộ + ghi nhận Quyết định trúng tuyển cho các hồ sơ ``nhan`` (sạch, ``approved``)."""
    bo = await _bo_ok(client, h, hs, nhan)
    qd = await _ghi_ok(client, h, bo["id"], so=so, so_hs=len(nhan))
    return bo, qd


def _ma_chan(r):
    return sorted(c["ma"] for c in r.json()["kiem_tra_dung_bo"]["chan"])


# ═══════════════════════════════ C2 — dòng bộ, sự kiện, cổng tình trạng QĐ ═══════════════════
async def test_dung_bo_ghi_dong_bo_dung_ho_so_va_su_kien(client, hs, ad):
    bo = await _bo_ok(client, ad, hs, SACH)
    dong = await _q(
        "SELECT stt, profile_id, status_luc_dung, academic_year, admission_path_id "
        "FROM council_document_set_row WHERE set_id = :s ORDER BY stt",
        s=bo["id"],
    )
    assert [(d[0], d[1], d[2], d[3]) for d in dong] == [
        (i, hs[n][1], "approved", 2026) for i, n in enumerate(SACH, 1)
    ]
    assert all(d[4] is not None for d in dong)  # khoá đếm của NV in
    sk = await _q("SELECT loai, so_lieu FROM council_document_event WHERE set_id = :s", s=bo["id"])
    assert len(sk) == 1 and sk[0][0] == "tao_bo" and sk[0][1]["so_ho_so"] == 3
    assert not any(hs[n][0] in json.dumps(sk[0][1]) for n in SACH)  # không CCCD


async def test_dung_bo_bao_ho_so_dang_o_bo_khac_khong_chan(client, hs, ad):
    b1 = await _bo_ok(client, ad, hs, SACH)
    b2 = await _bo_ok(client, ad, hs, SACH[:2])
    assert b2["thong_tin_dung"]["ho_so_o_bo_khac"] == {str(b1["id"]): 2}


async def test_dung_bo_moi_chan_ho_so_da_co_qd_hieu_luc(client, hs, ad):
    await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    r = await _bo(client, ad, hs, SACH)
    assert r.status_code == 400, r.text
    assert _ma_chan(r) == ["da_co_quyet_dinh"]
    assert r.json()["kiem_tra_dung_bo"]["chan"][0]["dong"] == [1]


@pytest.mark.parametrize("nguon", ["revision_reason", "tu_van", "tu_van_da_xoa"])
async def test_dung_bo_moi_chan_dau_appsheet(client, hs, ad, nguon):
    pid = hs[SACH[1]][1]
    if nguon == "revision_reason":
        await _sql("UPDATE admission_profile SET revision_reason = :d WHERE id = :p", d=DAU, p=pid)
    else:
        await _sql(
            "INSERT INTO consultation (lead_id, consultation_date, method, notes, officer_id, "
            "reminder_sent, created_at, deleted_at) SELECT p.lead_id, now(), 'system', :d, "
            '(SELECT min(id) FROM "user"), false, now(), CAST(:x AS timestamptz) '
            "FROM admission_profile p WHERE p.id = :p",
            d=DAU,
            p=pid,
            x=datetime.now(timezone.utc) if nguon == "tu_van_da_xoa" else None,
        )
    r = await _bo(client, ad, hs, SACH)
    assert r.status_code == 400, r.text
    assert _ma_chan(r) == ["dau_trung_tuyen_appsheet"]


async def test_dung_bo_dau_lech_mot_ky_tu_khong_bi_chan(client, hs, ad):
    # Đối chứng: tiền tố sai một ký tự (không dấu "số") ⇒ không phải dấu AppSheet.
    await _sql(
        "UPDATE admission_profile SET revision_reason = :d WHERE id = :p",
        d=DAU.replace("QĐ số", "QĐ so"),
        p=hs[SACH[1]][1],
    )
    await _bo_ok(client, ad, hs, SACH)


async def test_tinh_trang_qd_cong_dung_bo_bang_ham_hoi_mot_nguon(client, hs, ad):
    # Đặc tả 8.2: cột của SQL_KIEM_NGUON (cổng dựng bộ, giao dịch chỉ đọc) == hàm hỏi
    # ``tinh_trang_qd`` trên đủ năm tình trạng (HL, CQ, XL, KO, dấu AppSheet).
    from app.database import AsyncSessionLocal
    from app.services import council_decision_status_service as tq
    from app.services.council_candidate_service import doc_ho_so_theo_id

    _, x = await _qd_cua_bo(client, ad, hs, SACH[:2], "501")
    assert (await _huy_hieu_luc(client, ad, x["id"], "701")).status_code == 201
    muc = await _q1("SELECT id FROM council_decision_hold WHERE profile_id = :p", p=hs[SACH[1]][1])
    await client.post(P + "/decision-holds/%d/cho-xet-lai" % muc, json={"ly_do": "GIA"}, headers=ad)
    await _qd_cua_bo(client, ad, hs, SACH[2:], "502")
    await _sql(
        "UPDATE admission_profile SET revision_reason = :d WHERE id = :p",
        d=DAU,
        p=hs["don_vi_khac"][1],
    )
    nhan = SACH + ["don_vi_khac", "khong_khu_vuc"]
    pids = [hs[n][1] for n in nhan]
    async with AsyncSessionLocal() as db:
        tt = await tq.tinh_trang_qd(db, pids)
    anh = await doc_ho_so_theo_id(csdl.engine, pids, academic_year=2026)
    for k, p in zip(anh.kiem, pids):
        assert (k.qd_hieu_luc_id, k.qd_chuoi_id, k.cho_quyet_id, k.dau_appsheet) == (
            tt[p].qd_hieu_luc_id,
            tt[p].qd_chuoi_id,
            tt[p].cho_quyet_id,
            tt[p].dau_appsheet,
        ), p
    assert [tt[p].ma for p in pids] == [tq.CQ, tq.XL, tq.HL, tq.KO, tq.KO]
    assert [tt[p].dau_appsheet for p in pids] == [False, False, False, True, False]


# ═══════════════════════════════ C3 — ghi nhận ═════════════════════════════════════════════
async def test_ghi_nhan_tao_van_ban_dong_scan_su_kien(client, hs, ad, tk):
    bo, qd = await _qd_cua_bo(client, ad, hs, SACH, "501")
    assert (qd["loai"], qd["trang_thai"], qd["so_ho_so"], qd["pham_vi_so"]) == (
        "trung_tuyen",
        "hieu_luc",
        3,
        _ngay().year,
    )
    dong = await _q(
        "SELECT stt, profile_id, trang_thai_cha FROM council_decision_row WHERE decision_id = :d "
        "ORDER BY stt",
        d=qd["id"],
    )
    assert [tuple(x) for x in dong] == [
        (i, hs[n][1], "hieu_luc") for i, n in enumerate(SACH, 1)
    ]
    assert await _q1(
        "SELECT count(*) FROM council_decision_scan WHERE decision_id = :d AND sha256 = "
        "encode(sha256(:b), 'hex')",
        d=qd["id"],
        b=PDF,
    ) == 1
    assert await _q1(
        "SELECT count(*) FROM council_document_event WHERE decision_id = :d AND loai = 'ghi_nhan'",
        d=qd["id"],
    ) == 1
    # Quản lý đơn vị xem được trạng thái QĐ trên bộ của mình (không id hồ sơ)
    r = await client.get(P + "/sets/%d" % bo["id"], headers=await tk("ql_u1"))
    assert r.status_code == 200
    # Vòng giao diện (đặc tả 3.4 / 3.5): GIỮ các khoá cũ + thêm ``id`` và ``goc`` (văn bản xét mới ⇒ goc null).
    assert r.json()["quyet_dinh"] == {
        "id": qd["id"],
        "loai": "trung_tuyen",
        "trang_thai": "hieu_luc",
        "so_quyet_dinh": "501",
        "ngay_ky": _ngay().isoformat(),
        "so_ho_so": 3,
        "goc": None,
    }
    assert r.json()["tinh_trang"] == "con_hieu_luc" and r.json()["luot_gui_cho"] is None


async def test_tai_scan_tra_dung_byte_va_ghi_su_kien(client, hs, ad):
    # Đường tải bản scan (cột HOÃN ``noi_dung`` — nạp tường minh): trả đúng byte đã ghi, mỗi lần cấp một sự kiện.
    _, a = await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    r = await client.get(P + "/decisions/%d/scan" % a["id"], headers=ad)
    assert r.status_code == 200 and r.content == PDF, (r.status_code, r.text[:200])
    assert await _q1(
        "SELECT count(*) FROM council_document_event WHERE loai = 'tai_scan' AND decision_id = :d",
        d=a["id"],
    ) == 1


@pytest.mark.parametrize("vai", ["ql_u1", "can_bo", "ke_toan"])
async def test_ghi_nhan_chi_admin(client, hs, ad, tk, vai):
    bo = await _bo_ok(client, ad, hs, SACH)
    r = await _ghi(client, await tk(vai), bo["id"], so="501", so_hs=3)
    assert r.status_code == 403, r.text
    assert await _q1("SELECT count(*) FROM council_decision") == 0


async def test_ghi_nhan_casbin_cho_qua_quan_ly_lop_phu_van_403(client, hs, ad, tk):
    from tests.api.test_council_documents_hop_dong_api import _policy_tam

    bo = await _bo_ok(client, ad, hs, SACH)
    h = await tk("ql_u1")
    with _policy_tam(["role:manager", P + "/decisions", "POST", "allow"]):
        r = await _ghi(client, h, bo["id"], so="501", so_hs=3)
    assert r.status_code == 403, r.text
    assert await _q1("SELECT count(*) FROM council_decision") == 0


async def test_ghi_nhan_so_trung_trong_nam_409(client, hs, ad):
    await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    b2 = await _bo_ok(client, ad, hs, SACH[1:])
    r = await _ghi(client, ad, b2["id"], so="501", so_hs=2)
    assert r.status_code == 409, r.text
    assert await _q1("SELECT count(*) FROM council_decision") == 1


async def test_ghi_nhan_bo_hai_lan_409(client, hs, ad):
    bo, _ = await _qd_cua_bo(client, ad, hs, SACH, "501")
    r = await _ghi(client, ad, bo["id"], so="502", so_hs=3)
    assert r.status_code == 409, r.text


@pytest.mark.parametrize(
    "sua, ma",
    [
        ({"so_hs": 2}, 400),
        ({"khop": False}, 400),
        ({"pdf": b"GIA khong phai pdf"}, 400),
        ({"so": "12a"}, 422),
    ],
)
async def test_ghi_nhan_dau_vao_sai_khong_ghi(client, hs, ad, sua, ma):
    bo = await _bo_ok(client, ad, hs, SACH)
    kw = dict(so="501", so_hs=3)
    kw.update(sua)
    r = await _ghi(client, ad, bo["id"], **kw)
    assert r.status_code == ma, r.text
    assert await _q1("SELECT count(*) FROM council_decision") == 0


async def test_ghi_nhan_scan_qua_tran_ky_thuat(client, hs, ad, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "COUNCIL_DECISION_SCAN_MAX_BYTES", 64 * 1024)
    bo = await _bo_ok(client, ad, hs, SACH)
    r = await _ghi(client, ad, bo["id"], so="501", so_hs=3, pdf=PDF + b"0" * (64 * 1024))
    assert r.status_code == 400, r.text


async def test_ghi_nhan_ngay_ky_truoc_ngay_dung_theo_gio_viet_nam(client, hs, ad):
    # G11: bộ tạo 23:30 UTC ngày X (= 06:30 giờ VN ngày X+1) ⇒ ký ngày X bị chặn (so theo ngày UTC sẽ lọt).
    bo = await _bo_ok(client, ad, hs, SACH)
    x = _ngay() - timedelta(days=1)
    await _sql(
        "UPDATE council_document_set SET tao_luc = :t WHERE id = :s",
        t=datetime(x.year, x.month, x.day, 23, 30, tzinfo=timezone.utc),
        s=bo["id"],
    )
    r = await _ghi(client, ad, bo["id"], so="501", so_hs=3, ngay=x)
    assert r.status_code == 400 and "trước ngày dựng" in r.json()["detail"], r.text
    r = await _ghi(client, ad, bo["id"], so="501", so_hs=3, ngay=x + timedelta(days=1))
    assert r.status_code == 201, r.text  # đối chứng: ngày VN của lúc dựng


async def test_ghi_nhan_mau_theo_ngay_ky_khac_mau_bo_da_dung(client, hs, ad):
    # G10: bộ chọn mẫu theo ngày dựng; mẫu BIÊN BẢN mới hiệu lực từ ngày ký ⇒ chặn (chỉ so mẫu QĐ sẽ lọt).
    bo = await _bo_ok(client, ad, hs, SACH)
    sau = _ngay() + timedelta(days=2)
    r = await client.post(
        P + "/templates",
        data={"loai": "bien_ban", "hieu_luc_tu": sau.isoformat()},
        files={"file": ("m.docx", api._danh_dau(api.MAU_GIA["bien_ban"]), api.KIEU_DOCX)},
        headers=ad,
    )
    assert r.status_code == 201, r.text
    r = await _ghi(client, ad, bo["id"], so="501", so_hs=3, ngay=sau)
    assert r.status_code == 400 and r.json().get("mau_lech") == ["bien_ban"], r.text


async def test_ghi_nhan_tham_so_bo_da_in_khac_giay(client, hs, ad):
    bo = await _bo_ok(client, ad, hs, SACH, tham_so_quyet_dinh={"so_quyet_dinh": "777"})
    r = await _ghi(client, ad, bo["id"], so="778", so_hs=3)
    assert r.status_code == 400 and r.json().get("truong_lech") == ["số Quyết định"], r.text
    await _ghi_ok(client, ad, bo["id"], so="777", so_hs=3)  # đối chứng


async def test_ghi_nhan_em_doi_trang_thai_can_xac_nhan_dung_so_dem(client, hs, ad):
    # C3: em đổi trạng thái giữa lúc dựng và lúc ký ⇒ ghi đúng bản ký, Admin xác nhận số đếm.
    bo = await _bo_ok(client, ad, hs, SACH)
    await _sql("UPDATE admission_profile SET status = 'draft' WHERE id = :p", p=hs[SACH[2]][1])
    r = await _ghi(client, ad, bo["id"], so="501", so_hs=3)
    assert r.status_code == 409, r.text
    assert r.json()["xac_nhan_can"] == {
        "so_ho_so_theo_loai": {"draft": 1},
        "dong_theo_loai": {"draft": [3]},
    }
    r = await _ghi(client, ad, bo["id"], so="501", so_hs=3, xac_nhan={"withdrawn": 1})
    assert r.status_code == 409, r.text
    qd = await _ghi_ok(client, ad, bo["id"], so="501", so_hs=3, xac_nhan={"draft": 1})
    assert qd["xac_nhan"]["doi_trang_thai"] == {"draft": 1}


async def test_ghi_nhan_hai_phien_cung_ho_so_dung_mot_thanh_cong(client, hs, ad):
    # Hai bộ chung một hồ sơ, hai request ĐỒNG THỜI ⇒ đúng một 201 (khoá hồ sơ + U3).
    b1 = await _bo_ok(client, ad, hs, SACH[:2])
    b2 = await _bo_ok(client, ad, hs, SACH[1:])
    r1, r2 = await asyncio.gather(
        _ghi(client, ad, b1["id"], so="601", so_hs=2), _ghi(client, ad, b2["id"], so="602", so_hs=2)
    )
    assert sorted([r1.status_code, r2.status_code]) == [201, 409], (r1.text, r2.text)
    assert await _q1(
        "SELECT count(*) FROM council_decision_row WHERE profile_id = :p AND "
        "trang_thai_cha = 'hieu_luc' AND bi_bo_boi_id IS NULL",
        p=hs[SACH[1]][1],
    ) == 1


async def test_ghi_nhan_bo_sung_can_goc_hieu_luc(client, hs, ad):
    _, a = await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    b = await _bo_ok(client, ad, hs, SACH[1:])
    r = await _ghi(client, ad, b["id"], so="502", so_hs=2, loai="bo_sung")
    assert r.status_code == 400, r.text  # thiếu gốc
    qd = await _ghi_ok(client, ad, b["id"], so="502", so_hs=2, loai="bo_sung", goc_id=a["id"])
    assert qd["goc_id"] == a["id"]


# ═══════════════════════════════ C4 — huỷ hiệu lực, nhóm chờ, huỷ ghi nhận, xoá bộ ═══════════════
async def test_huy_hieu_luc_dua_moi_em_vao_nhom_cho(client, hs, ad):
    bo, x = await _qd_cua_bo(client, ad, hs, SACH, "501")
    r = await _huy_hieu_luc(client, ad, x["id"], "701")
    assert r.status_code == 201, r.text
    h = r.json()
    assert h["loai"] == "van_ban_huy" and h["so_lieu"]["so_muc_cho_moi"] == 3
    assert await _q1("SELECT trang_thai FROM council_decision WHERE id = :x", x=x["id"]) == (
        "het_hieu_luc"
    )
    assert await _q1(
        "SELECT count(*) FROM council_decision_row WHERE decision_id = :x AND "
        "trang_thai_cha = 'het_hieu_luc'",
        x=x["id"],
    ) == 3
    cho = await _q(
        "SELECT profile_id, trang_thai FROM council_decision_hold WHERE van_ban_huy_id = :h "
        "ORDER BY profile_id",
        h=h["id"],
    )
    assert [tuple(c) for c in cho] == sorted((hs[n][1], "cho_quyet") for n in SACH)


async def test_huy_hieu_luc_chan_khi_con_bo_sung_hieu_luc(client, hs, ad):
    _, a = await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    b = await _bo_ok(client, ad, hs, SACH[1:])
    await _ghi_ok(client, ad, b["id"], so="502", so_hs=2, loai="bo_sung", goc_id=a["id"])
    r = await _huy_hieu_luc(client, ad, a["id"], "701")
    assert r.status_code == 409, r.text


async def test_nhom_cho_chan_dung_bo_va_ghi_nhan_den_khi_admin_cho_tung_em(client, hs, ad):
    # F244-1, F244-2, F244-4: bộ dựng TRƯỚC khi huỷ cũng không ghi nhận được; cho xét lại em A ⇒ A qua
    # cổng, B (chưa cho) vẫn bị chặn.
    bo_truoc = await _bo_ok(client, ad, hs, SACH[1:2])  # dựng khi em CHƯA có Quyết định nào
    _, x = await _qd_cua_bo(client, ad, hs, SACH[:2], "501")
    assert (await _huy_hieu_luc(client, ad, x["id"], "701")).status_code == 201
    r = await _bo(client, ad, hs, SACH[:2])
    assert r.status_code == 400 and _ma_chan(r) == ["cho_admin_quyet"], r.text
    r = await _ghi(client, ad, bo_truoc["id"], so="502", so_hs=1)
    assert r.status_code == 409, r.text
    muc_a = await _q1(
        "SELECT id FROM council_decision_hold WHERE profile_id = :p", p=hs[SACH[0]][1]
    )
    r = await client.post(
        P + "/decision-holds/%d/cho-xet-lai" % muc_a, json={"ly_do": "GIA truong cho"}, headers=ad
    )
    assert r.status_code == 200, r.text
    await _bo_ok(client, ad, hs, SACH[:1])
    r = await _bo(client, ad, hs, SACH[1:2])
    assert r.status_code == 400 and _ma_chan(r) == ["cho_admin_quyet"], r.text


@pytest.mark.parametrize("vai", ["ql_u1", "can_bo"])
async def test_cho_xet_lai_chi_admin_muc_khong_doi(client, hs, ad, tk, vai):
    _, x = await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    assert (await _huy_hieu_luc(client, ad, x["id"], "701")).status_code == 201
    muc = await _q1("SELECT id FROM council_decision_hold")
    r = await client.post(
        P + "/decision-holds/%d/cho-xet-lai" % muc, json={"ly_do": "GIA"}, headers=await tk(vai)
    )
    assert r.status_code == 403, r.text
    assert await _q1("SELECT trang_thai FROM council_decision_hold WHERE id = :m", m=muc) == (
        "cho_quyet"
    )


async def test_huy_ghi_nhan_van_ban_huy_khoi_phuc_qd_va_vo_hieu_nhom_cho(client, hs, ad):
    # F244-7 + 2.5: một em đã được cho xét lại ⇒ phải xác nhận; sau đó X hiệu lực lại, mọi mục chờ vô hiệu.
    _, x = await _qd_cua_bo(client, ad, hs, SACH[:2], "501")
    h = (await _huy_hieu_luc(client, ad, x["id"], "701")).json()
    muc_a = await _q1(
        "SELECT id FROM council_decision_hold WHERE profile_id = :p", p=hs[SACH[0]][1]
    )
    await client.post(
        P + "/decision-holds/%d/cho-xet-lai" % muc_a, json={"ly_do": "GIA"}, headers=ad
    )
    r = await _huy_ghi_nhan(client, ad, h["id"], "701")
    assert r.status_code == 409 and r.json()["xac_nhan_can"]["so_ho_so_theo_loai"] == {
        "da_cho_xet_lai": 1
    }, r.text
    r = await _huy_ghi_nhan(client, ad, h["id"], "701", xac_nhan={"da_cho_xet_lai": 1})
    assert r.status_code == 200, r.text
    assert await _q1("SELECT trang_thai FROM council_decision WHERE id = :x", x=x["id"]) == (
        "hieu_luc"
    )
    assert await _q1(
        "SELECT count(*) FROM council_decision_row WHERE decision_id = :x AND "
        "trang_thai_cha = 'hieu_luc'",
        x=x["id"],
    ) == 2
    assert [
        t[0] for t in await _q("SELECT DISTINCT trang_thai FROM council_decision_hold")
    ] == ["vo_hieu"]


async def test_huy_ghi_nhan_van_ban_huy_khi_em_da_vao_qd_khac_409(client, hs, ad):
    # F244-6: A được cho xét lại rồi vào Quyết định B ⇒ huỷ ghi nhận văn bản huỷ bị từ chối, X giữ nguyên.
    _, x = await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    h = (await _huy_hieu_luc(client, ad, x["id"], "701")).json()
    muc = await _q1("SELECT id FROM council_decision_hold")
    await client.post(P + "/decision-holds/%d/cho-xet-lai" % muc, json={"ly_do": "GIA"}, headers=ad)
    await _qd_cua_bo(client, ad, hs, SACH[:1], "502")
    r = await _huy_ghi_nhan(client, ad, h["id"], "701", xac_nhan={"da_cho_xet_lai": 1})
    assert r.status_code == 409 and r.json()["dong_xung_dot"][0]["dong"] == 1, r.text
    assert await _q1("SELECT trang_thai FROM council_decision WHERE id = :x", x=x["id"]) == (
        "het_hieu_luc"
    )
    assert await _q1("SELECT trang_thai FROM council_decision_hold WHERE id = :m", m=muc) == (
        "da_cho_xet_lai"
    )


async def test_huy_ghi_nhan_chi_van_ban_moi_nhat_cua_chuoi(client, hs, ad):
    _, a = await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    b = await _bo_ok(client, ad, hs, SACH[1:])
    await _ghi_ok(client, ad, b["id"], so="502", so_hs=2, loai="bo_sung", goc_id=a["id"])
    r = await _huy_ghi_nhan(client, ad, a["id"], "501")
    assert r.status_code == 409 and r.json()["van_ban_sau"], r.text


async def test_huy_ghi_nhan_so_go_lai_sai_400(client, hs, ad):
    _, a = await _qd_cua_bo(client, ad, hs, SACH[:1], "501")
    r = await _huy_ghi_nhan(client, ad, a["id"], "502")
    assert r.status_code == 400, r.text


async def test_xoa_bo_cua_qd_chan_den_khi_huy_ghi_nhan(client, hs, ad):
    bo, a = await _qd_cua_bo(client, ad, hs, SACH, "501")
    r = await client.request("DELETE", P + "/sets/%d" % bo["id"], json={"ly_do": "GIA"}, headers=ad)
    assert r.status_code == 409, r.text
    assert await _q1("SELECT count(*) FROM council_document_set WHERE id = :s", s=bo["id"]) == 1
    assert (await _huy_ghi_nhan(client, ad, a["id"], "501")).status_code == 200
    r = await client.request("DELETE", P + "/sets/%d" % bo["id"], json={"ly_do": "GIA"}, headers=ad)
    assert r.status_code == 200, r.text
    hang = await _q(
        "SELECT set_id, set_row_id, profile_id FROM council_decision_row WHERE decision_id = :d",
        d=a["id"],
    )
    assert all(h[0] is None and h[1] is None and h[2] is not None for h in hang)
    assert await _q1("SELECT so_quyet_dinh FROM council_decision WHERE id = :d", d=a["id"]) == "501"


# ═══════════════════════════════ C5 — điều chỉnh ═════════════════════════════════════════════
async def _dieu_chinh(client, h, goc_id, so, bo_dong=(), set_id=None, so_hs=None, xac_nhan=None):
    # httpx: multipart cần ``data`` là dict (giá trị list ⇒ trường lặp); list cặp bị coi là thân thô.
    data = {"so_quyet_dinh": so, "ngay_ky": _ngay().isoformat()}
    if bo_dong:
        data["bo_dong"] = [str(x) for x in bo_dong]
    if set_id is not None:
        data.update(
            set_id=str(set_id), xac_nhan_so_ho_so=str(so_hs), xac_nhan_khop_ban_in="true"
        )
    if xac_nhan is not None:
        data["xac_nhan_trang_thai"] = json.dumps(xac_nhan)
    return await client.post(
        P + "/decisions/%d/dieu-chinh" % goc_id,
        data=data,
        files={"scan": ("dc.pdf", PDF, "application/pdf")},
        headers=h,
    )


async def _dong_cua(qd_id, pid):
    return await _q1(
        "SELECT id FROM council_decision_row WHERE decision_id = :d AND profile_id = :p",
        d=qd_id,
        p=pid,
    )


async def test_dieu_chinh_bo_mot_em_em_ay_het_bi_khoa(client, hs, ad):
    _, a = await _qd_cua_bo(client, ad, hs, SACH, "501")
    pid = hs[SACH[0]][1]
    r = await _dieu_chinh(client, ad, a["id"], "801", bo_dong=[await _dong_cua(a["id"], pid)])
    assert r.status_code == 201, r.text
    assert await _q1(
        "SELECT count(*) FROM council_decision_row WHERE profile_id = :p AND "
        "trang_thai_cha = 'hieu_luc' AND bi_bo_boi_id IS NULL",
        p=pid,
    ) == 0
    await _bo_ok(client, ad, hs, SACH[:1])  # em đã bị bỏ ⇒ vào bộ mới được


async def test_dieu_chinh_sua_thong_tin_em_bo_moi_chan_bo_dieu_chinh_cho_qua(client, hs, ad):
    _, a = await _qd_cua_bo(client, ad, hs, SACH, "501")
    r = await _bo(client, ad, hs, SACH[:1])  # P1 / N10: bộ XÉT MỚI vẫn chặn
    assert r.status_code == 400 and _ma_chan(r) == ["da_co_quyet_dinh"], r.text
    bd = await _bo_ok(client, ad, hs, SACH[:1], duong="/decisions/%d/bo-dieu-chinh" % a["id"])
    assert bd["cho_quyet_dinh_goc_id"] == a["id"]
    pid = hs[SACH[0]][1]
    r = await _dieu_chinh(client, ad, a["id"], "801", set_id=bd["id"], so_hs=1)
    assert r.status_code == 409 and r.json()["dong_bi_chan"][0]["ly_do"] == "chua_bo_dong_cu"
    cu = await _dong_cua(a["id"], pid)
    r = await _dieu_chinh(client, ad, a["id"], "801", bo_dong=[cu], set_id=bd["id"], so_hs=1)
    assert r.status_code == 201, r.text
    dc = r.json()
    moi = await _q(
        "SELECT decision_id FROM council_decision_row WHERE profile_id = :p AND "
        "trang_thai_cha = 'hieu_luc' AND bi_bo_boi_id IS NULL",
        p=pid,
    )
    assert [m[0] for m in moi] == [dc["id"]]
    # bộ điều chỉnh KHÔNG ghi nhận được như Quyết định trúng tuyển
    bd2 = await _bo_ok(client, ad, hs, SACH[1:2], duong="/decisions/%d/bo-dieu-chinh" % a["id"])
    r = await _ghi(client, ad, bd2["id"], so="802", so_hs=1)
    assert r.status_code == 400, r.text


async def test_huy_ghi_nhan_dieu_chinh_bat_lai_dong_da_bo(client, hs, ad):
    # G13: điều chỉnh bỏ A → huỷ ghi nhận điều chỉnh ⇒ A hiệu lực lại trong Quyết định gốc.
    _, a = await _qd_cua_bo(client, ad, hs, SACH, "501")
    pid = hs[SACH[0]][1]
    cu = await _dong_cua(a["id"], pid)
    dc = (await _dieu_chinh(client, ad, a["id"], "801", bo_dong=[cu])).json()
    r = await _huy_ghi_nhan(client, ad, dc["id"], "801")
    assert r.status_code == 200, r.text
    assert await _q1("SELECT bi_bo_boi_id FROM council_decision_row WHERE id = :d", d=cu) is None
    r = await _bo(client, ad, hs, SACH[:1])
    assert r.status_code == 400 and _ma_chan(r) == ["da_co_quyet_dinh"]


# ═══════════════════════════════ C6 — tái dựng bản ký + so với hiện tại (F245) ═════════════════
async def test_tai_dung_ban_ky_dong_sua_tay_va_em_da_rut(client, hs, ad):
    s0 = await _bo_ok(client, ad, hs, SACH)
    await _sql(
        "UPDATE admission_profile SET full_name = 'Họ Giả Sửa Tay' WHERE id = :p", p=hs[SACH[1]][1]
    )
    await _sql("UPDATE admission_profile SET status = 'withdrawn' WHERE id = :p", p=hs[SACH[2]][1])
    r = await _bo(client, ad, hs, SACH)  # bộ XÉT MỚI: em đã rút bị chặn F228 (P3)
    assert r.status_code == 400 and "trang_thai_chan" in _ma_chan(r), r.text
    than = {
        "so_quyet_dinh": "901",
        "ngay_ky": _ngay().isoformat(),
        "dong_sua_tay": [2],
        "ly_do": "GIA truong sua tay ho ten tren ban ky",
    }
    r = await client.post(P + "/sets/%d/dung-lai-ban-ky" % s0["id"], json=than, headers=ad)
    assert r.status_code == 409, r.text
    khac = r.json()["dong_khac"]
    assert khac == [{"stt": 2, "truong": ["ho", "ten"]}], khac
    r = await client.post(
        P + "/sets/%d/dung-lai-ban-ky" % s0["id"],
        json=dict(than, xac_nhan_dong_khac=khac),
        headers=ad,
    )
    assert r.status_code == 201, r.text
    rb = r.json()
    assert (rb["dung_lai_tu_set_id"], rb["ban_ky_so_quyet_dinh"]) == (s0["id"], "901")
    # Đặc tả 3.1: lý do bắt buộc, giữ ở thông tin dựng của R, KHÔNG ghi vào sự kiện (bước 12).
    assert await _q1(
        "SELECT thong_tin_dung->'dung_lai_ban_ky'->>'ly_do' FROM council_document_set WHERE id = :s",
        s=rb["id"],
    ) == than["ly_do"]
    assert await _q1(
        "SELECT count(*) FROM council_document_event WHERE loai = 'dung_lai_ban_ky' AND set_id = :s "
        "AND so_lieu ? 'ly_do'",
        s=rb["id"],
    ) == 0
    thieu = {k: v for k, v in than.items() if k != "ly_do"}
    r = await client.post(P + "/sets/%d/dung-lai-ban-ky" % s0["id"], json=thieu, headers=ad)
    assert r.status_code == 422, r.text
    # ghi nhận bộ tái dựng: em đã rút được LIỆT KÊ, Admin xác nhận (C3) — không chặn
    r = await _ghi(client, ad, rb["id"], so="901", so_hs=3)
    assert r.status_code == 409 and r.json()["xac_nhan_can"]["so_ho_so_theo_loai"] == {
        "withdrawn": 1
    }, r.text
    r = await _ghi(client, ad, rb["id"], so="902", so_hs=3, xac_nhan={"withdrawn": 1})
    assert r.status_code == 400, r.text  # P5: số ≠ số bản ký đã khai
    await _ghi_ok(client, ad, rb["id"], so="901", so_hs=3, xac_nhan={"withdrawn": 1})


async def test_tai_dung_dong_sua_tay_trang_thai_chan_f228_chi_liet_ke(client, hs, ad):
    # Đặc tả 3.1 bước 6 + P3: CHÍNH dòng sửa tay có trạng thái chặn F228 ("Nháp") ⇒ đường tái dựng KHÔNG chặn
    # (trạng thái chỉ liệt kê lúc ghi nhận — C3); bộ xét mới thì chặn. Trạng thái đặt bằng SQL ⇒ học phí còn nguyên
    # (khác ca ba lớp ở dưới).
    s0 = await _bo_ok(client, ad, hs, SACH)
    pid = hs[SACH[1]][1]
    await _sql(
        "UPDATE admission_profile SET full_name = 'Họ Giả Sửa Tay', status = 'draft' WHERE id = :p", p=pid
    )
    r = await _bo(client, ad, hs, SACH)
    assert r.status_code == 400 and "trang_thai_chan" in _ma_chan(r), r.text
    than = {
        "so_quyet_dinh": "901",
        "ngay_ky": _ngay().isoformat(),
        "dong_sua_tay": [2],
        "ly_do": "GIA",
        "xac_nhan_dong_khac": [{"stt": 2, "truong": ["ho", "ten"]}],
    }
    r = await client.post(P + "/sets/%d/dung-lai-ban-ky" % s0["id"], json=than, headers=ad)
    assert r.status_code == 201, r.text


async def test_tai_dung_dong_sua_tay_khong_dung_lai_duoc_tu_du_lieu_song(client, hs, ad):
    # Ca ba lớp (sửa tay + chính em ấy rút làm huỷ học phí): CHẶN, liệt kê — fail-closed.
    s0 = await _bo_ok(client, ad, hs, SACH)
    await _sql(
        "UPDATE fee SET status = 'cancelled' WHERE admission_profile_id = :p", p=hs[SACH[1]][1]
    )
    r = await client.post(
        P + "/sets/%d/dung-lai-ban-ky" % s0["id"],
        json={
            "so_quyet_dinh": "901",
            "ngay_ky": _ngay().isoformat(),
            "dong_sua_tay": [2],
            "ly_do": "GIA",
        },
        headers=ad,
    )
    assert r.status_code == 400, r.text
    ma = [c["ma"] for c in r.json()["kiem_tra_dung_lai"]]
    assert ma == ["thieu_hoc_phi_hk1"] and r.json()["kiem_tra_dung_lai"][0]["dong"] == [2]


async def test_post_sets_khong_nhan_tham_so_noi_cong(client, hs, ad):
    # P2: schema extra="forbid" — không có đường nào nới cổng qua POST /sets.
    for k, v in (("dung_lai_tu_set_id", 1), ("cho_quyet_dinh_goc_id", 1), ("dong_sua_tay", [1])):
        r = await _bo(client, ad, hs, SACH, **{k: v})
        assert r.status_code == 422, (k, r.text)


@pytest.mark.parametrize("ham", ["tao_bo_van_ban", "tao_bo_van_ban_theo_id"])
def test_tao_bo_van_ban_goi_cong_day_du_khong_tham_so_noi(ham):
    # P1 (AST): HAI điểm vào dựng bộ XÉT MỚI (dạng mã; dạng id của vòng giao diện) không nhận tham số nới
    # cổng; gọi lõi với HẰNG None; lõi gọi ``cong.danh_gia`` (không ``danh_gia_dung_lai``).
    f = getattr(bo_vb, ham)
    tham_so = set(inspect.signature(f).parameters)
    assert not tham_so & {"chuoi_qd_cho_phep", "dong_sua_tay", "dung_lai_tu_set_id"}
    cay = ast.parse(textwrap.dedent(inspect.getsource(f)))
    goi = [n for n in ast.walk(cay) if isinstance(n, ast.Call)]
    loi = [g for g in goi if getattr(g.func, "id", None) == "_dung_va_ghi_bo"]
    assert len(loi) == 1
    kw = {k.arg: k.value for k in loi[0].keywords}
    assert isinstance(kw["chuoi_qd_cho_phep"], ast.Constant) and kw["chuoi_qd_cho_phep"].value is None
    nguon_loi = inspect.getsource(bo_vb._dung_va_ghi_bo)
    assert "cong.danh_gia(" in nguon_loi and "danh_gia_dung_lai" not in nguon_loi


async def test_so_voi_hien_tai_chi_ten_truong_khong_gia_tri(client, hs, ad, tk):
    s0 = await _bo_ok(client, ad, hs, SACH)
    await _sql(
        "UPDATE admission_profile SET full_name = 'Họ Giả Đổi Tên' WHERE id = :p", p=hs[SACH[0]][1]
    )
    r = await client.get(P + "/sets/%d/so-voi-hien-tai" % s0["id"], headers=ad)
    assert r.status_code == 200, r.text
    assert r.json()["dong_khac"] == [{"stt": 1, "truong": ["ho", "ten"]}]
    assert "Đổi Tên" not in r.text and hs[SACH[0]][0] not in r.text
    r = await client.get(P + "/sets/%d/so-voi-hien-tai" % s0["id"], headers=await tk("ql_u1"))
    assert r.status_code == 403
