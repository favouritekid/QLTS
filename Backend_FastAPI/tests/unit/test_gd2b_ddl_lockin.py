# -*- coding: utf-8 -*-
"""GĐ2-B (lát L1) — khoá văn bản DDL: bản ``create_all()`` (``app/models/admission_review.py`` + ``admission_review_ddl.py``) và bản
thật ở migration ``gd2b20261121`` không được trôi khỏi nhau; SQLSTATE mới chỉ dùng đúng chỗ; chuỗi Alembic một đầu; cờ hạ cấp mang
nghĩa CHO PHÉP; khoá bảng có sẵn theo thứ tự cố định; sổ phân loại khoá ngoại tới ``user`` có đủ cột mới (BT38, một phần BT37).

Khuôn ``test_gd2a_quota_ddl_lockin.py`` (so từng câu sau khi chuẩn hoá khoảng trắng) + ``test_council_document_models.py`` (so
tên ràng buộc model ↔ migration). Lược đồ THẬT (cột, kiểu, mặc định, định nghĩa ràng buộc sau khi PostgreSQL chuẩn hoá) so ở
``tests/integration/test_gd2b_migration.py``. Mỗi ca kiểm MỘT bất biến.
"""
import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

from app.models import admission_review as m
from app.models import admission_review_ddl as ddl

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
_MIGRATION = GOC / "alembic" / "versions" / "gd2b20261121_lan_xet_nhap.py"
BANG = ("admission_review_session", "admission_review_floor", "admission_review_run", "admission_review_row")
LOP = (m.AdmissionReviewSession, m.AdmissionReviewFloor, m.AdmissionReviewRun, m.AdmissionReviewRow)


