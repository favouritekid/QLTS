# tests/unit/test_priority_kv_lien_cap_g5.py
"""G5 — mục LIÊN CẤP (``THCS_THPT``) trong luật học nhiều trường chỉ đóng góp PHẦN THPT.

Căn cứ: owner 11-10 — ``bang-chung/QUYET-DINH-OWNER-2026-10-11-TRA-LOI-DANH-SACH-CAU-HOI-v2.md`` T5c "Chỉ tính THPT";
``bang-chung/QUYET-DINH-OWNER-2026-10-11-TRA-LOI-V3.md`` Q8 "Suy 3 năm cuối (từ năm kết thúc + lớp kết thúc)"; owner 22-11 L1 (PR riêng).

Phần THPT của mục liên cấp lớp kết thúc ``g`` (10..12) đếm như một mục THPT CÙNG khoảng (quy ước đếm hiện hành: mục ``a→b`` tra các
năm ``a..b``): năm đầu ``year_to − (g − 9)``, không sớm hơn ``year_from``. Lớp kết thúc ≤ 9 ⇒ chỉ năm THCS ⇒ bỏ qua cả mục. Thiếu lớp
kết thúc ⇒ GIỮ hành vi cũ (Q8 không nói — câu hỏi owner).

Giá trị mong đợi VIẾT TAY. Hai hàm đọc danh mục được thay bằng bảng tra trong bộ nhớ (ghi lại từng lần hỏi); không CSDL.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import priority_service as ps

pytestmark = pytest.mark.unit

X, Y = 1, 2
#: KV trường giả: X = KV1, Y = KV3 cho mọi năm.
DANH_MUC = {}
for _nam in range(2010, 2031):
    DANH_MUC[(X, _nam)] = "KV1"
    DANH_MUC[(Y, _nam)] = "KV3"


def _lc(sid, tu, den, lop=None):
    muc = {"level": "THCS_THPT", "school_id": sid, "year_from": tu, "year_to": den}
    if lop is not None:
        muc["grade_to"] = lop
    return muc


def _thpt(sid, tu, den, lop=12):
    return {"level": "THPT", "school_id": sid, "year_from": tu, "year_to": den, "grade_to": lop}


def _chay(monkeypatch, lich_su):
    hoi = []

    async def _tra(db, sid, nam):
        hoi.append((sid, nam))
        return DANH_MUC.get((sid, nam))

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


def test_cat_phan_thcs_lam_doi_kv(monkeypatch):
    """Liên cấp X (KV1) lớp 6–10 ``2016→2021`` + THPT Y (KV3) ``2021→2023``. Chỉ tính THPT: X đóng góp 2020–2021 (2), Y 2021–2023 (3)
    ⇒ KV3. (Đếm cả mục liên cấp — luật cũ: X 6 ⇒ KV1.)"""
    kv, meta, hoi = _chay(monkeypatch, [_lc(X, 2016, 2021, 10), _thpt(Y, 2021, 2023)])
    assert (kv, meta["rule_applied"]) == ("KV3", "longest_duration"), meta
    assert meta["breakdown"]["kv_totals"] == {"KV1": 2, "KV3": 3}, meta["breakdown"]
    assert [h for h in hoi if h[0] == X] == [(X, 2020), (X, 2021)], hoi


def test_lien_cap_ngan_khong_dem_truoc_nam_bat_dau(monkeypatch):
    """Liên cấp lớp 12 chỉ ``2022→2023`` (chuyển tới năm cuối): phần THPT suy ra (2020–2023) bị chặn ở ``year_from`` ⇒ tra 2022, 2023."""
    kv, meta, hoi = _chay(monkeypatch, [_lc(X, 2022, 2023, 12)])
    assert kv == "KV1" and meta["breakdown"]["kv_totals"] == {"KV1": 2}, meta
    assert hoi == [(X, 2022), (X, 2023)], hoi


def test_hoa_sau_khi_cat_lay_truong_tot_nghiep(monkeypatch):
    """Liên cấp X lớp 6–11 ``2016→2022`` (THPT 2020–2022 = 3) + THPT Y ``2022→2024`` (3) ⇒ HOÀ ⇒ nơi tốt nghiệp (Y, 2024, lớp 12) ⇒ KV3.
    (Luật cũ: X 7 ⇒ KV1, không hoà.)"""
    kv, meta, _ = _chay(monkeypatch, [_lc(X, 2016, 2022, 11), _thpt(Y, 2022, 2024)])
    assert (kv, meta["rule_applied"]) == ("KV3", "tiebreak_graduation_school"), meta
    assert meta["breakdown"]["kv_totals"] == {"KV1": 3, "KV3": 3}, meta["breakdown"]
    assert meta["breakdown"]["graduation_school_id"] == Y


def test_lien_cap_lop_9_tro_xuong_bo_qua(monkeypatch):
    """Liên cấp X kết thúc lớp 9 (chỉ THCS) + THPT Y ``2020→2023`` ⇒ X không được tra, KV theo Y = KV3. (Luật cũ: X 5 > Y 4 ⇒ KV1.)"""
    kv, meta, hoi = _chay(monkeypatch, [_lc(X, 2016, 2020, 9), _thpt(Y, 2020, 2023)])
    assert kv == "KV3" and meta["breakdown"]["kv_totals"] == {"KV3": 4}, meta
    assert not [h for h in hoi if h[0] == X], hoi


def test_chi_co_lien_cap_lop_9_thi_khong_co_muc_dem(monkeypatch):
    kv, meta, hoi = _chay(monkeypatch, [_lc(X, 2016, 2020, 9)])
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "insufficient_data", "no_qualifying_thpt_history_entries")
    assert hoi == []


def test_lien_cap_tron_6_12_bang_muc_thpt_cung_khoang(monkeypatch):
    """Phần THPT của liên cấp lớp 6–12 ``2016→2023`` được tra ĐÚNG như một mục THPT lớp 10–12 ``2020→2023`` (một quy ước đếm)."""
    _, _, lien_cap = _chay(monkeypatch, [_lc(X, 2016, 2023, 12)])
    _, _, thpt = _chay(monkeypatch, [_thpt(X, 2020, 2023)])
    assert lien_cap == thpt == [(X, 2020), (X, 2021), (X, 2022), (X, 2023)]


def test_lien_cap_thieu_lop_ket_thuc_giu_hanh_vi_cu_cho_owner(monkeypatch):
    """Q8 chưa nói ca thiếu lớp kết thúc ⇒ GIỮ hành vi cũ (đếm cả mục) cho tới khi owner chốt. Ca này KHOÁ hành vi tạm thời."""
    _, meta, hoi = _chay(monkeypatch, [_lc(X, 2016, 2023)])
    assert hoi == [(X, n) for n in range(2016, 2024)], hoi
    assert meta["breakdown"]["kv_totals"] == {"KV1": 8}


@pytest.mark.parametrize(
    "muc, nam_dau",
    [
        (_thpt(X, 2018, 2021), 2018),
        ({"level": "GDTX", "school_id": X, "year_from": 2018, "year_to": 2021}, 2018),
        (_lc(X, 2016, 2023, 12), 2020),
        (_lc(X, 2016, 2023, 11), 2021),
        (_lc(X, 2016, 2023, 10), 2022),
        (_lc(X, 2022, 2023, 12), 2022),
        (_lc(X, 2016, 2023, 13), 2016),
        (_lc(X, 2016, 2023, True), 2016),
    ],
    ids=["thpt_khong_doi", "gdtx_khong_doi", "lop12", "lop11", "lop10", "ngan", "lop_sai_giu_cu", "lop_bool_giu_cu"],
)
def test_nam_dau_duoc_dem(muc, nam_dau):
    assert ps.kv_counted_first_year(muc) == nam_dau
