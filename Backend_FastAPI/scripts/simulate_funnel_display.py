#!/usr/bin/env python3
"""
Simulate Funnel Chart display for Admin user.
Run: python scripts/simulate_funnel_display.py
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

    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "🎯 PIPELINE FUNNEL - ADMIN VIEW" + " " * 25 + "║")
    print("║" + " " * 20 + "   (Aggregated - All Officers)" + " " * 25 + "║")
    print("╚" + "═" * 78 + "╝")

    async with AsyncSessionLocal() as db:
        # Get all stages
        stages_result = await db.execute(
            select(PipelineStage).order_by(PipelineStage.order)
        )
        stages = stages_result.scalars().all()

        # Calculate metrics per stage (with counts_for_funnel filter)
        funnel_data = []
        total_enrolled = 0
        total_lost = 0
        total_early_exit = 0
        grand_total = 0

        for stage in stages:
            # Total leads at stage (counts_for_funnel = TRUE)
            total_result = await db.execute(
                select(func.count(Lead.id))
                .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
                .where(
                    Lead.pipeline_stage_id == stage.id,
                    Lead.deleted_at.is_(None),
                    ConsultationStatus.counts_for_funnel == True,
                )
            )
            lead_count = total_result.scalar() or 0
            grand_total += lead_count

            # Early Exit count (FINAL + negative at non-final stage)
            early_exit_count = 0
            if not stage.is_final_stage:
                early_exit_result = await db.execute(
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
                early_exit_count = early_exit_result.scalar() or 0
                total_early_exit += early_exit_count

            # Outcome breakdown
            outcome_result = await db.execute(
                select(
                    func.count(case((ConsultationStatus.outcome_type == "positive", 1))).label("positive"),
                    func.count(case((ConsultationStatus.outcome_type == "negative", 1))).label("negative"),
                    func.count(case((ConsultationStatus.outcome_type == "neutral", 1))).label("neutral"),
                )
                .select_from(Lead)
                .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
                .where(
                    Lead.pipeline_stage_id == stage.id,
                    Lead.deleted_at.is_(None),
                    ConsultationStatus.counts_for_funnel == True,
                )
            )
            outcome = outcome_result.fetchone()

            # Track Won/Lost for final stages
            if stage.is_final_stage:
                if stage.id == "stg06":  # Đã nhập học
                    total_enrolled += lead_count
                else:  # stg07 - Không đi học
                    total_lost += outcome.negative if outcome else 0

            move_forward = lead_count - early_exit_count

            funnel_data.append({
                "stage_id": stage.id,
                "stage_name": stage.name,
                "lead_count": lead_count,
                "early_exit": early_exit_count,
                "move_forward": move_forward,
                "is_final": stage.is_final_stage,
                "positive": outcome.positive if outcome else 0,
                "negative": outcome.negative if outcome else 0,
                "neutral": outcome.neutral if outcome else 0,
            })

        # Calculate Net Conversion Rate
        total_lost_all = total_early_exit + total_lost
        net_conversion = (total_enrolled / (total_enrolled + total_lost_all) * 100) if (total_enrolled + total_lost_all) > 0 else 0

        # Display Header with Net Conversion
        print("\n┌" + "─" * 78 + "┐")
        print(f"│  Net Conversion: {net_conversion:.1f}%".ljust(40) + f"Total Leads: {grand_total}".rjust(38) + " │")
        print(f"│  Won: {total_enrolled} | Lost: {total_lost_all} (Early Exit: {total_early_exit} + Failed: {total_lost})".ljust(79) + "│")
        print("└" + "─" * 78 + "┘")

        # Display Core Funnel Stages
        print("\n" + "─" * 80)
        print("  CORE STAGES (Pipeline Flow)")
        print("─" * 80)

        max_count = max(s["lead_count"] for s in funnel_data if not s["is_final"]) or 1
        bar_width = 50

        for i, stage in enumerate(funnel_data):
            if stage["is_final"]:
                continue

            # Calculate bar width proportional to max
            width = int((stage["lead_count"] / max_count) * bar_width) if max_count > 0 else 0
            percent = (stage["lead_count"] / grand_total * 100) if grand_total > 0 else 0

            # Create funnel shape (narrowing)
            indent = " " * (i * 2)
            bar = "█" * width + "░" * (bar_width - width)

            print(f"\n  {stage['stage_name']:<20}")
            print(f"  {indent}┌{'─' * (bar_width - i*2)}┐")
            print(f"  {indent}│{bar[:bar_width - i*2]}│  {stage['lead_count']:>4} leads ({percent:.1f}%)")

            # Show Early Exit badge if any
            if stage["early_exit"] > 0:
                exit_percent = (stage["early_exit"] / stage["lead_count"] * 100) if stage["lead_count"] > 0 else 0
                print(f"  {indent}│{' ' * (bar_width - i*2 - 20)}  ❌ Early Exit: -{stage['early_exit']} ({exit_percent:.0f}%)")
                print(f"  {indent}│{' ' * (bar_width - i*2 - 20)}  → Move Forward: {stage['move_forward']}")

            print(f"  {indent}└{'─' * (bar_width - i*2)}┘")

            # Show conversion arrow between stages
            if i < len([s for s in funnel_data if not s["is_final"]]) - 1:
                print(f"  {indent}        ↓")

        # Display Outcome Stages
        print("\n" + "─" * 80)
        print("  OUTCOME STAGES (Final Results)")
        print("─" * 80)

        for stage in funnel_data:
            if not stage["is_final"]:
                continue

            icon = "✅" if stage["stage_id"] == "stg06" else "❌"
            status = "WON" if stage["stage_id"] == "stg06" else "LOST"

            print(f"\n  {icon} {stage['stage_name']} ({status})")
            print(f"     Leads: {stage['lead_count']}")
            if stage["lead_count"] > 0:
                print(f"     Breakdown: +{stage['positive']} positive, -{stage['negative']} negative, ○{stage['neutral']} neutral")

        # Summary
        print("\n" + "═" * 80)
        print("  📊 SUMMARY")
        print("═" * 80)
        print(f"""
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  Metric                          │  Value                              │
  ├─────────────────────────────────────────────────────────────────────────┤
  │  Total Input Leads               │  {grand_total:<36}│
  │  Won (Enrolled)                  │  {total_enrolled:<36}│
  │  Lost Total                      │  {total_lost_all:<36}│
  │    ├─ Early Exit (before final)  │  {total_early_exit:<36}│
  │    └─ Failed (at final stage)    │  {total_lost:<36}│
  │  In-Progress                     │  {grand_total - total_enrolled - total_lost_all:<36}│
  ├─────────────────────────────────────────────────────────────────────────┤
  │  Net Conversion Rate             │  {net_conversion:.1f}% (Won / (Won + Lost))           │
  │  Formula                         │  {total_enrolled} / ({total_enrolled} + {total_lost_all}) = {net_conversion:.1f}%             │
  └─────────────────────────────────────────────────────────────────────────┘
""")

        # Key Insights
        print("  💡 KEY INSIGHTS")
        print("  " + "─" * 76)

        # Find biggest early exit stage
        max_early_exit = max((s for s in funnel_data if not s["is_final"]), key=lambda x: x["early_exit"], default=None)
        if max_early_exit and max_early_exit["early_exit"] > 0:
            print(f"  ⚠️  Biggest Early Exit: {max_early_exit['stage_name']} with {max_early_exit['early_exit']} leads")
            print(f"      → {max_early_exit['early_exit']} leads became FINAL (Lost) before reaching outcome stages")

        if net_conversion == 0:
            print(f"  ⚠️  Net Conversion = 0%: No leads have enrolled yet (stg06 = 0)")
            print(f"      → {total_early_exit} leads exited early, need to investigate why")

        print("\n")


if __name__ == "__main__":
    asyncio.run(main())
