# -*- coding: utf-8 -*-
"""GĐ2-C C1 — khoá văn bản DDL + các luật thuần của quyền "Thư ký Hội đồng" (không CSDL).

- Bản ``create_all()`` (``app/models/admission_review_secretary.py`` + ``admission_review_secretary_ddl.py``) và bản thật ở
  migration ``gd2c20261122`` không được trôi khỏi nhau (khuôn ``test_gd2a_quota_ddl_lockin.py`` + GĐ2-B ``test_gd2b_ddl_lockin``):
  so từng câu hàm / trigger, tên + chữ CHECK, chỉ mục; lược đồ THẬT so ở ``tests/integration/test_gd2c_c1_migration.py``.
- Owner C1 22-11 "không hết hạn" ⇒ bảng KHÔNG có cột hết hạn.
- Chuỗi Alembic một đầu; SQLSTATE mới chỉ dùng đúng tệp; cờ hạ cấp mang nghĩa CHO PHÉP.
- Sổ K4 có đủ ba cột người dùng (``BLOCK_ACTOR``) — sổ khớp ``pg_constraint`` kiểm ở ``tests/api/test_gd1b_xoa_tai_khoan.py``.
- Vị từ tự thu hồi (bảng chân trị) + cổng ``deps.require_review_secretary`` khai ĐÚNG hai dependency (xác thực + phiên chung).

Mỗi ca kiểm MỘT bất biến.
"""
import importlib.util
import inspect
import re
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, Index

from app.models import admission_review_secretary as m
from app.models import admission_review_secretary_ddl as ddl

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
_MIGRATION = GOC / "alembic" / "versions" / "gd2c20261122_review_secretary_grant.py"
BANG = "admission_review_secretary_grant"


