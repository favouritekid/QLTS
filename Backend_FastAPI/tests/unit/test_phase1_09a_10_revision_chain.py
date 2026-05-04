"""Unit tests for #184 Wave 2 PR-2A migrations
(``phase1_09a_add_eligibility_scalars_and_backfill`` +
``phase1_10_create_status_history_table_and_backfill``).

Pure-text contract tests — locks the revision chain, ENUM values,
column additions, backfill SQL contract, status_history table
shape, scattered scalar audit migrate, and ORM model parity.

What lives here:
1. Revision chain (phase1_13 → phase1_09a → phase1_10).
2. phase1_09a: 4 column add (gpa/conduct/health/grad_year),
   conduct_grade ENUM 3 values, backfill scope locked to
   gpa + grad_year, exception sink for out-of-range +
   missing-after-backfill.
3. phase1_10: status_history table + 3 ENUMs (legacy/actor_actual/
   effective) + CHECK actor consistency + 6 backfill blocks
   (initial + 5 scattered scalar).
4. ORM model parity: AdmissionProfile 4 new columns +
   AdmissionProfileStatusHistory module-level export.

What does NOT live here:
* End-to-end DDL apply — alembic upgrade smoke runs in dev container.
* Backfill correctness on real data — covered by manual roundtrip
  on dev DB pre-merge.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_09A = _VERSIONS_DIR / "phase1_09a_add_eligibility_scalars_and_backfill.py"
_PHASE1_10 = _VERSIONS_DIR / "phase1_10_create_status_history_table_and_backfill.py"


def _load_migration(filename: str):
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_09a():
    return _load_migration(_PHASE1_09A.name)


@pytest.fixture
def phase1_10():
    return _load_migration(_PHASE1_10.name)


# ---------------------------------------------------------------------------
# 1. Revision chain
# ---------------------------------------------------------------------------


def test_phase1_09a_chains_off_phase1_13(phase1_09a) -> None:
    assert phase1_09a.revision == "phase1_09a"
    assert phase1_09a.down_revision == "phase1_13"


def test_phase1_10_chains_off_phase1_09a(phase1_10) -> None:
    assert phase1_10.revision == "phase1_10"
    assert phase1_10.down_revision == "phase1_09a"


# ---------------------------------------------------------------------------
# 2. phase1_09a contract
# ---------------------------------------------------------------------------


def test_phase1_09a_declares_3_conduct_grade_values(phase1_09a) -> None:
    """conduct_grade ENUM per PLAN line 818. Adding a value =
    update migration + Subject model + downstream consumer."""
    assert phase1_09a.CONDUCT_GRADE_VALUES == ("TB", "KHA", "TOT")


def test_phase1_09a_adds_4_columns() -> None:
    src = _PHASE1_09A.read_text(encoding="utf-8")
    for col in ("gpa_overall", "conduct", "health_category", "graduation_year"):
        assert f'"{col}"' in src, f"column {col} missing from migration"


def test_phase1_09a_columns_all_nullable() -> None:
    src = _PHASE1_09A.read_text(encoding="utf-8")
    # All 4 columns nullable so backfill can populate selectively.
    # Check at least 4 occurrences of nullable=True (one per add_column).
    assert src.count("nullable=True") >= 4


def test_phase1_09a_backfill_uses_lateral_jsonb() -> None:
    """gpa_overall backfill uses LATERAL jsonb_array_elements +
    WITH ORDINALITY per PLAN line 2718. Anti-pattern (academic_history->-1)
    explicitly rejected per PLAN line 4198."""
    src = _PHASE1_09A.read_text(encoding="utf-8")
    assert "LATERAL jsonb_array_elements" in src
    assert "WITH ORDINALITY" in src


def test_phase1_09a_gpa_backfill_uses_length_bounded_regex() -> None:
    """Length-bounded regex prevents overflow on absurd values
    (e.g. '999999999999' would pass simple format check but
    overflow numeric(8,4))."""
    src = _PHASE1_09A.read_text(encoding="utf-8")
    # Regex is `^[0-9]{1,3}(\\.[0-9]{1,4})?$` (escaped backslash for Python).
    assert "[0-9]{1,3}" in src


def test_phase1_09a_backfill_scope_only_gpa_and_grad_year() -> None:
    """Codex P2 contract — backfill ONLY 2 fields. conduct +
    health_category stay NULL (no JSON source)."""
    src = _PHASE1_09A.read_text(encoding="utf-8")
    # gpa + graduation_year UPDATE blocks present.
    assert "SET gpa_overall = " in src
    assert "SET graduation_year = " in src
    # No UPDATE for conduct or health_category.
    assert "SET conduct = " not in src
    assert "SET health_category = " not in src


def test_phase1_09a_inserts_4_exception_sinks() -> None:
    """4 exception sinks per PLAN line 2746 + 2791 + 2801 + 2815:
    INVALID_GPA_VALUE (out-of-range numeric) +
    MISSING_GPA_OVERALL (NULL after backfill on submitted+) +
    INVALID_GRADUATION_YEAR (year_to outside [1900, 2100]) +
    MISSING_GRADUATION_YEAR (graduation_type set but year_to
    malformed/missing).

    Codex P1 + P2 catches on PR-2A: GPA_OUT_OF_RANGE renamed to
    INVALID_GPA_VALUE per PLAN; 2 graduation_year exception sinks
    added (were missing in initial draft)."""
    src = _PHASE1_09A.read_text(encoding="utf-8")
    for exception_type in (
        "INVALID_GPA_VALUE",
        "MISSING_GPA_OVERALL",
        "INVALID_GRADUATION_YEAR",
        "MISSING_GRADUATION_YEAR",
    ):
        assert f"'{exception_type}'" in src, f"exception sink missing: {exception_type}"
    assert "ON CONFLICT (profile_id, exception_type) DO NOTHING" in src


def test_phase1_09a_graduation_year_range_1900_to_2100() -> None:
    """PLAN line 2795 mandates [1900, 2100] — wider than naive
    [1990, 2030] to allow legitimate older graduations + future-
    dated international transfers. Codex P1 catch on PR-2A."""
    src = _PHASE1_09A.read_text(encoding="utf-8")
    assert "BETWEEN 1900 AND 2100" in src
    # Anti-regression — narrower bounds rejected.
    assert "BETWEEN 1990 AND 2030" not in src


def test_phase1_09a_idempotent_per_row_guard() -> None:
    """All UPDATEs gated by WHERE <field> IS NULL per-row guard
    so re-runs leave valid rows alone."""
    src = _PHASE1_09A.read_text(encoding="utf-8")
    assert "p.gpa_overall IS NULL" in src
    assert "p.graduation_year IS NULL" in src


# ---------------------------------------------------------------------------
# 3. phase1_10 contract
# ---------------------------------------------------------------------------


def test_phase1_10_declares_3_enums(phase1_10) -> None:
    """3 ENUMs per PLAN Phần 2.7: legacy (4 values), actor_actual
    (6 values), effective (4 values)."""
    assert phase1_10.TRANSITION_ROLE_LEGACY_VALUES == (
        "system", "officer", "admin", "candidate",
    )
    assert phase1_10.ACTOR_ACTUAL_ROLE_VALUES == (
        "candidate", "officer", "manager", "accountant", "admin", "system",
    )
    assert phase1_10.EFFECTIVE_TRANSITION_ROLE_VALUES == (
        "candidate", "officer", "admin", "system",
    )


def test_phase1_10_creates_status_history_table() -> None:
    src = _PHASE1_10.read_text(encoding="utf-8")
    assert '"admission_profile_status_history"' in src


def test_phase1_10_check_constraint_actor_consistency() -> None:
    """CHECK constraint per PLAN line 1057-1064 — pin the 3-clause
    actor consistency (system / officer-admin / candidate)."""
    src = _PHASE1_10.read_text(encoding="utf-8")
    assert "ck_status_history_actor_consistency" in src
    # The 3 OR-clauses must all be present.
    assert "transitioned_by_role = 'system'" in src
    assert "transitioned_by_role IN ('officer', 'admin')" in src
    assert "transitioned_by_role = 'candidate'" in src


def test_phase1_10_creates_2_indexes() -> None:
    src = _PHASE1_10.read_text(encoding="utf-8")
    assert "ix_status_history_profile_occurred" in src
    assert "ix_status_history_to_status" in src


def test_phase1_10_backfill_initial_state_block() -> None:
    """Block 0 — 1 row/profile, idempotent via NOT EXISTS."""
    src = _PHASE1_10.read_text(encoding="utf-8")
    assert "phase1_10_initial" in src
    assert "WHERE NOT EXISTS" in src


def test_phase1_10_backfill_5_scattered_scalar_blocks() -> None:
    """5 transition blocks per PLAN line 2997-3038. Each block
    sets metadata.source = 'scattered_scalar_backfill' for
    idempotent re-run."""
    src = _PHASE1_10.read_text(encoding="utf-8")
    for transition in (
        "approved", "rejected", "revision_requested",
        "resubmitted", "overridden",
    ):
        # The backfill block tags the metadata transition value.
        assert f"'transition', '{transition}'" in src, (
            f"scattered scalar backfill block for {transition} missing"
        )

    # All 5 blocks share the source tag.
    assert src.count("scattered_scalar_backfill") >= 5


def test_phase1_10_overridden_block_fallback_admin() -> None:
    """Override transition is admin-only per state machine matrix.
    Backfill fallback role = 'admin' when User row exists but
    role lookup misses (legacy data); 'system' fallback when
    *_by_id IS NULL itself (Codex P1 catch on PR-2A — CHECK
    ck_status_history_actor_consistency requires user_id NOT
    NULL when role IN ('officer', 'admin')).
    """
    src = _PHASE1_10.read_text(encoding="utf-8")
    idx = src.index("'transition', 'overridden'")
    block_start = max(0, idx - 2000)
    overridden_block = src[block_start:idx]
    assert "COALESCE(u.role::text, 'admin')" in overridden_block


def test_phase1_10_scattered_audit_falls_back_to_system_when_actor_null() -> None:
    """Codex P1 catch on PR-2A — 5 scattered scalar backfill blocks
    must classify ``*_by_id IS NULL`` as 'system' actor (CHECK
    first OR clause: role='system' AND user_id NULL AND lead_id
    NULL). Without the fallback, legacy rows with audit timestamp
    but no actor cause the backfill INSERT to violate
    ``ck_status_history_actor_consistency``.

    Each block must contain a ``CASE WHEN p.<actor>_by_id IS NULL
    THEN 'system'`` pattern."""
    src = _PHASE1_10.read_text(encoding="utf-8")
    # 5 blocks × 3 column assignments per block × CASE WHEN check
    # — at minimum 5 ``actor_fallback`` metadata flags + 15 CASE
    # WHEN ``IS NULL THEN 'system'`` patterns. Lock at lower bound
    # to allow future formatting changes.
    assert src.count("'actor_fallback'") == 5, (
        "Each of the 5 scattered scalar blocks must record actor_fallback metadata"
    )
    # Pattern lock — at least 15 (= 5 blocks * 3 role columns) IS NULL fallbacks.
    assert src.count("IS NULL THEN 'system'") >= 15, (
        "Each scattered block needs CASE WHEN <actor_id> IS NULL THEN 'system' "
        "for transitioned_by_role + actor_actual_role + effective_transition_role"
    )


# ---------------------------------------------------------------------------
# 4. ORM model parity
# ---------------------------------------------------------------------------


def test_admission_profile_model_declares_4_eligibility_scalars() -> None:
    from app.models.admission import AdmissionProfile

    for col in ("gpa_overall", "conduct", "health_category", "graduation_year"):
        assert hasattr(AdmissionProfile, col), f"AdmissionProfile missing {col}"
        column = AdmissionProfile.__table__.columns[col]
        assert column.nullable is True, f"{col} must be nullable"


def test_status_history_model_imports_cleanly() -> None:
    from app.models import AdmissionProfileStatusHistory
    from app.models.admission_profile_status_history import (
        AdmissionProfileStatusHistory as DirectImport,
    )

    assert AdmissionProfileStatusHistory is DirectImport
    assert AdmissionProfileStatusHistory.__tablename__ == "admission_profile_status_history"


def test_status_history_model_declares_3_role_columns() -> None:
    from app.models.admission_profile_status_history import (
        AdmissionProfileStatusHistory,
    )

    for col in (
        "transitioned_by_role",
        "actor_actual_role",
        "effective_transition_role",
    ):
        assert hasattr(AdmissionProfileStatusHistory, col), f"missing {col}"
        column = AdmissionProfileStatusHistory.__table__.columns[col]
        assert column.nullable is False, f"{col} must be NOT NULL"


def test_status_history_model_declares_actor_consistency_check() -> None:
    from app.models.admission_profile_status_history import (
        AdmissionProfileStatusHistory,
    )

    constraint_names = {
        c.name for c in AdmissionProfileStatusHistory.__table__.constraints
    }
    assert "ck_status_history_actor_consistency" in constraint_names


def test_status_history_metadata_python_attr_renamed_to_avoid_collision() -> None:
    """``metadata`` collides với SQLAlchemy DeclarativeBase.metadata —
    Python attribute renamed to ``metadata_`` while SQL column stays
    ``metadata``."""
    from app.models.admission_profile_status_history import (
        AdmissionProfileStatusHistory,
    )

    assert hasattr(AdmissionProfileStatusHistory, "metadata_")
    assert "metadata" in AdmissionProfileStatusHistory.__table__.columns


# ---------------------------------------------------------------------------
# 5. Sanity — both migrations import cleanly
# ---------------------------------------------------------------------------


def test_both_migrations_define_upgrade_and_downgrade(
    phase1_09a, phase1_10
) -> None:
    for module in (phase1_09a, phase1_10):
        assert callable(getattr(module, "upgrade", None))
        assert callable(getattr(module, "downgrade", None))
