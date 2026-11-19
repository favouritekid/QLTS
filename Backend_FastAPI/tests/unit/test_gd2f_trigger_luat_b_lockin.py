# -*- coding: utf-8 -*-
"""GĐ2-F1 luật B — hai bản DDL trigger học vụ (bản ``create_all()`` :data:`admission_quota_ddl.STATEMENTS_F1` và bản thật ở
migration ``gd2f20261119``) không trôi khỏi nhau; ``downgrade`` trả ĐÚNG hàm + trigger GĐ2-A; chuỗi Alembic nối đúng chỗ.
Khuôn ``test_gd2a_quota_ddl_lockin.py``: so từng câu sau khi chuẩn hoá khoảng trắng."""
import importlib.util
import re
from pathlib import Path

import pytest

from app.models import admission_quota_ddl as ddl

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
_MIGRATION = GOC / "alembic" / "versions" / "gd2f20261119_luat_b_bang_khoa.py"


def _chuan_hoa(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _mig():
    spec = importlib.util.spec_from_file_location("_gd2f_mig", _MIGRATION)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ban_create_all_va_migration_nang_cap_khop_tung_cau():
    assert [_chuan_hoa(c) for c in ddl.STATEMENTS_F1] == [_chuan_hoa(c) for c in _mig().UPGRADE_STATEMENTS]


def test_create_all_dung_gd2a_roi_f1_trang_thai_cuoi_la_head():
    assert ddl.STATEMENTS == (*ddl.STATEMENTS_GD2A, *ddl.STATEMENTS_F1)


def test_ha_cap_tra_dung_ham_va_trigger_gd2a():
    """``downgrade`` = hàm GĐ2-A nguyên văn + trigger GĐ2-A (chỉ khác ``CREATE`` → ``CREATE OR REPLACE`` vì tên đã có)."""
    m = _mig()
    trigger_gd2a = re.sub(r"^\s*CREATE\s+TRIGGER\b", "CREATE OR REPLACE TRIGGER", ddl.SQL_TRIGGERS[0], count=1, flags=re.M)
    assert [_chuan_hoa(c) for c in m.DOWNGRADE_STATEMENTS] == [
        _chuan_hoa(ddl.SQL_FN_ACADEMIC_INFO_QUOTA),
        _chuan_hoa(trigger_gd2a),
    ]
    assert "trg_chan_sua_chi_tieu_nganh_khi_bang_khoa" in ddl.SQL_TRIGGERS[0]


def test_trigger_f1_theo_doi_insert_va_nam_hoc():
    t = _chuan_hoa(ddl.SQL_TRIGGER_ACADEMIC_INFO_F1)
    assert "BEFORE INSERT OR UPDATE OF annual_admission_quota, academic_year ON offering_academic_info" in t


def test_khong_co_ky_tu_lam_hong_ddl_hoac_text():
    m = _mig()
    for cau in (*ddl.STATEMENTS_F1, *m.UPGRADE_STATEMENTS, *m.DOWNGRADE_STATEMENTS):
        assert "%" not in cau and "::" not in cau


def test_migration_noi_ngay_sau_gd2a():
    m = _mig()
    assert (m.revision, m.down_revision) == ("gd2f20261119", "gd2a20261118")
