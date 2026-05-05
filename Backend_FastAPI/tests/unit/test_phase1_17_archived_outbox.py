"""Unit tests for #184 Wave 5-E migration ``phase1_17_create_archived_outbox_table``.

Companion test to ``test_phase1_16_archived_admission_profile.py``. Locks the
revision chain, table name, the column-mirror invariant against the live
``NotificationOutbox`` model, the archive metadata column, the
``archived_at`` index per Option II chốt 2026-05-05, the dropped surface (UQ
idempotency_key + 2 partial worker-only indexes), the no-FK/UQ/CHECK shape,
and the idempotent guard surface.

Live alembic roundtrip is DEFERRED to staging clone D12-D14 (same dev DB
drift workaround as Wave 5-D — `alembic_version` stamped without upgrade
body execution for Wave 2 artifacts).

What lives here:
1. Revision row + chain (``phase1_17`` → ``phase1_16``).
2. Underscore-prefixed table name ``_archived_notification_outbox``.
3. Mirror parity — every ``NotificationOutbox`` column name appears in the
   migration source (re-derived, NOT hardcoded) — anchor non-tautological.
4. Archive metadata column ``archived_at`` shape.
5. ``ix_archived_outbox_archived_at`` single-column index per Option II.
6. NO FK / UQ / CHECK constraints (archive must accept historical violators).
7. UQ ``idempotency_key`` from source NOT mirrored (drop on archive).
8. Source's worker-only partial indexes (``ix_outbox_pending`` /
   ``ix_outbox_claim`` WHERE dispatched_at IS NULL) NOT mirrored.
9. Idempotent guards (``table_exists`` + ``index_exists``) on both upgrade
   and downgrade paths.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_17 = _VERSIONS_DIR / "phase1_17_create_archived_outbox_table.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_17.stem, _PHASE1_17)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_17():
    return _load_migration()


@pytest.fixture
def src() -> str:
    return _PHASE1_17.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_17_revision_id(phase1_17) -> None:
    assert phase1_17.revision == "phase1_17"


def test_phase1_17_chains_off_phase1_16(phase1_17) -> None:
    """Wave 5 ship-order chốt 2026-05-05 Codex round 19: phase1_17 follows
    phase1_16 (Wave 5-D), so phase1_19d (Wave 5-B archive task body) can
    register knowing this table exists."""
    assert phase1_17.down_revision == "phase1_16"


# ---------------------------------------------------------------------------
# 2. Table name + index name
# ---------------------------------------------------------------------------


def test_phase1_17_uses_underscore_prefixed_table_name(phase1_17) -> None:
    """PLAN line 176, 178, 3465, 3495 ALL use the leading-underscore
    convention to mark this as an internal/archive table."""
    assert phase1_17.TABLE == "_archived_notification_outbox"


def test_phase1_17_index_name_matches_option_ii(phase1_17) -> None:
    """Option II chốt 2026-05-05 — ``archived_at`` single-column index for
    typical admin time-range queries."""
    assert phase1_17.INDEX_ARCHIVED_AT == "ix_archived_outbox_archived_at"


# ---------------------------------------------------------------------------
# 3. Column mirror parity — re-derived from NotificationOutbox model
# ---------------------------------------------------------------------------


def test_phase1_17_mirrors_every_notification_outbox_column(src) -> None:
    """Re-derive the column list from the live ``NotificationOutbox`` model
    instead of hardcoding it (memory ``verify-schema-before-proposing`` +
    ``pattern-change-impact-audit``). A later schema rename to source must
    not silently drift from the archive mirror."""
    from app.models.notification_outbox import NotificationOutbox

    source_columns = {c.name for c in NotificationOutbox.__table__.columns}

    missing = []
    for column_name in source_columns:
        if f'"{column_name}"' not in src:
            missing.append(column_name)

    assert not missing, (
        f"phase1_17 archive table missing NotificationOutbox columns: {missing}"
    )


def test_phase1_17_column_count_matches_source_plus_one(src) -> None:
    """Archive table = source columns + exactly 1 archive-metadata column
    (``archived_at``). No extra audit/discriminator columns."""
    from app.models.notification_outbox import NotificationOutbox

    source_count = len(NotificationOutbox.__table__.columns)
    column_decls = re.findall(r'sa\.Column\(\s*"([a-z_]+)"', src)
    unique = set(column_decls)
    assert len(unique) == source_count + 1, (
        f"Expected {source_count + 1} columns "
        f"({source_count} source + 1 archived_at), got {len(unique)}: {unique}"
    )


# ---------------------------------------------------------------------------
# 4. Archive metadata column
# ---------------------------------------------------------------------------


def test_phase1_17_archived_at_is_not_null_with_now_default(src) -> None:
    """``archived_at`` is the cron's INSERT marker — NOT NULL with
    ``DEFAULT now()`` so the cron INSERT does not need to set it
    explicitly."""
    pattern = re.compile(
        r'sa\.Column\(\s*"archived_at"[^)]*?'
        r'sa\.DateTime\(timezone=True\)[^)]*?'
        r'nullable=False[^)]*?'
        r'server_default=sa\.text\("now\(\)"\)',
        re.DOTALL,
    )
    assert pattern.search(src), "archived_at column shape mismatch"


# ---------------------------------------------------------------------------
# 5. Index — Option II single column
# ---------------------------------------------------------------------------


def test_phase1_17_creates_archived_at_index(src) -> None:
    """Option II chốt — single-column index on ``archived_at`` for admin
    time-range queries."""
    assert "ix_archived_outbox_archived_at" in src
    # Single column, not composite — verify only `archived_at` appears
    # inside the create_index call's column list.
    pattern = re.compile(
        r'op\.create_index\(\s*INDEX_ARCHIVED_AT[^)]*?'
        r'\[\s*"archived_at"\s*\]',
        re.DOTALL,
    )
    assert pattern.search(src), (
        "Index must be single-column on archived_at (Option II chốt)"
    )


# ---------------------------------------------------------------------------
# 6. No FK / UQ / CHECK constraints
# ---------------------------------------------------------------------------


def test_phase1_17_declares_no_foreign_keys(src) -> None:
    """Source notification_outbox has no FKs either — symmetry preserved."""
    assert "ForeignKey(" not in src


def test_phase1_17_drops_idempotency_key_unique(src) -> None:
    """Source has ``UniqueConstraint("idempotency_key", ...)`` (notification
    _outbox.py:113-116). On the archive side this is dropped — archived rows
    are outside the worker's dedupe window so the live UNIQUE contract no
    longer needs to extend across the archive."""
    # The idempotency_key column itself MUST appear (mirror parity) but
    # NO UNIQUE constraint or `unique=True` flag may decorate it.
    assert '"idempotency_key"' in src  # mirror present
    assert "UniqueConstraint" not in src
    assert "unique=True" not in src


def test_phase1_17_declares_no_check_constraints(src) -> None:
    """Archive must round-trip historical rows even if live contract
    evolves."""
    assert "CheckConstraint" not in src


# ---------------------------------------------------------------------------
# 7. No partial worker-only indexes
# ---------------------------------------------------------------------------


def test_phase1_17_does_not_mirror_worker_partial_indexes(src) -> None:
    """Source's ``ix_outbox_pending`` + ``ix_outbox_claim`` partial-WHERE
    ``dispatched_at IS NULL`` filters serve the worker's claim path. Every
    archived row has ``dispatched_at IS NOT NULL`` (cron's archive
    predicate) — these partial indexes would match zero rows on the
    archive.

    Scope check to the executable body (between ``def upgrade():`` and
    ``def downgrade():``) so the rationale text in the module docstring
    can name the dropped indexes without the assertion misfiring."""
    upgrade_body = src[
        src.index("def upgrade()") : src.index("def downgrade()")
    ]
    assert "ix_outbox_pending" not in upgrade_body
    assert "ix_outbox_claim" not in upgrade_body
    assert "postgresql_where" not in upgrade_body


# ---------------------------------------------------------------------------
# 8. Idempotent guards
# ---------------------------------------------------------------------------


def test_phase1_17_upgrade_guards_table_create(src) -> None:
    """Idempotent re-run: a half-applied upgrade re-running must skip the
    ``CREATE TABLE`` if the table already exists."""
    assert "if not table_exists(TABLE):" in src


def test_phase1_17_upgrade_guards_index_create(src) -> None:
    assert "if not index_exists(TABLE, INDEX_ARCHIVED_AT):" in src


def test_phase1_17_downgrade_short_circuits_when_table_missing(src) -> None:
    """Per ``phase1_19a`` template — drop_index against a missing parent
    table raises; downgrade returns early when the table is already gone."""
    pattern = re.compile(
        r"def downgrade\(\) -> None:\s*"
        r"(?:#[^\n]*\n\s*)*"
        r"if not table_exists\(TABLE\):\s*\n\s*return",
        re.MULTILINE,
    )
    assert pattern.search(src), (
        "downgrade() must short-circuit when the table is already gone"
    )


def test_phase1_17_downgrade_drops_index_before_table(src) -> None:
    """Even though ``DROP TABLE`` cascades indexes, the explicit
    ``drop_index`` call lets a half-applied downgrade resume safely."""
    downgrade_block = src[src.index("def downgrade("):]
    drop_index_pos = downgrade_block.index("op.drop_index(")
    drop_table_pos = downgrade_block.index("op.drop_table(")
    assert drop_index_pos < drop_table_pos


# ---------------------------------------------------------------------------
# 9. Module sanity
# ---------------------------------------------------------------------------


def test_phase1_17_defines_upgrade_and_downgrade(phase1_17) -> None:
    assert callable(getattr(phase1_17, "upgrade", None))
    assert callable(getattr(phase1_17, "downgrade", None))
