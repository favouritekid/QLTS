# tests/unit/test_kv_hoa_thpt_thieu_lop.py
"""Bước hoà (M1) của luật học nhiều trường THPT khi mục có thể là trường tốt nghiệp THIẾU / SAI KIỂU ``grade_to`` / ``year_to``.

Owner GO 22-11 "sửa ngay, PR nhỏ riêng" (phát hiện ở bàn giao L3-a ``logs-P5/cong-bo-ket-qua/gd2/l3/BAN-GIAO-L3A-LUOT2-2026-11-22.md``,
mục sổ nợ): khoá sắp xếp cũ ``(.get("year_to", 0), .get("grade_to", 0), -index)`` chỉ thay khi THIẾU khoá — ``grade_to`` là JSON
``null`` (schema ``AcademicRecordSchema.grade_to: Optional[int]`` cho lưu) hay chuỗi ⇒ so ``None`` / ``str`` với ``int`` ⇒
``TypeError`` (nộp: ``KV_RESOLUTION_FAILED``; T6 dừng ``PRIORITY_FREEZE_FAILED``; bản in ``khu_vuc_khong_tinh_lai_duoc``).

Bản vá: các mục có thể là trường tốt nghiệp mà không so được ⇒ hoà không phân định ⇒ CÙNG đường M1 (``ambiguous_requires_manual``,
``tied_graduation_year_and_grade``, cần xét tay). Đối chứng: đủ lớp, hoặc không hoà, hoặc chỉ một mục học sau cùng ⇒ hành vi cũ.

Dựng lại trên G5 (rà hợp nhất 23-11 mục B): MỘT helper ``_history_int`` (bỏ bản trùng ``_graduation_int``); bước hoà chỉ xếp NHÓM
``year_to`` lớn nhất (B-H1 — hai mục cùng ``year_to`` ở nhóm THẤP, một lớp null / chuỗi, một lớp số, vẫn nổ ``TypeError`` khi xếp
toàn bộ ``basis_entries``).

Giá trị mong đợi VIẾT TAY. Hàm đọc KV trường được thay bằng bảng tra trong bộ nhớ (ghi lại từng lần hỏi); không CSDL. Quy ước năm G5
(owner 22-11): mục ``a → b`` gồm ``b − a`` năm học, tra các khoá ``a .. b − 1``; trường tốt nghiệp tra ở năm học cuối ``b − 1``; mục
``a → a`` (0 năm học) ⇒ dừng ``insufficient_data``.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import priority_service as ps

pytestmark = pytest.mark.unit

A, B, C, D = 101, 202, 303, 404
KV = {A: "KV1", B: "KV3", C: "KV2", D: "KV2"}


def _m(sid, tu, den, lop=12, **kw):
    muc = {"level": "THPT", "school_id": sid, "school_name": "Trường thử", "year_from": tu, "year_to": den, "grade_to": lop}
    muc.update(kw)
    return muc


def _chay(monkeypatch, lich_su):
    hoi = []

    async def _tra(db, sid, nam):
        hoi.append((sid, nam))
        return KV.get(sid)

    monkeypatch.setattr(ps, "lookup_kv_for_school_year", _tra)
    ho_so = SimpleNamespace(id=1, academic_year=2026, cultural_education_level="graduated_thpt", vocational_qualification="none",
                            area_resolution_basis=None, permanent_commune_code=None, academic_history=lich_su)
    kv, meta = asyncio.run(ps.resolve_kv_for_profile(ho_so, db=None, target_level="cao_dang", admission_type="chinh_quy"))
    return kv, meta, hoi


def _can_xet_tay(meta, truong):
    assert (meta["rule_applied"], meta["reason"], meta["requires_manual_override"]) == (
        "ambiguous_requires_manual", "tied_graduation_year_and_grade", True,
    ), meta
    assert sorted(meta["breakdown"]["tied_entries"]) == sorted(truong)


# ═══════════════════════════════ tái hiện: hoà KV + cùng year_to + một mục thiếu / sai kiểu lớp ═══════════════════════════════
@pytest.mark.parametrize("lop_la", [None, "12"], ids=["grade_to_null", "grade_to_chuoi"])
@pytest.mark.parametrize("muc_la_dung_truoc", [False, True], ids=["muc_la_sau", "muc_la_truoc"])
def test_hoa_cung_year_to_mot_muc_thieu_lop_thi_can_xet_tay_khong_loi(monkeypatch, lop_la, muc_la_dung_truoc):
    lich_su = [_m(A, 2021, 2023, 12), _m(B, 2021, 2023, lop_la)]
    if muc_la_dung_truoc:
        lich_su.reverse()
    kv, meta, hoi = _chay(monkeypatch, lich_su)
    assert kv is None
    _can_xet_tay(meta, [A, B])
    assert meta["breakdown"]["kv_totals"] == {"KV1": 2, "KV3": 2}  # G5: 2021→2023 = năm học 2021, 2022
    assert len(hoi) == 4  # chỉ tra các năm học, KHÔNG tra trường tốt nghiệp


def test_hoa_mot_muc_thieu_year_to_thi_can_xet_tay_khong_loi(monkeypatch):
    """``year_to`` null KHÔNG qua được schema (``AcademicRecordSchema.year_to`` bắt buộc) — chỉ có ở dữ liệu ghi thẳng / cũ. Mục ấy bị
    bỏ khỏi phép đếm nhưng vẫn là ứng viên trường tốt nghiệp ⇒ không biết mục nào học sau cùng ⇒ cần xét tay."""
    lich_su = [_m(A, 2021, 2022, 12), _m(C, 2021, None, 12), _m(B, 2022, 2023, 12)]
    kv, meta, _ = _chay(monkeypatch, lich_su)
    assert kv is None
    _can_xet_tay(meta, [A, C, B])


# ═══════════════ B-H1: lớp lạ ở NHÓM year_to THẤP (cùng năm với một mục lớp số), có hoà KV — trường tốt nghiệp ở nhóm cao ═══════════════
@pytest.mark.parametrize("lop_la", [None, "12"], ids=["grade_to_null", "grade_to_chuoi"])
@pytest.mark.parametrize("dao_thu_tu", [False, True], ids=["thu_tu_nhap", "thu_tu_dao"])
def test_hoa_nhom_year_to_thap_co_lop_la_van_lay_truong_tot_nghiep_khong_loi(monkeypatch, lop_la, dao_thu_tu):
    """Ví dụ của bản rà hợp nhất 23-11 (B-H1): A 2018→2020 lớp 10 KV1 (năm học 2018, 2019); C 2019→2020 lớp lạ KV2 (2019); B 2020→2022
    lớp 12 KV3 (2020, 2021). KV1 = KV3 = 2 năm ⇒ hoà; nhóm ``year_to`` lớn nhất (2022) chỉ có B ⇒ B là trường tốt nghiệp, tra ở năm học
    cuối 2021 ⇒ KV3. Trước khi vá lỗ: xếp TOÀN BỘ ⇒ A và C cùng ``year_to`` 2020 buộc phải so lớp ⇒ ``TypeError``."""
    lich_su = [_m(A, 2018, 2020, 10), _m(C, 2019, 2020, lop_la), _m(B, 2020, 2022, 12)]
    if dao_thu_tu:
        lich_su.reverse()
    kv, meta, hoi = _chay(monkeypatch, lich_su)
    assert (kv, meta["rule_applied"], meta["breakdown"]["graduation_school_id"]) == ("KV3", "tiebreak_graduation_school", B), meta
    assert meta["breakdown"]["kv_totals"] == {"KV1": 2, "KV2": 1, "KV3": 2}
    assert (meta["breakdown"]["graduation_year"], meta["breakdown"]["graduation_lookup_year"]) == (2022, 2021)
    assert (len(hoi), hoi[-1]) == (6, (B, 2021))


@pytest.mark.parametrize(
    "lop_d, mong",
    [(11, "B"), (12, "M1")],
    ids=["nhom_cao_khac_lop_lay_lop_cao", "nhom_cao_cung_lop_van_m1"],
)
def test_nhom_thap_lop_la_nhom_cao_hai_muc_van_xep_theo_lop(monkeypatch, lop_d, mong):
    """Nhóm ``year_to`` cao nhất có HAI mục đủ lớp (B lớp 12, D lớp ``lop_d``), nhóm thấp có mục lớp null — phép xếp trong nhóm cao
    vẫn chạy như cũ: khác lớp ⇒ lấy lớp cao (B); cùng lớp ⇒ M1 chỉ nêu HAI mục nhóm cao (không kéo mục nhóm thấp vào).
    KV1 (A: 2018, 2019) = KV2 (C: 2019; D: 2021) = KV3 (B: 2020, 2021) = 2 năm ⇒ hoà ba bên."""
    lich_su = [_m(A, 2018, 2020, 10), _m(C, 2019, 2020, None), _m(B, 2020, 2022, 12), _m(D, 2021, 2022, lop_d)]
    kv, meta, hoi = _chay(monkeypatch, lich_su)
    assert meta["breakdown"]["kv_totals"] == {"KV1": 2, "KV2": 2, "KV3": 2}
    if mong == "B":
        assert (kv, meta["rule_applied"], meta["breakdown"]["graduation_school_id"]) == ("KV3", "tiebreak_graduation_school", B)
        assert hoi[-1] == (B, 2021)
    else:
        assert kv is None
        _can_xet_tay(meta, [B, D])
        assert len(hoi) == 6  # chỉ tra các năm học, KHÔNG tra trường tốt nghiệp


# ═══════════════════════════════ đối chứng: hành vi cũ không đổi ═══════════════════════════════
def test_doi_chung_du_lop_cung_year_to_khac_lop_lay_lop_cao(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, [_m(A, 2021, 2023, 11), _m(B, 2021, 2023, 12)])
    assert (kv, meta["rule_applied"], meta["breakdown"]["graduation_school_id"]) == ("KV3", "tiebreak_graduation_school", B)
    assert hoi[-1] == (B, 2022)  # G5: trường tốt nghiệp tra ở năm học cuối year_to − 1


def test_doi_chung_du_lop_cung_year_to_cung_lop_van_m1(monkeypatch):
    kv, meta, _ = _chay(monkeypatch, [_m(A, 2021, 2023, 12), _m(B, 2021, 2023, 12)])
    assert kv is None
    _can_xet_tay(meta, [A, B])


def test_doi_chung_hoa_muc_cu_hon_thieu_lop_van_lay_truong_hoc_sau_cung(monkeypatch):
    """Mục học TRƯỚC thiếu lớp không cản: trường học sau cùng xác định bằng ``year_to`` — như cũ (khoá cũ không so tới lớp)."""
    kv, meta, _ = _chay(monkeypatch, [_m(A, 2019, 2020, None), _m(B, 2021, 2022, 12)])
    assert (kv, meta["rule_applied"], meta["breakdown"]["graduation_school_id"]) == ("KV3", "tiebreak_graduation_school", B)


def test_doi_chung_hoa_muc_hoc_sau_cung_duy_nhat_thieu_lop_van_lay(monkeypatch):
    """Chỉ MỘT mục có ``year_to`` lớn nhất ⇒ là trường tốt nghiệp dù thiếu lớp — như cũ."""
    kv, meta, _ = _chay(monkeypatch, [_m(A, 2019, 2020, 11), _m(B, 2021, 2022, None)])
    assert (kv, meta["rule_applied"], meta["breakdown"]["graduation_school_id"]) == ("KV3", "tiebreak_graduation_school", B)


def test_doi_chung_khong_hoa_co_muc_thieu_lop_van_hoc_lau_nhat(monkeypatch):
    """G5: ``2023→2023`` của bản trên main nay là mục 0 năm học (dừng ``insufficient_data``) ⇒ dữ liệu đổi sang ``2020→2022`` (2 năm
    học) + ``2022→2023`` (1 năm học) để giữ ý ca: không hoà ⇒ học lâu nhất, lớp thiếu không cản."""
    kv, meta, _ = _chay(monkeypatch, [_m(A, 2020, 2022, None), _m(B, 2022, 2023, None)])
    assert (kv, meta["rule_applied"]) == ("KV1", "longest_duration")


@pytest.mark.parametrize(
    "muc, mong",
    [
        ([_m(A, 2021, 2023, 12), _m(B, 2021, 2023, None)], [A, B]),
        ([_m(A, 2021, 2023, True), _m(B, 2021, 2023, 12)], [A, B]),
        ([_m(A, 2021, 2023, 12), _m(B, 2021, 2023, 12)], None),
        ([_m(A, 2019, 2020, None), _m(B, 2021, 2022, 12)], None),
        ([_m(A, 2021, "2023", 12), _m(B, 2021, 2023, 12)], "tat_ca"),
        ([_m(A, 2018, 2020, 10), _m(C, 2019, 2020, None), _m(B, 2020, 2022, 12)], None),
    ],
    ids=["null", "bool", "du_lop", "muc_cu_thieu_lop", "year_to_chuoi", "nhom_thap_cung_nam_lop_null"],
)
def test_vi_tu_ung_vien_truong_tot_nghiep(muc, mong):
    thay = ps.kv_graduation_candidates_unclear(muc)
    if mong is None:
        assert thay is None
    else:
        assert [e["school_id"] for e in thay] == ([e["school_id"] for e in muc] if mong == "tat_ca" else mong)


def test_nhom_xep_la_nhom_year_to_lon_nhat_giu_chi_so_goc():
    """Nhóm được xếp ở bước hoà = các mục có ``year_to`` lớn nhất, kèm chỉ số GỐC (khoá ổn định ``-index`` của phép xếp)."""
    muc = [_m(A, 2018, 2020, 10), _m(B, 2020, 2022, 12), _m(C, 2019, 2020, None), _m(D, 2021, 2022, 11)]
    assert [(i, e["school_id"]) for i, e in ps.kv_graduation_year_group(muc)] == [(1, B), (3, D)]
