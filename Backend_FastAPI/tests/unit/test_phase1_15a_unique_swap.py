"""Unit tests for #184 Wave 3-E migration ``phase1_15a_drop_lead_id_unique_to_composite``.

Final ⚠ ONE-WAY migration of Wave 3 — completes Phase 1 Schema 100%
post-merge. Swaps single-profile-per-lead UNIQUE for composite
``(lead_id, academic_year)`` so a lead can apply across academic years.

Tests cover:

1. Revision row + chain (``phase1_15a`` → ``phase1_18``).
2. Constants lock-in (TABLE + LEAD_ID_INDEX live name + COMPOSITE_UNIQUE_NAME).
3. 3-step DDL ordering: drop legacy UNIQUE INDEX → recreate as plain →
   add composite UNIQUE.
4. Idempotent guards via inspector helpers (``_index_exists`` /
   ``_is_index_unique`` / ``_constraint_exists``).
5. Same-name index re-use: legacy index is UNIQUE, plain replacement
   reuses the SAME name (transition UNIQUE → plain).
6. Defensive ONE-WAY downgrade — counts leads with >1 profile BEFORE
   drop, raises RuntimeError on any.
7. Downgrade safe path: drop composite + drop plain index + recreate
   UNIQUE on lead_id.
8. ORM model parity — ``AdmissionProfile.__table_args__`` carries the
   new composite UNIQUE; column ``unique=True`` removed.
9. Module sanity (callable upgrade + downgrade).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_15A = _VERSIONS_DIR / "phase1_15a_drop_lead_id_unique_to_composite.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_15A.stem, _PHASE1_15A)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_15a():
    return _load_migration()


@pytest.fixture
def src() -> str:
    return _PHASE1_15A.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_15a_revision_id(phase1_15a) -> None:
    assert phase1_15a.revision == "phase1_15a"


def test_phase1_15a_chains_off_phase1_18(phase1_15a) -> None:
    """Wave 3 sequence final: 3-A (phase1_11) → 3-C (phase1_12 backfill)
    → 3-D (phase1_18 token) → 3-E (this — UNIQUE swap, completes
    Phase 1 Schema 100%)."""
    assert phase1_15a.down_revision == "phase1_18"


# ---------------------------------------------------------------------------
# 2. Constants lock-in
# ---------------------------------------------------------------------------


def test_phase1_15a_table_name_canonical(phase1_15a) -> None:
    assert phase1_15a.TABLE == "admission_profile"


def test_phase1_15a_lead_id_index_name_matches_live_db(phase1_15a) -> None:
    """SQLAlchemy ``unique=True + index=True`` produces ONE UNIQUE
    INDEX named with the ``ix_*`` prefix — verified live via
    ``\\d admission_profile`` 2026-05-05. Same correction pattern as
    Wave 3-D phase1_18 (``_lead_id_key`` constraint convention is the
    PLAN draft style; live DB uses ``ix_*`` index convention)."""
    assert phase1_15a.LEAD_ID_INDEX == "ix_admission_profile_lead_id"


def test_phase1_15a_composite_unique_name_per_plan_line_3343(phase1_15a) -> None:
    assert phase1_15a.COMPOSITE_UNIQUE_NAME == "uq_admission_profile_lead_year"


# ---------------------------------------------------------------------------
# 3. 3-step DDL ordering
# ---------------------------------------------------------------------------


def test_phase1_15a_upgrade_steps_in_correct_order(src) -> None:
    """Step 1 (drop legacy UNIQUE) → Step 2 (recreate as plain) →
    Step 3 (add composite UNIQUE). Order matters: the recreated plain
    index uses the SAME name as the dropped UNIQUE index; the
    composite UNIQUE is independent but logically follows the lead_id
    transition."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    drop_legacy_pos = upgrade_body.index("op.drop_index(LEAD_ID_INDEX")
    create_plain_pos = upgrade_body.index("op.create_index(LEAD_ID_INDEX")
    create_composite_pos = upgrade_body.index("op.create_unique_constraint(")
    assert drop_legacy_pos < create_plain_pos < create_composite_pos


def test_phase1_15a_recreated_index_is_plain_not_unique(src) -> None:
    """Step 2 recreates the lead_id index as a PLAIN btree — not
    UNIQUE. The UNIQUE flavor would conflict with the composite
    UNIQUE at the application contract level."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    create_plain_block = upgrade_body[
        upgrade_body.index("op.create_index(LEAD_ID_INDEX") :
    ]
    create_plain_block = create_plain_block[: create_plain_block.index(")") + 1]
    # No ``unique=True`` argument on the recreate call.
    assert "unique=True" not in create_plain_block


def test_phase1_15a_composite_columns_lead_id_academic_year(src) -> None:
    """Composite UNIQUE columns must be ``(lead_id, academic_year)`` in
    that order — matches PLAN line 3343 spec."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    composite_block = upgrade_body[
        upgrade_body.index("op.create_unique_constraint(") :
    ]
    assert '["lead_id", "academic_year"]' in composite_block


