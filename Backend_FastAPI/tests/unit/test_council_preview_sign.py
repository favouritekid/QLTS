# -*- coding: utf-8 -*-
"""Vòng giao diện (đặc tả 3.1 + bản 2/3 mục 3.1.1) — dấu kiểm trước + thứ tự chuẩn: HÀM THUẦN, không CSDL.

Mỗi ca một bất biến (CLAUDE.md §3):

* dấu NHẠY với phần dữ liệu in (đổi họ, giữ tên — ca F266), với dữ liệu kiểm ngoài ảnh in (khoá đếm
  ``nv_in_offering_id``), với kết quả cổng (mức / mã lý do), với năm học và với khoá HMAC;
* dấu KHÔNG nhạy với vị trí đầu vào (``DuLieuKiem.stt`` + thứ tự dòng đưa vào) — ca ``pbk_dau_bat_bien_thu_tu_vao``
  ở mức hàm;
* thứ tự chuẩn: nhóm (ngành, trình độ) → điểm giảm → tên → id hồ sơ (phá hoà, ca ``pbk_hoa_diem_ten``);
* MỘT nguồn khoá sắp: bộ dựng gọi đúng hai hàm khoá chung, không còn biểu thức sắp riêng.
"""
import dataclasses
import inspect
import re
from datetime import datetime, timezone

import pytest

from app.repositories.council_candidate_repository import ThongTinGiaoDich
from app.services import council_document_render_service as bo_dung
from app.services import council_document_set_service as bo_vb
from app.services import council_set_gate_service as cong
from app.services.council_candidate_service import AnhChupHoSo

pytestmark = pytest.mark.unit

GD = ThongTinGiaoDich("repeatable read", "on", datetime(2026, 11, 11, tzinfo=timezone.utc), 1)


def _hang(**kw) -> bo_dung.CandidateRowV1:
    gia_tri = {t: "" for t in bo_dung.CANDIDATE_FIELDS}
    gia_tri.update(
        ma_ho_so="000000000001",
        ho="Họ Giả",
        ten="An",
        nganh="Công nghệ ô tô",
        trinh_do="Cao đẳng",
        tong_diem="18.00",
        diem_kv="0.25",
        diem_ut="0",
    )
    gia_tri.update(kw)
    return bo_dung.CandidateRowV1(**gia_tri)


def _kiem(stt: int, **kw) -> cong.DuLieuKiem:
    gia_tri = dict(
        stt=stt,
        status="approved",
        uses_choice_engine=True,
        so_nv=1,
        nv1_id=10,
        nv_in_id=10,
        so_nv_trung=0,
        nv_trung_id=None,
        hp_co=True,
        hp_nganh_id=5,
        nv_in_nganh_id=5,
        nv_in_path_id=7,
        nv_in_sg_id=3,
        lg_nganh_id=None,
        lg_path_id=None,
        lg_sg_id=None,
        diem_ca_hai_khac=0,
        diem_chi_nv=0,
        diem_chi_hs=0,
        kv_ly_do=None,
        kv_muc="0.25",
        luat_kv=cong.LUAT_KV_CONG,
        luat_ut=cong.LUAT_KV_CONG,
        nv_in_ai_id=11,
        nv_in_offering_id=12,
    )
    gia_tri.update(kw)
    return cong.DuLieuKiem(**gia_tri)


def _anh(dong):
    """``dong`` = [(pid, hàng, dữ liệu kiểm KHÔNG có stt)] theo thứ tự ĐẦU VÀO — ``stt`` = vị trí (1…)."""
    return AnhChupHoSo(
        rows=tuple(h for _, h, _ in dong),
        don_vi=tuple(1 for _ in dong),
        giao_dich=GD,
        kiem=tuple(dataclasses.replace(k, stt=i) for i, (_, _, k) in enumerate(dong, 1)),
        pids=tuple(p for p, _, _ in dong),
    )


def _dau(anh, nam=2026):
    return bo_vb.dau_kiem_truoc(bo_vb.chuan_hoa(anh, cong.danh_gia(anh.kiem)), nam)


A = (101, _hang(ten="An", tong_diem="18.00"), _kiem(0))
B = (102, _hang(ma_ho_so="000000000002", ten="Bình", tong_diem="20.00"), _kiem(0))
C = (103, _hang(ma_ho_so="000000000003", ten="Chi", nganh="Điện", tong_diem="10.00"), _kiem(0))


def test_dau_la_hmac_hex_64():
    assert re.fullmatch(r"[0-9a-f]{64}", _dau(_anh([A, B, C])))


