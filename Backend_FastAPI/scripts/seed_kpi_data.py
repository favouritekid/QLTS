#!/usr/bin/env python3
"""
KPI Test Data Seeder

Creates realistic leads at various pipeline stages (including FINAL)
so the KPI enrollment tracking has real data to work with.

Distribution mimics a realistic admission funnel:
- 40% drop off before final stage (various negative outcomes)
- 35% reach "Đã nhập học" (enrolled, positive)
- 15% reach "Không đi học" (dropped, negative)
- 10% still in pipeline

Spreads leads across fiscal year months with seasonal weighting
(heavy in T6-T9 admission season).

Usage:
    docker compose exec backend python -m scripts.seed_kpi_data
    docker compose exec backend python -m scripts.seed_kpi_data --count 50
    docker compose exec backend python -m scripts.seed_kpi_data --officer 7
    docker compose exec backend python -m scripts.seed_kpi_data --year 2026
    docker compose exec backend python -m scripts.seed_kpi_data --dry-run
    docker compose exec backend python -m scripts.seed_kpi_data --sync
"""
import argparse
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text, select
from app.database import AsyncSessionLocal
from app import models

# ============================================================
# VIETNAMESE NAME GENERATION
# ============================================================

HO = [
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan",
    "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương",
]
TEN_DEM = [
    "Văn", "Thị", "Hữu", "Minh", "Thanh", "Đức", "Quốc",
    "Xuân", "Ngọc", "Anh", "Hoàng", "Phương", "",
]
TEN = [
    "An", "Bình", "Chi", "Dũng", "Phúc", "Giang", "Hà",
    "Hùng", "Khoa", "Linh", "Mai", "Nam", "Phong", "Quân",
    "Sơn", "Trang", "Uyên", "Tú", "Thảo", "Đạt", "Long",
    "Hiếu", "Vinh", "Hương", "Yến", "Vy", "Như", "Hạnh",
]

SOURCES = ["phone", "website", "walk_in", "referral", "social_media", "event"]
LOCATIONS = [
    "TP. Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Đắk Lắk", "Gia Lai",
    "Kon Tum", "Lâm Đồng", "Bình Dương", "Đồng Nai", "Khánh Hòa",
]

# Seasonal weights — admission season peaks T6-T9
MONTHLY_WEIGHTS = {
    1: 0.04, 2: 0.033, 3: 0.05, 4: 0.067, 5: 0.08, 6: 0.12,
    7: 0.15, 8: 0.15, 9: 0.12, 10: 0.08, 11: 0.06, 12: 0.05,
}

# Pipeline outcomes — what happens to each lead
# (pipeline_stage_id, consultation_status_id, label)
OUTCOMES = [
    # 35% → Enrolled (FINAL, positive)
    ("stg06", "sts11", "enrolled"),
    # 10% → Dropped out (FINAL, negative)
    ("stg07", "sts12", "dropped"),
    # 8% → Refused consult (early exit)
    ("stg02", "sts04", "refused"),
    # 7% → Withdrew application
    ("stg04", "sts08", "withdrew"),
    # 5% → Application rejected
    ("stg04", "sts16", "rejected"),
    # 5% → Tuition refunded
    ("stg05", "sts18", "refunded"),
    # 10% → Still in pipeline: Đang tư vấn
    ("stg02", "sts06", "in_progress"),
    # 8% → Still in pipeline: Đã nộp hồ sơ
    ("stg03", "sts07", "in_progress"),
    # 6% → Still in pipeline: Chờ nhập học
    ("stg04", "sts09", "in_progress"),
    # 6% → Still in pipeline: Đã nộp học phí
    ("stg05", "sts10", "in_progress"),
]
OUTCOME_WEIGHTS = [35, 10, 8, 7, 5, 5, 10, 8, 6, 6]


def gen_name():
    ho = random.choice(HO)
    dem = random.choice(TEN_DEM)
    ten = random.choice(TEN)
    return f"{ho} {dem} {ten}".replace("  ", " ")


def gen_phone():
    return f"0{random.choice(['3','5','7','8','9'])}{random.randint(10000000, 99999999)}"


def pick_month(year: int):
    """Pick a month weighted by admission season."""
    months = list(MONTHLY_WEIGHTS.keys())
    weights = list(MONTHLY_WEIGHTS.values())
    month = random.choices(months, weights=weights, k=1)[0]
    # Random day within month
    if month == 12:
        max_day = 28
    elif month == 2:
        max_day = 28
    else:
        max_day = 28
    day = random.randint(1, max_day)
    hour = random.randint(7, 18)
    minute = random.randint(0, 59)
    return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


