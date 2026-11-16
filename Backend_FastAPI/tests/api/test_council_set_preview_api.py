# -*- coding: utf-8 -*-
"""Vòng giao diện — đường chọn hồ sơ (đặc tả 3.1, 3.2, 3.3, 3.11 + bản 2/3 mục 3.1.1) qua REQUEST THẬT (app +
lifespan + Casbin + deps + middleware), CSDL test, DỮ LIỆU GIẢ.

* ``POST /sets/kiem-truoc``: thứ tự chuẩn + dấu bất biến với thứ tự gửi; không ghi gì; dòng bị chặn mang mã +
  câu thật của cổng; vị trí không tìm thấy / khác năm / ngoài đơn vị gộp một danh sách (không lộ tồn tại).
* ``POST /sets`` dạng id: dựng đúng thứ tự kiểm trước (``pbk_dau_vao_chua_sap``); thứ tự gửi khác / dữ liệu đổi
  (họ) / khoá HMAC đổi ⇒ 409 ``du_lieu_doi_tu_luc_kiem``, 0 bộ; trường ngoài ảnh chụp đổi ⇒ vẫn dựng (đối
  chứng: dấu không nhạy thừa); đọc hồ sơ ĐÚNG MỘT lần; cổng chặn vẫn áp SAU khi dấu khớp; thứ tự dòng bộ = thứ
  tự trên Quyết định đã dựng (đọc từ tệp).
* ``POST /sets/doi-ma``: không dừng ở dòng lỗi đầu; chỉ số dòng + mã lý do; không trả lại giá trị.
* ``POST /sets/tim-ho-so``: cùng service danh sách hồ sơ; từ khoá (CCCD giả) KHÔNG vào log / URL.

Mỗi ca một bất biến (CLAUDE.md §3); trạng thái CSDL đo bằng SQL từ kết nối khác (CLAUDE.md §10).
"""
import io
import logging

import docx
import pytest
import pytest_asyncio
from sqlalchemy import text

import app.database as csdl
from app.main import fastapi_app
from app.services import council_document_set_service as bo_vb
from app.services import council_set_gate_service as cong
from tests.api import test_council_documents_api as api
from tests.fixtures.hoi_dong_seed import ma_gia, seed_hoi_dong

pytestmark = pytest.mark.integration

P = api.P
SACH = ["dia_chi_rong", "nhieu_nv_khoang_trang", "loai_hinh_chinh_quy"]
ID_KHONG_CO = 2147483000


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


async def _q(sql, **ts):
    async with csdl.engine.connect() as c:
        return (await c.execute(text(sql), ts)).all()


async def _sql(sql, **ts):
    async with csdl.engine.begin() as c:
        await c.execute(text(sql), ts)


async def _so_bo():
    return (await _q("SELECT count(*) FROM council_document_set"))[0][0]


async def _kiem(client, h, pids, nam=2026):
    return await client.post(
        P + "/sets/kiem-truoc",
        json={"academic_year": nam, "profile_ids": list(pids)},
        headers=h,
    )


async def _kiem_ok(client, h, pids, nam=2026):
    r = await _kiem(client, h, pids, nam)
    assert r.status_code == 200, r.text
    return r.json()


async def _dung(client, h, pids, dau, **them):
    return await client.post(
        P + "/sets",
        json=dict(
            {"academic_year": 2026, "profile_ids": list(pids), "phien_ban_kiem": dau},
            **them,
        ),
        headers=h,
    )


def _pids(hs, nhan=SACH):
    return [hs[n][1] for n in nhan]


def _ma_loi(r):
    return r.json().get("ma_loi")


