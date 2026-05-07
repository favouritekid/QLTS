"""B2.2 — lock-in tests for `NotificationOutbox` model + migration parity.

Replaces the T0-4a canary `test_models_package_still_lacks_notification_outbox`
(retired in this PR; see comment in `tests/unit/test_outbox_skeleton.py`).
The remaining T0-4a invariants — that the skeleton task body and
`app/tasks/__init__.py` still don't reference the model — stay in place;
B2.2 only ships the model + migration, not the worker body (B2.4).

What this file locks:

1. **Importability** — `from app.models import NotificationOutbox` works
   from a fresh interpreter (re-export not silently dropped).
2. **Tablename + column shape** — every column declared in
   `phase1_19a_create_notification_outbox.py` is also on the ORM model
   with matching name + nullability. Catches drift if either side is
   tuned without the other.
3. **Index shape (partial WHERE)** — the two partial indexes
   (`ix_outbox_pending`, `ix_outbox_claim`) are declared on the ORM model
   so SQLAlchemy autogenerate would not silently re-add them.
4. **Idempotency UNIQUE** — `idempotency_key` carries the named UNIQUE
   constraint that B2.3 wrapper relies on for end-to-end dedupe.
5. **Migration head + chain** — `phase1_19a` revision parses, points at
   `phase0br01` as its parent, and no other migration declares it as a
   `down_revision` (= it's currently the head).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType


# alembic/versions is not a Python package (no __init__.py) — Alembic itself
# loads migrations via `spec_from_file_location`. Mirror that here so the
# tests don't depend on package layout.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "phase1_19a_create_notification_outbox.py"
)


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "phase1_19a_create_notification_outbox", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None, (
        f"Cannot build module spec for {_MIGRATION_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Importability + re-export contract -----------------------------------


def test_notification_outbox_importable_from_models_package():
    from app.models import NotificationOutbox

    assert NotificationOutbox.__name__ == "NotificationOutbox"


def test_notification_outbox_in_models_package_all():
    import app.models as models_pkg

    assert "NotificationOutbox" in models_pkg.__all__, (
        "NotificationOutbox must appear in app/models/__init__.py __all__ "
        "so `from app.models import *` callers and editor autocompleters "
        "see the symbol."
    )


# --- Tablename + ORM column contract ---------------------------------------


def test_notification_outbox_tablename():
    from app.models import NotificationOutbox

    assert NotificationOutbox.__tablename__ == "notification_outbox"


def test_notification_outbox_columns_match_expected_shape():
    """Every column declared in the migration must be on the ORM model
    with matching nullability + primary_key flag. Type drift is best
    caught by the live alembic upgrade smoke (verified manually); this
    test catches the more common name/nullable/PK drift in code review.
    """
    from app.models import NotificationOutbox

    cols = {c.name: c for c in NotificationOutbox.__table__.columns}

    expected = {
        "id":              {"nullable": False, "primary_key": True},
        "event_code":      {"nullable": False, "primary_key": False},
        "payload":         {"nullable": False, "primary_key": False},
        "idempotency_key": {"nullable": False, "primary_key": False},
        "created_at":      {"nullable": False, "primary_key": False},
        "dispatched_at":   {"nullable": True,  "primary_key": False},
        "attempts":        {"nullable": False, "primary_key": False},
        "last_error":      {"nullable": True,  "primary_key": False},
        "claimed_at":      {"nullable": True,  "primary_key": False},
        "claimed_until":   {"nullable": True,  "primary_key": False},
    }

    assert set(cols.keys()) == set(expected.keys()), (
        "NotificationOutbox column drift.\n"
        f"  Expected: {sorted(expected.keys())}\n"
        f"  Actual:   {sorted(cols.keys())}"
    )
    for name, want in expected.items():
        col = cols[name]
        assert col.nullable == want["nullable"], (
            f"{name}.nullable expected {want['nullable']}, got {col.nullable}"
        )
        assert col.primary_key == want["primary_key"], (
            f"{name}.primary_key expected {want['primary_key']}, got {col.primary_key}"
        )


def test_notification_outbox_id_is_bigint():
    """BIGSERIAL in the migration → BigInteger PK in the ORM."""
    from sqlalchemy import BigInteger

    from app.models import NotificationOutbox

    id_col = NotificationOutbox.__table__.columns["id"]
    assert isinstance(id_col.type, BigInteger), (
        f"id must be BigInteger to match BIGSERIAL in migration; "
        f"got {type(id_col.type).__name__}"
    )


def test_notification_outbox_payload_is_jsonb():
    """JSONB (Postgres dialect-specific) — not generic JSON, which would
    autogenerate as plain `json` column on Postgres and miss GIN-friendly
    operators that the dispatcher will eventually rely on."""
    from sqlalchemy.dialects.postgresql import JSONB

    from app.models import NotificationOutbox

    payload_col = NotificationOutbox.__table__.columns["payload"]
    assert isinstance(payload_col.type, JSONB), (
        f"payload must be JSONB to match migration; "
        f"got {type(payload_col.type).__name__}"
    )


def test_notification_outbox_idempotency_key_has_named_unique_constraint():
    """End-to-end dedupe contract: `idempotency_key` UNIQUE blocks
    double-INSERT from retried service callers. The named constraint
    lets future migrations reference it by name."""
    from sqlalchemy import UniqueConstraint

    from app.models import NotificationOutbox

    unique_constraints = [
        c
        for c in NotificationOutbox.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    matching = [
        c for c in unique_constraints
        if c.name == "uq_notification_outbox_idempotency_key"
    ]
    assert len(matching) == 1, (
        "Expected exactly one UniqueConstraint named "
        "`uq_notification_outbox_idempotency_key`; got "
        f"{[c.name for c in unique_constraints]}"
    )
    cols = [c.name for c in matching[0].columns]
    assert cols == ["idempotency_key"], (
        f"UNIQUE constraint must cover only `idempotency_key`; got {cols}"
    )


# --- Index shape (partial WHERE) -------------------------------------------


def test_notification_outbox_partial_indexes_present():
    from app.models import NotificationOutbox

    index_names = {idx.name for idx in NotificationOutbox.__table__.indexes}
    expected = {"ix_outbox_pending", "ix_outbox_claim"}
    assert expected.issubset(index_names), (
        f"Missing partial index(es). Expected: {expected}; got: {index_names}"
    )


def test_ix_outbox_pending_is_on_created_at():
    from app.models import NotificationOutbox

    pending = next(
        idx for idx in NotificationOutbox.__table__.indexes
        if idx.name == "ix_outbox_pending"
    )
    cols = [c.name for c in pending.columns]
    assert cols == ["created_at"], (
        f"ix_outbox_pending must index `created_at` only; got {cols}"
    )


def test_ix_outbox_claim_is_on_claimed_until():
    from app.models import NotificationOutbox

    claim = next(
        idx for idx in NotificationOutbox.__table__.indexes
        if idx.name == "ix_outbox_claim"
    )
    cols = [c.name for c in claim.columns]
    assert cols == ["claimed_until"], (
        f"ix_outbox_claim must index `claimed_until` only; got {cols}"
    )


def test_partial_indexes_filter_dispatched_at_null():
    """Both partial indexes must carry the same ``dispatched_at IS NULL``
    predicate — that's what makes them cheap (the table grows but the
    index only covers the tiny pending window)."""
    from app.models import NotificationOutbox

    for name in ("ix_outbox_pending", "ix_outbox_claim"):
        idx = next(
            i for i in NotificationOutbox.__table__.indexes if i.name == name
        )
        pg_opts = idx.dialect_options.get("postgresql", {})
        where = pg_opts.get("where")
        assert where is not None, f"{name} missing partial WHERE"
        where_str = str(where).lower()
        assert "dispatched_at" in where_str and "null" in where_str, (
            f"{name} WHERE clause must filter `dispatched_at IS NULL`; "
            f"got {where_str!r}"
        )


# --- Migration revision metadata + chain parity ----------------------------


def test_migration_phase1_19a_module_imports_with_expected_revision_chain():
    """The migration module loads cleanly; revision constants match."""
    mod = _load_migration_module()
    assert mod.revision == "phase1_19a", (
        f"revision constant must be 'phase1_19a'; got {mod.revision!r}"
    )
    assert mod.down_revision == "phase0br01", (
        "down_revision must point at phase0br01 (the merged Phase 0 trigger "
        "relax migration). If a new Phase 0 ships before this lands, "
        "retarget the down_revision."
    )


def test_phase1_19a_is_alembic_head_no_other_migration_descends_from_it():
    """No other revision file declares phase1_19a as its `down_revision`,
    i.e. phase1_19a is currently the alembic head. A future migration must
    bump this lineage explicitly; this test fails loudly when that happens
    so the author is forced to acknowledge the rebase."""
    versions_dir = (
        Path(__file__).resolve().parents[2] / "alembic" / "versions"
    )
    self_name = "phase1_19a_create_notification_outbox.py"
    children: list[str] = []
    pattern = re.compile(
        r"down_revision\s*[:=][^=]*?[\"']phase1_19a[\"']"
    )
    for migration in versions_dir.glob("*.py"):
        if migration.name == self_name or migration.name == "__init__.py":
            continue
        text_ = migration.read_text(encoding="utf-8")
        if pattern.search(text_):
            children.append(migration.name)
    assert not children, (
        "phase1_19a should be the current alembic head, but the following "
        f"migration files declare it as their down_revision: {children}. "
        "If you intentionally added a child, retire this test (or update "
        "it to point at the new head)."
    )


def test_migration_table_and_index_constants_match_orm_model():
    """The migration's stable name constants (`TABLE`, `INDEX_PENDING`,
    `INDEX_CLAIM`, `UNIQUE_IDEMPOTENCY`) must equal what the ORM model
    declares. Drift on either side breaks downgrade-by-name + future
    migration references."""
    mod = _load_migration_module()
    from app.models import NotificationOutbox

    assert mod.TABLE == NotificationOutbox.__tablename__

    index_names = {idx.name for idx in NotificationOutbox.__table__.indexes}
    assert mod.INDEX_PENDING in index_names, (
        f"Migration constant INDEX_PENDING={mod.INDEX_PENDING!r} not on ORM model; "
        f"model declares: {sorted(index_names)}"
    )
    assert mod.INDEX_CLAIM in index_names, (
        f"Migration constant INDEX_CLAIM={mod.INDEX_CLAIM!r} not on ORM model; "
        f"model declares: {sorted(index_names)}"
    )

    from sqlalchemy import UniqueConstraint

    unique_names = {
        c.name
        for c in NotificationOutbox.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert mod.UNIQUE_IDEMPOTENCY in unique_names, (
        f"Migration constant UNIQUE_IDEMPOTENCY={mod.UNIQUE_IDEMPOTENCY!r} "
        f"not on ORM model; model declares: {sorted(unique_names)}"
    )
