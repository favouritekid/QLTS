"""q9_07_e0c: seed Casbin policies for Q9 #07 Phase E priority endpoints

Revision ID: q9_07_e0c
Revises: q9_07_e0b
Create Date: 2026-05-19

Q9 #07 Phase E Foundation gap fix — Casbin enforcer reads policies từ
``casbin_rule`` table at request time, so adding entries to
``policy_templates.py`` alone is not enough — without an INSERT migration
each route returns 403 for every caller.

5 routes seeded (Wave 1 + forward-declared Wave 2/3):
* Wave 1 (this PR): preview-priority-kv POST + priority-objects/catalog GET
* Wave 2 forward: override-priority-kv POST (ship Wave 2)
* Wave 3 forward: priority-objects/{sub_code}/verify PATCH + reject PATCH

Per role (matching ``dd5m6n7o8p9q_minor_correction_policy.py`` pattern):
* role:admin ALLOW × 5 (redundant due to ``/*.*``  wildcard but explicit
  for grep-by-route audit consistency)
* role:manager ALLOW × 5 (manager inherits officer via g-rule but seed
  explicit per audit convention)
* role:officer ALLOW × 5 (primary subject — officer write-path)
* role:user ALLOW × 2 (candidate self-fill: preview + catalog only;
  candidate doesn't have override/verify/reject access)
* role:accountant DENY × 5 (separation-of-duties — finance staff không
  view/mutate priority scoring data; mirrors existing accountant DENY
  block in ``ACCOUNTANT_TEMPLATE`` lines 371-377+)

Per memory ``casbin-insert-must-include-eft``: ``v3`` (eft) MUST be
included in INSERT — NULL → ``load_policy()`` crash → 500 every endpoint.

Idempotent ``INSERT ... WHERE NOT EXISTS`` — safe re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q9_07_e0c"
down_revision: Union[str, None] = "q9_07_e0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All 22 policy rows: (v0=subject, v1=object, v2=action, v3=eft)
_PRIORITY_POLICIES = [
    # ---- Wave 1: candidate-facing reads (preview + catalog) ----
    # role:user — candidate self-fill access
    ("role:user", "/api/v2/admissions/*/preview-priority-kv", "POST", "allow"),
    ("role:user", "/api/v2/admissions/priority-objects/catalog", "GET", "allow"),
    # role:officer — officer working on candidate profile
    ("role:officer", "/api/v2/admissions/*/preview-priority-kv", "POST", "allow"),
    ("role:officer", "/api/v2/admissions/priority-objects/catalog", "GET", "allow"),
    # role:manager — explicit for grep audit (inherits officer via g-rule)
    ("role:manager", "/api/v2/admissions/*/preview-priority-kv", "POST", "allow"),
    ("role:manager", "/api/v2/admissions/priority-objects/catalog", "GET", "allow"),
    # role:admin — explicit for grep audit (wildcard handles)
    ("role:admin", "/api/v2/admissions/*/preview-priority-kv", "POST", "allow"),
    ("role:admin", "/api/v2/admissions/priority-objects/catalog", "GET", "allow"),
    # role:accountant — DENY (separation of duties)
    ("role:accountant", "/api/v2/admissions/*/preview-priority-kv", "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/priority-objects/catalog", "GET", "deny"),

    # ---- Wave 2/3: officer-side mutations (forward-declared) ----
    # role:officer — primary subject
    ("role:officer", "/api/v2/admissions/*/override-priority-kv", "POST", "allow"),
    ("role:officer", "/api/v2/admissions/*/priority-objects/*/verify", "PATCH", "allow"),
    ("role:officer", "/api/v2/admissions/*/priority-objects/*/reject", "PATCH", "allow"),
    # role:manager — explicit
    ("role:manager", "/api/v2/admissions/*/override-priority-kv", "POST", "allow"),
    ("role:manager", "/api/v2/admissions/*/priority-objects/*/verify", "PATCH", "allow"),
    ("role:manager", "/api/v2/admissions/*/priority-objects/*/reject", "PATCH", "allow"),
    # role:admin — explicit
    ("role:admin", "/api/v2/admissions/*/override-priority-kv", "POST", "allow"),
    ("role:admin", "/api/v2/admissions/*/priority-objects/*/verify", "PATCH", "allow"),
    ("role:admin", "/api/v2/admissions/*/priority-objects/*/reject", "PATCH", "allow"),
    # role:accountant — DENY
    ("role:accountant", "/api/v2/admissions/*/override-priority-kv", "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/*/priority-objects/*/verify", "PATCH", "deny"),
    ("role:accountant", "/api/v2/admissions/*/priority-objects/*/reject", "PATCH", "deny"),
]


def upgrade() -> None:
    conn = op.get_bind()
    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM casbin_rule "
            "WHERE v1 LIKE '/api/v2/admissions/%priority%'"
            "   OR v1 LIKE '/api/v2/admissions/priority-objects/%'"
        )
    ).scalar()
    print(f"[q9_07_e0c] Pre-flight: existing priority policy rows={pre_count}")

    inserted = 0
    for v0, v1, v2, v3 in _PRIORITY_POLICIES:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_q9_07_e0c_priority_seed',
                       NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype='p'
                      AND v0=CAST(:v0 AS VARCHAR)
                      AND v1=CAST(:v1 AS VARCHAR)
                      AND v2=CAST(:v2 AS VARCHAR)
                      AND v3=CAST(:v3 AS VARCHAR)
                )
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )
        inserted += result.rowcount

    print(f"[q9_07_e0c] Seeded {inserted} new policy row(s).")


def downgrade() -> None:
    conn = op.get_bind()
    deleted = 0
    for v0, v1, v2, v3 in _PRIORITY_POLICIES:
        result = conn.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype='p'
                  AND v0=CAST(:v0 AS VARCHAR)
                  AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR)
                  AND v3=CAST(:v3 AS VARCHAR)
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )
        deleted += result.rowcount
    print(f"[q9_07_e0c] Removed {deleted} policy row(s).")