# ═══════════════════════════════ kiểm trước ═══════════════════════════════════════════════
async def test_kiem_truoc_bat_bien_thu_tu_gui_va_khong_ghi(client, hs, ad):
    truoc = await _q(
        "SELECT (SELECT count(*) FROM council_document_set), (SELECT count(*) FROM council_document_event)"
    )
    xuoi = await _kiem_ok(client, ad, _pids(hs))
    nguoc = await _kiem_ok(client, ad, list(reversed(_pids(hs))))
    assert xuoi["phien_ban_kiem"] == nguoc["phien_ban_kiem"]
    assert [d["profile_id"] for d in xuoi["dong"]] == [d["profile_id"] for d in nguoc["dong"]]
    assert sorted(d["profile_id"] for d in xuoi["dong"]) == sorted(_pids(hs))
    assert [d["stt"] for d in xuoi["dong"]] == [1, 2, 3]
    assert xuoi["khong_tim_thay"] == [] and xuoi["tom_tat"]["tong"] == 3
    assert xuoi["tom_tat"]["du_kien_so_tep"] == 2 + 2 * xuoi["tom_tat"]["so_nhom"]
    assert await _q(
        "SELECT (SELECT count(*) FROM council_document_set), (SELECT count(*) FROM council_document_event)"
    ) == truoc


async def test_kiem_truoc_id_vuot_int32_400_khong_500(client, hs, ad):
    # Review max PR #724 (dưới ngưỡng): id vượt int4 ⇒ 400 có số dòng, không 500 ở câu SQL ``CAST(... integer[])``.
    r = await _kiem(client, ad, _pids(hs) + [2147483648])
    assert r.status_code == 400 and "Dòng 4" in r.json()["detail"], r.text


async def test_kiem_truoc_phan_hoi_no_store(client, hs, ad):
    r = await _kiem(client, ad, _pids(hs))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"


async def test_kiem_truoc_dong_bi_chan_mang_ma_va_cau_cua_cong(client, hs, ad):
    kq = await _kiem_ok(client, ad, _pids(hs, SACH + ["khong_khu_vuc"]))
    dong = {d["profile_id"]: d for d in kq["dong"]}[hs["khong_khu_vuc"][1]]
    assert dong["muc"] == "bi_chan" and dong["ly_do"]
    assert all(x["cau"] == cong.BLOCK_REASONS[x["ma"]] for x in dong["ly_do"])
    assert kq["tom_tat"]["bi_chan"] == 1


@pytest.mark.parametrize("cccd", [None, ""], ids=["null", "chuoi_rong"])
async def test_kiem_truoc_cccd_trong_chi_chan_dong_ay(client, hs, ad, cccd):
    # Review max PR #724 (R5) — trước đây CCCD trống làm _to_dto ném ⇒ CẢ bản xem trước 400. Nay: 200, đúng
    # dòng ấy bị chặn mã ``thieu_ma_ho_so`` (câu thật của cổng), các dòng khác không mang mã ấy.
    pid = hs["dia_chi_rong"][1]
    await _sql("UPDATE admission_profile SET citizen_id = :c WHERE id = :p", c=cccd, p=pid)
    kq = await _kiem_ok(client, ad, _pids(hs))
    dong = {d["profile_id"]: d for d in kq["dong"]}
    ma = {x["ma"]: x["cau"] for x in dong[pid]["ly_do"]}
    assert dong[pid]["muc"] == "bi_chan" and ma.get("thieu_ma_ho_so") == cong.BLOCK_REASONS["thieu_ma_ho_so"], dong[pid]
    assert all("thieu_ma_ho_so" not in {x["ma"] for x in d["ly_do"]} for p, d in dong.items() if p != pid)


async def test_dung_bo_cccd_trong_400_khong_ghi(client, hs, ad):
    # R5 — dòng thiếu CCCD KHÔNG bao giờ được in: dấu khớp vẫn qua cổng chặn ⇒ 400 liệt kê dòng, 0 bộ.
    pid = hs["dia_chi_rong"][1]
    await _sql("UPDATE admission_profile SET citizen_id = NULL WHERE id = :p", p=pid)
    kq = await _kiem_ok(client, ad, _pids(hs))
    r = await _dung(client, ad, [d["profile_id"] for d in kq["dong"]], kq["phien_ban_kiem"])
    assert r.status_code == 400 and r.json()["kiem_tra_dung_bo"]["muc"] == "chan", r.text
    assert await _so_bo() == 0