# ---------------------------------------------------------------------------
# 4. Idempotent helpers
# ---------------------------------------------------------------------------


def test_phase1_15a_uses_inspector_idempotency_helpers(src) -> None:
    """Helpers wrap inspector calls — same shape as Wave 5-D phase1_16
    and Wave 3-D phase1_18."""
    assert "_index_exists" in src
    assert "_is_index_unique" in src
    assert "_constraint_exists" in src
    assert "from sqlalchemy import inspect" in src


def test_phase1_15a_step_1_only_drops_if_index_is_unique(src) -> None:
    """Idempotent — if a prior partial run already converted the
    index to plain, skip the drop. ``_is_index_unique`` gates the
    drop."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    # The drop_index call is guarded by AND clause on _is_index_unique.
    assert "_is_index_unique(TABLE, LEAD_ID_INDEX)" in upgrade_body


# ---------------------------------------------------------------------------
# 5. Defensive ONE-WAY downgrade
# ---------------------------------------------------------------------------


def test_phase1_15a_downgrade_counts_multi_profile_leads_first(src) -> None:
    """COUNT must run BEFORE drop_constraint / drop_index — surface
    the violation up-front instead of failing mid-DDL when CREATE
    UNIQUE INDEX rejects multi-profile rows."""
    downgrade_body = src[src.index("def downgrade()"):]
    count_pos = downgrade_body.index("HAVING COUNT(*) > 1")
    drop_pos = downgrade_body.index("op.drop_constraint(")
    assert count_pos < drop_pos


def test_phase1_15a_downgrade_raises_with_one_way_hint(src) -> None:
    downgrade_body = src[src.index("def downgrade()"):]
    assert "raise RuntimeError" in downgrade_body
    assert "ONE-WAY" in downgrade_body
    assert "snapshot" in downgrade_body
    assert "Manual cleanup" in downgrade_body  # ops playbook hint


def test_phase1_15a_downgrade_safe_path_recreates_unique_index(src) -> None:
    """When safe (0 multi-profile leads), downgrade rebuilds the
    legacy single UNIQUE on lead_id."""
    downgrade_body = src[src.index("def downgrade()"):]
    # The recreate call sets unique=True.
    recreate_pos = downgrade_body.index("op.create_index(LEAD_ID_INDEX")
    recreate_block = downgrade_body[recreate_pos : recreate_pos + 200]
    assert "unique=True" in recreate_block


# ---------------------------------------------------------------------------
# 6. ORM model parity (cross-source consistency anchor)
# ---------------------------------------------------------------------------


def test_admission_profile_model_carries_composite_unique() -> None:
    """``AdmissionProfile.__table_args__`` declares the composite
    UNIQUE so test DB (``Base.metadata.create_all``) matches prod
    schema. Drift here = test-vs-prod skew per memory
    ``test-db-schema-source``."""
    from sqlalchemy import UniqueConstraint

    from app.models.admission import AdmissionProfile

    composite = next(
        (
            c
            for c in AdmissionProfile.__table_args__
            if isinstance(c, UniqueConstraint)
            and c.name == "uq_admission_profile_lead_year"
        ),
        None,
    )
    assert composite is not None, (
        "AdmissionProfile.__table_args__ missing composite UniqueConstraint "
        "'uq_admission_profile_lead_year' (lead_id, academic_year)"
    )
    column_names = {c.name for c in composite.columns}
    assert column_names == {"lead_id", "academic_year"}


def test_admission_profile_lead_id_no_longer_unique_at_column_level() -> None:
    """``unique=True`` removed from the column declaration — the
    composite UNIQUE in ``__table_args__`` is now the single source
    of truth for lead-related uniqueness."""
    from app.models.admission import AdmissionProfile

    lead_id_col = AdmissionProfile.__table__.columns["lead_id"]
    # Column-level unique=True would surface here as `unique=True` on
    # the SQLAlchemy column — must be falsy after Wave 3-E swap.
    assert lead_id_col.unique is None or lead_id_col.unique is False


# ---------------------------------------------------------------------------
# 7. Module sanity
# ---------------------------------------------------------------------------


def test_phase1_15a_callable_upgrade_and_downgrade(phase1_15a) -> None:
    assert callable(getattr(phase1_15a, "upgrade", None))
    assert callable(getattr(phase1_15a, "downgrade", None))
