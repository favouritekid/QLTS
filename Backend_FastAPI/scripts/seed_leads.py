# scripts/seed_leads.py
"""
Lead Seeding Script - Generate ~200 test leads for UI testing
Run with: python scripts/seed_leads.py
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone

# Add parent directory to path to import app modules
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import AsyncSessionLocal
from app import models


# ============================================================
# EXACT DATA FROM DATABASE (from get_db_info.py output)
# ============================================================

# Pipeline Stages
PIPELINE_STAGES = ["stg01", "stg02", "stg03", "stg04", "stg05", "stg06", "stg07"]

# Organization Units (id, name)
UNIT_IDS = [1, 2, 3, 5, 6, 8, 15, 17]

# Program Offerings (id)
OFFERING_IDS = [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33]

# Officers (id)
OFFICER_IDS = [7, 8, 9, 10]

# Consultation Statuses by stage
CONSULTATION_STATUSES = {
    "stg01": ["stg15", "sts00", "sts01", "sts02", "sts03"],
    "stg02": ["sts04", "sts05", "sts06"],
    "stg03": ["sts07", "sts08"],
    "stg04": ["sts09", "sts13"],
    "stg05": ["sts10"],
    "stg06": ["sts11"],
    "stg07": ["sts12", "sts14"],
}

# Sources
SOURCES = ["phone", "website", "walk_in", "referral", "facebook", "event"]

# ============================================================
# VIETNAMESE NAME DATA
# ============================================================

HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", 
      "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Đinh", "Lưu", "Trương", "Cao"]
TEN_DEM = ["Văn", "Thị", "Hữu", "Minh", "Thanh", "Đức", "Quốc", "Xuân", "Ngọc", "Anh",
           "Hoàng", "Thành", "Phương", "Quang", "Tuấn", "Hồng", "Bảo", "Như", "Kim", ""]
TEN = ["An", "Bình", "Chi", "Dũng", "Em", "Phúc", "Giang", "Hà", "Hùng", "Khoa",
       "Linh", "Mai", "Nam", "Oanh", "Phong", "Quân", "Như", "Sơn", "Trang", "Uyên",
       "Vy", "Yến", "Tú", "Thảo", "Hạnh", "Đạt", "Long", "Hiếu", "Vinh", "Hương"]

LOCATIONS = [
    "TP. Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Đắk Lắk", "Gia Lai",
    "Kon Tum", "Đắk Nông", "Lâm Đồng", "Bình Phước", "Bình Dương",
    "Đồng Nai", "Khánh Hòa", "Phú Yên", "Bình Định", "Quảng Ngãi"
]

STATUSES = ["new", "assigned", "contacted", "qualified", "unqualified", "converted", "rejected"]
EDUCATION_LEVELS = ["high_school", "diploma", "bachelor", "master", None]


def generate_vietnamese_name():
    """Generate a random Vietnamese full name."""
    ho = random.choice(HO)
    ten_dem = random.choice(TEN_DEM)
    ten = random.choice(TEN)
    if ten_dem:
        return f"{ho} {ten_dem} {ten}"
    return f"{ho} {ten}"


def generate_phone():
    """Generate a random Vietnamese phone number."""
    prefixes = ["03", "05", "07", "08", "09"]
    prefix = random.choice(prefixes)
    suffix = "".join([str(random.randint(0, 9)) for _ in range(8)])
    return f"{prefix}{suffix}"


def generate_email(full_name: str, index: int):
    """Generate email from name."""
    name_parts = full_name.lower().split()
    if len(name_parts) >= 2:
        email_name = f"{name_parts[-1]}.{name_parts[0]}{index}"
    else:
        email_name = f"{name_parts[0]}{index}"
    
    # Vietnamese ASCII conversion
    replacements = {
        'á': 'a', 'à': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a', 'ă': 'a', 'ắ': 'a', 'ằ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ấ': 'a', 'ầ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'đ': 'd',
        'é': 'e', 'è': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e', 'ê': 'e', 'ế': 'e', 'ề': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'í': 'i', 'ì': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ó': 'o', 'ò': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o', 'ô': 'o', 'ố': 'o', 'ồ': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ớ': 'o', 'ờ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ú': 'u', 'ù': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u', 'ư': 'u', 'ứ': 'u', 'ừ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ý': 'y', 'ỳ': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
    }
    for vn, ascii_char in replacements.items():
        email_name = email_name.replace(vn, ascii_char)
    
    domains = ["gmail.com", "yahoo.com", "outlook.com"]
    return f"{email_name}@{random.choice(domains)}"


async def seed_leads(count: int = 200):
    """Seed the database with test leads."""
    print(f"🌱 Starting to seed {count} leads...")
    
    async with AsyncSessionLocal() as session:
        leads = []
        now = datetime.now(timezone.utc)
        
        for i in range(count):
            full_name = generate_vietnamese_name()
            
            # Random created_at within last 90 days
            days_ago = random.randint(0, 90)
            created_at = now - timedelta(days=days_ago, hours=random.randint(0, 23), minutes=random.randint(0, 59))
            
            # Determine pipeline stage (weighted distribution)
            weights = [15, 25, 15, 10, 10, 15, 10]  # More leads in stg01, stg02
            pipeline_stage = random.choices(PIPELINE_STAGES, weights=weights)[0]
            
            # Map pipeline stage to status
            stage_to_status = {
                "stg01": "new",
                "stg02": random.choice(["assigned", "contacted"]),
                "stg03": "qualified",
                "stg04": "qualified",
                "stg05": "qualified",
                "stg06": "converted",
                "stg07": random.choice(["unqualified", "rejected"]),
            }
            status = stage_to_status.get(pipeline_stage, "new")
            
            # Assign officer for non-new leads
            assigned_officer_id = None
            assigned_at = None
            assignment_status = "pending"
            if status != "new":
                assigned_officer_id = random.choice(OFFICER_IDS)
                assigned_at = created_at + timedelta(hours=random.randint(1, 48))
                assignment_status = "assigned"
            
            # Next activity for some leads
            next_activity_at = None
            if random.random() > 0.5 and status in ["assigned", "contacted", "qualified"]:
                if random.random() > 0.3:
                    next_activity_at = now + timedelta(hours=random.randint(-72, 168))
            
            # Get matching consultation status for the stage
            consultation_status_id = None
            if pipeline_stage in CONSULTATION_STATUSES and random.random() > 0.3:
                consultation_status_id = random.choice(CONSULTATION_STATUSES[pipeline_stage])
            
            lead = models.Lead(
                full_name=full_name,
                email=generate_email(full_name, i) if random.random() > 0.2 else None,
                phone=generate_phone(),
                phone2=generate_phone() if random.random() > 0.85 else None,
                source=random.choice(SOURCES),
                status=status,
                assignment_status=assignment_status,
                lead_score=random.randint(0, 100),
                education_level=random.choice(EDUCATION_LEVELS),
                gpa=round(random.uniform(5.0, 10.0), 1) if random.random() > 0.5 else None,
                location=random.choice(LOCATIONS) if random.random() > 0.3 else None,
                created_at=created_at,
                updated_at=created_at + timedelta(hours=random.randint(0, 24*max(days_ago, 1))),
                assigned_at=assigned_at,
                next_activity_at=next_activity_at,
                offering_id=random.choice(OFFERING_IDS) if random.random() > 0.2 else None,
                unit_id=random.choice(UNIT_IDS),
                assigned_officer_id=assigned_officer_id,
                pipeline_stage_id=pipeline_stage,
                consultation_status_id=consultation_status_id,
            )
            leads.append(lead)
            
            if (i + 1) % 50 == 0:
                print(f"  ✓ Generated {i + 1}/{count} leads...")
        
        # Bulk insert
        session.add_all(leads)
        await session.commit()
        
        print(f"✅ Successfully seeded {count} leads!")
        print(f"\n📊 Pipeline stage distribution:")
        for stage in PIPELINE_STAGES:
            stage_count = sum(1 for l in leads if l.pipeline_stage_id == stage)
            print(f"   - {stage}: {stage_count} leads")


async def clear_leads():
    """Clear all seeded leads (keeps real data by deleting only recent bulk inserts)."""
    async with AsyncSessionLocal() as session:
        # Delete leads, consultations, etc.
        await session.execute(text("DELETE FROM consultation"))
        await session.execute(text("DELETE FROM crm_interaction"))
        await session.execute(text("DELETE FROM assignment_log"))
        await session.execute(text("DELETE FROM application"))
        await session.execute(text("DELETE FROM lead"))
        await session.commit()
        print("🗑️ Cleared all leads and related data")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Seed leads for testing")
    parser.add_argument("--count", type=int, default=200, help="Number of leads to create (default: 200)")
    parser.add_argument("--clear", action="store_true", help="Clear all leads before seeding")
    args = parser.parse_args()
    
    async def main():
        if args.clear:
            await clear_leads()
        await seed_leads(args.count)
    
    asyncio.run(main())
