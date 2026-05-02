# tests/repositories/test_admission_config_repository_p0c.py
"""Phase 0c — `admission_config_repository.check_criteria_usage` field-name regression.

Pre-fix, `check_criteria_usage` referenced
``OfferingAdmissionConfig.admission_criteria_id`` and
``AdmissionPath.admission_criteria_id``. Both models actually declare the
FK column as ``criteria_id`` (verified
``app/models/admission_config/offering_config.py:38`` and
``app/models/admission_config/admission_path.py:82``). SQLAlchemy
expression construction does ``getattr(Model, attr_name)`` at the
``.where(...)`` line, so the mismatch raised ``AttributeError`` the
moment the method was called — long before any SQL hit the DB.

The visible production symptom: an admin trying to delete an
``AdmissionCriteria`` that was actually in use would crash on a 500
``AttributeError`` instead of getting the
``BusinessRuleViolation("Cannot delete criteria...")`` that
``admission_config_service.delete_criteria`` is supposed to emit.

Two layers of coverage:

1. Behaviour: call ``check_criteria_usage`` against a mock DB session;
   the build-time attribute access on ``OfferingAdmissionConfig`` and
   ``AdmissionPath`` must succeed and the method must return the
   expected boolean.
2. Model contract: assert that both models still expose ``criteria_id``
   and do **not** expose ``admission_criteria_id``. If a future model
   refactor renames the FK back, this test fails loud.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.admission_config.admission_path import AdmissionPath
from app.models.admission_config.offering_config import OfferingAdmissionConfig
from app.repositories.admission_config_repository import AdmissionConfigRepository


# ---------------------------------------------------------------------------
# Behaviour: build-time attribute access succeeds, return value correct.
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def repo(mock_db):
    return AdmissionConfigRepository(mock_db)


def _empty_result() -> MagicMock:
    """Mock execute() return that has no rows (`first()` is None)."""
    res = MagicMock()
    res.first = MagicMock(return_value=None)
    return res


def _hit_result() -> MagicMock:
    """Mock execute() return that has a row (`first()` is truthy)."""
    res = MagicMock()
    res.first = MagicMock(return_value=MagicMock())
    return res


@pytest.mark.asyncio
async def test_check_criteria_usage_returns_false_when_unused(repo, mock_db):
    """Both queries empty → criteria is unused; returns False.

    The build-time attribute access on the two models must NOT raise
    AttributeError. If P0c regresses, this test fails before reaching
    the assert.
    """
    mock_db.execute.side_effect = [_empty_result(), _empty_result()]

    used = await repo.check_criteria_usage(criteria_id=42)

    assert used is False
    assert mock_db.execute.await_count == 2  # both branches probed


@pytest.mark.asyncio
async def test_check_criteria_usage_returns_true_when_offering_uses_it(repo, mock_db):
    """First query (OfferingAdmissionConfig) hits → short-circuit True."""
    mock_db.execute.side_effect = [_hit_result()]  # second query never runs

    used = await repo.check_criteria_usage(criteria_id=42)

    assert used is True
    assert mock_db.execute.await_count == 1


@pytest.mark.asyncio
async def test_check_criteria_usage_returns_true_when_path_uses_it(repo, mock_db):
    """First query empty, second (AdmissionPath) hits → True."""
    mock_db.execute.side_effect = [_empty_result(), _hit_result()]

    used = await repo.check_criteria_usage(criteria_id=42)

    assert used is True
    assert mock_db.execute.await_count == 2


# ---------------------------------------------------------------------------
# Model contract: lock the field names that the repository depends on.
# ---------------------------------------------------------------------------


def test_offering_admission_config_exposes_criteria_id_not_admission_criteria_id():
    assert hasattr(OfferingAdmissionConfig, "criteria_id"), (
        "OfferingAdmissionConfig.criteria_id missing — Phase 0c repository "
        "fix relies on this column name. See "
        "app/models/admission_config/offering_config.py:38."
    )
    assert not hasattr(OfferingAdmissionConfig, "admission_criteria_id"), (
        "OfferingAdmissionConfig.admission_criteria_id should not exist; "
        "if it does, the Phase 0c hot-fix has been undone or the model "
        "drift is back."
    )


def test_admission_path_exposes_criteria_id_not_admission_criteria_id():
    assert hasattr(AdmissionPath, "criteria_id"), (
        "AdmissionPath.criteria_id missing — Phase 0c repository fix "
        "relies on this column name. See "
        "app/models/admission_config/admission_path.py:82."
    )
    assert not hasattr(AdmissionPath, "admission_criteria_id"), (
        "AdmissionPath.admission_criteria_id should not exist; if it does, "
        "the Phase 0c hot-fix has been undone or the model drift is back."
    )


def test_repository_source_does_not_reference_admission_criteria_id():
    """Belt-and-suspenders: scan the repository source for the bad name.

    The behaviour tests catch a regression at runtime; this static check
    catches it the moment a reviewer reads the diff. AST-walk would be
    over-engineered for a literal substring match; the repository file
    is small and the bad name is distinctive.
    """
    from pathlib import Path

    repo_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "repositories"
        / "admission_config_repository.py"
    )
    src = repo_path.read_text(encoding="utf-8")
    # Allow the docstring mention of the historical bad name (it documents
    # the fix); forbid any non-comment occurrence by checking each line and
    # skipping comment-only lines.
    bad = "admission_criteria_id"
    offending: list[tuple[int, str]] = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Inside the docstring it's fine — docstrings are triple-quoted
        # and we keep the historical name there to explain the fix.
        if bad in line and '"""' not in src.splitlines()[max(0, lineno - 2)]:
            # Heuristic: if the line is inside the existing fix docstring,
            # the surrounding `"""` framing keeps it from being a runtime
            # reference. The simplest check: forbid the bad name anywhere
            # outside a comment OR a triple-quoted block. To stay simple we
            # tolerate the name only when it appears between two `"""`
            # markers in the file.
            offending.append((lineno, line.rstrip()))
    # Final filter: drop hits that are inside the fix docstring (block
    # between the first pair of `"""` after the function def).
    if offending:
        # Find the pair of `"""` that wraps the docstring of
        # `check_criteria_usage`; tolerate hits between them.
        try:
            doc_start = next(
                i
                for i, line in enumerate(src.splitlines(), start=1)
                if line.strip().startswith('"""')
                and i > _line_of_check_criteria_usage(src)
            )
            doc_end = next(
                i
                for i, line in enumerate(src.splitlines(), start=1)
                if i > doc_start and line.strip().startswith('"""')
            )
            offending = [
                (ln, txt) for ln, txt in offending if not (doc_start <= ln <= doc_end)
            ]
        except StopIteration:
            pass

    assert not offending, (
        "Repository source still references `admission_criteria_id` outside "
        "the fix docstring. Phase 0c regressed:\n"
        + "\n".join(f"  line {ln}: {txt!r}" for ln, txt in offending)
    )


def _line_of_check_criteria_usage(src: str) -> int:
    for i, line in enumerate(src.splitlines(), start=1):
        if "def check_criteria_usage" in line:
            return i
    return 0
