import asyncio
import sys
import os
import random
from faker import Faker
from sqlalchemy import select, func
from datetime import datetime, timedelta

# Add current directory to sys.path to ensure imports work
sys.path.append(os.getcwd())

from app.database import AsyncSessionLocal
from app.models.lead import Lead, LeadSourceEnum
from app.models.pipeline import ConsultationStatus
from app.models.organization import OrganizationUnit

# Initialize Faker
fake = Faker('vi_VN')

async def seed_leads():
    async with AsyncSessionLocal() as session:
        print("🚀 Starting seed script...")

        # 1. Fetch Organization Unit (Lead needs a unit_id)
        unit = (await session.execute(select(OrganizationUnit))).scalars().first()
        if not unit:
            print("⚠️ No Organization Unit found. Creating one...")
            unit = OrganizationUnit(name="Ban Tuyển Sinh", type="department")
            session.add(unit)
            await session.commit()
            await session.refresh(unit)
        
        print(f"✅ Using Unit: {unit.name} (ID: {unit.id})")

        # 2. Fetch Consultation Statuses (Phase = 'consultation')
        # If 'phase' column query fails (if schema mismatch), fallback to all statuses
        try:
            stmt = select(ConsultationStatus).where(ConsultationStatus.phase == 'consultation')
            statuses = (await session.execute(stmt)).scalars().all()
        except Exception as e:
            print(f"⚠️ Could not filter by phase='consultation' ({e}). Fetching all statuses.")
            stmt = select(ConsultationStatus)
            statuses = (await session.execute(stmt)).scalars().all()

        if not statuses:
            print("❌ No Consultation Statuses found! Please seed statuses first.")
            return

        status_ids = [s.id for s in statuses]
        print(f"✅ Found {len(statuses)} statuses in 'consultation' phase: {status_ids}")

        # 3. Generate 3000 Leads
        leads_to_create = []
        BATCH_SIZE = 500
        TOTAL_LEADS = 3000

        print(f"🔄 Generating {TOTAL_LEADS} leads...")

        for i in range(TOTAL_LEADS):
            # Randomize creation time within last 30 days
            created_at = datetime.now() - timedelta(days=random.randint(0, 30))
            
            lead = Lead(
                full_name=fake.name(),
                email=fake.email(),
                phone=fake.phone_number(),
                source=random.choice(list(LeadSourceEnum)).value,
                status="new", # Default lead status
                assignment_status="pending",
                consultation_status_id=random.choice(status_ids),
                unit_id=unit.id,
                created_at=created_at,
                updated_at=created_at,
                lead_score=random.randint(0, 100),
            )
            leads_to_create.append(lead)

            # Insert in batches
            if len(leads_to_create) >= BATCH_SIZE:
                session.add_all(leads_to_create)
                await session.commit()
                print(f"   Saved batch {i+1}/{TOTAL_LEADS}...")
                leads_to_create = []

        # Commit remaining
        if leads_to_create:
            session.add_all(leads_to_create)
            await session.commit()
            print(f"   Saved final batch.")

        print("🎉 Seeding complete!")

# Run the async function
if __name__ == "__main__":
    asyncio.run(seed_leads())
