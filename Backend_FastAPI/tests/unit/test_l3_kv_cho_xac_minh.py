# tests/unit/test_l3_kv_cho_xac_minh.py
"""L3 — KV của thí sinh trung cấp xét sau THCS theo NƠI HỌC THCS; sơ cấp + nhánh cũ "KV chờ xác minh".

Căn cứ (owner 22-11, ``logs-P5/cong-bo-ket-qua/gd2/l3/``):
* ``QUYET-DINH-OWNER-L3-5-CAU-2026-11-22.md`` — câu 1 (đo trước rồi quyết ⇒ cờ hồ sơ cũ), câu 2 (không tin nhãn
  ``permanent_address_special``), câu 4 (trường học lâu nhất lớp 6–9, hoà ⇒ trường tốt nghiệp THCS), câu 5 (sơ cấp + nhánh cũ chờ
  xác minh);
* ``QUYET-DINH-OWNER-L3-TRUONG-THCS-VAO-DANH-MUC-2026-11-22.md`` — Admin thêm trường THCS vào danh mục ⇒ hồ sơ tính lại được;
* lệnh điều phối 22-11 + ``DE-XUAT-DANH-MUC-THCS-VA-CONG-CU-CHUAN-HOA-2026-11-22.md`` Phần C — trường DTNT ⇒ chờ xác minh; KV không phủ
  đủ năm ⇒ chờ xác minh (KHÔNG ``catalog_gap_school``); dòng ``level`` trống + trình độ THCS là dòng THCS; dòng ``y→y`` theo G5.

Giá trị mong đợi VIẾT TAY. Ba hàm đọc danh mục được thay bằng bảng tra trong bộ nhớ (ghi lại từng lần hỏi); MỌI ca chạy qua CẢ
đường từng hồ sơ (``resolve_kv_for_profile``) lẫn đường lô (``decide_kv_for_profile`` trên khoá ``kv_lookup_keys`` /
``kv_school_dtnt_keys``) và đòi hai kết quả BẰNG nhau. Không CSDL.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.services import priority_service as ps

pytestmark = pytest.mark.unit

NAM = 2026
#: Trường giả: T1 KV1, T2 KV2, T3 KV3 (mọi năm); T4 chỉ có KV từ năm học 2020; D là trường PT DTNT (KV1); P là trường cấp THPT.
T1, T2, T3, T4, D, P = 11, 12, 13, 14, 15, 16
KV_TRUONG = {}
for _y in range(2000, 2031):
    KV_TRUONG[(T1, _y)] = "KV1"
    KV_TRUONG[(T2, _y)] = "KV2"
    KV_TRUONG[(T3, _y)] = "KV3"
    KV_TRUONG[(D, _y)] = "KV1"
    KV_TRUONG[(P, _y)] = "KV3"
    if _y >= 2020:
        KV_TRUONG[(T4, _y)] = "KV2-NT"
DTNT = {T1: False, T2: False, T3: False, T4: False, D: True, P: False}
XA = {("X1", NAM): "KV1", ("X2", NAM): "KV2-NT"}


def _thcs(sid, tu, den, lop=None, level="THCS", trinh_do="THCS"):
    muc = {"level": level, "graduation_type": trinh_do, "school_id": sid, "school_name": "Trường giả", "year_from": tu,
           "year_to": den}
    if lop is not None:
        muc["grade_to"] = lop
    return muc


def _go_tay(tu, den, trinh_do="THCS"):
    """Dòng gõ tay như production 22-11: ``level`` trống, trình độ THCS, không ``school_id``."""
    return {"level": None, "graduation_type": trinh_do, "school_id": None, "school_name": "Trường gõ tay", "year_from": tu,
            "year_to": den}


def _hs(**kw):
    goc = dict(
        id=1,
        academic_year=NAM,
        cultural_education_level="graduated_thcs",
        vocational_qualification="none",
        area_resolution_basis=None,
        permanent_commune_code="X1",
        academic_history=[_thcs(T1, 2018, 2022)],
        priority_resolution_snapshot=None,
    )
    goc.update(kw)
    return SimpleNamespace(**goc)


def _chay(monkeypatch, hs, tl="trung_cap", at="chinh_quy", kv_truong=None, dtnt=None):
    """Hai đường, cùng danh mục giả; trả ``(kv, meta, các phép tra đường từng hồ sơ)``. Đòi hai đường bằng nhau và khoá nạp trước
    BAO TRÙM mọi phép tra thật sự hỏi."""
    bang = KV_TRUONG if kv_truong is None else kv_truong
    co = DTNT if dtnt is None else dtnt
    hoi = []

    async def _xa(db, ma, nam):
        hoi.append(("xa", ma, nam))
        return XA.get((ma, nam))

    async def _truong(db, sid, nam):
        hoi.append(("truong", sid, nam))
        return bang.get((sid, nam))

    async def _dtnt(db, sid):
        hoi.append(("dtnt", sid))
        return co.get(sid)

    monkeypatch.setattr(ps, "_lookup_commune_kv", _xa)
    monkeypatch.setattr(ps, "lookup_kv_for_school_year", _truong)
    monkeypatch.setattr(ps, "lookup_school_is_dtnt", _dtnt)
    kv, meta = asyncio.run(ps.resolve_kv_for_profile(hs, db=None, target_level=tl, admission_type=at))

    xa_k, truong_k = ps.kv_lookup_keys(hs, target_level=tl, admission_type=at)
    dtnt_k = ps.kv_school_dtnt_keys(hs, target_level=tl, admission_type=at)
    lo = ps.decide_kv_for_profile(
        hs,
        commune_kv={k: XA.get(k) for k in xa_k},
        school_kv={k: bang.get(k) for k in truong_k},
        school_dtnt={k: co.get(k) for k in dtnt_k},
        target_level=tl,
        admission_type=at,
    )
    assert lo == (kv, meta), (lo, kv, meta)
    assert {(h[1], h[2]) for h in hoi if h[0] == "xa"} <= set(xa_k)
    assert {(h[1], h[2]) for h in hoi if h[0] == "truong"} <= set(truong_k)
    assert {h[1] for h in hoi if h[0] == "dtnt"} <= set(dtnt_k)
    return kv, meta, hoi


def _cho_xac_minh(meta, reason):
    assert meta["rule_applied"] == ps.KV_PENDING_VERIFICATION_RULE, meta
    assert meta["reason"] == reason, meta
    assert meta["requires_manual_override"] is True
    snap = {"kv_resolved": None, **meta}
    assert not ps.kv_snapshot_resolved(snap)
    assert not ps.kv_snapshot_blocks_submit(snap)


def _ca_dung(meta):
    return [(e["index"], e["case"]) for e in meta["breakdown"]["entries"]]


# ═══════════════════════════════ 1. Trung cấp sau THCS — tính từ trường THCS (câu 4) ═══════════════════════════════
def test_mot_truong_thcs_bon_nam_ra_kv_cua_truong(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, _hs())
    assert (kv, meta["rule_applied"], meta["basis"], meta["pathway"]) == (
        "KV1", "longest_duration", "LICH_SU_THCS", "lich_su_thcs",
    )
    assert meta["basis_reason"] == "tc_chinh_quy_post_thcs_uses_thcs_school_history"
    # Đếm năm như G5: 2018 → 2022 = năm học 2018, 2019, 2020, 2021 (khoá năm bắt đầu); KHÔNG tra xã thường trú.
    assert hoi == [("dtnt", T1), ("truong", T1, 2018), ("truong", T1, 2019), ("truong", T1, 2020), ("truong", T1, 2021)]
    assert meta["breakdown"]["winner_years"] == 4


def test_chuyen_truong_3_1_khu_vuc_hoc_lau_hon_thang(monkeypatch):
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2018, 2021), _thcs(T2, 2021, 2022, lop=9)]))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV1", "longest_duration", {"KV1": 3, "KV2": 1})


@pytest.mark.parametrize("dao_thu_tu", [False, True], ids=["thu_tu_khai", "dao_thu_tu"])
def test_hoa_2_2_theo_truong_tot_nghiep_lop_9(monkeypatch, dao_thu_tu):
    lich_su = [_thcs(T1, 2018, 2020), _thcs(T2, 2020, 2022)]
    if dao_thu_tu:
        lich_su.reverse()
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"]) == ("KV2", "tiebreak_graduation_school")
    assert (meta["breakdown"]["graduation_school_id"], meta["breakdown"]["graduation_lookup_year"]) == (T2, 2021)
    assert hoi[-1] == ("truong", T2, 2021)


def test_hoa_hai_truong_cung_nam_ket_thuc_khong_phan_dinh_thi_cho_xac_minh(monkeypatch):
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2018, 2020), _thcs(T2, 2018, 2020)]))
    assert kv is None
    _cho_xac_minh(meta, "thcs_tied_graduation_school")


def test_moi_lop_mot_dong_nhu_nut_them_nhanh(monkeypatch):
    """Nút thêm nhanh (G5) sinh mỗi lớp một dòng ``Y → Y+1``; chọn trường cho từng dòng ⇒ đếm đủ 4 năm."""
    dong = [_thcs(T1, 2018, 2019, lop=6), _thcs(T1, 2019, 2020, lop=7), _thcs(T1, 2020, 2021, lop=8),
            _thcs(T3, 2021, 2022, lop=9)]
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=dong))
    assert (kv, meta["breakdown"]["kv_totals"]) == ("KV1", {"KV1": 3, "KV3": 1})


def test_lien_thong_tu_so_cap_cung_tinh_tu_truong_thcs(monkeypatch):
    kv, meta, _ = _chay(monkeypatch, _hs(vocational_qualification="so_cap"), at="lien_thong")
    assert (kv, meta["basis"], meta["basis_reason"]) == (
        "KV1", "LICH_SU_THCS", "tc_lien_thong_post_thcs_with_voc_uses_thcs_school_history",
    )


def test_dong_level_trong_trinh_do_thcs_la_dong_thcs(monkeypatch):
    """Dữ liệu thật 22-11: ``level`` trống, ``graduation_type = 'THCS'``. Có ``school_id`` thì đếm như dòng cấp THCS."""
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=[_thcs(T2, 2018, 2022, level=None)]))
    assert (kv, meta["rule_applied"]) == ("KV2", "longest_duration")


def test_lien_cap_lop_9_tro_xuong_la_dong_thcs(monkeypatch):
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=[_thcs(T3, 2018, 2022, lop=9, level="THCS_THPT", trinh_do=None)]))
    assert (kv, meta["breakdown"]["kv_totals"]) == ("KV3", {"KV3": 4})


def test_lien_cap_chi_co_nam_lop_10_khong_phai_dong_thcs(monkeypatch):
    lich_su = [_thcs(T1, 2018, 2022), _thcs(T3, 2022, 2023, lop=10, level="THCS_THPT", trinh_do="THPT")]
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["breakdown"]["kv_totals"]) == ("KV1", {"KV1": 4})


#: Owner 22-11 ``QUYET-DINH-OWNER-L3A-5-CAU`` câu 3: liên cấp cùng một trường tới lớp ≥ 10 ⇒ đếm phần lớp 6–9, cắt như G5 cắt phần
#: THPT (``kv_lien_cap_split_year`` — một nguồn).
_LIEN_CAP_TOI_THPT = [
    (_thcs(T1, 2017, 2022, lop=10, level="THCS_THPT", trinh_do=None), [2017, 2018, 2019, 2020]),
    (_thcs(T1, 2016, 2023, lop=12, level="THCS_THPT", trinh_do="THPT"), [2016, 2017, 2018, 2019]),
    (_thcs(T1, 2019, 2022, lop=11, level="THCS_THPT", trinh_do=None), [2019]),
]
_ID_LIEN_CAP = ["lop_6_10", "lop_6_12", "vao_lop_9_het_lop_11"]


@pytest.mark.parametrize("dong, nam_dem", _LIEN_CAP_TOI_THPT, ids=_ID_LIEN_CAP)
def test_lien_cap_cung_truong_toi_lop_10_tro_len_dem_phan_lop_6_9(monkeypatch, dong, nam_dem):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[dong]))
    assert (kv, meta["rule_applied"], meta["basis"]) == ("KV1", "longest_duration", "LICH_SU_THCS")
    assert meta["breakdown"]["entries"][0]["counted_school_years"] == nam_dem
    assert [h for h in hoi if h[0] == "truong"] == [("truong", T1, y) for y in nam_dem]


@pytest.mark.parametrize("dong, nam_dem", _LIEN_CAP_TOI_THPT, ids=_ID_LIEN_CAP)
def test_cho_cat_lien_cap_mot_nguon_phan_thcs_va_phan_thpt_bu_nhau(dong, nam_dem):
    thcs, thpt = list(ps.kv_entry_thcs_school_years(dong)), list(ps.kv_entry_school_years(dong))
    assert thcs == nam_dem
    assert thcs + thpt == list(range(dong["year_from"], dong["year_to"]))
    assert ps.kv_entry_thcs_last_school_year(dong) == nam_dem[-1]


def test_hoa_voi_dong_lien_cap_tot_nghiep_lop_9_tra_nam_hoc_lop_9(monkeypatch):
    """Hoà 2–2: THCS T1 2016→2018 (KV1) và liên cấp T2 2018→2021 tới lớp 10 (phần THCS 2018, 2019 — KV2). Trường tốt nghiệp lớp 9 = T2
    (phần THCS kết thúc 2020) ⇒ tra T2 ở năm học 2019 (lớp 9), KHÔNG ở 2020 (lớp 10)."""
    lich_su = [_thcs(T1, 2016, 2018), _thcs(T2, 2018, 2021, lop=10, level="THCS_THPT", trinh_do=None)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == (
        "KV2", "tiebreak_graduation_school", {"KV1": 2, "KV2": 2},
    )
    assert (meta["breakdown"]["graduation_year"], meta["breakdown"]["graduation_lookup_year"]) == (2020, 2019)
    assert hoi[-1] == ("truong", T2, 2019)


def test_khong_tra_dong_thpt_cua_em_bo_hoc_thpt(monkeypatch):
    lich_su = [_thcs(T1, 2018, 2022), {"level": "THPT", "graduation_type": "THPT", "school_id": P, "year_from": 2022,
                                       "year_to": 2023}]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert kv == "KV1" and all(h[1] != P for h in hoi)


# ═════════ 1b. Bước hoà — MỘT luật THPT / THCS (``kv_graduation_pick``): lớp không so được ở nhóm tốt nghiệp ⇒ cần xét tay ═════════
#: Owner 23-11 ``QUYET-DINH-OWNER-O-LOP-TRONG-CAN-XET-TAY``: lựa chọn (a) — lớp trống / null / sai kiểu ở nhóm tốt nghiệp khi hoà KV
#: ⇒ cần xét tay, áp CHUNG THPT và THCS; "thiếu hẳn khoá" và "null" NHƯ NHAU. Trước đây nhánh THCS coi lớp trống = 0 (luật (b)).
_KHONG_KHOA = object()
#: (tên, lớp mục 2 theo (THPT, THCS), phán quyết mong đợi) — mục 1 luôn có lớp cuối hợp lệ (THPT 12 / THCS 9).
_LOP_HOA = [
    ("thieu_khoa", (_KHONG_KHOA, _KHONG_KHOA), "xet_tay"),
    ("null", (None, None), "xet_tay"),
    ("chuoi", ("12", "9"), "xet_tay"),
    ("bool", (True, True), "xet_tay"),
    ("so_thap_hon", (11, 8), "muc_1"),
    ("so_bang_nhau", (12, 9), "xet_tay"),
]
#: Lớp NGOÀI dải của cấp KHÔNG còn chung một đường bước hoà (owner 24-11 đính chính): THPT / GDTX số nguyên ngoài 10..12 ⇒ dừng ở BƯỚC
#: ĐẾM (``test_kv_hoa_thpt_thieu_lop.py``); THCS lớp 10–12 / 0 ⇒ bước hoà (mục 1c); THCS lớp hợp lệ ≤ 5 ⇒ không phải dòng THCS (1e).


def _dat_lop(muc, lop):
    """Bản sao ``muc`` với ``grade_to`` = ``lop`` (``_KHONG_KHOA`` ⇒ bỏ hẳn khoá; ``None`` ⇒ khoá có, giá trị null)."""
    muc = dict(muc)
    muc.pop("grade_to", None)
    if lop is not _KHONG_KHOA:
        muc["grade_to"] = lop
    return muc


def _thpt(sid, tu, den, lop):
    return _dat_lop({"level": "THPT", "graduation_type": "THPT", "school_id": sid, "school_name": "Trường giả", "year_from": tu,
                     "year_to": den}, lop)


def _phan_quyet(kv, meta):
    """Phán quyết của bước hoà, không phụ thuộc nhánh: ``("xet_tay", id các mục không phân định)`` | ``("truong", id, KV)``."""
    if kv is None:
        return "xet_tay", sorted(meta["breakdown"]["tied_entries"])
    assert meta["rule_applied"] == "tiebreak_graduation_school", meta
    return "truong", meta["breakdown"]["graduation_school_id"], kv


@pytest.mark.parametrize("dao_thu_tu", [False, True], ids=["thu_tu_khai", "dao_thu_tu"])
@pytest.mark.parametrize("ten, lop, mong", _LOP_HOA, ids=[c[0] for c in _LOP_HOA])
def test_luat_hoa_mot_nguon_thpt_va_thcs_cung_phan_quyet(monkeypatch, ten, lop, mong, dao_thu_tu):
    """Hoà 2–2, hai mục CÙNG năm kết thúc; mục 2 mang lớp ``lop``. Nhánh THPT (CĐ, văn hoá THPT, ``2021→2023``) và nhánh THCS (trung
    cấp sau THCS, ``2018→2020``) cho CÙNG phán quyết (CLAUDE.md §7 — một luật, test khoá bằng nhau):
    * lớp không so được (thiếu khoá / null / chuỗi / bool) hoặc hai lớp bằng nhau ⇒ cần xét tay — THPT ``ambiguous_requires_manual``,
      THCS "KV chờ xác minh" ``thcs_tied_graduation_school`` — và KHÔNG tra trường tốt nghiệp;
    * lớp mục 2 thấp hơn ⇒ mục 1 là trường tốt nghiệp (như cũ).
    Luật (b) cũ của nhánh THCS (lớp trống / lạ = 0) chọn mục 1 ở bốn ca lớp lạ ⇒ ĐỎ."""
    thpt = [_thpt(T1, 2021, 2023, 12), _thpt(T2, 2021, 2023, lop[0])]
    thcs = [_dat_lop(_thcs(T1, 2018, 2020), 9), _dat_lop(_thcs(T2, 2018, 2020), lop[1])]
    if dao_thu_tu:
        thpt.reverse()
        thcs.reverse()
    kv_a, meta_a, hoi_a = _chay(monkeypatch, _hs(cultural_education_level="graduated_thpt", academic_history=thpt), tl="cao_dang")
    kv_b, meta_b, hoi_b = _chay(monkeypatch, _hs(academic_history=thcs))
    assert (meta_a["basis"], meta_b["basis"]) == ("LICH_SU_THPT", "LICH_SU_THCS")
    assert meta_a["breakdown"]["kv_totals"] == meta_b["breakdown"]["kv_totals"] == {"KV1": 2, "KV2": 2}
    mong_pq = ("xet_tay", sorted([T1, T2])) if mong == "xet_tay" else ("truong", T1, "KV1")
    assert _phan_quyet(kv_a, meta_a) == _phan_quyet(kv_b, meta_b) == mong_pq, (meta_a, meta_b)
    if mong == "xet_tay":
        assert (meta_a["rule_applied"], meta_a["reason"], meta_a["requires_manual_override"]) == (
            "ambiguous_requires_manual", "tied_graduation_year_and_grade", True,
        )
        _cho_xac_minh(meta_b, "thcs_tied_graduation_school")
        # Chỉ tra các năm học (2 + 2), KHÔNG tra trường tốt nghiệp.
        assert sum(h[0] == "truong" for h in hoi_a) == sum(h[0] == "truong" for h in hoi_b) == 4
    else:
        assert (hoi_a[-1], hoi_b[-1]) == (("truong", T1, 2022), ("truong", T1, 2019))


@pytest.mark.parametrize(
    "lop_khac, mong",
    [(9, "xet_tay"), (8, "lien_cap"), (_KHONG_KHOA, "xet_tay")],
    ids=["dong_thcs_lop_9_bang_nhau", "dong_thcs_lop_8_lien_cap_thang", "dong_thcs_thieu_khoa_lop"],
)
def test_hoa_thcs_lien_cap_toi_lop_10_so_nhu_lop_9(monkeypatch, lop_khac, mong):
    """Liên cấp T2 lớp 6 → hết lớp 10 ``2017→2021`` ⇒ phần THCS 2017–2019 (KV2, 3 năm), kết thúc 2020, lớp cuối phần THCS = 9; dòng
    THCS T1 ``2017→2020`` (KV1, 3 năm) ⇒ hoà 3–3, CÙNG năm kết thúc 2020. Dòng THCS lớp 9 ⇒ ngang nhau ⇒ chờ xác minh; lớp 8 ⇒ liên cấp
    là trường tốt nghiệp lớp 9, tra ở năm học lớp 9 (2019); dòng THCS thiếu khoá lớp ⇒ chờ xác minh (owner 23-11 (a) — luật (b) cũ coi
    lớp trống = 0 nên chọn liên cấp)."""
    lich_su = [_dat_lop(_thcs(T1, 2017, 2020), lop_khac), _thcs(T2, 2017, 2021, lop=10, level="THCS_THPT", trinh_do=None)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert meta["breakdown"]["kv_totals"] == {"KV1": 3, "KV2": 3}
    if mong == "xet_tay":
        assert kv is None
        _cho_xac_minh(meta, "thcs_tied_graduation_school")
        assert sorted(meta["breakdown"]["tied_entries"]) == [T1, T2]
        assert sum(h[0] == "truong" for h in hoi) == 6  # chỉ các năm học, không tra trường tốt nghiệp
    else:
        assert (kv, meta["rule_applied"], meta["breakdown"]["graduation_school_id"]) == ("KV2", "tiebreak_graduation_school", T2)
        assert (meta["breakdown"]["graduation_year"], meta["breakdown"]["graduation_lookup_year"]) == (2020, 2019)
        assert hoi[-1] == ("truong", T2, 2019)


@pytest.mark.parametrize("dao_thu_tu", [False, True], ids=["thu_tu_khai", "dao_thu_tu"])
@pytest.mark.parametrize("lop_la", [_KHONG_KHOA, None, "8"], ids=["thieu_khoa", "null", "chuoi"])
def test_hoa_thcs_nhom_thap_lop_la_van_lay_truong_tot_nghiep(monkeypatch, lop_la, dao_thu_tu):
    """Rà hợp nhất 23-11 B-H1, nhánh THCS: A T1 ``2016→2018`` lớp 7 (KV1: 2016, 2017); C T2 ``2017→2018`` lớp lạ (KV2: 2017); B T3
    ``2018→2020`` lớp 9 (KV3: 2018, 2019). KV1 = KV3 = 2 ⇒ hoà; nhóm năm kết thúc lớn nhất (2020) chỉ có B ⇒ B, tra ở năm học lớp 9
    (2019) ⇒ KV3. Lớp lạ ở nhóm THẤP không cản và không đổi sang chờ xác minh (nhóm ấy không được xếp — bản xếp toàn bộ buộc so A với C
    cùng năm 2018 ⇒ ``TypeError``)."""
    lich_su = [_thcs(T1, 2016, 2018, lop=7), _dat_lop(_thcs(T2, 2017, 2018), lop_la), _thcs(T3, 2018, 2020, lop=9)]
    if dao_thu_tu:
        lich_su.reverse()
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"], meta["breakdown"]["graduation_school_id"]) == ("KV3", "tiebreak_graduation_school", T3), meta
    assert meta["breakdown"]["kv_totals"] == {"KV1": 2, "KV2": 1, "KV3": 2}
    assert (meta["breakdown"]["graduation_year"], meta["breakdown"]["graduation_lookup_year"]) == (2020, 2019)
    assert hoi[-1] == ("truong", T3, 2019)


# ═══════════════════════════════ 1c. Lớp cuối phần THCS ngoài 6–9 ở bước hoà (owner 24-11) ═══════════════════════════════
#: Owner 24-11 ``QUYET-DINH-OWNER-L3-DONG-THCS-LOP-NGOAI-6-9``: dòng cấp THCS ghi lớp cuối NGOÀI 6–9 (schema cho 1..12) là dữ liệu lớp
#: không hợp lệ ⇒ như ô lớp trống (owner 23-11 (a)) ⇒ cần xét tay ("KV chờ xác minh" ``thcs_tied_graduation_school``), không tự chọn
#: KV. Lớp hợp lệ 1–5 (liên cấp hay không) KHÔNG còn tới bước hoà: owner 24-11 chỉ đếm năm lớp 6–9 + đính chính câu 1 ⇒ dòng ấy không
#: phải dòng THCS (mục 1d, 1e) — hai ca "lớp 5" cũ của mục này chuyển sang 1e. Owner 24-11 ``QUYET-DINH-OWNER-L3-THCS-LOP-10-12-VA-GO-DEM``:
#: dòng THCS (không ghi liên cấp) lớp 10–12 nay DỪNG ở bước ĐẾM (``grade_to_out_of_range`` ⇒ "chờ xác minh" ``thcs_history_inconsistent``,
#: 0 phép tra) — các ca lớp 10–12 dưới đây đổi mong đợi, giữ id. Owner 24-11 THCS-LOP-VO-NGHIA: lớp số nguyên 0 / âm / ≥ 13 cũng dừng
#: ở bước đếm (ca ``lop_0`` dưới đây đổi mong đợi, giữ id; mục 1f). Dải 6..9 ở bước hoà chỉ còn là lớp phòng thủ thêm.
def _dung_dem_thcs(kv, meta, hoi, chi_so):
    """Dừng ở bước ĐẾM nhánh THCS: "chờ xác minh" ``thcs_history_inconsistent``, dòng ``chi_so`` mang ``grade_to_out_of_range``, 0 phép
    tra (kể cả cờ DTNT)."""
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_history_inconsistent")
    assert _ca_dung(meta) == [(i, "grade_to_out_of_range") for i in chi_so]


def _cho_xac_minh_hoa(kv, meta, hoi, so_lan_tra_nam_hoc):
    assert kv is None
    _cho_xac_minh(meta, "thcs_tied_graduation_school")
    assert sorted(meta["breakdown"]["tied_entries"]) == [T1, T2]
    # Chỉ tra các năm học, KHÔNG tra trường tốt nghiệp.
    assert sum(h[0] == "truong" for h in hoi) == so_lan_tra_nam_hoc


@pytest.mark.parametrize("lop", [10, 11, 12], ids=["lop_10", "lop_11", "lop_12"])
def test_hoa_dong_thcs_lop_ngoai_6_9_voi_lien_cap_thi_cho_xac_minh(monkeypatch, lop):
    """Rà đoàn 3 D'2 NỢ-1. Liên cấp T2 lớp 6 → hết lớp 10 ``2017→2021`` (phần THCS 2017–2019, KV2, kết thúc 2020, lớp cuối 9); dòng
    THCS T1 ``2017→2020`` (KV1) ghi lớp ``lop``. Trước 24-11: lớp so như số ⇒ "lớp 10–12" thắng liên cấp lặng lẽ (KV1); 14ca4a29: bước
    hoà chờ xác minh. Nay (owner 24-11 THCS-LOP-10-12): dừng ngay ở bước ĐẾM, không đếm năm, không tra gì. (Ca "lớp 5" cũ ⇒ mục 1e.)"""
    lich_su = [_thcs(T1, 2017, 2020, lop=lop), _thcs(T2, 2017, 2021, lop=10, level="THCS_THPT", trinh_do=None)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    _dung_dem_thcs(kv, meta, hoi, [0])


#: (lớp của dòng T1, phán quyết mong đợi) — dòng T2 cùng năm luôn lớp 8. Biên 6 và 9 hợp lệ (so như số, như trước); 0 không hợp lệ ở
#: bước hoà; 0 / 10–12 dừng ở bước ĐẾM (owner 24-11 THCS-LOP-10-12, THCS-LOP-VO-NGHIA). (Ca "lớp 5" cũ ⇒ mục 1e.)
_BIEN_LOP_THCS = [
    (9, ("truong", T1, "KV1")),
    (6, ("truong", T2, "KV2")),
    (0, ("dung_dem", [0])),
    (10, ("dung_dem", [0])),
    (11, ("dung_dem", [0])),
    (12, ("dung_dem", [0])),
]


@pytest.mark.parametrize("lop, mong", _BIEN_LOP_THCS, ids=[f"lop_{c[0]}" for c in _BIEN_LOP_THCS])
def test_hoa_hai_dong_thcs_bien_lop_cuoi_6_9(monkeypatch, lop, mong):
    """Hai dòng THCS cùng ``2017→2020`` (T1 KV1, T2 KV2 lớp 8) ⇒ hoà 3–3, cùng năm kết thúc. Lớp 9 của T1 hợp lệ ⇒ T1 là trường tốt
    nghiệp (không đổi so với trước); lớp 6 hợp lệ ⇒ T2 lớp 8 lớn hơn; lớp 0 / 10–12 ⇒ dừng ở bước đếm."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2017, 2020, lop=lop), _thcs(T2, 2017, 2020, lop=8)]))
    if mong[0] == "dung_dem":
        _dung_dem_thcs(kv, meta, hoi, mong[1])
        return
    assert meta["breakdown"]["kv_totals"] == {"KV1": 3, "KV2": 3}
    assert _phan_quyet(kv, meta) == mong, meta
    if mong[0] == "xet_tay":
        _cho_xac_minh_hoa(kv, meta, hoi, 6)
    else:
        assert (meta["breakdown"]["graduation_year"], meta["breakdown"]["graduation_lookup_year"]) == (2020, 2019)
        assert hoi[-1] == ("truong", mong[1], 2019)


