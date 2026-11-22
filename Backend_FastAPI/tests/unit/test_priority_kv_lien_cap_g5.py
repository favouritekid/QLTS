# tests/unit/test_priority_kv_lien_cap_g5.py
"""G5 — luật học nhiều trường: MỘT quy ước năm (khoá = NĂM BẮT ĐẦU của năm học) + mục liên cấp chỉ tính lớp 10–12.

Căn cứ (owner):
* 11-10: ``bang-chung/QUYET-DINH-OWNER-2026-10-11-TRA-LOI-DANH-SACH-CAU-HOI-v2.md`` T5c "Chỉ tính THPT";
  ``bang-chung/QUYET-DINH-OWNER-2026-10-11-TRA-LOI-V3.md`` Q8 "Suy 3 năm cuối"; ``bang-chung/QUYET-DINH-OWNER-2026-10-11-Q15-Q18.md``
  Q15(b) (mục k năm học tính k năm, mục 0 năm dừng);
* 22-11: ``logs-P5/cong-bo-ket-qua/gd2/QUYET-DINH-OWNER-KV-NAM-THUC-HOC-VA-L3-2026-11-22.md`` mục 1–2 (khoá năm học = năm bắt đầu;
  THPT 2022 → tốt nghiệp 2025 chỉ tra 2022, 2023, 2024; liên cấp thiếu lớp kết thúc ⇒ dừng);
  ``…/QUYET-DINH-OWNER-G5-HAS-THPT-HISTORY-2026-11-22.md`` (``_has_thpt_history`` dùng chung luật lớp 10–12);
  ``…/g5/QUYET-DINH-OWNER-G5-NUT-THEM-NHANH-VA-DO-2026-11-22.md`` mục C (test theo CẶP với nút thêm nhanh ở giao diện) + Codex G5
  lượt 1 (``…/g5/KET-QUA-CODEX-GON-G5-2026-11-22.md`` P1, P4, P5).

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


def _chay(monkeypatch, lich_su, danh_muc=None, *, target_level=None, admission_type=None, **cot):
    """Chạy ``resolve_kv_for_profile`` thật trên hồ sơ giả; ``cot`` đè cột hồ sơ (vd trình độ văn hoá / chuyên môn)."""
    bang = danh_muc if danh_muc is not None else _danh_muc()
    hoi = []

    async def _tra(db, sid, nam):
        hoi.append((sid, nam))
        return bang.get((sid, nam))

    monkeypatch.setattr(ps, "lookup_kv_for_school_year", _tra)
    cot_ho_so = dict(
        id=1,
        academic_year=2026,
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        area_resolution_basis=None,
        permanent_commune_code=None,
        academic_history=lich_su,
    )
    cot_ho_so.update(cot)
    ho_so = SimpleNamespace(**cot_ho_so)
    kv, meta = asyncio.run(
        ps.resolve_kv_for_profile(ho_so, db=None, target_level=target_level, admission_type=admission_type)
    )
    return kv, meta, hoi


def _lech(meta):
    return [(m["index"], m["case"]) for m in meta["breakdown"]["entries"]]


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
    # Codex G5 P1: kết quả chi tiết ghi năm thực sự đem tra (khoá năm học cuối), cạnh năm tốt nghiệp ``year_to`` như cũ.
    assert (meta["breakdown"]["graduation_year"], meta["breakdown"]["graduation_lookup_year"]) == (2025, 2024), meta


def test_muc_0_nam_hoc_thi_dung_co_nhan(monkeypatch):
    """Q15(b): mục ``year_from == year_to`` (0 năm học) ⇒ DỪNG, liệt kê mục lệch, không tra danh mục."""
    kv, meta, hoi = _chay(monkeypatch, [_thpt(A, 2020, 2023), _thpt(B, 2023, 2023)])
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "insufficient_data", "history_entries_inconsistent"), meta
    assert [(m["index"], m["case"]) for m in meta["breakdown"]["entries"]] == [(1, "zero_length_entry")]
    assert hoi == []


# ═══════════════════════════════ CẶP với nút thêm nhanh ở giao diện (owner 22-11 mục C) ═══════════════════════════════
#: Chép NGUYÊN từ ``frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/AcademicHistoryTab.test.tsx``
#: (``CAP_FE_NUT_THEM_NHANH_2022``): cán bộ gõ "Năm bắt đầu lớp 10" = 2022, bấm "Thêm 3 năm THPT (lớp 10/11/12)", rồi chọn trường từ
#: danh mục cho cả 3 dòng (mock: school_id 42, level THPT). ĐỔI một bên thì đổi cả hai.
CAP_FE_NUT_THEM_NHANH_2022 = [
    {"school_id": 42, "school_name": "THPT Chuyên Nguyễn Du", "level": "THPT", "year_from": 2022, "year_to": 2023, "grade_to": 10, "gpa": None, "graduation_type": "THPT"},
    {"school_id": 42, "school_name": "THPT Chuyên Nguyễn Du", "level": "THPT", "year_from": 2023, "year_to": 2024, "grade_to": 11, "gpa": None, "graduation_type": "THPT"},
    {"school_id": 42, "school_name": "THPT Chuyên Nguyễn Du", "level": "THPT", "year_from": 2024, "year_to": 2025, "grade_to": 12, "gpa": None, "graduation_type": "THPT"},
]
TRUONG_FE = 42

#: Dữ liệu nút thêm nhanh CŨ (trước G5) cho em tốt nghiệp 2026, đã chọn trường: mỗi lớp một mục y→y, y = năm KẾT THÚC của năm học
#: (``AcademicHistoryTab.tsx`` ``addBand`` tại ``d4b7a69f``; Codex G5 P3).
NUT_CU_TOT_NGHIEP_2026 = [
    {"school_id": 42, "school_name": "THPT Chuyên Nguyễn Du", "level": "THPT", "year_from": y, "year_to": y, "grade_to": lop, "gpa": None, "graduation_type": "THPT"}
    for y, lop in ((2024, 10), (2025, 11), (2026, 12))
]


def _danh_muc_fe(doi_tu=None):
    """Trường 42: KV1 mọi năm; ``doi_tu`` = (năm bắt đầu đổi, KV mới)."""
    out = {(TRUONG_FE, nam): "KV1" for nam in range(2010, 2031)}
    if doi_tu:
        out.update({(TRUONG_FE, nam): doi_tu[1] for nam in range(doi_tu[0], 2031)})
    return out


def test_cap_fe_nut_them_nhanh_2022_moi_lop_mot_nam_tra_dung_2022_2023_2024(monkeypatch):
    """Codex P5(b) + owner mục C: mỗi lớp một mục 1 năm cùng trường ⇒ ĐÚNG 3 lần tra 2022, 2023, 2024 (mã trước G5 tra 6 lần)."""
    kv, meta, hoi = _chay(monkeypatch, CAP_FE_NUT_THEM_NHANH_2022, _danh_muc_fe())
    assert hoi == [(TRUONG_FE, 2022), (TRUONG_FE, 2023), (TRUONG_FE, 2024)], hoi
    assert (kv, meta["rule_applied"], meta["breakdown"]["kv_totals"]) == ("KV1", "longest_duration", {"KV1": 3}), meta
    assert [e["counted_school_years"] for e in meta["breakdown"]["entries"]] == [[2022], [2023], [2024]]


def test_cap_fe_nut_them_nhanh_2022_ca_bat_buoc_truong_doi_kv_tu_nam_hoc_2025_2026(monkeypatch):
    """Ca BẮT BUỘC trên ĐÚNG dữ liệu nút sinh ra: tốt nghiệp 2025, trường đổi KV1 → KV3 từ năm học 2025–2026 ⇒ vẫn KV1."""
    kv, meta, hoi = _chay(monkeypatch, CAP_FE_NUT_THEM_NHANH_2022, _danh_muc_fe((2025, "KV3")))
    assert (kv, meta["rule_applied"]) == ("KV1", "longest_duration"), meta
    assert (TRUONG_FE, 2025) not in hoi, hoi


def test_du_lieu_nut_them_nhanh_cu_ba_muc_y_y_deu_lech(monkeypatch):
    """Codex P5(a): khoá hành vi hiện tại với dữ liệu nút CŨ — 3 mục 0 năm ⇒ DỪNG, liệt kê CẢ BA (index 0, 1, 2), không tra."""
    kv, meta, hoi = _chay(monkeypatch, NUT_CU_TOT_NGHIEP_2026, _danh_muc_fe())
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "insufficient_data", "history_entries_inconsistent"), meta
    assert _lech(meta) == [(0, "zero_length_entry"), (1, "zero_length_entry"), (2, "zero_length_entry")], meta
    assert [(m["year_from"], m["year_to"], m["grade_to"]) for m in meta["breakdown"]["entries"]] == [
        (2024, 2024, 10),
        (2025, 2025, 11),
        (2026, 2026, 12),
    ]
    assert hoi == []


def test_nhieu_muc_lech_co_thcs_dung_truoc_liet_ke_moi_muc_index_theo_academic_history(monkeypatch):
    """Codex P5(c): mục THCS (không vào tập đếm) đứng ĐẦU ⇒ index phải tính theo ``academic_history`` (1, 3), không theo tập đếm
    (0, 2); và phải liệt kê MỌI mục lệch, không chỉ mục đầu."""
    lich_su = [
        {"level": "THCS", "school_id": A, "year_from": 2016, "year_to": 2020, "grade_to": 9},
        _thpt(A, 2020, 2020, 10),
        _thpt(B, 2021, 2023),
        _lc(B, 2016, 2023),
    ]
    kv, meta, hoi = _chay(monkeypatch, lich_su)
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "insufficient_data", "history_entries_inconsistent"), meta
    assert _lech(meta) == [(1, "zero_length_entry"), (3, "lien_cap_missing_grade_to")], meta
    assert hoi == []


def test_hoa_truong_tot_nghiep_lien_cap_tra_nam_hoc_cuoi(monkeypatch):
    """Codex P5(d): hoà 2–2, trường tốt nghiệp là LIÊN CẤP. A THPT (KV1) lớp 10–11 ``2020→2022`` ⇒ 2020, 2021; B liên cấp (KV3) lớp
    12 (học hai năm) ``2022→2024`` ⇒ 2022, 2023 ⇒ hoà ⇒ tốt nghiệp B (2024, lớp 12) tra ở khoá 2023; KV của B đổi từ 2024 không dùng."""
    kv, meta, hoi = _chay(
        monkeypatch, [_thpt(A, 2020, 2022, 11), _lc(B, 2022, 2024, 12)], _danh_muc({B: (2024, "KV2")})
    )
    assert (kv, meta["rule_applied"]) == ("KV3", "tiebreak_graduation_school"), meta
    assert meta["breakdown"]["kv_totals"] == {"KV1": 2, "KV3": 2}, meta["breakdown"]
    assert hoi[-1] == (B, 2023) and (B, 2024) not in hoi, hoi
    assert (
        meta["breakdown"]["graduation_school_id"],
        meta["breakdown"]["graduation_year"],
        meta["breakdown"]["graduation_lookup_year"],
    ) == (B, 2024, 2023), meta


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


# ═══════════════════════════════ ở lại lớp (owner 22-11 ``gd2/g5/QUYET-DINH-OWNER-G5-O-LAI-LOP-2026-11-22.md``) ═══════════════════════════════
# Luật (không đổi mã phía tính): mỗi năm học thực học tính 1 năm, kể cả năm ở lại lớp. Ví dụ owner — THPT ở lại lớp 10:
# 2021→2022, 2022→2023 (lớp 10), 2023→2024, 2024→2025 ⇒ 4 năm học.
_O_LAI_LOP_10 = [(2021, 2022, 10), (2022, 2023, 10), (2023, 2024, 11), (2024, 2025, 12)]
_BON_NAM = [(A, 2021), (A, 2022), (A, 2023), (A, 2024)]


def test_o_lai_lop_a_thpt_moi_nam_mot_dong_tinh_4_nam(monkeypatch):
    """(a) THPT mỗi năm một dòng, ở lại lớp 10 ⇒ tra 2021–2024, 4 năm."""
    kv, meta, hoi = _chay(monkeypatch, [_thpt(A, tu, den, lop) for tu, den, lop in _O_LAI_LOP_10])
    assert hoi == _BON_NAM, hoi
    assert (kv, meta["breakdown"]["kv_totals"]) == ("KV1", {"KV1": 4}), meta


def test_o_lai_lop_b_thpt_mot_dong_2021_2025_tinh_4_nam(monkeypatch):
    """(b) THPT một dòng 2021→2025 lớp 12 ⇒ 4 năm (THPT tính đủ mọi năm học — không cắt theo số lớp)."""
    kv, meta, hoi = _chay(monkeypatch, [_thpt(A, 2021, 2025, 12)])
    assert hoi == _BON_NAM, hoi
    assert (kv, meta["breakdown"]["kv_totals"]) == ("KV1", {"KV1": 4}), meta


def test_o_lai_lop_c_lien_cap_moi_nam_mot_dong_tinh_4_nam(monkeypatch):
    """(c) Liên cấp mỗi năm một dòng (lớp 6–9 rồi lớp 10 hai năm, 11, 12) ⇒ dòng lớp ≤ 9 bỏ qua; mỗi dòng lớp 10–12 một năm ⇒ 4 năm."""
    thcs = [_lc(A, 2017 + i, 2018 + i, 6 + i) for i in range(4)]
    thpt = [_lc(A, tu, den, lop) for tu, den, lop in _O_LAI_LOP_10]
    kv, meta, hoi = _chay(monkeypatch, thcs + thpt)
    assert hoi == _BON_NAM, hoi
    assert (kv, meta["breakdown"]["kv_totals"]) == ("KV1", {"KV1": 4}), meta


def test_o_lai_lop_d_lien_cap_mot_dong_2015_2023_chi_tinh_3_nam(monkeypatch):
    """(d) Liên cấp một dòng 2015→2023 lớp 12 ⇒ 3 năm (2020, 2021, 2022). KHOÁ hành vi Q8 "Suy 3 năm cuối".

    Giới hạn đã biết, dữ liệu không có lớp đầu: dòng gộp 8 năm học cho 7 lớp (6–12) nghĩa là em ở lại một lớp, nhưng không biết lớp
    nào — nếu ở lại lớp 10 thì phần THPT thật là 4 năm, máy vẫn chỉ tính 3. Giao diện nhắc tách mỗi năm học một dòng (ca c)."""
    kv, meta, hoi = _chay(monkeypatch, [_lc(A, 2015, 2023, 12)])
    assert hoi == [(A, 2020), (A, 2021), (A, 2022)], hoi
    assert (kv, meta["breakdown"]["kv_totals"]) == ("KV1", {"KV1": 3}), meta


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


#: Ngữ cảnh CĐ liên thông "khối lượng VH THPT + TC" (nhánh lai ``_derive_kv_basis_level`` 5a) cho ``resolve_kv_for_profile``.
_CD_LIEN_THONG = dict(
    target_level="cao_dang",
    admission_type="lien_thong",
    cultural_education_level="completed_thpt",
    vocational_qualification="trung_cap",
)


def test_cd_lien_thong_chay_het_resolve_lien_cap_thieu_lop_thi_dung(monkeypatch):
    """Codex P4: CĐ liên thông chạy HẾT ``resolve_kv_for_profile`` (không chỉ bước chọn căn cứ): liên cấp thiếu lớp ⇒ căn cứ lịch sử
    THPT ⇒ DỪNG có nhãn ``lien_cap_missing_grade_to``, không tra danh mục, không về thường trú."""
    kv, meta, hoi = _chay(monkeypatch, [_lc(A, 2016, 2023)], **_CD_LIEN_THONG)
    assert (meta["basis"], meta["basis_reason"]) == ("LICH_SU_THPT", "cd_lien_thong_khoi_luong_with_thpt_history"), meta
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "insufficient_data", "history_entries_inconsistent"), meta
    assert _lech(meta) == [(0, "lien_cap_missing_grade_to")]
    assert hoi == []


@pytest.mark.parametrize(
    "lich_su, can_cu, ket_qua, hoi_mong_doi",
    [
        ([_lc(A, 2016, 2022, 11)], "LICH_SU_THPT", ("KV1", "longest_duration"), [(A, 2020), (A, 2021)]),
        ([_lc(A, 2016, 2020, 9)], "THUONG_TRU", (None, "address_not_normalized"), []),
    ],
    ids=["lien_cap_lop_6_11_tra_lop_10_11", "lien_cap_lop_6_9_ve_thuong_tru"],
)
def test_cd_lien_thong_chay_het_resolve_doi_chung(monkeypatch, lich_su, can_cu, ket_qua, hoi_mong_doi):
    """Đối chứng cho ca trên, cùng ngữ cảnh CĐ liên thông: liên cấp lớp 6–11 ⇒ tra ĐÚNG lớp 10–11; lớp 6–9 ⇒ thường trú (hồ sơ giả
    không có xã ⇒ ``address_not_normalized``), không tra trường nào."""
    kv, meta, hoi = _chay(monkeypatch, lich_su, **_CD_LIEN_THONG)
    assert meta["basis"] == can_cu, meta
    assert (kv, meta["rule_applied"]) == ket_qua, meta
    assert hoi == hoi_mong_doi


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
