"""Phase C.5 anchor tests — KV resolution algorithm + eligibility validate.

Tests the v1.3 multi-school KV resolution rule per TT 05/2021 Phụ lục 01
+ TT 06/2026/TT-BGDĐT Phụ lục I.

Covers:
- 6-row matrix `_derive_kv_basis_level()` (cultural × vocational)
- 3 area_basis bypass (permanent_address_special / manual_override / NOT_RESOLVED)
- M1 ambiguous tiebreak detection
- validate_eligibility() for CĐ/TC/SC target levels

Schema refs:
- [[q9-07-pr5-phase-a-shipped-2026-05-18]]
- `Documents/Q9_07_PR5_REDESIGN.md` v1.3
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.priority_service import (
    _derive_kv_basis_level,
    resolve_kv_for_profile,
    validate_eligibility,
)


# =============================================================================
# C.1 — `_derive_kv_basis_level()` 6-row matrix + 3 bypass
# =============================================================================

@pytest.mark.parametrize(
    "cultural,vocational,area_basis,expected_basis",
    [
        # Phase E.4 commit 5: _derive_kv_basis_level rename basis values:
        #   "THPT" → "LICH_SU_THPT"
        #   "COMMUNE_FALLBACK" → "THUONG_TRU"
        # Legacy 3-arg signature (target_level=None) vẫn được hỗ trợ;
        # callers cũ fall vào legacy matrix branch.
        ("graduated_thpt", "none", None, "LICH_SU_THPT"),
        ("graduated_thpt", "trung_cap", None, "LICH_SU_THPT"),
        ("graduated_gdtx", "cao_dang", None, "LICH_SU_THPT"),
        ("completed_thpt", "trung_cap", None, "LICH_SU_THPT"),
        ("completed_thpt", "cao_dang", None, "LICH_SU_THPT"),
        # completed_thpt + so_cap/none — legacy branch fall back commune
        ("completed_thpt", "so_cap", None, "THUONG_TRU"),
        ("completed_thpt", "none", None, "THUONG_TRU"),
        # graduated_thcs all → THUONG_TRU (per nghiệp vụ 2026-05-18 user override)
        ("graduated_thcs", "trung_cap", None, "THUONG_TRU"),
        ("graduated_thcs", "cao_dang", None, "THUONG_TRU"),
        ("graduated_thcs", "so_cap", None, "THUONG_TRU"),
        ("graduated_thcs", "none", None, "THUONG_TRU"),
        ("completed_thcs", "none", None, "THUONG_TRU"),
        ("completed_thcs", "trung_cap", None, "THUONG_TRU"),
        # Cultural NULL → NOT_RESOLVED
        (None, "none", None, "NOT_RESOLVED"),
        (None, "trung_cap", None, "NOT_RESOLVED"),
        # area_basis bypass — output overrides matrix
        ("graduated_thpt", "none", "permanent_address_special", "COMMUNE_SPECIAL"),
        ("graduated_thcs", "trung_cap", "permanent_address_special", "COMMUNE_SPECIAL"),
        (None, "none", "permanent_address_special", "COMMUNE_SPECIAL"),
        ("graduated_thpt", "none", "manual_override", "MANUAL"),
        ("graduated_thcs", "cao_dang", "manual_override", "MANUAL"),
    ],
)
def test_derive_kv_basis_level_full_matrix(
    cultural, vocational, area_basis, expected_basis
):
    # Phase E.4: returns tuple (basis, basis_reason). Test pin basis only;
    # basis_reason coverage trong test_priority_eligibility_kv_matrix.py mới.
    basis, _reason = _derive_kv_basis_level(
        cultural=cultural,
        vocational=vocational,
        area_resolution_basis=area_basis,
    )
    assert basis == expected_basis


def test_derive_kv_basis_level_unknown_cultural_defensive():
    """Defensive: unknown cultural (CHECK should prevent, but defensive)."""
    basis, _reason = _derive_kv_basis_level(
        cultural="alien_value",
        vocational="none",
        area_resolution_basis=None,
    )
    assert basis == "NOT_RESOLVED"


# =============================================================================
# C.2 — `resolve_kv_for_profile()` algorithm
# =============================================================================

def _mock_profile(**kwargs):
    """Build a SimpleNamespace profile with defaults."""
    defaults = {
        "id": 1,
        "cultural_education_level": None,
        "vocational_qualification": "none",
        "area_resolution_basis": None,
        "permanent_commune_code": None,
        "academic_history": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _Result:
    """Plain Result mock — `scalar_one_or_none()` returns stored value."""

    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _mock_db(commune_kv=None, school_kv_sequence=None):
    """Build mock DB.

    - `commune_kv`: single string returned for any vn_commune_area_map lookup
    - `school_kv_sequence`: list of KV strings returned in call order for
      vn_school_kv_assignment lookups (pop from front each call).
    """
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


@pytest.mark.asyncio
async def test_resolve_kv_special_case_with_commune():
    """Row 8: area_resolution_basis='permanent_address_special' + commune set."""
    profile = _mock_profile(
        cultural_education_level="graduated_thcs",  # would normally be TC pathway
        area_resolution_basis="permanent_address_special",
        permanent_commune_code="66_24305",
    )
    db = _mock_db(commune_kv="KV1")
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv == "KV1"
    assert meta["pathway"] == "commune_special"
    assert meta["rule_applied"] == "commune_lookup"


@pytest.mark.asyncio
async def test_resolve_kv_special_case_no_commune_requires_manual():
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        area_resolution_basis="permanent_address_special",
        permanent_commune_code=None,
    )
    db = _mock_db()
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv is None
    assert meta["requires_manual_override"] is True
    assert meta["pathway"] == "commune_special"


@pytest.mark.asyncio
async def test_resolve_kv_manual_override_returns_none():
    """Row 9: manual_override — service returns None (admin populates snapshot directly)."""
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        area_resolution_basis="manual_override",
    )
    db = _mock_db()
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv is None
    assert meta["rule_applied"] == "manual_override"
    assert meta["pathway"] == "manual"


@pytest.mark.asyncio
async def test_resolve_kv_draft_cultural_not_set():
    """Row 7: cultural NULL → NOT_RESOLVED + no manual override flag (draft state)."""
    profile = _mock_profile(cultural_education_level=None)
    db = _mock_db()
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv is None
    assert meta["pathway"] == "not_resolved"
    assert meta["reason"] == "cultural_not_set"


@pytest.mark.asyncio
async def test_resolve_kv_commune_fallback_thcs_only():
    """Row 5: graduated_thcs + none → COMMUNE_FALLBACK."""
    profile = _mock_profile(
        cultural_education_level="graduated_thcs",
        vocational_qualification="none",
        permanent_commune_code="66_22255",
    )
    db = _mock_db(commune_kv="KV2-NT")
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv == "KV2-NT"
    assert meta["pathway"] == "thuong_tru"


@pytest.mark.asyncio
async def test_resolve_kv_thpt_tied_then_tiebreak_graduation():
    """Row 1: 2 schools tied 2 years each → tiebreak by graduation school."""
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {"school_id": 100, "level": "THPT", "year_from": 2020, "year_to": 2021, "grade_to": 11},
            {"school_id": 200, "level": "THPT", "year_from": 2022, "year_to": 2023, "grade_to": 12},
        ],
    )
    # 4 year lookups + 1 graduation lookup = 5 KV calls
    db = _mock_db(school_kv_sequence=[
        "KV1", "KV1",  # school 100 → 2 years KV1
        "KV3", "KV3",  # school 200 → 2 years KV3
        "KV3",         # graduation lookup (school 200, year 2023)
    ])
    kv, meta = await resolve_kv_for_profile(profile, db)
    # School 200 is graduation (year_to=2023 > 2021, grade_to=12 > 11)
    assert kv == "KV3"
    assert meta["pathway"] == "lich_su_thpt"
    assert meta["rule_applied"] == "tiebreak_graduation_school"
    assert meta["breakdown"]["graduation_school_id"] == 200


@pytest.mark.asyncio
async def test_resolve_kv_thpt_clear_longest_winner():
    """Single KV dominates → longest_duration (no tiebreak)."""
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {"school_id": 100, "level": "THPT", "year_from": 2020, "year_to": 2022, "grade_to": 11},  # 3 years
            {"school_id": 200, "level": "THPT", "year_from": 2023, "year_to": 2023, "grade_to": 12},  # 1 year
        ],
    )
    db = _mock_db(school_kv_sequence=[
        "KV1", "KV1", "KV1",  # school 100 → 3 years KV1
        "KV3",                # school 200 → 1 year KV3
    ])
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv == "KV1"
    assert meta["rule_applied"] == "longest_duration"
    assert meta["breakdown"]["winner_years"] == 3


@pytest.mark.asyncio
async def test_resolve_kv_m1_ambiguous_tied_graduation():
    """M1 edge: 2 schools tied year_to + grade_to → require manual."""
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {"school_id": 100, "level": "THPT", "year_from": 2021, "year_to": 2023, "grade_to": 12},
            {"school_id": 200, "level": "THPT", "year_from": 2021, "year_to": 2023, "grade_to": 12},
        ],
    )
    db = _mock_db(school_kv_sequence=[
        "KV1", "KV1", "KV1",  # school 100 → 3 years KV1
        "KV3", "KV3", "KV3",  # school 200 → 3 years KV3
    ])
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv is None
    assert meta["rule_applied"] == "ambiguous_requires_manual"
    assert meta["reason"] == "tied_graduation_year_and_grade"
    assert meta["requires_manual_override"] is True
    assert set(meta["breakdown"]["tied_entries"]) == {100, 200}


@pytest.mark.asyncio
async def test_resolve_kv_no_qualifying_entries():
    """Cultural pathway THPT but no entries with level='THPT' in history.

    Phase E.4 commit 5: rule_applied = 'insufficient_data', reason rename.
    """
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        academic_history=[
            # All level=THCS, no THPT
            {"school_id": 50, "level": "THCS", "year_from": 2017, "year_to": 2019},
        ],
    )
    db = _mock_db()
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv is None
    assert meta["requires_manual_override"] is True
    assert meta["rule_applied"] == "insufficient_data"
    assert meta["reason"] == "no_qualifying_thpt_history_entries"


@pytest.mark.asyncio
async def test_resolve_kv_thpt_accepts_thcs_thpt_lien_cap():
    """Row 1+ extension: graduated_thpt + level='THCS_THPT' (liên cấp 2-3) → KV resolve.

    Bug fix (Q9 #07 Phase D.4 audit): engine filter previously hard-coded
    level=='THPT' which excluded THCS_THPT liên cấp candidates. Both
    standalone THPT + THCS_THPT now accepted for THPT basis.
    """
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {
                "school_id": 100,
                "level": "THCS_THPT",  # ← liên cấp
                "year_from": 2020,
                "year_to": 2022,
                "grade_to": 12,
            },
        ],
    )
    db = _mock_db(school_kv_sequence=["KV1", "KV1", "KV1"])
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv == "KV1"
    assert meta["pathway"] == "lich_su_thpt"
    assert meta["breakdown"]["winner_years"] == 3


@pytest.mark.asyncio
async def test_resolve_kv_thcs_plus_tc_falls_to_commune():
    """Nghiệp vụ user 2026-05-18: TN THCS bất kể có bằng TC → KV theo hộ khẩu.

    Original v1.3 design Row 4 (TC basis cho liên thông TC pathway) overridden
    by trường nghiệp vụ. Engine should fallback to commune_lookup even when
    candidate khai TC school history.
    """
    profile = _mock_profile(
        cultural_education_level="graduated_thcs",
        vocational_qualification="trung_cap",
        permanent_commune_code="40_03139",
        academic_history=[
            {
                "school_id": 200,
                "level": "TRUNG_HOC_NGHE",  # candidate khai TC nhưng engine ignore
                "year_from": 2022,
                "year_to": 2024,
                "grade_to": 12,
            },
        ],
    )
    db = _mock_db(commune_kv="KV1")
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv == "KV1"
    assert meta["pathway"] == "thuong_tru"
    assert meta["rule_applied"] == "commune_lookup"


# =============================================================================
# C.4 — validate_eligibility()
# =============================================================================

@pytest.mark.parametrize(
    "cultural,vocational,target,expected_ok",
    [
        # CĐ target — Path 1: tốt nghiệp THPT/GDTX
        ("graduated_thpt", "none", "CD", True),
        ("graduated_gdtx", "none", "CD", True),
        # CĐ target — Path 2: liên thông (THPT kiến thức + TC)
        ("completed_thpt", "trung_cap", "CD", True),
        # CĐ chính quy mới (Phase E.4 chốt 2026-05-21): TN_THPT hoặc
        # HOAN_THANH_THPT — completed_thpt được phép vì "hoàn thành THPT"
        # đủ cho CĐ chính quy. Trước commit này test expected False; sau
        # commit eligibility wire mới, validate_eligibility(default admission_type
        # = chinh_quy) PASS completed_thpt cho CĐ.
        ("completed_thpt", "none", "CD", True),
        ("graduated_thcs", "trung_cap", "CD", False),  # Chưa TN THPT → CD FAIL (path 2 strict)
        ("graduated_thcs", "none", "CD", False),  # Chỉ TN THCS → CD FAIL
        ("completed_thcs", "trung_cap", "CD", False),  # Chưa đủ THPT → CD FAIL
        (None, "none", "CD", False),  # Cultural draft → CD FAIL
        # TC target — TN THCS trở lên OK
        ("graduated_thcs", "none", "TC", True),
        ("graduated_thpt", "none", "TC", True),
        ("completed_thpt", "so_cap", "TC", True),
        # TC target — completed_thcs OK (TT22); draft cultural (None) still fails
        ("completed_thcs", "none", "TC", True),
        (None, "none", "TC", False),
        # SC target — luôn pass
        ("completed_thcs", "none", "SC", True),
        (None, "none", "SC", True),
    ],
)
def test_validate_eligibility_matrix(cultural, vocational, target, expected_ok):
    profile = SimpleNamespace(
        cultural_education_level=cultural,
        vocational_qualification=vocational,
    )
    is_ok, reason = validate_eligibility(profile, target)
    assert is_ok is expected_ok, (
        f"({cultural}, {vocational}, {target}) → expected {expected_ok}, "
        f"got {is_ok} ({reason})"
    )
    if not expected_ok:
        assert reason is not None


# =============================================================================
# C.5b — Integration: temporal split data (depends on Phase B.1.b dedup)
# =============================================================================
#
# Verifies engine `resolve_kv_for_profile()` correctly hits historical
# vs current entries via vn_school_kv_assignment.effective_from/to_year.
# Anchor for Phase B.1.b dedup pattern (memory
# [[q9-07-pr5-phase-a-shipped-2026-05-18]]):
# - Buôn Ma Thuột Mã 002 (KV1 2000-2024) + Mã 090 (KV2 2025-now)
# - Lâm Đồng/Gia Lai dup pairs sau 04/6/2021 boundary
#
# Engine queries `WHERE :year BETWEEN effective_from_year AND COALESCE(
# effective_to_year, 9999)` per VnSchoolKvAssignment docstring.


@pytest.mark.asyncio
async def test_resolve_kv_pre_2025_history_hits_before_entry():
    """Candidate học 2020-2022 lớp 10→12 tại THPT Buôn Ma Thuột Mã 002 → KV1.

    Simulates Buôn Ma Thuột Mã 002 (effective 2000-2024 KV1).
    Engine lookup_kv_for_school_year(school_id=132, year=2020/2021/2022)
    → all hit before-row → KV1 dominates.
    """
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {
                "school_id": 132,
                "level": "THPT",
                "year_from": 2020,
                "year_to": 2022,
                "grade_to": 12,
            },
        ],
    )
    db = _mock_db(school_kv_sequence=["KV1", "KV1", "KV1"])
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv == "KV1"
    assert meta["pathway"] == "lich_su_thpt"
    assert meta["breakdown"]["winner_years"] == 3


@pytest.mark.asyncio
async def test_resolve_kv_post_2025_history_hits_after_entry():
    """Candidate học 2025-2027 tại THPT Buôn Ma Thuột Mã 090 → KV2.

    Simulates Buôn Ma Thuột Mã 090 (effective 2025-now KV2).
    """
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {
                "school_id": 162,
                "level": "THPT",
                "year_from": 2025,
                "year_to": 2027,
                "grade_to": 12,
            },
        ],
    )
    db = _mock_db(school_kv_sequence=["KV2", "KV2", "KV2"])
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv == "KV2"
    assert meta["breakdown"]["winner_years"] == 3


@pytest.mark.asyncio
async def test_resolve_kv_cross_period_max_duration_wins():
    """TT 05/2021 rule: candidate học 2-trường cross-period 2023-2026.

    2 năm pre-2025 KV1 + 2 năm post-2025 KV2 → tied → tiebreak graduation
    school (year_to=2026 grade=12 wins).
    """
    profile = _mock_profile(
        cultural_education_level="graduated_thpt",
        academic_history=[
            {
                "school_id": 132,
                "level": "THPT",
                "year_from": 2023,
                "year_to": 2024,
                "grade_to": 11,
            },
            {
                "school_id": 162,
                "level": "THPT",
                "year_from": 2025,
                "year_to": 2026,
                "grade_to": 12,
            },
        ],
    )
    # 2023, 2024 from school 132 → KV1
    # 2025, 2026 from school 162 → KV2
    # +1 graduation lookup for tiebreak (school 162, year 2026)
    db = _mock_db(school_kv_sequence=["KV1", "KV1", "KV2", "KV2", "KV2"])
    kv, meta = await resolve_kv_for_profile(profile, db)
    assert kv == "KV2"
    assert meta["rule_applied"] == "tiebreak_graduation_school"
    assert meta["breakdown"]["graduation_school_id"] == 162
