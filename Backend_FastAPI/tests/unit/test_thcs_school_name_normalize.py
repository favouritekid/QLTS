# -*- coding: utf-8 -*-
"""Công cụ ghép tên trường THCS (owner 22-11) — phần KHÔNG cần CSDL: hàm chuẩn hoá tên (MỘT nguồn, là khoá ghép),
vị từ "dòng THCS gõ tay" / "dòng y→y", chuỗi DDL model ↔ migration ``thcsmap20261122``.

Phần cần CSDL: ``tests/unit/test_thcs_school_mapping_service.py`` · nối dây: ``tests/api/test_thcs_school_mapping_api.py``.
"""
import importlib.util
import unicodedata
from pathlib import Path

import pytest
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models.thcs_school_name_mapping import ThcsSchoolNameMapping
from app.services.thcs_school_mapping_service import (
    APPLY_ACADEMIC_YEAR,
    APPLY_ELIGIBLE_STATUSES,
    candidate_profiles_stmt,
    is_apply_target,
    is_same_year_row,
    is_thcs_manual_row,
)
from app.services.thcs_school_name import NORMALIZED_NAME_MAX_LEN, normalize_thcs_school_name

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
TEP_MIGRATION = GOC / "alembic" / "versions" / "thcsmap20261122_thcs_school_name_mapping.py"


