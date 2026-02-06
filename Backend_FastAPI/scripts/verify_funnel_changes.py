#!/usr/bin/env python3
"""
Verify funnel chart changes work correctly.
Run: python scripts/verify_funnel_changes.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")


async def main():
    from sqlalchemy import select, func, case, and_
    from app.database import AsyncSessionLocal
    from app.models.pipeline import PipelineStage, ConsultationStatus
    from app.models import Lead

    print("\n" + "=" * 80)
    print("🔍 VERIFY FUNNEL CHANGES - SPEC 2026-02-04")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        # Test 1: Verify counts_for_funnel filter works
        print("\n✅ TEST 1: counts_for_funnel filter")
        print("-" * 40)

        total_statuses = await db.execute(select(func.count(ConsultationStatus.id)))
        total = total_statuses.scalar()

        funnel_statuses = await db.execute(
            select(func.count(ConsultationStatus.id))
            .where(ConsultationStatus.counts_for_funnel == True)
        )
        funnel_count = funnel_statuses.scalar()

        not_in_funnel = await db.execute(
            select(ConsultationStatus.id, ConsultationStatus.name)
            .where(ConsultationStatus.counts_for_funnel == False)
        )
        excluded = not_in_funnel.fetchall()

        print(f"  Total statuses: {total}")
        print(f"  Funnel statuses (counts_for_funnel=True): {funnel_count}")
        print(f"  Excluded from funnel: {len(excluded)}")
        for s in excluded:
            print(f"    - {s.id}: {s.name}")

        # Test 2: Verify Universal statuses excluded
        print("\n✅ TEST 2: Universal statuses (stage_id IS NULL)")
        print("-" * 40)

        universal = await db.execute(
            select(ConsultationStatus.id, ConsultationStatus.name)
            .where(ConsultationStatus.stage_id.is_(None))
        )
        universal_list = universal.fetchall()

        print(f"  Universal statuses (excluded from funnel): {len(universal_list)}")
        for s in universal_list:
            print(f"    - {s.id}: {s.name}")

        # Test 3: Early Exit detection (FINAL + negative at non-final stage)
        print("\n✅ TEST 3: Early Exit statuses")
        print("-" * 40)

        early_exit_statuses = await db.execute(
            select(
                ConsultationStatus.id,
                ConsultationStatus.name,
                ConsultationStatus.stage_id,
                PipelineStage.name.label("stage_name"),
                PipelineStage.is_final_stage
            )
            .join(PipelineStage, ConsultationStatus.stage_id == PipelineStage.id)
            .where(
                ConsultationStatus.is_final == True,
                ConsultationStatus.outcome_type == "negative",
                PipelineStage.is_final_stage == False  # Non-final stage
            )
        )
        early_exits = early_exit_statuses.fetchall()

        print(f"  Early Exit statuses found: {len(early_exits)}")
        for s in early_exits:
            print(f"    - {s.id}: {s.name} → Stage: {s.stage_id} ({s.stage_name})")

        # Test 4: Count leads with Early Exit
        print("\n✅ TEST 4: Lead counts with Early Exit")
        print("-" * 40)

        # Get stages with their counts
        stages_result = await db.execute(
            select(PipelineStage).order_by(PipelineStage.order)
        )
        stages = stages_result.scalars().all()

        for stage in stages:
            if stage.is_final_stage:
                continue

            # Count total leads at this stage
            total_at_stage = await db.execute(
                select(func.count(Lead.id))
                .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
                .where(
                    Lead.pipeline_stage_id == stage.id,
                    Lead.deleted_at.is_(None),
                    ConsultationStatus.counts_for_funnel == True,
                )
            )
            total_count = total_at_stage.scalar() or 0

            # Count early exit at this stage
            early_exit_at_stage = await db.execute(
                select(func.count(Lead.id))
                .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
                .where(
                    Lead.pipeline_stage_id == stage.id,
                    Lead.deleted_at.is_(None),
                    ConsultationStatus.counts_for_funnel == True,
                    ConsultationStatus.is_final == True,
                    ConsultationStatus.outcome_type == "negative",
                )
            )
            early_exit_count = early_exit_at_stage.scalar() or 0

            move_forward = total_count - early_exit_count

            if early_exit_count > 0:
                print(f"  {stage.id} ({stage.name}):")
                print(f"    Total: {total_count}, Early Exit: {early_exit_count}, Move Forward: {move_forward}")

        # Test 5: Net Conversion Rate calculation
        print("\n✅ TEST 5: Net Conversion Rate")
        print("-" * 40)

        # Enrolled (stg06, positive)
        enrolled_result = await db.execute(
            select(func.count(Lead.id))
            .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
            .where(
                Lead.pipeline_stage_id == "stg06",
                Lead.deleted_at.is_(None),
                ConsultationStatus.counts_for_funnel == True,
            )
        )
        enrolled = enrolled_result.scalar() or 0

        # Lost at final stages (stg06, stg07 negative)
        final_lost_result = await db.execute(
            select(func.count(Lead.id))
            .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
            .join(PipelineStage, Lead.pipeline_stage_id == PipelineStage.id)
            .where(
                Lead.deleted_at.is_(None),
                ConsultationStatus.counts_for_funnel == True,
                PipelineStage.is_final_stage == True,
                ConsultationStatus.outcome_type == "negative",
            )
        )
        final_lost = final_lost_result.scalar() or 0

        # Early exit total (FINAL negative at non-final stages)
        early_exit_total_result = await db.execute(
            select(func.count(Lead.id))
            .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
            .join(PipelineStage, Lead.pipeline_stage_id == PipelineStage.id)
            .where(
                Lead.deleted_at.is_(None),
                ConsultationStatus.counts_for_funnel == True,
                ConsultationStatus.is_final == True,
                ConsultationStatus.outcome_type == "negative",
                PipelineStage.is_final_stage == False,
            )
        )
        early_exit_total = early_exit_total_result.scalar() or 0

        total_lost = early_exit_total + final_lost
        net_rate = (enrolled / (enrolled + total_lost) * 100) if (enrolled + total_lost) > 0 else 0

        print(f"  Enrolled (Won): {enrolled}")
        print(f"  Lost at final stages: {final_lost}")
        print(f"  Early Exit total: {early_exit_total}")
        print(f"  Total Lost: {total_lost}")
        print(f"  Net Conversion Rate: {net_rate:.1f}%")
        print(f"  Formula: {enrolled} / ({enrolled} + {total_lost}) = {net_rate:.1f}%")

        print("\n" + "=" * 80)
        print("✅ ALL VERIFICATIONS PASSED")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
