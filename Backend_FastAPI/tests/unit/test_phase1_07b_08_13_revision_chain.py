"""Unit tests for #184 Wave 1 PR-1D migrations
(``phase1_07b_create_backfill_exceptions_table`` +
``phase1_08_add_uses_choice_engine_flag_to_profile`` +
``phase1_13_create_system_config_table``).

Pure-text contract tests — locks the revision chain, the upgrade
SQL surface, the seed semantics, the FK/index shapes, and the
ORM model parity. A regression in any surface fails CI before the
migration runs against a real DB.

What lives here:
1. Revision row + linear chain (phase1_06 → phase1_07b → phase1_08
   → phase1_13).
2. phase1_07b ``_admission_backfill_exceptions`` table contract.
3. phase1_08 ``uses_choice_engine`` boolean NOT NULL DEFAULT false.
4. phase1_13 ``system_config`` table + ``current_intake_year`` seed.
5. ORM model parity (AdmissionProfile.uses_choice_engine + SystemConfig).

What does NOT live here:
* End-to-end DDL apply — alembic upgrade smoke runs in dev container.
* SystemConfigService admin-only guard — see
  ``test_system_config_service_admin_only.py``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_07B = _VERSIONS_DIR / "phase1_07b_create_backfill_exceptions_table.py"
_PHASE1_08 = _VERSIONS_DIR / "phase1_08_add_uses_choice_engine_flag_to_profile.py"
_PHASE1_13 = _VERSIONS_DIR / "phase1_13_create_system_config_table.py"


def _load_migration(filename: str):
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_07b():
    return _load_migration(_PHASE1_07B.name)


@pytest.fixture
def phase1_08():
    return _load_migration(_PHASE1_08.name)


@pytest.fixture
def phase1_13():
    return _load_migration(_PHASE1_13.name)


# ---------------------------------------------------------------------------
# 1. Revision row + linear chain
# ---------------------------------------------------------------------------


def test_phase1_07b_chains_off_phase1_06(phase1_07b) -> None:
    assert phase1_07b.revision == "phase1_07b"
    assert phase1_07b.down_revision == "phase1_06"


def test_phase1_08_chains_off_phase1_07b(phase1_08) -> None:
    assert phase1_08.revision == "phase1_08"
    assert phase1_08.down_revision == "phase1_07b"


def test_phase1_13_chains_off_phase1_08(phase1_13) -> None:
    """phase1_09/10/11/12/14-19a slots reserved for Wave 2-5;
    phase1_13 ships now in Wave 1 chain."""
    assert phase1_13.revision == "phase1_13"
    assert phase1_13.down_revision == "phase1_08"


# ---------------------------------------------------------------------------
# 2. phase1_07b backfill_exceptions contract
# ---------------------------------------------------------------------------


def test_phase1_07b_creates_audit_table_with_underscore_prefix() -> None:
    """Leading underscore signals "internal table, not a domain
    entity"; the admin queue UI reads directly without a service."""
    src = _PHASE1_07B.read_text(encoding="utf-8")
    assert '"_admission_backfill_exceptions"' in src


def test_phase1_07b_declares_unique_profile_type_constraint() -> None:
    """UNIQUE(profile_id, exception_type) chặn duplicate rows
    cho cùng caller across re-runs."""
    src = _PHASE1_07B.read_text(encoding="utf-8")
    assert "uq_admission_backfill_exceptions_profile_type" in src
    assert "UniqueConstraint" in src


def test_phase1_07b_creates_open_partial_index() -> None:
    """Partial index ``WHERE resolved_at IS NULL`` — admin queue
    only loads unresolved rows; closed set grows much faster."""
    src = _PHASE1_07B.read_text(encoding="utf-8")
    assert "ix_admission_backfill_exceptions_open" in src
    assert "resolved_at IS NULL" in src
    assert "postgresql_where" in src