async def _xa_trung(pid):
    """Hai xã HIỆN HÀNH cùng mã (``administrative_nodes.code`` không UNIQUE), khác tỉnh ⇒ số liệu in của hồ sơ ``pid``
    khớp HAI hàng tham chiếu (địa chỉ khác nhau)."""
    await _sql("UPDATE admission_profile SET permanent_commune_code = 'GIA9901' WHERE id = :p", p=pid)
    for xa, tinh, ten_tinh in (("Xã Giả Một", "GT991", "Tỉnh Giả Một"), ("Xã Giả Hai", "GT992", "Tỉnh Giả Hai")):
        await _sql(
            "INSERT INTO administrative_nodes (code, name, level, path, province_code, valid_from, is_active) "
            "VALUES ('GIA9901', :x, 'WARD', :pa, :t, DATE '2020-01-01', true)",
            x=xa, pa="/gia/" + tinh + "/GIA9901", t=tinh,
        )
        await _sql(
            "INSERT INTO administrative_nodes (code, name, level, path, province_code, valid_from, is_active) "
            "VALUES (:t, :n, 'PROVINCE', :pa, :t, DATE '2020-01-01', true)",
            t=tinh, n=ten_tinh, pa="/gia/" + tinh,
        )


async def test_kiem_truoc_tham_chieu_trung_chi_chan_dong_ay_id_loc_dung_truoc(client, hs, ad):
    # Codex 42 F334 (nhánh anh em của R5) — trước đây CẢ bản xem trước 400 "Dòng N: … khớp nhiều hàng", N đếm SAU khi
    # lọc (id không có đứng trước ⇒ sai dòng). Nay: 200, id không có ở VỊ TRÍ ĐẦU VÀO 1, đúng hồ sơ ấy (theo
    # profile_id) bị chặn ``tham_chieu_trung``, dòng khác không mang mã ấy; dựng bộ từ chối, 0 bộ.
    pid = _pids(hs)[-1]  # hồ sơ CUỐI: số dòng sau lọc ≠ vị trí đầu vào
    await _xa_trung(pid)
    pids = [2147480000] + _pids(hs)  # id KHÔNG CÓ đứng trước
    assert pids.index(pid) >= 2
    kq = await _kiem_ok(client, ad, pids)
    assert kq["khong_tim_thay"] == [1], kq["khong_tim_thay"]
    dong = {d["profile_id"]: d for d in kq["dong"]}
    ma = {x["ma"]: x["cau"] for x in dong[pid]["ly_do"]}
    assert dong[pid]["muc"] == "bi_chan" and ma.get("tham_chieu_trung") == cong.BLOCK_REASONS["tham_chieu_trung"], dong[pid]
    assert all("tham_chieu_trung" not in {x["ma"] for x in d["ly_do"]} for p, d in dong.items() if p != pid)
    r = await _dung(client, ad, [d["profile_id"] for d in kq["dong"]], kq["phien_ban_kiem"])
    assert r.status_code == 400 and r.json()["kiem_tra_dung_bo"]["muc"] == "chan", r.text
    assert await _so_bo() == 0


async def test_kiem_truoc_van_hoa_trong_chan_dong_ay(client, hs, ad):
    # Review max PR #724 (R10): bước dựng dừng khi trình độ văn hoá rỗng; trước đây bản xem trước vẫn báo "được dựng"
    # (kèm dấu hợp lệ) cho dòng ấy. Nay: dòng ấy mang mã chặn ``du_lieu_van_hoa_la``, các dòng khác không mang mã ấy.
    # (Đổi văn hoá còn làm khu vực tính lại khác ảnh chụp ⇒ dòng cũng có mã của cổng — bất biến kiểm ở đây là MÃ dữ liệu.)
    from app.services.council_document_render_service import ROW_DATA_ERROR_REASONS

    pid = hs["dia_chi_rong"][1]
    await _sql("UPDATE admission_profile SET cultural_education_level = NULL WHERE id = :p", p=pid)
    kq = await _kiem_ok(client, ad, _pids(hs))
    dong = {d["profile_id"]: d for d in kq["dong"]}
    ma = {x["ma"]: x["cau"] for x in dong[pid]["ly_do"]}
    assert dong[pid]["muc"] == "bi_chan" and ma.get("du_lieu_van_hoa_la") == ROW_DATA_ERROR_REASONS["du_lieu_van_hoa_la"], dong[pid]
    assert all("du_lieu_van_hoa_la" not in {x["ma"] for x in d["ly_do"]} for p, d in dong.items() if p != pid)