# ═══════════════════════════════ 1d. Chỉ đếm năm học lớp 6–9 (owner 24-11) ═══════════════════════════════
#: Owner 24-11 ``QUYET-DINH-OWNER-L3-CHI-DEM-NAM-THCS-VA-THU-TU-3B`` mục 1 (Codex đoàn 3a A1 NỢ-2): khi đếm thời gian học để chọn KV
#: cho trung cấp sau THCS, CHỈ tính các năm lớp 6–9. Dòng liên cấp đếm ngược từ lớp kết thúc (một năm một lớp — CÙNG phép tính với chỗ
#: cắt lớp 10, ``kv_lien_cap_grade_start_year``): bỏ năm tiểu học ở đầu mục; mục kết thúc ở lớp ≤ 5 không có năm lớp 6–9 ⇒ KHÔNG phải
#: dòng THCS (như mục liên cấp chỉ có năm THPT): không đếm, không tra cờ DTNT, không là ứng viên trường tốt nghiệp. Dòng KHÔNG ghi liên
#: cấp: mục 1e (lớp ≤ 5 ⇒ như liên cấp; còn lại đủ mọi năm). Thay hai ca cũ
#: ``test_hoa_lien_cap_ket_thuc_lop_duoi_6_thi_cho_xac_minh`` (liên cấp ``2017→2020`` lớp 5 / 6
#: góp 3 năm "THCS" — tiền đề nay trái luật đếm).
def test_vi_du_codex_lien_cap_het_lop_5_khong_dem_nam_tieu_hoc(monkeypatch):
    """Codex đoàn 3a A1 NỢ-2: liên cấp X (T1, KV1) ``2012→2017`` kết thúc lớp 5 + THCS Y (T2, KV2) ``2017→2021`` lớp 9. Trước: X góp 5
    năm tiểu học ⇒ KV1. Nay: X không có năm lớp 6–9 ⇒ không phải dòng THCS (không tra KV, không tra cờ DTNT) ⇒ chỉ Y ⇒ KV2."""
    lich_su = [_thcs(T1, 2012, 2017, lop=5, level="THCS_THPT", trinh_do=None), _thcs(T2, 2017, 2021, lop=9)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV2", "longest_duration", {"KV2": 4})
    assert hoi == [("dtnt", T2), ("truong", T2, 2017), ("truong", T2, 2018), ("truong", T2, 2019), ("truong", T2, 2020)]


def test_lien_cap_bo_nam_tieu_hoc_hoa_thi_theo_truong_tot_nghiep(monkeypatch):
    """Liên cấp X (T1, KV1) ``2014→2019`` lớp 3 → hết lớp 7: chỉ năm học lớp 6, 7 (2017, 2018) ⇒ KV1: 2. THCS Y (T2, KV2) ``2019→2021``
    lớp 8 → 9 ⇒ KV2: 2. Hoà 2–2 ⇒ luật hoà: trường tốt nghiệp = năm kết thúc lớn nhất (Y, 2021) ⇒ KV2, tra ở năm học lớp 9 (2020).
    Trước: X góp 5 năm ⇒ KV1 thắng lặng lẽ."""
    lich_su = [_thcs(T1, 2014, 2019, lop=7, level="THCS_THPT", trinh_do=None), _thcs(T2, 2019, 2021, lop=9)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == (
        "KV2", "tiebreak_graduation_school", {"KV1": 2, "KV2": 2},
    )
    assert meta["breakdown"]["entries"][0]["counted_school_years"] == [2017, 2018]
    assert (meta["breakdown"]["graduation_school_id"], meta["breakdown"]["graduation_lookup_year"]) == (T2, 2020)
    assert hoi[-1] == ("truong", T2, 2020)


#: (dòng liên cấp T3 — KV3 — có năm tiểu học ở đầu mục, năm học lớp 6–9 được đếm). Lớp đầu mục = lớp kết thúc − số năm + 1.
_LIEN_CAP_CO_NAM_TIEU_HOC = [
    (_thcs(T3, 2012, 2021, lop=9, level="THCS_THPT", trinh_do=None), [2017, 2018, 2019, 2020]),
    (_thcs(T3, 2010, 2022, lop=12, level="THCS_THPT", trinh_do="THPT"), [2015, 2016, 2017, 2018]),
    (_thcs(T3, 2015, 2023, lop=10, level="THCS_THPT", trinh_do=None), [2018, 2019, 2020, 2021]),
    (_thcs(T3, 2015, 2021, lop=6, level="THCS_THPT", trinh_do=None), [2020]),
]
_ID_TIEU_HOC = ["lop_1_9", "lop_1_12", "lop_3_10", "lop_1_6"]


@pytest.mark.parametrize("dong, nam_dem", _LIEN_CAP_CO_NAM_TIEU_HOC, ids=_ID_TIEU_HOC)
def test_lien_cap_co_nam_tieu_hoc_chi_dem_nam_lop_6_9(monkeypatch, dong, nam_dem):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[dong]))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV3", "longest_duration", {"KV3": len(nam_dem)})
    assert meta["breakdown"]["entries"][0]["counted_school_years"] == nam_dem
    assert [h for h in hoi if h[0] == "truong"] == [("truong", T3, y) for y in nam_dem]


