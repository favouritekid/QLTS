# scripts/seed_leads.py
"""
Comprehensive Lead Seeding Script for Testing Statistics

Creates realistic test data including:
- 200 leads distributed across 3 officers
- 2-5 consultations per lead following allowed_transitions
- Lead status history for each stage transition
- Assignment logs
- Soft-deleted leads, overdue leads, upcoming appointments

Usage:
    python scripts/seed_leads.py --clear --count 200
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional

# Add parent directory to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import AsyncSessionLocal
from app import models


# ============================================================
# CONFIGURATION (from CSV files in Documents/Seeding data)
# ============================================================

# Officers to distribute leads to
OFFICER_IDS = [7, 8, 9]

# Unit IDs (officers 7,8 in unit 2, officer 9 in unit 17)
OFFICER_UNITS = {7: 2, 8: 2, 9: 17}

# Pipeline Stages with distribution weights
PIPELINE_STAGES = [
    {"id": "stg01", "name": "Chưa tư vấn", "weight": 15, "is_final": False},
    {"id": "stg02", "name": "Đang tư vấn", "weight": 25, "is_final": False},
    {"id": "stg03", "name": "Đã nộp hồ sơ", "weight": 12, "is_final": False},
    {"id": "stg04", "name": "Chờ nhập học", "weight": 10, "is_final": False},
    {"id": "stg05", "name": "Đã nộp học phí", "weight": 13, "is_final": False},
    {"id": "stg06", "name": "Đã nhập học", "weight": 15, "is_final": True},
    {"id": "stg07", "name": "Không đi học", "weight": 10, "is_final": True},
]

# Consultation statuses mapped to stages (from consultation_status.csv)
CONSULTATION_STATUSES = {
    "stg01": [
        {"id": "sts00", "name": "Chưa liên hệ", "outcome": "neutral"},
        {"id": "sts01", "name": "Không nghe máy", "outcome": "neutral", "is_universal": True},
        {"id": "sts02", "name": "Thuê bao", "outcome": "neutral", "is_universal": True},
        {"id": "sts03", "name": "Nhầm số", "outcome": "negative"},  # Reactivatable
        {"id": "sts15", "name": "Nhắn tin không trả lời", "outcome": "neutral", "is_universal": True},
    ],
    "stg02": [
        {"id": "sts04", "name": "Không đồng ý", "outcome": "negative"},  # Reactivatable
        {"id": "sts05", "name": "Cân nhắc", "outcome": "neutral"},
        {"id": "sts06", "name": "Đồng ý tư vấn", "outcome": "positive"},
    ],
    "stg03": [
        {"id": "sts07", "name": "Chờ nhập học", "outcome": "neutral"},
        {"id": "sts08", "name": "Không nhập học", "outcome": "negative"},  # Reactivatable
    ],
    "stg04": [
        {"id": "sts09", "name": "Chờ đóng học phí", "outcome": "neutral"},
        {"id": "sts13", "name": "Đã đóng lệ phí", "outcome": "positive"},
    ],
    "stg05": [
        {"id": "sts10", "name": "Đã nộp học phí", "outcome": "positive", "is_final": True},  # FINAL
    ],
    "stg06": [
        {"id": "sts11", "name": "Đã nhập học", "outcome": "positive", "is_final": True},  # FINAL
    ],
    "stg07": [
        {"id": "sts12", "name": "Bỏ học", "outcome": "negative"},  # Reactivatable
        {"id": "sts14", "name": "Đã rút lại học phí", "outcome": "negative"},  # Reactivatable
    ],
}

# Stage progression paths (realistic flow based on allowed_transitions)
STAGE_PATHS = {
    "stg01": ["stg01"],
    "stg02": ["stg01", "stg02"],
    "stg03": ["stg01", "stg02", "stg03"],
    "stg04": ["stg01", "stg02", "stg03", "stg04"],
    "stg05": ["stg01", "stg02", "stg03", "stg04", "stg05"],
    "stg06": ["stg01", "stg02", "stg03", "stg04", "stg05", "stg06"],
    "stg07": ["stg01", "stg02", "stg07"],  # Can drop off early
}

# Program Offerings (from CSV)
OFFERING_IDS = [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33]

# Sources
SOURCES = ["phone", "website", "walk_in", "referral", "facebook", "event"]

# Consultation methods
CONSULTATION_METHODS = ["phone", "email", "sms", "video_call", "in_person"]


# ============================================================
# VIETNAMESE NAME GENERATION
# ============================================================

HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", 
      "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Đinh", "Lưu", "Trương", "Cao"]
TEN_DEM = ["Văn", "Thị", "Hữu", "Minh", "Thanh", "Đức", "Quốc", "Xuân", "Ngọc", "Anh",
           "Hoàng", "Thành", "Phương", "Quang", "Tuấn", "Hồng", "Bảo", "Như", "Kim", ""]
TEN = ["An", "Bình", "Chi", "Dũng", "Em", "Phúc", "Giang", "Hà", "Hùng", "Khoa",
       "Linh", "Mai", "Nam", "Oanh", "Phong", "Quân", "Như", "Sơn", "Trang", "Uyên",
       "Vy", "Yến", "Tú", "Thảo", "Hạnh", "Đạt", "Long", "Hiếu", "Vinh", "Hương"]

LOCATIONS = [
    "TP. Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Đắk Lắk", "Gia Lai",
    "Kon Tum", "Đắk Nông", "Lâm Đồng", "Bình Phước", "Bình Dương",
    "Đồng Nai", "Khánh Hòa", "Phú Yên", "Bình Định", "Quảng Ngãi"
]

EDUCATION_LEVELS = ["high_school", "diploma", "bachelor", "master", None]


def generate_vietnamese_name():
    """Generate a random Vietnamese full name."""
    ho = random.choice(HO)
    ten_dem = random.choice(TEN_DEM)
    ten = random.choice(TEN)
    if ten_dem:
        return f"{ho} {ten_dem} {ten}"
    return f"{ho} {ten}"


def generate_phone():
    """Generate a random Vietnamese phone number."""
    prefixes = ["03", "05", "07", "08", "09"]
    prefix = random.choice(prefixes)
    suffix = "".join([str(random.randint(0, 9)) for _ in range(8)])
    return f"{prefix}{suffix}"


def generate_email(full_name: str, index: int):
    """Generate email from name."""
    name_parts = full_name.lower().split()
    if len(name_parts) >= 2:
        email_name = f"{name_parts[-1]}.{name_parts[0]}{index}"
    else:
        email_name = f"{name_parts[0]}{index}"
    
    # Vietnamese ASCII conversion
    replacements = {
        'á': 'a', 'à': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a', 'ă': 'a', 'ắ': 'a', 'ằ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ấ': 'a', 'ầ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'đ': 'd',
        'é': 'e', 'è': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e', 'ê': 'e', 'ế': 'e', 'ề': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'í': 'i', 'ì': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ó': 'o', 'ò': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o', 'ô': 'o', 'ố': 'o', 'ồ': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ớ': 'o', 'ờ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ú': 'u', 'ù': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u', 'ư': 'u', 'ứ': 'u', 'ừ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ý': 'y', 'ỳ': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
    }
    for vn, ascii_char in replacements.items():
        email_name = email_name.replace(vn, ascii_char)
    
    domains = ["gmail.com", "yahoo.com", "outlook.com"]
    return f"{email_name}@{random.choice(domains)}"


def get_status_for_stage(stage_id: str) -> str:
    """Map pipeline stage to lead status."""
    mapping = {
        "stg01": "new",
        "stg02": random.choice(["assigned", "contacted"]),
        "stg03": "qualified",
        "stg04": "qualified",
        "stg05": "qualified",
        "stg06": "converted",
        "stg07": random.choice(["unqualified", "rejected"]),
    }
    return mapping.get(stage_id, "new")


# ============================================================
# SEEDING FUNCTIONS
# ============================================================

async def seed_leads(count: int = 200):
    """Seed the database with comprehensive test data."""
    print(f"\n🌱 Starting comprehensive seeding of {count} leads...")
    print(f"   Officers: {OFFICER_IDS}")
    print(f"   Time range: 90 days")
    
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        
        # Calculate special lead counts
        num_soft_deleted = int(count * 0.08)  # ~8% deleted
        num_overdue = int(count * 0.12)  # ~12% overdue
        num_upcoming = int(count * 0.10)  # ~10% upcoming in 24h
        num_hot = int(count * 0.15)  # ~15% hot leads
        
        all_leads = []
        all_consultations = []
        all_history = []
        all_assignments = []
        
        # Build weighted stage list
        stage_weights = [s["weight"] for s in PIPELINE_STAGES]
        stage_ids = [s["id"] for s in PIPELINE_STAGES]
        
        for i in range(count):
            # Basic lead info
            full_name = generate_vietnamese_name()
            officer_id = OFFICER_IDS[i % len(OFFICER_IDS)]
            unit_id = OFFICER_UNITS[officer_id]
            
            # Random created_at within last 90 days
            days_ago = random.randint(1, 90)
            created_at = now - timedelta(
                days=days_ago, 
                hours=random.randint(0, 23), 
                minutes=random.randint(0, 59)
            )
            
            # Select pipeline stage
            pipeline_stage_id = random.choices(stage_ids, weights=stage_weights)[0]
            status = get_status_for_stage(pipeline_stage_id)
            
            # Get consultation status for current stage
            stage_statuses = CONSULTATION_STATUSES.get(pipeline_stage_id, [])
            consultation_status_id = None
            if stage_statuses:
                consultation_status_id = random.choice(stage_statuses)["id"]
            
            # Lead score (15% are hot leads with score >= 70)
            if i < num_hot:
                lead_score = random.randint(70, 100)
            else:
                lead_score = random.randint(0, 69)
            
            # Determine special flags
            is_deleted = i < num_soft_deleted
            is_overdue_lead = num_soft_deleted <= i < (num_soft_deleted + num_overdue)
            is_upcoming_lead = (num_soft_deleted + num_overdue) <= i < (num_soft_deleted + num_overdue + num_upcoming)
            
            # Assignment info
            assigned_at = None
            assignment_status = "pending"
            if status != "new":
                assigned_at = created_at + timedelta(hours=random.randint(1, 24))
                assignment_status = "assigned"
            
            # Next activity
            next_activity_at = None
            if is_overdue_lead:
                # Overdue: next_activity in the past
                next_activity_at = now - timedelta(hours=random.randint(1, 72))
            elif is_upcoming_lead:
                # Upcoming: next_activity within 24 hours
                next_activity_at = now + timedelta(hours=random.randint(1, 24))
            elif status in ["assigned", "contacted", "qualified"] and random.random() > 0.5:
                # Random future activity
                next_activity_at = now + timedelta(hours=random.randint(24, 168))
            
            # Soft delete some leads
            deleted_at = None
            if is_deleted:
                deleted_at = created_at + timedelta(days=random.randint(1, days_ago))
            
            # Create lead
            lead = models.Lead(
                full_name=full_name,
                email=generate_email(full_name, i) if random.random() > 0.15 else None,
                phone=generate_phone(),
                phone2=generate_phone() if random.random() > 0.9 else None,
                source=random.choice(SOURCES),
                status=status,
                assignment_status=assignment_status,
                lead_score=lead_score,
                education_level=random.choice(EDUCATION_LEVELS),
                gpa=round(random.uniform(5.0, 10.0), 1) if random.random() > 0.5 else None,
                location=random.choice(LOCATIONS) if random.random() > 0.3 else None,
                birth_year=random.randint(1990, 2006) if random.random() > 0.4 else None,
                created_at=created_at,
                updated_at=now - timedelta(hours=random.randint(0, 24 * days_ago)),
                assigned_at=assigned_at,
                next_activity_at=next_activity_at,
                deleted_at=deleted_at,
                offering_id=random.choice(OFFERING_IDS) if random.random() > 0.15 else None,
                unit_id=unit_id,
                assigned_officer_id=officer_id if status != "new" else None,
                pipeline_stage_id=pipeline_stage_id,
                consultation_status_id=consultation_status_id,
                # Cached fields
                is_hot_lead=lead_score >= 70,
                is_overdue=is_overdue_lead,
                consultation_count=0,  # Will be updated
                last_consultation_at=None,  # Will be updated
            )
            all_leads.append(lead)
            
            if (i + 1) % 50 == 0:
                print(f"  ✓ Generated {i + 1}/{count} leads...")
        
        # Bulk insert leads first to get IDs
        session.add_all(all_leads)
        await session.flush()
        
        print(f"\n📝 Generating consultations and history...")
        
        # Now create consultations and history for each lead
        for idx, lead in enumerate(all_leads):
            if lead.deleted_at:
                continue  # Skip deleted leads for now
                
            # Get the path this lead took through stages
            stage_path = STAGE_PATHS.get(lead.pipeline_stage_id, [lead.pipeline_stage_id])
            
            # Generate 2-5 consultations based on stage path
            num_consultations = min(len(stage_path), random.randint(2, 5))
            consultation_dates = []
            
            # Create timeline of consultations
            base_date = lead.created_at
            for j in range(num_consultations):
                # Each consultation 1-14 days apart
                base_date = base_date + timedelta(
                    days=random.randint(1, 14),
                    hours=random.randint(8, 18)
                )
                if base_date > datetime.now(timezone.utc):
                    break
                consultation_dates.append(base_date)
            
            # Create consultations and history entries
            prev_stage_id = None
            for j, cons_date in enumerate(consultation_dates):
                # Determine which stage this consultation was in
                stage_idx = min(j, len(stage_path) - 1)
                current_stage = stage_path[stage_idx]
                
                # Get status for this stage
                stage_statuses = CONSULTATION_STATUSES.get(current_stage, [])
                cons_status_id = None
                if stage_statuses:
                    cons_status_id = random.choice(stage_statuses)["id"]
                
                # Create consultation
                consultation = models.Consultation(
                    lead_id=lead.id,
                    consultation_date=cons_date,
                    scheduled_at=cons_date - timedelta(days=random.randint(1, 3)) if random.random() > 0.5 else None,
                    method=random.choice(CONSULTATION_METHODS),
                    notes=f"Tư vấn lần {j+1}" if random.random() > 0.5 else None,
                    duration_minutes=random.randint(5, 60) if random.random() > 0.3 else None,
                    officer_id=lead.assigned_officer_id or random.choice(OFFICER_IDS),
                    consultation_status_id=cons_status_id,
                    reminder_sent=cons_date < datetime.now(timezone.utc),
                )
                all_consultations.append(consultation)
                
                # Create history entry if stage changed
                if prev_stage_id and prev_stage_id != current_stage:
                    history = models.LeadStatusHistory(
                        lead_id=lead.id,
                        changed_by_user_id=lead.assigned_officer_id,
                        reason=f"Stage transition: {prev_stage_id} → {current_stage}",
                        changed_at=cons_date,
                        old_status=get_status_for_stage(prev_stage_id),
                        new_status=get_status_for_stage(current_stage),
                        old_pipeline_stage_id=prev_stage_id,
                        new_pipeline_stage_id=current_stage,
                        old_assigned_officer_id=lead.assigned_officer_id,
                        new_assigned_officer_id=lead.assigned_officer_id,
                    )
                    all_history.append(history)
                
                prev_stage_id = current_stage
            
            # Update lead's cached consultation fields
            if consultation_dates:
                lead.consultation_count = len(consultation_dates)
                lead.last_consultation_at = consultation_dates[-1]
            
            # Create assignment log
            if lead.assigned_officer_id:
                assignment = models.AssignmentLog(
                    lead_id=lead.id,
                    officer_id=lead.assigned_officer_id,
                    method="auto" if random.random() > 0.3 else "manual",
                    timestamp=lead.assigned_at or lead.created_at + timedelta(hours=1),
                    reason="Initial assignment from seed script",
                )
                all_assignments.append(assignment)
            
            if (idx + 1) % 50 == 0:
                print(f"  ✓ Processed {idx + 1}/{count} leads (consultations & history)...")
        
        # Bulk insert all related data
        print(f"\n💾 Saving to database...")
        session.add_all(all_consultations)
        session.add_all(all_history)
        session.add_all(all_assignments)
        
        await session.commit()
        
        # Print summary
        print(f"\n✅ Successfully seeded data!")
        print(f"\n📊 Summary:")
        print(f"   Leads: {len(all_leads)}")
        print(f"   ├─ Soft-deleted: {num_soft_deleted}")
        print(f"   ├─ Overdue: {num_overdue}")
        print(f"   ├─ Upcoming (24h): {num_upcoming}")
        print(f"   └─ Hot leads (score>=70): {num_hot}")
        print(f"   Consultations: {len(all_consultations)}")
        print(f"   History entries: {len(all_history)}")
        print(f"   Assignment logs: {len(all_assignments)}")
        
        print(f"\n📊 Pipeline stage distribution:")
        for stage in PIPELINE_STAGES:
            stage_count = sum(1 for l in all_leads if l.pipeline_stage_id == stage["id"] and not l.deleted_at)
            print(f"   {stage['id']}: {stage_count} leads")
        
        print(f"\n👥 Officer distribution:")
        for oid in OFFICER_IDS:
            officer_count = sum(1 for l in all_leads if l.assigned_officer_id == oid and not l.deleted_at)
            print(f"   Officer {oid}: {officer_count} leads")


async def clear_leads():
    """Clear all lead-related data (keeps master data like users, units, etc.)."""
    print("\n🗑️ Clearing all lead-related data...")
    
    async with AsyncSessionLocal() as session:
        # Delete in correct order (children first)
        tables = [
            "lead_status_history",
            "consultation",
            "crm_interaction", 
            "assignment_log",
            "admission_profile",
            "application",
            "lead",
        ]
        
        for table in tables:
            try:
                result = await session.execute(text(f"DELETE FROM {table}"))
                print(f"   ✓ Deleted from {table}: {result.rowcount} rows")
            except Exception as e:
                print(f"   ⚠ Skipped {table}: {e}")
        
        await session.commit()
        print("\n✅ Cleared all lead-related data!")


async def check_existing_data() -> Dict[str, int]:
    """Check existing data counts before clearing."""
    print("\n🔍 BƯỚC 1: Kiểm tra dữ liệu hiện có...")
    
    async with AsyncSessionLocal() as session:
        tables = [
            "lead",
            "consultation",
            "lead_status_history",
            "assignment_log",
            "application",
            "crm_interaction",
        ]
        
        counts = {}
        total = 0
        
        print("\n📊 Dữ liệu hiện có trong database:")
        print("-" * 40)
        
        for table in tables:
            try:
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar() or 0
                counts[table] = count
                total += count
                print(f"   {table}: {count:,} records")
            except Exception as e:
                print(f"   {table}: ⚠ Error - {e}")
                counts[table] = 0
        
        print("-" * 40)
        print(f"   TỔNG: {total:,} records")
        
        return counts


async def interactive_seed(count: int = 200):
    """Interactive 2-step seeding process."""
    
    # BƯỚC 1: Kiểm tra dữ liệu
    counts = await check_existing_data()
    total = sum(counts.values())
    
    if total > 0:
        print("\n⚠️  Dữ liệu hiện có sẽ bị XÓA nếu tiếp tục!")
        print(f"   Tổng cộng {total:,} records sẽ bị xóa.")
        
        confirm = input("\n👉 Bạn có muốn XÓA dữ liệu cũ và tiếp tục? (y/N): ").strip().lower()
        
        if confirm != 'y':
            print("\n❌ Đã hủy. Không có thay đổi nào được thực hiện.")
            return
        
        # Xóa dữ liệu
        await clear_leads()
    else:
        print("\n✅ Database trống, không cần xóa dữ liệu.")
    
    # BƯỚC 2: Seed dữ liệu mới
    print("\n" + "=" * 50)
    print("🌱 BƯỚC 2: Seed dữ liệu mới")
    print("=" * 50)
    
    print(f"\n📋 Cấu hình:")
    print(f"   - Số leads: {count}")
    print(f"   - Officers: {OFFICER_IDS}")
    print(f"   - Stages: {[s['id'] for s in PIPELINE_STAGES]}")
    print(f"   - Thời gian dữ liệu: 90 ngày")
    
    confirm = input("\n👉 Bắt đầu seed? (Y/n): ").strip().lower()
    
    if confirm == 'n':
        print("\n❌ Đã hủy seed.")
        return
    
    # Thực hiện seed
    await seed_leads(count)
    
    print("\n" + "=" * 50)
    print("✅ HOÀN TẤT!")
    print("=" * 50)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Comprehensive lead seeding for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  python scripts/seed_leads.py                    # Interactive mode (khuyến nghị)
  python scripts/seed_leads.py --count 100        # Seed 100 leads (interactive)
  python scripts/seed_leads.py --check            # Chỉ kiểm tra, không thay đổi
  python scripts/seed_leads.py --clear --count 200 --force  # Không hỏi xác nhận
        """
    )
    parser.add_argument("--count", type=int, default=200, help="Số leads cần tạo (mặc định: 200)")
    parser.add_argument("--clear", action="store_true", help="Xóa dữ liệu trước khi seed")
    parser.add_argument("--check", action="store_true", help="Chỉ kiểm tra dữ liệu, không thay đổi")
    parser.add_argument("--force", action="store_true", help="Bỏ qua xác nhận (dùng với --clear)")
    args = parser.parse_args()
    
    async def main():
        if args.check:
            # Chỉ kiểm tra
            await check_existing_data()
            print("\n💡 Dùng lệnh không có --check để seed dữ liệu.")
        elif args.force and args.clear:
            # Force mode - không hỏi
            await clear_leads()
            await seed_leads(args.count)
        else:
            # Interactive mode
            await interactive_seed(args.count)
    
    asyncio.run(main())

