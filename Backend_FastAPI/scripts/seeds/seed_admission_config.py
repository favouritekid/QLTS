# scripts/seeds/seed_admission_config.py
"""
Phase 2: Seed Admission Config Data.

Seeds:
1. Subject - 20 môn học
2. SubjectGroup - tổ hợp môn (A00, D01...) + flexible groups
3. SubjectGroupSubject - mapping môn vào tổ hợp
4. AdmissionMethod - phương thức tuyển sinh
5. AdmissionCriteria - tiêu chí với Rule Engine config

Usage:
    python -m scripts.seeds.seed_admission_config
"""

import asyncio
import sys
import os

# Add parent dir to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.admission_config import (
    Subject,
    SubjectGroup,
    SubjectGroupSubject,
    AdmissionMethod,
    AdmissionCriteria,
)


# =============================================================================
# SUBJECT DATA (20 môn học)
# =============================================================================
SUBJECTS = [
    # Core subjects
    {"code": "math", "name_vi": "Toán", "display_order": 1},
    {"code": "literature", "name_vi": "Ngữ văn", "display_order": 2},
    {"code": "english", "name_vi": "Tiếng Anh", "display_order": 3},
    {"code": "physics", "name_vi": "Vật lý", "display_order": 4},
    {"code": "chemistry", "name_vi": "Hóa học", "display_order": 5},
    {"code": "biology", "name_vi": "Sinh học", "display_order": 6},
    {"code": "history", "name_vi": "Lịch sử", "display_order": 7},
    {"code": "geography", "name_vi": "Địa lý", "display_order": 8},
    {"code": "civic_education", "name_vi": "Giáo dục công dân", "display_order": 9},
    # Foreign languages
    {"code": "french", "name_vi": "Tiếng Pháp", "display_order": 10},
    {"code": "german", "name_vi": "Tiếng Đức", "display_order": 11},
    {"code": "russian", "name_vi": "Tiếng Nga", "display_order": 12},
    {"code": "chinese", "name_vi": "Tiếng Trung", "display_order": 13},
    {"code": "japanese", "name_vi": "Tiếng Nhật", "display_order": 14},
    {"code": "korean", "name_vi": "Tiếng Hàn", "display_order": 15},
    # Arts
    {"code": "art", "name_vi": "Mỹ thuật", "display_order": 16},
    {"code": "music", "name_vi": "Âm nhạc", "display_order": 17},
    # Other
    {"code": "informatics", "name_vi": "Tin học", "display_order": 18},
    {"code": "technology", "name_vi": "Công nghệ", "display_order": 19},
    {"code": "physical_education", "name_vi": "Thể dục", "display_order": 20},
]


# =============================================================================
# SUBJECT GROUP DATA
# Now includes: Traditional 3-môn groups + Flexible 2-môn groups for TC/CĐ
# =============================================================================
SUBJECT_GROUPS = [
    # ========== A groups (Tự nhiên - 3 môn) ==========
    {"code": "A00", "name": "Toán, Vật lý, Hóa học", "subjects": ["math", "physics", "chemistry"]},
    {"code": "A01", "name": "Toán, Vật lý, Tiếng Anh", "subjects": ["math", "physics", "english"]},
    {"code": "A02", "name": "Toán, Vật lý, Sinh học", "subjects": ["math", "physics", "biology"]},
    
    # ========== B groups (Sinh học - 3 môn) ==========
    {"code": "B00", "name": "Toán, Hóa học, Sinh học", "subjects": ["math", "chemistry", "biology"]},
    {"code": "B08", "name": "Toán, Sinh học, Tiếng Anh", "subjects": ["math", "biology", "english"]},
    
    # ========== C groups (Xã hội - 3 môn) ==========
    {"code": "C00", "name": "Ngữ văn, Lịch sử, Địa lý", "subjects": ["literature", "history", "geography"]},
    {"code": "C01", "name": "Ngữ văn, Toán, Vật lý", "subjects": ["literature", "math", "physics"]},
    
    # ========== D groups (Ngoại ngữ - 3 môn) ==========
    {"code": "D01", "name": "Ngữ văn, Toán, Tiếng Anh", "subjects": ["literature", "math", "english"]},
    {"code": "D07", "name": "Toán, Hóa học, Tiếng Anh", "subjects": ["math", "chemistry", "english"]},
    {"code": "D14", "name": "Ngữ văn, Lịch sử, Tiếng Anh", "subjects": ["literature", "history", "english"]},
    
    # ========== TC/CĐ Flexible Groups (2 môn) ==========
    {"code": "TC01", "name": "Toán, Văn (Trung cấp)", "subjects": ["math", "literature"]},
    {"code": "TC02", "name": "Toán, Anh (Trung cấp)", "subjects": ["math", "english"]},
    {"code": "CD01", "name": "Toán, Văn (Cao đẳng)", "subjects": ["math", "literature"]},
    {"code": "CD02", "name": "Toán, Lý (Cao đẳng)", "subjects": ["math", "physics"]},
    
    # ========== Single subject pools (1 môn - xét đơn) ==========
    {"code": "S_MATH", "name": "Chỉ Toán", "subjects": ["math"]},
    {"code": "S_LIT", "name": "Chỉ Văn", "subjects": ["literature"]},
    
    # ========== Large pools (Best-N selection) ==========
    {"code": "P_KHTN", "name": "Pool Khoa học tự nhiên", "subjects": ["math", "physics", "chemistry", "biology"]},
    {"code": "P_KHXH", "name": "Pool Khoa học xã hội", "subjects": ["literature", "history", "geography", "civic_education"]},
    {"code": "P_ALL", "name": "Pool tất cả môn chính", "subjects": ["math", "literature", "physics", "chemistry", "biology", "history", "geography", "english"]},
]