def _chuan_hoa(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _mig():
    spec = importlib.util.spec_from_file_location("_gd2c_c1_mig", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rang_buoc_model():
    t = m.AdmissionReviewSecretaryGrant.__table__
    ra = {c.name: c for c in t.constraints if c.name}
    ra.update({i.name: i for i in t.indexes})
    return ra


def _check_trong_migration(nguon: str, ten: str) -> str:
    dau = "CONSTRAINT %s CHECK (" % ten
    i = nguon.index(dau) + len(dau)
    sau, j = 1, i
    while sau:
        if nguon[j] == "(":
            sau += 1
        elif nguon[j] == ")":
            sau -= 1
        j += 1
    return nguon[i : j - 1]


# ── hàm + trigger ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_ham_va_trigger_create_all_khop_migration_tung_cau():
    assert [_chuan_hoa(c) for c in ddl.STATEMENTS] == [_chuan_hoa(c) for c in _mig().STATEMENTS]


def test_danh_sach_ham_ha_cap_khop_cau_create_function():
    tao = []
    for cau in ddl.STATEMENTS:
        r = re.search(r"CREATE OR REPLACE FUNCTION (\w+)\(([^)]*)\)", cau)
        if r:
            tao.append("%s(%s)" % (r.group(1), r.group(2).strip()))
    assert tuple(tao) == ddl.FUNCTION_SIGNATURES == _mig().FUNCTION_SIGNATURES


def test_trigger_canh_ca_sua_lan_xoa():
    """Một trigger BEFORE UPDATE OR DELETE trên đúng bảng mới — thiếu DELETE thì xoá lọt, thiếu UPDATE thì sửa lọt."""
    assert "BEFORE UPDATE OR DELETE ON %s" % BANG in _chuan_hoa(ddl.SQL_TRIGGER_REVOKE_ONLY)


def test_khong_co_ky_tu_lam_hong_ddl_hoac_text():
    for cau in (*ddl.STATEMENTS, *_mig().STATEMENTS):
        assert "%" not in cau and "::" not in cau


def test_sqlstate_trigger_khop_hang():
    assert ddl.SQLSTATE_SECRETARY_GRANT_IMMUTABLE == "QLC20"
    assert ddl.SQL_FN_REVOKE_ONLY.count("ERRCODE = 'QLC20'") == 2


@pytest.mark.parametrize(
    "ma, duoc_phep",
    [
        ("QLC20", {"app/models/admission_review_secretary_ddl.py", "alembic/versions/gd2c20261122_review_secretary_grant.py"}),
        ("QLC21", {"alembic/versions/gd2c20261122_review_secretary_grant.py"}),
    ],
)
def test_sqlstate_moi_chi_dung_o_tep_gd2c_c1(ma, duoc_phep):
    gap = set()
    for thu_muc in ("app", "alembic"):
        for p in (GOC / thu_muc).rglob("*.py"):
            if re.search(r"['\"]%s['\"]" % ma, p.read_text(encoding="utf-8")):
                gap.add(p.relative_to(GOC).as_posix())
    assert gap == duoc_phep


# ── bảng ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_khong_co_cot_het_han():
    """Owner C1 22-11: "Không hết hạn, giữ tới khi Admin thu hồi" — model và migration đều không có cột hạn."""
    cot = set(m.AdmissionReviewSecretaryGrant.__table__.columns.keys())
    assert cot == {
        "id", "user_id", "granted_by_user_id", "granted_at", "reason", "revoked_at", "revoked_by_user_id", "revoke_reason",
    }
    assert "expire" not in _mig().CREATE_TABLES[0]


def test_ten_rang_buoc_va_chi_muc_model_bang_migration():
    nguon = _MIGRATION.read_text(encoding="utf-8")
    trong_mig = set(re.findall(r"CONSTRAINT ((?:ck|uq|fk)_\w+)", nguon))
    trong_mig |= set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+) ON", nguon))
    assert trong_mig == set(_rang_buoc_model())


def test_chu_check_model_bang_migration():
    nguon = _MIGRATION.read_text(encoding="utf-8")
    checks = {ten: c for ten, c in _rang_buoc_model().items() if isinstance(c, CheckConstraint)}
    assert set(checks) == {
        "ck_review_secretary_grant_reason",
        "ck_review_secretary_grant_revoked_triple",
        "ck_review_secretary_grant_revoke_reason",
    }
    for ten, c in checks.items():
        assert _chuan_hoa(_check_trong_migration(nguon, ten)) == _chuan_hoa(str(c.sqltext)), ten


def test_chi_muc_mot_phan_mot_quyen_con_hieu_luc_moi_nguoi():
    idx = _rang_buoc_model()["uq_review_secretary_grant_active_user"]
    assert isinstance(idx, Index) and idx.unique and [c.name for c in idx.columns] == ["user_id"]
    assert str(idx.dialect_options["postgresql"]["where"]) == m.ACTIVE_GRANT_WHERE == "revoked_at IS NULL"
    assert any(
        _chuan_hoa(c) == "CREATE UNIQUE INDEX uq_review_secretary_grant_active_user ON %s (user_id) WHERE revoked_at IS NULL"
        % BANG
        for c in _mig().CREATE_INDEXES
    )


def test_moi_khoa_ngoai_toi_user_la_restrict_o_ca_hai_ban():
    cot_user = sorted(
        (fk.parent.name, fk.ondelete) for fk in m.AdmissionReviewSecretaryGrant.__table__.foreign_keys
        if fk.column.table.name == "user"
    )
    assert cot_user == [("granted_by_user_id", "RESTRICT"), ("revoked_by_user_id", "RESTRICT"), ("user_id", "RESTRICT")]
    nguon = _chuan_hoa(_mig().CREATE_TABLES[0])
    for cot, _ in cot_user:
        assert 'FOREIGN KEY(%s) REFERENCES "user" (id) ON DELETE RESTRICT' % cot in nguon, cot


# ── chuỗi Alembic + hạ cấp ─────────────────────────────────────────────────────────────────────────────────────────────
def test_migration_noi_sau_head_cua_nen():
    mod = _mig()
    assert (mod.revision, mod.down_revision) == ("gd2c20261122", "gd2b20261121")


def test_mot_head_alembic():
    """Đúng MỘT head (đọc cả ``down_revision`` dạng bộ nhiều dòng). Gộp GĐ2-B mà quên nối lại ⇒ hai head ⇒ ĐỎ."""
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
    assert revs - downs == {"gd2c20261122"}


def test_co_ha_cap_mang_nghia_cho_phep_dung_chu_1():
    mod = _mig()
    nguon = inspect.getsource(mod.downgrade)
    assert mod.DOWNGRADE_FLAG == "GD2C_C1_DOWNGRADE_DROP_DATA_ENABLED"
    assert "os.environ.get(DOWNGRADE_FLAG) == \"1\"" in nguon
    assert "IS DISTINCT FROM '1'" in mod.DOWNGRADE_SQL and "ERRCODE = 'QLC21'" in mod.DOWNGRADE_SQL


# ── sổ K4 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_so_k4_co_ba_cot_nguoi_dung_cua_bang_moi_la_block_actor():
    from app.services.user_deletion_policy import USER_REFERENCES, UserRefGroup

    hang = {(r.table, r.column): r.group for r in USER_REFERENCES if r.table == BANG}
    assert hang == {
        (BANG, "granted_by_user_id"): UserRefGroup.BLOCK_ACTOR,
        (BANG, "revoked_by_user_id"): UserRefGroup.BLOCK_ACTOR,
        (BANG, "user_id"): UserRefGroup.BLOCK_ACTOR,
    }


# ── vị từ tự thu hồi (bảng chân trị) ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "cu_vai, cu_tt, moi_vai, moi_tt, mong_doi",
    [
        ("officer", "active", None, "inactive", "Tự thu hồi: tài khoản bị khoá"),
        ("manager", "active", None, "banned", "Tự thu hồi: tài khoản bị khoá"),
        ("officer", "active", None, "pending", "Tự thu hồi: tài khoản bị khoá"),
        ("officer", "active", "accountant", None, "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Kế toán"),
        ("manager", "active", "admin", None, "Tự thu hồi: tài khoản đổi vai từ Quản lý sang Admin"),
        ("manager", "active", "user", None, "Tự thu hồi: tài khoản đổi vai từ Quản lý sang Người dùng"),
        (
            "officer", "active", "collaborator", "inactive",
            "Tự thu hồi: tài khoản bị khoá; Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Cộng tác viên",
        ),
        # Giữ quyền: đổi qua lại giữa hai vai được gán; không đổi gì; mở khoá; đổi trạng thái khi vốn không hoạt động.
        ("manager", "active", "officer", None, None),
        ("officer", "active", "manager", None, None),
        ("officer", "active", "officer", "active", None),
        ("officer", "inactive", None, "active", None),
        ("officer", "inactive", None, "banned", None),
        ("officer", "active", None, None, None),
        # Vai cũ không được gán (không thể có quyền) — không sinh câu.
        ("accountant", "active", "user", None, None),
    ],
)
def test_vi_tu_tu_thu_hoi(cu_vai, cu_tt, moi_vai, moi_tt, mong_doi):
    from app.services.review_secretary_service import auto_revoke_reason

    assert auto_revoke_reason(old_role=cu_vai, old_status=cu_tt, new_role=moi_vai, new_status=moi_tt) == mong_doi


