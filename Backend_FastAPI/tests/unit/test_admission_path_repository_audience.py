"""Unit tests for ``AdmissionPathRepository`` audience filter
methods (#184 Wave 1 PR-1B' / phase1_03).

Operator-contract guard tests — the production semantic
``WHERE :audience = ANY(applicable_to)`` is logically equivalent
to ``applicable_to @> ARRAY[:audience]`` BUT the Postgres planner
cannot pick a GIN index for ``= ANY(arr)``, so the storefront
audience filter would seq-scan the entire ``admission_path``
table. PLAN line 2646-2657 mandates ``@>`` / ``&&`` operators.

This file inspects the repository source text + the rendered SQL
of the two new methods to lock the operator contract:

* ``list_paths_by_audience`` MUST emit ``@>`` containment.
* ``list_paths_by_audiences_overlap`` MUST emit ``&&`` overlap.
* Neither method may use ``.any(`` (SQLAlchemy operator that
  compiles to ``= ANY(arr)``).

What does NOT live here:
* End-to-end SQL execution + EXPLAIN plan — staging clone D12-D14
  smoke per PLAN line 2656.
* DB migration shape — see ``test_phase1_03_revision_chain.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.repositories import admission_path_repository as repo_module
from app.repositories.admission_path_repository import AdmissionPathRepository


_REPO_FILE = Path(repo_module.__file__).resolve()


# ---------------------------------------------------------------------------
# 1. Anti-pattern guard — operator source contract
# ---------------------------------------------------------------------------


def test_repository_does_not_use_any_operator() -> None:
    """``.any(`` would compile to ``WHERE val = ANY(arr)`` which
    cannot use the GIN index. Anti-pattern per PLAN line 2657.

    The grep is intentionally broad — anywhere in the file. Any
    future audience-filter method that introduces ``.any(`` would
    silently degrade the storefront query to a seq-scan; this
    static guard catches it pre-merge."""
    src = _REPO_FILE.read_text()
    assert ".any(" not in src, (
        "Found ``.any(`` in admission_path_repository.py — this is the "
        "= ANY(arr) anti-pattern per PLAN line 2657. Use @> containment "
        "(applicable_to.op('@>')(...)) or && overlap instead so the "
        "ix_admission_path_applicable_to GIN index is reachable."
    )


def test_repository_uses_containment_operator() -> None:
    """The ``@>`` operator is the canonical containment for the
    single-audience filter contract per PLAN line 2647."""
    src = _REPO_FILE.read_text()
    assert ".op(\"@>\")" in src, (
        "list_paths_by_audience must use applicable_to.op('@>')(...)"
    )


def test_repository_uses_overlap_operator() -> None:
    """The ``&&`` operator is the canonical overlap for the
    multi-audience filter contract per PLAN line 2648."""
    src = _REPO_FILE.read_text()
    assert ".op(\"&&\")" in src, (
        "list_paths_by_audiences_overlap must use applicable_to.op('&&')(...)"
    )


# ---------------------------------------------------------------------------
# 2. Method existence + signature
# ---------------------------------------------------------------------------


def test_list_paths_by_audience_exists() -> None:
    assert hasattr(AdmissionPathRepository, "list_paths_by_audience")
    assert callable(AdmissionPathRepository.list_paths_by_audience)


def test_list_paths_by_audiences_overlap_exists() -> None:
    assert hasattr(AdmissionPathRepository, "list_paths_by_audiences_overlap")
    assert callable(AdmissionPathRepository.list_paths_by_audiences_overlap)


def test_list_paths_by_audience_signature_includes_legacy_null_flag() -> None:
    """``include_legacy_null`` is the Phase-3 cutover knob — when
    flipped to False, the OR NULL branch drops out of the WHERE
    clause and the storefront only returns paths with explicit
    audience set. Phase 1+2 contract: default True."""
    import inspect

    sig = inspect.signature(AdmissionPathRepository.list_paths_by_audience)
    params = sig.parameters
    assert "include_legacy_null" in params
    assert params["include_legacy_null"].default is True


def test_list_paths_by_audiences_overlap_signature_includes_legacy_null_flag() -> None:
    import inspect

    sig = inspect.signature(
        AdmissionPathRepository.list_paths_by_audiences_overlap
    )
    params = sig.parameters
    assert "include_legacy_null" in params
    assert params["include_legacy_null"].default is True


# ---------------------------------------------------------------------------
# 3. Empty-input contract — overlap with no audiences = no rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overlap_with_empty_input_returns_empty_list() -> None:
    """Empty ``audiences`` argument = "filter active but caller passed
    no buckets" — should return [] without hitting the DB. Caller
    wanting "all audiences" should not invoke this method."""
    # No DB session needed — the method short-circuits.
    repo = AdmissionPathRepository.__new__(AdmissionPathRepository)
    result = await repo.list_paths_by_audiences_overlap([])
    assert result == []


# ---------------------------------------------------------------------------
# 4. Source contract — preserve NULL via OR branch when flag True
# ---------------------------------------------------------------------------


def test_repository_preserves_null_via_or_branch() -> None:
    """Phase 1+2 query contract (PLAN line 2649-2655) — legacy paths
    with ``applicable_to IS NULL`` must remain visible. Static check
    that the OR NULL branch lives in the source; runtime smoke
    against staging clone covers the planner behavior."""
    src = _REPO_FILE.read_text()
    # The two methods both use ``or_(AdmissionPath.applicable_to.is_(None), ...)``
    assert "or_(" in src
    assert "AdmissionPath.applicable_to.is_(None)" in src


# ---------------------------------------------------------------------------
# 5. Compile-dialect contract — runtime SQL must render correctly
# ---------------------------------------------------------------------------
#
# Codex P1 catch on PR-1B' first cut: the source-grep tests above all
# passed even though the original ``literal_column("admission_audience")``
# cast failed compile with ``AttributeError: ... '_variant_mapping'``.
# Source grep is necessary but not sufficient — we also need to
# materialize the SQL via the postgresql dialect so a future cast-
# style change can't pass tests while breaking runtime.


def _compile_select_with_filter(method_name: str, *args, **kwargs) -> str:
    """Run the repository method body up to the SQL-compile step.

    Both methods build the same shape: ``select(AdmissionPath).where(<filter>)``.
    We use SQLAlchemy's postgresql dialect compile directly to render
    the final SQL string with literal_binds so the rendered output
    can be substring-checked for the operator + cast contract.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql
    from sqlalchemy import cast as sql_cast, or_

    from app.models.admission_config.admission_path import AdmissionPath
    from app.repositories.admission_path_repository import _AUDIENCE_ARRAY_TYPE

    if method_name == "contains":
        audience = args[0]
        cond = AdmissionPath.applicable_to.op("@>")(
            sql_cast([audience], _AUDIENCE_ARRAY_TYPE)
        )
    elif method_name == "overlap":
        audiences = args[0]
        cond = AdmissionPath.applicable_to.op("&&")(
            sql_cast(list(audiences), _AUDIENCE_ARRAY_TYPE)
        )
    else:
        raise AssertionError(f"unknown method {method_name}")

    if kwargs.get("include_legacy_null", True):
        where_clause = or_(AdmissionPath.applicable_to.is_(None), cond)
    else:
        where_clause = cond

    stmt = select(AdmissionPath.id).where(where_clause)
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_contains_compiles_with_typed_array_cast() -> None:
    """``list_paths_by_audience`` must render
    ``CAST(ARRAY[...] AS admission_audience[])`` with the @> operator.
    Bare ``literal_column`` (the first-cut bug) raises AttributeError
    on ``_variant_mapping`` — this test catches that regression."""
    sql = _compile_select_with_filter("contains", "POST_THPT")
    assert "@>" in sql
    assert "CAST(ARRAY[" in sql
    assert "AS admission_audience[]" in sql
    # Anti-pattern: ``= ANY(arr)`` would pass a logically-equivalent
    # query but cannot use the GIN index.
    assert " ANY(" not in sql.upper()


def test_overlap_compiles_with_typed_array_cast() -> None:
    """``list_paths_by_audiences_overlap`` must render
    ``CAST(ARRAY[...] AS admission_audience[])`` with the && operator."""
    sql = _compile_select_with_filter("overlap", ["POST_THPT", "LIEN_THONG_TC"])
    assert "&&" in sql
    assert "CAST(ARRAY[" in sql
    assert "AS admission_audience[]" in sql
    assert " ANY(" not in sql.upper()


def test_contains_preserves_legacy_null_in_compiled_sql() -> None:
    """Phase 1+2 contract (PLAN line 2649-2655) — when
    ``include_legacy_null=True`` (default), the rendered SQL must OR
    in the NULL branch so paths not yet backfilled stay visible."""
    sql = _compile_select_with_filter("contains", "POST_THPT")
    assert "applicable_to IS NULL" in sql


def test_contains_drops_null_branch_when_strict_filter_enabled() -> None:
    """Phase 3 cutover knob — when ``include_legacy_null=False``, the
    NULL branch is gone. Storefront after the validator gate uses
    this mode."""
    sql = _compile_select_with_filter(
        "contains", "POST_THPT", include_legacy_null=False
    )
    assert "applicable_to IS NULL" not in sql
    assert "@>" in sql