@pytest.mark.parametrize("dong, nam_dem", _LIEN_CAP_CO_NAM_TIEU_HOC, ids=_ID_TIEU_HOC)
def test_cho_cat_lien_cap_tieu_hoc_thcs_thpt_noi_tiep(dong, nam_dem):
    """MỘT phép đếm ngược (``kv_lien_cap_grade_start_year``) cho cả hai chỗ cắt: năm tiểu học (trước năm học lớp 6) + phần THCS + phần
    THPT = MỌI năm học của mục, nối tiếp, không chồng."""
    thcs, thpt = list(ps.kv_entry_thcs_school_years(dong)), list(ps.kv_entry_school_years(dong))
    tieu_hoc = list(range(dong["year_from"], ps.kv_lien_cap_grade_start_year(dong, 6)))
    assert thcs == nam_dem
    assert tieu_hoc + thcs + thpt == list(range(dong["year_from"], dong["year_to"]))


@pytest.mark.parametrize("lop", [5, 1], ids=["lop_5", "lop_1"])
def test_lien_cap_het_lop_5_tro_xuong_khong_phai_dong_thcs(monkeypatch, lop):
    """Liên cấp T3 kết thúc ở lớp ``lop`` ≤ 5 (``2017 − lop → 2017``, chỉ năm tiểu học) đứng một mình ⇒ không có dòng THCS ⇒ "KV chờ
    xác minh" ``thcs_history_missing``, không tra danh mục. Trước: góp ``lop`` năm ⇒ KV3."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T3, 2017 - lop, 2017, lop=lop, level="THCS_THPT", trinh_do=None)]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_history_missing")


def test_lien_cap_het_lop_5_o_truong_dtnt_khong_keo_ho_so_ve_cho_xac_minh(monkeypatch):
    """Mục chỉ có năm tiểu học KHÔNG được tra cờ DTNT: liên cấp D (PT DTNT) ``2012→2017`` lớp 5 + THCS T2 ``2017→2021`` ⇒ KV2 (trước:
    D là dòng THCS ⇒ "chờ xác minh" ``thcs_school_dtnt`` vì một trường em chỉ học tiểu học)."""
    lich_su = [_thcs(D, 2012, 2017, lop=5, level="THCS_THPT", trinh_do=None), _thcs(T2, 2017, 2021, lop=9)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"]) == ("KV2", "longest_duration")
    assert ("dtnt", D) not in hoi


def test_lien_cap_het_lop_5_khong_la_ung_vien_truong_tot_nghiep(monkeypatch):
    """Mục không có năm lớp 6–9 không được là trường tốt nghiệp THCS. T1 (KV1) ``2015→2017`` và T3 (KV3) ``2017→2019`` lớp 9 ⇒ hoà 2–2;
    liên cấp T2 (KV2) ``2015→2020`` lớp 5 (dữ liệu chồng năm) có năm kết thúc lớn nhất. Nếu mục ấy còn là dòng THCS "0 năm", nó đứng
    MỘT mình ở nhóm năm kết thúc lớn nhất ⇒ thành trường tốt nghiệp ⇒ KV2 lặng lẽ. Nay: chỉ T1, T3 ⇒ T3 (2019) ⇒ KV3."""
    lich_su = [_thcs(T1, 2015, 2017), _thcs(T3, 2017, 2019, lop=9), _thcs(T2, 2015, 2020, lop=5, level="THCS_THPT", trinh_do=None)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == (
        "KV3", "tiebreak_graduation_school", {"KV1": 2, "KV3": 2},
    )
    assert meta["breakdown"]["graduation_school_id"] == T3
    assert all(h[1] != T2 for h in hoi)


def test_hoa_lien_cap_het_lop_6_dem_mot_nam_va_so_nhu_lop_6(monkeypatch):
    """Biên dưới hợp lệ: liên cấp T2 (KV2) ``2015→2020`` lớp 1 → 6 ⇒ chỉ năm học lớp 6 (2019) ⇒ KV2: 1; THCS T1 (KV1) ``2019→2020`` lớp
    8 ⇒ KV1: 1. Hoà 1–1, cùng năm kết thúc 2020 ⇒ so lớp cuối 8 > 6 ⇒ T1, tra năm học 2019 ⇒ KV1. Trước: T2 góp 5 năm ⇒ KV2."""
    lich_su = [_thcs(T1, 2019, 2020, lop=8), _thcs(T2, 2015, 2020, lop=6, level="THCS_THPT", trinh_do=None)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == (
        "KV1", "tiebreak_graduation_school", {"KV1": 1, "KV2": 1},
    )
    assert meta["breakdown"]["entries"][1]["counted_school_years"] == [2019]
    assert (meta["breakdown"]["graduation_school_id"], meta["breakdown"]["graduation_lookup_year"]) == (T1, 2019)
    assert hoi[-1] == ("truong", T1, 2019)


@pytest.mark.parametrize(
    "dong, ca",
    [
        (_thcs(T2, None, 2017, lop=5, level="THCS_THPT", trinh_do=None), "entry_years_invalid"),
        (_thcs(T2, 2017, 2012, lop=5, level="THCS_THPT", trinh_do=None), "entry_years_invalid"),
        (_thcs(T2, 2012, None, lop=9, level="THCS_THPT", trinh_do=None), "entry_years_invalid"),
        (_thcs(T2, 2012, 2021, lop=0, level="THCS_THPT", trinh_do=None), "lien_cap_missing_grade_to"),
        (_thcs(T2, 2012, 2021, lop=13, level="THCS_THPT", trinh_do=None), "lien_cap_missing_grade_to"),
    ],
    ids=["lop_5_thieu_nam", "lop_5_nam_nguoc", "lop_9_thieu_nam", "lop_0", "lop_13"],
)
def test_lien_cap_bien_thieu_nam_hoac_lop_la_thi_dung_co_nhan(monkeypatch, dong, ca):
    """Ca biên: năm thiếu / ngược, hoặc lớp kết thúc lạ ⇒ KHÔNG biết mục có năm lớp 6–9 hay không ⇒ đường cần xét tay SẴN CÓ (dòng dừng
    có nhãn ⇒ "KV chờ xác minh" ``thcs_history_inconsistent``) — kể cả mục kết thúc lớp ≤ 5: kiểm năm TRƯỚC khi loại."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2018, 2021), dong]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_history_inconsistent")
    assert _ca_dung(meta) == [(1, ca)]