# =============================================================================
# ADMISSION METHOD DATA
# =============================================================================
ADMISSION_METHODS = [
    {
        "code": "hoc_ba",
        "name": "Xét học bạ THPT",
        "description": "Xét tuyển dựa trên điểm trung bình học bạ 3 năm THPT",
        "requires_gpa": True,
        "requires_subject_scores": True,
        "display_order": 1,
    },
    {
        "code": "thpt_qg",
        "name": "Xét điểm thi THPT Quốc gia",
        "description": "Xét tuyển dựa trên điểm thi tốt nghiệp THPT Quốc gia",
        "requires_gpa": False,
        "requires_subject_scores": True,
        "display_order": 2,
    },
    {
        "code": "dgnl",
        "name": "Xét đánh giá năng lực",  
        "description": "Xét tuyển dựa trên kết quả kỳ thi đánh giá năng lực (ĐHQG)",
        "requires_gpa": False,
        "requires_subject_scores": False,
        "display_order": 3,
    },
    {
        "code": "xet_tuyen_thang",
        "name": "Xét tuyển thẳng",
        "description": "Xét tuyển thẳng theo quy định (học sinh giỏi quốc gia, quốc tế)",
        "requires_gpa": False,
        "requires_subject_scores": False,
        "display_order": 4,
    },
]


