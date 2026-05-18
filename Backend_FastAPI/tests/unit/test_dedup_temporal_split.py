"""Phase B.1.b anchor tests — Smart dedup + temporal split.

Covers `app/scripts/dedup_temporal_split.py`:

* Helper functions: `strip_date_suffix`, `parse_date_suffix`,
  `normalize_address`
* Decision logic: `determine_split()` Case A (DATE suffix) + Case B
  (Đắk Lắk Mã code gap) + skip cases

Integration smoke verifies pre-2025 lookup via resolve_kv_for_profile
returns historical KV (not current Phase B.1.a default 2025+ row).

See `Documents/Q9_07_PR5_REDESIGN.md` v1.3 + memory
[[q9-07-pr5-phase-a-shipped-2026-05-18]].
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.scripts.dedup_temporal_split import (
    DAK_LAK_MERGER_CUTOFF_YEAR,
    DAK_LAK_MERGER_FROM_YEAR,
    PRE_BOUNDARY_FROM_YEAR,
    determine_split,
    normalize_address,
    parse_date_suffix,
    strip_date_suffix,
)

# Integration tests for resolve_kv_for_profile() with temporal split data
# live in tests/unit/test_priority_kv_resolution.py (Phase C engine suite) —
# B.1.b ships data layer only, engine integration tested alongside engine
# code per memory `solo-dev-batch-prs-to-reduce-ci-overhead`.


# =============================================================================
# Helper: build mock VnSchool
# =============================================================================

def _school(code: str, name: str, province: str = "040", address: str = "x") -> SimpleNamespace:
    return SimpleNamespace(
        id=int(code) if code.isdigit() else 0,
        moet_province_code=province,
        moet_school_code=code,
        name=name,
        address=address,
        level="THPT",
    )


# =============================================================================
# T1 — strip_date_suffix()
# =============================================================================

@pytest.mark.parametrize("input_name,expected", [
    ("THPT Lê Lợi (trước 04/6/2021)", "THPT Lê Lợi"),
    ("THPT Lê Lợi (từ 04/6/2021)", "THPT Lê Lợi"),
    ("THPT Buôn Ma Thuột", "THPT Buôn Ma Thuột"),  # no suffix
    ("THPT X (từ 24/10/2024)", "THPT X"),  # different date format
    ("THPT Y  (trước 1/1/2020)  ", "THPT Y"),  # whitespace edge
])
def test_strip_date_suffix(input_name, expected):
    assert strip_date_suffix(input_name) == expected


# =============================================================================
# T2 — parse_date_suffix()
# =============================================================================

@pytest.mark.parametrize("input_name,expected", [
    ("THPT Lê Lợi (trước 04/6/2021)", ("trước", 2021)),
    ("THPT Lê Lợi (từ 04/6/2021)", ("từ", 2021)),
    ("THPT X (từ 24/10/2024)", ("từ", 2024)),
    ("THPT Y", None),  # no suffix
    ("THPT Z (vô nghĩa)", None),  # non-matching pattern
])
def test_parse_date_suffix(input_name, expected):
    assert parse_date_suffix(input_name) == expected


# =============================================================================
# T3 — normalize_address()
# =============================================================================

def test_normalize_address_lowercase_collapse():
    assert normalize_address("Số 27, Trần Nhật Duật") == "số 27, trần nhật duật"
    assert normalize_address("  multiple   spaces  ") == "multiple spaces"


def test_normalize_address_none_safe():
    assert normalize_address(None) == ""
    assert normalize_address("") == ""


# =============================================================================
# T4 — determine_split() Case A (both have DATE suffix)
# =============================================================================

def test_determine_split_case_a_canonical():
    """Gia Lai pattern: Mã 004 (trước) + Mã 104 (từ) cùng date."""
    cluster = [
        _school("004", "Trường THPT Lê Lợi (trước 04/6/2021)", province="038"),
        _school("104", "Trường THPT Lê Lợi (từ 04/6/2021)", province="038"),
    ]
    split = determine_split(cluster)
    assert split is not None
    assert split["case"] == "A"
    assert split["before"].moet_school_code == "004"
    assert split["after"].moet_school_code == "104"
    assert split["before_eff_from"] == PRE_BOUNDARY_FROM_YEAR  # 2000
    assert split["before_eff_to"] == 2020
    assert split["after_eff_from"] == 2021
    assert split["after_eff_to"] is None


def test_determine_split_case_a_different_dates():
    """Lâm Đồng pattern: 24/10/2024 sáp nhập"""
    cluster = [
        _school("079", "THPT Đạ Tẻh (trước 24/10/2024)", province="042"),
        _school("189", "THPT Đạ Tẻh (từ 24/10/2024)", province="042"),
    ]
    split = determine_split(cluster)
    assert split is not None
    assert split["case"] == "A"
    assert split["before_eff_to"] == 2023  # 2024 - 1
    assert split["after_eff_from"] == 2024


def test_determine_split_case_a_both_truoc_ambiguous():
    """Both 'trước' — ambiguous, skip."""
    cluster = [
        _school("001", "THPT A (trước 01/01/2020)"),
        _school("100", "THPT A (trước 01/01/2021)"),
    ]
    assert determine_split(cluster) is None


# =============================================================================
# T5 — determine_split() Case B (Đắk Lắk no-suffix Mã code gap)
# =============================================================================

def test_determine_split_case_b_buon_ma_thuot():
    """E2E target: THPT Buôn Ma Thuột Mã 002 (KV1 pre) + Mã 090 (KV2 post)."""
    cluster = [
        _school("002", "THPT Buôn Ma Thuột"),
        _school("090", "THPT Buôn Ma Thuột"),
    ]
    split = determine_split(cluster)
    assert split is not None
    assert split["case"] == "B"
    assert split["before"].moet_school_code == "002"
    assert split["after"].moet_school_code == "090"
    assert split["before_eff_from"] == PRE_BOUNDARY_FROM_YEAR  # 2000
    assert split["before_eff_to"] == DAK_LAK_MERGER_CUTOFF_YEAR  # 2024
    assert split["after_eff_from"] == DAK_LAK_MERGER_FROM_YEAR  # 2025
    assert split["after_eff_to"] is None


def test_determine_split_case_b_skip_both_in_low_range():
    """2 entries cùng tên cả 2 < 90 → không match Đắk Lắk pattern, skip."""
    cluster = [
        _school("020", "THPT X"),
        _school("030", "THPT X"),
    ]
    assert determine_split(cluster) is None


def test_determine_split_case_b_skip_both_in_high_range():
    """Both >= 90 → no pre/post split available."""
    cluster = [
        _school("095", "THPT Y"),
        _school("105", "THPT Y"),
    ]
    assert determine_split(cluster) is None


def test_determine_split_case_b_non_numeric_code_skipped():
    """Special pseudo entries (Mã 800/900/K01) → defer manual."""
    cluster = [
        _school("800", "Học ở nước ngoài"),
        _school("900", "Quân nhân tại ngũ"),
    ]
    # Both are numeric but pseudo — pass int check, then 800 > 89 and 900 > 89
    # → fails low_code check → returns None
    assert determine_split(cluster) is None


# =============================================================================
# T6 — determine_split() skip cases
# =============================================================================

def test_determine_split_single_entry_skipped():
    """Cluster of 1 → no pair to split."""
    assert determine_split([_school("001", "Lone")]) is None


def test_determine_split_3plus_cluster_skipped():
    """Cluster size 3+ → defer manual (M1 ambiguous risk)."""
    cluster = [
        _school("001", "THPT Z"),
        _school("050", "THPT Z"),
        _school("100", "THPT Z"),
    ]
    assert determine_split(cluster) is None


def test_determine_split_asymmetric_one_has_suffix():
    """1 có DATE suffix + 1 không → asymmetric, manual review."""
    cluster = [
        _school("195", "THPT Đạ Tẻh"),  # no suffix
        _school("207", "THPT Đạ Tẻh (từ 24/10/2024)"),
    ]
    assert determine_split(cluster) is None


