# tests/unit/test_priority_kv_lien_cap_g5.py
"""G5 — luật học nhiều trường: MỘT quy ước năm (khoá = NĂM BẮT ĐẦU của năm học) + mục liên cấp chỉ tính lớp 10–12.

Căn cứ (owner):
* 11-10: ``bang-chung/QUYET-DINH-OWNER-2026-10-11-TRA-LOI-DANH-SACH-CAU-HOI-v2.md`` T5c "Chỉ tính THPT";
  ``bang-chung/QUYET-DINH-OWNER-2026-10-11-TRA-LOI-V3.md`` Q8 "Suy 3 năm cuối"; ``bang-chung/QUYET-DINH-OWNER-2026-10-11-Q15-Q18.md``
  Q15(b) (mục k năm học tính k năm, mục 0 năm dừng);
* 22-11: ``logs-P5/cong-bo-ket-qua/gd2/QUYET-DINH-OWNER-KV-NAM-THUC-HOC-VA-L3-2026-11-22.md`` mục 1–2 (khoá năm học = năm bắt đầu;
  THPT 2022 → tốt nghiệp 2025 chỉ tra 2022, 2023, 2024; liên cấp thiếu lớp kết thúc ⇒ dừng);
  ``…/QUYET-DINH-OWNER-G5-HAS-THPT-HISTORY-2026-11-22.md`` (``_has_thpt_history`` dùng chung luật lớp 10–12).

Giá trị mong đợi VIẾT TAY. Hàm đọc danh mục KV trường được thay bằng bảng tra trong bộ nhớ (ghi lại từng lần hỏi); không CSDL.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import priority_service as ps

pytestmark = pytest.mark.unit

A, B = 1, 2


def _danh_muc(doi_tu=None):
    """KV trường giả theo khoá năm học (năm bắt đầu). ``doi_tu``: {trường: (năm bắt đầu đổi, KV mới)}."""
    goc = {A: "KV1", B: "KV3"}
    out = {}
    for sid, kv in goc.items():
        for nam in range(2010, 2031):
            out[(sid, nam)] = kv
    for sid, (tu, kv_moi) in (doi_tu or {}).items():
        for nam in range(tu, 2031):
            out[(sid, nam)] = kv_moi
    return out


def _lc(sid, tu, den, lop=None):
    muc = {"level": "THCS_THPT", "school_id": sid, "year_from": tu, "year_to": den}
    if lop is not None:
        muc["grade_to"] = lop
    return muc


def _thpt(sid, tu, den, lop=12):
    return {"level": "THPT", "school_id": sid, "year_from": tu, "year_to": den, "grade_to": lop}


def _chay(monkeypatch, lich_su, danh_muc=None):
    bang = danh_muc if danh_muc is not None else _danh_muc()
    hoi = []

    async def _tra(db, sid, nam):
        hoi.append((sid, nam))
        return bang.get((sid, nam))

    monkeypatch.setattr(ps, "lookup_kv_for_school_year", _tra)
    ho_so = SimpleNamespace(
        id=1,
        academic_year=2026,
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        area_resolution_basis=None,
        permanent_commune_code=None,
        academic_history=lich_su,
    )
    kv, meta = asyncio.run(ps.resolve_kv_for_profile(ho_so, db=None))
    return kv, meta, hoi


# ═══════════════════════════════ quy ước năm: khoá = năm bắt đầu ═══════════════════════════════
def test_thpt_2022_tot_nghiep_2025_chi_tra_ba_nam_hoc_thuc_hoc(monkeypatch):
    _, meta, hoi = _chay(monkeypatch, [_thpt(A, 2022, 2025)])
    assert hoi == [(A, 2022), (A, 2023), (A, 2024)], hoi
    assert meta["breakdown"]["winner_years"] == 3


def test_kv_truong_doi_tu_nam_hoc_2025_2026_khong_anh_huong_em_tot_nghiep_2025(monkeypatch):
    """Ca BẮT BUỘC (owner 22-11): trường A đổi KV1 → KV3 từ khoá 2025 (năm học 2025–2026). Em học A 2022 → tốt nghiệp 2025 ⇒ KV1."""
    kv, meta, hoi = _chay(monkeypatch, [_thpt(A, 2022, 2025)], _danh_muc({A: (2025, "KV3")}))
    assert (kv, meta["rule_applied"]) == ("KV1", "longest_duration"), meta
    assert (A, 2025) not in hoi, hoi


def test_hoa_tra_truong_tot_nghiep_o_nam_hoc_cuoi(monkeypatch):
    """Hoà 2–2 ⇒ trường tốt nghiệp B (2025, lớp 12) tra ở khoá 2024 (năm học cuối 2024–2025). KV của B đổi từ khoá 2025 KHÔNG được dùng.
    A (KV1) 2021 → 2023 lớp 11 ⇒ 2021, 2022; B 2023 → 2025 ⇒ 2023, 2024 (KV3 tới 2024, KV2 từ 2025) ⇒ KV3."""
    kv, meta, hoi = _chay(
        monkeypatch, [_thpt(A, 2021, 2023, 11), _thpt(B, 2023, 2025)], _danh_muc({B: (2025, "KV2")})
    )
    assert (kv, meta["rule_applied"]) == ("KV3", "tiebreak_graduation_school"), meta
    assert hoi[-1] == (B, 2024) and (B, 2025) not in hoi, hoi


def test_muc_0_nam_hoc_thi_dung_co_nhan(monkeypatch):
    """Q15(b): mục ``year_from == year_to`` (0 năm học) ⇒ DỪNG, liệt kê mục lệch, không tra danh mục."""
    kv, meta, hoi = _chay(monkeypatch, [_thpt(A, 2020, 2023), _thpt(B, 2023, 2023)])
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "insufficient_data", "history_entries_inconsistent"), meta
    assert [(m["index"], m["case"]) for m in meta["breakdown"]["entries"]] == [(1, "zero_length_entry")]
    assert hoi == []


# ═══════════════════════════════ liên cấp: chỉ lớp 10–12 ═══════════════════════════════
def test_vi_du_owner_lop_6_toi_het_lop_10_roi_lop_11_12(monkeypatch):
    """Owner 22-11: A lớp 6 tới hết lớp 10 (``2017→2022``), B lớp 11–12 (``2022→2024``) ⇒ A 1 năm (2021), B 2 năm ⇒ KV3."""
    kv, meta, hoi = _chay(monkeypatch, [_lc(A, 2017, 2022, 10), _thpt(B, 2022, 2024)])
    assert (kv, meta["rule_applied"]) == ("KV3", "longest_duration"), meta
    assert meta["breakdown"]["kv_totals"] == {"KV1": 1, "KV3": 2}, meta["breakdown"]
    assert [h for h in hoi if h[0] == A] == [(A, 2021)], hoi


def test_lien_cap_tron_6_12_ba_lan_tra_cho_ba_nam(monkeypatch):
    """Liên cấp lớp 6–12 ``2016→2023`` ⇒ chỉ lớp 10–12: 2020, 2021, 2022 (3 lần tra cho 3 năm) — như THPT ``2020→2023``."""
    _, _, lien_cap = _chay(monkeypatch, [_lc(A, 2016, 2023, 12)])
    _, _, thpt = _chay(monkeypatch, [_thpt(A, 2020, 2023)])
    assert lien_cap == thpt == [(A, 2020), (A, 2021), (A, 2022)]


def test_lien_cap_ngan_khong_dem_truoc_nam_vao_hoc(monkeypatch):
    """Vào trường liên cấp ở lớp 11 (``2023→2025``, lớp 12): phần lớp 10–12 suy ra từ 2022 bị chặn ở năm vào học ⇒ 2023, 2024."""
    kv, meta, hoi = _chay(monkeypatch, [_lc(A, 2023, 2025, 12)])
    assert kv == "KV1" and hoi == [(A, 2023), (A, 2024)], (meta, hoi)


def test_hoa_sau_khi_cat_lay_truong_tot_nghiep(monkeypatch):
    """Liên cấp A lớp 6–11 ``2016→2022`` ⇒ 2020, 2021; THPT B ``2022→2024`` ⇒ 2022, 2023 ⇒ hoà ⇒ tốt nghiệp B ⇒ KV3."""
    kv, meta, _ = _chay(monkeypatch, [_lc(A, 2016, 2022, 11), _thpt(B, 2022, 2024)])
    assert (kv, meta["rule_applied"]) == ("KV3", "tiebreak_graduation_school"), meta
    assert meta["breakdown"]["kv_totals"] == {"KV1": 2, "KV3": 2}, meta["breakdown"]


def test_lien_cap_lop_9_tro_xuong_bo_qua(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, [_lc(A, 2016, 2020, 9), _thpt(B, 2020, 2023)])
    assert kv == "KV3" and meta["breakdown"]["kv_totals"] == {"KV3": 3}, meta
    assert not [h for h in hoi if h[0] == A], hoi


def test_chi_co_lien_cap_lop_9_thi_khong_co_muc_dem(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, [_lc(A, 2016, 2020, 9)])
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "insufficient_data", "no_qualifying_thpt_history_entries")
    assert hoi == []


@pytest.mark.parametrize("lop", [None, 13, True, "12"], ids=["thieu", "ngoai_1_12", "bool", "chuoi"])
def test_lien_cap_thieu_lop_ket_thuc_thi_dung(monkeypatch, lop):
    """Owner 22-11: liên cấp THIẾU (hoặc sai) lớp kết thúc ⇒ DỪNG, báo thiếu dữ liệu — không đếm, không tự xác định KV."""
    muc = _lc(A, 2016, 2023)
    if lop is not None:
        muc["grade_to"] = lop
    kv, meta, hoi = _chay(monkeypatch, [muc, _thpt(B, 2020, 2023)])
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "insufficient_data", "history_entries_inconsistent"), meta
    assert [(m["index"], m["case"]) for m in meta["breakdown"]["entries"]] == [(0, "lien_cap_missing_grade_to")]
    assert hoi == []


@pytest.mark.parametrize(
    "muc, nam",
    [
        (_thpt(A, 2022, 2025), [2022, 2023, 2024]),
        ({"level": "GDTX", "school_id": A, "year_from": 2018, "year_to": 2021}, [2018, 2019, 2020]),
        (_thpt(A, 2022, 2023), [2022]),
        (_lc(A, 2016, 2023, 12), [2020, 2021, 2022]),
        (_lc(A, 2016, 2023, 11), [2021, 2022]),
        (_lc(A, 2016, 2023, 10), [2022]),
        (_lc(A, 2022, 2023, 12), [2022]),
    ],
    ids=["thpt_3_nam", "gdtx_3_nam", "thpt_1_nam", "lc_lop12", "lc_lop11", "lc_lop10", "lc_ngan"],
)
def test_khoa_nam_hoc_cua_muc(muc, nam):
    assert list(ps.kv_entry_school_years(muc)) == nam
    assert ps.kv_last_school_year(muc) == muc["year_to"] - 1


# ═══════════════════════════════ ``_has_thpt_history`` — cùng luật lớp 10–12 ═══════════════════════════════
def _can_cu_cd_lien_thong(lich_su):
    """Nhánh lai CĐ liên thông "khối lượng VH THPT + TC": có lịch sử THPT ⇒ LICH_SU_THPT; không ⇒ THUONG_TRU."""
    basis, _ = ps._derive_kv_basis_level(
        cultural="completed_thpt",
        vocational="trung_cap",
        target_level="cao_dang",
        admission_type="lien_thong",
        academic_history=lich_su,
    )
    return basis


def test_cd_lien_thong_lien_cap_lop_6_9_la_thuong_tru():
    assert ps._has_thpt_history([_lc(A, 2016, 2020, 9)]) is False
    assert _can_cu_cd_lien_thong([_lc(A, 2016, 2020, 9)]) == "THUONG_TRU"


def test_cd_lien_thong_lien_cap_lop_6_11_la_lich_su_thpt():
    assert ps._has_thpt_history([_lc(A, 2016, 2022, 11)]) is True
    assert _can_cu_cd_lien_thong([_lc(A, 2016, 2022, 11)]) == "LICH_SU_THPT"


def test_cd_lien_thong_doi_chung_muc_thpt_thuong():
    assert _can_cu_cd_lien_thong([_thpt(A, 2020, 2023)]) == "LICH_SU_THPT"


def test_cd_lien_thong_lien_cap_thieu_lop_khong_lang_le_ve_thuong_tru(monkeypatch):
    """Liên cấp thiếu lớp: không loại được phần THPT ⇒ vẫn là "có lịch sử THPT" ⇒ LICH_SU_THPT ⇒ phép đếm DỪNG có nhãn (không rơi
    lặng lẽ về thường trú)."""
    assert _can_cu_cd_lien_thong([_lc(A, 2016, 2023)]) == "LICH_SU_THPT"


def test_mot_vi_tu_cho_phep_dem_va_has_thpt_history():
    """Một nguồn (CLAUDE.md §7): mục được ``_has_thpt_history`` tính ⇔ mục vào tập đếm (khi có đủ hai năm)."""
    mau = [
        _thpt(A, 2020, 2023),
        _lc(A, 2016, 2020, 9),
        _lc(A, 2016, 2022, 11),
        _lc(A, 2016, 2023),
        {"level": "THCS", "school_id": A, "year_from": 2016, "year_to": 2020, "grade_to": 9},
        {"level": "THPT", "year_from": 2020, "year_to": 2023},
    ]
    for muc in mau:
        assert ps._has_thpt_history([muc]) is ps.kv_history_basis_entry(muc), muc
