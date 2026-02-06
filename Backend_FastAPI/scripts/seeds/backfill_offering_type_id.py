# scripts/seeds/backfill_offering_type_id.py
"""
Backfill offering_type_id for existing ProgramOffering records.

This script matches ProgramOffering.offering_type (String) with
ConfigOfferingType.code and populates the new FK column.

Usage:
    wsl bash -c "cd /mnt/d/QLTS/Backend_FastAPI && source venv/bin/activate && python -m scripts.seeds.backfill_offering_type_id"
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.program_offering import ProgramOffering
from app.models.config import ConfigOfferingType


async def backfill_offering_type_id(db: AsyncSession):
    """Match offering_type string with ConfigOfferingType and populate FK."""
    print("=" * 60)
    print("🔗 BACKFILL: ProgramOffering.offering_type_id")
    print("=" * 60)
    
    # Step 1: Get all ConfigOfferingType records
    result = await db.execute(select(ConfigOfferingType))
    offering_types = result.scalars().all()
    
    # Build lookup: code -> id, name -> id
    code_to_id = {}
    name_to_id = {}
    for ot in offering_types:
        code_to_id[ot.code.lower()] = ot.id
        name_to_id[ot.name.lower()] = ot.id
        print(f"   ConfigOfferingType: {ot.code} / {ot.name} (id={ot.id})")
    
    if not offering_types:
        print("   ⚠️ No ConfigOfferingType records found!")
        print("   Please seed ConfigOfferingType first.")
        return
    
    # Step 2: Get all ProgramOffering records
    result = await db.execute(
        select(ProgramOffering)
        .where(ProgramOffering.offering_type_id.is_(None))
    )
    offerings = result.scalars().all()
    
    print(f"\n📋 Found {len(offerings)} ProgramOffering records without offering_type_id")
    
    # Step 3: Match and update
    matched = 0
    unmatched = []
    
    for offering in offerings:
        offering_type_str = offering.offering_type.lower().strip()
        
        # Try to match by code first, then by name
        offering_type_id = (
            code_to_id.get(offering_type_str) or 
            name_to_id.get(offering_type_str)
        )
        
        if offering_type_id:
            offering.offering_type_id = offering_type_id
            matched += 1
        else:
            unmatched.append(offering.offering_type)
    
    await db.commit()
    
    # Report
    print(f"\n✅ Matched: {matched} records")
    
    if unmatched:
        unique_unmatched = set(unmatched)
        print(f"⚠️ Unmatched ({len(unique_unmatched)} unique values):")
        for val in sorted(unique_unmatched)[:10]:
            print(f"   - '{val}'")
        if len(unique_unmatched) > 10:
            print(f"   ... and {len(unique_unmatched) - 10} more")
        print("\n   You may need to:")
        print("   1. Add missing ConfigOfferingType records")
        print("   2. Or normalize offering_type strings in ProgramOffering")


async def main():
    """Main backfill function."""
    async with AsyncSessionLocal() as db:
        await backfill_offering_type_id(db)
        
    print("\n" + "=" * 60)
    print("✅ BACKFILL COMPLETE!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