def test_dau_bat_bien_thu_tu_dau_vao():
    # pbk_dau_bat_bien_thu_tu_vao (mức hàm): cùng dữ liệu, ba thứ tự đầu vào ⇒ một dấu + một thứ tự chuẩn.
    ds = [_anh(x) for x in ([A, B, C], [C, B, A], [B, C, A])]
    assert len({_dau(a) for a in ds}) == 1
    thu_tu = {
        tuple(d.pid for d in bo_vb.chuan_hoa(a, cong.danh_gia(a.kiem))) for a in ds
    }
    # Nhóm "Công nghệ ô tô" < "Điện" (chữ); trong nhóm điểm giảm: Bình 20 trước An 18.
    assert thu_tu == {(102, 101, 103)}


def test_dau_nhay_voi_ho_giu_ten():
    # pbk_doi_ho (mức hàm — ca F266): đổi HỌ, giữ tên / điểm / ngành ⇒ dấu đổi.
    doi = (A[0], A[1].model_copy(update={"ho": "Họ Khác"}), A[2])
    assert _dau(_anh([A, B])) != _dau(_anh([doi, B]))


def test_dau_nhay_voi_khoa_dem_ngoai_anh_in():
    # pbk_doi_khoa_dem (mức hàm): đổi khoá đếm của NV in (không có trong ảnh in, không đổi cổng) ⇒ dấu đổi.
    doi = (A[0], A[1], dataclasses.replace(A[2], nv_in_offering_id=99))
    a1, a2 = _anh([A, B]), _anh([doi, B])
    assert cong.danh_gia(a1.kiem).chan == cong.danh_gia(a2.kiem).chan == ()
    assert _dau(a1) != _dau(a2)


def test_dau_nhay_voi_muc_cong():
    # pbk_doi_trang_thai_cung_muc (mức hàm): approved → admitted, cùng mức "không cảnh báo" ⇒ dấu VẪN đổi
    # (trạng thái thuộc dữ liệu kiểm); approved → submitted (cảnh báo) ⇒ đổi mức.
    cung_muc = (A[0], A[1], dataclasses.replace(A[2], status="admitted"))
    assert _dau(_anh([A, B])) != _dau(_anh([cung_muc, B]))
    canh_bao = (A[0], A[1], dataclasses.replace(A[2], status="submitted"))
    dc = bo_vb.chuan_hoa(_anh([canh_bao, B]), cong.danh_gia(_anh([canh_bao, B]).kiem))
    assert {d.pid: d.muc for d in dc}[101] == bo_vb.MUC_CAN_XAC_NHAN


def test_dau_nhay_voi_nam_va_khoa_hmac(monkeypatch):
    a = _anh([A, B])
    goc = _dau(a)
    assert _dau(a, nam=2027) != goc
    monkeypatch.setattr(bo_vb.settings, "SECRET_KEY", "khoa-khac-cho-test")
    assert _dau(a) != goc


def test_thu_tu_pha_hoa_bang_id_ho_so():
    # pbk_hoa_diem_ten (mức hàm): cùng nhóm, cùng điểm, cùng TÊN ⇒ id hồ sơ tăng — bất kể thứ tự đầu vào.
    x = (205, _hang(ma_ho_so="000000000005", ten="An", tong_diem="18.00"), _kiem(0))
    y = (204, _hang(ma_ho_so="000000000004", ten="An", tong_diem="18.00"), _kiem(0))
    for dong in ([x, y], [y, x]):
        a = _anh(dong)
        assert [d.pid for d in bo_vb.chuan_hoa(a, cong.danh_gia(a.kiem))] == [204, 205]


def test_dong_bi_chan_van_sap_duoc_va_mang_ma_ly_do():
    chan = (106, _hang(ma_ho_so="000000000006", ten="Dũng"), _kiem(0, hp_co=False))
    a = _anh([A, chan])
    dc = {d.pid: d for d in bo_vb.chuan_hoa(a, cong.danh_gia(a.kiem))}
    assert dc[106].muc == bo_vb.MUC_BI_CHAN and "thieu_hoc_phi_hk1" in dc[106].ma_ly_do
    assert dc[101].muc == bo_vb.MUC_DUOC_DUNG and dc[101].ma_ly_do == ()


def test_bo_dung_dung_mot_nguon_khoa_sap():
    # MỘT nguồn (CLAUDE.md §7): mọi chỗ sắp trong nhóm của bộ dựng gọi hàm khoá chung; không còn biểu thức
    # sắp "-…tong_xt" viết tay; khoá nhóm của hồ sơ đã chuẩn bị đi qua hàm chung.
    nguon = inspect.getsource(bo_dung)
    assert nguon.count("khoa_trong_nhom_quyet_dinh(h.diem.tong_xt, h.dto.ten)") == 2
    assert not re.search(r"key=lambda h: \(-h\.diem\.tong_xt", nguon)
    assert "return khoa_nhom_quyet_dinh(self.dto)" in inspect.getsource(bo_dung._HoSo)
