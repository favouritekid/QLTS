# -*- coding: utf-8 -*-
"""K-2 — hai bản DDL trigger khoá cấu hình (bản cho ``create_all()`` ở ``app/models/council_config_lock_ddl.py`` và
bản thật ở migration ``hdts20261111``) không được trôi khỏi nhau. Khuôn ``test_duplicate_guard_ddl_lockin.py``: so
TỪNG câu sau khi chuẩn hoá khoảng trắng; không kiểm SQL đúng sai — chỉ kiểm hai bên còn là một."""
import re
from pathlib import Path

import pytest

from app.models import council_config_lock_ddl as ddl

pytestmark = pytest.mark.unit

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "hdts20261111_khoa_cau_hinh_da_dung.py"
)


def _chuan_hoa(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_hai_ban_ddl_khong_troi_khoi_nhau():
    van = _chuan_hoa(_MIGRATION.read_text(encoding="utf-8"))
    for cau in (*ddl.CAC_CAU_LENH, ddl.SQL_DEM_LECH):
        chuan = _chuan_hoa(cau)
        assert chuan, "câu lệnh rỗng"
        assert chuan in van, "câu có trong bản create_all nhưng KHÔNG có trong migration:\n\n%s" % cau


def test_sqlstate_trigger_khop_hang():
    for cau in (ddl.SQL_FN_HOC_VU, ddl.SQL_FN_DUONG_XET):
        assert "ERRCODE = '%s'" % ddl.SQLSTATE_CAU_HINH_DA_DUNG in cau


def test_khong_co_ky_tu_lam_hong_ddl_hoac_text():
    # DDL() nội suy bằng toán tử % ; text() của migration hiểu :tên là tham số
    for cau in (*ddl.CAC_CAU_LENH, ddl.SQL_DEM_LECH):
        assert "%" not in cau and "::" not in cau
