# -*- coding: utf-8 -*-
"""Cổng dựng bộ văn bản Hội đồng (lượt G — owner 05-11: F228, F229, F231) — phần THUẦN (không
CSDL): ba mức trạng thái phủ ĐỦ 15 trạng thái của app, luật từng dòng, luật xác nhận.

Mỗi ca "một lý do" vi phạm ĐÚNG MỘT bất biến trên một dòng SẠCH (CLAUDE.md §3); ca CSDL thật ở
``tests/integration/test_council_set_gate_db.py``, ca qua API ở
``tests/api/test_council_documents_gate_api.py``.
"""
import dataclasses
import re

import pytest

from app.models.admission import AdmissionProfile
from app.services import council_set_gate_service as cong
from app.services.admission_state_machine import ALLOWED_TRANSITIONS, AdmissionStatus
from app.utils.exceptions import (
    ConflictError,
    DataValidationError,
    PermissionDeniedError,
)

pytestmark = pytest.mark.unit


def _trang_thai_cua_check():
    """15 trạng thái đọc từ CHÍNH chuỗi CHECK ``ck_admission_profile_status`` của model."""
    ck = [
        c
        for c in AdmissionProfile.__table__.constraints
        if getattr(c, "name", None) == "ck_admission_profile_status"
    ]
    assert len(ck) == 1
    return set(re.findall(r"'([a-z_]+)'", str(ck[0].sqltext)))


# ═══════════════════════════════ F228 — ba mức phủ đủ 15 trạng thái ═══════════════════════
def test_ba_muc_dung_nguyen_van_owner_05_11():
    assert cong.TRANG_THAI_CHAN == {"draft", "rejected", "withdrawal_pending", "withdrawn"}
    assert cong.TRANG_THAI_CANH_BAO == {
        "submitted",
        "resubmitted",
        "reviewing",
        "revision_requested",
        "waitlisted",
        "result_published",
    }
    assert cong.TRANG_THAI_KHONG_CANH_BAO == {
        "approved",
        "admitted",
        "confirmed",
        "enrolled",
        "overridden",
    }


def test_ba_muc_roi_nhau_va_phu_dung_15_trang_thai_cua_check_enum_va_bang_chuyen():
    ba = (cong.TRANG_THAI_CHAN, cong.TRANG_THAI_CANH_BAO, cong.TRANG_THAI_KHONG_CANH_BAO)
    hop = set().union(*ba)
    assert sum(len(t) for t in ba) == len(hop) == 15  # rời nhau
    tu_check = _trang_thai_cua_check()
    tu_enum = {s.value for s in AdmissionStatus}
    tu_bang = {s.value for s in ALLOWED_TRANSITIONS} | {
        d.value for dich in ALLOWED_TRANSITIONS.values() for d in dich
    }
    assert hop == tu_check == tu_enum == tu_bang


@pytest.mark.parametrize("s", sorted(cong.TRANG_THAI_CHAN))
def test_muc_chan(s):
    assert cong.muc_trang_thai(s) == cong.MUC_CHAN


@pytest.mark.parametrize("s", sorted(cong.TRANG_THAI_CANH_BAO))
def test_muc_canh_bao(s):
    assert cong.muc_trang_thai(s) == cong.MUC_CANH_BAO


@pytest.mark.parametrize("s", sorted(cong.TRANG_THAI_KHONG_CANH_BAO))
def test_muc_khong(s):
    assert cong.muc_trang_thai(s) == cong.MUC_KHONG


@pytest.mark.parametrize(
    "s", ["trang_thai_moi_sau_nay", "Approved", " approved", "", None, 1, ["approved"]]
)
def test_trang_thai_la_thi_chan_fail_closed(s):
    assert cong.muc_trang_thai(s) == cong.MUC_CHAN


# ═══════════════════════════════ F229 / F231 — luật từng dòng ═════════════════════════════
def _sach(**kw):
    """Một dòng SẠCH của hồ sơ bộ máy nguyện vọng: NV1 id 11 được in, ngành 5, học phí ngành 5,
    khu vực có mức."""
    goc = dict(
        stt=1,
        status="approved",
        uses_choice_engine=True,
        so_nv=2,
        nv1_id=11,
        nv_in_id=11,
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
        kv_muc="0.75",
    )
    goc.update(kw)
    return cong.DuLieuKiem(**goc)


def _sach_mot_nv(**kw):
    """Dòng SẠCH của hồ sơ một nguyện vọng kiểu cũ: một dòng nguyện vọng khớp cấu hình hồ sơ."""
    goc = dict(
        uses_choice_engine=False,
        so_nv=1,
        lg_nganh_id=5,
        lg_path_id=7,
        lg_sg_id=3,
    )
    goc.update(kw)
    return _sach(**goc)


def test_dong_sach_khong_ly_do():
    assert cong.ly_do_cua_dong(_sach()) == []
    assert cong.ly_do_cua_dong(_sach_mot_nv()) == []


