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


# ── Nợ N1 (rà hợp nhất 23-11, mục I1): ba route ghi bảng chỉ tiêu kiểm phản hồi TRƯỚC commit ─────────────────────────────
@pytest.mark.parametrize("ten", ["put_quota_table", "lock_quota_table", "unlock_quota_table"])
def test_route_ghi_bang_chi_tieu_kiem_phan_hoi_truoc_commit(ten):
    """Nợ N1 (khuôn C2 ``0f727a0a``): ba route ghi bảng chỉ tiêu (PUT / khoá / mở khoá) gọi ``response_checked_before_commit`` —
    hàm của chính ``app.routers.admission_review`` (MỘT helper với GĐ2-B) — với ĐÚNG ``response_model`` của route, một lần, TRƯỚC
    ``db.commit()``. Hành vi (thân lệch ⇒ 500 VÀ CSDL không đổi):
    ``tests/api/test_gd2a_bang_chi_tieu_api.py::test_n1_phan_hoi_lech_schema_500_khong_ghi_gi``."""
    import ast
    import inspect

    from fastapi.routing import APIRoute

    from app.main import fastapi_app
    from app.routers import admission_review as r

    ham = getattr(r, ten)
    goi = [n for n in ast.walk(ast.parse(inspect.getsource(ham))) if isinstance(n, ast.Call)]
    kiem = [n for n in goi if isinstance(n.func, ast.Name) and n.func.id == "response_checked_before_commit"]
    commit = [n for n in goi if isinstance(n.func, ast.Attribute) and n.func.attr == "commit"]
    assert len(kiem) == 1 and len(commit) == 1, (ten, len(kiem), len(commit))
    assert (kiem[0].lineno, kiem[0].col_offset) < (commit[0].lineno, commit[0].col_offset), ten
    route = next(x for x in fastapi_app.routes if isinstance(x, APIRoute) and x.endpoint is ham)
    assert isinstance(kiem[0].args[0], ast.Name) and kiem[0].args[0].id == route.response_model.__name__, ten


def test_helper_kiem_phan_hoi_truoc_commit_mot_dinh_nghia_trong_app():
    """CLAUDE.md §7 (một nguồn): ``response_checked_before_commit`` được ĐỊNH NGHĨA đúng một lần trong ``app/`` — ở
    ``app/routers/admission_review.py`` (bản trùng byte GĐ2-B L4 ``53b3b6ec``; route khác IMPORT từ đó). Gộp GĐ2-B mà giữ cả hai
    bản (hoặc chép helper sang router khác) ⇒ đỏ."""
    import ast

    app_dir = GOC / "app"
    noi = sorted(
        "%s:%d" % (p.relative_to(app_dir).as_posix(), n.lineno)
        for p in app_dir.rglob("*.py")
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "response_checked_before_commit"
    )
    assert [x.split(":")[0] for x in noi] == ["routers/admission_review.py"], noi
