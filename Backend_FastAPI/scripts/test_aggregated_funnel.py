#!/usr/bin/env python3
"""
Test aggregated funnel with counts_for_funnel filter.
Run: python scripts/test_aggregated_funnel.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")


async def main():
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.repositories.officer_repository import OfficerRepository
    from app.models import User

    print("\n" + "=" * 80)
    print("🧪 TEST: Aggregated Funnel with counts_for_funnel filter")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        repo = OfficerRepository(db)

        # Get all active officer IDs (organization scope)
        officer_ids = await repo.get_active_officer_ids(scope="organization")
        print(f"\n📋 Officers found: {len(officer_ids)}")

        if not officer_ids:
            print("❌ No officers found. Cannot test.")
            return

        # Test aggregated funnel
        print("\n🔍 Testing get_aggregated_funnel()...")
        funnel = await repo.get_aggregated_funnel(officer_ids)

        # Display results
        print(f"\n{'Stage':<25} {'Leads':>8} {'EarlyExit':>10} {'MoveForward':>12} {'Positive':>10} {'Negative':>10}")
        print("-" * 85)

        total_leads = 0
        total_early_exit = 0
        total_enrolled = 0
        total_lost = 0

        for stage in funnel:
            stage_name = stage["stage_name"][:24]
            lead_count = stage["lead_count"]
            early_exit = stage["early_exit_count"]
            move_forward = stage["move_forward"]
            positive = stage["outcome_breakdown"]["positive"]
            negative = stage["outcome_breakdown"]["negative"]

            print(f"{stage_name:<25} {lead_count:>8} {early_exit:>10} {move_forward:>12} {positive:>10} {negative:>10}")

            total_leads += lead_count

            if stage["is_final_stage"]:
                total_enrolled += positive
                total_lost += negative
            else:
                total_early_exit += early_exit

        print("-" * 85)
        print(f"{'TOTAL':<25} {total_leads:>8}")

        # Calculate Net Conversion
        total_lost_all = total_early_exit + total_lost
        net_conversion = (total_enrolled / (total_enrolled + total_lost_all) * 100) if (total_enrolled + total_lost_all) > 0 else 0

        print(f"\n📊 METRICS:")
        print(f"  Total Leads in Funnel: {total_leads}")
        print(f"  Enrolled (Won): {total_enrolled}")
        print(f"  Early Exit: {total_early_exit}")
        print(f"  Lost at Final: {total_lost}")
        print(f"  Total Lost: {total_lost_all}")
        print(f"  Net Conversion Rate: {net_conversion:.1f}%")

        if total_leads > 0:
            print("\n✅ TEST PASSED: Funnel data is being retrieved correctly!")
        else:
            print("\n⚠️ WARNING: No leads in funnel - check counts_for_funnel filter")

        print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