@pytest.mark.parametrize(
    "sua, ma",
    [
        (dict(uses_choice_engine=None), "luong_khong_xac_dinh"),
        (dict(uses_choice_engine=1), "luong_khong_xac_dinh"),  # 1 KHÔNG phải bool
        (dict(so_nv=0, nv1_id=None, nv_in_id=None, nv_in_nganh_id=None), "nhieu_nv_khong_co_nv"),
        (dict(nv_in_id=None, nv_in_nganh_id=None), "nv1_thieu_cau_hinh"),
        (dict(nv_in_id=12), "nv_in_khac_nv1"),
        (dict(so_nv_trung=1, nv_trung_id=12), "trung_nv_khac"),
        (dict(so_nv_trung=2, nv_trung_id=11), "nhieu_nv_trung"),
        (dict(diem_ca_hai_khac=1), "diem_hai_nguon_khac"),
        (dict(hp_co=False, hp_nganh_id=None), "thieu_hoc_phi_hk1"),
        (dict(hp_nganh_id=None), "hoc_phi_chua_gan_nganh"),
        (dict(hp_nganh_id=6), "hoc_phi_khac_nganh_nv"),
        (dict(kv_ly_do="thieu_khu_vuc", kv_muc=None), "thieu_khu_vuc"),
    ],
)
def test_bo_may_nguyen_vong_mot_ly_do(sua, ma):
    assert cong.ly_do_cua_dong(_sach(**sua)) == [ma]


def test_nv1_trung_thi_khong_chan():
    assert cong.ly_do_cua_dong(_sach(so_nv_trung=1, nv_trung_id=11)) == []


@pytest.mark.parametrize(
    "sua, ma",
    [
        (dict(so_nv=0, nv_in_id=None, nv1_id=None, nv_in_nganh_id=None,
              nv_in_path_id=None, nv_in_sg_id=None), "mot_nv_khong_co_dong_nguyen_vong"),
        (dict(so_nv=2), "mot_nv_nhieu_dong_nguyen_vong"),
        (dict(lg_nganh_id=None), "mot_nv_khong_xac_dinh_nganh"),
        (dict(lg_path_id=None), "mot_nv_khong_xac_dinh_duong_xet"),
        (dict(lg_sg_id=None), "mot_nv_khong_xac_dinh_to_hop"),
        (dict(lg_nganh_id=6), "mot_nv_khac_nganh"),  # học phí = dòng in (5), hồ sơ ghi 6
        (dict(lg_path_id=8), "mot_nv_khac_duong_xet"),
        (dict(lg_sg_id=4), "mot_nv_khac_to_hop"),
        (dict(diem_ca_hai_khac=1), "mot_nv_diem_lech"),
        (dict(diem_chi_nv=1), "mot_nv_diem_lech"),
        (dict(diem_chi_hs=1), "mot_nv_diem_lech"),
    ],
)  # fmt: skip
def test_mot_nguyen_vong_mot_ly_do(sua, ma):
    assert cong.ly_do_cua_dong(_sach_mot_nv(**sua)) == [ma]


def test_bo_may_nguyen_vong_khong_doi_bang_diem_ho_so_khi_chi_mot_ben():
    # Bộ máy nguyện vọng: nguồn = điểm nguyện vọng; bảng điểm hồ sơ vắng môn ⇒ KHÔNG lệch.
    assert cong.ly_do_cua_dong(_sach(diem_chi_nv=3)) == []
    assert cong.ly_do_cua_dong(_sach(diem_chi_hs=3)) == []


# ═══════════════════════════════ đánh giá cả danh sách + xác nhận ═════════════════════════
def _ds(*trang_thai):
    return [_sach(stt=i, status=s, kv_muc="0.%d0" % i) for i, s in enumerate(trang_thai, 1)]


def test_danh_gia_gom_theo_ly_do_va_trang_thai_so_dong_tang_dan():
    kq = cong.danh_gia(
        _ds("approved", "draft", "submitted", "withdrawn", "submitted", "draft", "lạ")
    )
    assert kq.chan == (
        ("trang_thai_chan", "draft", (2, 6)),
        ("trang_thai_chan", "withdrawn", (4,)),
        ("trang_thai_la", "lạ", (7,)),
    )
    assert kq.canh_bao == {"submitted": (3, 5)}
    assert kq.so_canh_bao() == {"submitted": 2}
    assert kq.diem_kv == tuple("0.%d0" % i for i in range(1, 8))
    assert kq.so_theo_trang_thai() == {
        "approved": 1,
        "draft": 2,
        "lạ": 1,
        "submitted": 2,
        "withdrawn": 1,
    }