async def _xoa_ma_nganh_cua(pid):
    await _sql(
        "UPDATE major_program SET code = '' WHERE id = (SELECT resolved_major_id FROM fee WHERE admission_profile_id = :p "
        "AND fee_type = 'tuition' AND status <> 'cancelled' AND semester_no = 1 ORDER BY id DESC LIMIT 1)",
        p=pid,
    )


async def test_kiem_truoc_nhom_thieu_ma_nganh_chan_ca_nhom(client, hs, ad):
    # R10 — phép kiểm theo NHÓM (ngành, trình độ) của bước dựng: mã ngành rỗng ⇒ MỌI dòng của nhóm bị chặn.
    pid = hs["dia_chi_rong"][1]
    await _xoa_ma_nganh_cua(pid)
    kq = await _kiem_ok(client, ad, _pids(hs))
    dong = {d["profile_id"]: d for d in kq["dong"]}
    nhom = (dong[pid]["nganh_nhan"], dong[pid]["trinh_do"])
    cung = [d for d in dong.values() if (d["nganh_nhan"], d["trinh_do"]) == nhom]
    assert cung and all(
        d["muc"] == "bi_chan" and "du_lieu_thieu_ma_nganh" in {x["ma"] for x in d["ly_do"]} for d in cung
    ), cung


async def test_dung_bo_sau_kiem_truoc_loi_du_lieu_400_dung_ly_do(client, hs, ad):
    # R10 — dấu kiểm trước KHỚP ở hai phía (cùng ``chuan_hoa``) ⇒ dựng bị từ chối vì CHÍNH lỗi dữ liệu (câu của bước
    # dựng "Thiếu mã ngành"), không phải 409 "dữ liệu đã đổi từ lúc kiểm"; 0 bộ. Dùng mã ngành rỗng (không đụng cổng —
    # văn hoá rỗng làm cổng chặn trước, hai bất biến).
    pid = hs["dia_chi_rong"][1]
    await _xoa_ma_nganh_cua(pid)
    kq = await _kiem_ok(client, ad, _pids(hs))
    r = await _dung(client, ad, [d["profile_id"] for d in kq["dong"]], kq["phien_ban_kiem"])
    assert r.status_code == 400 and "Thiếu mã ngành" in r.json().get("detail", ""), r.text
    assert await _so_bo() == 0


async def test_kiem_truoc_khong_nap_do_thi_ho_so(client, hs, ad):
    # Review max PR #724 (R6): tra khu vực từng dòng (``_tra_khu_vuc``) nạp hồ sơ CHỈ CỘT — trước đây ``phien.get`` kéo cả
    # đồ thị quan hệ nạp sẵn (học phí → hoá đơn → phiếu thu, giấy tờ, điểm…) cho MỖI dòng. Bất biến: bản xem trước KHÔNG
    # đọc bảng hoá đơn / phiếu thu (truy vấn đọc của bộ dựng không cần hai bảng ấy).
    import re

    from sqlalchemy import event

    cau = []

    def ghi(conn, cursor, stmt, params, context, executemany):
        cau.append(stmt)

    event.listen(csdl.engine.sync_engine, "before_cursor_execute", ghi)
    try:
        kq = await _kiem_ok(client, ad, _pids(hs))
    finally:
        event.remove(csdl.engine.sync_engine, "before_cursor_execute", ghi)
    assert kq["dong"]
    bang = sorted({m.group(1) for s in cau for m in re.finditer(r"\bFROM (\w+)", s)})
    print("SO_CAU_SQL_KIEM_TRUOC=%d BANG=%s" % (len(cau), ",".join(bang)))
    assert not {"invoice", "payment"} & set(bang), bang


async def test_kiem_truoc_gop_khong_co_khac_nam_mot_danh_sach(client, hs, ad):
    # Năm khác ⇒ mọi vị trí "không tìm thấy" — như id không tồn tại (không phân biệt).
    kq = await _kiem_ok(client, ad, _pids(hs, SACH[:1]) + [ID_KHONG_CO], nam=2027)
    assert kq["khong_tim_thay"] == [1, 2] and kq["dong"] == []
    kq = await _kiem_ok(client, ad, _pids(hs, SACH[:1]) + [ID_KHONG_CO])
    assert kq["khong_tim_thay"] == [2] and len(kq["dong"]) == 1


