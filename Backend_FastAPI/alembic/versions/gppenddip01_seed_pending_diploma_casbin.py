"""gppenddip01: seed Casbin policy for the pending-diploma reminder endpoint

Revision ID: gppenddip01
Revises: gpcasbin01
Create Date: 2026-06-04

PR #13.7 — NEW read endpoint ``GET /api/admissions/pending-diploma`` lists
profiles that still owe the official diploma ("nợ bằng"). It is defended by
``CasbinAuth`` and therefore needs Casbin policy rows. ``policy_templates.py``
is updated in the SAME commit (officer ALLOW + accountant DENY).

2 rows seeded, mirroring the ``/stats`` / ``/status-counts`` read routes:
* role:officer ALLOW — primary subject (officer follows up on the debt; the
  service IDOR-scopes to assigned profiles). Manager + admin inherit via the
  diamond g-rules.
* role:accountant DENY — the list carries candidate PII (name/phone);
  finance staff have no business need + separation-of-duties. accountant
  inherits officer, so without this explicit deny the inherited ALLOW would
  leak the list.

Per memory ``casbin-insert-must-include-eft``: v3 (eft) MUST be present —
NULL eft makes ``load_policy()`` crash → 500. Idempotent
``INSERT ... WHERE NOT EXISTS`` so reruns + boot template sync are safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "gppenddip01"
down_revision: Union[str, None] = "gpcasbin01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (v0=subject, v1=object, v2=action, v3=eft)
_PENDING_DIPLOMA_POLICIES = [
    ("role:officer", "/api/admissions/pending-diploma", "GET", "allow"),
    ("role:accountant", "/api/admissions/pending-diploma", "GET", "deny"),
]


def upgrade() -> None:
    conn = op.get_bind()
    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM casbin_rule "
            "WHERE v1 = '/api/admissions/pending-diploma'"
        )
    ).scalar()
    print(
        f"[gppenddip01] Pre-flight: existing pending-diploma policy "
        f"rows={pre_count}"
    )

    inserted = 0
    for v0, v1, v2, v3 in _PENDING_DIPLOMA_POLICIES:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule
                    (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_gppenddip01_pending_diploma_seed',
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

    print(f"[gppenddip01] Seeded {inserted} new policy row(s).")


def downgrade() -> None:
    conn = op.get_bind()
    deleted = 0
    for v0, v1, v2, v3 in _PENDING_DIPLOMA_POLICIES:
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
    print(f"[gppenddip01] Removed {deleted} policy row(s).")
