#!/usr/bin/env python3
"""
Script Faker: Tạo Lead mẫu cho hệ thống QLTS

Chức năng:
- Tạo N leads ngẫu nhiên với dữ liệu thực tế
- Random phân bố qua units, offerings, sources
- Tự động calculate lead_score
- Hỗ trợ tạo kèm consultations (optional)

Usage:
    python scripts/faker_leads.py --count 100
    python scripts/faker_leads.py --count 50 --with-consultations
    python scripts/faker_leads.py --count 200 --unit-id 1
"""
import argparse
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path để import được app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from faker import Faker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_session

from app import models
from app.config import settings
from app.database import async_engine
from app.services import lead_service

# Initialize Faker with Vietnamese locale
fake = Faker(['vi_VN', 'en_US'])

# Vietnamese names for better data quality
VIETNAMESE_NAMES = [
    "Nguyễn Văn An", "Trần Thị Bình", "Lê Hoàng Cường", "Phạm Thị Dung",
    "Hoàng Văn Em", "Vũ Thị Phương", "Đặng Minh Giang", "Bùi Thị Hà",
    "Đỗ Văn Hùng", "Ngô Thị Lan", "Dương Văn Khoa", "Lý Thị Mai",
    "Phan Văn Nam", "Trịnh Thị Nga", "Võ Minh Quân", "Cao Thị Trang",
    "Mai Văn Sơn", "Tô Thị Thảo", "Lưu Văn Tuấn", "Đinh Thị Uyên",
    "Nguyễn Minh Vũ", "Trần Thị Xuân", "Lê Văn Yên", "Phạm Thị Hoa",
    "Hoàng Đức Anh", "Vũ Thị Bảo", "Đặng Văn Chiến", "Bùi Thị Diệu",
]

# Lead sources
LEAD_SOURCES = [
    "website", "referral", "social_media", "walk_in",
    "email", "phone", "event", "other"
]

# Education levels
EDUCATION_LEVELS = [
    "high_school", "bachelor", "master", "phd"
]

# Vietnamese cities/provinces
LOCATIONS = [
    "Hà Nội", "Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", "Cần Thơ",
    "Bình Dương", "Đồng Nai", "Khánh Hòa", "Lâm Đồng", "Nghệ An",
    "Thanh Hóa", "Thừa Thiên Huế", "Quảng Nam", "Quảng Ninh", "Vũng Tàu",
]

# Consultation methods
CONSULTATION_METHODS = [
    "phone", "email", "in_person", "video_call", "chat"
]

# Consultation notes templates
CONSULTATION_NOTES = [
    "Học viên quan tâm chương trình đào tạo, cần tư vấn thêm về học phí",
    "Đã giải đáp thắc mắc về điều kiện đầu vào và thời gian học",
    "Học viên yêu cầu xem cơ sở vật chất, đã hẹn lịch tham quan",
    "Tư vấn về các chương trình học bổng và hỗ trợ tài chính",
    "Học viên đang cân nhắc giữa nhiều chương trình, cần follow-up",
    "Đã gửi tài liệu chi tiết về chương trình qua email",
    "Học viên rất hài lòng với buổi tư vấn, khả năng cao sẽ đăng ký",
    "Cần liên hệ lại sau 1 tuần để cập nhật quyết định",
]