def _cho_quan_ly_qua_casbin(monkeypatch):
    """Casbin GIẢ cho quản lý qua mọi route của module (Casbin thật KHÔNG có dòng cho các route này) ⇒ đo được
    lớp phạm vi đơn vị ở deps + service."""
    enf = fastapi_app.state.enforcer
    goc = enf.enforce

    def enforce(sub, obj, act, *them):
        if sub == "role:manager" and obj.startswith(P):
            return True
        return goc(sub, obj, act, *them)

    monkeypatch.setattr(enf, "enforce", enforce)


async def test_kiem_truoc_quan_ly_ngoai_don_vi_nhu_khong_co(client, hs, tk, monkeypatch):
    # Hồ sơ đơn vị khác và id không có ra CÙNG một danh sách vị trí (không lộ tồn tại).
    _cho_quan_ly_qua_casbin(monkeypatch)
    h = await tk("ql_u1")
    kq = await _kiem_ok(
        client, h, [hs[SACH[0]][1], hs["don_vi_khac"][1], ID_KHONG_CO]
    )
    assert kq["khong_tim_thay"] == [2, 3]
    assert [d["profile_id"] for d in kq["dong"]] == [hs[SACH[0]][1]]
    assert kq["tom_tat"]["nguoi_goi_duoc_xac_nhan"] is False


async def test_kiem_truoc_quan_ly_casbin_that_bi_chan(client, hs, tk):
    r = await _kiem(client, await tk("ql_u1"), _pids(hs))
    assert r.status_code == 403, r.text


# ═══════════════════════════════ POST /sets dạng id ═══════════════════════════════════════
async def test_dung_theo_id_dung_thu_tu_kiem_truoc(client, hs, ad):
    # pbk_dau_vao_chua_sap: gửi kiểm trước NGƯỢC ⇒ nhận thứ tự chuẩn ⇒ dựng thành công, dòng bộ theo đúng thứ tự ấy.
    kq = await _kiem_ok(client, ad, list(reversed(_pids(hs))))
    thu_tu = [d["profile_id"] for d in kq["dong"]]
    r = await _dung(client, ad, thu_tu, kq["phien_ban_kiem"])
    assert r.status_code == 201, r.text
    dong = await _q(
        "SELECT profile_id FROM council_document_set_row WHERE set_id = :s ORDER BY stt",
        s=r.json()["id"],
    )
    assert [x[0] for x in dong] == thu_tu


async def test_thu_tu_dong_bo_khop_quyet_dinh_da_dung(client, hs, ad):
    # Đặc tả 3.3 (test khoá): thứ tự dòng bộ = thứ tự người trên tệp Quyết định đã dựng (đọc từ bytes đã lưu).
    kq = await _kiem_ok(client, ad, _pids(hs))
    r = await _dung(client, ad, [d["profile_id"] for d in kq["dong"]], kq["phien_ban_kiem"])
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    # Mã hồ sơ (CCCD GIẢ) có ô riêng trên bảng Quyết định và duy nhất ⇒ định vị từng người bằng nó.
    ma = [
        x[0]
        for x in await _q(
            "SELECT s.snapshot_dto -> (r.stt - 1) ->> 'ma_ho_so' FROM council_document_set s "
            "JOIN council_document_set_row r ON r.set_id = s.id WHERE s.id = :s ORDER BY r.stt",
            s=sid,
        )
    ]
    cccd_cua = {hs[n][1]: hs[n][0] for n in SACH}
    assert ma == [cccd_cua[d["profile_id"]] for d in kq["dong"]]
    tep = (
        await _q(
            "SELECT noi_dung FROM council_document_set_file WHERE set_id = :s AND path LIKE 'HoiDong/QuyetDinh%'",
            s=sid,
        )
    )[0][0]
    van_ban = "\n".join(
        o.text
        for bang in docx.Document(io.BytesIO(bytes(tep))).tables
        for hang in bang.rows
        for o in hang.cells
    )
    vi_tri = [van_ban.find(m) for m in ma]
    assert all(v >= 0 for v in vi_tri)
    assert vi_tri == sorted(vi_tri)


