"""Anchor tests for Phase B.1.a MOET THPT import script.

Tests pure helpers — no DB integration (DB import covered by manual
verify in `Documents/reports/dak_lak_kv_table_report.md`).

Related:
- [[q9-07-pr5-phase-a-shipped-2026-05-18]] Phase A schema
- [[moet-2025-school-list-findings]] file structure
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.scripts.import_moet_schools_3_provinces import (
    SPECIAL_SCHOOL_CODES,
    TARGET_PROVINCES,
    build_rows,
    is_special_school,
    normalize_kv,
)


# ---------- normalize_kv ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("KV1", "KV1"),
        ("kv1", "KV1"),
        ("KV-1", "KV1"),
        ("KV 1", "KV1"),
        ("KV2", "KV2"),
        ("KV3", "KV3"),
        ("KV2-NT", "KV2-NT"),
        ("KV2NT", "KV2-NT"),
        ("kv2nt", "KV2-NT"),
        ("KV 2 NT", "KV2-NT"),
    ],
)
def test_normalize_kv_canonical_forms(raw, expected):
    assert normalize_kv(raw) == expected


def test_normalize_kv_empty():
    assert normalize_kv("") == ""
    assert normalize_kv(None) == ""


# ---------- is_special_school ----------

@pytest.mark.parametrize(
    "code,expected",
    [
        ("800", True),  # Học ở nước ngoài
        ("801", True),  # Trường THPT - Khu vực 1 (wildcard)
        ("802", True),
        ("803", True),
        ("804", True),
        ("900", True),  # Quân nhân, Công an
        ("002", False),  # Real school
        ("090", False),
        ("123", False),
    ],
)
def test_is_special_school(code, expected):
    assert is_special_school(code) is expected


def test_special_codes_complete():
    """Sanity: SPECIAL_SCHOOL_CODES contains the 6 known MOET pseudo-codes."""
    assert SPECIAL_SCHOOL_CODES == {"800", "801", "802", "803", "804", "900"}


# ---------- target provinces lock ----------

def test_target_provinces_locked():
    """Phase B.1.a scope locked to 3 Tây Nguyên provinces (per user 2026-05-18)."""
    assert set(TARGET_PROVINCES) == {"Lâm Đồng", "Đắk Lắk", "Gia Lai"}


# ---------- build_rows pipeline ----------

@pytest.fixture
def synthetic_master_df():
    """Synthetic MOET Excel matching 21/4/2025 file column layout."""
    return pd.DataFrame([
        # Đắk Lắk regular school
        [1, 40, "Đắk Lắk", 1, "TP Buôn Ma Thuột", "002", "THPT Buôn Ma Thuột",
         "Số 57 Bà Triệu", "KV1", None],
        # Đắk Lắk dup pair (same name, different mã + KV)
        [2, 40, "Đắk Lắk", 1, "TP Buôn Ma Thuột", "090", "THPT Buôn Ma Thuột",
         "Số 57 Bà Triệu, Tự An", "KV2", None],
        # Đắk Lắk DTNT
        [3, 40, "Đắk Lắk", 1, "TP Buôn Ma Thuột", "010", "THPT DTNT N'Trang Lơng",
         "BMT", "KV3", "x"],
        # Đắk Lắk special pseudo
        [4, 40, "Đắk Lắk", 0, "Sở GD", "800", "Học ở nước ngoài_40",
         None, "KV3", None],
        # Gia Lai real school
        [5, 38, "Gia Lai", 1, "TP Pleiku", "005",
         "Trường THPT Chuyên Hùng Vương (trước 04/6/2021)",
         "48 Hùng Vương", "KV1", None],
        # Excluded province (must be filtered out)
        [6, 1, "Hà Nội", 1, "Ba Đình", "062", "THPT Nguyễn Trãi",
         "50 Nam Cao", "KV3", None],
    ], columns=[
        "stt", "ma_tinh", "ten_tinh", "ma_huyen", "ten_huyen",
        "ma_truong", "ten_truong", "dia_chi", "khu_vuc", "dtnt",
    ])


def test_build_rows_filters_to_target_provinces(synthetic_master_df):
    rows = build_rows(synthetic_master_df, TARGET_PROVINCES)
    # 5 rows from 3 target provinces (Đắk Lắk x4 + Gia Lai x1); Hà Nội excluded
    assert len(rows) == 5
    provinces = {r["province"] for r in rows}
    assert provinces == {"Đắk Lắk", "Gia Lai"}
    assert "Hà Nội" not in provinces


def test_build_rows_zfill_province_code(synthetic_master_df):
    rows = build_rows(synthetic_master_df, TARGET_PROVINCES)
    by_code = {r["moet_school_code"]: r for r in rows}
    # Đắk Lắk mã 40 → zfill 3 → "040"
    assert by_code["002"]["moet_province_code"] == "040"
    # Gia Lai mã 38 → zfill 3 → "038"
    assert by_code["005"]["moet_province_code"] == "038"


def test_build_rows_zfill_district_code(synthetic_master_df):
    rows = build_rows(synthetic_master_df, TARGET_PROVINCES)
    by_code = {r["moet_school_code"]: r for r in rows}
    # ma_huyen 1 → zfill 5 → "00001"
    assert by_code["002"]["moet_district_code"] == "00001"


def test_build_rows_level_classification(synthetic_master_df):
    rows = build_rows(synthetic_master_df, TARGET_PROVINCES)
    by_code = {r["moet_school_code"]: r for r in rows}
    # Real schools → THPT
    assert by_code["002"]["level"] == "THPT"
    assert by_code["005"]["level"] == "THPT"
    assert by_code["010"]["level"] == "THPT"
    # Special pseudo → OTHER
    assert by_code["800"]["level"] == "OTHER"
    assert by_code["800"]["is_special"] is True


def test_build_rows_dtnt_flag(synthetic_master_df):
    rows = build_rows(synthetic_master_df, TARGET_PROVINCES)
    by_code = {r["moet_school_code"]: r for r in rows}
    # N'Trang Lơng has "x" in dtnt column
    assert by_code["010"]["is_dtnt"] is True
    # Regular schools no dtnt value
    assert by_code["002"]["is_dtnt"] is False
    assert by_code["005"]["is_dtnt"] is False


def test_build_rows_preserves_dup_pair(synthetic_master_df):
    """User concern: 'trường trùng nhau' — Option 1 naive keeps both rows."""
    rows = build_rows(synthetic_master_df, TARGET_PROVINCES)
    bmt = [r for r in rows if r["name"] == "THPT Buôn Ma Thuột"]
    assert len(bmt) == 2  # Mã 002 + 090 both preserved
    codes = {r["moet_school_code"] for r in bmt}
    assert codes == {"002", "090"}
    kvs = {r["kv_code"] for r in bmt}
    assert kvs == {"KV1", "KV2"}  # different temporal KV preserved
