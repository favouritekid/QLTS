"""
Script to remove invalid backward transitions from allowed_transitions table.

These transitions were incorrectly added and violate business logic:
- sts05 -> sts02: Goes from stg02 (Đang tư vấn) back to stg01 (Chưa tư vấn)
- sts03 -> sts02: Goes from stg02 (Đang tư vấn) back to stg01 (Chưa tư vấn)

Run with: python scripts/remove_invalid_transitions.py
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import AsyncSessionLocal


# Invalid backward transitions to remove
INVALID_TRANSITIONS = [
    ('sts05', 'sts02', 'Đã kết nối lại'),      # stg02 -> stg01 (backward)
    ('sts03', 'sts02', 'Quay lại liên hệ'),    # stg02 -> stg01 (backward)
]


async def remove_invalid_transitions():
    """Remove invalid backward transitions from the database."""
    async with AsyncSessionLocal() as session:
        print("Checking for invalid backward transitions...")

        removed = 0
        for from_id, to_id, desc in INVALID_TRANSITIONS:
            # Check if transition exists
            result = await session.execute(
                text("""
                    SELECT id, from_status_id, to_status_id, description
                    FROM allowed_transitions
                    WHERE from_status_id = :from_id AND to_status_id = :to_id
                """),
                {"from_id": from_id, "to_id": to_id}
            )
            existing = result.fetchone()

            if existing:
                print(f"  Found ID {existing[0]}: {existing[1]} -> {existing[2]} ({existing[3]})")

                # Delete the invalid transition
                await session.execute(
                    text("""
                        DELETE FROM allowed_transitions
                        WHERE from_status_id = :from_id AND to_status_id = :to_id
                    """),
                    {"from_id": from_id, "to_id": to_id}
                )
                print(f"    -> REMOVED")
                removed += 1
            else:
                print(f"  Not found: {from_id} -> {to_id} ({desc})")

        await session.commit()

        print(f"\nSummary: Removed {removed} invalid transitions")

        # Verify remaining transitions
        result = await session.execute(
            text("""
                SELECT COUNT(*) FROM allowed_transitions
            """)
        )
        total = result.scalar()
        print(f"Total transitions remaining: {total}")


if __name__ == "__main__":
    asyncio.run(remove_invalid_transitions())