async def test_thu_tu_gui_khac_thu_tu_chuan_409(client, hs, ad):
    # pbk_thu_tu_gui_khac
    kq = await _kiem_ok(client, ad, _pids(hs))
    thu_tu = [d["profile_id"] for d in kq["dong"]]
    r = await _dung(client, ad, [thu_tu[1], thu_tu[0], thu_tu[2]], kq["phien_ban_kiem"])
    assert r.status_code == 409 and _ma_loi(r) == bo_vb.CHANGED_SINCE_CHECK_ERROR_CODE, r.text
    assert await _so_bo() == 0


async def test_doi_ho_giu_ten_sau_kiem_truoc_409(client, hs, ad):
    # pbk_doi_ho (ca F266): thêm một chữ ĐẦU họ tên ⇒ họ đổi, tên (chữ cuối) giữ.
    kq = await _kiem_ok(client, ad, _pids(hs))
    thu_tu = [d["profile_id"] for d in kq["dong"]]
    await _sql(
        "UPDATE admission_profile SET full_name = 'Zzz ' || full_name WHERE id = :p", p=thu_tu[0]
    )
    r = await _dung(client, ad, thu_tu, kq["phien_ban_kiem"])
    assert r.status_code == 409 and _ma_loi(r) == bo_vb.CHANGED_SINCE_CHECK_ERROR_CODE, r.text
    assert await _so_bo() == 0


async def test_doi_truong_ngoai_anh_chup_van_dung_duoc(client, hs, ad):
    # pbk_doi_truong_ngoai_anh (đối chứng): ``admission_profile.updated_at`` không thuộc ``CandidateRowV1`` /
    # ``CheckData`` ⇒ dấu không đổi ⇒ dựng được.
    kq = await _kiem_ok(client, ad, _pids(hs))
    thu_tu = [d["profile_id"] for d in kq["dong"]]
    await _sql(
        "UPDATE admission_profile SET updated_at = updated_at + interval '1 day' WHERE id = :p",
        p=thu_tu[0],
    )
    r = await _dung(client, ad, thu_tu, kq["phien_ban_kiem"])
    assert r.status_code == 201, r.text


async def test_doi_khoa_hmac_thi_dau_cu_409(client, hs, ad, monkeypatch):
    kq = await _kiem_ok(client, ad, _pids(hs))
    monkeypatch.setattr(bo_vb.settings, "SECRET_KEY", "khoa-da-xoay-cho-test")
    r = await _dung(client, ad, [d["profile_id"] for d in kq["dong"]], kq["phien_ban_kiem"])
    assert r.status_code == 409 and _ma_loi(r) == bo_vb.CHANGED_SINCE_CHECK_ERROR_CODE, r.text


async def test_dung_theo_id_doc_ho_so_dung_mot_lan(client, hs, ad, monkeypatch):
    # pbk_mot_lan_doc: từ lúc đọc tới lúc ghi không đọc hồ sơ lần nào nữa (đếm MỌI hàm đọc của tầng đọc).
    kq = await _kiem_ok(client, ad, _pids(hs))
    dem = {"theo_id": 0, "theo_ma": 0, "kiem_truoc": 0}

    def boc(ten, f):
        async def g(*a, **k):
            dem[ten] += 1
            return await f(*a, **k)

        return g

    monkeypatch.setattr(bo_vb._candidate_service, "read_profiles_by_id", boc("theo_id", bo_vb._candidate_service.read_profiles_by_id))
    monkeypatch.setattr(bo_vb, "read_profiles_by_code", boc("theo_ma", bo_vb.read_profiles_by_code))
    monkeypatch.setattr(
        bo_vb._candidate_service, "read_profiles_for_preview", boc("kiem_truoc", bo_vb._candidate_service.read_profiles_for_preview)
    )
    r = await _dung(client, ad, [d["profile_id"] for d in kq["dong"]], kq["phien_ban_kiem"])
    assert r.status_code == 201, r.text
    assert dem == {"theo_id": 1, "theo_ma": 0, "kiem_truoc": 0}


async def test_dau_khop_van_qua_cong_chan(client, hs, ad):
    # Dấu khớp KHÔNG gỡ cổng: dòng bị chặn ⇒ 400 liệt kê từng dòng, 0 bộ.
    kq = await _kiem_ok(client, ad, _pids(hs, SACH + ["khong_khu_vuc"]))
    r = await _dung(client, ad, [d["profile_id"] for d in kq["dong"]], kq["phien_ban_kiem"])
    assert r.status_code == 400 and r.json()["kiem_tra_dung_bo"]["muc"] == "chan", r.text
    assert await _so_bo() == 0