# ═══════════ 1e. Dòng KHÔNG ghi liên cấp mà lớp cuối ≤ 5 ⇒ như liên cấp (owner 24-11 đính chính tiền đề THCS) ═══════════
#: Owner 24-11 ``QUYET-DINH-OWNER-L3-DINH-CHINH-TIEN-DE-THCS`` (Codex gói nhỏ L3 G3(b): danh mục không có cấp tiểu học ⇒ trường
#: TH&THCS mang cấp THCS; công cụ ghép 3b gắn được trường vào dòng gõ tay để trống ``level``):
#: * câu 1 — dòng không ghi liên cấp mà lớp cuối ≤ 5 ⇒ như liên cấp: không góp năm THCS, không là trường tốt nghiệp THCS;
#: * câu 2 — lưu ban (nhiều năm hơn số lớp) / không ghi lớp ⇒ tính đủ mọi năm thật học (như cũ).
def _dong_khac_lop_9():
    return _thcs(T2, 2017, 2021, lop=9)


@pytest.mark.parametrize("level", ["THCS", None], ids=["cap_thcs", "level_trong_trinh_do_thcs"])
def test_vi_du_codex_dong_khong_ghi_lien_cap_het_lop_5_khong_dem(monkeypatch, level):
    """Ví dụ Codex G3(b): dòng X (T1, KV1) ``2012→2017`` lớp 5 KHÔNG ghi liên cấp — cấp THCS (trường TH&THCS trong danh mục) hoặc
    ``level`` trống + trình độ THCS (dòng gõ tay được ghép trường) — + THCS Y (T2, KV2) ``2017→2021`` lớp 9. Trước: X góp 5 năm ⇒ KV1.
    Nay: X không phải dòng THCS (không tra KV, không tra cờ DTNT) ⇒ KV2."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2012, 2017, lop=5, level=level), _dong_khac_lop_9()]))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV2", "longest_duration", {"KV2": 4})
    assert hoi == [("dtnt", T2), ("truong", T2, 2017), ("truong", T2, 2018), ("truong", T2, 2019), ("truong", T2, 2020)]


@pytest.mark.parametrize(
    "dong_kia",
    [_thcs(T2, 2017, 2021, lop=10, level="THCS_THPT", trinh_do=None), _thcs(T2, 2017, 2020, lop=8)],
    ids=["voi_lien_cap_het_lop_10", "voi_dong_thcs_lop_8"],
)
def test_dong_thcs_het_lop_5_khong_con_hoa_voi_dong_kia(monkeypatch, dong_kia):
    """Thay hai ca "lớp 5" cũ của mục 1c (``…lop_ngoai_6_9_voi_lien_cap…[lop_5]``, ``…bien_lop_cuoi_6_9[lop_5]``): dòng THCS T1
    ``2017→2020`` lớp 5 nay không phải dòng THCS ⇒ không còn hoà 3–3; chỉ dòng kia (KV2, 3 năm THCS) ⇒ KV2, T1 không được tra."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2017, 2020, lop=5), dong_kia]))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV2", "longest_duration", {"KV2": 3})
    assert all(h[1] != T1 for h in hoi)


