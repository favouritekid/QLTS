# -*- coding: utf-8 -*-
"""Model + migration của kho mẫu / bộ văn bản Hội đồng — khoá các chỗ phải TRÙNG nhau.

CSDL test dựng bằng ``create_all()`` (đọc model), production dựng bằng migration
``hdts20261103``: chuỗi CHECK và tên ràng buộc khai hai nơi ⇒ test này so hai bên (không cần
CSDL). Phép so lược đồ thật (cột · ràng buộc · chỉ mục) giữa CSDL dựng bằng migration và CSDL
dựng bằng ``create_all`` chạy ngoài CI, ghi ở báo cáo lượt E1.
"""
import importlib.util
import re
from pathlib import Path

import pytest

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.models import council_document as m
from app.services import council_document_render_service as bo_dung
from app.services import council_document_template_service as kho_mau

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
TEP_MIGRATION = GOC / "alembic" / "versions" / "hdts20261103_council_document_tables.py"


def _migration():
    spec = importlib.util.spec_from_file_location("hdts20261103", TEP_MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ba_loai_mau_trung_nhau_o_moi_noi():
    assert m.LOAI_MAU_HOI_DONG == bo_dung.LOAI_MAU == tuple(kho_mau.TEN_LOAI)
    assert set(re.findall(r"'([a-z_]+)'", m.CHECK_LOAI_MAU)) == set(bo_dung.LOAI_MAU)


def test_chuoi_check_cua_model_va_migration_bang_nhau():
    mig = _migration()
    for ten in (
        "CHECK_LOAI_MAU",
        "CHECK_SHA_NOI_DUNG",
        "CHECK_KICH_THUOC",
        "CHECK_MANG_MA",
        "CHECK_MANG_DTO",
    ):
        assert getattr(mig, ten) == getattr(m, ten), ten


def _ten_rang_buoc_model(lop):
    return {
        c.name
        for c in lop.__table__.constraints
        if c.name and not c.name.endswith("_pkey")
    }


def test_ten_rang_buoc_cua_model_co_du_trong_migration():
    nguon = TEP_MIGRATION.read_text(encoding="utf-8")
    trong_mig = set(
        re.findall(r'name="((?:ck|uq)_council_document_[a-z0-9_]+)"', nguon)
    )
    o_model = set()
    for lop in (
        m.CouncilDocumentTemplate,
        m.CouncilDocumentSet,
        m.CouncilDocumentSetFile,
    ):
        o_model |= {
            n for n in _ten_rang_buoc_model(lop) if n.startswith(("ck_", "uq_"))
        }
    assert o_model == trong_mig and len(o_model) == 15


def test_cot_bytes_va_pii_la_deferred():
    for lop, cot in (
        (m.CouncilDocumentTemplate, "noi_dung"),
        (m.CouncilDocumentSetFile, "noi_dung"),
        (m.CouncilDocumentSet, "ma_ho_so_dau_vao"),
        (m.CouncilDocumentSet, "snapshot_dto"),
    ):
        assert lop.__mapper__.attrs[cot].deferred, (lop.__name__, cot)
    assert not m.CouncilDocumentSet.__mapper__.attrs["thong_tin_dung"].deferred


def test_khoa_ngoai_tep_xoa_theo_bo():
    fk = next(iter(m.CouncilDocumentSetFile.__table__.c.set_id.foreign_keys))
    assert fk.ondelete == "CASCADE" and fk.column.table.name == "council_document_set"
    dv = next(iter(m.CouncilDocumentSet.__table__.c.unit_id.foreign_keys))
    assert dv.ondelete == "SET NULL"  # đơn vị bị xoá ⇒ bộ THU HẸP về chỉ admin


def test_migration_la_head_duy_nhat_noi_tiep_head_cu():
    cfg = Config(str(GOC / "alembic.ini"))
    cfg.set_main_option("script_location", str(GOC / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert heads == ["hdts20261103"]
    mig = _migration()
    assert (mig.revision, mig.down_revision) == ("hdts20261103", "v3circ20261011c")
    assert mig.CO_CHO_PHEP_XOA.endswith("_ENABLED")  # cờ CHO PHÉP, mặc định tắt
