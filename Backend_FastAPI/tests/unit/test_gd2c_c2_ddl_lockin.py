# -*- coding: utf-8 -*-
"""GĐ2-C C2 — khoá văn bản DDL + nối dây + luật thuần của lựa chọn Ban thư ký (không CSDL).

- Bản ``create_all()`` (``app/models/admission_review_selection.py`` + ``admission_review_selection_ddl.py``) và bản thật ở
  migration ``gd2cs20261122`` không được trôi khỏi nhau (khuôn ``test_gd2c_c1_ddl_lockin.py``): từng câu hàm / trigger, tên + chữ
  CHECK, cột của UNIQUE / khoá ngoại / chỉ mục; lược đồ THẬT so ở ``tests/integration/test_gd2c_c2_migration.py``.
- Sáu loại lựa chọn (ĐT3 §3 năm loại + thiết kế GĐ2-C §2.2 / owner C5 loại thứ sáu) MỘT nguồn cho CHECK, schema API, dịch vụ.
- Owner C6: lý do bắt buộc đúng hai loại; owner C5: cờ "đang ngừng" chỉ hai loại xử lý được.
- Chuỗi Alembic một đầu; SQLSTATE mới chỉ ở đúng tệp; cờ hạ cấp mang nghĩa CHO PHÉP; Casbin template == migration; Casbin trỏ
  đúng route thật và route ấy đi qua ``deps.require_review_secretary``; sổ K4; kiểm kê đóng băng.
- Luật thuần: bảng chân trị "loại áp được cho dòng", "dòng cờ đang ngừng đã xử lý chưa"; thứ tự khoá của đường ghi (đọc mã).
- Câu đọc của repository lựa chọn BIÊN DỊCH được trên phương ngữ PostgreSQL (phiên giả, không CSDL) — CI 45192218468 23-11: hai
  câu GET nổ ``Can't determine which FROM clause to join from`` lúc biên dịch; hình dạng JOIN + tương quan "hiệu lực" giữ nghĩa.

Mỗi ca kiểm MỘT bất biến.
"""
import importlib.util
import inspect
import re
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.models import admission_review_selection as m
from app.models import admission_review_selection_ddl as ddl

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
_MIGRATION = GOC / "alembic" / "versions" / "gd2cs20261122_review_selection.py"
BANG = "admission_review_selection"
SAU_LOAI = (
    "admit_over_major_quota",
    "consider_next_choice",
    "defer_supplement",
    "admit_without_ethnic_bonus",
    "exclude_this_session",
    "keep_despite_inactive",
)


