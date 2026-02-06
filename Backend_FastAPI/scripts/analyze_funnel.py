#!/usr/bin/env python3
"""
Script to analyze PipelineStage and ConsultationStatus data for funnel chart.
Run: python scripts/analyze_funnel.py
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set env before imports
os.environ.setdefault("APP_ENV", "development")


async def main():
    # Import after setting env
    from sqlalchemy import select, func
    from sqlalchemy.orm import selectinload
    from app.database import AsyncSessionLocal
    from app.models.pipeline import PipelineStage, ConsultationStatus
    from app.models import Lead

    async with AsyncSessionLocal() as db:
        # 1. Pipeline Stages
        print("\n" + "=" * 100)
        print("BẢNG 1: PIPELINE STAGES")
        print("=" * 100)

        stages_result = await db.execute(
            select(PipelineStage).order_by(PipelineStage.order)
        )
        stages = stages_result.scalars().all()

        print(f"\n{'ID':<10} {'Name':<30} {'Order':<6} {'Is Final':<10} {'Color':<10}")
        print("-" * 70)
        for stage in stages:
            print(f"{stage.id:<10} {stage.name:<30} {stage.order:<6} {str(stage.is_final_stage):<10} {stage.color_code:<10}")

        # 2. Consultation Status
        print("\n" + "=" * 100)
        print("BẢNG 2: CONSULTATION STATUS")
        print("=" * 100)

        statuses_result = await db.execute(
            select(ConsultationStatus)
            .options(selectinload(ConsultationStatus.stage))
            .order_by(ConsultationStatus.stage_id, ConsultationStatus.display_order)
        )
        statuses = statuses_result.scalars().all()

        print(f"\n{'ID':<15} {'Name':<25} {'Stage':<10} {'Phase':<12} {'Outcome':<10} {'Final':<6} {'Funnel':<7} {'Universal':<9}")
        print("-" * 110)
        for s in statuses:
            stage_id = s.stage_id or "NULL"
            outcome = s.outcome_type.value if s.outcome_type else "-"
            print(f"{s.id:<15} {s.name:<25} {stage_id:<10} {s.phase:<12} {outcome:<10} {str(s.is_final):<6} {str(s.counts_for_funnel):<7} {str(s.is_universal):<9}")

        # 3. Group by stage
        print("\n" + "=" * 100)
        print("BẢNG 3: PHÂN BỐ STATUS THEO STAGE")
        print("=" * 100)

        stage_status_map = {}
        for s in statuses:
            stage_key = s.stage_id or "UNIVERSAL"
            if stage_key not in stage_status_map:
                stage_status_map[stage_key] = {"statuses": [], "stage_name": None, "order": 999}
            stage_status_map[stage_key]["statuses"].append(s)
            if s.stage:
                stage_status_map[stage_key]["stage_name"] = s.stage.name
                stage_status_map[stage_key]["order"] = s.stage.order

        sorted_stages = sorted(stage_status_map.items(), key=lambda x: x[1]["order"])

        for stage_id, data in sorted_stages:
            stage_name = data["stage_name"] or "Universal"
            print(f"\n📌 {stage_id} - {stage_name}")
            print("-" * 80)

            by_outcome = {"positive": [], "neutral": [], "negative": []}
            for s in data["statuses"]:
                outcome = s.outcome_type.value if s.outcome_type else "neutral"
                by_outcome[outcome].append(s)

            for outcome_type in ["positive", "neutral", "negative"]:
                if by_outcome[outcome_type]:
                    icon = "✅" if outcome_type == "positive" else ("⚠️" if outcome_type == "neutral" else "❌")
                    print(f"  {icon} {outcome_type.upper()}:")
                    for s in by_outcome[outcome_type]:
                        final_marker = " [FINAL]" if s.is_final else ""
                        funnel_marker = "" if s.counts_for_funnel else " [NOT IN FUNNEL]"
                        print(f"      - {s.id}: {s.name}{final_marker}{funnel_marker}")

        # 4. Summary
        print("\n" + "=" * 100)
        print("BẢNG 4: THỐNG KÊ TỔNG HỢP")
        print("=" * 100)

        final_statuses = [s for s in statuses if s.is_final]
        funnel_statuses = [s for s in statuses if s.counts_for_funnel]
        universal_statuses = [s for s in statuses if s.is_universal]
        positive_outcomes = [s for s in statuses if s.outcome_type and s.outcome_type.value == "positive"]
        negative_outcomes = [s for s in statuses if s.outcome_type and s.outcome_type.value == "negative"]
        neutral_outcomes = [s for s in statuses if s.outcome_type and s.outcome_type.value == "neutral"]

        print(f"\n{'Metric':<40} {'Count':<10}")
        print("-" * 50)
        print(f"{'Tổng số status':<40} {len(statuses):<10}")
        print(f"{'Status FINAL':<40} {len(final_statuses):<10}")
        print(f"{'Status đếm trong Funnel':<40} {len(funnel_statuses):<10}")
        print(f"{'Status Universal':<40} {len(universal_statuses):<10}")
        print(f"{'Outcome POSITIVE':<40} {len(positive_outcomes):<10}")
        print(f"{'Outcome NEUTRAL':<40} {len(neutral_outcomes):<10}")
        print(f"{'Outcome NEGATIVE':<40} {len(negative_outcomes):<10}")

        # 5. Funnel analysis
        print("\n" + "=" * 100)
        print("BẢNG 5: PHÂN TÍCH FUNNEL CHART")
        print("=" * 100)

        print("\n🔍 STATUS FINAL:")
        print("-" * 60)
        for s in final_statuses:
            stage_name = s.stage.name if s.stage else "Universal"
            outcome = s.outcome_type.value if s.outcome_type else "?"
            print(f"  {s.id}: {s.name} → Stage: {s.stage_id or 'NULL'} ({stage_name}), Outcome: {outcome}")

        final_stage_ids = [stage.id for stage in stages if stage.is_final_stage]
        early_exit = [s for s in final_statuses if s.stage_id not in final_stage_ids]

        print("\n⚠️ EARLY EXIT (FINAL nhưng KHÔNG ở stage cuối):")
        print("-" * 60)
        if early_exit:
            for s in early_exit:
                stage_name = s.stage.name if s.stage else "Universal"
                outcome = s.outcome_type.value if s.outcome_type else "?"
                print(f"  {s.id}: {s.name} → Stage: {s.stage_id or 'NULL'} ({stage_name}), Outcome: {outcome}")
        else:
            print("  (Không có)")

        not_in_funnel = [s for s in statuses if not s.counts_for_funnel]
        print("\n📊 STATUS KHÔNG ĐẾM TRONG FUNNEL:")
        print("-" * 60)
        if not_in_funnel:
            for s in not_in_funnel:
                print(f"  {s.id}: {s.name} → Phase: {s.phase}")
        else:
            print("  (Không có)")

        # 6. Lead count by stage
        print("\n" + "=" * 100)
        print("BẢNG 6: LEAD COUNT THEO STAGE")
        print("=" * 100)

        lead_count_result = await db.execute(
            select(
                PipelineStage.id,
                PipelineStage.name,
                PipelineStage.order,
                func.count(Lead.id).label("lead_count")
            )
            .outerjoin(Lead, Lead.pipeline_stage_id == PipelineStage.id)
            .group_by(PipelineStage.id)
            .order_by(PipelineStage.order)
        )
        lead_counts = lead_count_result.all()

        print(f"\n{'Stage ID':<10} {'Stage Name':<30} {'Lead Count':<12}")
        print("-" * 55)
        total_leads = 0
        for row in lead_counts:
            print(f"{row.id:<10} {row.name:<30} {row.lead_count:<12}")
            total_leads += row.lead_count
        print("-" * 55)
        print(f"{'TOTAL':<10} {'':<30} {total_leads:<12}")

        # 7. Lead count by status
        print("\n" + "=" * 100)
        print("BẢNG 7: LEAD COUNT THEO STATUS (Top 20)")
        print("=" * 100)

        status_count_result = await db.execute(
            select(
                ConsultationStatus.id,
                ConsultationStatus.name,
                ConsultationStatus.stage_id,
                ConsultationStatus.outcome_type,
                ConsultationStatus.is_final,
                func.count(Lead.id).label("lead_count")
            )
            .outerjoin(Lead, Lead.consultation_status_id == ConsultationStatus.id)
            .group_by(ConsultationStatus.id)
            .order_by(func.count(Lead.id).desc())
            .limit(20)
        )
        status_counts = status_count_result.all()

        print(f"\n{'Status ID':<15} {'Name':<25} {'Stage':<8} {'Outcome':<10} {'Final':<6} {'Count':<8}")
        print("-" * 80)
        for row in status_counts:
            outcome = row.outcome_type.value if row.outcome_type else "-"
            stage = row.stage_id or "NULL"
            print(f"{row.id:<15} {row.name:<25} {stage:<8} {outcome:<10} {str(row.is_final):<6} {row.lead_count:<8}")

        print("\n✅ HOÀN TẤT\n")


if __name__ == "__main__":
    asyncio.run(main())
