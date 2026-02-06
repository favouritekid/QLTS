# scripts/seed_leads.py
"""
Comprehensive Lead Seeding Script for Testing Statistics

Creates realistic test data including:
- Leads distributed across available officers
- 2-5 consultations per lead following allowed_transitions
- Lead status history for each stage transition
- Assignment logs
- Soft-deleted leads, overdue leads, upcoming appointments

Usage:
    python scripts/seed_leads.py                    # Interactive mode (recommended)
    python scripts/seed_leads.py --count 100        # Seed 100 leads
    python scripts/seed_leads.py --check            # Check existing data only
    python scripts/seed_leads.py --clear --force    # Clear and seed without confirmation
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Optional, Tuple
from decimal import Decimal

# Add parent directory to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text, select
from sqlalchemy.orm import selectinload
from app.database import AsyncSessionLocal
from app import models
from app.models.pipeline import PipelineStage, ConsultationStatus


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
SOURCES = ["phone", "website", "walk_in", "referral", "facebook", "event"]
CONSULTATION_METHODS = ["phone", "email", "sms", "video_call", "in_person"]


def generate_vietnamese_name() -> str:
    """Generate a random Vietnamese full name."""
    ho = random.choice(HO)
    ten_dem = random.choice(TEN_DEM)
    ten = random.choice(TEN)
    if ten_dem:
        return f"{ho} {ten_dem} {ten}"
    return f"{ho} {ten}"


def generate_phone() -> str:
    """Generate a random Vietnamese phone number."""
    prefixes = ["03", "05", "07", "08", "09"]
    prefix = random.choice(prefixes)
    suffix = "".join([str(random.randint(0, 9)) for _ in range(8)])
    return f"{prefix}{suffix}"


def generate_email(full_name: str, index: int) -> str:
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


# ============================================================
# DATABASE CONFIGURATION LOADER
# ============================================================

class SeedConfig:
    """Configuration loaded from database."""

    def __init__(self):
        self.officers: List[Tuple[int, int]] = []  # (user_id, unit_id)
        self.offering_ids: List[int] = []
        self.pipeline_stages: List[Dict] = []
        self.consultation_statuses: Dict[str, List[Dict]] = {}
        self.stage_paths: Dict[str, List[str]] = {}

    async def load(self, session) -> bool:
        """Load configuration from database. Returns False if missing required data."""
        print("\n📋 Loading configuration from database...")

        # 1. Load officers (users with role 'officer' who are active)
        # Note: User model uses `status` column, not `is_active`
        result = await session.execute(
            select(models.User)
            .where(
                models.User.role == "officer",
                models.User.status == "active",
                models.User.unit_id.isnot(None)
            )
            .limit(10)
        )
        officers = result.scalars().all()

        if not officers:
            # Fallback: get any active users with unit_id
            result = await session.execute(
                select(models.User)
                .where(
                    models.User.status == "active",
                    models.User.unit_id.isnot(None)
                )
                .limit(10)
            )
            officers = result.scalars().all()

        if not officers:
            print("   ❌ No active users with unit_id found!")
            return False

        self.officers = [(o.id, o.unit_id) for o in officers]
        print(f"   ✅ Found {len(self.officers)} officers: {[o[0] for o in self.officers]}")

        # 2. Load program offerings
        result = await session.execute(
            select(models.ProgramOffering.id)
            .where(models.ProgramOffering.is_active == True)
            .limit(50)
        )
        self.offering_ids = [r[0] for r in result.all()]

        if not self.offering_ids:
            print("   ⚠️  No active program offerings found (will create leads without offering)")
        else:
            print(f"   ✅ Found {len(self.offering_ids)} active offerings")

        # 3. Load pipeline stages
        # Note: PipelineStage uses is_final_stage, not is_final or is_active
        result = await session.execute(
            select(PipelineStage)
            .order_by(PipelineStage.order)
        )
        stages = result.scalars().all()

        if not stages:
            print("   ❌ No pipeline stages found!")
            return False

        self.pipeline_stages = [
            {
                "id": s.id,
                "name": s.name,
                "is_final": s.is_final_stage,  # Use is_final_stage column
                "order": s.order,
            }
            for s in stages
        ]
        print(f"   ✅ Found {len(self.pipeline_stages)} pipeline stages")

        # 4. Load consultation statuses grouped by stage
        # Note: ConsultationStatus doesn't have is_active, load all
        result = await session.execute(
            select(ConsultationStatus)
        )
        statuses = result.scalars().all()

        if not statuses:
            print("   ❌ No active consultation statuses found!")
            return False

        # Group statuses by stage_id (ConsultationStatus uses stage_id, not pipeline_stage_id)
        for status in statuses:
            stage_id = status.stage_id  # stage_id column
            if stage_id not in self.consultation_statuses:
                self.consultation_statuses[stage_id] = []
            self.consultation_statuses[stage_id].append({
                "id": status.id,
                "name": status.name,
                "outcome": getattr(status, 'outcome', 'neutral'),
            })

        print(f"   ✅ Found {len(statuses)} consultation statuses")

        # 5. Build stage progression paths
        sorted_stages = sorted(self.pipeline_stages, key=lambda x: x["order"])
        for i, stage in enumerate(sorted_stages):
            # Path is all stages from first to current
            path = [s["id"] for s in sorted_stages[:i+1]]
            self.stage_paths[stage["id"]] = path

        return True

    def get_random_officer(self) -> Tuple[int, int]:
        """Get random (officer_id, unit_id)."""
        return random.choice(self.officers)

    def get_random_stage(self, consultation_only: bool = False) -> Dict:
        """Get random pipeline stage with weighted distribution.

        Args:
            consultation_only: If True, only return non-final stages (consultation phase)
        """
        # Filter stages if consultation_only
        if consultation_only:
            available_stages = [s for s in self.pipeline_stages if not s["is_final"]]
            if not available_stages:
                available_stages = self.pipeline_stages  # Fallback
        else:
            available_stages = self.pipeline_stages

        # Weight towards middle stages
        weights = []
        for i, stage in enumerate(available_stages):
            if stage["is_final"]:
                weights.append(10)  # Lower weight for final stages
            elif stage["order"] == 1:
                weights.append(10)  # Lower weight for first stage (not yet contacted)
            else:
                weights.append(25)  # Higher weight for consultation stages

        return random.choices(available_stages, weights=weights)[0]

    def get_status_for_stage(self, stage_id: str) -> Optional[str]:
        """Get random consultation status for a stage."""
        statuses = self.consultation_statuses.get(stage_id, [])
        if statuses:
            return random.choice(statuses)["id"]
        return None

    def get_lead_status_for_stage(self, stage: Dict) -> str:
        """Map pipeline stage to lead status."""
        order = stage["order"]
        is_final = stage["is_final"]

        if order == 1:
            return "new"
        elif is_final:
            # Check if it's a positive or negative final stage
            stage_name = stage.get("name", "").lower()
            if any(x in stage_name for x in ["nhập học", "đã nộp", "hoàn tất"]):
                return "converted"
            else:
                return random.choice(["unqualified", "rejected"])
        elif order == 2:
            return random.choice(["assigned", "contacted"])
        else:
            return "qualified"


# ============================================================
# SEEDING FUNCTIONS
# ============================================================

async def seed_leads(count: int = 200, consultation_only: bool = False):
    """Seed the database with comprehensive test data.

    Args:
        count: Number of leads to create
        consultation_only: If True, only create leads in consultation phase (non-final stages)
                          and ensure each lead has 1-5 consultations
    """
    mode = "CONSULTATION PHASE ONLY" if consultation_only else "ALL STAGES"
    print(f"\n🌱 Starting seeding of {count} leads ({mode})...")

    async with AsyncSessionLocal() as session:
        # Load configuration from database
        config = SeedConfig()
        if not await config.load(session):
            print("\n❌ Failed to load required configuration. Please ensure:")
            print("   - At least 1 active user with unit_id exists")
            print("   - Pipeline stages are configured")
            print("   - Consultation statuses are configured")
            return

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

        # Show available stages based on mode
        if consultation_only:
            available_stages = [s for s in config.pipeline_stages if not s["is_final"]]
            print(f"\n   Mode: CONSULTATION ONLY (non-final stages)")
            print(f"   Available stages: {[s['id'] for s in available_stages]}")
        else:
            print(f"\n   Mode: ALL STAGES")
            print(f"   Available stages: {[s['id'] for s in config.pipeline_stages]}")

        print(f"   Officers: {[o[0] for o in config.officers]}")
        print(f"   Time range: 90 days\n")

        for i in range(count):
            # Basic lead info
            full_name = generate_vietnamese_name()
            officer_id, unit_id = config.get_random_officer()

            # Random created_at within last 90 days
            days_ago = random.randint(1, 90)
            created_at = now - timedelta(
                days=days_ago,
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )

            # Select pipeline stage (consultation_only excludes final stages)
            stage = config.get_random_stage(consultation_only=consultation_only)
            pipeline_stage_id = stage["id"]
            status = config.get_lead_status_for_stage(stage)
            consultation_status_id = config.get_status_for_stage(pipeline_stage_id)

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
                next_activity_at = now - timedelta(hours=random.randint(1, 72))
            elif is_upcoming_lead:
                next_activity_at = now + timedelta(hours=random.randint(1, 24))
            elif status in ["assigned", "contacted", "qualified"] and random.random() > 0.5:
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
                offering_id=random.choice(config.offering_ids) if config.offering_ids and random.random() > 0.15 else None,
                unit_id=unit_id,
                assigned_officer_id=officer_id if status != "new" else None,
                pipeline_stage_id=pipeline_stage_id,
                consultation_status_id=consultation_status_id,
                # Cached fields
                is_hot_lead=lead_score >= 70,
                is_overdue=is_overdue_lead,
                consultation_count=0,
                last_consultation_at=None,
            )
            all_leads.append(lead)

            if (i + 1) % 50 == 0:
                print(f"  ✓ Generated {i + 1}/{count} leads...")

        # Bulk insert leads first to get IDs
        session.add_all(all_leads)
        await session.flush()

        print(f"\n📝 Generating consultations and history...")

        # Create consultations and history for each lead
        for idx, lead in enumerate(all_leads):
            if lead.deleted_at:
                continue

            # Get the path this lead took through stages
            stage_path = config.stage_paths.get(lead.pipeline_stage_id, [lead.pipeline_stage_id])

            # Generate consultations based on mode
            if consultation_only:
                # In consultation mode, ensure at least 1-5 consultations per lead
                num_consultations = random.randint(1, 5)
            else:
                # Normal mode: 2-5 consultations based on stage path
                num_consultations = min(len(stage_path), random.randint(2, 5))

            consultation_dates = []

            # Create timeline of consultations
            base_date = lead.created_at
            for j in range(num_consultations):
                base_date = base_date + timedelta(
                    days=random.randint(1, 14),
                    hours=random.randint(8, 18)
                )
                if base_date > datetime.now(timezone.utc):
                    # In consultation_only mode, still create at least 1 consultation
                    if consultation_only and len(consultation_dates) == 0:
                        consultation_dates.append(lead.created_at + timedelta(hours=random.randint(1, 48)))
                    break
                consultation_dates.append(base_date)

            # Ensure at least 1 consultation in consultation_only mode
            if consultation_only and len(consultation_dates) == 0:
                consultation_dates.append(lead.created_at + timedelta(hours=random.randint(1, 48)))

            # Create consultations and history entries
            prev_stage_id = None
            for j, cons_date in enumerate(consultation_dates):
                stage_idx = min(j, len(stage_path) - 1)
                current_stage = stage_path[stage_idx]
                cons_status_id = config.get_status_for_stage(current_stage)

                # Create consultation
                consultation = models.Consultation(
                    lead_id=lead.id,
                    consultation_date=cons_date,
                    scheduled_at=cons_date - timedelta(days=random.randint(1, 3)) if random.random() > 0.5 else None,
                    method=random.choice(CONSULTATION_METHODS),
                    notes=f"Tư vấn lần {j+1}" if random.random() > 0.5 else None,
                    duration_minutes=random.randint(5, 60) if random.random() > 0.3 else None,
                    officer_id=lead.assigned_officer_id or config.officers[0][0],
                    consultation_status_id=cons_status_id,
                    reminder_sent=cons_date < datetime.now(timezone.utc),
                )
                all_consultations.append(consultation)

                # Create history entry if stage changed
                if prev_stage_id and prev_stage_id != current_stage:
                    # Find stage info
                    prev_stage_info = next((s for s in config.pipeline_stages if s["id"] == prev_stage_id), None)
                    curr_stage_info = next((s for s in config.pipeline_stages if s["id"] == current_stage), None)

                    history = models.LeadStatusHistory(
                        lead_id=lead.id,
                        changed_by_user_id=lead.assigned_officer_id,
                        reason=f"Stage transition: {prev_stage_id} → {current_stage}",
                        changed_at=cons_date,
                        old_status=config.get_lead_status_for_stage(prev_stage_info) if prev_stage_info else "new",
                        new_status=config.get_lead_status_for_stage(curr_stage_info) if curr_stage_info else "new",
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
        for stage in config.pipeline_stages:
            stage_count = sum(1 for l in all_leads if l.pipeline_stage_id == stage["id"] and not l.deleted_at)
            print(f"   {stage['id']}: {stage_count} leads ({stage['name']})")

        print(f"\n👥 Officer distribution:")
        for oid, _ in config.officers:
            officer_count = sum(1 for l in all_leads if l.assigned_officer_id == oid and not l.deleted_at)
            print(f"   Officer {oid}: {officer_count} leads")


async def clear_leads():
    """Clear all lead-related data (keeps master data like users, units, etc.)."""
    print("\n🗑️ Clearing all lead-related data...")

    async with AsyncSessionLocal() as session:
        # Delete in correct order (children first, respecting FK constraints)
        tables = [
            "lead_status_history",
            "consultation",
            "crm_interaction",
            "assignment_log",
            "fee_applied_discount",
            "payment_transaction",
            "payment",
            "invoice",
            "fee",
            "admission_profile",
            "lead",
        ]

        for table in tables:
            try:
                result = await session.execute(text(f"DELETE FROM {table}"))
                print(f"   ✓ Deleted from {table}: {result.rowcount} rows")
            except Exception as e:
                print(f"   ⚠ Skipped {table}: {str(e)[:50]}")

        await session.commit()
        print("\n✅ Cleared all lead-related data!")


async def check_existing_data() -> Dict[str, int]:
    """Check existing data counts."""
    print("\n🔍 Checking existing data...")

    async with AsyncSessionLocal() as session:
        tables = [
            "lead",
            "consultation",
            "lead_status_history",
            "assignment_log",
            "admission_profile",
            "fee",
        ]

        counts = {}
        total = 0

        print("\n📊 Current data in database:")
        print("-" * 40)

        for table in tables:
            try:
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar() or 0
                counts[table] = count
                total += count
                print(f"   {table}: {count:,} records")
            except Exception as e:
                print(f"   {table}: ⚠ Error - {str(e)[:30]}")
                counts[table] = 0

        print("-" * 40)
        print(f"   TOTAL: {total:,} records")

        return counts


async def interactive_seed(count: int = 200, consultation_only: bool = False):
    """Interactive 2-step seeding process."""

    mode = "CONSULTATION PHASE ONLY" if consultation_only else "ALL STAGES"

    # Step 1: Check existing data
    counts = await check_existing_data()
    total = sum(counts.values())

    if total > 0:
        print(f"\n⚠️  Existing data will be DELETED if you continue!")
        print(f"   Total {total:,} records will be deleted.")

        confirm = input("\n👉 Delete existing data and continue? (y/N): ").strip().lower()

        if confirm != 'y':
            print("\n❌ Cancelled. No changes made.")
            return

        await clear_leads()
    else:
        print("\n✅ Database is empty, no need to delete.")

    # Step 2: Seed new data
    print("\n" + "=" * 50)
    print("🌱 STEP 2: Seed new data")
    print("=" * 50)

    print(f"\n📋 Configuration:")
    print(f"   - Lead count: {count}")
    print(f"   - Mode: {mode}")
    print(f"   - Time range: 90 days")

    if consultation_only:
        print(f"   - Each lead will have 1-5 consultations")
        print(f"   - Only non-final pipeline stages")

    confirm = input("\n👉 Start seeding? (Y/n): ").strip().lower()

    if confirm == 'n':
        print("\n❌ Cancelled.")
        return

    await seed_leads(count, consultation_only=consultation_only)

    print("\n" + "=" * 50)
    print("✅ COMPLETE!")
    print("=" * 50)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Comprehensive lead seeding for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/seed_leads.py                        # Interactive mode (recommended)
  python scripts/seed_leads.py --count 100            # Seed 100 leads (interactive)
  python scripts/seed_leads.py --consultation-only    # Only consultation phase leads
  python scripts/seed_leads.py --count 2000 --consultation-only --clear --force
  python scripts/seed_leads.py --check                # Check only, no changes
        """
    )
    parser.add_argument("--count", type=int, default=200, help="Number of leads to create (default: 200)")
    parser.add_argument("--consultation-only", action="store_true",
                        help="Only create leads in consultation phase (non-final stages) with 1-5 consultations each")
    parser.add_argument("--clear", action="store_true", help="Clear data before seeding")
    parser.add_argument("--check", action="store_true", help="Check data only, no changes")
    parser.add_argument("--force", action="store_true", help="Skip confirmation (use with --clear)")
    args = parser.parse_args()

    async def main():
        if args.check:
            await check_existing_data()
            print("\n💡 Use without --check to seed data.")
        elif args.force and args.clear:
            await clear_leads()
            await seed_leads(args.count, consultation_only=args.consultation_only)
        else:
            await interactive_seed(args.count, consultation_only=args.consultation_only)

    asyncio.run(main())
