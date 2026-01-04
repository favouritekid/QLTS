"""
Script to update subjects field in config_subject_group table.
Parses Vietnamese subject names and converts to English keys.

Run with WSL:
wsl bash -c "cd /mnt/d/QLTS/Backend_FastAPI && source venv/bin/activate && python -m scripts.seeds.update_subjects"
"""
import asyncio
import json

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


# Vietnamese to English subject mapping
SUBJECT_MAP = {
    # Core subjects
    "Toán": "math",
    "Vật lí": "physics",
    "Vật lý": "physics",  # Alternate spelling
    "Hóa học": "chemistry",
    "Hoá học": "chemistry",  # Alternate spelling
    "Sinh học": "biology",
    "Ngữ văn": "literature",
    "Lịch sử": "history",
    "Địa lí": "geography",
    
    # Foreign languages
    "Tiếng Anh": "english",
    "Tiếng Pháp": "french",
    "Tiếng Đức": "german",
    "Tiếng Nga": "russian",
    "Tiếng Nhật": "japanese",
    "Tiếng Trung": "chinese",
    "Tiếng Hàn": "korean",
    
    # Other subjects
    "Giáo dục công dân": "civic_education",
    "Tin học": "informatics",
    "Khoa học tự nhiên": "natural_science",
    "Khoa học xã hội": "social_science",
    "Giáo dục Kinh tế và pháp luật": "economic_law",
    "Công nghệ công nghiệp": "industrial_tech",
    "Công nghệ nông nghiệp": "agricultural_tech",
}


def parse_subjects_from_name(name: str) -> list[str]:
    """Parse Vietnamese subject name to list of English keys."""
    subjects = []
    parts = [p.strip() for p in name.split(",")]
    
    for part in parts:
        # Try to find exact match
        if part in SUBJECT_MAP:
            subjects.append(SUBJECT_MAP[part])
        else:
            # Log unknown subject
            print(f"  ⚠️  Unknown subject: '{part}'")
            # Use lowercase with underscores as fallback
            subjects.append(part.lower().replace(" ", "_"))
    
    return subjects


async def update_subjects():
    """Update subjects field for all subject groups."""
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        async with async_session() as session:
            # Get all subject groups
            result = await session.execute(
                text("SELECT id, code, name, subjects FROM config_subject_group ORDER BY display_order")
            )
            rows = result.fetchall()
            
            updated_count = 0
            
            for row in rows:
                id_, code, name, current_subjects = row
                
                # Parse subjects from name
                subjects = parse_subjects_from_name(name)
                
                # Update if different
                if subjects != current_subjects:
                    subjects_json = json.dumps(subjects)
                    await session.execute(
                        text("""
                            UPDATE config_subject_group 
                            SET subjects = CAST(:subjects AS jsonb)
                            WHERE id = :id
                        """),
                        {"id": id_, "subjects": subjects_json}
                    )
                    updated_count += 1
                    print(f"  ✅ {code}: {name} → {subjects}")
            
            await session.commit()
            print(f"\n✅ Updated {updated_count} subject groups with subjects data!")
            
            # Verify
            result = await session.execute(
                text("SELECT code, name, subjects FROM config_subject_group WHERE subjects != '[]'::jsonb LIMIT 5")
            )
            rows = result.fetchall()
            print("\n📋 Sample verified data:")
            for row in rows:
                print(f"   {row[0]}: {row[2]}")
    
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(update_subjects())
