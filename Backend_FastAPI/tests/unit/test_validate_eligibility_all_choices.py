"""Unit tests for ``_validate_eligibility_all_choices`` (Phase E.4 reviewer P0 fix).

Reviewer 2026-05-21 đã chỉ ra: gate eligibility nằm trong nhánh
``if profile.uses_choice_engine`` → 9/11 dev profile legacy single-path
bypass. Fix: gate chạy unconditional sau status draft check; helper xử lý
cả 2 flow.

Tests verify:
  - multi-NV (uses_choice_engine=True): loop choices, validate per choice
  - legacy single-path (uses_choice_engine=False): derive từ
    offering_admission_config_id, validate 1 chain
  - Cả 2 raise BusinessRuleViolation với reason rõ ràng khi fail
  - Cả 2 raise CONFIG_GAP_TARGET_LEVEL khi missing config

Mock pattern: AsyncMock cho db.execute dispatching theo statement target.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.admission_service import _validate_eligibility_all_choices
from app.utils.exceptions import BusinessRuleViolation


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make_path(degree_code: str, offering_code: str):
    """Build AdmissionPath stub với eager chain shape mà derive_target_level_and_type
    đọc qua __dict__."""
    degree_obj = SimpleNamespace(code=degree_code) if degree_code else None
    program = SimpleNamespace()
    program.__dict__["degree_level_ref"] = degree_obj

    offering_type_obj = SimpleNamespace(code=offering_code) if offering_code else None
    offering = SimpleNamespace()
    offering.__dict__["program"] = program
    offering.__dict__["offering_type_config"] = offering_type_obj

    academic_info = SimpleNamespace()
    academic_info.__dict__["offering"] = offering

    path = SimpleNamespace()
    path.__dict__["academic_info"] = academic_info
    return path


def _profile(
    cultural: str | None,
    vocational: str = "none",
    uses_choice_engine: bool = True,
    offering_admission_config_id: int | None = None,
):
    return SimpleNamespace(
        id=1,
        cultural_education_level=cultural,
        vocational_qualification=vocational,
        uses_choice_engine=uses_choice_engine,
        offering_admission_config_id=offering_admission_config_id,
    )


def _make_db_multi_nv(choices: list[SimpleNamespace]):
    """Mock db that returns choices for the multi-NV branch query."""
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=choices)

    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars_result)

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _make_db_legacy(config_stub: SimpleNamespace | None):
    """Mock db that returns single OfferingAdmissionConfig stub for legacy branch."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=config_stub)

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


# ===========================================================================
# multi-NV branch — pass + fail cases
# ===========================================================================


async def test_multi_nv_all_choices_pass_same_target_type() -> None:
    """Multi-NV cùng (cao_dang, chinh_quy) cho cả 2 NV → consistency pass."""
    profile = _profile(cultural="graduated_thpt", uses_choice_engine=True)
    choices = [
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=1,
        ),
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=2,
        ),
    ]
    db = _make_db_multi_nv(choices)

    # Should not raise
    await _validate_eligibility_all_choices(db, profile)


async def test_multi_nv_one_choice_fails_blocks_submit() -> None:
    """cultural=graduated_thcs + cả 2 NV CĐ chính quy → CĐ fail eligibility
    cho cả 2; raise ELIGIBILITY_FAIL (KHÔNG raise MULTI_NV vì consistency OK)."""
    profile = _profile(cultural="graduated_thcs", uses_choice_engine=True)
    choices = [
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=1,
        ),
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=2,
        ),
    ]
    db = _make_db_multi_nv(choices)

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    assert "ELIGIBILITY_FAIL" in str(exc.value)
    assert "NV1" in str(exc.value)
    assert "cao_dang" in str(exc.value)


# ===========================================================================
# Phase E.4 commit 6 — Multi-NV consistency guard (yêu cầu nghiệp vụ #12)
# ===========================================================================


async def test_multi_nv_inconsistent_target_levels_blocks() -> None:
    """2 NV với target_level khác nhau (CĐ vs TC) → MULTI_NV_INCONSISTENT.
    Profile cultural OK cho cả 2 (graduated_thpt) — block hoàn toàn do
    target/type mismatch, không phải eligibility data."""
    profile = _profile(cultural="graduated_thpt", uses_choice_engine=True)
    choices = [
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=1,
        ),
        SimpleNamespace(
            admission_path=_make_path("trung_cap", "chinh_quy"),
            display_order=2,
        ),
    ]
    db = _make_db_multi_nv(choices)

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    msg = str(exc.value)
    assert "MULTI_NV_INCONSISTENT" in msg
    assert "NV1=cao_dang/chinh_quy" in msg
    assert "NV2=trung_cap/chinh_quy" in msg
    assert "tách thành nhiều hồ sơ riêng" in msg


