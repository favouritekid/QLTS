"""Unit tests for Phase E.4 eligibility + target_level derivation.

Q9 #07 Phase E.4 — exercises:
  - ``priority_service.derive_target_level_and_type(path)`` happy/gap paths
  - ``priority_service.validate_eligibility(profile, target, type)`` cho 5
    nghiệp vụ levels (CĐ/CĐ liên thông/TC/TC liên thông/SC) chốt 2026-05-21.

Pure-logic tests dùng SimpleNamespace + stub objects. KHÔNG cần DB; gọi
helpers trực tiếp.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.priority_service import (
    _is_health_sector_code,
    derive_target_level_and_type,
    normalize_target_level,
    validate_eligibility,
)
from app.utils.exceptions import BusinessRuleViolation


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Builder helpers — build path/profile stubs
# ---------------------------------------------------------------------------


def _build_path(degree_level_code: str | None, offering_type_code: str | None):
    """Build AdmissionPath stub với eager-loaded chain matching helper contract.

    derive_target_level_and_type đọc qua ``__dict__`` để mimic SQLAlchemy
    eager-load semantics (NOT lazy fetch). Builders mirror chain shape:
        path.__dict__['academic_info'].__dict__['offering'].__dict__['program']
            .__dict__['degree_level_ref'].code
        path.__dict__['academic_info'].__dict__['offering']
            .__dict__['offering_type_config'].code
    """
    degree_obj = SimpleNamespace(code=degree_level_code) if degree_level_code else None
    program = SimpleNamespace()
    program.__dict__["degree_level_ref"] = degree_obj

    offering_type_obj = (
        SimpleNamespace(code=offering_type_code) if offering_type_code else None
    )
    offering = SimpleNamespace()
    offering.__dict__["program"] = program
    offering.__dict__["offering_type_config"] = offering_type_obj

    academic_info = SimpleNamespace()
    academic_info.__dict__["offering"] = offering

    path = SimpleNamespace()
    path.__dict__["academic_info"] = academic_info
    return path


def _profile(
    cultural: str | None = None,
    vocational: str = "none",
    academic_year: int | None = None,
):
    return SimpleNamespace(
        cultural_education_level=cultural,
        vocational_qualification=vocational,
        academic_year=academic_year,
    )


# ===========================================================================
# derive_target_level_and_type — happy paths
# ===========================================================================


def test_derive_cao_dang_chinh_quy() -> None:
    path = _build_path("cao_dang", "chinh_quy")
    target, admission_type = derive_target_level_and_type(path)
    assert target == "cao_dang"
    assert admission_type == "chinh_quy"


def test_derive_cao_dang_lien_thong() -> None:
    path = _build_path("cao_dang", "lien_thong")
    target, admission_type = derive_target_level_and_type(path)
    assert target == "cao_dang"
    assert admission_type == "lien_thong"


def test_derive_trung_cap_chinh_quy() -> None:
    path = _build_path("trung_cap", "chinh_quy")
    assert derive_target_level_and_type(path) == ("trung_cap", "chinh_quy")


def test_derive_trung_cap_lien_thong() -> None:
    path = _build_path("trung_cap", "lien_thong")
    assert derive_target_level_and_type(path) == ("trung_cap", "lien_thong")


def test_derive_so_cap_chinh_quy() -> None:
    path = _build_path("so_cap", "chinh_quy")
    assert derive_target_level_and_type(path) == ("so_cap", "chinh_quy")


# ===========================================================================
# derive_target_level_and_type — CONFIG_GAP raises BusinessRuleViolation
# ===========================================================================


def test_derive_missing_degree_level_ref_raises() -> None:
    path = _build_path(None, "chinh_quy")
    with pytest.raises(BusinessRuleViolation) as exc:
        derive_target_level_and_type(path)
    assert "CONFIG_GAP_TARGET_LEVEL" in str(exc.value)
    assert "degree_level_id" in str(exc.value)


def test_derive_missing_offering_type_raises() -> None:
    path = _build_path("cao_dang", None)
    with pytest.raises(BusinessRuleViolation) as exc:
        derive_target_level_and_type(path)
    assert "CONFIG_GAP_TARGET_LEVEL" in str(exc.value)
    assert "offering_type_id" in str(exc.value)


def test_derive_out_of_gdnn_scope_raises_for_dai_hoc() -> None:
    # GDNN scope: chỉ CĐ/TC/SC. dai_hoc/thac_si/tien_si không thuộc Phase E.4.
    path = _build_path("dai_hoc", "chinh_quy")
    with pytest.raises(BusinessRuleViolation) as exc:
        derive_target_level_and_type(path)
    assert "CONFIG_GAP_TARGET_LEVEL" in str(exc.value)
    assert "GDNN" in str(exc.value) or "ngoài" in str(exc.value)


def test_derive_no_academic_info_chain_raises() -> None:
    # Eager-load chain missing (path bare) → raise.
    bare_path = SimpleNamespace()
    bare_path.__dict__["academic_info"] = None
    with pytest.raises(BusinessRuleViolation) as exc:
        derive_target_level_and_type(bare_path)
    assert "CONFIG_GAP_TARGET_LEVEL" in str(exc.value)


# ===========================================================================
# validate_eligibility — CĐ chính quy
# ===========================================================================


@pytest.mark.parametrize(
    "cultural",
    [
        "graduated_thpt",
        "graduated_gdtx",
        "completed_thpt",  # đủ kiến thức THPT theo nghiệp vụ #5 (HOAN_THANH_THPT)
    ],
)
def test_cd_chinh_quy_pass(cultural: str) -> None:
    profile = _profile(cultural=cultural)
    ok, reason = validate_eligibility(profile, "cao_dang", "chinh_quy")
    assert ok is True
    assert reason is None


@pytest.mark.parametrize(
    "cultural",
    [None, "graduated_thcs", "completed_thcs"],
)
def test_cd_chinh_quy_fail_without_thpt_knowledge(cultural: str | None) -> None:
    profile = _profile(cultural=cultural)
    ok, reason = validate_eligibility(profile, "cao_dang", "chinh_quy")
    assert ok is False
    assert reason == "cd_chinh_quy_requires_thpt_or_completed_thpt"


# ===========================================================================
# validate_eligibility — CĐ liên thông
# ===========================================================================


@pytest.mark.parametrize(
    "cultural, vocational",
    [
        ("graduated_thpt", "trung_cap"),
        ("graduated_thpt", "cao_dang"),
        ("completed_thpt", "trung_cap"),  # HOAN_THANH_THPT + bằng TC
        ("graduated_gdtx", "cao_dang"),
    ],
)
def test_cd_lien_thong_pass(cultural: str, vocational: str) -> None:
    profile = _profile(cultural=cultural, vocational=vocational)
    ok, _ = validate_eligibility(profile, "cao_dang", "lien_thong")
    assert ok is True


@pytest.mark.parametrize(
    "cultural, vocational",
    [
        ("graduated_thpt", "none"),  # thiếu bằng TC/CĐ
        ("graduated_thpt", "so_cap"),  # SC không đủ cho CĐ liên thông
        ("graduated_thcs", "trung_cap"),  # thiếu THPT knowledge
        ("completed_thpt", "none"),
    ],
)
def test_cd_lien_thong_fail(cultural: str, vocational: str) -> None:
    profile = _profile(cultural=cultural, vocational=vocational)
    ok, reason = validate_eligibility(profile, "cao_dang", "lien_thong")
    assert ok is False
    assert reason == "cd_lien_thong_requires_thpt_knowledge_plus_tc_or_cd"


# ===========================================================================
# validate_eligibility — TC chính quy
# ===========================================================================


@pytest.mark.parametrize(
    "cultural",
    [
        "completed_thcs",
        "graduated_thcs",
        "completed_thpt",
        "graduated_thpt",
        "graduated_gdtx",
    ],
)
def test_tc_chinh_quy_pass(cultural: str) -> None:
    profile = _profile(cultural=cultural)
    ok, _ = validate_eligibility(profile, "trung_cap", "chinh_quy")
    assert ok is True


@pytest.mark.parametrize("cultural", [None])
def test_tc_chinh_quy_fail(cultural: str | None) -> None:
    profile = _profile(cultural=cultural)
    ok, reason = validate_eligibility(profile, "trung_cap", "chinh_quy")
    assert ok is False
    assert reason == "tc_requires_graduated_thcs_or_higher"


# ===========================================================================
# validate_eligibility — TC liên thông
# ===========================================================================


@pytest.mark.parametrize(
    "cultural, vocational",
    [
        ("completed_thcs", "so_cap"),
        ("completed_thcs", "trung_cap"),
        ("graduated_thcs", "so_cap"),
        ("graduated_thcs", "trung_cap"),
        ("graduated_thpt", "so_cap"),
    ],
)
def test_tc_lien_thong_pass(cultural: str, vocational: str) -> None:
    profile = _profile(cultural=cultural, vocational=vocational)
    ok, _ = validate_eligibility(profile, "trung_cap", "lien_thong")
    assert ok is True


@pytest.mark.parametrize(
    "cultural, vocational",
    [
        ("completed_thcs", "none"),  # cần SC/TC
        ("completed_thcs", "cao_dang"),  # CĐ đã cao hơn TC — out of liên thông scope
        ("graduated_thcs", "none"),  # cần SC/TC
        ("graduated_thcs", "cao_dang"),  # CĐ đã cao hơn TC — out of liên thông scope
    ],
)
def test_tc_lien_thong_fail(cultural: str, vocational: str) -> None:
    profile = _profile(cultural=cultural, vocational=vocational)
    ok, reason = validate_eligibility(profile, "trung_cap", "lien_thong")
    assert ok is False
    assert reason == "tc_lien_thong_requires_thcs_plus_sc_or_tc"


# ===========================================================================
# validate_eligibility — SC chính quy + edge cases
# ===========================================================================


@pytest.mark.parametrize(
    "cultural",
    [None, "completed_thcs", "graduated_thcs", "graduated_thpt"],
)
def test_sc_chinh_quy_pass_any_cultural(cultural: str | None) -> None:
    profile = _profile(cultural=cultural)
    ok, _ = validate_eligibility(profile, "so_cap", "chinh_quy")
    assert ok is True


def test_sc_lien_thong_not_supported() -> None:
    profile = _profile(cultural="graduated_thpt", vocational="trung_cap")
    ok, reason = validate_eligibility(profile, "so_cap", "lien_thong")
    assert ok is False
    assert reason == "sc_only_supports_chinh_quy_in_phase_e4"


def test_unsupported_target_level_blocks() -> None:
    profile = _profile(cultural="graduated_thpt")
    ok, reason = validate_eligibility(profile, "dai_hoc", "chinh_quy")
    assert ok is False
    assert "unsupported_target_level" in reason


# ===========================================================================
# Health-sector TC guard — Luật GDNN 2025 Điều 45 K2 (đóng đầu vào THCS từ 2026)
# ===========================================================================

_YSY_TC = "5720101"  # Y sỹ đa khoa — Trung cấp (lĩnh vực sức khỏe "72")
_OTO_TC = "5510216"  # Công nghệ ô tô — Trung cấp (lĩnh vực "51", non-health)


def test_is_health_sector_code() -> None:
    assert _is_health_sector_code("5720101") is True
    assert _is_health_sector_code("6720201") is True  # Dược CĐ
    assert _is_health_sector_code("5510216") is False  # CN ô tô
    assert _is_health_sector_code(None) is False
    assert _is_health_sector_code("72") is False  # len < 3


@pytest.mark.parametrize("cultural", ["completed_thcs", "graduated_thcs"])
def test_tc_health_thcs_blocked_2026_chinh_quy(cultural: str) -> None:
    # Cả completed_thcs lẫn graduated_thcs (nhãn legacy cùng tầng THCS) đều chặn.
    profile = _profile(cultural=cultural, academic_year=2026)
    ok, reason = validate_eligibility(profile, "trung_cap", "chinh_quy", _YSY_TC)
    assert ok is False
    assert reason == "tc_health_thcs_entry_closed_2026"


@pytest.mark.parametrize("cultural", ["completed_thcs", "graduated_thcs"])
def test_tc_health_thcs_blocked_2026_lien_thong(cultural: str) -> None:
    profile = _profile(cultural=cultural, vocational="trung_cap", academic_year=2026)
    ok, reason = validate_eligibility(profile, "trung_cap", "lien_thong", _YSY_TC)
    assert ok is False
    assert reason == "tc_health_thcs_entry_closed_2026"


@pytest.mark.parametrize(
    "cultural", ["completed_thpt", "graduated_thpt", "graduated_gdtx"]
)
def test_tc_health_thpt_input_still_passes(cultural: str) -> None:
    # Chỉ đóng đầu vào THCS; đầu vào THPT vào TC sức khỏe vẫn hợp lệ.
    profile = _profile(cultural=cultural, academic_year=2026)
    ok, _ = validate_eligibility(profile, "trung_cap", "chinh_quy", _YSY_TC)
    assert ok is True


def test_tc_nonhealth_completed_thcs_passes_2026() -> None:
    # Ngành thường (CN ô tô) + completed_thcs + 2026 → vẫn pass (Option B).
    profile = _profile(cultural="completed_thcs", academic_year=2026)
    ok, _ = validate_eligibility(profile, "trung_cap", "chinh_quy", _OTO_TC)
    assert ok is True


@pytest.mark.parametrize("cultural", ["completed_thcs", "graduated_thcs"])
def test_tc_health_thcs_pre_2026_passes(cultural: str) -> None:
    # Trước mốc 01/01/2026 guard không áp (backward-compat cycle cũ).
    profile = _profile(cultural=cultural, academic_year=2025)
    ok, _ = validate_eligibility(profile, "trung_cap", "chinh_quy", _YSY_TC)
    assert ok is True


# ===========================================================================
# normalize_target_level — legacy uppercase aliases
# ===========================================================================


def test_normalize_target_level_legacy_uppercase() -> None:
    assert normalize_target_level("CD") == "cao_dang"
    assert normalize_target_level("TC") == "trung_cap"
    assert normalize_target_level("SC") == "so_cap"
    # Already normalized → no change
    assert normalize_target_level("cao_dang") == "cao_dang"
    # Unknown → pass-through (caller validates)
    assert normalize_target_level("xyz") == "xyz"


# ===========================================================================
# Backward-compat: legacy "CD"/"TC"/"SC" call signature still works
# ===========================================================================


def test_validate_eligibility_legacy_cd_alias_works() -> None:
    profile = _profile(cultural="graduated_thpt")
    ok, _ = validate_eligibility(profile, "CD")
    assert ok is True


def test_validate_eligibility_legacy_tc_alias_works() -> None:
    profile = _profile(cultural="graduated_thcs")
    ok, _ = validate_eligibility(profile, "TC")
    assert ok is True