def test_dong_thcs_het_lop_5_dung_mot_minh_thi_khong_co_dong_thcs(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T3, 2012, 2017, lop=5)]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_history_missing")


@pytest.mark.parametrize(
    "dong",
    [_thcs(D, 2012, 2017, lop=5), {**_go_tay(2012, 2017), "grade_to": 5}],
    ids=["truong_dtnt", "go_tay_chua_co_truong"],
)
def test_dong_thcs_het_lop_5_khong_keo_ho_so_ve_cho_xac_minh(monkeypatch, dong):
    """Dòng chỉ có năm tiểu học không được tra cờ DTNT / danh mục: trường PT DTNT, hay dòng gõ tay chưa có trường, mà lớp cuối 5 ⇒ bỏ
    qua; THCS T2 ⇒ KV2 (trước: "chờ xác minh" ``thcs_school_dtnt`` / ``thcs_school_not_in_catalog`` vì một trường tiểu học)."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[dong, _dong_khac_lop_9()]))
    assert (kv, meta["rule_applied"]) == ("KV2", "longest_duration")
    assert ("dtnt", D) not in hoi


def test_dong_thcs_het_lop_5_khong_la_ung_vien_truong_tot_nghiep(monkeypatch):
    """T1 (KV1) ``2015→2017`` và T3 (KV3) ``2017→2019`` lớp 9 ⇒ hoà 2–2; dòng cấp THCS T2 (KV2) ``2015→2020`` lớp 5 (dữ liệu chồng năm) có
    năm kết thúc lớn nhất nhưng không phải dòng THCS ⇒ không là trường tốt nghiệp ⇒ T3 (2019) ⇒ KV3."""
    lich_su = [_thcs(T1, 2015, 2017), _thcs(T3, 2017, 2019, lop=9), _thcs(T2, 2015, 2020, lop=5)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == (
        "KV3", "tiebreak_graduation_school", {"KV1": 2, "KV3": 2},
    )
    assert meta["breakdown"]["graduation_school_id"] == T3
    assert all(h[1] != T2 for h in hoi)


def test_dong_thcs_het_lop_5_y_y_bi_loai_nhu_lien_cap(monkeypatch):
    """"Như liên cấp": dòng ``2017→2017`` lớp 5 bị loại (chỉ năm tiểu học) TRƯỚC phép kiểm 0 năm học — như liên cấp lớp ≤ 5 ``y→y``.
    Trước: dừng ``zero_length_entry``. Còn T1 ``2018→2021`` ⇒ KV1."""
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2018, 2021), _thcs(T2, 2017, 2017, lop=5)]))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV1", "longest_duration", {"KV1": 3})


@pytest.mark.parametrize(
    "dong",
    [_thcs(T2, None, 2017, lop=5), _thcs(T2, 2017, 2012, lop=5)],
    ids=["thieu_nam", "nam_nguoc"],
)
def test_dong_thcs_het_lop_5_nam_hong_thi_dung_co_nhan(monkeypatch, dong):
    """Năm thiếu / ngược ⇒ kiểm năm TRƯỚC khi loại dòng lớp ≤ 5 (như liên cấp) ⇒ dừng ``entry_years_invalid`` — không lặng lẽ bỏ."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2018, 2021), dong]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_history_inconsistent")
    assert _ca_dung(meta) == [(1, "entry_years_invalid")]


#: Câu 2 (giữ như cũ): dòng KHÔNG ghi liên cấp, lớp cuối 6..9 hoặc không ghi ⇒ đủ MỌI năm thật học — kể cả lưu ban, kể cả dòng ghi từ
#: lớp 1 ở trường TH&THCS (không phân biệt được với lưu ban). (dòng T1 — KV1 —, năm đếm). Ca ``lop_0_khong_hop_le`` cũ ⇒ mục 1f (owner
#: 24-11 THCS-LOP-VO-NGHIA: lớp số nguyên 0 nay dừng ở bước đếm).
_DEM_DU_NAM = [
    (_thcs(T1, 2016, 2021, lop=9), list(range(2016, 2021))),
    (_thcs(T1, 2012, 2021, lop=9), list(range(2012, 2021))),
    (_thcs(T1, 2016, 2021), list(range(2016, 2021))),
    (_thcs(T1, 2016, 2021, lop=6), list(range(2016, 2021))),
]


@pytest.mark.parametrize(
    "dong, nam_dem", _DEM_DU_NAM, ids=["luu_ban_lop_9", "tu_lop_1_den_9", "khong_ghi_lop", "bien_lop_6"],
)
def test_dong_thcs_luu_ban_hoac_khong_ghi_lop_dem_du_nam(monkeypatch, dong, nam_dem):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[dong]))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV1", "longest_duration", {"KV1": len(nam_dem)})
    assert meta["breakdown"]["entries"][0]["counted_school_years"] == nam_dem
    assert [h for h in hoi if h[0] == "truong"] == [("truong", T1, y) for y in nam_dem]


