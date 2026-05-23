"""sl20260524 — suspicious login canonical fingerprint migration contract.

Three layers, all unit-level (no DB / no Alembic CLI):

1. **Revision chain lock** — file declares ``revision='sl20260524_canonical'``
   and ``down_revision='cleanup_upper_notif'`` (PR-1 #327's head).
2. **Helper parity + immutability** — migration ships LOCAL helpers
   ``_generate_device_fingerprint_canonical_v1`` and
   ``_generate_device_fingerprint_old_display_v1`` that MUST match the
   service helper output bit-for-bit at this commit. Locking parity here
   prevents a future service-side refactor from silently desynchronising
   the migration. The local copies are intentionally NOT imported from
   ``app.services.login_history_service`` so the migration replays
   deterministically months later even after the service evolves.
3. **Source-code contract** — every behavioural promise in the plan
   (single-transaction, NULL-safe merge, tombstone restore, ON CONFLICT
   DO UPDATE, dedupe merge metadata, idempotent backup) is anchored to a
   SQL/Python pattern in the migration body. A future refactor that
   loses any of these guarantees will break a test.

Real alembic ``upgrade head`` / ``downgrade -1`` / re-upgrade roundtrip
on the dev DB is the integration gate — run during PR review with
operator switching stacks (D:\\QLTS down → option-b worktree up). The
roundtrip logs go in the PR description. This file is the contract
sentinel for everything that can be checked without standing the stack
up.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import re
from pathlib import Path
from types import ModuleType

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "sl20260524_suspicious_login_canonical.py"
)


@pytest.fixture
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sl20260524_migration", str(MIGRATION_PATH)
    )
    assert spec is not None and spec.loader is not None, (
        f"Cannot load migration {MIGRATION_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ===========================================================================
# Layer 1 — Revision chain
# ===========================================================================


def test_revision_id(migration):
    assert migration.revision == "sl20260524_canonical", (
        "Revision ID is part of the alembic chain — renaming breaks any "
        "downstream migration that lists this as down_revision."
    )


def test_down_revision_chains_off_pr1(migration):
    """Migration revises off PR-1 #327's head ``cleanup_upper_notif``.

    If a NEW migration lands between Commit 1 and merge, this revision
    must be rebased to chain off the new head OR the new migration must
    bump its down_revision to point to ``sl20260524_canonical``.
    """
    assert migration.down_revision == "cleanup_upper_notif"


# ===========================================================================
# Layer 2 — Helper parity + immutability
# ===========================================================================


def test_local_helpers_exposed(migration):
    """Migration ships immutable local helpers — NOT imported from service.

    Re-running this migration months/years later (replay on fresh DB,
    staging restore, or in-place rebuild) must produce identical
    fingerprints regardless of how the service helper evolves. Hence
    the migration carries its own pinned copy.
    """
    assert callable(getattr(migration, "_generate_device_fingerprint_canonical_v1", None))
    assert callable(getattr(migration, "_generate_device_fingerprint_old_display_v1", None))
    assert callable(getattr(migration, "_get_salt", None))


def test_no_service_helper_import(migration):
    """Migration must not import ``generate_device_fingerprint`` from service.

    Importing would couple migration replay to service-side state at run
    time — a service refactor (rename, signature change, salt source
    change) would silently break replay. The local copies pin the exact
    commit-time logic.

    Scope: scan executable lines only (skip docstrings) so cross-references
    in module-level documentation don't trip the import guard.
    """
    src = inspect.getsource(migration)

    # Filter out docstring blocks AND ``#`` comments so the only remaining
    # matches are real executable Python (imports, calls). The migration's
    # module-level explainer comments deliberately mention the service
    # path ("MUST NOT import from app.services.login_history_service") and
    # that's documentation, not a real import — we don't want the test
    # to trip on the docs.
    import re as _re
    src_executable = _re.sub(r'"""[\s\S]*?"""', '', src)
    src_executable = _re.sub(r"'''[\s\S]*?'''", '', src_executable)
    # Strip whole-line + trailing ``# comment`` content.
    src_executable = "\n".join(
        _re.sub(r"\s*#.*$", "", line) for line in src_executable.splitlines()
    )

    # Real import statement: matches ``from app.services.login_history_service``
    # at line start (after optional whitespace).
    assert not _re.search(
        r"(?m)^\s*from\s+app\.services\.login_history_service\b",
        src_executable,
    ), (
        "Migration must NOT import from login_history_service — use the "
        "local pinned helpers instead so replay is reproducible."
    )
    # Permit module-level mention only via the local pinned symbol names
    # (they contain the canonical name as a substring).
    bare_calls = _re.findall(
        r"\bgenerate_device_fingerprint\b(?!_canonical_v1|_old_display_v1)",
        src_executable,
    )
    assert not bare_calls, (
        f"Found {len(bare_calls)} bare ``generate_device_fingerprint`` "
        "reference(s) outside the pinned local helpers — migration must "
        "only use _generate_device_fingerprint_canonical_v1 / _old_display_v1."
    )


def test_canonical_helper_parity_with_service(migration):
    """Local canonical helper output MUST match service helper output.

    Asserted across 6 sample inputs covering: standard display, None
    handling, salt mixing, user_id stringification, and the exact case
    from the user 16 bug repro (Mobile Safari + iOS).

    If this test fails after a service refactor, the migration is
    out-of-date — generate a NEW migration with an updated local helper
    rather than editing this one in place.
    """
    from app.services.login_history_service import generate_device_fingerprint
    from app.config import settings

    salt = settings.DEVICE_FINGERPRINT_SALT

    samples = [
        # (browser_family, os_family, device_type, user_id) — canonical inputs.
        # Post-Commit 2 the service helper accepts ``browser_family=`` /
        # ``os_family=`` kwargs to mirror the migration's local copy.
        ("Mobile Safari", "iOS", "mobile", 16),
        ("Chrome", "Windows", "desktop", 16),
        ("Chrome", "Mac OS X", "desktop", 42),
        ("Firefox", "Linux", "desktop", 1),
        (None, None, None, None),
        ("Mobile Safari", "iOS", "mobile", None),  # anonymous
    ]
    for browser_family, os_family, device_type, user_id in samples:
        service_fp = generate_device_fingerprint(
            browser_family=browser_family,
            os_family=os_family,
            device_type=device_type,
            user_id=user_id,
        )
        local_fp = migration._generate_device_fingerprint_canonical_v1(
            browser_family, os_family, device_type, user_id, salt
        )
        assert service_fp == local_fp, (
            f"Helper parity broken for inputs "
            f"({browser_family!r}, {os_family!r}, {device_type!r}, user_id={user_id!r}): "
            f"service={service_fp}, local={local_fp}. "
            "Either service helper was refactored or migration local copy "
            "drifted — must align."
        )


def test_old_display_helper_matches_canonical_shape(migration):
    """At Commit 1 (this migration), old_display_v1 is IDENTICAL in shape
    to canonical_v1 — both hash 5 components in the same order with the
    same separator. The distinction is purely SEMANTIC: callers feed
    display strings to old_display_v1 and family strings to canonical_v1.
    Locking the shape here ensures the downgrade path produces hashes
    that the PRE-Commit-2 service code (which hashes display strings)
    would have produced.
    """
    salt = "dummy-salt-for-parity-test"
    # Identical components → identical hash (regardless of helper name).
    fp_canon = migration._generate_device_fingerprint_canonical_v1(
        "Mobile Safari 26.4", "iOS 18.7", "mobile", 16, salt
    )
    fp_old = migration._generate_device_fingerprint_old_display_v1(
        "Mobile Safari 26.4", "iOS 18.7", "mobile", 16, salt
    )
    assert fp_canon == fp_old, (
        "old_display_v1 and canonical_v1 must agree when fed the same "
        "inputs. The two helpers exist for SEMANTIC clarity (callers "
        "feed different string forms) — the hash function itself is "
        "the same SHA-256 over '|'-joined components."
    )


def test_canonical_helper_handles_none(migration):
    """``None`` inputs → 'unknown' / 'anonymous' fallback per service contract.

    Pinning fallback behaviour is critical for backfill of pre-PR rows
    where ``device_type`` is NULL (loop in Step 4 / Step 5b).
    """
    salt = "dummy-salt"
    fp_all_none = migration._generate_device_fingerprint_canonical_v1(
        None, None, None, None, salt
    )
    # Expected: hash of 'unknown|unknown|unknown|anonymous|{salt}'
    expected = hashlib.sha256(
        f"unknown|unknown|unknown|anonymous|{salt}".encode()
    ).hexdigest()
    assert fp_all_none == expected


# ===========================================================================
# Layer 3 — Upgrade source contract
# ===========================================================================


def test_upgrade_creates_backup_with_idempotent_guard(migration):
    """Step 1: backup table is recreated on every upgrade. The DROP IF
    EXISTS guard makes re-upgrade after downgrade idempotent (downgrade
    keeps the backup so the operator can verify; subsequent upgrade
    overwrites without conflict).
    """
    src = inspect.getsource(migration.upgrade)
    assert "DROP TABLE IF EXISTS trusted_device_pre_sl20260524_canonical_backup" in src
    assert "CREATE TABLE trusted_device_pre_sl20260524_canonical_backup" in src
    assert "AS SELECT * FROM trusted_device" in src


def test_upgrade_adds_login_history_canonical_columns(migration):
    src = inspect.getsource(migration.upgrade)
    for col in ("browser_family", "os_family", "device_fingerprint"):
        # Must be added to login_history — verify via column name + table reference.
        # The op.add_column calls reference both table and column.
        pattern = rf'"login_history",\s*sa\.Column\("{col}"'
        assert re.search(pattern, src, re.DOTALL), (
            f"login_history.{col} column add missing — must be in upgrade()."
        )


def test_upgrade_adds_trusted_device_canonical_columns(migration):
    """trusted_device gets ``browser_family``, ``os_family``, and the
    critical ``device_type`` (blocker B1.v4) — canonical fingerprint
    inputs need device_type which pre-PR trusted_device didn't have.
    """
    src = inspect.getsource(migration.upgrade)
    for col in ("browser_family", "os_family", "device_type"):
        pattern = rf'"trusted_device",\s*sa\.Column\("{col}"'
        assert re.search(pattern, src, re.DOTALL), (
            f"trusted_device.{col} column add missing — Blocker B1.v4."
        )


def test_upgrade_creates_fingerprint_index(migration):
    """Step 2: ``ix_login_history_user_fp_response`` enables fast
    ``check_device_seen_before`` lookups (post-Commit 3 query path).
    """
    src = inspect.getsource(migration.upgrade)
    assert "ix_login_history_user_fp_response" in src
    assert "login_history" in src
    # Index columns: user_id, device_fingerprint, user_response
    assert re.search(
        r'"ix_login_history_user_fp_response".*?"login_history".*?'
        r'"user_id".*?"device_fingerprint".*?"user_response"',
        src, re.DOTALL,
    ), "Index must cover (user_id, device_fingerprint, user_response) in order."


def test_upgrade_backfills_family_via_regex(migration):
    """Step 4 / Step 6: family columns backfilled from display strings via
    Postgres ``regexp_replace`` — strips trailing version-like suffix.

    Verifies the regex constant is used (not inlined repeatedly).
    """
    src = inspect.getsource(migration.upgrade)
    assert "_VERSION_SUFFIX_REGEX_PG" in src, (
        "Family backfill must use the named regex constant for clarity."
    )
    # Both login_history and trusted_device backfilled.
    assert "UPDATE login_history SET" in src
    assert "UPDATE trusted_device SET" in src


def test_upgrade_backfills_fingerprint_via_local_helper(migration):
    """Step 4: login_history.device_fingerprint computed via the LOCAL
    canonical helper (not the service helper). Critical for replay
    reproducibility per Blocker B2.v5.
    """
    src = inspect.getsource(migration.upgrade)
    assert "_generate_device_fingerprint_canonical_v1" in src
    # Must NOT use the service helper inside upgrade body.
    upgrade_only = src
    assert "from app.services.login_history_service import" not in upgrade_only


def test_upgrade_device_type_backfill_with_fallback(migration):
    """Step 5: trusted_device.device_type backfilled by JOIN with
    login_history (closest trusted_at). Step 5b: fallback heuristic for
    unmatched rows, with audit log per fallback (Blocker B1.v4 + audit).
    """
    src = inspect.getsource(migration.upgrade)

    # Step 5 JOIN with closest trusted_at via abs(extract(epoch))
    assert "DISTINCT ON (td2.id)" in src
    assert "abs(extract(epoch FROM lh.login_at - td2.trusted_at))" in src

    # Step 5b fallback for device_type IS NULL
    assert "device_type IS NULL" in src
    # Heuristic must check ios/android/windows phone for mobile
    assert '"ios"' in src.lower() or "'ios'" in src.lower() or "ios" in src.lower()
    assert "android" in src.lower()
    # Fallback audit log via log.warning
    assert "device_type fallback heuristic" in src or "fallback_device_type" in src


def test_upgrade_creates_merge_map(migration):
    """Step 7b: merge_map table with versioned name + idempotent DROP guard.
    Holds (loser_id, winner_id, user_id, old_fp, new_fp) for tombstone
    detection in downgrade (V9.P0 — preserve user-deleted devices).
    """
    src = inspect.getsource(migration.upgrade)
    assert "DROP TABLE IF EXISTS trusted_device_sl20260524_merge_map" in src
    assert "CREATE TABLE trusted_device_sl20260524_merge_map" in src
    # Schema columns
    for col in ("loser_id", "winner_id", "user_id", "old_fingerprint", "new_fingerprint"):
        assert col in src, f"merge_map missing column {col}"


def test_upgrade_dedupe_merges_metadata(migration):
    """Step 7: dedupe MERGE — winner = oldest first_seen_at, losers
    metadata merged (last_used_at = MAX, IP/name from row with newest
    last_used_at). Winner gets canonical fingerprint.
    """
    src = inspect.getsource(migration.upgrade)
    # Group ordering for winner selection
    assert "ORDER BY first_seen_at ASC NULLS LAST, id ASC" in src
    # MAX(last_used_at) merge
    assert "max_last_used" in src or "MAX(last_used_at)" in src
    # latest_row IP / name carried forward
    assert "trusted_from_ip" in src

    # DELETE losers before UPDATE winner (UNIQUE collision safe).
    # The migration has TWO update paths: (a) single-row group (no
    # losers → only UPDATE) and (b) multi-row group (DELETE losers THEN
    # UPDATE winner). We anchor the ordering check to the multi-row
    # branch by slicing source from the DELETE statement onward and
    # asserting the next ``device_fingerprint = :fp`` UPDATE that
    # follows is the winner-update.
    delete_marker = "DELETE FROM trusted_device WHERE id = ANY(:ids)"
    delete_idx = src.find(delete_marker)
    assert delete_idx >= 0, "Multi-row DELETE statement missing"

    # First UPDATE following the DELETE — that's the winner update.
    post_delete_src = src[delete_idx:]
    winner_update_idx = post_delete_src.find("device_fingerprint = :fp")
    assert winner_update_idx >= 0, (
        "Winner UPDATE (`device_fingerprint = :fp`) does not appear after "
        "the multi-row DELETE — order violates UNIQUE collision invariant."
    )


def test_upgrade_writes_merge_map_audit(migration):
    """Each merge writes an audit row to merge_map AND a structlog line.
    Both are required for downgrade tombstone resolution + forensic.
    """
    src = inspect.getsource(migration.upgrade)
    assert "INSERT INTO trusted_device_sl20260524_merge_map" in src
    # structlog warning/info per merge
    assert "log.info" in src or "log.warning" in src
    assert "merging trusted_device" in src or "merge" in src.lower()


# ===========================================================================
# Layer 4 — Downgrade source contract
# ===========================================================================


def test_downgrade_snapshots_current_then_identifies_new_rows(migration):
    """Step D1: snapshot FULL current trusted_device. Step D2: subset
    rows whose id is NOT in backup → new rows (post-deploy writes).
    Per V7.P0 #1: must snapshot ALL current rows (not just new) to also
    preserve updates on existing rows.
    """
    src = inspect.getsource(migration.downgrade)
    assert "_td_current_snapshot" in src
    assert "_td_new_rows" in src
    # Snapshot FULL current (no WHERE filter)
    snapshot_match = re.search(
        r"_td_current_snapshot.*?SELECT\s+\*\s+FROM\s+trusted_device",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert snapshot_match, (
        "Step D1 must snapshot ALL current trusted_device rows (no WHERE) "
        "— required for Step D5 MERGE updates on existing rows."
    )
    # New rows = current NOT IN backup via LEFT JOIN ... IS NULL
    assert re.search(
        r"LEFT JOIN trusted_device_pre_sl20260524_canonical_backup",
        src, re.IGNORECASE,
    )
    assert "WHERE b.id IS NULL" in src


def test_downgrade_rehashes_new_rows_with_old_display_helper(migration):
    """Step D3: new rows re-hashed via ``_generate_device_fingerprint_old_display_v1``
    so the reverted (pre-PR) service code can match them.
    """
    src = inspect.getsource(migration.downgrade)
    assert "_generate_device_fingerprint_old_display_v1" in src


def test_downgrade_restore_is_tombstone_aware(migration):
    """Step D4: CONDITIONAL restore — only rows whose winner is still
    alive in current snapshot, OR rows that are losers of a still-alive
    winner (via merge_map). User-deleted devices are NOT resurrected.

    This is the V9.P0 security-critical guarantee — downgrade must not
    override the user's explicit revoke decision (secure_account / single
    delete / remove_all_devices).
    """
    src = inspect.getsource(migration.downgrade)

    # The migration body uses multi-line ``op.execute(text("..." "..."))``
    # Python string concatenation, so ``inspect.getsource`` returns
    # literal ``"`` and newlines that would defeat a strict SQL regex.
    # Normalize by stripping the Python quote-newline noise so the
    # remaining text reads as flowing SQL.
    flat = re.sub(r'"\s*\n\s*"', " ", src)
    flat = re.sub(r"\s+", " ", flat)

    # Path 1: winner still alive (id match in current snapshot).
    assert re.search(
        r"EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+_td_current_snapshot\s+c\s+WHERE\s+c\.id\s*=\s*b\.id",
        flat, re.IGNORECASE,
    ), "Tombstone Path 1 (winner alive) missing"

    # Path 2: backup row is loser of an alive winner (via merge_map).
    assert re.search(
        r"EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+trusted_device_sl20260524_merge_map\s+m",
        flat, re.IGNORECASE,
    ), "Tombstone Path 2 (loser of alive winner via merge_map) missing"
    assert "m.loser_id = b.id" in flat


def test_downgrade_merge_existing_is_null_safe(migration):
    """Step D5: UPDATE existing rows from current snapshot. NULL-safe
    GREATEST via '-infinity'::timestamptz sentinel + NULLIF to restore
    NULL when both sides NULL (V9.P1 fix — SQL pattern, not just comment).

    Critical because TrustedDevice.last_used_at is nullable; plain
    ``s.last_used_at > t.last_used_at`` evaluates NULL → falsy with
    Postgres three-valued logic, dropping post-deploy IP/name updates
    onto NULL backup rows.
    """
    src = inspect.getsource(migration.downgrade)
    # The Step D5 UPDATE block
    update_block = re.search(
        r"UPDATE trusted_device t SET.*?WHERE t\.id = s\.id",
        src, re.DOTALL,
    )
    assert update_block, "Step D5 UPDATE block missing"
    block_src = update_block.group(0)

    # NULLIF wrapping for last_used_at (both NULL → NULL output)
    assert "NULLIF" in block_src
    # GREATEST + COALESCE with -infinity sentinel
    assert "GREATEST" in block_src
    assert "'-infinity'::timestamptz" in block_src
    # CASE for IP and name using same NULL-safe comparison
    assert "trusted_from_ip" in block_src
    assert "name" in block_src
    assert block_src.count("COALESCE") >= 4, (
        "Expected COALESCE on both sides in last_used_at + IP CASE + name CASE — "
        "at least 4 occurrences."
    )


def test_downgrade_insert_new_rows_uses_on_conflict_do_update(migration):
    """Step D6: INSERT new rows. ON CONFLICT (user_id, device_fingerprint)
    DO UPDATE merges metadata if a new row's OLD display fingerprint
    collides with a restored backup row (V7.P0 #2 — was DO NOTHING which
    silently dropped metadata).
    """
    src = inspect.getsource(migration.downgrade)
    assert "ON CONFLICT (user_id, device_fingerprint) DO UPDATE SET" in src
    # Must NOT be DO NOTHING (regression guard)
    assert "DO NOTHING" not in src or src.find("DO NOTHING") > src.find(
        "ON CONFLICT (user_id, device_fingerprint) DO UPDATE SET"
    ), "ON CONFLICT must be DO UPDATE for the new-rows insert (V7.P0 #2)."
    # NULL-safe merge inside ON CONFLICT clause
    on_conflict_block = re.search(
        r"ON CONFLICT \(user_id, device_fingerprint\) DO UPDATE SET.*",
        src, re.DOTALL,
    )
    assert on_conflict_block
    assert "GREATEST" in on_conflict_block.group(0)
    assert "'-infinity'::timestamptz" in on_conflict_block.group(0)
    assert "NULLIF" in on_conflict_block.group(0)


def test_downgrade_drops_merge_map_and_all_columns(migration):
    """Step D7: drop merge_map (idempotent for re-upgrade) + drop all 6
    new columns + drop index. Backup table KEPT (operator drops manually
    after stable verification).
    """
    src = inspect.getsource(migration.downgrade)
    assert "DROP TABLE IF EXISTS trusted_device_sl20260524_merge_map" in src
    # All 6 columns dropped
    for col in ("browser_family", "os_family", "device_fingerprint"):
        assert f'op.drop_column("login_history", "{col}")' in src, (
            f"login_history.{col} drop missing in downgrade"
        )
    for col in ("browser_family", "os_family", "device_type"):
        assert f'op.drop_column("trusted_device", "{col}")' in src, (
            f"trusted_device.{col} drop missing in downgrade"
        )
    # Index drop
    assert "ix_login_history_user_fp_response" in src
    assert "drop_index" in src

    # Backup table NOT dropped — operator's manual decision.
    assert "DROP TABLE IF EXISTS trusted_device_pre_sl20260524_canonical_backup" not in src
    assert "DROP TABLE trusted_device_pre_sl20260524_canonical_backup" not in src


def test_downgrade_resets_sequence(migration):
    """Step D7: reset trusted_device_id_seq to MAX(id) so future INSERTs
    don't collide with restored backup IDs.
    """
    src = inspect.getsource(migration.downgrade)
    assert "setval('trusted_device_id_seq'" in src
    assert "MAX(id)" in src


# ===========================================================================
# Layer 5 — Cross-cutting invariants
# ===========================================================================


def test_no_per_batch_commit_in_loops(migration):
    """Migration must NOT call ``conn.commit()`` / ``op.commit()`` / a
    SAVEPOINT inside any loop (V8.B1 fix). Entire upgrade is one Alembic
    transaction so a mid-migration failure rolls back cleanly.
    """
    src = inspect.getsource(migration)
    # Forbid explicit commit calls anywhere in upgrade/downgrade
    assert "conn.commit()" not in src
    assert "session.commit()" not in src
    # SAVEPOINTs are also a sign of nested transaction management
    assert "SAVEPOINT" not in src


def test_idempotent_temp_table_creation(migration):
    """Downgrade TEMP tables ``_td_current_snapshot`` and ``_td_new_rows``
    are dropped at session end automatically. The DROP IF EXISTS guards
    in downgrade make manual reruns safe.
    """
    src = inspect.getsource(migration.downgrade)
    assert "DROP TABLE IF EXISTS _td_current_snapshot" in src
    assert "DROP TABLE IF EXISTS _td_new_rows" in src


def test_audit_logging_uses_module_logger(migration):
    """Audit log calls use ``log = logging.getLogger("alembic.runtime.migration")``
    so output flows through Alembic's logging pipeline and shows up in
    deploy logs.
    """
    src = inspect.getsource(migration)
    assert 'logging.getLogger("alembic.runtime.migration")' in src
    # At minimum: backup row count, login_history backfill count, dedupe summary
    assert src.count("log.info") >= 3
    # Fallback heuristic warning
    assert "log.warning" in src
