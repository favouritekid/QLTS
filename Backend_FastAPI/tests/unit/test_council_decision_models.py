# -*- coding: utf-8 -*-
"""Lượt I (F230) — model ↔ migration ``hdts20261107`` của ghi nhận Quyết định đã ký: khoá các chỗ phải
TRÙNG nhau (CSDL test dựng bằng ``create_all()`` đọc model; production dựng bằng migration). Không CSDL.

Đặc tả: ``ma-gd1/DAC-TA-TRIEN-KHAI-F230-2026-11-07.md`` mục 1 (+ mục 8). Ràng buộc chạy THẬT trên CSDL ở
``tests/integration/test_council_decision_constraints_db.py``.
"""
import importlib.util
import re
from pathlib import Path

import pytest

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.constants import SYSTEM_CONSULTATION_METHOD
from app.models import council_document as m

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
VERS = GOC / "alembic" / "versions"
TEP = VERS / "hdts20261107_council_decision.py"

LOP_MOI = (
    m.CouncilDocumentSetRow,
    m.CouncilDecision,
    m.CouncilDecisionRow,
    m.CouncilDecisionScan,
    m.CouncilDecisionHold,
    m.CouncilDocumentEvent,
)


def _nap(tep, ten):
    spec = importlib.util.spec_from_file_location(ten, VERS / tep)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _nap("hdts20261107_council_decision.py", "hdts20261107_unit")


def test_moi_chuoi_check_va_dieu_kien_chi_muc_bang_nhau_model_migration():
    ten = [
        t
        for t in vars(MIG)
        if t.startswith(("CHECK_", "DIEU_KIEN_")) and isinstance(getattr(MIG, t), str)
    ]
    assert len(ten) >= 40, "phép đo rỗng: %d hằng" % len(ten)
    for t in ten:
        assert getattr(MIG, t) == getattr(m, t), t
    assert MIG.LOAI_SU_KIEN == m.LOAI_SU_KIEN
    assert MIG.LY_DO_TOI_DA == m.LY_DO_XOA_TOI_DA


def _ten_rang_buoc(lop):
    return {
        c.name
        for c in lop.__table__.constraints
        if c.name and not c.name.endswith("_pkey")
    }


def test_ten_rang_buoc_co_ten_cua_model_dung_bang_migration():
    nguon = TEP.read_text(encoding="utf-8")
    trong_mig = set(re.findall(r'name="((?:ck|uq|fk)_council_[a-z0-9_]+)"', nguon))
    trong_mig |= set(re.findall(r'\("(ck_council_document_set_[a-z_]+)", CHECK_', nguon))
    o_model = set()
    for lop in LOP_MOI:
        o_model |= _ten_rang_buoc(lop)
    o_model |= {
        c.name
        for c in m.CouncilDocumentSet.__table__.constraints
        if c.name
        in (
            "ck_council_document_set_ban_ky_du",
            "ck_council_document_set_dung_lai_ban_ky",
            "ck_council_document_set_mot_che_do",
            "ck_council_document_set_so_ban_ky",
        )
    }
    assert len(o_model) >= 45, "phép đo rỗng"
    assert o_model <= trong_mig, sorted(o_model - trong_mig)


def test_ten_chi_muc_cua_model_dung_bang_migration():
    nguon = TEP.read_text(encoding="utf-8")
    o_model = set()
    for lop in LOP_MOI:
        o_model |= {i.name for i in lop.__table__.indexes}
    for cot in ("dung_lai_tu_set_id", "cho_quyet_dinh_goc_id"):
        o_model.add("ix_council_document_set_%s" % cot)
    trong_mig = set(
        re.findall(r'op\.create_index\(\s*"((?:ix|uq)_council_[a-z0-9_]+)"', nguon)
    ) | {
        "ix_council_document_set_row_%s" % c for c in ("set_id", "profile_id")
    } | {"ix_council_decision_%s" % c for c in ("set_id", "goc_id", "huy_qd_id")} | {
        "ix_council_decision_row_%s" % c
        for c in ("decision_id", "profile_id", "bi_bo_boi_id")
    } | {"ix_council_decision_hold_%s" % c for c in ("profile_id", "van_ban_huy_id")} | {
        "ix_council_document_event_%s" % c for c in ("set_id", "decision_id", "luc")
    } | {
        "ix_council_document_set_dung_lai_tu_set_id",
        "ix_council_document_set_cho_quyet_dinh_goc_id",
    }
    assert o_model == trong_mig, (sorted(o_model - trong_mig), sorted(trong_mig - o_model))


def test_ba_migration_hoi_dong_cung_tran_cho_khoa():
    a = _nap("hdts20261103_council_document_tables.py", "hdts20261103_i")
    b = _nap("hdts20261104_council_document_audit.py", "hdts20261104_i")
    assert a.TRAN_CHO_KHOA == b.TRAN_CHO_KHOA == MIG.TRAN_CHO_KHOA == "10s"
    assert "set_config('lock_timeout', '10s', true)" in MIG._sql_them_cot_bo()
    assert "set_config('lock_timeout', '10s', true)" in MIG._sql_ha_cap(False)


