"""PR #13 — coverage for graduation_proof migration (gpkind01).

Source-level lock-in (same rationale as ``test_ardockeys01`` /
``test_m_p0b``): the test DB is built with ``Base.metadata.create_all``
(no alembic — memory ``test-db-schema-source``), so structural behaviour
is verified by the alembic CLI roundtrip on the dev DB (upgrade → cols +
constraints + label present → downgrade → cols dropped + label reverted).
These tests pin the migration source against silent drift.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "gpkind01_add_graduation_proof_to_profile_document.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gpkind01_migration", str(MIGRATION_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _section(start: str, end: str | None) -> str:
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    s = src.index(start)
    e = len(src) if end is None else src.index(end)
    return src[s:e]


def test_revision_chain():
    mod = _load()
    assert mod.revision == "gpkind01"
    assert mod.down_revision == "ardockeys01"


def test_label_constants():
    """Label mới gộp cả 2 loại giấy; revert về tên cũ ở downgrade."""
    mod = _load()
    assert mod.GRAD_DOC_CODE == "bang_tot_nghiep_thpt"
    assert "Giấy CN tốt nghiệp tạm thời" in mod.NEW_LABEL
    assert mod.OLD_LABEL == "Bằng tốt nghiệp THPT"


def test_upgrade_adds_columns_constraints_and_label():
    up = _section("def upgrade", "def downgrade")
    # 2 cột mới
    assert up.count("add_column") == 2
    assert "graduation_proof_kind" in up
    assert "supplement_due_date" in up
    # 2 CHECK constraint
    assert "ck_graduation_proof_kind" in up
    assert "ck_supplement_due_only_provisional" in up
    assert "official_diploma" in up and "provisional_cert" in up
    assert "supplement_due_date IS NULL" in up
    # data migration đổi label doc type (idempotent theo code)
    assert "config_document_type" in up
    assert "WHERE code = :code" in up


def test_downgrade_drops_columns_constraints_and_reverts_label():
    down = _section("def downgrade", None)
    assert down.count("drop_column") == 2
    assert "graduation_proof_kind" in down
    assert "supplement_due_date" in down
    assert down.count("drop_constraint") == 2
    # revert label về tên cũ
    assert "config_document_type" in down
    assert "OLD_LABEL" in down or "Bằng tốt nghiệp THPT" in down