def _chuan_hoa(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _mig():
    spec = importlib.util.spec_from_file_location("_gd2c_c2_mig", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rang_buoc_model():
    t = m.AdmissionReviewSelection.__table__
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


def test_trigger_canh_ca_them_sua_xoa():
    """Một trigger BEFORE INSERT OR UPDATE OR DELETE — thiếu INSERT thì "chỉ khi nháp" / "dòng dựa vào" lọt; thiếu UPDATE / DELETE
    thì "chỉ thêm" lọt."""
    assert "BEFORE INSERT OR UPDATE OR DELETE ON %s" % BANG in _chuan_hoa(ddl.SQL_TRIGGER_SELECTION_GUARD)


def test_trigger_chi_nhap_goi_dung_ham_kiem_chung_cua_gd2b():
    """T16 "lựa chọn chỉ ghi khi ``draft``": MỘT nguồn với điểm sàn — gọi ``admission_review_assert_session_draft`` (``FOR SHARE``,
    ``QLC02`` ⇒ 409 ``REVIEW_SESSION_NOT_DRAFT``), không tự viết lại phép kiểm."""
    s = _chuan_hoa(ddl.SQL_FN_SELECTION_GUARD)
    assert "PERFORM admission_review_assert_session_draft(NEW.session_id);" in s
    assert "'draft'" not in s


def test_trigger_doi_dong_dua_vao_khop_ma_bam_va_nv():
    s = _chuan_hoa(ddl.SQL_FN_SELECTION_GUARD)
    assert "v_row_hash IS DISTINCT FROM NEW.based_on_row_hash" in s
    assert "v_row_choice IS DISTINCT FROM NEW.choice_id" in s
    assert "v_run_kind IS DISTINCT FROM 'evaluate'" in s and "v_run_status IS DISTINCT FROM 'done'" in s


def test_khong_co_ky_tu_lam_hong_ddl_hoac_text():
    for cau in (*ddl.STATEMENTS, *_mig().STATEMENTS):
        assert "%" not in cau and "::" not in cau


def test_sqlstate_trigger_khop_hang():
    assert ddl.SQLSTATE_SELECTION_IMMUTABLE == "QLC22"
    assert ddl.SQL_FN_SELECTION_GUARD.count("ERRCODE = 'QLC22'") == 4
    mig = _mig()
    assert (mig.SQLSTATE_CASBIN_COUNT, mig.SQLSTATE_DOWNGRADE_DATA_PRESENT) == ("QLC23", "QLC24")


@pytest.mark.parametrize(
    "ma, duoc_phep",
    [
        ("QLC22", {"app/models/admission_review_selection_ddl.py", "alembic/versions/gd2cs20261122_review_selection.py"}),
        ("QLC23", {"alembic/versions/gd2cs20261122_review_selection.py"}),
        ("QLC24", {"alembic/versions/gd2cs20261122_review_selection.py"}),
    ],
)
def test_sqlstate_moi_chi_dung_o_tep_gd2c_c2(ma, duoc_phep):
    gap = set()
    for thu_muc in ("app", "alembic"):
        for p in (GOC / thu_muc).rglob("*.py"):
            if re.search(r"['\"]%s['\"]" % ma, p.read_text(encoding="utf-8")):
                gap.add(p.relative_to(GOC).as_posix())
    assert gap == duoc_phep


# ── bảng ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_cot_model_bang_migration():
    cot = [c.name for c in m.AdmissionReviewSelection.__table__.columns]
    nguon = _mig().CREATE_TABLES[0]
    trong_mig = re.findall(r"^\t(\w+) [A-Z]", nguon, re.M)
    assert [c for c in trong_mig if c not in ("PRIMARY", "CONSTRAINT")] == cot


def test_ten_rang_buoc_va_chi_muc_model_bang_migration():
    nguon = _MIGRATION.read_text(encoding="utf-8")
    trong_mig = set(re.findall(r"CONSTRAINT ((?:ck|uq|fk)_\w+)", nguon))
    trong_mig |= set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+) ON", nguon))
    assert trong_mig == set(_rang_buoc_model())


def test_chu_check_model_bang_migration():
    nguon = _MIGRATION.read_text(encoding="utf-8")
    checks = {ten: c for ten, c in _rang_buoc_model().items() if isinstance(c, CheckConstraint)}
    assert set(checks) == {
        "ck_admission_review_selection_kind",
        "ck_admission_review_selection_row_hash",
        "ck_admission_review_selection_note",
        "ck_admission_review_selection_note_required",
        "ck_admission_review_selection_supersedes_order",
    }
    for ten, c in checks.items():
        assert _chuan_hoa(_check_trong_migration(nguon, ten)) == _chuan_hoa(str(c.sqltext)), ten


def test_unique_khoa_ngoai_chi_muc_model_bang_migration():
    """Cột của mỗi UNIQUE / khoá ngoại (kèm bảng đích + ``ON DELETE``) / chỉ mục — model == migration."""
    nguon = _chuan_hoa(_MIGRATION.read_text(encoding="utf-8"))
    nguon_cm = _chuan_hoa(" ".join(_mig().CREATE_INDEXES))
    for ten, c in _rang_buoc_model().items():
        if isinstance(c, UniqueConstraint):
            cot = ", ".join(col.name for col in c.columns)
            assert re.search(r"CONSTRAINT %s UNIQUE \(%s\)" % (ten, re.escape(cot)), nguon), ten
        elif isinstance(c, ForeignKeyConstraint):
            cot = ", ".join(c.column_keys)
            dich = c.elements[0].target_fullname.split(".")[0]
            dich_sql = '"user"' if dich == "user" else dich
            cot_dich = ", ".join(e.target_fullname.split(".")[1] for e in c.elements)
            mau = r"CONSTRAINT %s FOREIGN KEY\(%s\) REFERENCES %s \(%s\) ON DELETE %s" % (
                ten, re.escape(cot), re.escape(dich_sql), re.escape(cot_dich), c.ondelete,
            )
            assert re.search(mau, nguon), ten
        elif isinstance(c, Index):
            cot = ", ".join(col.name for col in c.columns)
            dau = "CREATE UNIQUE INDEX" if c.unique else "CREATE INDEX"
            assert re.search(r"%s %s ON %s \(%s\)" % (dau, ten, BANG, re.escape(cot)), nguon_cm), ten


def test_goc_chuoi_thay_the_duy_nhat_mot_phan():
    """Gốc chuỗi thay thế của một (lần xét, hồ sơ) là DUY NHẤT — điều kiện một phần giống hệt ở model và migration."""
    idx = _rang_buoc_model()["uq_admission_review_selection_root"]
    assert idx.unique and [c.name for c in idx.columns] == ["session_id", "profile_id"]
    where = str(idx.dialect_options["postgresql"]["where"])
    assert where == m.ROOT_WHERE == "supersedes_id IS NULL"
    assert (
        "uq_admission_review_selection_root ON %s (session_id, profile_id) WHERE %s" % (BANG, where)
        in _chuan_hoa(" ".join(_mig().CREATE_INDEXES))
    )


def test_ho_so_khong_co_khoa_ngoai_va_nguoi_dung_restrict():
    """``profile_id`` KHÔNG khoá ngoại (khuôn ``admission_review_row`` — ảnh chụp bất biến); cột người dùng duy nhất
    ``decided_by_user_id`` RESTRICT ở cả hai bản."""
    fks = {tuple(c.column_keys) for c in m.AdmissionReviewSelection.__table__.foreign_key_constraints}
    assert fks == {("session_id", "academic_year"), ("based_on_run_id",), ("decided_by_user_id",), ("supersedes_id",)}
    assert "admission_profile" not in _mig().CREATE_TABLES[0]
    cot_user = sorted(
        (fk.parent.name, fk.ondelete) for fk in m.AdmissionReviewSelection.__table__.foreign_keys
        if fk.column.table.name == "user"
    )
    assert cot_user == [("decided_by_user_id", "RESTRICT")]


# ── sáu loại + lý do + cờ đang ngừng: MỘT nguồn ───────────────────────────────────────────────────────────────────────
def test_sau_loai_lua_chon_mot_nguon_cho_check_va_schema():
    from typing import get_args

    from app.schemas.admission_review_selection import SelectionKind

    assert m.SELECTION_KINDS == SAU_LOAI
    assert get_args(SelectionKind) == SAU_LOAI
    assert m.CHECK_SELECTION_KIND == "kind IN (%s)" % ",".join("'%s'" % k for k in SAU_LOAI)


def test_owner_c6_bat_buoc_ly_do_dung_hai_loai():
    assert set(m.SELECTION_KINDS_REASON_REQUIRED) == {"exclude_this_session", "defer_supplement"}
    assert m.CHECK_SELECTION_NOTE_REQUIRED == (
        "kind NOT IN ('exclude_this_session','defer_supplement') OR note IS NOT NULL"
    )


def test_owner_c5_co_dang_ngung_chi_hai_loai_xu_ly():
    assert set(m.SELECTION_KINDS_RESOLVING_INACTIVE) == {"keep_despite_inactive", "exclude_this_session"}


def test_co_dang_ngung_lay_tu_luat_gd2b():
    from app.services import admission_review_rules as rules
    from app.services import admission_review_selection_service as svc

    assert svc.INACTIVE_FLAGS == (rules.FLAG_OFFERING_INACTIVE, rules.FLAG_MAJOR_INACTIVE)


# ── chuỗi Alembic + hạ cấp ────────────────────────────────────────────────────────────────────────────────────────────
def test_migration_noi_sau_c1():
    mod = _mig()
    assert (mod.revision, mod.down_revision) == ("gd2cs20261122", "gd2c20261122")


def test_mot_head_alembic_va_c2_tren_chuoi_toi_head():
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
    assert "gd2cs20261122" in revs and ("gd2cs20261122" in heads or "gd2cs20261122" in downs)


def test_nang_cap_mot_cau_do_khoa_bang_theo_thu_tu_truoc_moi_cau_tao():
    sql = _chuan_hoa(_mig()._upgrade_sql())
    assert sql.count("DO $gd2c_c2$") == 1
    khoa = [sql.index("LOCK TABLE %s IN SHARE ROW EXCLUSIVE MODE" % t) for t in ('"user"', "admission_review_session",
                                                                                 "admission_review_run")]
    assert khoa == sorted(khoa)
    assert sql.index("set_config('lock_timeout', '10s', true)") < khoa[0] < sql.index("CREATE TABLE %s" % BANG)


def test_co_ha_cap_mang_nghia_cho_phep_dung_chu_1():
    mod = _mig()
    nguon = inspect.getsource(mod.downgrade)
    assert mod.DOWNGRADE_FLAG == "GD2C_C2_DOWNGRADE_DROP_DATA_ENABLED"
    assert "os.environ.get(DOWNGRADE_FLAG) == \"1\"" in nguon
    ha = mod._downgrade_sql()
    assert "IS DISTINCT FROM '1'" in ha and "ERRCODE = 'QLC24'" in ha


# ── Casbin ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_casbin_template_bang_migration_chi_can_bo_allow():
    """Template (seed dev / test) sinh ĐÚNG các dòng migration chép cứng (seed production): chỉ ``role:officer`` allow (Quản lý /
    Kế toán kế thừa; Admin wildcard); KHÔNG deny kế toán (cổng trả 404 như người chưa gán — thiết kế §4)."""
    from app.casbin_config import policy_templates as pt

    mig = _mig()
    doi_tuong = set(pt.GD2C_REVIEW_SECRETARY_OBJECTS)
    tu_template = set()
    for tid in pt.POLICY_TEMPLATES:
        for r in pt.apply_template(tid, f"role:{tid}"):
            if (r["object"], r["action"]) in doi_tuong:
                tu_template.add((r["subject"], r["object"], r["action"], r["eft"]))
    assert set(mig.CASBIN_POLICIES) == tu_template
    assert {p[0] for p in tu_template} == {"role:officer"} and {p[3] for p in tu_template} == {"allow"}
    assert f"template_id = '{mig.CASBIN_TEMPLATE_ID}'" in mig._downgrade_sql()


def test_casbin_tro_dung_route_that_va_route_di_qua_cong_thu_ky():
    """Mỗi dòng Casbin của C2 khớp ĐÚNG một route thật; route ấy khai ``deps.require_review_secretary`` (lớp quyền thật) và
    ``database.get_db`` (cổng khoá trong CHÍNH giao dịch của route)."""
    from fastapi.routing import APIRoute

    from app import database
    from app.casbin_config import policy_templates as pt
    from app.core import deps
    from app.main import fastapi_app

    def _goi(dep):
        yield dep.call
        for con in dep.dependencies:
            yield from _goi(con)

    that = {(meth, r.path): r for r in fastapi_app.routes if isinstance(r, APIRoute) for meth in r.methods}
    for o, a in pt.GD2C_REVIEW_SECRETARY_OBJECTS:
        route = that.get((a, o))
        assert route is not None, (a, o)
        goi = set(_goi(route.dependant))
        assert deps.require_review_secretary in goi, (a, o)
        assert database.get_db in goi, (a, o)
        assert deps.require_quota_table_admin not in goi, (a, o)


def test_route_lua_chon_dung_bo_ba_route_cua_module_rieng():
    from fastapi.routing import APIRoute

    from app.main import fastapi_app

    duong = sorted(
        (meth, r.path)
        for r in fastapi_app.routes
        if isinstance(r, APIRoute) and r.endpoint.__module__ == "app.routers.admission_review_selection"
        for meth in r.methods
    )
    assert duong == [
        ("GET", "/api/admission-config/review-sessions/{session_id}/selections"),
        ("GET", "/api/admission-config/review-sessions/{session_id}/selections/{profile_id}"),
        ("PUT", "/api/admission-config/review-sessions/{session_id}/selections/{profile_id}"),
    ]


# ── K4 + đóng băng ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_so_k4_co_cot_nguoi_ghi_la_block_actor():
    from app.services.user_deletion_policy import USER_REFERENCES, UserRefGroup

    hang = {(r.table, r.column): r.group for r in USER_REFERENCES if r.table == BANG}
    assert hang == {(BANG, "decided_by_user_id"): UserRefGroup.BLOCK_ACTOR}


def test_dong_bang_co_route_ghi_va_module():
    from app.middleware.admission_freeze import ADMISSION_ROUTER_MODULES, ADMISSION_WRITE_ROUTES

    assert ("PUT", "/api/admission-config/review-sessions/{session_id}/selections/{profile_id}") in ADMISSION_WRITE_ROUTES
    assert "app.routers.admission_review_selection" in ADMISSION_ROUTER_MODULES


# ── luật thuần ────────────────────────────────────────────────────────────────────────────────────────────────────────
KHONG_AP = "selection_kind_not_applicable"
VUOT, NV_KE, CHO_BS, KHONG_DT = "admit_over_major_quota", "consider_next_choice", "defer_supplement", "admit_without_ethnic_bonus"
BON_GOI_Y = (VUOT, NV_KE, CHO_BS, KHONG_DT)


@pytest.mark.parametrize(
    "loai, nv, co, goi_y, mong_doi",
    [
        # Bốn loại theo GỢI Ý của GĐ2-B: áp được KHI VÀ CHỈ KHI dòng mang đúng gợi ý ấy (rà hợp nhất 23-11 H5.2, CLAUDE.md §7).
        (VUOT, 11, (), (VUOT,), None),
        (VUOT, 11, (), (), KHONG_AP),  # dòng ``auto`` (trong số chỗ) — máy xét không gợi ý trúng vượt
        (VUOT, 11, (), (NV_KE,), KHONG_AP),
        (NV_KE, 11, (), (VUOT, NV_KE), None),
        (NV_KE, 11, (), (VUOT,), KHONG_AP),  # không còn NV sau xét được (vd chỉ còn học vụ chỉ tiêu 0)
        (CHO_BS, 11, (), (KHONG_DT, CHO_BS), None),
        (CHO_BS, 11, (), (), KHONG_AP),
        (CHO_BS, None, ("ethnic_priority_undetermined",), (), KHONG_AP),  # ``not_passed`` + cờ dân tộc: máy xét không gợi ý
        (KHONG_DT, 11, (), (KHONG_DT, CHO_BS), None),
        (KHONG_DT, 11, (), (), KHONG_AP),
        # Ràng buộc định nghĩa: loại nói về NV được xếp mà dòng không có NV được xếp (dòng lạ) ⇒ không áp, kể cả khi có gợi ý.
        (VUOT, None, (), (VUOT,), KHONG_AP),
        (KHONG_DT, None, (), (KHONG_DT,), KHONG_AP),
        # "Vẫn giữ" (owner C5): có NV được xếp + cờ đang ngừng (một trong hai cờ là đủ); gợi ý không liên quan.
        ("keep_despite_inactive", 11, ("offering_inactive",), (), None),
        ("keep_despite_inactive", 11, ("major_inactive", "quota_closed"), (), None),
        ("keep_despite_inactive", 11, ("quota_closed",), (), KHONG_AP),
        ("keep_despite_inactive", 11, (), BON_GOI_Y, KHONG_AP),
        ("keep_despite_inactive", None, ("offering_inactive",), (), KHONG_AP),
        # "Loại khỏi lần này": mọi dòng.
        ("exclude_this_session", 11, (), (), None),
        ("exclude_this_session", None, (), (), None),
        # Mã lạ — kể cả khi chính mã ấy nằm trong gợi ý — không mở được loại lạ.
        ("loai_la", 11, (), (), KHONG_AP),
        ("loai_la", 11, (), ("loai_la",), KHONG_AP),
    ],
)
def test_loai_ap_duoc_cho_dong(loai, nv, co, goi_y, mong_doi):
    from app.services.admission_review_selection_service import kind_applicability_error

    assert kind_applicability_error(loai, considered_choice_id=nv, flags=co, decision_hints=goi_y) == mong_doi


@pytest.mark.parametrize(
    "nv, co, goi_y, mong_doi",
    [
        (11, (), (), ["exclude_this_session"]),
        (11, (), (VUOT, NV_KE), [VUOT, NV_KE, "exclude_this_session"]),
        (11, ("major_inactive",), (KHONG_DT, CHO_BS), [CHO_BS, KHONG_DT, "exclude_this_session", "keep_despite_inactive"]),
        (11, ("major_inactive",), BON_GOI_Y, list(SAU_LOAI)),
        (None, (), (), ["exclude_this_session"]),
    ],
)
def test_danh_sach_loai_chon_duoc_cung_vi_tu_voi_cong_ghi(nv, co, goi_y, mong_doi):
    """Danh sách cho giao diện (L4 đưa vào bản xem dòng) = ĐÚNG các loại cổng ghi nhận — MỘT vị từ."""
    from app.services.admission_review_selection_service import applicable_selection_kinds

    assert applicable_selection_kinds(considered_choice_id=nv, flags=co, decision_hints=goi_y) == mong_doi


def test_bon_loai_lua_chon_trung_bon_ma_goi_y_cua_gd2b():
    """CLAUDE.md §7: mã loại "theo gợi ý" = ĐÚNG mọi hằng ``HINT_*`` của luật GĐ2-B (GĐ2-B thêm / đổi gợi ý ⇒ đỏ — phải quyết loại
    lựa chọn tương ứng, không lặng lẽ lệch); hai loại còn lại là của riêng C2 (owner C5)."""
    from app.services import admission_review_rules as R
    from app.services import admission_review_selection_service as svc

    goi_y = {v for k, v in vars(R).items() if k.startswith("HINT_")}
    assert svc.KINDS_FROM_DECISION_HINTS == goi_y == set(BON_GOI_Y)
    assert set(m.SELECTION_KINDS) - goi_y == {m.SELECTION_EXCLUDE_THIS_SESSION, m.SELECTION_KEEP_DESPITE_INACTIVE}


def _dong_that_cua_may_xet_gd2b():
    """Dòng THẬT do máy xét GĐ2-B dựng (``admission_review_rules.evaluate_run`` trên dữ kiện SẠCH của ``test_gd2b_luat_thuan``) —
    phủ đủ bốn gợi ý, ``needs_decision`` có / không gợi ý, cờ "đang ngừng", cả bốn tab."""
    from decimal import Decimal as D

    from app.services import admission_review_rules as R
    from tests.unit import test_gd2b_luat_thuan as B

    hv_1_cho = {B.HV1: B._hv(B.HV1, annual_quota=1), B.HV2: B._hv(B.HV2), B.HV3: B._hv(B.HV3)}
    a = B._ho_so(1001, nvs=[B._nv(511, 1, B.HV1, subject_total=D("18"))])
    b_hai_nv = B._ho_so(1002, nvs=[B._nv(521, 1, B.HV1, subject_total=D("17")), B._nv(522, 2, B.HV2)])
    b_mot_nv = B._ho_so(1002, nvs=[B._nv(521, 1, B.HV1, subject_total=D("17"))])
    nhom_het = (R.GroupFacts(B.NHOM, "N1", "Nhóm 1", ceiling=1),)
    cu_tru_tu_choi = {B.HOC_BA: B._giay(), B.KHAI_SINH: B._giay(2), B.CU_TRU: B._giay(3, status="rejected")}
    ngung = {B.HV1: B._hv(B.HV1, offering_inactive=True, major_inactive=True), B.HV2: B._hv(B.HV2), B.HV3: B._hv(B.HV3)}
    luot = (
        B._chay(a, b_hai_nv, run=B._run(hv=hv_1_cho)),  # BT20: ``auto`` + vượt chỉ tiêu (trúng vượt + NV kế)
        B._chay(a, b_mot_nv, run=B._run(hv=hv_1_cho, groups=nhom_het)),  # nhóm hết chỗ, không NV sau: cần quyết, KHÔNG gợi ý
        B._chay(B._dtts(docs=cu_tru_tu_choi)),  # BT14: ưu tiên dân tộc chưa xác định, đạt sàn (không cộng dân tộc + chờ bổ sung)
        B._chay(B._dtts(docs=cu_tru_tu_choi, nvs=[B._nv(501, 1, B.HV1, subject_total=D("13.00"))])),  # ``not_passed`` + cờ dân tộc
        B._chay(B._ho_so(), run=B._run(hv=ngung)),  # BT41: ``auto`` + cờ đang ngừng
        B._run_hon_hop(),  # ``auto`` / ``needs_decision`` / ``not_passed`` / ``ineligible`` (nhiều mã)
    )
    return [r for l in luot for r in l.rows]


def _loai_cho_dong(svc, r):
    return svc.applicable_selection_kinds(
        considered_choice_id=r.considered.choice_id if r.considered is not None else None,
        flags=r.flags,
        decision_hints=r.decision_hints,
    )


def test_loai_theo_goi_y_khop_dung_decision_hints_tren_dong_that_cua_may_xet_gd2b():
    """CLAUDE.md §7 — test KHOÁ HAI BÊN BẰNG NHAU (rà hợp nhất 23-11 H5.2): trên dòng THẬT của máy xét GĐ2-B, tập loại "theo gợi ý"
    mà C2 cho chọn == ĐÚNG ``decision_hints`` của dòng. Ca tự kiểm độ phủ của bộ dữ kiện (đủ bốn gợi ý, có dòng cần quyết KHÔNG gợi ý,
    đủ bốn tab) — dữ kiện trôi thì đỏ ở đây, không xanh rỗng."""
    from app.services import admission_review_rules as R
    from app.services import admission_review_selection_service as svc

    dong = _dong_that_cua_may_xet_gd2b()
    assert set().union(*(r.decision_hints for r in dong)) == set(BON_GOI_Y)
    assert {r.tab for r in dong} == {R.TAB_AUTO, R.TAB_NEEDS_DECISION, R.TAB_NOT_PASSED, R.TAB_INELIGIBLE}
    assert any(r.tab == R.TAB_NEEDS_DECISION and not r.decision_hints for r in dong)
    for r in dong:
        theo_goi_y = {k for k in _loai_cho_dong(svc, r) if k in svc.KINDS_FROM_DECISION_HINTS}
        assert theo_goi_y == set(r.decision_hints), (r.profile_id, r.tab, r.decision_hints)


def test_van_giu_ap_duoc_dung_khi_dong_that_mang_co_dang_ngung():
    from app.services import admission_review_selection_service as svc

    dong = _dong_that_cua_may_xet_gd2b()
    assert any(set(r.flags) & set(svc.INACTIVE_FLAGS) for r in dong)
    for r in dong:
        co_ngung = bool(set(r.flags) & set(svc.INACTIVE_FLAGS))
        assert (m.SELECTION_KEEP_DESPITE_INACTIVE in _loai_cho_dong(svc, r)) == co_ngung, (r.profile_id, r.flags)


@pytest.mark.parametrize(
    "loai, bam_chon, mong_doi",
    [
        (None, None, "missing"),
        ("admit_over_major_quota", "a" * 64, "not_resolving"),
        ("consider_next_choice", "a" * 64, "not_resolving"),
        ("defer_supplement", "a" * 64, "not_resolving"),
        ("admit_without_ethnic_bonus", "a" * 64, "not_resolving"),
        ("keep_despite_inactive", "b" * 64, "stale"),
        ("exclude_this_session", "b" * 64, "stale"),
        ("keep_despite_inactive", "a" * 64, None),
        ("exclude_this_session", "a" * 64, None),
    ],
)
def test_dong_co_dang_ngung_da_xu_ly_chua(loai, bam_chon, mong_doi):
    from app.services.admission_review_selection_service import classify_inactive_row

    assert classify_inactive_row(row_hash="a" * 64, selection_kind=loai, selection_row_hash=bam_chon) == mong_doi


@pytest.mark.parametrize("vao, ra", [(None, None), ("", None), ("   ", None), ("  Thiếu học bạ  ", "Thiếu học bạ")])
def test_chuan_hoa_ly_do(vao, ra):
    from app.services.admission_review_selection_service import normalize_note

    assert normalize_note(vao) == ra


# ── thứ tự khoá của đường ghi (đọc mã; hành vi hai phiên đo ở test CSDL / API) ─────────────────────────────────────────
def test_duong_ghi_khoa_lan_xet_roi_ho_so_roi_moi_doc_va_chen_khong_khoa_nam_khong_dong_tien():
    """Thiết kế §3.1: ghi lựa chọn = lần xét ``FOR UPDATE`` (KHÔNG khoá năm) → hồ sơ ``FOR UPDATE`` → đọc → chèn; không chạm dòng
    tiền. Lý do bắt buộc kiểm TRƯỚC mọi khoá (lỗi đầu vào)."""
    from app.services import admission_review_selection_service as svc

    src = inspect.getsource(svc.record_selection)
    thu_tu = [
        src.index("SELECTION_KINDS_REASON_REQUIRED"),
        src.index("review_repo.lock_session("),
        src.index("repo.lock_profile("),
        src.index("repo.latest_done_evaluate_run_id("),
        src.index("repo.get_row("),
        src.index("based_on_row_hash != row.row_hash"),
        src.index("repo.effective_selection("),
        src.index("repo.insert_selection("),
    ]
    assert thu_tu == sorted(thu_tu)
    for cam in ("lock_review_year", "review_year_lock", "fee_", "payment", "lock_users_in_id_order"):
        assert cam not in src, cam


def test_route_ghi_commit_sau_dich_vu():
    from app.routers import admission_review_selection as r

    src = inspect.getsource(r.put_review_selection)
    assert src.index("selection_service.record_selection(") < src.index("await db.commit()")


def test_route_ghi_kiem_phan_hoi_truoc_commit_bang_helper_cua_l4():
    """Rà hợp nhất 23-11 I1 — CLAUDE.md §6: L4 vá 4 route ghi (E1 / E4 / E5 / E6); PUT lựa chọn là route ghi thứ NĂM cùng tiền tố.
    ``response_checked_before_commit`` (MỘT helper — đúng hàm của ``app.routers.admission_review``) với ĐÚNG ``response_model`` của
    route, gọi một lần, TRƯỚC ``db.commit()``. Hành vi (CSDL không đổi khi thân lệch): ``test_i1_phan_hoi_lech_schema_500_khong_ghi_gi``
    ở ``tests/api/test_gd2c_c2_lua_chon_api.py``."""
    import ast

    from fastapi.routing import APIRoute

    from app.main import fastapi_app
    from app.routers import admission_review as l4
    from app.routers import admission_review_selection as r

    assert r.response_checked_before_commit is l4.response_checked_before_commit
    goi = [n for n in ast.walk(ast.parse(inspect.getsource(r.put_review_selection))) if isinstance(n, ast.Call)]
    kiem = [n for n in goi if isinstance(n.func, ast.Name) and n.func.id == "response_checked_before_commit"]
    commit = [n for n in goi if isinstance(n.func, ast.Attribute) and n.func.attr == "commit"]
    assert len(kiem) == 1 and len(commit) == 1, (len(kiem), len(commit))
    assert (kiem[0].lineno, kiem[0].col_offset) < (commit[0].lineno, commit[0].col_offset)
    route = next(x for x in fastapi_app.routes if isinstance(x, APIRoute) and x.endpoint is r.put_review_selection)
    assert isinstance(kiem[0].args[0], ast.Name) and kiem[0].args[0].id == route.response_model.__name__


# ── câu đọc của repository biên dịch được (phiên giả, không CSDL) ──────────────────────────────────────────────────────
# CI 45192218468 (23-11): ba ca GET lựa chọn ở ``tests/api/test_gd2c_c2_lua_chon_api.py`` đỏ ``InvalidRequestError: Can't
# determine which FROM clause to join from`` tại ``list_effective_selections`` / ``selection_history`` — ORM không chọn được vế trái
# của ``outerjoin`` (hai ứng viên: bảng lựa chọn và ``user``; ON chứa câu con "lượt mới nhất"). Lỗi nổ lúc BIÊN DỊCH câu, chưa chạm
# CSDL ⇒ một phiên giả chỉ biên dịch là đủ thấy, ở lát unit. Biến thể kiểm ngược: bỏ ``.select_from(Sel)`` ở
# ``_selections_with_people_and_current_row`` ⇒ ``test_cau_doc_cua_repository_lua_chon_bien_dich_duoc[list_effective_selections]``
# và ``[selection_history]`` đỏ với ĐÚNG ``InvalidRequestError`` ấy.
class _KetQuaRong:
    """Đủ ba cách đọc kết quả mà repository lựa chọn dùng; luôn rỗng."""

    def all(self):
        return []

    def one_or_none(self):
        return None

    def scalar_one_or_none(self):
        return None


class _PhienChiBienDich:
    """``AsyncSession`` giả: BIÊN DỊCH câu nhận được bằng phương ngữ PostgreSQL (đúng bước ORM ném lỗi ở CI) rồi trả kết quả rỗng.
    Không CSDL, không thực thi."""

    def __init__(self):
        self.sql = []

    async def execute(self, cau, tham_so=None):
        self.sql.append(_chuan_hoa(str(cau.compile(dialect=postgresql.dialect()))))
        return _KetQuaRong()


#: Mọi hàm ĐỌC của repository lựa chọn → đối số giả (sau ``db``).
_HAM_DOC = {
    "lock_profile": (7,),
    "latest_done_evaluate_run_id": (1,),
    "get_row": (3, 7),
    "effective_selection": (1, 7),
    "list_effective_selections": (1,),
    "selection_history": (1, 7),
    "user_summary": (5,),
    "rows_with_flags_and_effective_selection": (1, ("offering_inactive",)),
    "session_exists": (1,),
}
#: Hàm GHI qua ORM (``add`` + ``flush``) — không đi qua ``execute``.
_HAM_GHI_ORM = {"insert_selection"}


async def _sql_cua(ten: str) -> str:
    from app.repositories import admission_review_selection_repository as repo

    db = _PhienChiBienDich()
    await getattr(repo, ten)(db, *_HAM_DOC[ten])
    assert len(db.sql) == 1, db.sql
    return db.sql[0]


def test_moi_ham_cua_repository_lua_chon_co_ca_bien_dich():
    """CLAUDE.md §6: hàm MỚI của repository (vd C4 thêm câu đọc) phải vào ``_HAM_DOC`` (hay ``_HAM_GHI_ORM``) — không thì câu của
    nó không được biên dịch ở đây và lỗi kiểu CI 45192218468 chỉ lộ ở ca API."""
    from app.repositories import admission_review_selection_repository as repo

    ham = {ten for ten, f in inspect.getmembers(repo, inspect.iscoroutinefunction) if f.__module__ == repo.__name__}
    assert ham == set(_HAM_DOC) | _HAM_GHI_ORM


@pytest.mark.parametrize("ten", sorted(_HAM_DOC))
async def test_cau_doc_cua_repository_lua_chon_bien_dich_duoc(ten):
    """Câu của hàm đọc biên dịch được (ORM xác định được vế trái của mọi JOIN) — không cần CSDL."""
    assert (await _sql_cua(ten)).startswith("SELECT ")


@pytest.mark.parametrize("ten", ["list_effective_selections", "selection_history"])
async def test_cau_doc_lua_chon_noi_tu_bang_lua_chon_dong_hien_tai_noi_ngoai_nguoi_ghi_noi_trong(ten):
    """Đặt vế trái tường minh KHÔNG đổi nghĩa: FROM bắt đầu ở bảng lựa chọn; dòng hiện tại nối NGOÀI theo (lượt ``evaluate`` xong
    mới nhất, hồ sơ) — hồ sơ rời lượt mới nhất vẫn còn lựa chọn, ``row_hash`` NULL ⇒ ``is_stale``; người ghi nối TRONG."""
    sql = await _sql_cua(ten)
    assert (
        "FROM admission_review_selection LEFT OUTER JOIN admission_review_row ON admission_review_row.run_id = "
        "(SELECT max(admission_review_run.id)" in sql
        and " AND admission_review_row.profile_id = admission_review_selection.profile_id "
        'JOIN "user" ON "user".id = admission_review_selection.decided_by_user_id' in sql
    ), sql


async def test_danh_sach_hieu_luc_tuong_quan_voi_dong_lua_chon_ngoai():
    """Vị từ "chưa bị thay" (``_is_effective``) TƯƠNG QUAN với dòng lựa chọn của câu ngoài: câu con chỉ có bí danh ``later``. Không
    tương quan (``FROM … AS …_1, admission_review_selection``) thì chỉ cần MỘT lần đổi ý ở bất kỳ hồ sơ nào là danh sách rỗng."""
    sql = await _sql_cua("list_effective_selections")
    assert (
        "FROM admission_review_selection AS admission_review_selection_1 "
        "WHERE admission_review_selection_1.supersedes_id = admission_review_selection.id" in sql
    ), sql
