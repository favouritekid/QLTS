"""q9_07_e4f: remove officer override-priority-kv policy (commit 7 hardening)

Revision ID: q9_07_e4f
Revises: q9_07_e4e
Create Date: 2026-05-21

Q9 #07 Phase E.4 commit 7 — KV override permission hardening per yêu cầu
nghiệp vụ #10: officer KHÔNG được override KV. Chỉ admin/manager.

Pre-commit 7 state (seeded ở q9_07_e0c):
  - role:officer allow override-priority-kv POST
  - role:manager allow override-priority-kv POST
  - role:admin allow override-priority-kv POST
  - role:accountant deny

Post-commit 7 state:
  - role:officer DELETED (hard-deny ở service layer + Casbin)
  - role:manager allow (unchanged)
  - role:admin allow (unchanged)
  - role:accountant deny (unchanged)

Service-level priority_override_service.override_kv() cũng raise
BusinessRuleViolation cho actor.role=="officer" — defense-in-depth.

Idempotent: DELETE WHERE (cụ thể 4-tuple) — safe re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q9_07_e4f"
down_revision: Union[str, None] = "q9_07_e4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Single row removal — officer override-priority-kv allow
_OFFICER_OVERRIDE_KV_POLICY = (
    "role:officer",
    "/api/v2/admissions/*/override-priority-kv",
    "POST",
    "allow",
)


def upgrade() -> None:
    conn = op.get_bind()
    v0, v1, v2, v3 = _OFFICER_OVERRIDE_KV_POLICY

    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM casbin_rule "
            "WHERE ptype='p' AND v0=:v0 AND v1=:v1 AND v2=:v2 AND v3=:v3"
        ),
        {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
    ).scalar()
    print(
        f"[q9_07_e4f] Pre-flight: existing officer override-priority-kv "
        f"rows={pre_count} (expected 1 if q9_07_e0c applied)"
    )

    result = conn.execute(
        sa.text(
            "DELETE FROM casbin_rule "
            "WHERE ptype='p' AND v0=:v0 AND v1=:v1 AND v2=:v2 AND v3=:v3"
        ),
        {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
    )
    print(f"[q9_07_e4f] Removed {result.rowcount} officer override-priority-kv row(s).")


def downgrade() -> None:
    """Re-insert officer policy row (revert to pre-commit 7 state).

    Note: service-layer hard-deny officer remains active even after downgrade
    (code change in priority_override_service.override_kv). Downgrade is for
    schema-level rollback only; full revert requires git revert of commit 7.
    """
    conn = op.get_bind()
    v0, v1, v2, v3 = _OFFICER_OVERRIDE_KV_POLICY

    result = conn.execute(
        sa.text(
            """
            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
            SELECT 'p',
                   CAST(:v0 AS VARCHAR),
                   CAST(:v1 AS VARCHAR),
                   CAST(:v2 AS VARCHAR),
                   CAST(:v3 AS VARCHAR),
                   '_q9_07_e4f_downgrade_restore',
                   NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype='p' AND v0=CAST(:v0 AS VARCHAR)
                  AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR)
                  AND v3=CAST(:v3 AS VARCHAR)
            )
            """
        ),
        {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
    )
    print(f"[q9_07_e4f] Downgrade: re-inserted {result.rowcount} officer policy row(s).")