async def test_multi_nv_inconsistent_admission_types_blocks() -> None:
    """Cùng target_level (CĐ) nhưng admission_type khác (chính quy vs liên thông)
    → MULTI_NV_INCONSISTENT."""
    profile = _profile(
        cultural="graduated_thpt",
        vocational="trung_cap",
        uses_choice_engine=True,
    )
    choices = [
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=1,
        ),
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "lien_thong"),
            display_order=2,
        ),
    ]
    db = _make_db_multi_nv(choices)

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    msg = str(exc.value)
    assert "MULTI_NV_INCONSISTENT" in msg
    assert "NV1=cao_dang/chinh_quy" in msg
    assert "NV2=cao_dang/lien_thong" in msg


async def test_multi_nv_same_target_and_type_passes() -> None:
    """3 NV cùng CĐ chính quy (chỉ khác admission_method qua path config) →
    consistency pass; eligibility check cho mỗi NV."""
    profile = _profile(cultural="graduated_thpt", uses_choice_engine=True)
    choices = [
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=1,
        ),
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=2,
        ),
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=3,
        ),
    ]
    db = _make_db_multi_nv(choices)

    # Should not raise
    await _validate_eligibility_all_choices(db, profile)


async def test_single_nv_no_consistency_check_needed() -> None:
    """1 NV duy nhất → consistency check skip (chỉ fire khi len(choices) >= 2)."""
    profile = _profile(cultural="graduated_thpt", uses_choice_engine=True)
    choices = [
        SimpleNamespace(
            admission_path=_make_path("cao_dang", "chinh_quy"),
            display_order=1,
        ),
    ]
    db = _make_db_multi_nv(choices)

    # Should not raise
    await _validate_eligibility_all_choices(db, profile)


async def test_multi_nv_inconsistent_with_eligibility_fail_prefers_consistency_msg() -> (
    None
):
    """Khi cả 2 vấn đề tồn tại (multi-NV inconsistent + eligibility fail
    cho ít nhất 1 NV), helper raise MULTI_NV_INCONSISTENT trước (architectural
    error first; data error after split sẽ surface eligibility riêng cho mỗi
    hồ sơ con)."""
    profile = _profile(cultural="graduated_thcs", uses_choice_engine=True)
    choices = [
        SimpleNamespace(
            admission_path=_make_path(
                "cao_dang", "chinh_quy"
            ),  # graduated_thcs fail CĐ
            display_order=1,
        ),
        SimpleNamespace(
            admission_path=_make_path("trung_cap", "chinh_quy"),  # graduated_thcs OK TC
            display_order=2,
        ),
    ]
    db = _make_db_multi_nv(choices)

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    # Multi-NV raise BEFORE eligibility (loop collects both, raise MULTI first)
    assert "MULTI_NV_INCONSISTENT" in str(exc.value)


async def test_legacy_non_multi_nv_no_consistency_check() -> None:
    """uses_choice_engine=False (legacy single-path) — không có multi-NV concept."""
    profile = _profile(
        cultural="graduated_thpt",
        uses_choice_engine=False,
        offering_admission_config_id=42,
    )
    path = _make_path("cao_dang", "chinh_quy")
    config_stub = SimpleNamespace()
    config_stub.academic_info = path.__dict__["academic_info"]
    db = _make_db_legacy(config_stub=config_stub)

    # Should not raise
    await _validate_eligibility_all_choices(db, profile)


async def test_multi_nv_config_gap_blocks() -> None:
    # Path thiếu degree_level_ref → helper raise CONFIG_GAP_TARGET_LEVEL
    profile = _profile(cultural="graduated_thpt", uses_choice_engine=True)
    choices = [
        SimpleNamespace(
            admission_path=_make_path(None, "chinh_quy"),  # missing degree
            display_order=1,
        ),
    ]
    db = _make_db_multi_nv(choices)

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    assert "CONFIG_GAP_TARGET_LEVEL" in str(exc.value)


# ===========================================================================
# Legacy non-multi-NV branch (uses_choice_engine=False)
# ===========================================================================


async def test_legacy_no_config_id_raises_config_gap() -> None:
    # Reviewer P0 finding: legacy profile chưa có offering_admission_config_id
    # phải block CONFIG_GAP_TARGET_LEVEL (fail-closed, KHÔNG fallback SC).
    profile = _profile(
        cultural="graduated_thpt",
        uses_choice_engine=False,
        offering_admission_config_id=None,
    )
    db = _make_db_legacy(config_stub=None)

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    assert "CONFIG_GAP_TARGET_LEVEL" in str(exc.value)


