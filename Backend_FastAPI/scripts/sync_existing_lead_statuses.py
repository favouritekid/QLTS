#!/usr/bin/env python3
"""
One-time data migration script to sync existing lead.status values
with their consultation_status using the Hybrid Approach.

This script should be run AFTER the Alembic migration that adds
the legacy_status column to consultation_status table.

Usage:
    cd Backend_FastAPI
    python -m scripts.sync_existing_lead_statuses

Or with dry-run (no changes):
    python -m scripts.sync_existing_lead_statuses --dry-run
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_engine, AsyncSessionLocal
from app.models import Lead, ConsultationStatus
from app.core.status_mapping import (
    sync_lead_status_from_consultation,
    create_status_info_from_model,
    derive_lead_status,
)


async def sync_lead_statuses(dry_run: bool = False) -> dict:
    """
    Sync all existing lead.status values with their consultation_status.

    Args:
        dry_run: If True, don't commit changes (preview only)

    Returns:
        Dictionary with migration statistics
    """
    stats = {
        "total_leads": 0,
        "synced": 0,
        "unchanged": 0,
        "no_consultation_status": 0,
        "errors": 0,
        "changes": [],  # List of (lead_id, old_status, new_status)
    }

    async with AsyncSessionLocal() as db:
        # Fetch all non-deleted leads with their consultation_status
        stmt = (
            select(Lead, ConsultationStatus)
            .outerjoin(
                ConsultationStatus,
                Lead.consultation_status_id == ConsultationStatus.id
            )
            .where(Lead.deleted_at.is_(None))
            .order_by(Lead.id)
        )

        result = await db.execute(stmt)
        rows = result.all()

        stats["total_leads"] = len(rows)
        print(f"\n📊 Found {stats['total_leads']} leads to process\n")

        for lead, consultation_status in rows:
            try:
                old_status = lead.status

                if consultation_status is None:
                    # No consultation_status, keep existing or set to "new"
                    if old_status in (None, ""):
                        new_status = "new"
                    else:
                        new_status = old_status
                    stats["no_consultation_status"] += 1
                else:
                    # Derive new status using Hybrid Approach
                    status_info = create_status_info_from_model(consultation_status)
                    new_status = derive_lead_status(status_info)

                if old_status != new_status:
                    stats["synced"] += 1
                    stats["changes"].append((lead.id, old_status, new_status))

                    if not dry_run:
                        lead.status = new_status
                        db.add(lead)

                    print(f"  Lead {lead.id}: '{old_status}' → '{new_status}'")
                else:
                    stats["unchanged"] += 1

            except Exception as e:
                stats["errors"] += 1
                print(f"  ❌ Lead {lead.id}: Error - {str(e)}")

        if not dry_run and stats["synced"] > 0:
            await db.commit()
            print(f"\n✅ Committed {stats['synced']} changes to database")
        elif dry_run:
            print(f"\n🔍 DRY RUN - No changes committed")

    return stats


def print_summary(stats: dict, dry_run: bool):
    """Print migration summary."""
    print("\n" + "=" * 60)
    print("📋 MIGRATION SUMMARY")
    print("=" * 60)
    print(f"  Total leads processed:    {stats['total_leads']}")
    print(f"  Status synced:            {stats['synced']}")
    print(f"  Already correct:          {stats['unchanged']}")
    print(f"  No consultation_status:   {stats['no_consultation_status']}")
    print(f"  Errors:                   {stats['errors']}")

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes were made")
        if stats["synced"] > 0:
            print(f"    Run without --dry-run to apply {stats['synced']} changes")
    else:
        if stats["synced"] > 0:
            print(f"\n✅ Successfully synced {stats['synced']} lead statuses")
        else:
            print("\n✅ All lead statuses are already in sync")

    print("=" * 60 + "\n")


async def main():
    parser = argparse.ArgumentParser(
        description="Sync existing lead.status values with consultation_status"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without committing to database"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("🔄 LEAD STATUS SYNC MIGRATION")
    print("=" * 60)
    print(f"Mode: {'DRY RUN (preview only)' if args.dry_run else 'LIVE (will commit changes)'}")

    try:
        stats = await sync_lead_statuses(dry_run=args.dry_run)
        print_summary(stats, args.dry_run)

        # Exit with error code if there were errors
        if stats["errors"] > 0:
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Migration failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