# ═══════════ 1f. Dòng THCS KHÔNG ghi liên cấp mà lớp cuối 10–12 ⇒ dừng ở bước ĐẾM (owner 24-11) ═══════════
#: Owner 24-11 ``QUYET-DINH-OWNER-L3-THCS-LOP-10-12-VA-GO-DEM`` câu 1: dòng trường THCS ghi lớp 10–12 (gõ nhầm, hoặc trường liên cấp ghi
#: SAI cấp) ⇒ cần xét tay CẢ ở bước đếm, đối xứng THPT / GDTX ngoài 10–12. Áp cho dòng KHÔNG ghi liên cấp (cấp THCS, ô cấp trống +
#: trình độ THCS); dòng GHI liên cấp lớp 10–12 là mục hợp lệ "lớp 6 → hết lớp 10–12" ⇒ giữ luật ``ca210d48`` (đếm phần lớp 6–9).
@pytest.mark.parametrize(
    "level, lop",
    [("THCS", 10), ("THCS", 11), ("THCS", 12), (None, 10), (None, 12)],
    ids=["cap_thcs_lop_10", "cap_thcs_lop_11", "cap_thcs_lop_12", "level_trong_lop_10", "level_trong_lop_12"],
)
def test_dong_thcs_khong_ghi_lien_cap_lop_10_12_dung_o_buoc_dem(monkeypatch, level, lop):
    """Dòng T1 (KV1) ``2017→2022`` lớp ``lop`` + dòng THCS hợp lệ T2 ``2022→2023``: không hoà gì mà vẫn dừng ở bước đếm, không tra gì.
    Trước: T1 góp 5 năm ⇒ KV1 lặng lẽ."""
    lich_su = [_thcs(T1, 2017, 2022, lop=lop, level=level), _thcs(T2, 2022, 2023, lop=9)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    _dung_dem_thcs(kv, meta, hoi, [0])


@pytest.mark.parametrize(
    "lop, nam_dem",
    [(10, [2017, 2018, 2019, 2020]), (11, [2017, 2018, 2019]), (12, [2017, 2018])],
    ids=["lop_10", "lop_11", "lop_12"],
)
def test_cung_dong_ghi_lien_cap_lop_10_12_van_dem_phan_lop_6_9(monkeypatch, lop, nam_dem):
    """Cặp của ca trên: CÙNG dòng ``2017→2022`` lớp ``lop`` nhưng GHI liên cấp ⇒ "vào lớp 6 → hết lớp ``lop``" hợp lệ ⇒ đếm phần lớp
    6–9 (``ca210d48``), KHÔNG dừng."""
    dong = _thcs(T1, 2017, 2022, lop=lop, level="THCS_THPT", trinh_do=None)
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[dong]))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV1", "longest_duration", {"KV1": len(nam_dem)})
    assert meta["breakdown"]["entries"][0]["counted_school_years"] == nam_dem


