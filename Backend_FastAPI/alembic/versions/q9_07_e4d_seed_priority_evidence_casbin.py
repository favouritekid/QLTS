"""q9_07_e4d: seed Casbin policies for Phase E.4 priority-evidence endpoints

Revision ID: q9_07_e4d
Revises: q9_07_e4c
Create Date: 2026-05-20

Q9 #07 Phase E.4 PR-2 — 2 NEW endpoints (upload + delete priority evidence)
need Casbin seed. ``policy_templates.py`` được update tại cùng commit
(officer ALLOW block + accountant DENY block) — script ``sync_casbin_policy``
sẽ catch on next deploy boot, NHƯNG migration cũng seed để dev DB không cần
manual restart pickup template change.

8 rows seeded:
* role:officer ALLOW × 2 (POST upload + DELETE untick — primary subject)
* role:manager ALLOW × 2 (explicit grep audit, inherits officer)
* role:admin ALLOW × 2 (explicit grep audit, wildcard catches)
* role:accountant DENY × 2 (separation-of-duties — finance staff không
  scan/manage UT minh chứng)

Per memory ``casbin-insert-must-include-eft``: v3 (eft) MUST be included
in INSERT — NULL → ``load_policy()`` crash → 500 every endpoint.

Idempotent ``INSERT ... WHERE NOT EXISTS`` — safe re-run sau template sync.

Note: role:user (candidate) KHÔNG có access — officer-driven paradigm
(officer scan giấy từ candidate hồ sơ vật lý). Public portal không exist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q9_07_e4d"
down_revision: Union[str, None] = "q9_07_e4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All 8 policy rows: (v0=subject, v1=object, v2=action, v3=eft)
_PRIORITY_EVIDENCE_POLICIES = [
    # role:officer — primary subject (officer write-path)
    ("role:officer", "/api/v2/admissions/*/priority-evidence/*/upload", "POST", "allow"),
    ("role:officer", "/api/v2/admissions/*/priority-evidence/*", "DELETE", "allow"),
    # role:manager — explicit for grep audit (inherits officer via g-rule)
    ("role:manager", "/api/v2/admissions/*/priority-evidence/*/upload", "POST", "allow"),
    ("role:manager", "/api/v2/admissions/*/priority-evidence/*", "DELETE", "allow"),
    # role:admin — explicit for grep audit (wildcard /*.*  handles)
    ("role:admin", "/api/v2/admissions/*/priority-evidence/*/upload", "POST", "allow"),
    ("role:admin", "/api/v2/admissions/*/priority-evidence/*", "DELETE", "allow"),
    # role:accountant — DENY (separation-of-duties)
    ("role:accountant", "/api/v2/admissions/*/priority-evidence/*/upload", "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/*/priority-evidence/*", "DELETE", "deny"),
]


def upgrade() -> None:
    conn = op.get_bind()
    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM casbin_rule "
            "WHERE v1 LIKE '/api/v2/admissions/%priority-evidence%'"
        )
    ).scalar()
    print(f"[q9_07_e4d] Pre-flight: existing priority-evidence policy rows={pre_count}")

    inserted = 0
    for v0, v1, v2, v3 in _PRIORITY_EVIDENCE_POLICIES:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_q9_07_e4d_priority_evidence_seed',
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

    print(f"[q9_07_e4d] Seeded {inserted} new policy row(s).")


def downgrade() -> None:
    conn = op.get_bind()
    deleted = 0
    for v0, v1, v2, v3 in _PRIORITY_EVIDENCE_POLICIES:
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
    print(f"[q9_07_e4d] Removed {deleted} policy row(s).")
