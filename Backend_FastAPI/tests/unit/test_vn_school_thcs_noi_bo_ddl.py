# -*- coding: utf-8 -*-
"""Danh mục THCS (owner 22-11) — phần KHÔNG cần CSDL: mã nội bộ ``NB`` + 6 số, chuỗi DDL model ↔ migration
``thcsnb20261122``, và lớp lọc ``NB…`` của các bộ nạp danh mục Bộ ở mức dữ liệu nguồn.

Phần cần CSDL (sinh mã từ sequence, bộ nạp không khớp trường ``NB…`` trên bảng thật, KV gợi ý, câu kiểm lệch):
``tests/unit/test_vn_school_thcs_noi_bo.py``. Lược đồ sau nâng cấp == ``create_all``:
``tests/integration/test_thcs_danh_muc_migration.py``.

Biến thể kiểm ngược (CLAUDE.md chung §3) ghi ở biên bản ``logs-P5/cong-bo-ket-qua/gd2/l3/thcs/``.
"""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.schema import CreateIndex, CreateSequence

from app.models import vn_school as m
from app.models.vn_school_internal_code import (
    INTERNAL_CODE_LEVELS,
    INTERNAL_CODE_SQL_PREDICATE,
    NO_MOET_CODE_LEVELS,
    format_internal_school_code,
    internal_code_sql,
    is_internal_school_code,
    not_internal_code_sql,
)
from app.scripts.import_moet_schools_3_provinces import build_rows
from app.scripts.rebuild_school_kv_from_xls import source_rows_for_apply

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
TEP_MIGRATION = GOC / "alembic" / "versions" / "thcsnb20261122_vn_school_internal_code.py"


