# scripts/verify_administrative_nodes.py
"""Verification script to check administrative_nodes data integrity."""

import asyncio
import sys
import os

# Add Backend_FastAPI to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import AsyncSessionLocal


async def verify_province(province_name: str):
    """Verify a specific province and its hierarchy."""
    print(f"\n{'='*60}")
    print(f"🔍 VERIFYING: {province_name}")
    print("=" * 60)
    
    async with AsyncSessionLocal() as db:
        # 1. Find the province
        result = await db.execute(
            text("SELECT id, code, name, level, path, valid_from, valid_to FROM administrative_nodes WHERE name = :name AND level = 'PROVINCE'").bindparams(name=province_name)
        )
        provinces = result.fetchall()
        
        if not provinces:
            print(f"❌ Province '{province_name}' not found!")
            return
        
        print(f"\n📍 Province Records:")
        for p in provinces:
            print(f"   ID: {p[0]}, Code: {p[1]}, Path: {p[4]}, Valid: {p[5]} → {p[6]}")
        
        province_code = provinces[0][1]  # Use first province's code
        
        # 2. Count by level
        result = await db.execute(
            text("""
                SELECT level, COUNT(*) 
                FROM administrative_nodes 
                WHERE province_code = :code
                GROUP BY level
                ORDER BY level
            """).bindparams(code=province_code)
        )
        print(f"\n📊 Counts for province_code '{province_code}':")
        for row in result:
            print(f"   {row[0]}: {row[1]}")
        
        # 3. Show hierarchy tree (first 15 rows)
        result = await db.execute(
            text("""
                SELECT level, code, name, path, parent_id, valid_to
                FROM administrative_nodes 
                WHERE province_code = :code
                ORDER BY path
                LIMIT 15
            """).bindparams(code=province_code)
        )
        print(f"\n🌳 Hierarchy Tree (first 15):")
        print(f"   {'Level':<10} {'Code':<12} {'Path':<25} {'Name':<30}")
        print(f"   {'-'*10} {'-'*12} {'-'*25} {'-'*30}")
        for row in result:
            indent = "  " * (row[3].count("/"))
            print(f"   {row[0]:<10} {row[1]:<12} {row[3]:<25} {indent}{row[2][:28]}")
        
        # 4. Validate parent-child paths
        result = await db.execute(
            text("""
                SELECT 
                    c.id,
                    c.name,
                    c.path AS child_path,
                    p.path AS parent_path,
                    c.code AS child_code
                FROM administrative_nodes c
                LEFT JOIN administrative_nodes p ON c.parent_id = p.id
                WHERE c.province_code = :code AND c.parent_id IS NOT NULL
                LIMIT 10
            """).bindparams(code=province_code)
        )
        print(f"\n✅ Path Validation (child_path should = parent_path + '/' + child_code):")
        all_valid = True
        for row in result:
            expected = f"{row[3]}/{row[4]}" if row[3] else row[4]
            is_valid = row[2] == expected
            status = "✓" if is_valid else "✗"
            if not is_valid:
                all_valid = False
            print(f"   {status} {row[1][:30]:<30} | path: {row[2]} | expected: {expected}")
        
        if all_valid:
            print(f"\n✅ All paths are VALID!")
        else:
            print(f"\n❌ Some paths are INVALID!")


async def summary():
    """Show overall summary."""
    print("\n" + "=" * 60)
    print("📊 OVERALL SUMMARY")
    print("=" * 60)
    
    async with AsyncSessionLocal() as db:
        # Total count
        result = await db.execute(text("SELECT COUNT(*) FROM administrative_nodes"))
        total = result.scalar()
        print(f"\n   Total nodes: {total}")
        
        # By level
        result = await db.execute(
            text("SELECT level, COUNT(*) FROM administrative_nodes GROUP BY level ORDER BY level")
        )
        print("\n   By Level:")
        for row in result:
            print(f"      {row[0]}: {row[1]}")
        
        # By structure (OLD vs NEW)
        result = await db.execute(
            text("""
                SELECT 
                    CASE WHEN valid_to IS NULL THEN 'NEW (2-level)' ELSE 'OLD (3-level)' END,
                    COUNT(*)
                FROM administrative_nodes
                GROUP BY 1
            """)
        )
        print("\n   By Structure:")
        for row in result:
            print(f"      {row[0]}: {row[1]}")
        
        # Province count
        result = await db.execute(
            text("SELECT COUNT(DISTINCT province_code) FROM administrative_nodes")
        )
        print(f"\n   Unique Province Codes: {result.scalar()}")


async def main():
    await summary()
    
    # First, list some province names to see the actual format
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT name, code FROM administrative_nodes WHERE level = 'PROVINCE' ORDER BY code LIMIT 10")
        )
        print("\n📋 First 10 Province Names (actual format in DB):")
        for row in result:
            print(f"   Code: {row[1]}, Name: '{row[0]}'")
    
    # Try with exact names from DB
    await verify_province("Tỉnh Phú Yên")
    await verify_province("Tỉnh Đắk Lắk")


if __name__ == "__main__":
    asyncio.run(main())
