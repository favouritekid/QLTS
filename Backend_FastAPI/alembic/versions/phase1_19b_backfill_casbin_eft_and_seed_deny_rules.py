"""B1 — backfill ``casbin_rule.v3='allow'`` + seed accountant deny rules.

Pre-flight evidence (probed 2026-05-03 on dev DB before any code change):

* The Casbin Python lib's ``AsyncEnforcer.enforce()`` raises
  ``RuntimeError("invalid policy size")`` when the model declares
  ``p = sub, obj, act, eft`` (4 tokens) and a loaded rule has only 3
  values (``core_enforcer.py:447-448``). The
  ``casbin_async_sqlalchemy_adapter`` ``CasbinRule.__str__`` breaks at
  the first ``None`` v-column (``adapter.py:42-46``), so a row with
  ``v3 IS NULL`` serialises to a 3-value rule and triggers the
  mismatch.
* ``SELECT v3 IS NULL, COUNT(*) FROM casbin_rule WHERE ptype='p' GROUP
  BY 1`` on the dev DB returned 210/210 ``v3 IS NULL``.
* Therefore B1 cannot land standalone: flipping ``auth_model.conf``
  to 4-field WITHOUT first writing ``v3='allow'`` for the 210 legacy
  rows would crash ``enforcer.enforce()`` on every request.

This migration runs BEFORE the new ``auth_model.conf`` is loaded by
the FastAPI lifespan in production. The runbook §7.2 cutover step
T+3:00 backfills + restarts at T+3:15 with
``RUN_CASBIN_LOAD_ON_STARTUP=false`` cleared so the enforcer reloads
against the backfilled DB.

Two operations, both idempotent:

1. **Backfill ``v3='allow'``** on every existing ``ptype='p'`` row
   that still has ``v3 IS NULL``. Predicate-guarded so re-running is a
   no-op. Other ptypes (``g`` for inheritance) are untouched — they
   already encode subject/role pairs in v0/v1 only and the new model
   does not alter the role_definition.

2. **Seed 6 accountant deny rules** for the admission state-machine
   routes accountant must NOT drive (per PLAN §3.3.b lines 1411-1415,
   with the ``waitlist-*`` wildcard expanded to ``waitlist-promote`` +
   ``waitlist-reject`` so each row is keyMatch4-precise). Each insert
   is guarded by a ``WHERE NOT EXISTS`` so re-running is a no-op.

Downgrade reverses both:

1. Delete the 6 deny rows by exact (ptype, v0, v1, v2, v3) match.
2. Restore ``v3=NULL`` on every ``ptype='p'`` row that still has
   ``v3='allow'``. This is symmetric to the upgrade backfill — rows
   that were created post-B1 with explicit ``eft='deny'`` are
   untouched.

Idempotency notes (per memory ``migration-predicate-safety``):

* Strict predicates: every UPDATE / DELETE / INSERT is gated by a
  ``WHERE`` clause that matches only the rows this migration owns.
* Pre-merge prod state audit: 210 rows with ``v3 IS NULL`` confirmed
  on dev DB; production replays the same shape because schema /
  seed code matches.
* No assumption that the migration is the first writer of ``v3``;
  later seeds (``add_policies_batch`` post-B1) write ``v3='allow'``
  or ``v3='deny'`` explicitly and this migration's predicate
  ``WHERE v3 IS NULL`` skips them.

Revision ID: phase1_19b
Revises: phase1_19a
Create Date: 2026-05-03
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "phase1_19b"
down_revision: Union[str, None] = "phase1_19a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Stable list of accountant deny rules (PLAN §3.3.b lines 1411-1415,
# waitlist-* expanded). Referenced from both upgrade INSERTs and
# downgrade DELETEs, plus the test matrix lock so growth is gated.
ACCOUNTANT_DENY_RULES: list[tuple[str, str, str, str]] = [
    ("role:accountant", "/api/v2/admissions/*/claim",            "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/*/request-revision", "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/*/publish-result",   "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/*/waitlist-promote", "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/*/waitlist-reject",  "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/*/admin-rollback",   "POST", "deny"),
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Backfill v3='allow' on legacy rows (idempotent — predicate-only
    # touches v3 IS NULL, leaves anything already explicitly set).
    bind.execute(
        text(
            """
            UPDATE casbin_rule
            SET v3 = 'allow'
            WHERE ptype = 'p'
              AND v3 IS NULL
            """
        )
    )

    # 2) Seed accountant deny rules (idempotent — WHERE NOT EXISTS guard).
    # The applied_at + template_id columns are nullable on this table;
    # if they exist (post-bootstrap) we populate them, otherwise the
    # NULL default is fine. We use `template_id='_system_b1_deny'`
    # so a future audit can find the exact set of rows this migration
    # planted. NOW() is a transaction-scoped timestamp; OK for an audit
    # marker.
    # Each parameter is cast to ``::varchar`` explicitly. asyncpg's
    # type-deduction infers parameter types from the first usage; with
    # the same ``:v0`` referenced both in an untyped INSERT SELECT
    # column position and a varchar comparison in the WHERE NOT EXISTS,
    # asyncpg raises ``AmbiguousParameterError: inconsistent types
    # deduced for parameter $1 (text versus character varying)``. The
    # cast pins the type to ``varchar`` so both usages agree.
    for v0, v1, v2, v3 in ACCOUNTANT_DENY_RULES:
        bind.execute(
            text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT
                    CAST('p' AS varchar),
                    CAST(:v0 AS varchar),
                    CAST(:v1 AS varchar),
                    CAST(:v2 AS varchar),
                    CAST(:v3 AS varchar),
                    CAST('_system_b1_deny' AS varchar),
                    NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype = 'p'
                      AND v0 = CAST(:v0 AS varchar)
                      AND v1 = CAST(:v1 AS varchar)
                      AND v2 = CAST(:v2 AS varchar)
                      AND v3 = CAST(:v3 AS varchar)
                )
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )


def downgrade() -> None:
    bind = op.get_bind()

    # 1) Drop the 6 accountant deny rows by exact match. Bounded by
    # the seeded tuple so any unrelated 'role:accountant' rule planted
    # by other code paths is left alone. Same asyncpg cast caveat as
    # the upgrade INSERT applies.
    for v0, v1, v2, v3 in ACCOUNTANT_DENY_RULES:
        bind.execute(
            text(
                """
                DELETE FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = CAST(:v0 AS varchar)
                  AND v1 = CAST(:v1 AS varchar)
                  AND v2 = CAST(:v2 AS varchar)
                  AND v3 = CAST(:v3 AS varchar)
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )

    # 2) Reverse the v3='allow' backfill. Predicate restricts to rows
    # this migration would have touched on upgrade — explicit
    # eft='deny' rows survive (their downgrade is the DELETE above for
    # the seeded set; any custom 'deny' rules a later operator added
    # are left intact). After this UPDATE, every ptype='p' row has
    # v3 IS NULL again, restoring the pre-B1 shape required by the
    # 3-field auth_model.conf.
    bind.execute(
        text(
            """
            UPDATE casbin_rule
            SET v3 = NULL
            WHERE ptype = 'p'
              AND v3 = 'allow'
            """
        )
    )