def test_phase1_07b_profile_fk_cascades_on_profile_delete() -> None:
    """ON DELETE CASCADE — orphan exception rows when profile is
    hard-deleted (auditing should NOT keep references to deleted PII)."""
    src = _PHASE1_07B.read_text(encoding="utf-8")
    # The ForeignKey for profile_id uses CASCADE.
    assert 'ondelete="CASCADE"' in src


# ---------------------------------------------------------------------------
# 3. phase1_08 uses_choice_engine contract
# ---------------------------------------------------------------------------


def test_phase1_08_adds_uses_choice_engine_with_server_default_false() -> None:
    """Server default backfills every existing row to false at
    ALTER time — PG fast path; no row-by-row UPDATE."""
    src = _PHASE1_08.read_text(encoding="utf-8")
    assert '"uses_choice_engine"' in src
    assert "nullable=False" in src
    # Server default literal "false" so every legacy row gets the
    # legacy single-NV semantic.
    assert 'server_default=sa.text("false")' in src


def test_phase1_08_no_op_execute() -> None:
    """Pure additive — no UPDATE/INSERT statements; default does
    the backfill."""
    src = _PHASE1_08.read_text(encoding="utf-8")
    assert "op.execute(" not in src


# ---------------------------------------------------------------------------
# 4. phase1_13 system_config + seed
# ---------------------------------------------------------------------------


def test_phase1_13_creates_system_config_table() -> None:
    src = _PHASE1_13.read_text(encoding="utf-8")
    assert '"system_config"' in src
    # ``key`` text PK chosen instead of integer PK.
    assert "primary_key=True" in src
    assert "JSONB()" in src


def test_phase1_13_seeds_current_intake_year_2026() -> None:
    """B4 P0 closer — seeded value is the FE storefront default
    + admin Phase 3 wizard default."""
    src = _PHASE1_13.read_text(encoding="utf-8")
    assert "current_intake_year" in src
    assert "'2026'::jsonb" in src
    assert "ON CONFLICT (key) DO NOTHING" in src


def test_phase1_13_updated_by_user_id_set_null_on_user_delete() -> None:
    """SET NULL — audit row survives even when the editor user is
    deleted."""
    src = _PHASE1_13.read_text(encoding="utf-8")
    assert 'ondelete="SET NULL"' in src


# ---------------------------------------------------------------------------
# 5. ORM model parity
# ---------------------------------------------------------------------------


def test_admission_profile_model_declares_uses_choice_engine() -> None:
    from app.models.admission import AdmissionProfile

    assert hasattr(AdmissionProfile, "uses_choice_engine")
    column = AdmissionProfile.__table__.columns["uses_choice_engine"]
    assert column.nullable is False
    # Default is False — backfill semantic.
    assert "BOOL" in type(column.type).__name__.upper()


def test_system_config_model_imports_cleanly() -> None:
    from app.models import SystemConfig
    from app.models.system_config import SystemConfig as DirectSystemConfig

    # Module-level export + direct import both reach the same class.
    assert SystemConfig is DirectSystemConfig
    # Table name matches migration.
    assert SystemConfig.__tablename__ == "system_config"


def test_system_config_pk_is_key_text() -> None:
    from app.models.system_config import SystemConfig

    pk_columns = [c for c in SystemConfig.__table__.columns if c.primary_key]
    assert len(pk_columns) == 1
    assert pk_columns[0].name == "key"
    assert "TEXT" in type(pk_columns[0].type).__name__.upper()


# ---------------------------------------------------------------------------
# 6. Sanity — all three migrations import cleanly
# ---------------------------------------------------------------------------


def test_all_three_migrations_define_upgrade_and_downgrade(
    phase1_07b, phase1_08, phase1_13
) -> None:
    for module in (phase1_07b, phase1_08, phase1_13):
        assert callable(getattr(module, "upgrade", None))
        assert callable(getattr(module, "downgrade", None))