def _chuan_hoa(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _mig():
    spec = importlib.util.spec_from_file_location("_gd2b_mig", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rang_buoc_model():
    """{tên: đối tượng} mọi ràng buộc / chỉ mục CÓ TÊN của bốn bảng mới + ``offering_admission_round`` (phần GĐ2-B)."""
    ra = {}
    for lop in LOP:
        t = lop.__table__
        for c in t.constraints:
            if c.name:
                ra[c.name] = c
        for i in t.indexes:
            ra[i.name] = i
    from app.models.offering_admission_round import OfferingAdmissionRound

    for c in OfferingAdmissionRound.__table__.constraints:
        if c.name == "uq_offering_admission_round_id_year":
            ra[c.name] = c
    return ra


def _check_trong_migration(nguon: str, ten: str) -> str:
    """Chữ trong ``CHECK (…)`` của ràng buộc ``ten`` ở migration (đếm ngoặc, không regex tham)."""
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


# ── Hàm + trigger ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_ham_va_trigger_create_all_khop_migration_tung_cau():
    assert [_chuan_hoa(c) for c in ddl.STATEMENTS] == [_chuan_hoa(c) for c in _mig().STATEMENTS]


def test_danh_sach_ham_ha_cap_khop_cau_create_function():
    """Hạ cấp gỡ ĐÚNG các hàm đã tạo (tên + kiểu tham số) — thiếu một hàm ⇒ rác sau hạ cấp; thừa ⇒ hạ cấp đổ."""
    tao = []
    for cau in ddl.STATEMENTS:
        r = re.search(r"CREATE OR REPLACE FUNCTION (\w+)\(([^)]*)\)", cau)
        if r:
            kieu = ", ".join(p.split()[-1] for p in r.group(2).split(",") if p.strip())
            tao.append("%s(%s)" % (r.group(1), kieu))
    assert tuple(tao) == ddl.FUNCTION_SIGNATURES == _mig().FUNCTION_SIGNATURES


def test_moi_bang_moi_co_dung_mot_trigger_canh():
    ten = {re.search(r"\bON (\w+)", c).group(1) for c in ddl.SQL_TRIGGERS}
    assert ten == set(BANG) and len(ddl.SQL_TRIGGERS) == 4


def test_khong_co_ky_tu_lam_hong_ddl_hoac_text():
    # DDL() nội suy bằng toán tử % ; text() hiểu :tên là tham số.
    for cau in (*ddl.STATEMENTS, *_mig().STATEMENTS):
        assert "%" not in cau and "::" not in cau


def test_trigger_san_va_dong_doc_dong_cha_for_share():
    """Kiểm "lần xét nháp" / "lượt đang chạy" phải KHOÁ dòng cha ``FOR SHARE`` (khuôn ``admission_quota_assert_table_unlocked``) —
    đọc thường thì lệnh ghi chen vào giữa giao dịch huỷ / chuyển ``done`` (đo hành vi: ``test_gd2b_rang_buoc_db.py`` hai phiên)."""
    assert "FROM admission_review_session s WHERE s.id = p_session_id FOR SHARE" in _chuan_hoa(ddl.SQL_FN_ASSERT_SESSION_DRAFT)
    assert "FROM admission_review_run r WHERE r.id = NEW.run_id FOR SHARE" in _chuan_hoa(ddl.SQL_FN_ROW_GUARD)


# ── SQLSTATE ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_sqlstate_trigger_khop_hang():
    assert ddl.SQLSTATE_REVIEW_SESSION_NOT_DRAFT == "QLC02"
    assert ddl.SQLSTATE_REVIEW_IMMUTABLE == "QLC03"
    for cau in (ddl.SQL_FN_ASSERT_SESSION_DRAFT, ddl.SQL_FN_SESSION_GUARD):
        assert "ERRCODE = 'QLC02'" in cau
    for cau in (ddl.SQL_FN_SESSION_GUARD, ddl.SQL_FN_RUN_GUARD, ddl.SQL_FN_ROW_GUARD):
        assert "ERRCODE = 'QLC03'" in cau
    assert "QLC03" not in ddl.SQL_FN_ASSERT_SESSION_DRAFT and "QLC02" not in ddl.SQL_FN_RUN_GUARD + ddl.SQL_FN_ROW_GUARD


@pytest.mark.parametrize(
    "ma, duoc_phep",
    [
        # SQLSTATE riêng của GĐ2-B chỉ được xuất hiện ở đúng các tệp GĐ2-B (đã kiểm còn trống trong toàn repo 21-11); một tệp khác
        # dùng lại cùng mã ⇒ handler đổi nhầm lỗi của người khác thành 409 lần xét.
        ("QLC02", {"app/models/admission_review_ddl.py", "alembic/versions/gd2b20261121_lan_xet_nhap.py"}),
        ("QLC03", {"app/models/admission_review_ddl.py", "alembic/versions/gd2b20261121_lan_xet_nhap.py"}),
        ("QLC12", {"alembic/versions/gd2b20261121_lan_xet_nhap.py"}),
    ],
)
def test_sqlstate_moi_chi_dung_o_tep_gd2b(ma, duoc_phep):
    gap = set()
    for thu_muc in ("app", "alembic"):
        for p in (GOC / thu_muc).rglob("*.py"):
            if re.search(r"['\"]%s['\"]" % ma, p.read_text(encoding="utf-8")):
                gap.add(p.relative_to(GOC).as_posix())
    assert gap == duoc_phep


# ── Bảng: tên ràng buộc / chỉ mục, chữ CHECK, khoá ngoại ────────────────────────────────────────────────────────────────
def test_ten_rang_buoc_va_chi_muc_model_bang_migration():
    nguon = _MIGRATION.read_text(encoding="utf-8")
    trong_mig = set(re.findall(r"CONSTRAINT ((?:ck|uq|fk)_\w+)", nguon))
    trong_mig |= set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+) ON", nguon))
    assert trong_mig == set(_rang_buoc_model())


def test_chu_check_model_bang_migration():
    nguon = _MIGRATION.read_text(encoding="utf-8")
    checks = {ten: c for ten, c in _rang_buoc_model().items() if isinstance(c, CheckConstraint)}
    assert checks
    for ten, c in checks.items():
        assert _chuan_hoa(_check_trong_migration(nguon, ten)) == _chuan_hoa(str(c.sqltext)), ten


def test_unique_va_khoa_ngoai_model_bang_migration():
    """Cột của mỗi UNIQUE / khoá ngoại (kèm bảng đích + ``ON DELETE``) — model == migration."""
    nguon = _chuan_hoa(_MIGRATION.read_text(encoding="utf-8"))
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
            assert re.search(r"%s %s ON \w+ \(%s\)" % (dau, ten, re.escape(cot)), nguon), ten


def test_chi_muc_mot_phan_luot_dang_chay():
    """Tối đa MỘT lượt ``queued`` / ``running`` mỗi lần xét — điều kiện một phần giống hệt ở model và migration."""
    idx = _rang_buoc_model()["uq_admission_review_run_session_active"]
    assert idx.unique
    where = str(idx.dialect_options["postgresql"]["where"])
    assert where == m.ACTIVE_RUN_WHERE == "status IN ('queued','running')"
    # Đọc HẰNG ``CREATE_INDEXES`` (câu đã ghép), không đọc chữ nguồn — trong nguồn câu này tách thành hai chuỗi Python.
    assert "uq_admission_review_run_session_active ON admission_review_run (session_id) WHERE %s" % where in _chuan_hoa(
        " ".join(_mig().CREATE_INDEXES)
    )


def test_dong_ket_qua_khong_khoa_ngoai_toi_ho_so():
    """Đặc tả §4.2 "Khác ĐT3 có chủ ý": ``profile_id`` của dòng KHÔNG có khoá ngoại (dòng bất biến; xoá hồ sơ nháp vẫn được)."""
    fks = {tuple(c.column_keys) for c in m.AdmissionReviewRow.__table__.foreign_key_constraints}
    assert fks == {("run_id",)}
    assert "admission_profile" not in _MIGRATION.read_text(encoding="utf-8")


def test_cot_nguoi_dung_moi_restrict_va_co_trong_so_phan_loai():
    """Mọi khoá ngoại tới ``user`` của bốn bảng mới: RESTRICT + nhóm ``BLOCK_ACTOR`` (K4); không thừa, không thiếu."""
    from app.services.user_deletion_policy import USER_REFERENCES, UserRefGroup

    tu_model = {}
    for lop in LOP:
        for c in lop.__table__.foreign_key_constraints:
            if c.referred_table.name == "user":
                assert len(c.column_keys) == 1, c.name
                tu_model[(lop.__tablename__, c.column_keys[0])] = c.ondelete
    assert set(tu_model) == {
        ("admission_review_session", "created_by_user_id"),
        ("admission_review_session", "cancelled_by_user_id"),
        ("admission_review_floor", "updated_by_user_id"),
        ("admission_review_run", "requested_by_user_id"),
    }
    assert set(tu_model.values()) == {"RESTRICT"}
    so = {(r.table, r.column): r.group for r in USER_REFERENCES}
    for k in tu_model:
        assert so.get(k) is UserRefGroup.BLOCK_ACTOR, k


def test_cot_phat_hien_nam_truoc_la_mang_json_bat_buoc():
    """Phụ lục đợt 1 §1 (cờ A13 kèm năm + căn cứ): ``prior_year_findings`` JSONB NOT NULL mặc định ``[]`` + CHECK mảng — ở model và
    migration. (Bất biến "cờ A13 ⇔ mảng khác rỗng" thuộc L2, không ở CSDL.)"""
    from sqlalchemy.dialects.postgresql import JSONB

    cot = m.AdmissionReviewRow.__table__.c.prior_year_findings
    assert isinstance(cot.type, JSONB) and not cot.nullable
    assert str(cot.server_default.arg) == "'[]'"
    assert m.CHECK_ROW_PRIOR_YEAR_FINDINGS_ARRAY == "jsonb_typeof(prior_year_findings) = 'array'"
    assert "prior_year_findings JSONB DEFAULT '[]' NOT NULL" in _MIGRATION.read_text(encoding="utf-8")
    assert "ck_admission_review_row_prior_year_findings_array" in _rang_buoc_model()


def test_cot_json_cho_null_luu_none_thanh_sql_null():
    """Mọi cột JSONB CHO NULL của bốn bảng mới dùng ``none_as_null=True``: Python ``None`` ⇒ SQL NULL (CHECK theo trạng thái lượt
    chạy đòi ``IS NULL``; ``document_gaps`` null = "không có"). Đo hành vi: ``tests/integration/test_gd2b_repository_db.py``."""
    from sqlalchemy.dialects.postgresql import JSONB

    cot = {
        (lop.__tablename__, c.name): c.type.none_as_null
        for lop in LOP
        for c in lop.__table__.columns
        if isinstance(c.type, JSONB) and c.nullable
    }
    assert cot == {
        ("admission_review_run", "summary"): True,
        ("admission_review_run", "quota_view"): True,
        ("admission_review_row", "document_gaps"): True,
    }


def test_cot_khoa_ngoai_ghep_khong_cho_null():
    """``MATCH SIMPLE`` bỏ qua khoá ngoại ghép khi có cột NULL (F257) ⇒ mọi cột của khoá ngoại GHÉP (lần xét → đợt / bảng chỉ tiêu,
    sàn → lần xét / học vụ) phải NOT NULL — không thì "sàn đúng năm của học vụ" lọt khi một cột trống."""
    ghep = 0
    for lop in LOP:
        for fk in lop.__table__.foreign_key_constraints:
            if len(fk.columns) < 2:
                continue
            ghep += 1
            for cot in fk.columns:
                assert not cot.nullable, (lop.__tablename__, fk.name, cot.name)
    assert ghep == 3


def test_dot_tuyen_sinh_co_unique_id_nam():
    """§4.1: đích của khoá ngoại ghép (đợt, năm) có ở model và được migration thêm vào bảng có sẵn."""
    c = _rang_buoc_model()["uq_offering_admission_round_id_year"]
    assert [col.name for col in c.columns] == ["id", "academic_year"]
    assert _mig().ADD_ROUND_UNIQUE == (
        "ALTER TABLE offering_admission_round ADD CONSTRAINT uq_offering_admission_round_id_year UNIQUE (id, academic_year)"
    )


# ── Chuỗi Alembic, khoá bảng, hạ cấp fail-closed ───────────────────────────────────────────────────────────────────────
def test_migration_noi_ngay_sau_gd2f():
    mod = _mig()
    assert (mod.revision, mod.down_revision) == ("gd2b20261121", "gd2f20261119")


def test_mot_head_alembic_va_gd2b_tren_chuoi_toi_head():
    """ĐÚNG một head (đọc cả ``down_revision`` dạng bộ); ``gd2b20261121`` là head hoặc tổ tiên của head (không ghim head = revision
    cuối — review max PR #724 R15). N4 / migration khác nối cùng chỗ ⇒ hai head ⇒ đỏ."""
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
    assert "gd2b20261121" in revs and ("gd2b20261121" in heads or "gd2b20261121" in downs)


def test_nang_cap_mot_cau_do_lock_timeout_truoc_moi_khoa():
    sql = _mig()._upgrade_sql()
    assert sql.count("DO $gd2b$") == 1
    vt_timeout = sql.index("set_config('lock_timeout', '10s', true)")
    vt_lock = sql.index("LOCK TABLE")
    vt_ddl = sql.index("ALTER TABLE offering_admission_round")
    assert vt_timeout < vt_lock < vt_ddl


def test_khoa_bang_co_san_theo_thu_tu_co_dinh_va_du_bang():
    """Mọi bảng CÓ SẴN mà nâng cấp chạm (đích ``REFERENCES`` + bảng bị ``ALTER``) đều bị ``LOCK TABLE`` TRƯỚC, đúng thứ tự cố định;
    bảng bị ``ALTER … ADD CONSTRAINT`` khoá ngay ở ACCESS EXCLUSIVE (không nâng khoá giữa chừng)."""
    mod = _mig()
    sql = mod._upgrade_sql()
    khoa = re.findall(r"LOCK TABLE (\S+) IN ([A-Z ]+) MODE", sql)
    assert khoa == [
        ('"user"', "SHARE ROW EXCLUSIVE"),
        ("offering_admission_round", "ACCESS EXCLUSIVE"),
        ("offering_academic_info", "SHARE ROW EXCLUSIVE"),
        ("admission_quota_table", "SHARE ROW EXCLUSIVE"),
    ]
    dich = set(re.findall(r"REFERENCES (\"?\w+\"?) \(", " ".join(mod.CREATE_TABLES))) - set(BANG)
    assert dich | {"offering_admission_round"} == {t for t, _ in khoa}


def test_ha_cap_khoa_cung_thu_tu_roi_moi_dem():
    sql = _mig()._downgrade_sql()
    khoa = re.findall(r"LOCK TABLE (.+?) IN ([A-Z ]+) MODE", sql)
    assert khoa[:4] == [(t, md) for t, md in _mig().LOCKS]
    assert khoa[4] == ("admission_review_session, admission_review_floor, admission_review_run, admission_review_row",
                       "ACCESS EXCLUSIVE")
    assert sql.index("LOCK TABLE admission_review_session") < sql.index("SELECT (SELECT count(*)") < sql.index("DROP TABLE")
    for bang in BANG:
        assert "(SELECT count(*) FROM %s)" % bang in sql


def test_co_ha_cap_mang_nghia_cho_phep_dung_chu_1():
    """Cờ tên ``*_ENABLED`` (CHO PHÉP, mặc định tắt); chỉ ĐÚNG chữ ``1`` mới bật (hành vi đo ở ``test_gd2b_migration.py``)."""
    mod = _mig()
    assert mod.DROP_DATA_ENABLED_ENV == "GD2B_DOWNGRADE_DROP_DATA_ENABLED"
    nguon = _MIGRATION.read_text(encoding="utf-8")
    assert 'os.environ.get(DROP_DATA_ENABLED_ENV) == "1"' in nguon
    sql = mod._downgrade_sql()
    assert "current_setting('gd2b.allow_drop_data', true) IS DISTINCT FROM '1'" in sql
    assert "USING ERRCODE = 'QLC12'" in sql and mod.SQLSTATE_DOWNGRADE_DATA_PRESENT == "QLC12"