async def seed(count: int, officer_id: int, year: int, dry_run: bool, sync: bool):
    async with AsyncSessionLocal() as db:
        # Validate officer exists
        officer = await db.get(models.User, officer_id)
        if not officer:
            print(f"[ERROR] Officer #{officer_id} not found")
            return
        unit_id = officer.unit_id
        if not unit_id:
            print(f"[ERROR] Officer #{officer_id} has no unit_id")
            return

        # Get available offerings
        r = await db.execute(text("SELECT id FROM program_offering LIMIT 20"))
        offering_ids = [row.id for row in r.fetchall()]
        if not offering_ids:
            print("[WARN] No program_offering found — leads will have offering_id=NULL")
            offering_ids = [None]

        print(f"{'[DRY RUN] ' if dry_run else ''}Seeding {count} leads for officer "
              f"#{officer_id} ({officer.full_name}) unit={unit_id} year={year}")

        # Distribution preview
        enrolled_expected = int(count * 0.35)
        print(f"  Expected enrolled: ~{enrolled_expected} (35% of {count})")
        print(f"  Expected dropped:  ~{int(count * 0.10)} (10%)")
        print(f"  Expected in-pipe:  ~{int(count * 0.30)} (30%)")
        print(f"  Expected exited:   ~{int(count * 0.25)} (25%)")

        if dry_run:
            print("\n[DRY RUN] No data written.")
            return

        created = 0
        outcome_counts = {}
        month_counts = {}

        for i in range(count):
            # Pick outcome
            outcome_stage, outcome_status, label = random.choices(
                OUTCOMES, weights=OUTCOME_WEIGHTS, k=1
            )[0]

            # Pick date (seasonal)
            dt = pick_month(year)
            month_counts[dt.month] = month_counts.get(dt.month, 0) + 1
            outcome_counts[label] = outcome_counts.get(label, 0) + 1

            name = gen_name()
            lead = models.Lead(
                full_name=name,
                phone=gen_phone(),
                email=f"seed{year}_{i}@test.example",
                source=random.choice(SOURCES),
                status="converted" if label == "enrolled" else "contacted",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                assignment_status="assigned",
                pipeline_stage_id=outcome_stage,
                consultation_status_id=outcome_status,
                lead_score=random.randint(20, 95),
                location=random.choice(LOCATIONS),
                education_level=random.choice(["high_school", "diploma", None]),
                offering_id=random.choice(offering_ids),
                created_at=dt - timedelta(days=random.randint(7, 60)),
                updated_at=dt,
                assigned_at=dt - timedelta(days=random.randint(5, 50)),
                validity_status="valid",
            )
            db.add(lead)
            created += 1

        await db.flush()
        await db.commit()

        print(f"\n  Created {created} leads")
        print(f"\n  Outcomes: {outcome_counts}")
        print(f"  Monthly: {dict(sorted(month_counts.items()))}")

        # Sync YTD
        if sync:
            print("\n  Syncing YTD...")
            from app.services import kpi_service
            async with AsyncSessionLocal() as db2:
                result = await kpi_service.sync_officer_ytd(db2, officer_id, year)
                await db2.commit()
                print(f"  Synced: {result}")

                progress = await kpi_service.get_annual_target_progress(
                    db2, officer_id, fiscal_year=year
                )
                if progress:
                    print(f"\n  === KPI Progress After Seed ===")
                    print(f"  Target: {progress['annual_target']}")
                    print(f"  Achieved YTD: {progress['achieved_ytd']}")
                    print(f"  Progress: {progress['progress_pct']}%")
                    print(f"  Status: {progress['status']}")
                else:
                    print("\n  [WARN] No KpiTarget found — create one first via /admin/kpi-config")


def main():
    parser = argparse.ArgumentParser(description="Seed KPI test data")
    parser.add_argument("--count", type=int, default=100, help="Number of leads (default: 100)")
    parser.add_argument("--officer", type=int, default=7, help="Officer ID (default: 7)")
    parser.add_argument("--year", type=int, default=2026, help="Fiscal year (default: 2026)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--sync", action="store_true", help="Sync YTD after seeding")
    args = parser.parse_args()

    asyncio.run(seed(args.count, args.officer, args.year, args.dry_run, args.sync))


if __name__ == "__main__":
    main()
