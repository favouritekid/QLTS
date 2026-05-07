"""Unit tests for #184 Wave 1 PR-1C' migrations
(``phase1_05_add_subject_kind_and_score_bounds`` +
``phase1_06_add_path_id_to_document_group``).

Pure-text contract tests — locks the revision chain, the upgrade
SQL surface, the ENUM type values, the seed semantics, the
partial index predicate, and the ORM model parity. A regression
in any surface fails CI before the migration runs against a real
DB.

What lives here:
1. Revision row + linear chain (phase1_03 → phase1_05 → phase1_06).
2. phase1_05 ENUM 4 values + 3 column add + 6 seed rows.
3. phase1_06 FK column + partial index predicate.
4. Subject ORM model declares 3 new fields with correct types.
5. DocumentGroup ORM model declares ``admission_path_id`` FK.

What does NOT live here:
* End-to-end DDL apply — ``alembic upgrade head`` smoke runs in
  the dev container.
* Service invariant for DocumentGroup path FK — see
  ``test_document_group_service_phase1_06_invariant.py``.
* 3-tier resolution rule — see
  ``test_admission_path_resolution_3tier.py``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_05_FILE = _VERSIONS_DIR / "phase1_05_add_subject_kind_and_score_bounds.py"
_PHASE1_06_FILE = _VERSIONS_DIR / "phase1_06_add_path_id_to_document_group.py"


def _load_migration(filename: str):
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_05():
    return _load_migration(_PHASE1_05_FILE.name)


@pytest.fixture
def phase1_06():
    return _load_migration(_PHASE1_06_FILE.name)


# ---------------------------------------------------------------------------
# 1. Revision row + linear chain
# ---------------------------------------------------------------------------


def test_phase1_05_revision_id(phase1_05) -> None:
    assert phase1_05.revision == "phase1_05"


def test_phase1_05_chains_off_phase1_03(phase1_05) -> None:
    """phase1_04 is DEFERRED Q1/2027 (Q9 chốt 2026-05-01) so the
    chain skips it intentionally — phase1_05 → phase1_03 directly.
    """
    assert phase1_05.down_revision == "phase1_03"


def test_phase1_06_revision_id(phase1_06) -> None:
    assert phase1_06.revision == "phase1_06"


def test_phase1_06_chains_off_phase1_05(phase1_06) -> None:
    assert phase1_06.down_revision == "phase1_05"


def test_neither_has_branch_labels(phase1_05, phase1_06) -> None:
    assert phase1_05.branch_labels is None
    assert phase1_06.branch_labels is None


# ---------------------------------------------------------------------------
# 2. phase1_05 ENUM contract
# ---------------------------------------------------------------------------


def test_phase1_05_declares_4_subject_kind_values(phase1_05) -> None:
    """4-value ENUM per PLAN line 733-737. Adding a value = update
    migration + Subject model SUBJECT_KIND_VALUES + downstream
    consumer in lockstep."""
    assert phase1_05.SUBJECT_KIND_VALUES == (
        "ACADEMIC_SUBJECT",
        "TERM_AVERAGE",
        "ABILITY_TEST",
        "CERTIFICATE",
    )


def test_phase1_05_creates_subject_kind_enum() -> None:
    src = _PHASE1_05_FILE.read_text(encoding="utf-8")
    assert 'name="subject_kind"' in src
    assert ".create(op.get_bind(), checkfirst=True)" in src


def test_phase1_05_drops_subject_kind_enum_in_downgrade() -> None:
    src = _PHASE1_05_FILE.read_text(encoding="utf-8")
    assert ".drop(op.get_bind(), checkfirst=True)" in src


# ---------------------------------------------------------------------------
# 3. phase1_05 column add contract
# ---------------------------------------------------------------------------


def test_phase1_05_adds_subject_kind_with_server_default() -> None:
    """Server default backfills every existing row at ALTER time
    (no row-by-row UPDATE). NOT NULL post-migration so the scoring
    engine never has to handle NULL kind."""
    src = _PHASE1_05_FILE.read_text(encoding="utf-8")
    assert '"subject_kind"' in src
    # Server default cast clause locks the type-aware backfill
    # so a future careless edit can't drop the cast.
    assert "'ACADEMIC_SUBJECT'::subject_kind" in src
    assert "nullable=False" in src


def test_phase1_05_adds_max_and_min_possible_score_nullable() -> None:
    src = _PHASE1_05_FILE.read_text(encoding="utf-8")
    assert '"max_score"' in src
    assert '"min_possible_score"' in src
    # Both are Numeric(precision=6, scale=2) and nullable.
    assert "Numeric(precision=6, scale=2)" in src


# ---------------------------------------------------------------------------
# 4. phase1_05 seed contract
# ---------------------------------------------------------------------------


def test_phase1_05_seeds_6_virtual_subjects() -> None:
    """Six virtual subjects per PLAN line 745 + 4174-4181. ON
    CONFLICT (code) DO NOTHING keeps the seed idempotent."""
    src = _PHASE1_05_FILE.read_text(encoding="utf-8")
    for code in (
        "TB_HK1_L12",
        "TB_HK2_L12",
        "TB_CN_L12",
        "DGNL_DHQGHN",
        "V_ACT",
        "IELTS",
    ):
        assert f"'{code}'" in src, f"seed row missing: {code}"

    assert "ON CONFLICT (code) DO NOTHING" in src


def test_phase1_05_downgrade_deletes_seeded_rows_before_dropping_enum() -> None:
    """Inverse order — DELETE rows BEFORE dropping the enum, else
    PG errors on type-still-in-use."""
    src = _PHASE1_05_FILE.read_text(encoding="utf-8")
    delete_pos = src.index("DELETE FROM subject")
    drop_enum_pos = src.index(".drop(op.get_bind(), checkfirst=True)")
    assert delete_pos < drop_enum_pos


# ---------------------------------------------------------------------------
# 5. phase1_06 FK + partial index contract
# ---------------------------------------------------------------------------


def test_phase1_06_adds_admission_path_id_fk() -> None:
    src = _PHASE1_06_FILE.read_text(encoding="utf-8")
    assert '"admission_path_id"' in src
    assert "create_foreign_key" in src
    assert '"fk_document_group_admission_path"' in src
    # ON DELETE SET NULL — deleting a path doesn't cascade-kill its
    # document groups; they fall back to the lower tiers.
    assert 'ondelete="SET NULL"' in src


def test_phase1_06_creates_partial_index_with_correct_predicate() -> None:
    """Partial index on admission_path_id WHERE NOT NULL keeps the
    index small (most rows are legacy = NULL); tier-1 query
    ``WHERE admission_path_id = X`` is the only consumer."""
    src = _PHASE1_06_FILE.read_text(encoding="utf-8")
    assert '"ix_doc_group_path"' in src
    assert "admission_path_id IS NOT NULL" in src
    assert "postgresql_where" in src


def test_phase1_06_downgrade_drops_index_then_fk_then_column() -> None:
    src = _PHASE1_06_FILE.read_text(encoding="utf-8")
    drop_idx = src.index('drop_index("ix_doc_group_path"')
    drop_fk = src.index('drop_constraint(\n        "fk_document_group_admission_path"')
    drop_col = src.index('drop_column("document_group", "admission_path_id")')
    assert drop_idx < drop_fk < drop_col


# ---------------------------------------------------------------------------
# 6. ORM model parity
# ---------------------------------------------------------------------------


def test_subject_model_declares_subject_kind() -> None:
    from app.models.admission_config.subject import Subject, SUBJECT_KIND_VALUES

    assert hasattr(Subject, "subject_kind")
    column = Subject.__table__.columns["subject_kind"]
    assert column.nullable is False
    # 4 enum values mirror the migration constant.
    assert SUBJECT_KIND_VALUES == (
        "ACADEMIC_SUBJECT",
        "TERM_AVERAGE",
        "ABILITY_TEST",
        "CERTIFICATE",
    )


def test_subject_model_declares_score_bounds() -> None:
    from app.models.admission_config.subject import Subject

    assert hasattr(Subject, "max_score")
    assert hasattr(Subject, "min_possible_score")
    max_col = Subject.__table__.columns["max_score"]
    min_col = Subject.__table__.columns["min_possible_score"]
    assert max_col.nullable is True
    assert min_col.nullable is True
    # Numeric(6, 2) — precision 6 / scale 2 (e.g. 1200.00 fits).
    assert "NUMERIC" in type(max_col.type).__name__.upper()


def test_document_group_model_declares_admission_path_id() -> None:
    from app.models.admission_config.document_group import DocumentGroup

    assert hasattr(DocumentGroup, "admission_path_id")
    column = DocumentGroup.__table__.columns["admission_path_id"]
    assert column.nullable is True
    assert column.foreign_keys, "admission_path_id must declare an FK"
    fk = next(iter(column.foreign_keys))
    assert fk.column.table.name == "admission_path"
    assert fk.column.name == "id"


# ---------------------------------------------------------------------------
# 7. Sanity — both migrations import cleanly
# ---------------------------------------------------------------------------


def test_both_migrations_define_upgrade_and_downgrade(phase1_05, phase1_06) -> None:
    for module in (phase1_05, phase1_06):
        assert callable(getattr(module, "upgrade", None))
        assert callable(getattr(module, "downgrade", None))