async def get_reference_data(db):
    """Load các tham chiếu từ DB để tạo leads hợp lệ."""
    print("📊 Loading reference data from database...")

    # Load organization units
    result = await db.execute(
        select(models.OrganizationUnit)
        .where(models.OrganizationUnit.is_active == True)
        .order_by(models.OrganizationUnit.id)
    )
    units = result.scalars().all()

    if not units:
        print("❌ ERROR: No active organization units found! Please create units first.")
        sys.exit(1)

    # Load program offerings
    result = await db.execute(
        select(models.ProgramOffering)
        .order_by(models.ProgramOffering.id)
        .limit(50)  # Limit to prevent memory issues
    )
    offerings = result.scalars().all()

    # Load consultation statuses
    result = await db.execute(
        select(models.ConsultationStatus)
        .order_by(models.ConsultationStatus.id)
    )
    consultation_statuses = result.scalars().all()

    # Load active officers (for consultations)
    result = await db.execute(
        select(models.User)
        .where(
            models.User.role == "officer",
            models.User.status == "active"
        )
        .limit(20)
    )
    officers = result.scalars().all()

    print(f"   ✅ Units: {len(units)}")
    print(f"   ✅ Offerings: {len(offerings)}")
    print(f"   ✅ Consultation Statuses: {len(consultation_statuses)}")
    print(f"   ✅ Officers: {len(officers)}")

    return {
        "units": units,
        "offerings": offerings if offerings else None,
        "consultation_statuses": consultation_statuses,
        "officers": officers if officers else None,
    }


def generate_random_lead(units, offerings=None, target_unit_id=None):
    """Generate dữ liệu ngẫu nhiên cho 1 lead."""
    # Choose name
    full_name = random.choice(VIETNAMESE_NAMES)

    # Generate unique email
    email_prefix = fake.user_name()
    email_domain = random.choice([
        "gmail.com", "yahoo.com", "outlook.com",
        "student.edu.vn", "email.vn", "hotmail.com"
    ])
    email = f"{email_prefix}@{email_domain}"

    # Generate phone (Vietnam format)
    phone = fake.phone_number()

    # Random source
    source = random.choice(LEAD_SOURCES)

    # Random education level
    education_level = random.choice(EDUCATION_LEVELS)

    # Random GPA (0.0-4.0)
    gpa = round(random.uniform(2.0, 4.0), 2) if random.random() > 0.3 else None

    # Random location
    location = random.choice(LOCATIONS)

    # Choose unit
    if target_unit_id:
        unit = next((u for u in units if u.id == target_unit_id), None)
        if not unit:
            unit = random.choice(units)
    else:
        unit = random.choice(units)

    # Choose offering (optional)
    offering = None
    if offerings and random.random() > 0.2:  # 80% have offering
        offering = random.choice(offerings)

    # Officer rating (optional)
    officer_rating = random.randint(1, 5) if random.random() > 0.7 else None

    # Officer summary (optional)
    officer_summary = None
    if officer_rating:
        summaries = [
            "Học viên có tiềm năng cao",
            "Rất quan tâm đến chương trình",
            "Cần follow-up thêm",
            "Khả năng chuyển đổi cao",
            "Đã sẵn sàng đăng ký",
        ]
        officer_summary = random.choice(summaries)

    return {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "source": source,
        "education_level": education_level,
        "gpa": gpa,
        "location": location,
        "unit_id": unit.id,
        "offering_id": offering.id if offering else None,
        "officer_rating": officer_rating,
        "officer_summary": officer_summary,
    }


async def create_leads_batch(
    db,
    count: int,
    units,
    offerings,
    target_unit_id=None,
    with_consultations=False,
    consultation_statuses=None,
    officers=None
):
    """Tạo một batch leads."""
    print(f"\n🔧 Creating batch of {count} leads...")

    created_leads = []
    errors = []

    for i in range(count):
        try:
            # Generate lead data
            lead_data = generate_random_lead(units, offerings, target_unit_id)

            # Create lead via service (includes auto-scoring)
            from app.schemas.lead import LeadCreate
            lead_create = LeadCreate(**lead_data)

            # Create lead
            lead = await lead_service.create_lead(db, lead_create)
            created_leads.append(lead)

            # Optionally create consultations
            if with_consultations and consultation_statuses and officers and random.random() > 0.3:
                # Create 1-3 consultations per lead
                num_consultations = random.randint(1, 3)
                for _ in range(num_consultations):
                    await create_random_consultation(
                        db, lead, consultation_statuses, officers
                    )

            # Progress indicator
            if (i + 1) % 10 == 0:
                print(f"   ✅ Created {i + 1}/{count} leads...")

        except Exception as e:
            error_msg = f"Row {i + 1}: {str(e)}"
            errors.append(error_msg)
            print(f"   ❌ {error_msg}")
            continue

    return created_leads, errors


