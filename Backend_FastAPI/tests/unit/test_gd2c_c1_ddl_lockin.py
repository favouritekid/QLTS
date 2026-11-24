# -*- coding: utf-8 -*-
"""GĐ2-C C1 — khoá văn bản DDL + các luật thuần của quyền "Thư ký Hội đồng" (không CSDL).

- Bản ``create_all()`` (``app/models/admission_review_secretary.py`` + ``admission_review_secretary_ddl.py``) và bản thật ở
  migration ``gd2c20261122`` không được trôi khỏi nhau (khuôn ``test_gd2a_quota_ddl_lockin.py`` + GĐ2-B ``test_gd2b_ddl_lockin``):
  so từng câu hàm / trigger, tên + chữ CHECK, chỉ mục; lược đồ THẬT so ở ``tests/integration/test_gd2c_c1_migration.py``.
- Owner C1 22-11 "không hết hạn" ⇒ bảng KHÔNG có cột hết hạn.
- Chuỗi Alembic một đầu; SQLSTATE mới chỉ dùng đúng tệp; cờ hạ cấp mang nghĩa CHO PHÉP.
- Sổ K4 có đủ ba cột người dùng (``BLOCK_ACTOR``) — sổ khớp ``pg_constraint`` kiểm ở ``tests/api/test_gd1b_xoa_tai_khoan.py``.
- Vị từ tự thu hồi (bảng chân trị) + cổng ``deps.require_review_secretary`` khai ĐÚNG hai dependency (xác thực + phiên chung).
- Gộp PR-B ``5effed10`` (lượt 8, owner 23-11): hàm khoá dòng quyền ``FOR UPDATE`` của đường TỰ THU HỒI (cả hai bảng quyền)
  chỉ được gọi từ đúng chỗ đã biết, và trong ``revoke_grants_on_account_change`` phép chặn 409 lưu gộp đứng TRƯỚC mọi lời gọi
  ấy (hành vi + hai phiên: ``tests/api/test_gd2c_c1_thu_ky_chan_gop.py``).

Mỗi ca kiểm MỘT bất biến.
"""
import ast
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
    """Đúng MỘT head (đọc cả ``down_revision`` dạng bộ nhiều dòng). Gộp GĐ2-B mà quên nối lại ⇒ hai head ⇒ ĐỎ.
    ``gd2c20261122`` là head HOẶC tổ tiên của head (không ghim head = revision cuối — khuôn GĐ2-B, review max PR #724 R15): từ
    GĐ2-C C2 (22-11) migration ``gd2cs20261122`` nối sau."""
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
    assert "gd2c20261122" in revs and ("gd2c20261122" in heads or "gd2c20261122" in downs)


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


# ── chặn lưu gộp PR-B lượt 8 đứng TRƯỚC mọi khoá dòng quyền của tự thu hồi (gộp PR-B 5effed10, 23-11) ─────────────────────
APP = GOC / "app"
HELPER_TU_THU_HOI = ("services/document_cross_review_service.py", "revoke_grants_on_account_change")
#: Hàm khoá dòng quyền ``FOR UPDATE`` của đường TỰ THU HỒI → nơi DUY NHẤT được gọi. Hai repository cùng tên hàm
#: (``document_bulk_repository`` cho quyền duyệt chéo, ``review_secretary_repository`` cho quyền Thư ký) — quét theo TÊN.
#: Đường mới gọi thẳng (không qua ``HELPER_TU_THU_HOI``) thì không đi qua phép chặn 409 ⇒ ĐỎ ⇒ người viết phải quyết.
GOI_KHOA_QUYEN_TU_THU_HOI = {
    "lock_active_grants_of_user_for_update": {
        HELPER_TU_THU_HOI,
        ("services/review_secretary_service.py", "revoke_on_account_change"),
    },
    "revoke_on_account_change": {HELPER_TU_THU_HOI},
}


def _ten_goi(nut) -> str:
    return nut.id if isinstance(nut, ast.Name) else nut.attr if isinstance(nut, ast.Attribute) else ""


def _ham_trong_app():
    for p in sorted(APP.rglob("*.py")):
        rel = p.relative_to(APP).as_posix()
        for f in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield (rel, f.name), f


def test_ham_khoa_dong_quyen_cua_tu_thu_hoi_chi_duoc_goi_tu_cho_da_biet():
    thay = {ten: set() for ten in GOI_KHOA_QUYEN_TU_THU_HOI}
    for khoa, f in _ham_trong_app():
        for n in ast.walk(f):
            if isinstance(n, ast.Call) and _ten_goi(n.func) in thay:
                thay[_ten_goi(n.func)].add(khoa)
    assert thay == GOI_KHOA_QUYEN_TU_THU_HOI


