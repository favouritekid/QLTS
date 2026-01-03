#!/usr/bin/env python3
"""
Script to configure default admission_rules for all ProgramOfferings.

This sets up a basic admission_rules structure so that admission profiles
can be created for leads in these programs.

Usage:
    python configure_admission_rules.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.config import settings


async def configure_admission_rules():
    """Configure default admission_rules for all ProgramOfferings"""

    print("🔧 Connecting to database...")
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )

    # Import after engine setup to avoid circular imports
    from app.models import ProgramOffering

    async with AsyncSession(engine) as session:
        # First, check offerings without admission_rules
        result = await session.execute(
            select(ProgramOffering).where(ProgramOffering.admission_rules == None)
        )
        offerings_no_rules = result.scalars().all()
        
        print(f"\n📊 ProgramOfferings without admission_rules: {len(offerings_no_rules)}")
        
        if not offerings_no_rules:
            print("✨ All offerings already have admission_rules configured!")
            await engine.dispose()
            return

        # Default admission rules template
        # Structure must match what admission_service.py expects:
        # - min_gpa: float
        # - mandatory_docs: List[str] - document CODES (not objects!)
        # - admission_method: str
        # See _generate_documents_checklist() for valid doc codes:
        # HOC_BA, CCCD, BANG_TN, CMND, GIAY_KHAI_SINH, ANH_3X4, GIAY_KHAM_SUC_KHOE
        default_rules = {
            "min_gpa": 6.0,
            "admission_method": "xét tuyển học bạ",
            "mandatory_docs": [
                "HOC_BA",       # Học bạ THPT
                "CCCD",         # Căn cước công dân
                "ANH_3X4",      # Ảnh 3x4
            ],
        }

        print(f"\n📝 Configuring default admission_rules for {len(offerings_no_rules)} offerings...")
        
        for offering in offerings_no_rules:
            print(f"  → id={offering.id}, type={offering.offering_type}, program_id={offering.program_id}")
            offering.admission_rules = default_rules

        await session.commit()
        print(f"\n✅ Successfully configured {len(offerings_no_rules)} offerings!")

        # Verify
        result2 = await session.execute(
            select(ProgramOffering).where(ProgramOffering.admission_rules == None)
        )
        remaining = result2.scalars().all()
        print(f"📊 Remaining offerings without rules: {len(remaining)}")

    await engine.dispose()
    print("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(configure_admission_rules())