async def test_legacy_config_id_missing_in_db_raises() -> None:
    profile = _profile(
        cultural="graduated_thpt",
        uses_choice_engine=False,
        offering_admission_config_id=999,
    )
    db = _make_db_legacy(config_stub=None)  # query returns None

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    assert "CONFIG_GAP_TARGET_LEVEL" in str(exc.value)
    assert "999" in str(exc.value)


async def test_legacy_cd_chinh_quy_graduated_thcs_blocks() -> None:
    # Reviewer regression: CD chính quy + cultural=graduated_thcs → block
    profile = _profile(
        cultural="graduated_thcs",
        uses_choice_engine=False,
        offering_admission_config_id=42,
    )
    # OfferingAdmissionConfig chain: academic_info → offering → program/offering_type
    path = _make_path("cao_dang", "chinh_quy")
    config_stub = SimpleNamespace()
    config_stub.academic_info = path.__dict__["academic_info"]
    db = _make_db_legacy(config_stub=config_stub)

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    assert "ELIGIBILITY_FAIL" in str(exc.value)
    assert "Legacy single-path" in str(exc.value)
    assert "cao_dang" in str(exc.value)


@pytest.mark.parametrize(
    "cultural",
    ["completed_thpt", "graduated_thpt", "graduated_gdtx"],
)
async def test_legacy_cd_chinh_quy_thpt_knowledge_passes(cultural: str) -> None:
    # Reviewer regression: CD chính quy + cultural=completed_thpt/graduated_thpt
    # → pass (nghiệp vụ #5: "TN_THPT hoặc HOAN_THANH_THPT").
    profile = _profile(
        cultural=cultural,
        uses_choice_engine=False,
        offering_admission_config_id=42,
    )
    path = _make_path("cao_dang", "chinh_quy")
    config_stub = SimpleNamespace()
    config_stub.academic_info = path.__dict__["academic_info"]
    db = _make_db_legacy(config_stub=config_stub)

    # Should not raise
    await _validate_eligibility_all_choices(db, profile)


async def test_legacy_tc_chinh_quy_graduated_thcs_passes() -> None:
    profile = _profile(
        cultural="graduated_thcs",
        uses_choice_engine=False,
        offering_admission_config_id=42,
    )
    path = _make_path("trung_cap", "chinh_quy")
    config_stub = SimpleNamespace()
    config_stub.academic_info = path.__dict__["academic_info"]
    db = _make_db_legacy(config_stub=config_stub)

    await _validate_eligibility_all_choices(db, profile)


async def test_legacy_tc_chinh_quy_completed_thcs_passes() -> None:
    profile = _profile(
        cultural="completed_thcs",
        uses_choice_engine=False,
        offering_admission_config_id=42,
    )
    path = _make_path("trung_cap", "chinh_quy")
    config_stub = SimpleNamespace()
    config_stub.academic_info = path.__dict__["academic_info"]
    db = _make_db_legacy(config_stub=config_stub)

    await _validate_eligibility_all_choices(db, profile)


async def test_legacy_sc_chinh_quy_no_cultural_passes() -> None:
    profile = _profile(
        cultural=None,  # SC không yêu cầu văn hóa
        uses_choice_engine=False,
        offering_admission_config_id=42,
    )
    path = _make_path("so_cap", "chinh_quy")
    config_stub = SimpleNamespace()
    config_stub.academic_info = path.__dict__["academic_info"]
    db = _make_db_legacy(config_stub=config_stub)

    await _validate_eligibility_all_choices(db, profile)


async def test_legacy_cd_lien_thong_requires_vocational() -> None:
    # CĐ liên thông + graduated_thpt + vocational=none → block (cần TC/CĐ)
    profile = _profile(
        cultural="graduated_thpt",
        vocational="none",
        uses_choice_engine=False,
        offering_admission_config_id=42,
    )
    path = _make_path("cao_dang", "lien_thong")
    config_stub = SimpleNamespace()
    config_stub.academic_info = path.__dict__["academic_info"]
    db = _make_db_legacy(config_stub=config_stub)

    with pytest.raises(BusinessRuleViolation) as exc:
        await _validate_eligibility_all_choices(db, profile)
    assert "ELIGIBILITY_FAIL" in str(exc.value)
    assert "lien_thong" in str(exc.value)


async def test_legacy_cd_lien_thong_with_trung_cap_passes() -> None:
    profile = _profile(
        cultural="graduated_thpt",
        vocational="trung_cap",
        uses_choice_engine=False,
        offering_admission_config_id=42,
    )
    path = _make_path("cao_dang", "lien_thong")
    config_stub = SimpleNamespace()
    config_stub.academic_info = path.__dict__["academic_info"]
    db = _make_db_legacy(config_stub=config_stub)

    await _validate_eligibility_all_choices(db, profile)