@pytest.mark.parametrize(
    "than",
    [
        {"ma_ho_so": ["000000000001"], "profile_ids": [1], "phien_ban_kiem": "x"},
        {"profile_ids": [1]},
        {"phien_ban_kiem": "x"},
        {},
    ],
    ids=["ca_hai_dang", "thieu_dau", "thieu_id", "khong_dang_nao"],
)
async def test_post_sets_dung_mot_dang(client, hs, ad, than):
    r = await client.post(P + "/sets", json=dict(than, academic_year=2026), headers=ad)
    assert r.status_code == 422, r.text
    assert await _so_bo() == 0


# ═══════════════════════════════ đổi mã ════════════════════════════════════════════════════
async def test_doi_ma_moi_dong_loi_chi_so_dong(client, hs, ad):
    ma = [
        hs[SACH[0]][0],
        "   ",
        hs[SACH[0]][0],
        "12345",
        ma_gia(990001),
        hs[SACH[1]][0],
    ]
    r = await client.post(
        P + "/sets/doi-ma", json={"academic_year": 2026, "ma_ho_so": ma}, headers=ad
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "profile_ids": [hs[SACH[0]][1], hs[SACH[1]][1]],
        "dong_loi": [
            {"dong": 2, "ly_do": "rong"},
            {"dong": 3, "ly_do": "trung"},
            {"dong": 4, "ly_do": "sai_dinh_dang"},
            {"dong": 5, "ly_do": "khong_khop"},
        ],
    }
    assert not any(m.strip() and m in r.text for m in ma)
    assert r.headers["cache-control"] == "no-store"


async def test_doi_ma_quan_ly_ngoai_don_vi_nhu_khong_khop(client, hs, tk, monkeypatch):
    _cho_quan_ly_qua_casbin(monkeypatch)
    r = await client.post(
        P + "/sets/doi-ma",
        json={"academic_year": 2026, "ma_ho_so": [hs[SACH[0]][0], hs["don_vi_khac"][0]]},
        headers=await tk("ql_u1"),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "profile_ids": [hs[SACH[0]][1]],
        "dong_loi": [{"dong": 2, "ly_do": "khong_khop"}],
    }


# ═══════════════════════════════ tìm hồ sơ ══════════════════════════════════════════════════
async def test_tim_ho_so_khong_log_tu_khoa(client, hs, ad, caplog, capsys):
    # Mức DEBUG chỉ cho cây logger ``app`` (router + service): bật ở gốc thì SQLAlchemy log cả tham số câu SQL —
    # thứ production không bật — và ca đỏ vì lý do khác.
    caplog.set_level(logging.DEBUG, logger="app")
    cccd = hs[SACH[0]][0]
    r = await client.post(
        P + "/sets/tim-ho-so",
        json={"academic_year": 2026, "tu_khoa": cccd, "page": 1, "page_size": 10},
        headers=ad,
    )
    assert r.status_code == 200, r.text
    dong = r.json()["dong"]
    assert [d["profile_id"] for d in dong] == [hs[SACH[0]][1]]
    assert dong[0]["cccd"] == cccd and dong[0]["academic_year"] == 2026
    assert r.headers["cache-control"] == "no-store"
    assert cccd not in str(r.request.url)
    ra = capsys.readouterr()
    assert cccd not in caplog.text + repr([x.__dict__ for x in caplog.records]) + ra.out + ra.err


async def test_tim_ho_so_loc_trang_thai_la_400(client, hs, ad):
    r = await client.post(
        P + "/sets/tim-ho-so",
        json={"academic_year": 2026, "trang_thai": ["khong_co_trang_thai_nay"]},
        headers=ad,
    )
    assert r.status_code == 400, r.text


async def test_tim_ho_so_quan_ly_casbin_that_bi_chan(client, hs, tk):
    r = await client.post(
        P + "/sets/tim-ho-so", json={"academic_year": 2026}, headers=await tk("ql_u1")
    )
    assert r.status_code == 403, r.text
