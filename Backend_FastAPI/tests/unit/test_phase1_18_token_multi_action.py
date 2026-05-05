"""Unit tests for #184 Wave 3-D migration ``phase1_18_extend_confirmation_token_for_multi_action``.

Wave 3 ⚠ ONE-WAY token schema extend. Tests cover:

1. Revision row + chain (``phase1_18`` → ``phase1_12``).
2. Constants lock-in (table name + 4-action enum + index/constraint
   names match PLAN spec).
3. 5 DDL steps in correct order: column add → CHECK → drop legacy
   UNIQUE → partial UNIQUE → lookup index.
4. Column add: NOT NULL + server_default 'confirm' (PG fast-path
   backfill of legacy rows).
5. CHECK constraint locks 4 action enum at DB layer.
6. Partial UNIQUE shape: ``(profile_id, action_type) WHERE
   confirmed_at IS NULL``.
7. Idempotent guards: ``_column_exists`` / ``_index_exists``.
8. Defensive ONE-WAY downgrade: count non-confirm rows BEFORE drop +
   raise RuntimeError on >0.
9. Module sanity (``upgrade`` + ``downgrade`` callable).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_18 = (
    _VERSIONS_DIR / "phase1_18_extend_confirmation_token_for_multi_action.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_18.stem, _PHASE1_18)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_18():
    return _load_migration()


@pytest.fixture
def src() -> str:
    return _PHASE1_18.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_18_revision_id(phase1_18) -> None:
    assert phase1_18.revision == "phase1_18"


def test_phase1_18_chains_off_phase1_12(phase1_18) -> None:
    """Wave 3 sequence: 3-A (phase1_11) → 3-B (FE Stage 3) → 3-C
    (phase1_12 backfill) → 3-D (this — token multi-action). Linear
    chain off Wave 3-C."""
    assert phase1_18.down_revision == "phase1_12"


# ---------------------------------------------------------------------------
# 2. Constants lock-in
# ---------------------------------------------------------------------------


def test_phase1_18_table_name_canonical(phase1_18) -> None:
    assert phase1_18.TABLE == "admission_confirmation_token"


def test_phase1_18_action_types_lock_four_values(phase1_18) -> None:
    """PLAN §3.3.g + line 1887 — 4 action values exact. Drift here =
    schema-vs-app contract divergence."""
    assert phase1_18.ACTION_TYPES == (
        "submit",
        "resubmit",
        "confirm",
        "withdraw",
    )
    assert len(phase1_18.ACTION_TYPES) == 4


def test_phase1_18_legacy_unique_index_name_matches_live(phase1_18) -> None:
    """SQLAlchemy ``unique=True + index=True`` produces the ``ix_*``
    prefix — verified live on dev DB 2026-05-05 via
    ``\\d admission_confirmation_token``. PLAN draft mentioned
    ``_profile_id_key`` which is the constraint convention; the live
    DB uses the index convention."""
    assert phase1_18.LEGACY_UNIQUE_INDEX == "ix_admission_confirmation_token_profile_id"


def test_phase1_18_partial_unique_name(phase1_18) -> None:
    assert phase1_18.PARTIAL_UNIQUE_NAME == "uq_active_token_per_profile_action"


def test_phase1_18_lookup_index_name(phase1_18) -> None:
    assert phase1_18.LOOKUP_INDEX_NAME == "ix_token_action_type"


def test_phase1_18_check_constraint_name(phase1_18) -> None:
    assert phase1_18.CHECK_NAME == "ck_token_action_type"


# ---------------------------------------------------------------------------
# 3. 5-step DDL order
# ---------------------------------------------------------------------------


def test_phase1_18_upgrade_steps_in_correct_order(src) -> None:
    """Step 1 (add column) → Step 2 (CHECK) → Step 3 (drop legacy
    UNIQUE) → Step 4 (partial UNIQUE) → Step 5 (lookup index). Steps
    must run in this order: the partial UNIQUE references action_type
    which doesn't exist before Step 1; the legacy UNIQUE drop must
    happen before the partial UNIQUE creation to avoid contention."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    add_col_pos = upgrade_body.index('op.add_column(')
    check_create_pos = upgrade_body.index("op.create_check_constraint(")
    drop_legacy_pos = upgrade_body.index('op.drop_index(LEGACY_UNIQUE_INDEX')
    partial_create_pos = upgrade_body.index("PARTIAL_UNIQUE_NAME")
    lookup_create_pos = upgrade_body.index("LOOKUP_INDEX_NAME")
    assert (
        add_col_pos
        < check_create_pos
        < drop_legacy_pos
        < partial_create_pos
        < lookup_create_pos
    )


