# scripts/seeds/migrate_to_relational_subject_groups.py
"""
Complete Migration: config_subject_group → Subject + SubjectGroup + SubjectGroupSubject

This script:
1. Seeds 21 subjects into Subject table
2. Reads config_subject_group.csv (281 records)
3. Creates SubjectGroup records
4. Creates SubjectGroupSubject mappings

Usage:
    python -m scripts.seeds.migrate_to_relational_subject_groups
"""

import asyncio
import csv
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.admission_config import Subject, SubjectGroup, SubjectGroupSubject


# =============================================================================
# 21 SUBJECTS (from CSV analysis)
# =============================================================================
SUBJECTS = [
    # Core subjects
    {"code": "math", "name_vi": "Toán", "display_order": 1},
    {"code": "literature", "name_vi": "Ngữ văn", "display_order": 2},
    {"code": "physics", "name_vi": "Vật lý", "display_order": 3},
    {"code": "chemistry", "name_vi": "Hóa học", "display_order": 4},
    {"code": "biology", "name_vi": "Sinh học", "display_order": 5},
    {"code": "history", "name_vi": "Lịch sử", "display_order": 6},
    {"code": "geography", "name_vi": "Địa lý", "display_order": 7},
    {"code": "civic_education", "name_vi": "Giáo dục công dân", "display_order": 8},
    
    # Foreign languages
    {"code": "english", "name_vi": "Tiếng Anh", "display_order": 9},
    {"code": "french", "name_vi": "Tiếng Pháp", "display_order": 10},
    {"code": "german", "name_vi": "Tiếng Đức", "display_order": 11},
    {"code": "russian", "name_vi": "Tiếng Nga", "display_order": 12},
    {"code": "chinese", "name_vi": "Tiếng Trung", "display_order": 13},
    {"code": "japanese", "name_vi": "Tiếng Nhật", "display_order": 14},
    {"code": "korean", "name_vi": "Tiếng Hàn", "display_order": 15},
    
    # Combined subjects (2025 curriculum)
    {"code": "natural_science", "name_vi": "Khoa học tự nhiên", "display_order": 16},
    {"code": "social_science", "name_vi": "Khoa học xã hội", "display_order": 17},
    
    # Technology subjects
    {"code": "informatics", "name_vi": "Tin học", "display_order": 18},
    {"code": "industrial_tech", "name_vi": "Công nghệ công nghiệp", "display_order": 19},
    {"code": "agricultural_tech", "name_vi": "Công nghệ nông nghiệp", "display_order": 20},
    {"code": "economic_law", "name_vi": "Giáo dục Kinh tế và pháp luật", "display_order": 21},
]


# Path to CSV file
CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "..", "Documents", "Seeding data", "config_subject_group.csv"
)


async def seed_subjects(db: AsyncSession) -> dict[str, int]:
    """Seed Subject table and return code->id mapping."""
    print("📚 Step 1: Seeding Subjects...")
    
    code_to_id = {}
    created = 0
    existing = 0
    
    for subject_data in SUBJECTS:
        result = await db.execute(
            select(Subject).where(Subject.code == subject_data["code"])
        )
        subject = result.scalar_one_or_none()
        
        if subject:
            code_to_id[subject.code] = subject.id
            existing += 1
        else:
            subject = Subject(**subject_data, is_active=True)
            db.add(subject)
            await db.flush()
            code_to_id[subject.code] = subject.id
            created += 1
    
    await db.commit()
    print(f"   ✅ Created: {created} | Existing: {existing} | Total: {len(code_to_id)}")
    return code_to_id


