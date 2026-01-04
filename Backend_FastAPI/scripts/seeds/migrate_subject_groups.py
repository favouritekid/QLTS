"""
Data migration script to populate 'subjects' field in config_subject_group table.
Parses the 'name' field (e.g., "Toán, Vật lí, Hóa học") and creates a subjects array.

Run with WSL:
wsl bash -c "cd /mnt/d/QLTS/Backend_FastAPI && source venv/bin/activate && python -m scripts.seeds.migrate_subject_groups"
"""
import asyncio
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

try:
    from app.core.config import settings
    DB_URL = settings.DATABASE_URL
except:
    print("⚠️  Could not import settings. Using default DB URL.")
    DB_URL = "postgresql+asyncpg://postgres:admin@192.168.88.125:5432/qlts_dev"


async def migrate_subjects():
    """Parse subject names and populate subjects array."""
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get all subject groups
        result = await session.execute(
            text("SELECT id, code, name, subjects FROM config_subject_group")
        )
        rows = result.fetchall()
        
        print(f"📋 Found {len(rows)} subject groups to process...")
        
        updated = 0
        skipped = 0
        
        for row in rows:
            id_, code, name, existing_subjects = row
            
            # Skip if subjects already populated and not empty/null
            if existing_subjects and len(existing_subjects) > 0:
                skipped += 1
                continue
            
            # Parse subjects from name (e.g., "Toán, Vật lí, Hóa học")
            subjects = [s.strip() for s in name.split(",")]
            subjects_json = json.dumps(subjects, ensure_ascii=False)
            
            # Update the row
            await session.execute(
                text(
                    "UPDATE config_subject_group SET subjects = :subjects WHERE id = :id"
                ),
                {"subjects": subjects_json, "id": id_}
            )
            updated += 1
            print(f"  ✅ {code}: {subjects}")
        
        await session.commit()
        
        print(f"\n✅ Migration complete!")
        print(f"   Updated: {updated}")
        print(f"   Skipped (already had subjects): {skipped}")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate_subjects())