def _migration():
    spec = importlib.util.spec_from_file_location("thcsmap20261122", TEP_MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gon(s: str) -> str:
    return " ".join(s.split())


# ---------- chuẩn hoá tên ----------


@pytest.mark.parametrize(
    "goc,khoa",
    [
        ("Trường THCS Lê Lợi", "lê lợi"),
        ("THCS  Lê   Lợi.", "lê lợi"),
        ("trường trung học cơ sở Lê Lợi", "lê lợi"),
        ("TRƯỜNG THCS LÊ LỢI", "lê lợi"),
        ("Thcs Lê Lợi - xã Ea Tu", "lê lợi xã ea tu"),
        ("Truong THCS Le Loi", "le loi"),  # bỏ từ không dấu, nhưng GIỮ "le loi" ≠ "lê lợi"
        ("truong trung hoc co so Le Loi", "le loi"),
        ("PTDTNT THCS Đăk Glei", "ptdtnt đăk glei"),  # DTNT phân biệt trường — giữ
        ("THCS bán trú Ea Kar", "bán trú ea kar"),
        ("THCS số 1 Ea Kar", "số 1 ea kar"),
        ("THCS&THPT Lê Lợi", "thpt lê lợi"),
        ("THCS Nguyễn_Du", "nguyễn du"),
        ("THCS H'Leo", "h leo"),
        ("THCSX Lê Lợi", "thcsx lê lợi"),  # chỉ bỏ khi là TỪ RIÊNG
        ("Trường THCS", "trường thcs"),  # bỏ hết ⇒ giữ dạng chuẩn hoá nhẹ, không rỗng
        ("ĐĂK MIL", "đăk mil"),
    ],
)
def test_chuan_hoa_ten_truong(goc, khoa):
    assert normalize_thcs_school_name(goc) == khoa


@pytest.mark.parametrize("goc", [None, 123, "", "   ", "...", "  - "])
def test_chuan_hoa_khong_phai_ten_thi_rong(goc):
    assert normalize_thcs_school_name(goc) == ""


def test_chuan_hoa_dung_unicode_dung_san_va_to_hop_la_mot():
    nfc = unicodedata.normalize("NFC", "Trường THCS Lê Lợi")
    nfd = unicodedata.normalize("NFD", "Trường THCS Lê Lợi")
    assert nfc != nfd
    assert normalize_thcs_school_name(nfc) == normalize_thcs_school_name(nfd) == "lê lợi"


def test_chuan_hoa_giu_dau_tieng_viet():
    assert normalize_thcs_school_name("THCS Hồ Tùng Mậu") != normalize_thcs_school_name("THCS Hổ Tùng Mậu")


@pytest.mark.parametrize(
    "goc",
    ["Trường THCS Lê Lợi", "Trường THCS", "PTDTNT THCS Đăk Glei", "THCS H'Leo", "x" * 400],
)
def test_chuan_hoa_luy_dang(goc):
    """Khoá của nhóm phải là điểm bất động: chuẩn hoá lại không đổi (API ghép kiểm điều này)."""
    k = normalize_thcs_school_name(goc)
    assert normalize_thcs_school_name(k) == k
    assert len(k) <= NORMALIZED_NAME_MAX_LEN


# ---------- vị từ dòng THCS gõ tay / y→y ----------


@pytest.mark.parametrize(
    "dong,la_thcs_go_tay",
    [
        ({"graduation_type": "THCS", "school_id": None, "school_name": "x"}, True),
        ({"graduation_type": "THCS", "school_name": "x"}, True),  # thiếu khoá school_id
        ({"level": "THCS", "graduation_type": None, "school_name": "x"}, True),
        ({"graduation_type": "THCS", "school_id": 5, "school_name": "x"}, False),  # đã gắn trường
        ({"graduation_type": "THPT", "school_id": None, "school_name": "x"}, False),
        ({"level": "THCS_THPT", "school_id": None, "school_name": "x"}, False),
        ({"graduation_type": "thcs", "school_id": None, "school_name": "x"}, False),  # đúng chữ như dữ liệu
        ("THCS", False),
        (None, False),
    ],
)
def test_vi_tu_dong_thcs_go_tay(dong, la_thcs_go_tay):
    assert is_thcs_manual_row(dong) is la_thcs_go_tay


def test_vi_tu_dong_y_y():
    assert is_same_year_row({"year_from": 2020, "year_to": 2020}) is True
    assert is_same_year_row({"year_from": 2019, "year_to": 2020}) is False
    assert is_same_year_row({"year_from": None, "year_to": None}) is False


def test_cau_loc_so_bo_gui_jsonpath_dang_hang_khong_qua_tham_so_varchar():
    """asyncpg ép tham số chuỗi ``::VARCHAR`` mà PostgreSQL không có ``jsonb_path_exists(jsonb, varchar)`` ⇒ câu lọc sơ
    bộ phải mang hằng ``::jsonpath`` (lỗi này chỉ lộ khi chạy trên CSDL thật)."""
    cau = str(candidate_profiles_stmt().compile(dialect=asyncpg.dialect()))
    assert "jsonb_path_exists(admission_profile.academic_history, '$[*] ? (" in cau, cau
    assert "::jsonpath)" in cau, cau
    assert "jsonb_path_exists(admission_profile.academic_history, $" not in cau, cau


def test_tap_trang_thai_duoc_cham_la_nhap_va_cho_xet_nam_2026():
    """Owner 22-11 (QUYET-DINH-OWNER-THCS-CONG-CU-GHEP) câu 1: nháp + chờ xét; câu 2: năm 2026."""
    assert APPLY_ELIGIBLE_STATUSES == ("draft", "submitted", "resubmitted", "revision_requested", "reviewing")
    assert APPLY_ACADEMIC_YEAR == 2026
    for ngoai in ("withdrawn", "withdrawal_pending", "result_published", "admitted", "waitlisted",
                  "rejected", "approved", "confirmed", "overridden", "enrolled"):
        assert ngoai not in APPLY_ELIGIBLE_STATUSES


@pytest.mark.parametrize(
    "ho_so,trong_pham_vi",
    [
        ({"status": "draft", "academic_year": 2026}, True),
        ({"status": "reviewing", "academic_year": 2026}, True),
        ({"status": "submitted", "academic_year": 2025}, False),
        ({"status": "admitted", "academic_year": 2026}, False),
        ({"status": "draft", "academic_year": None}, False),
    ],
)
def test_pham_vi_ap_ghep(ho_so, trong_pham_vi):
    assert is_apply_target(ho_so) is trong_pham_vi


# ---------- DDL: model == migration ----------


def test_migration_noi_tiep_ma_noi_bo():
    mig = _migration()
    assert (mig.revision, mig.down_revision) == ("thcsmap20261122", "thcsnb20261122")


def test_bang_ghep_model_bang_migration():
    mig = _migration()
    d = asyncpg.dialect()
    assert _gon(str(CreateTable(ThcsSchoolNameMapping.__table__).compile(dialect=d))) == _gon(mig.CREATE_TABLE)
    tu_model = sorted(
        _gon(str(CreateIndex(i).compile(dialect=d))) for i in ThcsSchoolNameMapping.__table__.indexes
    )
    assert tu_model == sorted(_gon(s) for s in mig.CREATE_INDEXES)
    for cau in (mig.CREATE_TABLE, *mig.CREATE_INDEXES):
        assert cau.strip() in mig._upgrade_sql()


def test_ha_cap_bang_ghep_fail_closed_trong_cung_cau_do():
    mig = _migration()
    cam = mig._downgrade_sql(False)
    cho = mig._downgrade_sql(True)
    assert "LOCK TABLE thcs_school_name_mapping" in cam
    assert cam.index("SELECT count(*)") < cam.index("DROP TABLE")
    assert "IF n > 0 AND NOT false THEN" in cam
    assert "IF n > 0 AND NOT true THEN" in cho
    assert mig.SQLSTATE_DOWNGRADE_DATA_PRESENT in cam