async def migrate_subject_groups(db: AsyncSession, subject_code_to_id: dict[str, int]):
    """Read CSV and create SubjectGroup + SubjectGroupSubject records."""
    print(f"\n📐 Step 2: Migrating Subject Groups from CSV...")
    print(f"   CSV Path: {CSV_PATH}")
    
    if not os.path.exists(CSV_PATH):
        print(f"   ❌ CSV file not found!")
        return
    
    created_groups = 0
    created_mappings = 0
    skipped_groups = 0
    errors = []
    
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            code = row['code']
            name = row['name']
            display_order = int(row['display_order'])
            
            # Parse subjects JSON (format: ["math", "physics", "chemistry"])
            subjects_str = row['subjects']
            # Handle CSV escaping: [""math"", ""physics""] -> ["math", "physics"]
            subjects_str = subjects_str.replace('""', '"')
            try:
                subject_codes = json.loads(subjects_str)
            except json.JSONDecodeError as e:
                errors.append(f"{code}: Failed to parse subjects - {e}")
                continue
            
            # Check if group exists
            result = await db.execute(
                select(SubjectGroup).where(SubjectGroup.code == code)
            )
            existing_group = result.scalar_one_or_none()
            
            if existing_group:
                skipped_groups += 1
                continue
            
            # Create SubjectGroup
            group = SubjectGroup(
                code=code,
                name=name,
                display_order=display_order,
                is_active=True
            )
            db.add(group)
            await db.flush()
            created_groups += 1
            
            # Create SubjectGroupSubject mappings
            for position, subject_code in enumerate(subject_codes, start=1):
                subject_id = subject_code_to_id.get(subject_code)
                
                if not subject_id:
                    errors.append(f"{code}: Subject '{subject_code}' not found in Subject table")
                    continue
                
                mapping = SubjectGroupSubject(
                    subject_group_id=group.id,
                    subject_id=subject_id,
                    position=position
                )
                db.add(mapping)
                created_mappings += 1
            
            # Progress indicator
            if created_groups % 50 == 0:
                print(f"   ... processed {created_groups} groups")
    
    await db.commit()
    
    print(f"   ✅ Created groups: {created_groups}")
    print(f"   ✅ Created mappings: {created_mappings}")
    print(f"   ⏭️ Skipped (existing): {skipped_groups}")
    
    if errors:
        print(f"\n   ⚠️ Errors ({len(errors)}):")
        for err in errors[:10]:
            print(f"      - {err}")
        if len(errors) > 10:
            print(f"      ... and {len(errors) - 10} more")


async def verify_migration(db: AsyncSession):
    """Verify migration by counting records."""
    print("\n🔍 Step 3: Verifying migration...")
    
    # Count subjects
    result = await db.execute(select(Subject))
    subjects = result.scalars().all()
    print(f"   Subject table: {len(subjects)} records")
    
    # Count groups
    result = await db.execute(select(SubjectGroup))
    groups = result.scalars().all()
    print(f"   SubjectGroup table: {len(groups)} records")
    
    # Count mappings
    result = await db.execute(select(SubjectGroupSubject))
    mappings = result.scalars().all()
    print(f"   SubjectGroupSubject table: {len(mappings)} records")
    
    # Sample verification
    print("\n   📋 Sample data (first 5 groups with subjects):")
    
    result = await db.execute(
        select(SubjectGroup)
        .order_by(SubjectGroup.display_order)
        .limit(5)
    )
    sample_groups = result.scalars().all()
    
    for group in sample_groups:
        result = await db.execute(
            select(SubjectGroupSubject)
            .where(SubjectGroupSubject.subject_group_id == group.id)
            .order_by(SubjectGroupSubject.position)
        )
        group_mappings = result.scalars().all()
        
        subject_ids = [m.subject_id for m in group_mappings]
        result = await db.execute(
            select(Subject).where(Subject.id.in_(subject_ids))
        )
        subjects = {s.id: s.code for s in result.scalars().all()}
        
        subject_names = [subjects.get(m.subject_id, "?") for m in group_mappings]
        print(f"      {group.code}: {subject_names}")


async def main():
    """Main migration function."""
    print("=" * 60)
    print("🚀 MIGRATION: config_subject_group → Relational Tables")
    print("=" * 60)
    
    async with AsyncSessionLocal() as db:
        # Step 1: Seed subjects
        subject_ids = await seed_subjects(db)
        
        # Step 2: Migrate subject groups from CSV
        await migrate_subject_groups(db, subject_ids)
        
        # Step 3: Verify
        await verify_migration(db)
        
        print("\n" + "=" * 60)
        print("✅ MIGRATION COMPLETE!")
        print("=" * 60)
        print("\nNext steps:")
        print("  1. Update config_data.py router to use SubjectGroup")
        print("  2. Update config_service.py to use SubjectGroup")
        print("  3. Create Alembic migration to DROP config_subject_group table")
        print("  4. Remove ConfigSubjectGroup from models/config.py")


if __name__ == "__main__":
    asyncio.run(main())