# =============================================================================
# ADMISSION CRITERIA DATA (with Rule Engine config)
# =============================================================================
ADMISSION_CRITERIA = [
    # ========== ĐẠI HỌC - 3 MÔN ==========
    {
        "method_code": "hoc_ba",
        "code": "HB_DH_3MON",
        "name": "Học bạ Đại học - 3 môn cố định",
        "min_gpa": Decimal("6.0"),
        "min_score": Decimal("18.0"),
        # Rule Engine config
        "required_subject_count": 3,
        "subject_selection_mode": "fixed",
        "scoring_method": "sum",
        "max_possible_score": Decimal("30.0"),
        "min_subject_score": Decimal("1.0"),
    },
    {
        "method_code": "thpt_qg",
        "code": "THPT_DH_3MON",
        "name": "THPT Quốc gia Đại học - 3 môn",
        "min_gpa": None,
        "min_score": Decimal("15.0"),
        "required_subject_count": 3,
        "subject_selection_mode": "fixed",
        "scoring_method": "sum",
        "max_possible_score": Decimal("30.0"),
        "min_subject_score": Decimal("1.0"),
    },
    
    # ========== CAO ĐẲNG - 2 MÔN ==========
    {
        "method_code": "hoc_ba",
        "code": "HB_CD_2MON",
        "name": "Học bạ Cao đẳng - 2 môn",
        "min_gpa": Decimal("5.0"),
        "min_score": Decimal("10.0"),
        "required_subject_count": 2,
        "subject_selection_mode": "fixed",
        "scoring_method": "sum",
        "max_possible_score": Decimal("20.0"),
        "min_subject_score": None,  # Không yêu cầu điểm liệt
    },
    {
        "method_code": "hoc_ba",
        "code": "HB_CD_BEST2",
        "name": "Học bạ Cao đẳng - Best 2 từ 4 môn",
        "min_gpa": Decimal("5.0"),
        "min_score": Decimal("12.0"),
        "required_subject_count": 2,
        "subject_selection_mode": "best_n",  # Chọn 2 môn cao nhất
        "scoring_method": "sum",
        "max_possible_score": Decimal("20.0"),
        "min_subject_score": None,
    },
    
    # ========== TRUNG CẤP - 1-2 MÔN ==========
    {
        "method_code": "hoc_ba",
        "code": "HB_TC_1MON",
        "name": "Học bạ Trung cấp - 1 môn Toán",
        "min_gpa": None,
        "min_score": Decimal("5.0"),
        "required_subject_count": 1,
        "subject_selection_mode": "fixed",
        "scoring_method": "sum",  # Sum of 1 = same as value
        "max_possible_score": Decimal("10.0"),
        "min_subject_score": None,
    },
    {
        "method_code": "hoc_ba",
        "code": "HB_TC_2MON",
        "name": "Học bạ Trung cấp - 2 môn Toán Văn",
        "min_gpa": None,
        "min_score": Decimal("8.0"),
        "required_subject_count": 2,
        "subject_selection_mode": "fixed",
        "scoring_method": "average",  # Trung bình 2 môn
        "max_possible_score": Decimal("10.0"),  # Average max = 10
        "min_subject_score": None,
    },
    
    # ========== FLEXIBLE - XÉT TẤT CẢ ==========
    {
        "method_code": "hoc_ba",
        "code": "HB_FLEX_AVG",
        "name": "Học bạ linh hoạt - Trung bình tất cả môn",
        "min_gpa": Decimal("5.0"),
        "min_score": Decimal("5.0"),  # Average >= 5.0
        "required_subject_count": None,  # Xét tất cả môn có điểm
        "subject_selection_mode": "any_n",
        "scoring_method": "average",
        "max_possible_score": Decimal("10.0"),
        "min_subject_score": None,
    },
]


