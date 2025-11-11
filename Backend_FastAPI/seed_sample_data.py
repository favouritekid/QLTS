#!/usr/bin/env python3
"""
Seed Sample Data for 3-Tier Architecture Testing
=================================================

This script populates the database with sample data for testing:
- Organization Units
- Major Programs (Level 1)
- Program Offerings (Level 2)
- Offering Academic Info (Level 3)
- Sample Leads

Usage:
    python seed_sample_data.py
"""

import asyncio
import sys
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Import settings to get DB URL
try:
    from app.core.config import settings
    DB_URL = settings.DATABASE_URL
except:
    print("⚠️  Could not import settings. Using default DB URL.")
    DB_URL = "postgresql+asyncpg://postgres:admin@192.168.88.125:5432/qlts_dev"

print("=" * 80)
print("SEEDING SAMPLE DATA FOR 3-TIER ARCHITECTURE")
print("=" * 80)
print(f"\nConnecting to: {DB_URL.split('@')[1] if '@' in DB_URL else 'database'}")
print()


async def seed_data():
    """Seed sample data for testing"""

    # Create async engine
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as session:
            print("=" * 80)
            print("STEP 1: Check existing organization units")
            print("=" * 80)

            # Get existing units
            result = await session.execute(text("SELECT id, name, type FROM organization_unit LIMIT 5"))
            units = result.fetchall()

            if not units:
                print("❌ No organization units found! Please create at least one unit first.")
                return False

            print(f"✅ Found {len(units)} organization units:")
            for unit in units:
                print(f"   - ID={unit[0]}, Name={unit[1]}, Type={unit[2]}")

            # Use first unit for testing
            test_unit_id = units[0][0]
            print(f"\n📍 Using unit ID {test_unit_id} for testing\n")

            print("=" * 80)
            print("STEP 2: Create Major Programs (Level 1)")
            print("=" * 80)

            programs_data = [
                {
                    "name": "Công nghệ Thông tin",
                    "code": "7480201",
                    "degree_level": "Đại học",
                    "unit_id": test_unit_id
                },
                {
                    "name": "Quản trị Kinh doanh",
                    "code": "7340101",
                    "degree_level": "Đại học",
                    "unit_id": test_unit_id
                },
                {
                    "name": "Kế toán",
                    "code": "7340301",
                    "degree_level": "Đại học",
                    "unit_id": test_unit_id
                }
            ]

            created_program_ids = []

            for prog in programs_data:
                # Check if program with this code already exists
                result = await session.execute(
                    text("SELECT id FROM major_program WHERE code = :code"),
                    {"code": prog["code"]}
                )
                existing = result.fetchone()

                if existing:
                    print(f"   ℹ️  Program '{prog['name']}' (code={prog['code']}) already exists (ID={existing[0]})")
                    created_program_ids.append(existing[0])
                else:
                    result = await session.execute(
                        text("""
                            INSERT INTO major_program (name, code, degree_level, unit_id, is_active)
                            VALUES (:name, :code, :degree_level, :unit_id, true)
                            RETURNING id
                        """),
                        prog
                    )
                    program_id = result.fetchone()[0]
                    created_program_ids.append(program_id)
                    print(f"   ✅ Created program: {prog['name']} (ID={program_id}, code={prog['code']})")

            await session.commit()
            print(f"\n✅ Total programs: {len(created_program_ids)}\n")

            print("=" * 80)
            print("STEP 3: Create Program Offerings (Level 2)")
            print("=" * 80)

            offering_types = ["Chính quy", "Liên thông", "Từ xa"]
            created_offering_ids = []

            # Create offerings for each program
            for idx, program_id in enumerate(created_program_ids):
                # For demo: IT has all 3 types, Business has 2, Accounting has 1
                types_to_create = offering_types[:3] if idx == 0 else offering_types[:2] if idx == 1 else offering_types[:1]

                for offering_type in types_to_create:
                    # Check if offering already exists
                    result = await session.execute(
                        text("SELECT id FROM program_offering WHERE program_id = :program_id AND offering_type = :offering_type"),
                        {"program_id": program_id, "offering_type": offering_type}
                    )
                    existing = result.fetchone()

                    if existing:
                        print(f"   ℹ️  Offering '{offering_type}' for program {program_id} already exists (ID={existing[0]})")
                        created_offering_ids.append(existing[0])
                    else:
                        duration = 8 if offering_type == "Chính quy" else 6 if offering_type == "Liên thông" else 10
                        credits = 140 if offering_type == "Chính quy" else 100 if offering_type == "Liên thông" else 130

                        result = await session.execute(
                            text("""
                                INSERT INTO program_offering
                                (offering_type, program_id, duration_semesters, total_credits, is_active)
                                VALUES (:offering_type, :program_id, :duration, :credits, true)
                                RETURNING id
                            """),
                            {
                                "offering_type": offering_type,
                                "program_id": program_id,
                                "duration": duration,
                                "credits": credits
                            }
                        )
                        offering_id = result.fetchone()[0]
                        created_offering_ids.append(offering_id)
                        print(f"   ✅ Created offering: {offering_type} for program {program_id} (ID={offering_id})")

            await session.commit()
            print(f"\n✅ Total offerings: {len(created_offering_ids)}\n")

            print("=" * 80)
            print("STEP 4: Create Academic Info (Level 3)")
            print("=" * 80)

            current_year = datetime.now().year
            years_to_create = [current_year, current_year + 1]
            created_academic_info_count = 0

            for offering_id in created_offering_ids:
                for year in years_to_create:
                    # Check if academic info exists
                    result = await session.execute(
                        text("SELECT id FROM offering_academic_info WHERE offering_id = :offering_id AND academic_year = :year"),
                        {"offering_id": offering_id, "year": year}
                    )
                    existing = result.fetchone()

                    if existing:
                        print(f"   ℹ️  Academic info for offering {offering_id}, year {year} already exists")
                        created_academic_info_count += 1
                    else:
                        # Generate realistic data based on year
                        tuition = 15000000 if year == current_year else 16000000
                        quota = 50 if year == current_year else 60
                        is_published = True if year == current_year else False

                        admission_criteria = {
                            "criteria": [
                                {
                                    "id": f"hocba_{year}",
                                    "method_name": "Xét tuyển học bạ",
                                    "subject_groups": ["A00", "A01", "D01"],
                                    "min_score": 22.0
                                },
                                {
                                    "id": f"thpt_{year}",
                                    "method_name": "Xét tuyển THPT Quốc gia",
                                    "subject_groups": ["A00", "A01", "D01"],
                                    "min_score": 18.0
                                }
                            ]
                        }

                        result = await session.execute(
                            text("""
                                INSERT INTO offering_academic_info
                                (offering_id, academic_year, tuition_fee_per_year, annual_admission_quota,
                                 admission_criteria, is_published, created_at, updated_at)
                                VALUES (:offering_id, :year, :tuition, :quota, :criteria::jsonb, :published, NOW(), NOW())
                                RETURNING id
                            """),
                            {
                                "offering_id": offering_id,
                                "year": year,
                                "tuition": tuition,
                                "quota": quota,
                                "criteria": str(admission_criteria).replace("'", '"'),
                                "published": is_published
                            }
                        )
                        academic_info_id = result.fetchone()[0]
                        created_academic_info_count += 1
                        status = "📢 PUBLISHED" if is_published else "📝 DRAFT"
                        print(f"   ✅ Created academic info: Offering {offering_id}, Year {year} (ID={academic_info_id}) {status}")

            await session.commit()
            print(f"\n✅ Total academic info records: {created_academic_info_count}\n")

            print("=" * 80)
            print("STEP 5: Create Sample Leads (for testing)")
            print("=" * 80)

            # Get default status from consultation_status table
            result = await session.execute(
                text("SELECT id, stage_id FROM consultation_status WHERE label ILIKE '%new%' OR label ILIKE '%initial%' LIMIT 1")
            )
            default_status = result.fetchone()

            if not default_status:
                print("   ⚠️  No default consultation status found, skipping lead creation")
            else:
                status_id, stage_id = default_status

                # Create 3 sample leads with different offerings
                leads_data = [
                    {
                        "full_name": "Nguyễn Văn A",
                        "email": "nguyenvana@example.com",
                        "phone": "0901234567",
                        "source": "Website",
                        "unit_id": test_unit_id,
                        "offering_id": created_offering_ids[0] if created_offering_ids else None
                    },
                    {
                        "full_name": "Trần Thị B",
                        "email": "tranthib@example.com",
                        "phone": "0907654321",
                        "source": "Facebook",
                        "unit_id": test_unit_id,
                        "offering_id": created_offering_ids[1] if len(created_offering_ids) > 1 else created_offering_ids[0]
                    },
                    {
                        "full_name": "Lê Văn C",
                        "email": "levanc@example.com",
                        "phone": "0909876543",
                        "source": "Referral",
                        "unit_id": test_unit_id,
                        "offering_id": created_offering_ids[2] if len(created_offering_ids) > 2 else created_offering_ids[0]
                    }
                ]

                created_leads = 0
                for lead in leads_data:
                    # Check if lead with this email already exists
                    result = await session.execute(
                        text("SELECT id FROM lead WHERE email = :email"),
                        {"email": lead["email"]}
                    )
                    existing = result.fetchone()

                    if existing:
                        print(f"   ℹ️  Lead '{lead['full_name']}' ({lead['email']}) already exists")
                    else:
                        result = await session.execute(
                            text("""
                                INSERT INTO lead
                                (full_name, email, phone, source, unit_id, offering_id,
                                 status, consultation_status_id, pipeline_stage_id, lead_score,
                                 created_at, updated_at)
                                VALUES (:full_name, :email, :phone, :source, :unit_id, :offering_id,
                                        :status, :status, :stage_id, 50, NOW(), NOW())
                                RETURNING id
                            """),
                            {
                                **lead,
                                "status": status_id,
                                "stage_id": stage_id
                            }
                        )
                        lead_id = result.fetchone()[0]
                        created_leads += 1
                        print(f"   ✅ Created lead: {lead['full_name']} (ID={lead_id}, offering_id={lead['offering_id']})")

                await session.commit()
                print(f"\n✅ Total leads created: {created_leads}\n")

            print("=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"✅ Programs (Level 1):              {len(created_program_ids)}")
            print(f"✅ Offerings (Level 2):             {len(created_offering_ids)}")
            print(f"✅ Academic Info (Level 3):         {created_academic_info_count}")
            print(f"✅ Sample Leads:                    {created_leads if 'created_leads' in locals() else 0}")
            print()
            print("=" * 80)
            print("✅ SAMPLE DATA SEEDING COMPLETED!")
            print("=" * 80)
            print()
            print("You can now run the API test script:")
            print("    python test_phase4_api.py")
            print()

            return True

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        result = asyncio.run(seed_data())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\nSeeding interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        sys.exit(1)
