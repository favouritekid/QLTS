"""Backfill NULL assigned_officer_id on leads with admission profiles.

Revision ID: idor20260216002
Revises: idor20260216001
Create Date: 2026-02-16

After IDOR tightening, officers can only see profiles assigned to them.
Leads with NULL assigned_officer_id would become invisible to officers.

This migration assigns such leads to the first active officer in the same unit.
Leads in units without active officers remain NULL (require manual manager assign).
"""
from alembic import op
import sqlalchemy as sa


revision = "idor20260216002"
down_revision = "idor20260216001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Backfill: assign NULL leads to first active officer in same unit
    conn.execute(sa.text("""
        UPDATE lead SET assigned_officer_id = sub.officer_id
        FROM (
            SELECT l.id AS lead_id, (
                SELECT u.id FROM "user" u
                WHERE u.unit_id = l.unit_id
                AND u.role = 'officer'
                AND u.status = 'active'
                ORDER BY u.id
                LIMIT 1
            ) AS officer_id
            FROM lead l
            JOIN admission_profile ap ON ap.lead_id = l.id
            WHERE l.assigned_officer_id IS NULL
            AND l.unit_id IS NOT NULL
        ) sub
        WHERE lead.id = sub.lead_id
        AND sub.officer_id IS NOT NULL
    """))

    # Post-migration verification: log remaining NULL leads
    result = conn.execute(sa.text("""
        SELECT l.id, l.full_name, l.unit_id
        FROM lead l
        JOIN admission_profile ap ON ap.lead_id = l.id
        WHERE l.assigned_officer_id IS NULL
    """))
    remaining = result.fetchall()
    if remaining:
        print(f"WARNING: {len(remaining)} leads still have NULL assigned_officer_id after backfill.")
        print("These leads are in units without active officers. Manager must assign manually:")
        for row in remaining:
            print(f"  Lead ID={row[0]}, Name={row[1]}, Unit ID={row[2]}")


def downgrade() -> None:
    # Cannot reliably restore original NULL values
    # This is a data migration - downgrade is a no-op
    pass
