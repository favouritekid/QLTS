#!/usr/bin/env python3
"""
Backfill script for Lead Insights cached fields.

Runs update_lead_cache for all existing leads to populate:
- last_consultation_at
- consultation_count
- cached_urgency_score
- is_hot_lead
- is_overdue

Usage:
    cd Backend_FastAPI
    python scripts/backfill_lead_cache.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app import models
from app.services.lead_cache_service import update_lead_cache


async def backfill_all_leads():
    """Backfill cached fields for all leads."""
    async with AsyncSessionLocal() as db:
        # Get total count
        count_result = await db.execute(
            select(func.count(models.Lead.id))
            .where(models.Lead.deleted_at.is_(None))
        )
        total = count_result.scalar() or 0
        print(f"📊 Total leads to backfill: {total}")
        
        if total == 0:
            print("✅ No leads to backfill")
            return
        
        # Get all lead IDs
        result = await db.execute(
            select(models.Lead.id)
            .where(models.Lead.deleted_at.is_(None))
            .order_by(models.Lead.id)
        )
        lead_ids = [row[0] for row in result.all()]
        
        # Process in batches
        batch_size = 50
        updated = 0
        errors = 0
        
        for i in range(0, len(lead_ids), batch_size):
            batch = lead_ids[i:i + batch_size]
            
            for lead_id in batch:
                try:
                    await update_lead_cache(db, lead_id)
                    updated += 1
                except Exception as e:
                    print(f"❌ Error updating lead {lead_id}: {e}")
                    errors += 1
            
            # Commit after each batch
            await db.commit()
            
            progress = min(i + batch_size, len(lead_ids))
            print(f"⏳ Progress: {progress}/{total} ({progress * 100 // total}%)")
        
        print(f"\n✅ Backfill complete!")
        print(f"   Updated: {updated}")
        print(f"   Errors: {errors}")


if __name__ == "__main__":
    print("🚀 Starting Lead Insights Cache Backfill...")
    asyncio.run(backfill_all_leads())