async def seed_subjects(db: AsyncSession) -> dict[str, int]:
    """Seed Subject table and return code->id mapping."""
    print("📚 Seeding Subjects...")
    
    code_to_id = {}
    
    for subject_data in SUBJECTS:
        # Check if exists
        result = await db.execute(
            select(Subject).where(Subject.code == subject_data["code"])
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            code_to_id[existing.code] = existing.id
            print(f"  - {subject_data['code']}: exists (id={existing.id})")
        else:
            subject = Subject(**subject_data, is_active=True)
            db.add(subject)
            await db.flush()
            code_to_id[subject.code] = subject.id
            print(f"  ✅ {subject_data['code']}: created (id={subject.id})")
    
    await db.commit()
    print(f"  Total: {len(code_to_id)} subjects")
    return code_to_id


async def seed_subject_groups(db: AsyncSession, subject_code_to_id: dict[str, int]) -> dict[str, int]:
    """Seed SubjectGroup and SubjectGroupSubject tables."""
    print("\n📐 Seeding Subject Groups...")
    
    group_code_to_id = {}
    
    for idx, group_data in enumerate(SUBJECT_GROUPS):
        code = group_data["code"]
        name = group_data["name"]
        subject_codes = group_data["subjects"]
        
        # Check if group exists
        result = await db.execute(
            select(SubjectGroup).where(SubjectGroup.code == code)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            group_code_to_id[code] = existing.id
            print(f"  - {code}: exists (id={existing.id})")
            continue
        
        # Create group
        group = SubjectGroup(
            code=code,
            name=name,
            display_order=idx + 1,
            is_active=True
        )
        db.add(group)
        await db.flush()
        group_code_to_id[code] = group.id
        
        # Create subject mappings
        for position, subject_code in enumerate(subject_codes, start=1):
            subject_id = subject_code_to_id.get(subject_code)
            if not subject_id:
                print(f"    ⚠️ Subject {subject_code} not found!")
                continue
            
            mapping = SubjectGroupSubject(
                subject_group_id=group.id,
                subject_id=subject_id,
                position=position
            )
            db.add(mapping)
        
        subjects_count = len(subject_codes)
        print(f"  ✅ {code}: created ({subjects_count} môn)")
    
    await db.commit()
    print(f"  Total: {len(group_code_to_id)} groups")
    return group_code_to_id


async def seed_admission_methods(db: AsyncSession) -> dict[str, int]:
    """Seed AdmissionMethod table."""
    print("\n🎓 Seeding Admission Methods...")
    
    code_to_id = {}
    
    for method_data in ADMISSION_METHODS:
        result = await db.execute(
            select(AdmissionMethod).where(AdmissionMethod.code == method_data["code"])
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            code_to_id[existing.code] = existing.id
            print(f"  - {method_data['code']}: exists (id={existing.id})")
        else:
            method = AdmissionMethod(**method_data, is_active=True)
            db.add(method)
            await db.flush()
            code_to_id[method.code] = method.id
            print(f"  ✅ {method_data['code']}: created (id={method.id})")
    
    await db.commit()
    print(f"  Total: {len(code_to_id)} methods")
    return code_to_id


async def seed_admission_criteria(db: AsyncSession, method_code_to_id: dict[str, int]) -> dict[str, int]:
    """Seed AdmissionCriteria table with Rule Engine config."""
    print("\n📋 Seeding Admission Criteria (with Rule Engine)...")
    
    code_to_id = {}
    
    for criteria_data in ADMISSION_CRITERIA:
        code = criteria_data["code"]
        method_code = criteria_data.pop("method_code")
        method_id = method_code_to_id.get(method_code)
        
        if not method_id:
            print(f"  ⚠️ Method {method_code} not found for {code}")
            continue
        
        result = await db.execute(
            select(AdmissionCriteria).where(AdmissionCriteria.code == code)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            code_to_id[code] = existing.id
            print(f"  - {code}: exists (id={existing.id})")
        else:
            criteria = AdmissionCriteria(
                method_id=method_id,
                is_active=True,
                **criteria_data
            )
            db.add(criteria)
            await db.flush()
            code_to_id[code] = criteria.id
            
            # Show rule engine config
            req_count = criteria_data.get("required_subject_count") or "ALL"
            mode = criteria_data.get("subject_selection_mode", "fixed")
            method = criteria_data.get("scoring_method", "sum")
            print(f"  ✅ {code}: created ({req_count} môn, {mode}, {method})")
    
    await db.commit()
    print(f"  Total: {len(code_to_id)} criteria")
    return code_to_id


async def main():
    """Main seeding function."""
    print("=" * 60)
    print("🌱 PHASE 2: SEED ADMISSION CONFIG DATA (with Rule Engine)")
    print("=" * 60)
    
    async with AsyncSessionLocal() as db:
        # 1. Seed Subjects
        subject_ids = await seed_subjects(db)
        
        # 2. Seed Subject Groups (with mappings)
        group_ids = await seed_subject_groups(db, subject_ids)
        
        # 3. Seed Admission Methods
        method_ids = await seed_admission_methods(db)
        
        # 4. Seed Admission Criteria (with Rule Engine config)
        criteria_ids = await seed_admission_criteria(db, method_ids)
        
        print("\n" + "=" * 60)
        print("✅ SEEDING COMPLETE!")
        print("=" * 60)
        print(f"  📚 Subjects: {len(subject_ids)}")
        print(f"  📐 Subject Groups: {len(group_ids)} (includes TC/CĐ flexible groups)")  
        print(f"  🎓 Admission Methods: {len(method_ids)}")
        print(f"  📋 Admission Criteria: {len(criteria_ids)} (with Rule Engine config)")
        print()
        print("  Rule Engine modes seeded:")
        print("    - fixed (3 môn ĐH)")
        print("    - fixed (2 môn CĐ)")
        print("    - fixed (1 môn TC)")
        print("    - best_n (Best 2 từ 4)")
        print("    - any_n (Flexible average)")


if __name__ == "__main__":
    asyncio.run(main())