async def create_random_consultation(db, lead, consultation_statuses, officers):
    """Tạo 1 consultation ngẫu nhiên cho lead."""
    # Ensure lead is assigned to an officer first
    if not lead.assigned_officer_id and officers:
        # Assign to random officer
        officer = random.choice(officers)
        await lead_service.assign_lead_manually(
            db, lead.id, officer.id, officer
        )
        # Refresh lead
        await db.refresh(lead)

    # Only create consultation if lead has officer
    if lead.assigned_officer_id:
        from app.schemas.lead import ConsultationCreate

        consultation_data = ConsultationCreate(
            method=random.choice(CONSULTATION_METHODS),
            notes=random.choice(CONSULTATION_NOTES),
            outcome=random.choice(["positive", "neutral", "negative", None]),
            duration_minutes=random.randint(10, 90) if random.random() > 0.5 else None,
            status_id=random.choice(consultation_statuses).id,
        )

        await lead_service.add_consultation(
            db, lead.id, lead.assigned_officer_id, consultation_data
        )


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Faker script: Tạo Lead mẫu cho hệ thống QLTS"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Số lượng leads cần tạo (default: 50)"
    )
    parser.add_argument(
        "--unit-id",
        type=int,
        default=None,
        help="Chỉ tạo leads cho unit_id cụ thể (optional)"
    )
    parser.add_argument(
        "--with-consultations",
        action="store_true",
        help="Tạo kèm consultations ngẫu nhiên cho mỗi lead"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Số leads tạo trong mỗi batch (default: 50)"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("🎯 QLTS LEAD FAKER SCRIPT")
    print("=" * 70)
    print(f"📌 Configuration:")
    print(f"   - Total leads to create: {args.count}")
    print(f"   - Target unit: {args.unit_id or 'All units (random)'}")
    print(f"   - With consultations: {args.with_consultations}")
    print(f"   - Batch size: {args.batch_size}")
    print("=" * 70)

    # Create async session
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(async_engine) as db:
        try:
            # Load reference data
            refs = await get_reference_data(db)

            # Validate target unit
            if args.unit_id:
                unit_exists = any(u.id == args.unit_id for u in refs["units"])
                if not unit_exists:
                    print(f"❌ ERROR: Unit ID {args.unit_id} not found!")
                    return

            # Create leads in batches
            total_created = 0
            total_errors = 0

            remaining = args.count
            while remaining > 0:
                batch_size = min(args.batch_size, remaining)

                created, errors = await create_leads_batch(
                    db,
                    count=batch_size,
                    units=refs["units"],
                    offerings=refs["offerings"],
                    target_unit_id=args.unit_id,
                    with_consultations=args.with_consultations,
                    consultation_statuses=refs["consultation_statuses"],
                    officers=refs["officers"],
                )

                total_created += len(created)
                total_errors += len(errors)
                remaining -= batch_size

                # Commit batch
                await db.commit()
                print(f"   💾 Batch committed to database")

            # Summary
            print("\n" + "=" * 70)
            print("✅ FAKER SCRIPT COMPLETED")
            print("=" * 70)
            print(f"📊 Summary:")
            print(f"   - Total leads created: {total_created}")
            print(f"   - Total errors: {total_errors}")
            print(f"   - Success rate: {total_created / args.count * 100:.1f}%")
            print("=" * 70)

            if total_errors > 0:
                print("\n⚠️  Some leads failed to create. Check error messages above.")

        except KeyboardInterrupt:
            print("\n\n⚠️  Script interrupted by user. Rolling back...")
            await db.rollback()
            print("   ✅ Rollback completed")

        except Exception as e:
            print(f"\n❌ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()


if __name__ == "__main__":
    asyncio.run(main())
