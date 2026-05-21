"""Phase E.4 commit 5 — `_derive_kv_basis_level` + `resolve_kv_for_profile`
mở rộng với target_level + admission_type + academic_history (yêu cầu nghiệp
vụ #6) + fail-closed cho catalog gap (yêu cầu nghiệp vụ #7).

Test boundaries:
  - Phase E.4 matrix coverage (CD/TC/SC × chính_quy/liên_thông × cultural × voc)
  - Hybrid CĐ liên thông KHOI_LUONG_VH_THPT + TC (3 sub-cases: history+/no/missing)
  - Fail-closed codes: address_not_normalized, catalog_gap_commune, catalog_gap_school
  - basis_reason short keys cho FE display

Lưu ý: legacy 3-arg signature (target_level=None) đã được pin trong
``test_priority_kv_resolution.py``; file này chỉ cover Phase E.4 signature
mới (5-arg).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.priority_service import (
    _derive_kv_basis_level,
    _has_thpt_history,
    resolve_kv_for_profile,
)


pytestmark = pytest.mark.unit


# ===========================================================================
# _has_thpt_history helper
# ===========================================================================


def test_has_thpt_history_empty() -> None:
    assert _has_thpt_history(None) is False
    assert _has_thpt_history([]) is False


def test_has_thpt_history_thpt_entry() -> None:
    history = [
        {"school_id": 100, "level": "THPT", "year_from": 2020, "year_to": 2022},
    ]
    assert _has_thpt_history(history) is True


def test_has_thpt_history_thcs_thpt_lien_cap() -> None:
    history = [
        {"school_id": 100, "level": "THCS_THPT", "year_from": 2019, "year_to": 2022},
    ]
    assert _has_thpt_history(history) is True


def test_has_thpt_history_gdtx_entry() -> None:
    history = [
        {"school_id": 100, "level": "GDTX", "year_from": 2020, "year_to": 2022},
    ]
    assert _has_thpt_history(history) is True


def test_has_thpt_history_only_thcs_returns_false() -> None:
    history = [
        {"school_id": 50, "level": "THCS", "year_from": 2017, "year_to": 2019},
    ]
    assert _has_thpt_history(history) is False


def test_has_thpt_history_only_tc_nghe_returns_false() -> None:
    history = [
        {"school_id": 200, "level": "TRUNG_HOC_NGHE", "year_from": 2022, "year_to": 2024},
    ]
    assert _has_thpt_history(history) is False


def test_has_thpt_history_thpt_missing_school_id_returns_false() -> None:
    history = [{"level": "THPT", "year_from": 2020, "year_to": 2022}]
    assert _has_thpt_history(history) is False


def test_has_thpt_history_thpt_missing_year_returns_false() -> None:
    history = [{"school_id": 100, "level": "THPT", "year_from": None, "year_to": 2022}]
    assert _has_thpt_history(history) is False


# ===========================================================================
# Phase E.4 matrix — target_level + admission_type drive basis
# ===========================================================================


@pytest.mark.parametrize(
    "cultural,vocational,target_level,admission_type,expected_basis,reason_contains",
    [
        # CĐ chính quy + cultural đủ THPT knowledge → LICH_SU_THPT
        ("graduated_thpt", "none", "cao_dang", "chinh_quy", "LICH_SU_THPT", "cd_chinh_quy_post_thpt"),
        ("graduated_gdtx", "none", "cao_dang", "chinh_quy", "LICH_SU_THPT", "cd_chinh_quy_post_thpt"),
        ("completed_thpt", "none", "cao_dang", "chinh_quy", "LICH_SU_THPT", "cd_chinh_quy_completed_thpt"),
        # CĐ chính quy + graduated_thcs → INSUFFICIENT_DATA (eligibility đã chặn upstream)
        ("graduated_thcs", "none", "cao_dang", "chinh_quy", "INSUFFICIENT_DATA", "cd_chinh_quy_cultural_insufficient"),
        # CĐ liên thông từ TC + cultural graduated_thpt → LICH_SU_THPT
        ("graduated_thpt", "trung_cap", "cao_dang", "lien_thong", "LICH_SU_THPT", "cd_lien_thong_post_thpt"),
        ("graduated_gdtx", "cao_dang", "cao_dang", "lien_thong", "LICH_SU_THPT", "cd_lien_thong_post_thpt"),
        # TC chính quy + graduated_thcs → THUONG_TRU
        ("graduated_thcs", "none", "trung_cap", "chinh_quy", "THUONG_TRU", "tc_chinh_quy_post_thcs"),
        # TC chính quy + cultural đủ THPT → LICH_SU_THPT
        ("graduated_thpt", "none", "trung_cap", "chinh_quy", "LICH_SU_THPT", "tc_chinh_quy_post_thpt"),
        ("completed_thpt", "so_cap", "trung_cap", "chinh_quy", "LICH_SU_THPT", "tc_chinh_quy_post_thpt"),
        # TC liên thông từ SC/TC + cultural graduated_thcs → THUONG_TRU
        ("graduated_thcs", "so_cap", "trung_cap", "lien_thong", "THUONG_TRU", "tc_lien_thong_post_thcs_with_voc"),
        ("graduated_thcs", "trung_cap", "trung_cap", "lien_thong", "THUONG_TRU", "tc_lien_thong_post_thcs_with_voc"),
        # TC liên thông + cultural THPT → LICH_SU_THPT
        ("graduated_thpt", "so_cap", "trung_cap", "lien_thong", "LICH_SU_THPT", "tc_lien_thong_post_thpt"),
        # TC chính quy + completed_thcs → INSUFFICIENT_DATA
        ("completed_thcs", "none", "trung_cap", "chinh_quy", "INSUFFICIENT_DATA", "tc_chinh_quy_cultural_insufficient"),
        # SC chính quy → THUONG_TRU
        ("graduated_thcs", "none", "so_cap", "chinh_quy", "THUONG_TRU", "sc_uses_commune"),
        (None, "none", "so_cap", "chinh_quy", "NOT_RESOLVED", "cultural_not_set"),
    ],
)
def test_phase_e4_matrix_basis_resolution(
    cultural, vocational, target_level, admission_type, expected_basis, reason_contains,
) -> None:
    basis, reason = _derive_kv_basis_level(
        cultural=cultural,
        vocational=vocational,
        target_level=target_level,
        admission_type=admission_type,
        academic_history=None,
    )
    assert basis == expected_basis, (
        f"Combo ({cultural}/{vocational}/{target_level}/{admission_type}) "
        f"expected basis={expected_basis} but got {basis} (reason={reason})"
    )
    assert reason_contains in reason


# ===========================================================================
# Hybrid: CĐ liên thông KHOI_LUONG_VH_THPT + TC (completed_thpt + trung_cap)
# ===========================================================================


def test_hybrid_cd_lien_thong_with_thpt_history_picks_lich_su_thpt() -> None:
    """Có lịch sử học THPT/GDTX hợp lệ → LICH_SU_THPT (per nghiệp vụ #6)."""
    history = [
        {"school_id": 100, "level": "THPT", "year_from": 2018, "year_to": 2020},
    ]
    basis, reason = _derive_kv_basis_level(
        cultural="completed_thpt",
        vocational="trung_cap",
        target_level="cao_dang",
        admission_type="lien_thong",
        academic_history=history,
    )
    assert basis == "LICH_SU_THPT"
    assert "cd_lien_thong_khoi_luong_with_thpt_history" in reason


def test_hybrid_cd_lien_thong_no_thpt_history_falls_to_thuong_tru() -> None:
    """Không có lịch sử THPT → THUONG_TRU (fallback per nghiệp vụ #6)."""
    history = [
        {"school_id": 200, "level": "TRUNG_HOC_NGHE", "year_from": 2022, "year_to": 2024},
    ]
    basis, reason = _derive_kv_basis_level(
        cultural="completed_thpt",
        vocational="trung_cap",
        target_level="cao_dang",
        admission_type="lien_thong",
        academic_history=history,
    )
    assert basis == "THUONG_TRU"
    assert "cd_lien_thong_khoi_luong_no_thpt_history_fallback" in reason


def test_hybrid_cd_lien_thong_no_history_at_all_falls_to_thuong_tru() -> None:
    """Empty academic_history → fall to THUONG_TRU; engine sẽ check commune
    ở resolve step → ADDRESS_NOT_NORMALIZED nếu cũng thiếu commune_code."""
    basis, reason = _derive_kv_basis_level(
        cultural="completed_thpt",
        vocational="cao_dang",
        target_level="cao_dang",
        admission_type="lien_thong",
        academic_history=[],
    )
    assert basis == "THUONG_TRU"
    assert "no_thpt_history_fallback" in reason


# ===========================================================================
# Bypass paths — area_resolution_basis trumps Phase E.4 matrix
# ===========================================================================


def test_permanent_address_special_overrides_phase_e4_matrix() -> None:
    basis, reason = _derive_kv_basis_level(
        cultural="graduated_thpt",
        vocational="none",
        target_level="cao_dang",
        admission_type="chinh_quy",
        academic_history=None,
        area_resolution_basis="permanent_address_special",
    )
    assert basis == "COMMUNE_SPECIAL"
    assert reason == "permanent_address_special_override"


def test_manual_override_trumps_everything() -> None:
    basis, reason = _derive_kv_basis_level(
        cultural=None,
        vocational="none",
        target_level=None,
        admission_type=None,
        academic_history=None,
        area_resolution_basis="manual_override",
    )
    assert basis == "MANUAL"
    assert reason == "admin_set_kv_directly"


# ===========================================================================
# resolve_kv_for_profile — fail-closed codes (yêu cầu nghiệp vụ #7)
# ===========================================================================


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _mock_db(commune_kv=None, school_kv_sequence=None):
    db = AsyncMock()
    kv_iter = iter(school_kv_sequence or [])

    async def execute(stmt):
        stmt_str = str(stmt).lower()
        if "vn_commune_area_map" in stmt_str:
            return _Result(commune_kv)
        if "vn_school_kv_assignment" in stmt_str:
            try:
                return _Result(next(kv_iter))
            except StopIteration:
                return _Result(None)
        return _Result(None)

    db.execute = execute
    return db


def _profile_stub(**kwargs):
    defaults = {
        "id": 1,
        "cultural_education_level": "graduated_thpt",
        "vocational_qualification": "none",
        "area_resolution_basis": None,
        "permanent_commune_code": None,
        "academic_history": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_resolve_thuong_tru_missing_commune_code_returns_address_not_normalized() -> None:
    """TC chính quy + graduated_thcs + thiếu permanent_commune_code → fail-closed."""
    profile = _profile_stub(
        cultural_education_level="graduated_thcs",
        permanent_commune_code=None,
    )
    db = _mock_db()
    kv, meta = await resolve_kv_for_profile(
        profile, db, target_level="trung_cap", admission_type="chinh_quy",
    )
    assert kv is None
    assert meta["rule_applied"] == "address_not_normalized"
    assert meta["pathway"] == "thuong_tru"
    assert meta["basis"] == "THUONG_TRU"
    assert meta["requires_manual_override"] is True


@pytest.mark.asyncio
async def test_resolve_thuong_tru_commune_not_in_catalog_returns_catalog_gap_commune() -> None:
    """commune_code có nhưng vn_commune_area_map miss → catalog_gap_commune."""
    profile = _profile_stub(
        cultural_education_level="graduated_thcs",
        permanent_commune_code="UNKNOWN_CODE",
    )
    db = _mock_db(commune_kv=None)  # lookup miss
    kv, meta = await resolve_kv_for_profile(
        profile, db, target_level="trung_cap", admission_type="chinh_quy",
    )
    assert kv is None
    assert meta["rule_applied"] == "catalog_gap_commune"
    assert meta["pathway"] == "thuong_tru"
    assert meta["breakdown"]["commune_code_attempted"] == "UNKNOWN_CODE"


@pytest.mark.asyncio
async def test_resolve_lich_su_thpt_all_school_lookups_miss_returns_catalog_gap_school() -> None:
    """CĐ chính quy + history THPT nhưng vn_school_kv_assignment miss tất cả."""
    profile = _profile_stub(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {"school_id": 100, "level": "THPT", "year_from": 2020, "year_to": 2022, "grade_to": 12},
        ],
    )
    db = _mock_db(school_kv_sequence=[None, None, None])  # all 3 years miss
    kv, meta = await resolve_kv_for_profile(
        profile, db, target_level="cao_dang", admission_type="chinh_quy",
    )
    assert kv is None
    assert meta["rule_applied"] == "catalog_gap_school"
    assert meta["pathway"] == "lich_su_thpt"
    assert meta["basis"] == "LICH_SU_THPT"


@pytest.mark.asyncio
async def test_resolve_commune_special_missing_code_returns_address_not_normalized() -> None:
    """area_resolution_basis=permanent_address_special + thiếu commune_code."""
    profile = _profile_stub(
        cultural_education_level="graduated_thpt",
        area_resolution_basis="permanent_address_special",
        permanent_commune_code=None,
    )
    db = _mock_db()
    kv, meta = await resolve_kv_for_profile(
        profile, db, target_level="cao_dang", admission_type="chinh_quy",
    )
    assert kv is None
    assert meta["rule_applied"] == "address_not_normalized"
    assert meta["basis"] == "COMMUNE_SPECIAL"


@pytest.mark.asyncio
async def test_resolve_thuong_tru_happy_with_commune_in_catalog() -> None:
    """TC chính quy + graduated_thcs + commune_code resolve OK."""
    profile = _profile_stub(
        cultural_education_level="graduated_thcs",
        permanent_commune_code="66_22255",
    )
    db = _mock_db(commune_kv="KV2-NT")
    kv, meta = await resolve_kv_for_profile(
        profile, db, target_level="trung_cap", admission_type="chinh_quy",
    )
    assert kv == "KV2-NT"
    assert meta["rule_applied"] == "commune_lookup"
    assert meta["pathway"] == "thuong_tru"
    assert meta["basis"] == "THUONG_TRU"
    assert meta["breakdown"]["commune_code_used"] == "66_22255"


@pytest.mark.asyncio
async def test_resolve_insufficient_data_for_cd_lien_thong_no_history_no_commune() -> None:
    """Hybrid: completed_thpt + trung_cap + no history + no commune → THUONG_TRU
    basis nhưng resolve fail với ADDRESS_NOT_NORMALIZED (commune missing)."""
    profile = _profile_stub(
        cultural_education_level="completed_thpt",
        vocational_qualification="trung_cap",
        academic_history=[],
        permanent_commune_code=None,
    )
    db = _mock_db()
    kv, meta = await resolve_kv_for_profile(
        profile, db, target_level="cao_dang", admission_type="lien_thong",
    )
    assert kv is None
    assert meta["basis"] == "THUONG_TRU"
    assert meta["rule_applied"] == "address_not_normalized"


# ===========================================================================
# Snapshot additive fields (target_level + admission_type bơm vào meta)
# ===========================================================================


@pytest.mark.asyncio
async def test_resolve_carries_basis_and_reason_into_meta() -> None:
    """Mọi resolve call phải emit basis + basis_reason trong meta (audit trail)."""
    profile = _profile_stub(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {"school_id": 100, "level": "THPT", "year_from": 2020, "year_to": 2022, "grade_to": 12},
        ],
    )
    db = _mock_db(school_kv_sequence=["KV1", "KV1", "KV1"])
    kv, meta = await resolve_kv_for_profile(
        profile, db, target_level="cao_dang", admission_type="chinh_quy",
    )
    assert kv == "KV1"
    assert meta["basis"] == "LICH_SU_THPT"
    assert "cd_chinh_quy_post_thpt" in meta["basis_reason"]
