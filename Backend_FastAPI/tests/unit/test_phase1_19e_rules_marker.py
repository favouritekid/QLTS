"""Unit tests for #184 Wave 5-C migration ``phase1_19e_seed_notification_rules``.

This is a marker migration documenting that the spec slot's payload (channel
routing rules per audience for 12 ADMISSION_* events) was absorbed by
``phase1_19c`` (Wave 5-A, PR #213 squash ``9af7510b`` — 12 NotificationRule
+ 12 NotificationTemplate + 29 NotificationAction rows).

Tests cover the marker contract:

1. Revision row + chain (``phase1_19e`` → ``phase1_19d``) — terminal
   Phase 1 #19 chain revision.
2. Marker body — no ``op.*`` DDL helper in upgrade/downgrade.
3. Module sanity — callable upgrade + downgrade.
4. Docstring documents the absorption (cite ``phase1_19c`` + scope b2).
5. Wave 5 status documented (5/5 sub-PRs accounted for in the docstring).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_19E = _VERSIONS_DIR / "phase1_19e_seed_notification_rules.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_19E.stem, _PHASE1_19E)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_19e():
    return _load_migration()


@pytest.fixture
def src() -> str:
    return _PHASE1_19E.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Migration revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_19e_revision_id(phase1_19e) -> None:
    assert phase1_19e.revision == "phase1_19e"


def test_phase1_19e_chains_off_phase1_19d(phase1_19e) -> None:
    """Phase 1 #19 chain terminal revision: 19a → 19b → 19c → 19d → 19e
    (where 19b is B1 casbin per Q2 cascade chốt 2026-05-03)."""
    assert phase1_19e.down_revision == "phase1_19d"


# ---------------------------------------------------------------------------
# 2. Marker body — no DDL
# ---------------------------------------------------------------------------


def test_phase1_19e_upgrade_body_is_marker(src) -> None:
    """Marker pattern — ``phase1_19c`` already shipped the rule rows.
    A non-no-op body here would attempt redundant inserts and noise the
    alembic logs with WHERE NOT EXISTS no-ops."""
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    downgrade_body = src[src.index("def downgrade()"):]
    assert "op." not in upgrade_body
    assert "op." not in downgrade_body
    assert "execute(" not in upgrade_body
    assert "execute(" not in downgrade_body


def test_phase1_19e_callable_upgrade_and_downgrade(phase1_19e) -> None:
    assert callable(getattr(phase1_19e, "upgrade", None))
    assert callable(getattr(phase1_19e, "downgrade", None))


# ---------------------------------------------------------------------------
# 3. Docstring contract — documents the absorption
# ---------------------------------------------------------------------------


def test_phase1_19e_docstring_cites_phase1_19c_absorption(src) -> None:
    """Future readers MUST find the deviation log in the migration
    itself, not buried in PLAN. The docstring names ``phase1_19c`` as
    the actual owner of the rule seed payload."""
    assert "phase1_19c" in src
    # Cite the PR + squash for traceability.
    assert "PR #213" in src
    assert "9af7510b" in src


def test_phase1_19e_docstring_lists_all_twelve_admission_events(src) -> None:
    """The docstring enumerates the 12 events that ``phase1_19c`` seeded
    so a reader does not need to open another file to know what is
    already covered."""
    expected_events = [
        "ADMISSION_PROFILE_SUBMITTED",
        "ADMISSION_REVISION_REQUESTED",
        "ADMISSION_RESUBMITTED",
        "ADMISSION_RESULT_PUBLISHED",
        "ADMISSION_DECISION_ADMITTED",
        "ADMISSION_DECISION_WAITLISTED",
        "ADMISSION_DECISION_REJECTED",
        "ADMISSION_WAITLIST_PROMOTED",
        "ADMISSION_CONFIRMED",
        "ADMISSION_ENROLLED",
        "ADMISSION_WITHDRAWN",
        "ADMISSION_ROLLED_BACK",
    ]
    missing = [e for e in expected_events if e not in src]
    assert not missing, f"docstring missing event references: {missing}"


def test_phase1_19e_docstring_documents_wave_5_complete(src) -> None:
    """The docstring closes Wave 5 by listing all 5 sub-PRs with their
    squash SHAs — anchor for the Wave 5 COMPLETE milestone."""
    assert "Wave 5-A" in src
    assert "Wave 5-B" in src
    assert "Wave 5-C" in src
    assert "Wave 5-D" in src
    assert "Wave 5-E" in src
    # Cite the merged squashes so a future reader can git-log directly.
    assert "9af7510b" in src  # 5-A
    assert "1989bd03" in src  # 5-D
    assert "0b17f394" in src  # 5-E
    assert "ef6a8b6d" in src  # 5-B


# ---------------------------------------------------------------------------
# 4. Sanity
# ---------------------------------------------------------------------------


def test_phase1_19e_no_branch_labels_or_depends_on(phase1_19e) -> None:
    """Marker migration must not introduce a branch label or dependency
    that could create a phantom alembic head."""
    assert phase1_19e.branch_labels is None
    assert phase1_19e.depends_on is None
