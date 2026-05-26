"""Anchor tests for Q9 #07 Phase B.2 KV dataset builder (Stage 1A).

Verifies parser logic + KV classification rule. Uses synthetic SQL fixtures
to avoid coupling to Documents/Seeding data/ (which is not in test fixture
search path + ships outside Docker image).

Related: [[q9-07-pr5-phase-a-shipped-2026-05-18]]
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.scripts.build_qd861_kv_dataset import (
    Province,
    Ward,
    _unescape_sql,
    build_rows,
    classify_kv,
    parse_provinces,
    parse_wards,
)


# ---------- Fixtures ----------

PROVINCES_SQL = """
INSERT INTO provinces (id, province_code, name, short_name, code, place_type, country_code) VALUES
    (1, '01', 'Thành phố Hà Nội', 'Thành phố Hà Nội', 'HNI', 'Thành phố Trung Ương', 'VN'),
    (2, '68', 'Lâm Đồng', 'Lâm Đồng', 'LDG', 'Tỉnh', 'VN'),
    (3, '79', 'Thành phố Hồ Chí Minh', 'Thành phố Hồ Chí Minh', 'HCM', 'Thành phố Trung Ương', 'VN');
"""

WARDS_SQL = """
INSERT INTO wards (id, ward_code, name, province_code) VALUES (1, '00004', 'Phường Ba Đình', '01');
INSERT INTO wards (id, ward_code, name, province_code) VALUES (34, '00376', 'Xã Sóc Sơn', '01');
INSERT INTO wards (id, ward_code, name, province_code) VALUES (741, '06994', 'Đặc khu Vân Đồn', '01');
INSERT INTO wards (id, ward_code, name, province_code) VALUES (2423, '24829', 'Phường B''Lao', '68');
INSERT INTO wards (id, ward_code, name, province_code) VALUES (2438, '24934', 'Xã D''Ran', '68');
INSERT INTO wards (id, ward_code, name, province_code) VALUES (3000, '99999', 'Phường Bến Nghé', '79');
"""


@pytest.fixture
def seed_files(tmp_path: Path) -> tuple[Path, Path]:
    p = tmp_path / "provinces.sql"
    w = tmp_path / "wards.sql"
    p.write_text(PROVINCES_SQL, encoding="utf-8")
    w.write_text(WARDS_SQL, encoding="utf-8")
    return p, w


# ---------- Unit tests ----------

def test_unescape_sql_apostrophe():
    assert _unescape_sql("B''Lao") == "B'Lao"
    assert _unescape_sql("Plain") == "Plain"


def test_parse_provinces_handles_tp_tu_flag(seed_files):
    p_sql, _ = seed_files
    provinces = parse_provinces(p_sql)
    assert set(provinces) == {"01", "68", "79"}
    assert provinces["01"].is_tp_tu is True
    assert provinces["68"].is_tp_tu is False
    assert provinces["79"].is_tp_tu is True


def test_parse_wards_decodes_apostrophe(seed_files):
    _, w_sql = seed_files
    wards = parse_wards(w_sql)
    assert len(wards) == 6
    apostrophe = [w for w in wards if w.code == "24829"][0]
    assert apostrophe.name == "Phường B'Lao"


def test_ward_kind_classification():
    assert Ward("1", "Phường X", "01").kind == "PHUONG"
    assert Ward("2", "Xã Y", "01").kind == "XA"
    assert Ward("3", "Đặc khu Z", "01").kind == "DAC_KHU"


@pytest.mark.parametrize(
    "ward_name,province_tp_tu,expected",
    [
        ("Đặc khu Vân Đồn", False, "KV1"),  # island override always KV1
        ("Đặc khu Bạch Long Vĩ", True, "KV1"),
        ("Phường Ba Đình", True, "KV3"),  # TP TƯ + Phường
        ("Xã Sóc Sơn", True, "KV2"),       # TP TƯ + Xã
        ("Phường B'Lao", False, "KV2"),    # Tỉnh + Phường
        ("Xã D'Ran", False, "KV2-NT"),     # Tỉnh + Xã (rural default)
    ],
)
def test_classify_kv_matrix(ward_name, province_tp_tu, expected):
    p = Province(
        code="00",
        name="Test",
        place_type="Thành phố Trung Ương" if province_tp_tu else "Tỉnh",
    )
    w = Ward("0", ward_name, "00")
    assert classify_kv(w, p) == expected


def test_build_rows_full_pipeline(seed_files):
    p_sql, w_sql = seed_files
    provinces = parse_provinces(p_sql)
    wards = parse_wards(w_sql)
    rows = build_rows(provinces, wards)
    assert len(rows) == 6

    by_code = {r["commune_code"]: r for r in rows}

    # commune_code = raw ward.code (revised 2026-05-26 — dropped province prefix;
    # ward.code is nationally-unique + matches FE permanent_commune_code)
    assert "00004" in by_code
    assert "24829" in by_code

    # district always empty (post-sáp nhập 2025)
    assert all(r["district"] == "" for r in rows)

    # area_code regex match
    import re
    assert all(re.match(r"^KV[1-9](-NT)?$", r["area_code"]) for r in rows)

    # KV mapping spot checks
    assert by_code["00004"]["area_code"] == "KV3"  # HN Phường
    assert by_code["00376"]["area_code"] == "KV2"  # HN Xã
    assert by_code["06994"]["area_code"] == "KV1"  # Đặc khu (any province)
    assert by_code["24829"]["area_code"] == "KV2"  # Lâm Đồng Phường
    assert by_code["24934"]["area_code"] == "KV2-NT"  # Lâm Đồng Xã

    # Apostrophe preserved end-to-end
    assert by_code["24829"]["ward"] == "Phường B'Lao"


def test_build_rows_rejects_unknown_province(tmp_path):
    p_sql = tmp_path / "provinces.sql"
    w_sql = tmp_path / "wards.sql"
    p_sql.write_text(PROVINCES_SQL, encoding="utf-8")
    w_sql.write_text(
        "INSERT INTO wards (id, ward_code, name, province_code) "
        "VALUES (1, '00001', 'Xã Test', '99');\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown province"):
        build_rows(parse_provinces(p_sql), parse_wards(w_sql))
