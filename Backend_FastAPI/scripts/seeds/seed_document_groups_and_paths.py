#!/usr/bin/env python
"""
Seed Script: DocumentGroup + DocumentGroupItem + AdmissionPath

This script seeds the following:
1. ConfigDocumentType records (if not exist)
2. DocumentGroup records (shared + method-specific)
3. DocumentGroupItem records (mandatory documents)
4. AdmissionPath records (4 paths for Điều dưỡng - Chính quy 2026)

Usage:
    python -m scripts.seeds.seed_document_groups_and_paths
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.admission_config import DocumentGroup, DocumentGroupItem, AdmissionPath, AdmissionMethod
from app.models.config import ConfigOfferingType, ConfigDocumentType
from app.models import OfferingAcademicInfo


# =============================================================================
# DOCUMENT TYPES (will be created if not exist)
# =============================================================================
DOCUMENT_TYPES = [
    {"code": "hoc_ba", "name": "Học bạ THPT", "description": "Bản sao học bạ 3 năm THPT", "display_order": 1},
    {"code": "cccd", "name": "Căn cước công dân", "description": "Bản sao CCCD hoặc CMND", "display_order": 2},
    {"code": "giay_khai_sinh", "name": "Giấy khai sinh", "description": "Bản sao giấy khai sinh", "display_order": 3},
    {"code": "bang_tot_nghiep", "name": "Bằng tốt nghiệp THPT", "description": "Bằng tốt nghiệp hoặc giấy xác nhận tốt nghiệp", "display_order": 4},
    {"code": "anh_3x4", "name": "Ảnh thẻ 3x4", "description": "4 ảnh 3x4 nền xanh", "display_order": 5},
    {"code": "giay_xac_nhan_suc_khoe", "name": "Giấy xác nhận sức khỏe", "description": "Giấy khám sức khỏe trong 6 tháng", "display_order": 6},
    {"code": "giay_uu_tien", "name": "Giấy xác nhận đối tượng ưu tiên", "description": "Giấy xác nhận ưu tiên (nếu có)", "display_order": 7},
    {"code": "phieu_diem_thpt", "name": "Phiếu điểm thi THPT", "description": "Phiếu điểm thi THPT Quốc gia", "display_order": 8},
    {"code": "phieu_dgnl", "name": "Phiếu điểm ĐGNL", "description": "Phiếu điểm Đánh giá năng lực", "display_order": 9},
    {"code": "giay_chung_nhan_dtt", "name": "Giấy chứng nhận xét tuyển thẳng", "description": "Giấy xác nhận đạt tiêu chuẩn xét tuyển thẳng", "display_order": 10},
]


# =============================================================================
# DOCUMENT GROUPS
# =============================================================================
# Structure:
#   - offering_type_code: which offering type this group belongs to
#   - admission_method_code: NULL = shared, else method-specific
#   - group_code: unique code for this group
#   - group_name: display name
#   - items: list of document_type codes with configs

DOCUMENT_GROUPS = [
    # SHARED documents for Chính quy (applies to ALL methods)
    {
        "offering_type_code": "chinh_quy",
        "admission_method_code": None,  # Shared
        "group_code": "HS_CHINH_QUY_SHARED",
        "group_name": "Hồ sơ chung - Chính quy",
        "description": "Hồ sơ bắt buộc cho tất cả phương thức xét tuyển chính quy",
        "items": [
            {"doc_code": "hoc_ba", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 1},
            {"doc_code": "cccd", "is_mandatory": True, "requires_upload": True, "submission_format": "photo", "display_order": 2},
            {"doc_code": "giay_khai_sinh", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 3},
            {"doc_code": "anh_3x4", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 4},
            {"doc_code": "giay_xac_nhan_suc_khoe", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 5},
            {"doc_code": "giay_uu_tien", "is_mandatory": False, "requires_upload": True, "submission_format": "certified_copy", "display_order": 6},
        ]
    },
    # Method-specific: THPT Quốc gia
    {
        "offering_type_code": "chinh_quy",
        "admission_method_code": "thpt_qg",  # Override
        "group_code": "HS_THPT_QG",
        "group_name": "Hồ sơ xét điểm THPT Quốc gia",
        "description": "Hồ sơ bổ sung cho phương thức xét điểm thi THPT Quốc gia",
        "items": [
            # Include base documents
            {"doc_code": "hoc_ba", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 1},
            {"doc_code": "cccd", "is_mandatory": True, "requires_upload": True, "submission_format": "photo", "display_order": 2},
            {"doc_code": "giay_khai_sinh", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 3},
            {"doc_code": "anh_3x4", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 4},
            {"doc_code": "giay_xac_nhan_suc_khoe", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 5},
            # THPT-specific
            {"doc_code": "phieu_diem_thpt", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 6},
            {"doc_code": "giay_uu_tien", "is_mandatory": False, "requires_upload": True, "submission_format": "certified_copy", "display_order": 7},
        ]
    },
    # Method-specific: ĐGNL
    {
        "offering_type_code": "chinh_quy",
        "admission_method_code": "dgnl",  # Override
        "group_code": "HS_DGNL",
        "group_name": "Hồ sơ xét điểm ĐGNL",
        "description": "Hồ sơ bổ sung cho phương thức xét Đánh giá năng lực",
        "items": [
            {"doc_code": "hoc_ba", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 1},
            {"doc_code": "cccd", "is_mandatory": True, "requires_upload": True, "submission_format": "photo", "display_order": 2},
            {"doc_code": "giay_khai_sinh", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 3},
            {"doc_code": "anh_3x4", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 4},
            {"doc_code": "giay_xac_nhan_suc_khoe", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 5},
            # ĐGNL-specific
            {"doc_code": "phieu_dgnl", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 6},
            {"doc_code": "giay_uu_tien", "is_mandatory": False, "requires_upload": True, "submission_format": "certified_copy", "display_order": 7},
        ]
    },
    # Method-specific: Xét tuyển thẳng
    {
        "offering_type_code": "chinh_quy",
        "admission_method_code": "xet_tuyen_thang",  # Override
        "group_code": "HS_XTT",
        "group_name": "Hồ sơ xét tuyển thẳng",
        "description": "Hồ sơ cho phương thức xét tuyển thẳng",
        "items": [
            {"doc_code": "hoc_ba", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 1},
            {"doc_code": "cccd", "is_mandatory": True, "requires_upload": True, "submission_format": "photo", "display_order": 2},
            {"doc_code": "giay_khai_sinh", "is_mandatory": True, "requires_upload": True, "submission_format": "certified_copy", "display_order": 3},
            {"doc_code": "anh_3x4", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 4},
            {"doc_code": "giay_xac_nhan_suc_khoe", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 5},
            # XTT-specific
            {"doc_code": "giay_chung_nhan_dtt", "is_mandatory": True, "requires_upload": True, "submission_format": "original", "display_order": 6},
        ]
    },
]


# =============================================================================
# ADMISSION PATHS
# =============================================================================
ADMISSION_PATHS = [
    # For academic_info_id=19 (Điều dưỡng - Chính quy 2026)
    {"academic_info_id": 19, "admission_method_code": "hoc_ba", "display_name": "Xét học bạ THPT", "display_order": 1},
    {"academic_info_id": 19, "admission_method_code": "thpt_qg", "display_name": "Xét điểm thi THPT Quốc gia", "display_order": 2},
    {"academic_info_id": 19, "admission_method_code": "dgnl", "display_name": "Xét đánh giá năng lực", "display_order": 3},
    {"academic_info_id": 19, "admission_method_code": "xet_tuyen_thang", "display_name": "Xét tuyển thẳng", "display_order": 4},
]


async def seed_document_types(db: AsyncSession) -> dict[str, int]:
    """Seed ConfigDocumentType and return code->id mapping."""
    print("\n📄 Step 1: Seeding Document Types...")
    
    code_to_id = {}
    created = 0
    existing = 0
    
    for doc_data in DOCUMENT_TYPES:
        # Check by code first
        result = await db.execute(
            select(ConfigDocumentType).where(ConfigDocumentType.code == doc_data["code"])
        )
        doc_type = result.scalar_one_or_none()
        
        if doc_type:
            code_to_id[doc_type.code] = doc_type.id
            existing += 1
            continue
        
        # Also check by name (since name is unique too)
        result = await db.execute(
            select(ConfigDocumentType).where(ConfigDocumentType.name == doc_data["name"])
        )
        doc_type = result.scalar_one_or_none()
        
        if doc_type:
            code_to_id[doc_data["code"]] = doc_type.id  # Map our code to existing id
            existing += 1
            print(f"   ℹ️ Mapped: {doc_data['code']} -> existing {doc_type.code} (ID {doc_type.id})")
            continue
        
        # Create new
        doc_type = ConfigDocumentType(**doc_data, is_active=True)
        db.add(doc_type)
        await db.flush()
        code_to_id[doc_type.code] = doc_type.id
        created += 1
    
    await db.commit()
    print(f"   ✅ Created: {created} | Existing: {existing} | Total: {len(code_to_id)}")
    return code_to_id


async def get_offering_type_map(db: AsyncSession) -> dict[str, int]:
    """Get offering_type code->id mapping."""
    result = await db.execute(select(ConfigOfferingType))
    offering_types = result.scalars().all()
    return {ot.code: ot.id for ot in offering_types}


async def get_admission_method_map(db: AsyncSession) -> dict[str, int]:
    """Get admission_method code->id mapping."""
    result = await db.execute(select(AdmissionMethod))
    methods = result.scalars().all()
    return {m.code: m.id for m in methods}


async def seed_document_groups(
    db: AsyncSession,
    doc_type_map: dict[str, int],
    offering_type_map: dict[str, int],
    method_map: dict[str, int]
) -> int:
    """Seed DocumentGroup and DocumentGroupItem records."""
    print("\n📦 Step 2: Seeding Document Groups...")
    
    created_groups = 0
    created_items = 0
    skipped = 0
    
    for group_data in DOCUMENT_GROUPS:
        # Check if group exists
        result = await db.execute(
            select(DocumentGroup).where(DocumentGroup.code == group_data["group_code"])
        )
        existing_group = result.scalar_one_or_none()
        
        if existing_group:
            skipped += 1
            print(f"   ⏭️ Skipped: {group_data['group_code']} (already exists)")
            continue
        
        # Resolve offering_type_id
        offering_type_id = offering_type_map.get(group_data["offering_type_code"])
        if not offering_type_id:
            print(f"   ⚠️ Skipped: {group_data['group_code']} - offering_type '{group_data['offering_type_code']}' not found")
            continue
        
        # Resolve admission_method_id (optional)
        admission_method_id = None
        if group_data["admission_method_code"]:
            admission_method_id = method_map.get(group_data["admission_method_code"])
            if not admission_method_id:
                print(f"   ⚠️ Skipped: {group_data['group_code']} - method '{group_data['admission_method_code']}' not found")
                continue
        
        # Create DocumentGroup
        group = DocumentGroup(
            offering_type_id=offering_type_id,
            admission_method_id=admission_method_id,
            code=group_data["group_code"],
            name=group_data["group_name"],
            description=group_data.get("description"),
            is_active=True
        )
        db.add(group)
        await db.flush()
        created_groups += 1
        
        # Create DocumentGroupItem records
        for item_data in group_data["items"]:
            doc_type_id = doc_type_map.get(item_data["doc_code"])
            if not doc_type_id:
                print(f"   ⚠️ Skipping item: doc_code '{item_data['doc_code']}' not found")
                continue
            
            item = DocumentGroupItem(
                group_id=group.id,
                document_type_id=doc_type_id,
                is_mandatory=item_data["is_mandatory"],
                requires_upload=item_data["requires_upload"],
                submission_format=item_data.get("submission_format"),
                display_order=item_data["display_order"]
            )
            db.add(item)
            created_items += 1
        
        method_note = f"method={group_data['admission_method_code']}" if group_data["admission_method_code"] else "shared"
        print(f"   ✅ Created: {group_data['group_code']} ({method_note})")
    
    await db.commit()
    print(f"\n   📊 Summary: {created_groups} groups, {created_items} items | Skipped: {skipped}")
    return created_groups


async def seed_admission_paths(db: AsyncSession, method_map: dict[str, int]) -> int:
    """Seed AdmissionPath records."""
    print("\n🛤️ Step 3: Seeding Admission Paths...")
    
    created = 0
    skipped = 0
    
    for path_data in ADMISSION_PATHS:
        # Resolve admission_method_id
        admission_method_id = method_map.get(path_data["admission_method_code"])
        if not admission_method_id:
            print(f"   ⚠️ Skipped: method '{path_data['admission_method_code']}' not found")
            continue
        
        # Check if path exists
        result = await db.execute(
            select(AdmissionPath).where(
                AdmissionPath.academic_info_id == path_data["academic_info_id"],
                AdmissionPath.admission_method_id == admission_method_id
            )
        )
        existing_path = result.scalar_one_or_none()
        
        if existing_path:
            skipped += 1
            print(f"   ⏭️ Skipped: {path_data['display_name']} (already exists)")
            continue
        
        # Create AdmissionPath with status='active' (ready for use)
        path = AdmissionPath(
            academic_info_id=path_data["academic_info_id"],
            admission_method_id=admission_method_id,
            display_name=path_data["display_name"],
            display_order=path_data["display_order"],
            status="active",  # Ready to use
            visibility="public"
        )
        db.add(path)
        created += 1
        print(f"   ✅ Created: {path_data['display_name']} (status=active)")
    
    await db.commit()
    print(f"\n   📊 Summary: {created} paths created | Skipped: {skipped}")
    return created


async def verify_data(db: AsyncSession):
    """Verify seeded data."""
    print("\n🔍 Step 4: Verifying seeded data...")
    
    # Count groups
    result = await db.execute(select(DocumentGroup).where(DocumentGroup.is_active == True))
    groups = result.scalars().all()
    print(f"   DocumentGroup: {len(groups)} active records")
    
    # Count items
    result = await db.execute(select(DocumentGroupItem))
    items = result.scalars().all()
    print(f"   DocumentGroupItem: {len(items)} records")
    
    # Count paths
    result = await db.execute(select(AdmissionPath))
    paths = result.scalars().all()
    print(f"   AdmissionPath: {len(paths)} records")
    
    # Show active paths
    print("\n   📋 Active Admission Paths:")
    for p in paths:
        print(f"      - ID {p.id}: {p.display_name} | Status: {p.status}")


async def main():
    """Main seed function."""
    print("=" * 70)
    print("🚀 SEED: DocumentGroup + AdmissionPath")
    print("=" * 70)
    
    async with AsyncSessionLocal() as db:
        # Step 1: Seed document types
        doc_type_map = await seed_document_types(db)
        
        # Get mappings
        offering_type_map = await get_offering_type_map(db)
        method_map = await get_admission_method_map(db)
        
        print(f"\n   📍 Offering Types: {list(offering_type_map.keys())}")
        print(f"   📍 Methods: {list(method_map.keys())}")
        
        # Step 2: Seed document groups
        await seed_document_groups(db, doc_type_map, offering_type_map, method_map)
        
        # Step 3: Seed admission paths
        await seed_admission_paths(db, method_map)
        
        # Step 4: Verify
        await verify_data(db)
        
        print("\n" + "=" * 70)
        print("✅ SEED COMPLETE!")
        print("=" * 70)
        print("\nNext steps:")
        print("  1. Test creating admission profile with admission_method_id")
        print("  2. Verify resolve_documents_for_path returns correct documents")


if __name__ == "__main__":
    asyncio.run(main())
