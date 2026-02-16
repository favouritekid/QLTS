"""Add Casbin policy for claim/unclaim endpoints.

Revision ID: idor20260216001
Revises: seed20260214001
Create Date: 2026-02-16

Adds Casbin policies for the new claim/unclaim admission endpoints:
- role:manager can POST /api/admissions/{profile_id}/claim
- role:manager can POST /api/admissions/{profile_id}/unclaim
- role:admin inherits via wildcard (no explicit entry needed)
"""
from alembic import op


revision = "idor20260216001"
down_revision = "seed20260214001"
branch_labels = None
depends_on = None


# Policies to insert (matching existing pattern with {profile_id} placeholder)
POLICIES = [
    ("p", "role:manager", "/api/admissions/{profile_id}/claim", "POST"),
    ("p", "role:manager", "/api/admissions/{profile_id}/unclaim", "POST"),
]


def upgrade() -> None:
    conn = op.get_bind()

    for ptype, v0, v1, v2 in POLICIES:
        # Check if policy already exists (idempotent)
        result = conn.execute(
            op.inline_literal(
                f"SELECT id FROM casbin_rule "
                f"WHERE ptype = '{ptype}' AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'"
            )
        )
        if result.fetchone() is None:
            conn.execute(
                op.inline_literal(
                    f"INSERT INTO casbin_rule (ptype, v0, v1, v2) "
                    f"VALUES ('{ptype}', '{v0}', '{v1}', '{v2}')"
                )
            )


def downgrade() -> None:
    conn = op.get_bind()

    for ptype, v0, v1, v2 in POLICIES:
        conn.execute(
            op.inline_literal(
                f"DELETE FROM casbin_rule "
                f"WHERE ptype = '{ptype}' AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'"
            )
        )