# ---------------------------------------------------------------------------
# 4. Column add shape
# ---------------------------------------------------------------------------


def test_phase1_18_action_type_column_not_null_default_confirm(src) -> None:
    """NOT NULL + server_default 'confirm' = PG fast-path backfill of
    every legacy row to the legacy single-action behavior at ALTER
    time, no follow-up UPDATE needed."""
    assert '"action_type"' in src
    assert "sa.String(20)" in src
    assert "nullable=False" in src
    assert "server_default=sa.text(\"'confirm'\")" in src


# ---------------------------------------------------------------------------
# 5. CHECK constraint locks the enum
# ---------------------------------------------------------------------------


def test_phase1_18_check_constraint_uses_quoted_action_list(src) -> None:
    """Predicate built via repr to quote each action_type literal —
    SQL injection-safe (states come from tuple constant, but quoting
    is the principled shape)."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    assert "create_check_constraint" in upgrade_body
    assert 'CHECK_NAME' in upgrade_body
    assert "f\"action_type IN ({quoted_actions})\"" in upgrade_body


# ---------------------------------------------------------------------------
# 6. Partial UNIQUE shape per PLAN line 1893-1897
# ---------------------------------------------------------------------------


def test_phase1_18_partial_unique_predicate_confirmed_at_null(src) -> None:
    """``WHERE confirmed_at IS NULL`` keeps audit-trail rows
    (already-confirmed tokens) free from contention with newly-
    issued live tokens for the same (profile, action) pair."""
    pattern = "postgresql_where=sa.text(\"confirmed_at IS NULL\")"
    assert pattern in src


def test_phase1_18_partial_unique_columns_profile_id_action_type(src) -> None:
    """Composite UNIQUE on ``(profile_id, action_type)`` — same profile
    can hold ONE active token per action concurrently."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    # Look for the create_index call with PARTIAL_UNIQUE_NAME and the
    # column list ``["profile_id", "action_type"]``.
    pu_idx = upgrade_body.index("PARTIAL_UNIQUE_NAME")
    pu_block = upgrade_body[pu_idx : pu_idx + 400]
    assert '["profile_id", "action_type"]' in pu_block
    assert "unique=True" in pu_block


# ---------------------------------------------------------------------------
# 7. Idempotent guards
# ---------------------------------------------------------------------------


def test_phase1_18_uses_inspector_idempotency_helpers(src) -> None:
    assert "_column_exists" in src
    assert "_index_exists" in src
    # Helpers wrap inspector — same shape as Wave 5-D phase1_16.
    assert "from sqlalchemy import inspect" in src


# ---------------------------------------------------------------------------
# 8. Downgrade defensive guard
# ---------------------------------------------------------------------------


def test_phase1_18_downgrade_counts_non_confirm_rows_first(src) -> None:
    """COUNT must run BEFORE drop_index / drop_column — otherwise the
    guard would already have torn down the schema by the time we
    notice the violation."""
    downgrade_body = src[src.index("def downgrade()"):]
    count_pos = downgrade_body.index("WHERE action_type != 'confirm'")
    drop_pos = downgrade_body.index("op.drop_index(")
    assert count_pos < drop_pos


def test_phase1_18_downgrade_raises_on_multi_action_rows(src) -> None:
    """Non-zero count must raise — silent skip would let Phase 3
    callers continue writing rows the migration just attempted to
    revert."""
    downgrade_body = src[src.index("def downgrade()"):]
    assert "raise RuntimeError" in downgrade_body
    assert "ONE-WAY" in downgrade_body
    assert "snapshot" in downgrade_body


def test_phase1_18_downgrade_recreates_legacy_unique_only_if_safe(src) -> None:
    """When safe (0 multi-action rows), downgrade rebuilds the legacy
    single-token-per-profile UNIQUE."""
    downgrade_body = src[src.index("def downgrade()"):]
    assert "LEGACY_UNIQUE_INDEX" in downgrade_body
    assert 'unique=True' in downgrade_body


# ---------------------------------------------------------------------------
# 9. Module sanity
# ---------------------------------------------------------------------------


def test_phase1_18_callable_upgrade_and_downgrade(phase1_18) -> None:
    assert callable(getattr(phase1_18, "upgrade", None))
    assert callable(getattr(phase1_18, "downgrade", None))
