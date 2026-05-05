"""Unit tests for #184 Wave 3-A migration ``phase1_11_extend_profile_status_check_constraint``.

Wave 3 ⚠ ONE-WAY first migration. Extends ``admission_profile.status`` CHECK
constraint from 10 to 14 states. Tests cover:

1. Revision row + chain (``phase1_11`` → ``phase1_19e``).
2. Constraint name + table name canonical.
3. ``OLD_STATES`` / ``NEW_STATES`` / ``ALL_STATES`` exact tuples.
4. Upgrade body shape — drop + recreate with 14 values.
5. Downgrade body shape — defensive guard against new-state rows + drop +
   recreate with 10 values.
6. Predicate helper produces SQL-safe quoting.
7. Module sanity (``upgrade`` + ``downgrade`` callable).
8. ORM model parity — ``AdmissionProfile.__table_args__`` ``CheckConstraint``
   lists all 14 values (test DB reads this; drift = test-vs-prod skew).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_11 = (
    _VERSIONS_DIR / "phase1_11_extend_profile_status_check_constraint.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_11.stem, _PHASE1_11)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_11():
    return _load_migration()


@pytest.fixture
def src() -> str:
    return _PHASE1_11.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_11_revision_id(phase1_11) -> None:
    assert phase1_11.revision == "phase1_11"


def test_phase1_11_chains_off_phase1_19e(phase1_11) -> None:
    """Wave 3 follows Wave 5 closure (``phase1_19e`` is the terminal Wave
    5 marker). Wave 3-A unblocks the rest of Wave 3 sequence
    (3-C/3-D/3-E)."""
    assert phase1_11.down_revision == "phase1_19e"


# ---------------------------------------------------------------------------
# 2. Constraint + table name canonical
# ---------------------------------------------------------------------------


def test_phase1_11_constraint_name_matches_model(phase1_11) -> None:
    """Must match the name in ``AdmissionProfile.__table_args__`` so DROP
    + ADD operates on the same constraint."""
    assert phase1_11.CONSTRAINT_NAME == "ck_admission_profile_status"


def test_phase1_11_table_name_admission_profile(phase1_11) -> None:
    assert phase1_11.TABLE == "admission_profile"


# ---------------------------------------------------------------------------
# 3. State tuple lock-in
# ---------------------------------------------------------------------------


def test_phase1_11_old_states_ten_values(phase1_11) -> None:
    """Lock-in the 10-state baseline. A drift here would mean the migration
    is operating on a different starting point than prod."""
    assert phase1_11.OLD_STATES == (
        "draft",
        "submitted",
        "approved",
        "rejected",
        "confirmed",
        "enrolled",
        "resubmitted",
        "overridden",
        "revision_requested",
        "withdrawn",
    )
    assert len(phase1_11.OLD_STATES) == 10


def test_phase1_11_new_states_four_values(phase1_11) -> None:
    """Lock-in the 4 Wave-3 additions per PLAN §3.3.b workflow remap."""
    assert phase1_11.NEW_STATES == (
        "reviewing",
        "result_published",
        "admitted",
        "waitlisted",
    )
    assert len(phase1_11.NEW_STATES) == 4


def test_phase1_11_all_states_fourteen_values(phase1_11) -> None:
    """``ALL_STATES`` = OLD + NEW; no overlap, no gap."""
    assert phase1_11.ALL_STATES == phase1_11.OLD_STATES + phase1_11.NEW_STATES
    assert len(phase1_11.ALL_STATES) == 14
    # No accidental duplicates.
    assert len(set(phase1_11.ALL_STATES)) == 14


# ---------------------------------------------------------------------------
# 4. Predicate helper
# ---------------------------------------------------------------------------


def test_phase1_11_check_predicate_quotes_each_state(phase1_11) -> None:
    """Predicate must quote each value individually — Postgres would reject
    bare identifiers in IN(...). ``repr`` produces single-quoted Python
    string literals which SQL accepts as character literals."""
    pred = phase1_11._check_predicate(("alpha", "beta"))
    assert pred == "status IN ('alpha', 'beta')"


# ---------------------------------------------------------------------------
# 5. Upgrade body — drop + recreate
# ---------------------------------------------------------------------------


def test_phase1_11_upgrade_drops_then_creates(src) -> None:
    """Postgres has no ``ALTER CHECK``; DROP + ADD is the canonical pair."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    drop_pos = upgrade_body.index("op.drop_constraint(")
    create_pos = upgrade_body.index("op.create_check_constraint(")
    assert drop_pos < create_pos


def test_phase1_11_upgrade_uses_all_states_predicate(src) -> None:
    """The recreated constraint must list all 14 states."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    assert "_check_predicate(ALL_STATES)" in upgrade_body


# ---------------------------------------------------------------------------
# 6. Downgrade defensive guard
# ---------------------------------------------------------------------------


def test_phase1_11_downgrade_guards_with_count(src) -> None:
    """Downgrade must run a COUNT against new-state rows BEFORE attempting
    to recreate the 10-state CHECK — otherwise Postgres would raise a
    constraint violation that is harder to recover from."""
    downgrade_body = src[src.index("def downgrade()"):]
    # Order: COUNT statement appears BEFORE drop_constraint.
    select_pos = downgrade_body.index('SELECT COUNT(*)')
    drop_pos = downgrade_body.index("op.drop_constraint(")
    assert select_pos < drop_pos


def test_phase1_11_downgrade_raises_on_new_state_rows(src) -> None:
    """The guard must ``raise RuntimeError`` on a non-zero count — silent
    skip would bury the data-loss risk."""
    downgrade_body = src[src.index("def downgrade()"):]
    assert "raise RuntimeError" in downgrade_body
    assert "ONE-WAY" in downgrade_body


def test_phase1_11_downgrade_uses_old_states_predicate_when_safe(src) -> None:
    """When safe, downgrade recreates the original 10-state CHECK."""
    downgrade_body = src[src.index("def downgrade()"):]
    assert "_check_predicate(OLD_STATES)" in downgrade_body


# ---------------------------------------------------------------------------
# 7. Module sanity
# ---------------------------------------------------------------------------


def test_phase1_11_callable_upgrade_and_downgrade(phase1_11) -> None:
    assert callable(getattr(phase1_11, "upgrade", None))
    assert callable(getattr(phase1_11, "downgrade", None))


# ---------------------------------------------------------------------------
# 8. ORM model parity — test DB reads this declaration
# ---------------------------------------------------------------------------


def test_admission_profile_check_constraint_lists_all_fourteen_states() -> None:
    """``AdmissionProfile.__table_args__`` carries the 14-state CHECK so
    test DB (``Base.metadata.create_all()``) can INSERT rows with the new
    states. A drift here = test-vs-prod skew per memory
    ``test-db-schema-source``."""
    from sqlalchemy import CheckConstraint

    from app.models.admission import AdmissionProfile

    status_check = next(
        c
        for c in AdmissionProfile.__table_args__
        if isinstance(c, CheckConstraint)
        and c.name == "ck_admission_profile_status"
    )
    sql = str(status_check.sqltext)
    for state in (
        "draft",
        "submitted",
        "approved",
        "rejected",
        "confirmed",
        "enrolled",
        "resubmitted",
        "overridden",
        "revision_requested",
        "withdrawn",
        "reviewing",
        "result_published",
        "admitted",
        "waitlisted",
    ):
        assert f"'{state}'" in sql, (
            f"AdmissionProfile.__table_args__ status CheckConstraint missing "
            f"value {state!r}"
        )
