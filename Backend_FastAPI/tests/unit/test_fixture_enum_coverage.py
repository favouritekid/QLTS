"""Lock test — fixture ``init_schema_once`` ENUM coverage anchor.

Every ENUM in ``app/models`` declared with ``create_type=False`` (DDL
owned by Alembic migration) MUST be explicitly created in
``tests/fixtures/database.py:init_schema_once`` BEFORE
``Base.metadata.create_all()`` is called — otherwise SQLAlchemy skips
the ENUM creation (per the ``create_type=False`` flag) and the column
CREATE fails with::

    asyncpg.exceptions.UndefinedObjectError: type "foo" does not exist

This test greps every ``create_type=False`` ENUM name from the model
source files and asserts each name appears as a ``CREATE TYPE foo AS
ENUM (...)`` statement in the fixture. Adding a new
``create_type=False`` ENUM without updating the fixture fails this
test loudly before the change can land.

Root cause incident: 2026-05-08 post-cutover follow-up batch CI gate
"PR Gate — Contract Tests" failed at
``test_lead_assignment_lifecycle_end_to_end`` with
``UndefinedObjectError: type "subject_kind" does not exist`` —
``subject_kind`` ENUM was added in Phase 1 Wave 1 PR-1C' (phase1_05)
with ``create_type=False`` but the test fixture was never updated.
This regression slipped through because cutover ship 2026-05-07
cancelled the deploy.yml CI run before "PR Gate" could fire on the
post-merge branch — the test debt only became visible on the next
non-cancelled main push.

Fix shipped 2026-05-08 in PR `test-debt/admission-workflow-e2e-
fixture-fix` adds 10 explicit ``CREATE TYPE`` statements covering all
``create_type=False`` ENUMs across the codebase. This anchor test
prevents the same regression class from recurring.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "app" / "models"
FIXTURE_FILE = REPO_ROOT / "tests" / "fixtures" / "database.py"


def _collect_create_type_false_enum_names() -> set[str]:
    """Walk ``app/models`` and extract every ENUM ``name="foo"``
    paired with ``create_type=False``."""
    names: set[str] = set()
    # Match patterns:
    #   name="foo",
    #   ...
    #   create_type=False,
    # OR same-line:
    #   Enum(X, name="foo", create_type=False)
    # We allow up to ~500 chars between name= and create_type=False to
    # handle multi-line column definitions (typical in models).
    pattern = re.compile(
        r'name\s*=\s*["\']([a-z_]+)["\'][^)]{0,500}?create_type\s*=\s*False',
        re.DOTALL,
    )
    for py_file in MODELS_DIR.rglob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        for match in pattern.finditer(src):
            names.add(match.group(1))
    return names


def _collect_fixture_create_type_names() -> set[str]:
    """Extract every ``CREATE TYPE foo AS ENUM (...)`` name from the
    fixture file."""
    src = FIXTURE_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r'CREATE TYPE\s+([a-z_]+)\s+AS ENUM', re.IGNORECASE)
    return set(pattern.findall(src))


def test_every_create_type_false_enum_is_in_fixture():
    """Each ENUM declared with ``create_type=False`` in the codebase
    must have a matching ``CREATE TYPE`` line in the test fixture."""
    model_enums = _collect_create_type_false_enum_names()
    fixture_enums = _collect_fixture_create_type_names()

    assert model_enums, (
        "Failed to discover any ``create_type=False`` ENUMs in app/models — "
        "regex pattern probably broke after a refactor; fix this test."
    )

    missing = model_enums - fixture_enums
    assert not missing, (
        f"\n\n🚨 ENUM coverage drift in test fixture:\n\n"
        f"Models declare {sorted(missing)} with ``create_type=False``\n"
        f"but ``tests/fixtures/database.py:init_schema_once`` does NOT\n"
        f"emit a ``CREATE TYPE ... AS ENUM (...)`` statement for them.\n\n"
        f"Without the explicit CREATE TYPE, ``Base.metadata.create_all()``\n"
        f"will fail with ``UndefinedObjectError: type \"foo\" does not\n"
        f"exist`` because ``create_type=False`` tells SQLAlchemy to skip\n"
        f"ENUM creation (DDL owned by Alembic migration, not test\n"
        f"fixture).\n\n"
        f"Fix: add ``CREATE TYPE {{name}} AS ENUM (...)`` for each missing\n"
        f"name in ``tests/fixtures/database.py:init_schema_once`` BEFORE\n"
        f"the ``await conn.run_sync(AppBase.metadata.create_all)`` call.\n"
        f"Mirror the pattern used for existing ENUMs (e.g.\n"
        f"``subject_kind``, ``admission_audience``).\n\n"
        f"All known model ENUMs: {sorted(model_enums)}\n"
        f"All fixture-created:   {sorted(fixture_enums)}\n"
    )


def test_fixture_does_not_create_orphan_enums():
    """Sanity check — fixture should not have CREATE TYPE for ENUMs
    that no model uses (would indicate stale fixture or model deletion
    without fixture cleanup)."""
    model_enums = _collect_create_type_false_enum_names()
    fixture_enums = _collect_fixture_create_type_names()

    # ``discount_type_enum`` historically created here even though
    # the model uses ``values_callable``; allow as legacy carrying.
    legacy_allowed: set[str] = set()

    orphan = fixture_enums - model_enums - legacy_allowed
    if orphan:
        # Soft warning via plain assert message — not a hard fail
        # because some fixtures may keep a CREATE TYPE for legacy
        # back-compat. If this triggers, audit each orphan and either
        # remove it from fixture OR add to ``legacy_allowed``.
        assert not orphan, (
            f"\n\nFixture creates orphan ENUMs (no matching model "
            f"declaration): {sorted(orphan)}\n"
            f"Audit each — remove from fixture OR add to "
            f"``legacy_allowed`` set in this test.\n"
        )
