"""gpcasbin01: seed Casbin policy for graduation-proof update endpoint

Revision ID: gpcasbin01
Revises: gpkind01
Create Date: 2026-06-04

PR #13.4b — NEW endpoint ``POST /api/admissions/{id}/documents/{doc_code}/
graduation-proof`` lets an officer upgrade a graduation proof
(provisional_cert → official_diploma) WITHOUT changing doc status. It is
defended by ``CasbinAuth`` and therefore needs a Casbin policy row, exactly
like ``paper-submitted`` (PR #5, migration ``zz7h8i9j0k1l2``).

``policy_templates.py`` is updated in the SAME commit (one ALLOW row added to
``OFFICER_TEMPLATE`` right after paper-submitted). To keep "fresh seed +
this migration → same end state", we seed ONLY the single ``role:officer``
ALLOW row that the template fresh-seed produces. Manager + admin reach the
route via the diamond inheritance g-rules (``g, role:manager, role:officer``
and the admin ``/*`` ``.*`` wildcard) — exactly the paper-submitted contract.

Accountant: no deny row, mirroring paper-submitted. Finance staff never pass
the owning-officer IDOR scope check in ``update_graduation_proof_kind``
(``get_profile``), so a Casbin allow they inherit is moot — and the
paper-submitted family deliberately carries no accountant deny.

Per memory ``casbin-insert-must-include-eft``: v3 (eft) MUST be present in
the INSERT — a NULL eft makes ``load_policy()`` crash → 500 on every
endpoint. Idempotent ``INSERT ... WHERE NOT EXISTS`` so reruns (and the boot
``sync_casbin_policy`` template pickup) are safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "gpcasbin01"
down_revision: Union[str, None] = "gpkind01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Single row: (v0=subject, v1=object, v2=action, v3=eft). Mirrors the lone
# row added to OFFICER_TEMPLATE — manager/admin inherit, accountant moot.
_GRADUATION_PROOF_POLICIES = [
    (
        "role:officer",
        "/api/admissions/{id}/documents/{doc_code}/graduation-proof",
        "POST",
        "allow",
    ),
]


def upgrade() -> None:
    conn = op.get_bind()
    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM casbin_rule "
            "WHERE v1 LIKE '/api/admissions/%documents%graduation-proof'"
        )
    ).scalar()
    print(
        f"[gpcasbin01] Pre-flight: existing graduation-proof policy "
        f"rows={pre_count}"
    )

    inserted = 0
    for v0, v1, v2, v3 in _GRADUATION_PROOF_POLICIES:
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
                       '_gpcasbin01_graduation_proof_seed',
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

    print(f"[gpcasbin01] Seeded {inserted} new policy row(s).")


def downgrade() -> None:
    conn = op.get_bind()
    deleted = 0
    for v0, v1, v2, v3 in _GRADUATION_PROOF_POLICIES:
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
    print(f"[gpcasbin01] Removed {deleted} policy row(s).")
