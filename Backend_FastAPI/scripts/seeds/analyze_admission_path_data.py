#!/usr/bin/env python
"""
Data Analysis Script for AdmissionPath Seeding

This script analyzes existing data in the database to determine
what AdmissionPath records should be created for testing.

It will report:
1. Existing OfferingAcademicInfo records (offering + year)
2. Existing AdmissionMethod records
3. Existing DocumentGroup records
4. Current AdmissionPath records (if any)
5. Recommended AdmissionPath combinations to create
"""

import asyncio
import sys
sys.path.insert(0, ".")

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import (
    OfferingAcademicInfo,
    ProgramOffering,
    MajorProgram,
)
from app.models.admission_config import (
    AdmissionMethod,
    AdmissionPath,
    DocumentGroup,
    AdmissionCriteria,
)


async def analyze_data():
    print("=" * 70)
    print("📊 DATA ANALYSIS FOR ADMISSION PATH SEEDING")
    print("=" * 70)
    
    async with AsyncSessionLocal() as db:
        # 1. Check OfferingAcademicInfo
        print("\n📌 1. OFFERING ACADEMIC INFO (Year-specific offerings)")
        print("-" * 50)
        
        query = (
            select(OfferingAcademicInfo)
            .options(
                selectinload(OfferingAcademicInfo.offering)
                .selectinload(ProgramOffering.program)
            )
            .order_by(OfferingAcademicInfo.academic_year.desc())
        )
        result = await db.execute(query)
        academic_infos = list(result.scalars().all())
        
        if not academic_infos:
            print("⚠️  No OfferingAcademicInfo records found!")
            print("   You need to create academic info before seeding paths.")
        else:
            print(f"✅ Found {len(academic_infos)} OfferingAcademicInfo records:")
            for info in academic_infos:
                program_name = info.offering.program.name if info.offering and info.offering.program else "N/A"
                offering_type = info.offering.offering_type if info.offering else "N/A"
                print(f"   - ID {info.id}: Year {info.academic_year} | {program_name} ({offering_type})")
                print(f"     Published: {info.is_published} | Quota: {info.annual_admission_quota or 'N/A'}")
        
        # 2. Check AdmissionMethod
        print("\n📌 2. ADMISSION METHODS")
        print("-" * 50)
        
        query = select(AdmissionMethod).where(AdmissionMethod.is_active == True)
        result = await db.execute(query)
        methods = list(result.scalars().all())
        
        if not methods:
            print("⚠️  No active AdmissionMethod records found!")
            print("   Run the admission config seed script first.")
        else:
            print(f"✅ Found {len(methods)} active admission methods:")
            for m in methods:
                print(f"   - ID {m.id}: {m.code} - {m.name}")
        
        # 3. Check DocumentGroup
        print("\n📌 3. DOCUMENT GROUPS")
        print("-" * 50)
        
        query = (
            select(DocumentGroup)
            .options(selectinload(DocumentGroup.offering_type))
            .where(DocumentGroup.is_active == True)
        )
        result = await db.execute(query)
        doc_groups = list(result.scalars().all())
        
        if not doc_groups:
            print("⚠️  No active DocumentGroup records found!")
            print("   You may want to seed document groups first.")
        else:
            print(f"✅ Found {len(doc_groups)} active document groups:")
            for g in doc_groups:
                offering_type_name = g.offering_type.name if g.offering_type else "All"
                method_note = f"Method ID: {g.admission_method_id}" if g.admission_method_id else "Shared"
                print(f"   - ID {g.id}: {g.name} ({offering_type_name}) [{method_note}]")
        
        # 4. Check existing AdmissionPath
        print("\n📌 4. EXISTING ADMISSION PATHS")
        print("-" * 50)
        
        query = (
            select(AdmissionPath)
            .options(
                selectinload(AdmissionPath.academic_info),
                selectinload(AdmissionPath.admission_method),
            )
        )
        result = await db.execute(query)
        existing_paths = list(result.scalars().all())
        
        if not existing_paths:
            print("ℹ️  No AdmissionPath records found (as expected)")
        else:
            print(f"Found {len(existing_paths)} existing paths:")
            for p in existing_paths:
                method_name = p.admission_method.name if p.admission_method else "N/A"
                print(f"   - ID {p.id}: {p.display_name} | Status: {p.status} | Method: {method_name}")
        
        # 5. Check AdmissionCriteria
        print("\n📌 5. ADMISSION CRITERIA")
        print("-" * 50)
        
        query = select(AdmissionCriteria).where(AdmissionCriteria.is_active == True)
        result = await db.execute(query)
        criteria = list(result.scalars().all())
        
        if not criteria:
            print("⚠️  No active AdmissionCriteria records found!")
            print("   Paths can be created without criteria, but activation will fail.")
        else:
            print(f"✅ Found {len(criteria)} active criteria:")
            for c in criteria:
                print(f"   - ID {c.id}: {c.name} | Min GPA: {c.min_gpa}")
        
        # 6. Recommend paths to create
        print("\n" + "=" * 70)
        print("📋 RECOMMENDED ADMISSION PATHS TO CREATE")
        print("=" * 70)
        
        if not academic_infos:
            print("\n❌ Cannot recommend paths - no OfferingAcademicInfo exists.")
            print("   Create academic info first!")
            return
        
        if not methods:
            print("\n❌ Cannot recommend paths - no AdmissionMethod exists.")
            print("   Seed admission methods first!")
            return
        
        print("\nBased on existing data, the following paths should be created:")
        print()
        
        path_count = 0
        for info in academic_infos:
            if not info.is_published:
                continue
            
            program_name = info.offering.program.name if info.offering and info.offering.program else "Unknown"
            offering_type = info.offering.offering_type if info.offering else "Unknown"
            
            print(f"📁 {program_name} - {offering_type} (Year {info.academic_year})")
            print(f"   academic_info_id = {info.id}")
            
            for method in methods:
                path_count += 1
                print(f"   → Path {path_count}: method_id={method.id} ({method.code})")
            print()
        
        print(f"\nTotal paths to create: {path_count}")
        print("\nNote: These paths will be created with status='draft'.")
        print("You will need to activate them via API or Config Console.")


if __name__ == "__main__":
    asyncio.run(analyze_data())