def test_chan_thi_400_lie_ke_tung_dong_xac_nhan_khong_go_duoc():
    kq = cong.danh_gia(_ds("approved", "draft", "reviewing"))
    with pytest.raises(DataValidationError) as e:
        cong.kiem_va_xac_nhan(kq, xac_nhan={"reviewing": 1}, duoc_xac_nhan=True)
    p = e.value.public_payload["kiem_tra_dung_bo"]
    assert p["muc"] == "chan" and p["so_dong"] == 3
    assert p["chan"] == [
        {
            "ma": "trang_thai_chan",
            "mo_ta": cong.LY_DO["trang_thai_chan"],
            "trang_thai": "draft",
            "so_ho_so": 1,
            "dong": [2],
        }
    ]
    assert p["canh_bao"]["dong_theo_trang_thai"] == {"reviewing": [3]}


def test_canh_bao_khong_xac_nhan_thi_409_kem_so_dem_va_dong():
    kq = cong.danh_gia(_ds("approved", "reviewing", "submitted", "submitted"))
    for duoc in (True, False):
        with pytest.raises(ConflictError) as e:
            cong.kiem_va_xac_nhan(kq, xac_nhan=None, duoc_xac_nhan=duoc)
        p = e.value.public_payload["kiem_tra_dung_bo"]
        assert p["muc"] == "can_xac_nhan" and p["chan"] == []
        assert p["canh_bao"] == {
            "so_ho_so_theo_trang_thai": {"reviewing": 1, "submitted": 2},
            "dong_theo_trang_thai": {"reviewing": [2], "submitted": [3, 4]},
        }
        assert p["can_admin_xac_nhan"] is True
        assert p["nguoi_goi_duoc_xac_nhan"] is duoc


def test_xac_nhan_dung_so_dem_thi_qua_lech_thi_409():
    kq = cong.danh_gia(_ds("approved", "reviewing", "submitted", "submitted"))
    dung = {"reviewing": 1, "submitted": 2}
    assert cong.kiem_va_xac_nhan(kq, xac_nhan=dung, duoc_xac_nhan=True) == dung
    for lech in ({"reviewing": 1, "submitted": 1}, {"submitted": 2}, {"reviewing": 1}):
        with pytest.raises(ConflictError) as e:
            cong.kiem_va_xac_nhan(kq, xac_nhan=lech, duoc_xac_nhan=True)
        assert e.value.public_payload["kiem_tra_dung_bo"]["muc"] == "xac_nhan_lech"


def test_khong_canh_bao_ma_van_gui_xac_nhan_thi_409():
    kq = cong.danh_gia(_ds("approved", "enrolled"))
    assert cong.kiem_va_xac_nhan(kq, xac_nhan=None, duoc_xac_nhan=True) is None
    with pytest.raises(ConflictError):
        cong.kiem_va_xac_nhan(kq, xac_nhan={"submitted": 1}, duoc_xac_nhan=True)


@pytest.mark.parametrize("duoc", [False, None, 1, "True"])
def test_chi_admin_duoc_gui_xac_nhan(duoc):
    # Kể cả khi xác nhận ĐÚNG số đếm: người không được xác nhận ⇒ 403 (chỉ ``True`` thật).
    kq = cong.danh_gia(_ds("submitted"))
    with pytest.raises(PermissionDeniedError):
        cong.kiem_va_xac_nhan(kq, xac_nhan={"submitted": 1}, duoc_xac_nhan=duoc)
    with pytest.raises(PermissionDeniedError):
        cong.kiem_quyen_xac_nhan({"submitted": 1}, duoc)
    cong.kiem_quyen_xac_nhan(None, duoc)  # không xác nhận ⇒ không cần quyền


@pytest.mark.parametrize(
    "xn",
    [
        {},
        {"approved": 1},
        {"draft": 1},
        {"submitted": 0},
        {"submitted": True},
        {"submitted": "1"},
        ["submitted"],
        "submitted",
    ],
)
def test_xac_nhan_sai_dang_thi_400(xn):
    with pytest.raises(DataValidationError):
        cong.kiem_dang_xac_nhan(xn)


def test_payload_chi_so_dong_ma_ly_do_trang_thai():
    # Không mã hồ sơ, không giá trị dữ liệu: mọi lá là số / mã lý do / trạng thái / câu cố định.
    kq = cong.danh_gia(
        [
            _sach(stt=1, status="draft"),
            _sach(stt=2, status="submitted", hp_nganh_id=9),
            dataclasses.replace(_sach(stt=3), kv_ly_do="thieu_khu_vuc", kv_muc=None),
        ]
    )
    with pytest.raises(DataValidationError) as e:
        cong.kiem_va_xac_nhan(kq, xac_nhan=None, duoc_xac_nhan=True)
    p = e.value.public_payload["kiem_tra_dung_bo"]
    assert {c["ma"] for c in p["chan"]} == {
        "trang_thai_chan",
        "hoc_phi_khac_nganh_nv",
        "thieu_khu_vuc",
    }
    assert all(set(c) == {"ma", "mo_ta", "trang_thai", "so_ho_so", "dong"} for c in p["chan"])
    assert all(c["mo_ta"] == cong.LY_DO[c["ma"]] for c in p["chan"])
    assert not re.search(r"\d{9,}", str(e.value.public_payload) + e.value.detail)
