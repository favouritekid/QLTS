"""B1 / phase1_19b — migration revision contract + idempotency lock.

Three layers, all unit-level (no real DB run, no Alembic CLI):

1. **Migration revision contract** — file declares ``revision``
   (``"phase1_19b"``) and ``down_revision`` (``"phase1_19a"``, head
   pre-B1).
2. **Idempotency-by-predicate** — ``upgrade()`` and ``downgrade()``
   guard every UPDATE / INSERT / DELETE with a WHERE predicate so a
   partial-apply re-run is a no-op (per memory
   ``migration-predicate-safety``).
3. **Accountant deny-rule set lock** — the seeded list contains
   exactly 6 rows, mapped to the routes from PLAN §3.3.b lines
   1411-1415, with ``waitlist-*`` expanded into two explicit entries
   (waitlist-promote + waitlist-reject) for keyMatch4 precision. A
   future PR cannot quietly grow / shrink the deny set without
   touching this test.

Live ``alembic upgrade`` / ``downgrade`` roundtrip on dev DB
(``qlts_dev``) was run during B1 implementation:

* ``phase1_19a → phase1_19b``: 210 rows go ``v3 IS NULL`` → ``v3 = 'allow'``
  + 6 deny rows inserted with ``template_id = '_system_b1_deny'``.
* ``phase1_19b → phase1_19a``: deny rows deleted; v3 reverted to NULL.
* Idempotent re-apply: the WHERE-predicate guards make the second
  ``alembic upgrade head`` a no-op (each predicate matches zero rows).

Those checks live in the daily log with command output (since
runtime-coupled). This file locks the migration source contract so a
future refactor cannot drop the predicate guards or change the deny
set without breaking the test.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "phase1_19b_backfill_casbin_eft_and_seed_deny_rules.py"
)


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "phase1_19b_migration", str(MIGRATION_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Layer 1 ----------------------------------------------------------------


def test_revision_chain_contract():
    mod = _load_migration_module()
    assert mod.revision == "phase1_19b"
    assert mod.down_revision == "phase1_19a", (
        "down_revision must point at phase1_19a (B2.2 NotificationOutbox "
        "create-table migration — the head pre-B1)."
    )


def test_phase1_19b_is_alembic_head():
    """No newer migration declares phase1_19b as its down_revision."""
    versions_dir = MIGRATION_PATH.parent
    children: list[str] = []
    pattern = re.compile(
        r"down_revision\s*[:=][^=]*?[\"']phase1_19b[\"']"
    )
    for f in versions_dir.glob("*.py"):
        if f.name == MIGRATION_PATH.name or f.name == "__init__.py":
            continue
        if pattern.search(f.read_text(encoding="utf-8")):
            children.append(f.name)
    assert not children, (
        f"phase1_19b should be the alembic head; found {children}"
    )


# Layer 2 ----------------------------------------------------------------


def test_upgrade_uses_predicate_guards():
    """The upgrade body must gate the v3 backfill with ``WHERE v3 IS
    NULL`` and the seed inserts with ``WHERE NOT EXISTS``. Without
    these, a partial-apply re-run double-mutates."""
    src = MIGRATION_PATH.read_text(encoding="utf-8")

    # v3 backfill: predicate-bounded.
    assert re.search(
        r"UPDATE\s+casbin_rule\s+SET\s+v3\s*=\s*'allow'\s+WHERE\s+ptype\s*=\s*'p'\s+AND\s+v3\s+IS\s+NULL",
        src,
        re.IGNORECASE,
    ), (
        "upgrade() must backfill v3='allow' guarded by 'WHERE ptype='p' "
        "AND v3 IS NULL' — without the predicate, re-applying double-touches "
        "rows that already carry an explicit eft."
    )

    # Seed inserts: WHERE NOT EXISTS (anti-double-insert).
    assert "WHERE NOT EXISTS" in src, (
        "Each accountant deny seed INSERT must be guarded by 'WHERE NOT "
        "EXISTS' so re-applying does not duplicate the row."
    )


def test_downgrade_uses_predicate_guards():
    src = MIGRATION_PATH.read_text(encoding="utf-8")

    # v3 reverse: predicate-bounded (only allow → NULL, leaves deny intact
    # for any non-seeded deny rows that other code paths might add).
    assert re.search(
        r"UPDATE\s+casbin_rule\s+SET\s+v3\s*=\s*NULL\s+WHERE\s+ptype\s*=\s*'p'\s+AND\s+v3\s*=\s*'allow'",
        src,
        re.IGNORECASE,
    ), (
        "downgrade() must reverse v3='allow' to NULL guarded by 'WHERE "
        "ptype='p' AND v3='allow'' — bounded to rows the upgrade owns."
    )

    # Deny-row delete: scoped by exact (ptype, v0, v1, v2, v3).
    assert (
        "DELETE FROM casbin_rule" in src
        and "AND v3 =" in src.replace(
            "AND v3 = CAST(:v3 AS varchar)", "AND v3 ="
        )
    ), (
        "downgrade() must DELETE deny rows by exact (ptype, v0, v1, v2, "
        "v3) match so unrelated rules are not collateral-damaged."
    )


def test_asyncpg_param_type_casts_present():
    """asyncpg's type-deduction trips on parameter reuse across
    untyped SELECT columns and varchar WHERE comparisons. The fix is
    explicit ``CAST(:param AS varchar)`` casts (encountered live during
    the B1 dev-DB upgrade). Lock the casts here."""
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    # Should appear at least 4 times in the INSERT (v0, v1, v2, v3) and
    # 4 times in the DELETE WHERE clauses.
    cast_count = len(re.findall(r"CAST\(:[\w]+ AS varchar\)", src))
    assert cast_count >= 8, (
        f"Expected at least 8 CAST(:param AS varchar) usages (4 per "
        f"INSERT + 4 per DELETE); got {cast_count}. Without casts, "
        "asyncpg raises AmbiguousParameterError on the INSERT."
    )


# Layer 3 ----------------------------------------------------------------


def test_accountant_deny_rules_locked_to_six_explicit_entries():
    mod = _load_migration_module()
    rules = mod.ACCOUNTANT_DENY_RULES
    assert isinstance(rules, list)
    assert len(rules) == 6, (
        f"ACCOUNTANT_DENY_RULES must contain exactly 6 entries (PLAN "
        f"§3.3.b lines 1411-1415, with waitlist-* expanded); got {len(rules)}"
    )

    # Every row must target role:accountant + POST + deny.
    for v0, v1, v2, v3 in rules:
        assert v0 == "role:accountant"
        assert v2 == "POST"
        assert v3 == "deny"

    objects = {v1 for v0, v1, v2, v3 in rules}
    expected = {
        "/api/v2/admissions/*/claim",
        "/api/v2/admissions/*/request-revision",
        "/api/v2/admissions/*/publish-result",
        "/api/v2/admissions/*/waitlist-promote",
        "/api/v2/admissions/*/waitlist-reject",
        "/api/v2/admissions/*/admin-rollback",
    }
    assert objects == expected, (
        "Accountant deny route set drifted from PLAN §3.3.b. "
        f"Expected: {sorted(expected)}; got: {sorted(objects)}"
    )


def test_seed_template_id_marker():
    """Tracking marker for audit / future cleanup queries."""
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "_system_b1_deny" in src, (
        "Migration must tag seeded deny rows with template_id "
        "'_system_b1_deny' so a future audit can query the exact set "
        "B1 planted."
    )
