"""
Debug script to test CSV export endpoint and identify 422 error cause.
Run this with:
    cd Backend_FastAPI
    source venv/bin/activate  # On Linux/WSL
    python test_csv_export_debug.py
"""
import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
from sqlalchemy import text

# Import after path setup
try:
    from app.core.database import AsyncSessionLocal
    print("✅ Successfully imported AsyncSessionLocal")
except ImportError as e:
    print(f"❌ Failed to import: {e}")
    print("Make sure you're running from Backend_FastAPI directory with venv activated")
    sys.exit(1)

async def check_database_schema():
    """Check if search_vector column exists in database."""
    print("=" * 80)
    print("CHECKING DATABASE SCHEMA")
    print("=" * 80)
    
    async with AsyncSessionLocal() as session:
        # Check columns
        result = await session.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'user' 
            AND column_name IN ('search_vector', 'current_assignment_id')
            ORDER BY column_name
        """))
        rows = result.fetchall()
        
        if rows:
            print("\n✅ Required columns found:")
            for row in rows:
                print(f"  - {row[0]}: {row[1]} (nullable: {row[2]})")
        else:
            print("\n❌ CRITICAL: Required columns NOT found in user table!")
            print("   Migration p1q2r3s4t5u6 may not have run successfully.")
            return False
        
        # Check GIN index
        result2 = await session.execute(text("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'user' 
            AND indexname LIKE '%search%'
        """))
        indexes = result2.fetchall()
        
        if indexes:
            print("\n✅ Search indexes found:")
            for idx in indexes:
                print(f"  - {idx[0]}")
        else:
            print("\n⚠️  WARNING: No search indexes found")
            print("   GIN index may not have been created.")
        
        # Check trigger
        result3 = await session.execute(text("""
            SELECT trigger_name, event_manipulation, action_statement
            FROM information_schema.triggers
            WHERE event_object_table = 'user'
            AND trigger_name LIKE '%search%'
        """))
        triggers = result3.fetchall()
        
        if triggers:
            print("\n✅ Search triggers found:")
            for trg in triggers:
                print(f"  - {trg[0]} ({trg[1]})")
        else:
            print("\n⚠️  WARNING: No search triggers found")
            print("   Auto-update trigger may not have been created.")
        
        # Test search_vector data
        result4 = await session.execute(text("""
            SELECT COUNT(*) as total,
                   COUNT(search_vector) as with_search_vector
            FROM "user"
        """))
        counts = result4.fetchone()
        
        print(f"\n📊 User table statistics:")
        print(f"  - Total users: {counts[0]}")
        print(f"  - Users with search_vector: {counts[1]}")
        
        if counts[0] > 0 and counts[1] == 0:
            print("\n❌ CRITICAL: search_vector column exists but has no data!")
            print("   Migration may have failed to populate existing rows.")
            return False
        
        return True

async def test_search_query():
    """Test if full-text search query works."""
    print("\n" + "=" * 80)
    print("TESTING FULL-TEXT SEARCH QUERY")
    print("=" * 80)
    
    async with AsyncSessionLocal() as session:
        try:
            # Test simple search
            result = await session.execute(text("""
                SELECT id, username, email
                FROM "user"
                WHERE search_vector @@ to_tsquery('simple', 'admin')
                LIMIT 5
            """))
            rows = result.fetchall()
            
            print(f"\n✅ Full-text search works! Found {len(rows)} results for 'admin'")
            for row in rows:
                print(f"  - {row[0]}: {row[1]} ({row[2]})")
            
            return True
        except Exception as e:
            print(f"\n❌ Full-text search FAILED: {e}")
            return False

async def test_model_import():
    """Test if User model can be imported and has search_vector attribute."""
    print("\n" + "=" * 80)
    print("TESTING MODEL DEFINITION")
    print("=" * 80)
    
    try:
        from app.models import User
        
        if hasattr(User, 'search_vector'):
            print("\n✅ User model has search_vector attribute")
        else:
            print("\n❌ User model MISSING search_vector attribute!")
            return False
        
        if hasattr(User, 'current_assignment_id'):
            print("✅ User model has current_assignment_id attribute")
        else:
            print("❌ User model MISSING current_assignment_id attribute!")
            return False
        
        # Check if use_alter is set
        fk = User.current_assignment_id.property.columns[0].foreign_keys
        if fk:
            fk_obj = list(fk)[0]
            print(f"✅ current_assignment_id FK: {fk_obj.target_fullname}")
            # Note: use_alter is internal to SQLAlchemy, hard to check here
        
        return True
    except Exception as e:
        print(f"\n❌ Model import FAILED: {e}")
        return False

async def main():
    """Run all diagnostic checks."""
    print("\n" + "=" * 80)
    print("CSV EXPORT DEBUG - DIAGNOSING 422 ERROR")
    print("=" * 80)
    
    results = []
    
    # Check 1: Database schema
    results.append(("Database Schema", await check_database_schema()))
    
    # Check 2: Search query
    results.append(("Search Query", await test_search_query()))
    
    # Check 3: Model definition
    results.append(("Model Definition", await test_model_import()))
    
    # Summary
    print("\n" + "=" * 80)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 80)
    
    all_passed = True
    for check_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {check_name}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n✅ All checks passed! The 422 error is likely NOT related to migration.")
        print("   Check backend server logs for actual error message.")
    else:
        print("\n❌ Some checks failed! This explains the 422 error.")
        print("   Fix the issues above before testing CSV export.")

if __name__ == "__main__":
    asyncio.run(main())