def test_migration_la_head_noi_sau_hdts20261105_va_co_cho_phep_dung_chu():
    cfg = Config(str(GOC / "alembic.ini"))
    cfg.set_main_option("script_location", str(GOC / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_heads() == ["hdts20261107"]
    assert (MIG.revision, MIG.down_revision) == ("hdts20261107", "hdts20261105")
    assert MIG.CO_CHO_PHEP_XOA == "COUNCIL_DECISION_DOWNGRADE_DROP_DATA_ENABLED"
    with pytest.raises(TypeError):
        MIG._sql_ha_cap(1)


def test_khoa_ngoai_ghep_va_hanh_dong_dung_dac_ta():
    fk = {c.name: c for c in m.CouncilDecisionRow.__table__.foreign_key_constraints}
    k2 = fk["fk_council_decision_row_k2"]
    assert [e.target_fullname for e in k2.elements] == [
        "council_decision.id",
        "council_decision.trang_thai",
    ]
    assert k2.onupdate == "CASCADE" and k2.ondelete is None
    db = fk["fk_council_decision_row_dong_bo"]
    assert db.ondelete == "SET NULL (set_row_id)" and db.onupdate == "CASCADE"
    assert [e.target_fullname for e in db.elements] == [
        "council_document_set_row.id",
        "council_document_set_row.set_id",
        "council_document_set_row.profile_id",
    ]
    assert fk["fk_council_decision_row_bo"].onupdate == "CASCADE"
    k6 = {c.name: c for c in m.CouncilDecision.__table__.foreign_key_constraints}[
        "fk_council_decision_k6"
    ]
    assert [e.target_fullname for e in k6.elements] == [
        "council_decision.id",
        "council_decision.huy_qd_id",
    ]
    bo = next(iter(m.CouncilDecision.__table__.c.set_id.foreign_keys))
    assert bo.ondelete == "SET NULL"  # K4: SET NULL + CHECK, không RESTRICT (đặc tả 1.8)
    hs = next(iter(m.CouncilDocumentSetRow.__table__.c.profile_id.foreign_keys))
    assert hs.ondelete == "SET NULL"
    # Bảng sự kiện ĐỘC LẬP: không khoá ngoại nào.
    assert not m.CouncilDocumentEvent.__table__.foreign_keys
    assert "ForeignKey" not in re.search(
        r"op\.create_table\(\n        SU_KIEN,(.*?)if_not_exists=True", TEP.read_text(encoding="utf-8"), re.S
    ).group(1)


def test_bieu_thuc_mot_nguon_cho_dong_hieu_luc_va_dau_appsheet():
    assert m.DIEU_KIEN_DONG_HIEU_LUC in m.SQL_COT_TINH_TRANG_QD
    assert m.DIEU_KIEN_DONG_GIU_HO_SO in m.SQL_COT_TINH_TRANG_QD
    assert m.SQL_DAU_APPSHEET in m.SQL_COT_TINH_TRANG_QD
    u3 = [
        i
        for i in m.CouncilDecisionRow.__table__.indexes
        if i.name == "uq_council_decision_row_u3_ho_so"
    ][0]
    assert str(u3.dialect_options["postgresql"]["where"]) == m.DIEU_KIEN_DONG_HIEU_LUC
    assert m.DAU_APPSHEET_TIEN_TO == "Đã trúng tuyển theo QĐ số "
    assert ("LIKE '%s%%'" % m.DAU_APPSHEET_TIEN_TO) in m.SQL_DAU_APPSHEET
    assert ("method = '%s'" % SYSTEM_CONSULTATION_METHOD) in m.SQL_DAU_APPSHEET
    assert "deleted_at" not in m.SQL_DAU_APPSHEET  # fail-closed: không lọc lần tư vấn đã xoá


def test_cot_bytes_scan_deferred():
    assert m.CouncilDecisionScan.__mapper__.attrs["noi_dung"].deferred


def test_ma_loi_csdl_chi_doc_thuoc_tinh_khong_doc_chu():
    # ``ma_loi_csdl`` đứng trong ``_S6_HAM_BOC`` (test_che_log_pii) ⇒ phải CHỈ đọc thuộc tính (SQLSTATE, tên
    # ràng buộc), không bao giờ ``str``/``args`` — chữ lỗi CSDL có thể mang tham số câu lệnh (CCCD giả ở đây).
    from app.repositories.council_decision_repository import ma_loi_csdl

    class Goc(Exception):
        sqlstate = "23505"
        constraint_name = "uq_council_decision_u1_so"

        def __str__(self):
            return "DETAIL: Key (so)=(099999000E99) CANARY"

    class Boc(Exception):
        def __init__(self):
            super().__init__("CANARY 099999000E99 boc")
            self.orig = Goc()

    kq = ma_loi_csdl(Boc())
    assert kq == ("23505", "uq_council_decision_u1_so")
    assert "CANARY" not in repr(kq) and "099999000E99" not in repr(kq)