@pytest.mark.parametrize(
    "dong, ca",
    [
        (_thcs(T1, None, 2022, lop=12), "entry_years_invalid"),
        ({**_go_tay(2017, 2022), "grade_to": 12}, "grade_to_out_of_range"),
        (_thcs(T1, 2022, 2022, lop=12), "grade_to_out_of_range"),
        ({**_go_tay(2017, 2022), "grade_to": 0}, "grade_to_out_of_range"),
        (_thcs(T1, 2022, 2022, lop=-1), "grade_to_out_of_range"),
    ],
    ids=["nam_hong_kiem_truoc", "go_tay_lop_truoc_truong", "y_y_lop_truoc_0_nam", "go_tay_lop_0_truoc_truong", "y_y_lop_am_truoc_0_nam"],
)
def test_dong_thcs_lop_10_12_thu_tu_phep_kiem(monkeypatch, dong, ca):
    """Thứ tự ở ``kv_thcs_entry_case``: năm hỏng ⇒ dừng năm TRƯỚC; lớp số nguyên ngoài 1..9 (10–12, và từ owner 24-11 THCS-LOP-VO-NGHIA
    cả 0 / âm) xét TRƯỚC 0 năm học và trước "chưa có trường" (sửa lớp trước) ⇒ lý do ``thcs_history_inconsistent``, không phải
    ``thcs_school_not_in_catalog``."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[dong, _thcs(T2, 2018, 2021)]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_history_inconsistent")
    assert _ca_dung(meta) == [(0, ca)]


#: Owner 24-11 ``QUYET-DINH-OWNER-L3-THCS-LOP-VO-NGHIA``: dòng THCS KHÔNG ghi liên cấp, lớp cuối SỐ NGUYÊN 0 / âm / ≥ 13 ⇒ cũng dừng ở
#: bước ĐẾM (đồng nhất THPT). Thay ca ``test_dong_thcs_lop_13_ngoai_cau_owner_dem_du_nam_hoa_can_xet_tay`` (45ba463a: lớp 13 đếm đủ năm,
#: bước hoà chờ xác minh — tiền đề "owner chỉ nói 10–12" nay hết) và ca ``_DEM_DU_NAM[lop_0_khong_hop_le]`` (f1c9f6ca: lớp 0 đếm đủ năm).
@pytest.mark.parametrize(
    "level, lop",
    [("THCS", 0), ("THCS", -1), ("THCS", 13), ("THCS", 99), (None, 0), (None, 13)],
    ids=["cap_thcs_lop_0", "cap_thcs_lop_am_1", "cap_thcs_lop_13", "cap_thcs_lop_99", "level_trong_lop_0", "level_trong_lop_13"],
)
def test_dong_thcs_khong_ghi_lien_cap_lop_vo_nghia_dung_o_buoc_dem(monkeypatch, level, lop):
    """Dòng T1 (KV1) ``2017→2022`` lớp ``lop`` + dòng THCS hợp lệ T2 ``2022→2023``: dừng ở bước đếm, không tra gì. Trước: T1 góp 5 năm
    ⇒ KV1 lặng lẽ."""
    lich_su = [_thcs(T1, 2017, 2022, lop=lop, level=level), _thcs(T2, 2022, 2023, lop=9)]
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=lich_su))
    _dung_dem_thcs(kv, meta, hoi, [0])


@pytest.mark.parametrize("lop", ["13", 13.0, True], ids=["chuoi_13", "so_thuc_13", "bool"])
def test_doi_chung_dong_thcs_lop_sai_kieu_khong_dung_o_buoc_dem(monkeypatch, lop):
    """Chỉ lớp SỐ NGUYÊN mới dừng ở bước đếm (đồng nhất THPT — ``_history_int``). Lớp sai kiểu ⇒ đếm đủ năm (5 năm KV1 > 1 năm KV2 ⇒
    KV1); ở bước hoà mới cần xét tay (owner 23-11 (a))."""
    lich_su = [_thcs(T1, 2017, 2022, lop=lop), _thcs(T2, 2022, 2023, lop=9)]
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=lich_su))
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV1", "longest_duration", {"KV1": 5, "KV2": 1})


# ═══════════════════════════════ 2. "KV chờ xác minh" — không tính được ═══════════════════════════════
def test_truong_chua_co_trong_danh_muc_go_tay_thi_cho_xac_minh(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_go_tay(2018, 2020), _go_tay(2020, 2022)]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_school_not_in_catalog")
    assert _ca_dung(meta) == [(0, "thcs_entry_without_school"), (1, "thcs_entry_without_school")]


def test_mot_dong_go_tay_lan_dong_co_truong_van_cho_xac_minh(monkeypatch):
    """Không tính KV từ phần còn lại: dòng gõ tay có thể là trường học lâu nhất."""
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2018, 2021), _go_tay(2021, 2022)]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_school_not_in_catalog")


def test_school_id_khong_co_trong_danh_muc_thi_cho_xac_minh(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(99, 2018, 2022)]))
    assert kv is None and hoi == [("dtnt", 99)]
    _cho_xac_minh(meta, "thcs_school_not_in_catalog")


def test_admin_them_truong_vao_danh_muc_thi_tinh_ra_kv(monkeypatch):
    """Owner 22-11: "cán bộ tra cứu và báo admin nhập vào" — trước khi thêm: chờ xác minh; Admin thêm trường (cờ DTNT tắt) + KV
    của xã hiện tại từ năm 2000 ⇒ CÙNG hồ sơ tính ra KV, không sửa gì hồ sơ."""
    hs = _hs(academic_history=[_thcs(50, 2018, 2022)])
    kv, meta, _ = _chay(monkeypatch, hs)
    assert kv is None
    _cho_xac_minh(meta, "thcs_school_not_in_catalog")
    them = {**KV_TRUONG, **{(50, y): "KV2-NT" for y in range(2000, 2031)}}
    kv, meta, _ = _chay(monkeypatch, hs, kv_truong=them, dtnt={**DTNT, 50: False})
    assert (kv, meta["rule_applied"]) == ("KV2-NT", "longest_duration")


def test_truong_dtnt_thi_cho_xac_minh_khong_tu_tinh(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2018, 2020), _thcs(D, 2020, 2022)]))
    assert kv is None
    _cho_xac_minh(meta, "thcs_school_dtnt")
    assert meta["breakdown"]["dtnt_school_ids"] == [D]
    assert [h for h in hoi if h[0] == "truong"] == []  # không tra KV trường nào
    assert ps.kv_pending_verification_kind({"kv_resolved": None, **meta}) == "manual"


def test_truong_co_kv_khong_phu_du_nam_6_9_thi_cho_xac_minh_khong_phai_catalog_gap(monkeypatch):
    """T4 chỉ có KV từ năm học 2020; học 2018 → 2022 ⇒ thiếu 2018, 2019 ⇒ chờ xác minh (KHÔNG ``catalog_gap_school`` — mã nhóm THPT
    chặn nộp)."""
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=[_thcs(T4, 2018, 2022)]))
    assert kv is None
    _cho_xac_minh(meta, "thcs_school_kv_missing")
    assert meta["breakdown"]["missing_lookups"] == [{"school_id": T4, "year": 2018}, {"school_id": T4, "year": 2019}]


def test_truong_khong_co_kv_nam_nao_thi_cho_xac_minh(monkeypatch):
    kv, meta, _ = _chay(monkeypatch, _hs(academic_history=[_thcs(T4, 2015, 2019)]))
    assert kv is None
    _cho_xac_minh(meta, "thcs_school_kv_missing")


def test_khong_co_dong_thcs_thi_cho_xac_minh(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_history_missing")


@pytest.mark.parametrize(
    "dong, ca",
    [
        (_thcs(T1, 2018, 2018), "zero_length_entry"),
        (_go_tay(2021, 2021), "zero_length_entry"),
        (_thcs(P, 2018, 2022, level="THPT"), "school_level_mismatch"),
        (_thcs(T1, 2018, 2022, trinh_do="THPT"), "school_level_mismatch"),
        (_go_tay(2018, 2022, trinh_do=None), "entry_level_unknown"),
        (_thcs(T1, 2018, 2022, level="THCS_THPT", trinh_do=None), "lien_cap_missing_grade_to"),
        (_thcs(T1, None, 2022), "entry_years_invalid"),
        (_thcs("11", 2018, 2022), "thcs_entry_school_id_invalid"),
    ],
    ids=["y_y", "y_y_go_tay", "chon_truong_cap_thpt", "cap_thcs_trinh_do_thpt", "trong_ca_hai", "lien_cap_thieu_lop",
         "thieu_nam", "school_id_chuoi"],
)
def test_dong_thcs_khong_hop_le_thi_cho_xac_minh_co_nhan(monkeypatch, dong, ca):
    kv, meta, hoi = _chay(monkeypatch, _hs(academic_history=[_thcs(T1, 2018, 2021), dong]))
    assert kv is None and hoi == []
    _cho_xac_minh(meta, "thcs_history_inconsistent")
    assert _ca_dung(meta) == [(1, ca)]


# ═══════════════════════════════ 3. Nhãn hộ khẩu đặc biệt · ấn định tay · sơ cấp · nhánh cũ ═══════════════════════════════
def test_nhan_ho_khau_dac_biet_khong_la_can_cu_cho_trung_cap_sau_thcs(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, _hs(area_resolution_basis="permanent_address_special", permanent_commune_code="X2"))
    assert (kv, meta["basis"]) == ("KV1", "LICH_SU_THCS")
    assert all(h[0] != "xa" for h in hoi)


@pytest.mark.parametrize(
    "kw, tl, at",
    [
        (dict(cultural_education_level=None), "so_cap", "chinh_quy"),
        (dict(), "so_cap", "chinh_quy"),
        (dict(), None, None),
        (dict(cultural_education_level="completed_thcs", vocational_qualification="so_cap"), None, None),
    ],
    ids=["so_cap_khong_van_hoa", "so_cap", "nhanh_cu_tn_thcs", "nhanh_cu_hoan_thanh_thcs"],
)
@pytest.mark.parametrize("nhan", [None, "permanent_address_special"], ids=["khong_nhan", "nhan_dac_biet"])
def test_so_cap_va_nhanh_cu_khong_truyen_trinh_do_cho_xac_minh(monkeypatch, kw, tl, at, nhan):
    kv, meta, hoi = _chay(monkeypatch, _hs(area_resolution_basis=nhan, **kw), tl=tl, at=at)
    assert (kv, meta["basis"], meta["pathway"], hoi) == (None, "PENDING_VERIFICATION", "cho_xac_minh", [])
    _cho_xac_minh(meta, "kv_basis_needs_manual_verification")
    assert ps.kv_pending_verification_kind({"kv_resolved": None, **meta}) == "manual"


def test_an_dinh_tay_thang_luat_l3(monkeypatch):
    _, meta, hoi = _chay(monkeypatch, _hs(area_resolution_basis="manual_override", academic_history=[_go_tay(2018, 2022)]))
    assert (meta["basis"], meta["rule_applied"], hoi) == ("MANUAL", "manual_override", [])


@pytest.mark.parametrize(
    "kw, tl, at, basis, rule",
    [
        # Rà §6 (owner 22-11 L3A câu 5): nhánh CÒN LẠI cho em đã xong THPT mà lấy hộ khẩu — CĐ liên thông "khối lượng VH THPT + TC"
        # KHÔNG có lịch sử THPT — GIỮ (chưa có quyết định).
        (dict(cultural_education_level="completed_thpt", vocational_qualification="trung_cap", academic_history=[]),
         "cao_dang", "lien_thong", "THUONG_TRU", "commune_lookup"),
        # Nhãn hộ khẩu đặc biệt ngoài ba nhóm L3 vẫn như cũ.
        (dict(cultural_education_level="graduated_thpt", area_resolution_basis="permanent_address_special",
              permanent_commune_code="X2"), "cao_dang", "chinh_quy", "COMMUNE_SPECIAL", "commune_lookup"),
        # Trung cấp sau THPT: luật THPT không đổi.
        (dict(cultural_education_level="graduated_thpt",
              academic_history=[{"level": "THPT", "school_id": T2, "year_from": 2022, "year_to": 2025}]),
         "trung_cap", "chinh_quy", "LICH_SU_THPT", "longest_duration"),
    ],
    ids=["cd_lien_thong_khong_lich_su_thpt", "cao_dang_nhan_dac_biet", "trung_cap_sau_thpt"],
)
def test_doi_chung_ngoai_ba_nhom_khong_doi(monkeypatch, kw, tl, at, basis, rule):
    _, meta, _ = _chay(monkeypatch, _hs(**kw), tl=tl, at=at)
    assert (meta["basis"], meta["rule_applied"]) == (basis, rule)


# ═══════════════════════════════ 3b. Nhánh cũ "hoàn thành THPT" ⇒ cách tính nhóm THPT (owner 22-11 L3A câu 5) ═══════════════════════════════
_THPT_T2 = [{"level": "THPT", "graduation_type": "THPT", "school_id": T2, "year_from": 2022, "year_to": 2025}]


@pytest.mark.parametrize("chuyen_mon", ["none", "so_cap"])
def test_nhanh_cu_hoan_thanh_thpt_tinh_theo_truong_thpt(monkeypatch, chuyen_mon):
    hs = _hs(cultural_education_level="completed_thpt", vocational_qualification=chuyen_mon, academic_history=_THPT_T2)
    kv, meta, hoi = _chay(monkeypatch, hs, tl=None, at=None)
    assert (kv, meta["basis"], meta["basis_reason"], meta["rule_applied"]) == (
        "KV2", "LICH_SU_THPT", "legacy_thpt_pathway", "longest_duration",
    )
    assert hoi == [("truong", T2, 2022), ("truong", T2, 2023), ("truong", T2, 2024)]  # không tra xã thường trú


def test_nhanh_cu_hoan_thanh_thpt_khong_lich_su_thpt_thi_dung_nhu_nhom_thpt(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, _hs(cultural_education_level="completed_thpt", academic_history=[]), tl=None, at=None)
    assert (kv, meta["rule_applied"], hoi) == (None, "insufficient_data", [])
    assert ps.kv_snapshot_blocks_submit({"kv_resolved": None, **meta})  # nhóm THPT: cổng nộp chặn như cũ


def test_nhanh_cu_hoan_thanh_thpt_nhan_dac_biet_van_thang(monkeypatch):
    """Là nhóm THPT ⇒ nhãn hộ khẩu đặc biệt vẫn là căn cứ (L3 câu 2 chỉ cho ba nhóm)."""
    hs = _hs(cultural_education_level="completed_thpt", area_resolution_basis="permanent_address_special",
             permanent_commune_code="X2", academic_history=_THPT_T2)
    kv, meta, _ = _chay(monkeypatch, hs, tl=None, at=None)
    assert (kv, meta["basis"]) == ("KV2-NT", "COMMUNE_SPECIAL")


def test_nhanh_cu_hoan_thanh_thpt_ho_so_cu_theo_co(monkeypatch):
    anh = {"kv_resolved": "KV1", "rule_applied": "commune_lookup", "basis": "THUONG_TRU",
           "basis_reason": "legacy_completed_thpt_no_vocational"}
    hs = _hs(cultural_education_level="completed_thpt", priority_resolution_snapshot=anh, academic_history=_THPT_T2)
    monkeypatch.setattr(settings, "KV_L3_APPLY_TO_EXISTING_ENABLED", False)
    kv, meta, _ = _chay(monkeypatch, hs, tl=None, at=None)
    assert (kv, meta["basis"], meta["basis_reason"]) == ("KV1", "THUONG_TRU", "legacy_completed_thpt_no_vocational")
    monkeypatch.setattr(settings, "KV_L3_APPLY_TO_EXISTING_ENABLED", True)
    kv, meta, _ = _chay(monkeypatch, hs, tl=None, at=None)
    assert (kv, meta["basis"]) == ("KV2", "LICH_SU_THPT")


# ═══════════════════════════════ 4. Hồ sơ cũ — cờ KV_L3_APPLY_TO_EXISTING_ENABLED (câu 1) ═══════════════════════════════
def _anh_cu(basis="THUONG_TRU", ly_do="tc_chinh_quy_post_thcs_uses_commune", kv="KV2-NT"):
    return {"kv_resolved": kv, "rule_applied": "commune_lookup", "basis": basis, "basis_reason": ly_do,
            "target_level": "trung_cap", "admission_type": "chinh_quy"}


def test_ho_so_cu_co_tat_giu_luat_cu_va_on_dinh(monkeypatch):
    monkeypatch.setattr(settings, "KV_L3_APPLY_TO_EXISTING_ENABLED", False)
    hs = _hs(permanent_commune_code="X2", priority_resolution_snapshot=_anh_cu())
    kv, meta, hoi = _chay(monkeypatch, hs)
    assert (kv, meta["rule_applied"], hoi) == ("KV2-NT", "commune_lookup", [("xa", "X2", NAM)])
    # Lần chụp sau tái tạo ĐÚNG cặp luật cũ ⇒ vẫn là hồ sơ cũ.
    assert ps.kv_l3_keeps_legacy_rule({**meta, "kv_resolved": kv})


def test_ho_so_cu_nhan_dac_biet_co_tat_giu_luat_cu(monkeypatch):
    monkeypatch.setattr(settings, "KV_L3_APPLY_TO_EXISTING_ENABLED", False)
    hs = _hs(area_resolution_basis="permanent_address_special", permanent_commune_code="X2",
             priority_resolution_snapshot=_anh_cu("COMMUNE_SPECIAL", "permanent_address_special_override"))
    kv, meta, _ = _chay(monkeypatch, hs)
    assert (kv, meta["basis"]) == ("KV2-NT", "COMMUNE_SPECIAL")


def test_bat_co_thi_ho_so_cu_theo_luat_moi(monkeypatch):
    monkeypatch.setattr(settings, "KV_L3_APPLY_TO_EXISTING_ENABLED", True)
    hs = _hs(permanent_commune_code="X2", priority_resolution_snapshot=_anh_cu())
    kv, meta, _ = _chay(monkeypatch, hs)
    assert (kv, meta["basis"]) == ("KV1", "LICH_SU_THCS")


@pytest.mark.parametrize(
    "anh",
    [None, {}, {"kv_resolved": None, "rule_applied": "kv_pending_verification", "basis": "LICH_SU_THCS",
                 "basis_reason": "tc_chinh_quy_post_thcs_uses_thcs_school_history"},
     {"kv_resolved": "KV1", "rule_applied": "commune_lookup", "pathway": "thuong_tru"}],
    ids=["chua_chup", "rong", "anh_luat_moi", "anh_khong_co_can_cu"],
)
def test_ho_so_khong_phai_ho_so_cu_theo_luat_moi_khi_co_tat(monkeypatch, anh):
    monkeypatch.setattr(settings, "KV_L3_APPLY_TO_EXISTING_ENABLED", False)
    kv, meta, _ = _chay(monkeypatch, _hs(priority_resolution_snapshot=anh))
    assert (kv, meta["basis"]) == ("KV1", "LICH_SU_THCS")


def test_ho_so_cu_ngoai_ba_nhom_khong_bi_doi(monkeypatch):
    """Cặp luật cũ trên hồ sơ nay ngoài ba nhóm (vd đổi sang văn hoá THPT) ⇒ theo ma trận hiện tại, không giữ gì."""
    monkeypatch.setattr(settings, "KV_L3_APPLY_TO_EXISTING_ENABLED", False)
    hs = _hs(cultural_education_level="graduated_thpt", priority_resolution_snapshot=_anh_cu(),
             academic_history=[{"level": "THPT", "school_id": T3, "year_from": 2022, "year_to": 2025}])
    _, meta, _ = _chay(monkeypatch, hs)
    assert meta["basis"] == "LICH_SU_THPT"


# ═══════════════════════════════ 5. Cổng nộp · T6 · F231 · căn cứ ═══════════════════════════════
def _anh(rule, kv=None, **kw):
    return {"kv_resolved": kv, "rule_applied": rule, **kw}


def test_cong_nop_cho_qua_rieng_cho_xac_minh():
    from app.services.admission_service import _kv_unresolved_error_message

    assert _kv_unresolved_error_message(_anh("kv_pending_verification", reason="thcs_school_not_in_catalog"), 1) is None
    # Mọi mã khác ngoài whitelist vẫn chặn — không nới mã nào của nhóm THPT.
    for ma in ("catalog_gap_school", "insufficient_data", "ambiguous_requires_manual", "catalog_gap_commune",
               "address_not_normalized", "manual_override_unverified", "not_resolved", None):
        assert _kv_unresolved_error_message(_anh(ma), 1) is not None, ma
    assert _kv_unresolved_error_message({}, 1) is not None


def test_cho_xac_minh_van_la_chua_phan_giai_voi_t6_va_ban_in():
    snap = _anh("kv_pending_verification")
    assert not ps.kv_snapshot_resolved(snap) and ps.kv_snapshot_pending_verification(snap)
    assert "kv_pending_verification" not in ps.KV_SUCCESS_RULE_APPLIED


@pytest.mark.parametrize(
    "snap, kind, cum",
    [
        (_anh("kv_pending_verification", pathway="lich_su_thcs", reason="thcs_school_not_in_catalog"), "thcs_history",
         "báo Admin thêm trường"),
        (_anh("kv_pending_verification", pathway="lich_su_thcs", reason="thcs_school_dtnt"), "manual", "ấn định"),
        (_anh("kv_pending_verification", pathway="cho_xac_minh", reason="kv_basis_needs_manual_verification"), "manual",
         "ấn định"),
    ],
    ids=["thcs_chua_co_truong", "thcs_dtnt", "so_cap"],
)
def test_t6_dung_co_nhan_kv_cho_xac_minh(snap, kind, cum):
    from app.utils.exceptions import PriorityKvUnresolved

    assert ps.kv_pending_verification_kind(snap) == kind
    with pytest.raises(PriorityKvUnresolved) as loi:
        asyncio.run(ps._resolve_area_bonus(None, SimpleNamespace(id=7, priority_resolution_snapshot=snap), NAM))
    assert loi.value.error_code == "PRIORITY_KV_UNRESOLVED"
    assert "đang chờ xác minh" in loi.value.detail and cum in loi.value.detail
    assert loi.value.public_payload == {"rule_applied": "kv_pending_verification", "reason": snap["reason"]}


def test_t6_ma_khac_giu_cau_cu():
    from app.utils.exceptions import PriorityKvUnresolved

    with pytest.raises(PriorityKvUnresolved) as loi:
        asyncio.run(ps._resolve_area_bonus(None, SimpleNamespace(id=7, priority_resolution_snapshot=_anh(
            "catalog_gap_school", reason="all_school_lookups_failed")), NAM))
    assert "chờ xác minh" not in loi.value.detail
    assert loi.value.detail.startswith("Chưa xác định được khu vực ưu tiên (catalog_gap_school")


def test_f231_ban_gd2b_ma_rieng_cho_xac_minh():
    from app.services import area_check_rules as r

    hs = _hs()
    chung = dict(area_resolution_basis=None, profile=hs, manual_audit_row=None, commune_kv={}, school_kv={},
                 open_area_rate_rows=[])
    assert r.area_check(kv_snapshot=_anh("kv_pending_verification"), **chung) == ("khu_vuc_cho_xac_minh", None)
    assert r.area_check(kv_snapshot=_anh("catalog_gap_school"), **chung) == ("thieu_khu_vuc", None)
    assert "khu_vuc_cho_xac_minh" in r.AREA_REASON_CODES


def test_f231_ban_gd2b_thieu_ban_do_dtnt_thi_khong_tinh_lai_duoc():
    """Đường lô không nạp cờ DTNT ⇒ bộ quyết định gặp khoá vắng ⇒ ``khu_vuc_khong_tinh_lai_duoc`` (fail-closed); nạp đủ ⇒ qua."""
    from app.services import area_check_rules as r

    hs = _hs(priority_resolution_snapshot=_anh("longest_duration", "KV1", target_level="trung_cap",
                                               admission_type="chinh_quy"))
    xa_k, truong_k = ps.kv_lookup_keys(hs, target_level="trung_cap", admission_type="chinh_quy")
    chung = dict(kv_snapshot=hs.priority_resolution_snapshot, area_resolution_basis=None, profile=hs, manual_audit_row=None,
                 commune_kv={}, school_kv={k: KV_TRUONG.get(k) for k in truong_k},
                 open_area_rate_rows=[("KV1", "0.75")])
    assert r.area_check(**chung) == ("khu_vuc_khong_tinh_lai_duoc", None)
    assert r.area_check(**chung, school_dtnt={T1: False}) == (None, "0.75")


def test_ly_do_chan_f231_co_cau_hien_thi():
    from app.services import area_check_rules as r
    from app.services import council_set_gate_service as g

    assert "chờ xác minh" in g.BLOCK_REASONS["khu_vuc_cho_xac_minh"]
    assert set(r.AREA_REASON_CODES) <= set(g.BLOCK_REASONS)


def test_bang_can_cu_co_ma_cho_xac_minh():
    from app.constants.priority_law_citation import RULE_LAW_CITATION_BY_CIRCULAR

    for bang in RULE_LAW_CITATION_BY_CIRCULAR.values():
        assert ps.KV_PENDING_VERIFICATION_RULE in bang and bang[ps.KV_PENDING_VERIFICATION_RULE] is None


def test_mot_ham_ho_so_cu_cho_moi_duong():
    """Câu 1 / Phần C mục 4: MỘT hàm ``kv_l3_keeps_legacy_rule``, gọi ĐÚNG một chỗ (``_derive_kv_basis_level``) — mọi đường (nộp,
    T6, xem trước, bản in GĐ1, máy xét GĐ2-B) đi qua chỗ ấy với ảnh chụp đang có của hồ sơ."""
    import inspect
    import re

    nguon = inspect.getsource(ps)
    assert len(re.findall(r"kv_l3_keeps_legacy_rule\(", nguon)) == 2  # định nghĩa + một lời gọi
    assert len(re.findall(r"previous_snapshot=getattr\(profile, \"priority_resolution_snapshot\", None\)", nguon)) == 2


# ═══════════════════════════════ 6. Ấn định tay khi hồ sơ còn nháp (Phần C mục 2) ═══════════════════════════════
async def _ngu_canh(profile_arg, db_arg):
    return {"target_level": "trung_cap", "admission_type": "chinh_quy"}


def _db_gia():
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _nhap(lich_su):
    return _hs(status="draft", version=3, lead_id=100, academic_history=lich_su,
               priority_resolution_snapshot={"kv_resolved": None, "rule_applied": "kv_pending_verification",
                                             "requires_manual_override": True, "reason": "thcs_school_dtnt"})


def _tra_gia(monkeypatch):
    async def _truong(db, sid, nam):
        return KV_TRUONG.get((sid, nam))

    async def _dtnt(db, sid):
        return DTNT.get(sid)

    monkeypatch.setattr(ps, "derive_profile_target_context", _ngu_canh)
    monkeypatch.setattr(ps, "lookup_kv_for_school_year", _truong)
    monkeypatch.setattr(ps, "lookup_school_is_dtnt", _dtnt)


async def test_an_dinh_tay_ho_so_nhap_dien_dtnt_duoc_mo(monkeypatch):
    """Máy tính lại TRỰC TIẾP (không giả ``resolve_kv_for_profile``) ra "chờ xác minh" ⇒ cổng nháp coi là CHƯA tính ra ⇒ cho ấn định."""
    from app.services.priority_override_service import override_kv

    _tra_gia(monkeypatch)
    hs = _nhap([_thcs(D, 2018, 2022)])
    moi, _ = await override_kv(_db_gia(), hs, kv_resolved="KV1", reason="Học sinh PT DTNT, hộ khẩu xã KV1 — học bạ + giấy cư trú",
                               evidence_file_id=None, actor=SimpleNamespace(id=7, role="manager", full_name="Quản lý"),
                               expected_version=3)
    assert (moi.priority_resolution_snapshot["kv_resolved"], moi.area_resolution_basis) == ("KV1", "manual_override")


async def test_an_dinh_tay_ho_so_nhap_bi_tu_choi_khi_may_tinh_ra(monkeypatch):
    """Đối chứng: cùng hồ sơ nhưng trường THCS thường (máy tính ra KV) ⇒ cổng nháp TỪ CHỐI."""
    from app.services.priority_override_service import override_kv
    from app.utils.exceptions import BusinessRuleViolation

    _tra_gia(monkeypatch)
    with pytest.raises(BusinessRuleViolation):
        await override_kv(_db_gia(), _nhap([_thcs(T1, 2018, 2022)]), kv_resolved="KV2",
                          reason="Thử ấn định khi máy đã tính ra được khu vực", evidence_file_id=None,
                          actor=SimpleNamespace(id=7, role="manager", full_name="Quản lý"), expected_version=3)
