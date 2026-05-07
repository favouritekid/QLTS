"""Unit tests for #184 Wave 3-C migration ``phase1_12_backfill_selected_subject_group_id``.

Wave 3 ⚠ ONE-WAY backfill. Tests cover:

1. Revision row + chain (``phase1_12`` → ``phase1_11``).
2. Pre-flight column-existence check raises clean error if Phase 0 not
   applied.
3. Rule (a) auto-map for single-group paths — SQL surface assertion.
4. Rule (b) infer scoped + group-completeness — SQL surface assertion.
5. Rule (c) exception INSERTs — both AMBIGUOUS and INSUFFICIENT_DATA
   types emitted with correct scope (status NOT IN draft/withdrawn).
6. ON CONFLICT (profile_id, exception_type) DO NOTHING — idempotent
   exception inserts.
7. Idempotent UPDATE guard (``WHERE selected_subject_group_id IS NULL``).
8. Downgrade is ONE-WAY — raises RuntimeError with snapshot-restore
   hint.
9. Module sanity (callable upgrade + downgrade).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_12 = _VERSIONS_DIR / "phase1_12_backfill_selected_subject_group_id.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_12.stem, _PHASE1_12)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_12():
    return _load_migration()


@pytest.fixture
def src() -> str:
    return _PHASE1_12.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_12_revision_id(phase1_12) -> None:
    assert phase1_12.revision == "phase1_12"


def test_phase1_12_chains_off_phase1_11(phase1_12) -> None:
    """Wave 3 sequence: 3-A (phase1_11 status CHECK) → 3-B (FE Stage 3,
    no migration) → 3-C (this — backfill). 3-C linear chain off 3-A."""
    assert phase1_12.down_revision == "phase1_11"


# ---------------------------------------------------------------------------
# 2. Pre-flight column-existence check
# ---------------------------------------------------------------------------


def test_phase1_12_preflight_checks_column_exists(src) -> None:
    """Column ``selected_subject_group_id`` is owned by Phase 0
    ``admstrict01``. If chain is applied out of order (this migration
    runs before Phase 0), the backfill UPDATEs would fail with a
    cryptic "column does not exist". The pre-flight surfaces a clear
    hint instead."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    assert "information_schema.columns" in upgrade_body
    assert "selected_subject_group_id" in upgrade_body
    assert "RuntimeError" in upgrade_body
    assert "Phase 0" in upgrade_body or "admstrict01" in upgrade_body


# ---------------------------------------------------------------------------
# 3. Rule (a) — auto-map single-group paths
# ---------------------------------------------------------------------------


def test_phase1_12_rule_a_single_group_path_auto_map(src) -> None:
    """Rule (a) HAVING COUNT(*) = 1 narrows to paths with exactly one
    criteria_subject_group; the UPDATE then applies the sole group to
    every profile attached to that path."""
    assert "single_group_paths" in src
    assert "HAVING COUNT(*) = 1" in src
    assert "MAX(csg.subject_group_id) AS group_id" in src


def test_phase1_12_rule_a_uses_cte_split_to_guard_cast(src) -> None:
    """Eligible-profile filter (numeric guard via regex) is split into a
    CTE so Postgres cannot reorder the int cast before the regex
    predicate. Same defensive pattern as phase1_09a."""
    assert "eligible_profiles_a" in src
    assert "(p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'" in src


# ---------------------------------------------------------------------------
# 4. Rule (b) — infer scoped + group-completeness
# ---------------------------------------------------------------------------


def test_phase1_12_rule_b_scopes_to_path_allowed_groups(src) -> None:
    """Group inference must be scoped to the path's allowed groups, not
    global. Otherwise a profile with Toán-Lý-Hóa scores would match
    A00 even if the path doesn't accept A00."""
    assert "path_allowed_groups" in src
    assert "criteria_subject_group" in src


def test_phase1_12_rule_b_requires_group_completeness(src) -> None:
    """Match group X iff profile has scores for EVERY subject in X.
    Weak match ("≥1 score in group") would flag any profile with a
    single shared subject."""
    assert "group_completeness" in src
    assert "matched_count = required_count" in src
    assert "required_count > 0" in src


def test_phase1_12_rule_b_accepts_only_unique_complete_groups(src) -> None:
    """Even with completeness, if 2+ groups satisfy, do NOT auto-pick.
    HAVING COUNT(*) = 1 enforces unambiguous selection; ambiguous
    profiles fall through to Rule (c) AMBIGUOUS exception."""
    assert "unique_complete_groups" in src
    assert "complete_groups_per_profile" in src


# ---------------------------------------------------------------------------
# 5. Rule (c) — exception sinks
# ---------------------------------------------------------------------------


def test_phase1_12_rule_c_emits_ambiguous_exception(src) -> None:
    """Profile has data (path + scores) but multiple complete groups
    satisfy. Admin picks one via UI."""
    assert "'AMBIGUOUS_SELECTED_GROUP'" in src
    assert "applied_rules_groups" in src
    assert "score_count" in src


def test_phase1_12_rule_c_emits_insufficient_data_exception(src) -> None:
    """Profile is active but missing path id / non-numeric / no scores.
    Different fix workflow than AMBIGUOUS."""
    assert "'INSUFFICIENT_DATA_FOR_BACKFILL'" in src
    assert "has_path_id" in src
    assert "has_scores" in src


def test_phase1_12_rule_c_skips_draft_and_withdrawn(src) -> None:
    """Both exception types scope to ``status NOT IN ('draft',
    'withdrawn')`` — abandoned drafts and withdrawn profiles do not
    flood the admin queue."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    # Two occurrences (one per exception type's scope filter).
    assert upgrade_body.count("status NOT IN ('draft', 'withdrawn')") == 2


def test_phase1_12_exception_inserts_idempotent(src) -> None:
    """``ON CONFLICT (profile_id, exception_type) DO NOTHING`` mirrors
    the unique constraint from phase1_07b — re-running the migration
    skips already-recorded exceptions."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    assert (
        upgrade_body.count(
            "ON CONFLICT (profile_id, exception_type) DO NOTHING"
        )
        == 2
    )


# ---------------------------------------------------------------------------
# 6. Idempotent UPDATE guards
# ---------------------------------------------------------------------------


def test_phase1_12_updates_guard_null_column(src) -> None:
    """Each backfill UPDATE filters
    ``WHERE selected_subject_group_id IS NULL`` — re-running the
    migration skips already-populated profiles."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    # Multiple occurrences across the rules + filter clauses.
    assert (
        upgrade_body.count("selected_subject_group_id IS NULL") >= 4
    )


# ---------------------------------------------------------------------------
# 7. Downgrade ONE-WAY
# ---------------------------------------------------------------------------


def test_phase1_12_downgrade_raises_one_way(src) -> None:
    """Downgrade is intentionally a no-op with a clear message —
    reverting backfill would dangle Phase 3 AdmissionProfileChoice
    FKs and force re-review of every profile."""
    downgrade_body = src[src.index("def downgrade()"):]
    assert "raise RuntimeError" in downgrade_body
    assert "ONE-WAY" in downgrade_body
    assert "snapshot" in downgrade_body


# ---------------------------------------------------------------------------
# 8. Module sanity
# ---------------------------------------------------------------------------


def test_phase1_12_callable_upgrade_and_downgrade(phase1_12) -> None:
    assert callable(getattr(phase1_12, "upgrade", None))
    assert callable(getattr(phase1_12, "downgrade", None))
