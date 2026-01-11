"""
Phase 0 Database Verification Script
Test the actual database schema after migration
"""
import asyncio
from sqlalchemy import text
import sys
sys.path.insert(0, '.')

from app.database import engine

async def check_db():
    print("=" * 60)
    print("PHASE 0 DATABASE VERIFICATION")
    print("=" * 60)
    
    async with engine.begin() as conn:
        # 1. Check admission_path table exists
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'admission_path'
            ORDER BY ordinal_position
        """))
        rows = result.fetchall()
        print("\n📋 1. admission_path TABLE COLUMNS:")
        if rows:
            for row in rows:
                print(f"  ✅ {row[0]}: {row[1]} (null={row[2]})")
        else:
            print("  ❌ Table not found!")
        
        # 2. Check document_group.admission_method_id
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'document_group' AND column_name = 'admission_method_id'
        """))
        rows = result.fetchall()
        print("\n📋 2. document_group.admission_method_id:")
        if rows:
            for row in rows:
                print(f"  ✅ {row[0]}: {row[1]} (null={row[2]})")
        else:
            print("  ❌ Column not found!")
        
        # 3. Check unique constraint
        result = await conn.execute(text("""
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'admission_path' AND constraint_type = 'UNIQUE'
        """))
        rows = result.fetchall()
        print("\n🔒 3. UNIQUE CONSTRAINTS on admission_path:")
        if rows:
            for row in rows:
                print(f"  ✅ {row[0]}")
        else:
            print("  ❌ No unique constraints found!")
        
        # 4. Check indexes
        result = await conn.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'admission_path'
        """))
        rows = result.fetchall()
        print("\n📊 4. INDEXES on admission_path:")
        for row in rows:
            print(f"  ✅ {row[0]}")
        
        # 5. Test unique constraint by checking for errors
        print("\n🧪 5. UNIQUE CONSTRAINT TEST:")
        print("  (Will be tested in integration tests)")

    print("\n" + "=" * 60)
    print("DATABASE VERIFICATION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(check_db())
