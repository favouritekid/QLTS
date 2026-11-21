# -*- coding: utf-8 -*-
"""GĐ2-A — hai bản DDL trigger bảng chỉ tiêu (bản cho ``create_all()`` ở ``app/models/admission_quota_ddl.py`` và bản thật ở
migration ``gd2a20261118``) không được trôi khỏi nhau. Khuôn ``test_council_config_lock_ddl_lockin.py``: so TỪNG câu sau
khi chuẩn hoá khoảng trắng. Thêm: sổ phân loại khoá ngoại tới ``user`` (K4) có cột mới; vùng khoá năm đã đăng ký."""
import importlib.util
import re
from pathlib import Path

import pytest

from app.models import admission_quota_ddl as ddl

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
_MIGRATION = GOC / "alembic" / "versions" / "gd2a20261118_quota_table.py"


def _chuan_hoa(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _mig():
    spec = importlib.util.spec_from_file_location("_gd2a_mig", _MIGRATION)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_hai_ban_ddl_khong_troi_khoi_nhau():
    """Phần GĐ2-A của bản ``create_all()`` (:data:`ddl.STATEMENTS_GD2A`) == migration ``gd2a20261118``. Phần F1 (luật B) thay
    hàm + trigger học vụ ở migration riêng — khoá ở ``tests/unit/test_gd2f_trigger_luat_b_lockin.py``."""
    m = _mig()
    assert [_chuan_hoa(c) for c in ddl.STATEMENTS_GD2A] == [_chuan_hoa(c) for c in m.STATEMENTS]
    assert ddl.STATEMENTS[: len(ddl.STATEMENTS_GD2A)] == ddl.STATEMENTS_GD2A


def test_sqlstate_trigger_khop_hang():
    for cau in (ddl.SQL_FN_ASSERT_UNLOCKED, ddl.SQL_FN_TABLE_DELETE):
        assert "ERRCODE = '%s'" % ddl.SQLSTATE_QUOTA_TABLE_LOCKED in cau


def test_khong_co_ky_tu_lam_hong_ddl_hoac_text():
    # DDL() nội suy bằng toán tử % ; text() của migration hiểu :tên là tham số
    for cau in ddl.STATEMENTS:
        assert "%" not in cau and "::" not in cau


def test_migration_noi_dung_head_gd1b():
    m = _mig()
    assert (m.revision, m.down_revision) == ("gd2a20261118", "gd1b20261117")


def test_mot_head_alembic():
    """Sau GĐ2-A Alembic có ĐÚNG một head (nhánh gộp đọc cả ``down_revision`` dạng bộ nhiều dòng) và ``gd2a20261118`` nằm
    trên chuỗi tới head (GĐ2-F1 luật B nối ``gd2f20261119`` ngay sau — khoá ở ``test_gd2f_trigger_luat_b_lockin.py``; không
    ghim head = revision cuối, như review max PR #724 R15)."""
    revs, downs = set(), set()
    for p in (GOC / "alembic" / "versions").glob("*.py"):
        s = p.read_text(encoding="utf-8")
        r = re.search(r"^revision\s*(?::[^=]+)?=\s*['\"]([^'\"]+)['\"]", s, re.M)
        if not r:
            continue
        revs.add(r.group(1))
        d = re.search(r"^down_revision\s*(?::[^=]+)?=\s*(\([^)]*\)|[^\n]+)", s, re.M | re.S)
        if d:
            downs.update(re.findall(r"['\"]([^'\"]+)['\"]", d.group(1)))
    heads = revs - downs
    assert len(heads) == 1, heads
    assert "gd2a20261118" in revs and ("gd2a20261118" in heads or "gd2a20261118" in downs)


def test_so_phan_loai_khoa_ngoai_co_nguoi_khoa_bang_chi_tieu():
    from app.services.user_deletion_policy import USER_REFERENCES, UserRefGroup

    hang = {(r.table, r.column): r.group for r in USER_REFERENCES}
    assert hang[("admission_quota_table", "locked_by_user_id")] is UserRefGroup.BLOCK_ACTOR


def test_vung_khoa_nam_da_dang_ky():
    from app.core import advisory_lock_keys as keys

    assert keys.REVIEW_YEAR_NS in keys.REGISTERED_NAMESPACES
