"""
Script to add missing flexible transitions to the allowed_transitions table.
This script only INSERTs new transitions without deleting existing data.

Run with: python scripts/add_missing_transitions.py
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal


# New transitions to add for flexible UX
NEW_TRANSITIONS = [
    # Direct jumps from sts00 (Mới)
    (21, 'sts00', 'sts03', 'user', 'consultation', True, 'Quan tâm ngay từ đầu'),
    (22, 'sts00', 'sts05', 'user', 'consultation', True, 'Hẹn gọi lại'),
    (23, 'sts00', 'sts06', 'user', 'consultation', True, 'Đồng ý tư vấn ngay'),

    # Additional forward transitions
    (24, 'sts02', 'sts06', 'user', 'consultation', True, 'Đồng ý tư vấn'),

    # Forward transitions within same stage (stg02)
    (25, 'sts05', 'sts06', 'user', 'consultation', True, 'Đồng ý sau khi gọi lại'),
    (26, 'sts03', 'sts05', 'user', 'consultation', True, 'Hẹn gọi lại'),
    (27, 'sts06', 'sts03', 'user', 'consultation', True, 'Quay lại quan tâm'),
    (28, 'sts06', 'sts05', 'user', 'consultation', True, 'Hẹn lại'),
    (29, 'sts06', 'sts04', 'user', 'consultation', True, 'Từ chối sau tư vấn'),

    # Finance Phase transitions (Phase 6)
    (30, 'sts10', 'sts18', 'system', 'fee', True, 'Hoàn tiền sau khi đã thanh toán'),
    (31, 'sts09', 'sts10', 'system', 'fee', True, 'Miễn học phí (100% scholarship)'),
]


async def add_missing_transitions():
    """Add missing transitions to the database."""
    async with AsyncSessionLocal() as session:
        # Check existing transitions
        result = await session.execute(
            text("SELECT id FROM allowed_transitions ORDER BY id")
        )
        existing_ids = {row[0] for row in result.fetchall()}
        print(f"Existing transition IDs: {sorted(existing_ids)}")

        # Insert only new transitions
        added = 0
        skipped = 0

        for transition in NEW_TRANSITIONS:
            tid, from_id, to_id, trigger, phase, active, desc = transition

            if tid in existing_ids:
                print(f"  Skipping ID {tid}: already exists")
                skipped += 1
                continue

            # Check if this from->to combination already exists
            check_result = await session.execute(
                text("""
                    SELECT id FROM allowed_transitions
                    WHERE from_status_id = :from_id AND to_status_id = :to_id
                """),
                {"from_id": from_id, "to_id": to_id}
            )
            existing = check_result.fetchone()

            if existing:
                print(f"  Skipping ID {tid}: transition {from_id}->{to_id} exists as ID {existing[0]}")
                skipped += 1
                continue

            # Insert the new transition
            await session.execute(
                text("""
                    INSERT INTO allowed_transitions
                    (id, from_status_id, to_status_id, trigger_type, required_phase, is_active, description)
                    VALUES (:id, :from_id, :to_id, :trigger, :phase, :active, :desc)
                """),
                {
                    "id": tid,
                    "from_id": from_id,
                    "to_id": to_id,
                    "trigger": trigger,
                    "phase": phase,
                    "active": active,
                    "desc": desc,
                }
            )
            print(f"  Added ID {tid}: {from_id} -> {to_id} ({desc})")
            added += 1

        await session.commit()

        print(f"\nSummary: Added {added} transitions, skipped {skipped}")

        # Show final state
        result = await session.execute(
            text("""
                SELECT id, from_status_id, to_status_id, trigger_type, description
                FROM allowed_transitions
                ORDER BY id
            """)
        )
        rows = result.fetchall()
        print(f"\nAll transitions ({len(rows)} total):")
        for row in rows:
            print(f"  {row[0]}: {row[1]} -> {row[2]} ({row[3]}) - {row[4]}")


if __name__ == "__main__":
    asyncio.run(add_missing_transitions())
