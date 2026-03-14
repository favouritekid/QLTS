"""phase2: normalize + audit lead_phone_identity backfill

Revision ID: zm2s3t4u5v6w7
Revises: zl1r2s3t4u5v6
Create Date: 2026-03-14 15:00:00.000000

Follow-up repair migration for PR3 phone identity table.

The initial migration (zl1r2s3t4u5v6) backfilled phone_normalized using raw
lead.phone / lead.phone2 values. Two problems:

  A. Raw values were inserted without normalization (runtime uses
     normalize_vietnam_phone() which strips separators and converts +84/84 → 0).
  B. ON CONFLICT DO NOTHING silently dropped rows when two active leads shared
     the same raw phone — those leads are now missing from lead_phone_identity.

This migration:
  1. Audits for orphaned leads (active lead has phone/phone2 but no matching
     identity row) — FAILS FAST with diagnostic output.
  2. Detects normalization conflicts (two active rows would collide after
     normalization) — FAILS FAST with diagnostic output.
  3. Normalizes all phone_normalized values.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "zm2s3t4u5v6w7"
down_revision: Union[str, None] = "zl1r2s3t4u5v6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize_phone_sql() -> str:
    """
    Build a SQL expression that replicates normalize_vietnam_phone() logic:
    1. Strip spaces, dashes, dots, parentheses, slashes, tabs
    2. Convert +84xxx → 0xxx
    3. Convert 84xxxxxxxxx (11-12 chars starting with '84') → 0xxxxxxxxx
    """
    # Step 1: strip separators
    stripped = "phone_normalized"
    for char in [" ", "-", ".", "(", ")", "/", "\t", "\n", "\r"]:
        stripped = f"REPLACE({stripped}, '{char}', '')"

    return f"""
    CASE
        -- +84 prefix → replace with 0
        WHEN {stripped} LIKE '+84%%'
            THEN '0' || SUBSTRING({stripped} FROM 4)
        -- 84 prefix with 11-12 digit length → replace with 0
        WHEN {stripped} LIKE '84%%'
             AND LENGTH({stripped}) IN (11, 12)
            THEN '0' || SUBSTRING({stripped} FROM 3)
        -- Already normalized or other format
        ELSE {stripped}
    END
    """


def upgrade() -> None:
    conn = op.get_bind()

    # Build the normalization expression
    norm_expr = _normalize_phone_sql()

    # Step 0: Audit for orphaned leads — active leads whose phone/phone2
    # was silently dropped by the first migration's ON CONFLICT DO NOTHING
    orphan_audit = text("""
        WITH active_lead_phones AS (
            -- All (lead_id, phone, slot) pairs from active leads
            SELECT id AS lead_id, phone AS raw_phone, 'phone' AS slot
            FROM lead
            WHERE deleted_at IS NULL AND phone IS NOT NULL AND phone != ''
            UNION ALL
            SELECT id AS lead_id, phone2 AS raw_phone, 'phone2' AS slot
            FROM lead
            WHERE deleted_at IS NULL AND phone2 IS NOT NULL AND phone2 != ''
        ),
        existing_identities AS (
            -- All (lead_id, slot) pairs already in identity table
            SELECT lead_id, slot
            FROM lead_phone_identity
            WHERE deleted_at IS NULL
        ),
        orphaned AS (
            SELECT alp.lead_id, alp.raw_phone, alp.slot
            FROM active_lead_phones alp
            LEFT JOIN existing_identities ei
                ON alp.lead_id = ei.lead_id AND alp.slot = ei.slot
            WHERE ei.lead_id IS NULL
        )
        SELECT lead_id, raw_phone, slot
        FROM orphaned
        ORDER BY lead_id, slot
        LIMIT 50
    """)

    result = conn.execute(orphan_audit)
    orphans = result.fetchall()

    if orphans:
        lines = [
            "\n=== PHONE IDENTITY BACKFILL AUDIT: ORPHANED LEADS ===",
            f"Found {len(orphans)} active lead phone(s) missing from lead_phone_identity.",
            "These were silently dropped by the initial migration's ON CONFLICT DO NOTHING.",
            "This means duplicate raw phones existed before migration.\n",
        ]
        for row in orphans:
            lead_id, raw_phone, slot = row
            lines.append(f"  Lead {lead_id}: {slot} = '{raw_phone}'")
        lines.append("")
        lines.append(
            "Action: Resolve duplicate phones in the lead table (merge or reassign),\n"
            "then re-run the initial migration backfill and this migration."
        )
        raise RuntimeError("\n".join(lines))

    print("  [phone_identity_audit] No orphaned leads found. Backfill is complete.")

    # Step 1: Check for conflicts BEFORE updating
    # Find active rows where normalization would produce duplicate phone_normalized
    conflict_check = text(f"""
        WITH normalized AS (
            SELECT
                id,
                lead_id,
                phone_normalized AS raw_phone,
                slot,
                ({norm_expr}) AS norm_phone
            FROM lead_phone_identity
            WHERE deleted_at IS NULL
        ),
        conflicts AS (
            SELECT
                norm_phone,
                ARRAY_AGG(lead_id ORDER BY lead_id) AS lead_ids,
                ARRAY_AGG(raw_phone ORDER BY lead_id) AS raw_phones,
                ARRAY_AGG(slot ORDER BY lead_id) AS slots,
                COUNT(*) AS cnt
            FROM normalized
            GROUP BY norm_phone
            HAVING COUNT(*) > 1
        )
        SELECT norm_phone, lead_ids, raw_phones, slots, cnt
        FROM conflicts
        ORDER BY cnt DESC
        LIMIT 20
    """)

    result = conn.execute(conflict_check)
    conflicts = result.fetchall()

    if conflicts:
        # Build diagnostic message
        lines = [
            "\n=== PHONE IDENTITY NORMALIZATION CONFLICTS ===",
            f"Found {len(conflicts)} conflicting normalized phones.",
            "These must be resolved manually before migration can proceed.\n",
        ]
        for row in conflicts:
            norm_phone, lead_ids, raw_phones, slots, cnt = row
            lines.append(f"  Phone: {norm_phone}")
            lines.append(f"    Leads: {lead_ids}")
            lines.append(f"    Raw values: {raw_phones}")
            lines.append(f"    Slots: {slots}")
            lines.append("")

        lines.append(
            "Action: Fix duplicate phones in the lead table, then re-run migration."
        )
        raise RuntimeError("\n".join(lines))

    # Step 2: No conflicts — apply normalization
    # Use a CTE-based UPDATE to normalize all phone_normalized values
    update_sql = text(f"""
        UPDATE lead_phone_identity
        SET phone_normalized = ({norm_expr})
        WHERE phone_normalized != ({norm_expr})
    """)
    result = conn.execute(update_sql)
    updated = result.rowcount
    print(f"  [phone_identity_normalize] Updated {updated} rows with normalized phone values.")


def downgrade() -> None:
    # Cannot reliably undo normalization (original raw values are lost).
    # The original raw values are still in lead.phone / lead.phone2 if needed.
    pass
