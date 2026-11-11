# -*- coding: utf-8 -*-
"""Lượt gửi ghi nhận — model ``CouncilDecisionSubmission`` (bản cho ``create_all()`` của CSDL test) và migration
``hdts20261112`` (bản thật) phải cùng CHECK / chỉ mục / khoá ngoại. So chuỗi sau khi chuẩn hoá khoảng trắng."""
import re
from pathlib import Path

import pytest

from app.models import council_document as m

pytestmark = pytest.mark.unit

_MIG = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "hdts20261112_luot_gui_ghi_nhan.py"


def _chuan(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_moi_check_cua_model_co_trong_migration():
    van = _chuan(_MIG.read_text(encoding="utf-8"))
    bang = m.CouncilDecisionSubmission.__table__
    check = [c for c in bang.constraints if c.__class__.__name__ == "CheckConstraint"]
    assert len(check) == 7
    for c in check:
        assert "CONSTRAINT %s CHECK (%s)" % (c.name, _chuan(str(c.sqltext))) in van, c.name


def test_chi_muc_va_khoa_ngoai_trung_ten():
    van = _MIG.read_text(encoding="utf-8")
    bang = m.CouncilDecisionSubmission.__table__
    for i in bang.indexes:
        assert i.name in van, i.name
    cho = [i for i in bang.indexes if i.name == "uq_council_decision_submission_cho_gui"][0]
    assert cho.unique and str(cho.dialect_options["postgresql"]["where"]) == m.DIEU_KIEN_LUOT_CHO_GUI
    assert "WHERE %s" % m.DIEU_KIEN_LUOT_CHO_GUI in van
    fk = {f.name: f for f in bang.foreign_key_constraints}
    assert fk["fk_council_decision_submission_set"].ondelete == "SET NULL"
    assert "REFERENCES council_document_set (id) ON DELETE SET NULL" in van
    for ten in fk:
        assert ten in van, ten
    for ten in ("uq_council_decision_submission_ma", "uq_council_decision_submission_decision"):
        assert ten in van


def test_danh_sach_ky_vong_trong_migration_trung_model():
    # Bước KIỂM HÌNH của migration (đọc tên kỳ vọng) phải trùng ĐÚNG ràng buộc / chỉ mục của model — một nguồn nghĩa.
    import importlib.util

    spec = importlib.util.spec_from_file_location("hdts20261112_kiem", _MIG)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    bang = m.CouncilDecisionSubmission.__table__
    rb_model = {c.name for c in bang.constraints if c.name} | {"council_decision_submission_pkey"}
    assert set(mig.RANG_BUOC_KY_VONG) == rb_model, (set(mig.RANG_BUOC_KY_VONG) ^ rb_model)
    assert set(mig.CHI_MUC_KY_VONG) == {i.name for i in bang.indexes}
    assert len(mig.RANG_BUOC_KY_VONG) == len(set(mig.RANG_BUOC_KY_VONG)) == 13