def test_vai_duoc_gan_la_quan_ly_va_can_bo_admin_luon_la_thu_ky():
    """Thiết kế GĐ2-C §4: Ban thư ký được GÁN = ``manager``, ``officer``. Owner 22-11 câu 1: Admin LUÔN là Thư ký, không qua bảng
    quyền (và không được gán — hai tập rời nhau)."""
    from app.services.review_secretary_service import ALWAYS_SECRETARY_ROLE, SECRETARY_ELIGIBLE_ROLES

    assert SECRETARY_ELIGIBLE_ROLES == frozenset({"manager", "officer"})
    assert ALWAYS_SECRETARY_ROLE == "admin" and ALWAYS_SECRETARY_ROLE not in SECRETARY_ELIGIBLE_ROLES


# ── cổng ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_cong_thu_ky_khai_xac_thuc_casbin_va_phien_chung():
    """``require_review_secretary`` nhận người dùng qua ``check_permission`` (Casbin + xác thực) và phiên qua ĐÚNG
    ``database.get_db`` — callable ấy là khoá dùng lại dependency của FastAPI, nên route khai ``Depends(database.get_db)``
    nhận CÙNG phiên (cùng giao dịch) mà cổng đã khoá quyền ``FOR SHARE``. Đo hành vi: ``test_gd2c_c1_thu_ky_cong.py``."""
    from app import database
    from app.core import deps

    tham_so = inspect.signature(deps.require_review_secretary).parameters
    assert tham_so["current_user"].default.dependency is deps.check_permission
    assert tham_so["db"].default.dependency is database.get_db