def _migration():
    spec = importlib.util.spec_from_file_location("thcsnb20261122", TEP_MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pg(stmt) -> str:
    """Biên dịch như ``create_all`` của CSDL test (asyncpg, paramstyle ``numeric_dollar`` — ``%`` KHÔNG bị nhân đôi)."""
    return str(stmt.compile(dialect=asyncpg.dialect())).strip()


# ---------- mã nội bộ: khuôn + vùng dành riêng ----------


@pytest.mark.parametrize(
    "so,ma",
    [(1, "NB000001"), (123, "NB000123"), (999999, "NB999999")],
)
def test_ma_noi_bo_dung_khuon_NB_sau_so(so, ma):
    assert format_internal_school_code(so) == ma
    assert len(ma) <= 10  # cột moet_school_code VARCHAR(10)


@pytest.mark.parametrize("so", [0, -1, 1_000_000, True, "1", 1.0])
def test_ma_noi_bo_ngoai_khoang_thi_tu_choi_khong_cat_khong_quay_vong(so):
    with pytest.raises(ValueError):
        format_internal_school_code(so)


@pytest.mark.parametrize(
    "ma,la_noi_bo",
    [
        ("NB000001", True),
        ("nb000001", True),  # mọi kiểu chữ
        (" NB12", True),  # khoảng trắng đầu
        ("Nb", True),
        ("NB", True),
        ("040123", False),
        ("N B000001", False),
        ("XNB000001", False),
        ("", False),
        (None, False),
        (123, False),
    ],
)
def test_vung_danh_rieng_NB(ma, la_noi_bo):
    assert is_internal_school_code(ma) is la_noi_bo


def test_cap_duoc_cap_ma_noi_bo():
    assert INTERNAL_CODE_LEVELS == frozenset({"THCS", "THCS_THPT"})
    # THCS không có mã Bộ; liên cấp CÓ THỂ có mã Bộ (cấp THPT nằm trong danh mục Bộ).
    assert NO_MOET_CODE_LEVELS == frozenset({"THCS"})


def test_vi_tu_sql_noi_bo_va_phu_dinh_dung_mot_bieu_thuc():
    cot = m.VnSchool.__table__.c.moet_school_code
    co = _pg(internal_code_sql(cot))
    khong = _pg(not_internal_code_sql(cot))
    assert "upper(btrim(vn_school.moet_school_code))" in co and "LIKE" in co
    assert khong.startswith("NOT (") or "NOT LIKE" in khong
    assert INTERNAL_CODE_SQL_PREDICATE.format(col="moet_school_code") == "upper(btrim(moet_school_code)) LIKE 'NB%'"


# ---------- DDL: model == migration ----------


def test_migration_noi_dung_dung_cho_revision():
    mig = _migration()
    assert (mig.revision, mig.down_revision) == ("thcsnb20261122", "gd2f20261119")


def test_chuoi_check_va_chi_muc_model_bang_migration():
    mig = _migration()
    assert m.CK_VN_SCHOOL_INTERNAL_CODE_FORMAT_SQL == mig.SQL_CK_INTERNAL_CODE
    assert m.UQ_VN_SCHOOL_INTERNAL_CODE_WHERE_SQL == mig.SQL_UQ_INTERNAL_CODE_WHERE
    # CHECK + chỉ mục có MẶT trong bảng của model (create_all của CSDL test dựng từ đây).
    ten_rb = {c.name for c in m.VnSchool.__table__.constraints if c.name}
    assert "ck_vn_school_internal_code_format" in ten_rb
    chi_muc = {i.name: i for i in m.VnSchool.__table__.indexes}
    assert chi_muc["uq_vn_school_internal_code"].unique is True
    cau = _pg(CreateIndex(chi_muc["uq_vn_school_internal_code"]))
    assert cau == (
        "CREATE UNIQUE INDEX uq_vn_school_internal_code ON vn_school (moet_school_code) "
        "WHERE " + mig.SQL_UQ_INTERNAL_CODE_WHERE
    ), cau
    assert ("CREATE UNIQUE INDEX uq_vn_school_internal_code ON vn_school (moet_school_code) WHERE "
            + mig.SQL_UQ_INTERNAL_CODE_WHERE) in mig.UPGRADE_SQL


def test_sequence_model_bang_migration():
    mig = _migration()
    seq = m.VN_SCHOOL_INTERNAL_CODE_SEQ
    assert seq.metadata is m.Base.metadata  # create_all dựng sequence cho CSDL test
    tu_model = set(_pg(CreateSequence(seq)).split())
    tu_migration = set(mig.SQL_CREATE_SEQUENCE.split())
    assert tu_model == tu_migration, (tu_model ^ tu_migration)
    assert mig.SQL_CREATE_SEQUENCE in mig.UPGRADE_SQL
    assert "NO CYCLE" in mig.SQL_CREATE_SEQUENCE and "MAXVALUE 999999" in mig.SQL_CREATE_SEQUENCE


def test_ha_cap_go_dung_ba_doi_tuong_khong_xoa_dong():
    mig = _migration()
    ha = mig.DOWNGRADE_SQL
    assert "DROP INDEX uq_vn_school_internal_code" in ha
    assert "DROP CONSTRAINT ck_vn_school_internal_code_format" in ha
    assert "DROP SEQUENCE vn_school_internal_code_seq" in ha
    assert "DELETE" not in ha.upper().replace("ON DELETE", "")
    # Nâng lại sau hạ cấp: sequence nối tiếp số lớn nhất đã cấp (không cấp trùng).
    assert "setval('vn_school_internal_code_seq', v_max, true)" in mig.UPGRADE_SQL


# ---------- bộ nạp danh mục Bộ: lớp lọc ở dữ liệu nguồn ----------


def _df_moet(*ma_truong):
    return pd.DataFrame(
        [
            [i, 40, "Đắk Lắk", 1, "TP Buôn Ma Thuột", ma, f"THPT Thử {ma}", "Địa chỉ", "KV1", None]
            for i, ma in enumerate(ma_truong, start=1)
        ],
        columns=[
            "stt", "ma_tinh", "ten_tinh", "ma_huyen", "ten_huyen",
            "ma_truong", "ten_truong", "dia_chi", "khu_vuc", "dtnt",
        ],
    )


def test_nap_moet_bo_qua_dong_nguon_mang_ma_NB():
    rows = build_rows(_df_moet("002", "NB000001", "nb000002", "090"), ["Đắk Lắk"])
    assert [r["moet_school_code"] for r in rows] == ["002", "090"]


def test_nap_lai_xls_bo_qua_dong_nguon_mang_ma_NB():
    nguon = [
        {"gso": "66", "moet_code": "66006", "name": "A"},
        {"gso": "66", "moet_code": "NB000001", "name": "B"},  # mã nội bộ nguyên dạng
        {"gso": "66", "moet_code": "66NB000003"[:8], "name": "C"},  # [2:] = 'NB0000'
        {"gso": "52", "moet_code": "52001", "name": "D"},
    ]
    ra = source_rows_for_apply(nguon, {"66", "52"})
    assert [r["name"] for r in ra] == ["A", "D"]