def test_chan_gop_409_dung_truoc_moi_khoa_dong_quyen_trong_helper_tu_thu_hoi():
    """``if target_locked_for_update: raise CombinedKeyChangeAndRevokeError()`` ở THÂN NGOÀI CÙNG của helper (không lồng trong
    nhánh của riêng một lý do) và đứng TRƯỚC (số dòng) mọi lời gọi khoá dòng quyền — duyệt chéo lẫn Thư ký. Ném SAU khoá (hoặc
    giữa hai khoá) thì rollback vẫn xoá mọi ghi chép nên ca HTTP "409 không ghi gì" vẫn xanh; chỉ ca hai phiên và phép kiểm
    này thấy được thứ tự. Giới hạn: không kiểm điều kiện "có lý do thu hồi" (đo bằng hành vi ở ca Quản lý của
    ``test_gd2c_c1_thu_ky_chan_gop.py``)."""
    f = dict(_ham_trong_app())[HELPER_TU_THU_HOI]
    chan = [
        n for n in f.body
        if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "target_locked_for_update"
        and any(
            isinstance(s, ast.Raise) and isinstance(s.exc, ast.Call)
            and _ten_goi(s.exc.func) == "CombinedKeyChangeAndRevokeError"
            for s in n.body
        )
    ]
    khoa = sorted(
        n.lineno for n in ast.walk(f) if isinstance(n, ast.Call) and _ten_goi(n.func) in GOI_KHOA_QUYEN_TU_THU_HOI
    )
    assert len(chan) == 1 and len(khoa) == 2, (len(chan), khoa)
    assert chan[0].lineno < khoa[0], (chan[0].lineno, khoa)


#: Hàm giữ dòng ``user`` ở mức CHẶT (``FOR UPDATE``): gọi ``lock_user_for_update`` hoặc ``lock_users_in_id_order`` có
#: ``key_update_ids=`` / ``delete_targets=``. Luật PR-B lượt 8 (``document_bulk_repository.lock_user_key_share``): không hàm nào
#: ở đây gọi THẲNG hàm khoá dòng quyền (``lock_*grant*`` — duyệt chéo lẫn Thư ký); tự thu hồi chỉ qua ``HELPER_TU_THU_HOI`` với
#: ``target_locked_for_update`` (sổ PR-B ``SO_GHI_COT_KHOA`` ở ``test_gd1b_cheo_duong_doi_vai.py``). Hàm mới giữ ``FOR UPDATE``
#: ⇒ ĐỎ ⇒ người viết quyết. Giới hạn: không thấy ``with_for_update()`` viết tay trên ``User`` (vd đăng nhập) — đăng nhập không
#: chạm dòng quyền.
GIU_NGUOI_FOR_UPDATE = {
    ("services/user_deletion_policy.py", "lock_users_in_id_order"),  # vòng khoá chung, id tăng
    ("services/user_deletion_policy.py", "assert_user_deletable"),  # K4: chỉ ĐỌC quyền (409 BLOCK_ACTOR), không khoá
    ("services/user_service.py", "update_user"),  # PUT đổi email: chặn gộp nằm trong HELPER_TU_THU_HOI
}


def test_ham_giu_nguoi_for_update_khong_goi_thang_ham_khoa_dong_quyen():
    giu, sai = set(), []
    for khoa, f in _ham_trong_app():
        goi = [n for n in ast.walk(f) if isinstance(n, ast.Call)]
        if any(
            _ten_goi(n.func) == "lock_user_for_update"
            or (
                _ten_goi(n.func) == "lock_users_in_id_order"
                and any(k.arg in ("key_update_ids", "delete_targets") for k in n.keywords)
            )
            for n in goi
        ):
            giu.add(khoa)
            sai += [(khoa, _ten_goi(n.func)) for n in goi if re.fullmatch(r"lock_\w*grant\w*", _ten_goi(n.func))]
    assert (giu, sai) == (GIU_NGUOI_FOR_UPDATE, [])


@pytest.mark.parametrize("ten", ["create_review_secretary", "revoke_review_secretary"])
def test_route_ghi_kiem_phan_hoi_truoc_commit_bang_helper_cua_l4(ten):
    """Rà hợp nhất 23-11 I1 + quyết định owner O2 23-11 (``gd2\\gd2c\\c2\\QUYET-DINH-OWNER-C2-O1-O2-CAU-404-2026-11-23.md``): hai route
    ghi của C1 gọi ``response_checked_before_commit`` — ĐÚNG hàm của ``app.routers.admission_review`` (MỘT helper) — với ĐÚNG
    ``response_model`` của route, một lần, TRƯỚC ``db.commit()``. Hành vi (CSDL không đổi khi thân lệch):
    ``tests/api/test_gd2c_c1_thu_ky_api.py::test_i1_phan_hoi_lech_schema_500_khong_ghi_gi``."""
    from fastapi.routing import APIRoute

    from app.main import fastapi_app
    from app.routers import admission_review as l4
    from app.routers import admission_review_secretary as r

    assert r.response_checked_before_commit is l4.response_checked_before_commit
    ham = getattr(r, ten)
    goi = [n for n in ast.walk(ast.parse(inspect.getsource(ham))) if isinstance(n, ast.Call)]
    kiem = [n for n in goi if isinstance(n.func, ast.Name) and n.func.id == "response_checked_before_commit"]
    commit = [n for n in goi if isinstance(n.func, ast.Attribute) and n.func.attr == "commit"]
    assert len(kiem) == 1 and len(commit) == 1, (ten, len(kiem), len(commit))
    assert (kiem[0].lineno, kiem[0].col_offset) < (commit[0].lineno, commit[0].col_offset), ten
    route = next(x for x in fastapi_app.routes if isinstance(x, APIRoute) and x.endpoint is ham)
    assert isinstance(kiem[0].args[0], ast.Name) and kiem[0].args[0].id == route.response_model.__name__, ten
