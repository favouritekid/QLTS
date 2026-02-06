#!/usr/bin/env python3
"""
Debug why funnel shows 0 leads.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")


async def main():
    from sqlalchemy import select, func, case, and_
    from sqlalchemy.orm import selectinload
    from app.database import AsyncSessionLocal
    from app.models.pipeline import PipelineStage, ConsultationStatus
    from app.models import Lead

    print("\n" + "=" * 80)
    print("🔍 DEBUG: Why Funnel Shows 0 Leads")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        # 1. Total leads in database
        total_leads = await db.execute(select(func.count(Lead.id)).where(Lead.deleted_at.is_(None)))
        total = total_leads.scalar()
        print(f"\n1️⃣ Total leads (not deleted): {total}")

        # 2. Leads with consultation_status_id set
        leads_with_status = await db.execute(
            select(func.count(Lead.id))
            .where(
                Lead.deleted_at.is_(None),
                Lead.consultation_status_id.isnot(None)
            )
        )
        with_status = leads_with_status.scalar()
        print(f"2️⃣ Leads with consultation_status_id: {with_status}")

        # 3. Leads with pipeline_stage_id set
        leads_with_stage = await db.execute(
            select(func.count(Lead.id))
            .where(
                Lead.deleted_at.is_(None),
                Lead.pipeline_stage_id.isnot(None)
            )
        )
        with_stage = leads_with_stage.scalar()
        print(f"3️⃣ Leads with pipeline_stage_id: {with_stage}")

        # 4. Check counts_for_funnel distribution
        print(f"\n4️⃣ ConsultationStatus.counts_for_funnel distribution:")
        status_dist = await db.execute(
            select(
                ConsultationStatus.counts_for_funnel,
                func.count(ConsultationStatus.id)
            )
            .group_by(ConsultationStatus.counts_for_funnel)
        )
        for row in status_dist.fetchall():
            print(f"   counts_for_funnel={row[0]}: {row[1]} statuses")

        # 5. Leads by counts_for_funnel of their status
        print(f"\n5️⃣ Leads grouped by their status.counts_for_funnel:")
        leads_by_funnel_flag = await db.execute(
            select(
                ConsultationStatus.counts_for_funnel,
                func.count(Lead.id)
            )
            .select_from(Lead)
            .outerjoin(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
            .where(Lead.deleted_at.is_(None))
            .group_by(ConsultationStatus.counts_for_funnel)
        )
        for row in leads_by_funnel_flag.fetchall():
            flag = row[0] if row[0] is not None else "NULL (no status)"
            print(f"   counts_for_funnel={flag}: {row[1]} leads")

        # 6. Leads with BOTH pipeline_stage_id AND consultation_status_id
        both_set = await db.execute(
            select(func.count(Lead.id))
            .where(
                Lead.deleted_at.is_(None),
                Lead.pipeline_stage_id.isnot(None),
                Lead.consultation_status_id.isnot(None)
            )
        )
        both = both_set.scalar()
        print(f"\n6️⃣ Leads with BOTH stage AND status set: {both}")

        # 7. Leads with counts_for_funnel=True status AND pipeline_stage set
        funnel_ready = await db.execute(
            select(func.count(Lead.id))
            .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
            .where(
                Lead.deleted_at.is_(None),
                Lead.pipeline_stage_id.isnot(None),
                ConsultationStatus.counts_for_funnel == True,
            )
        )
        ready = funnel_ready.scalar()
        print(f"7️⃣ Leads ready for funnel (stage + status + counts_for_funnel=True): {ready}")

        # 8. Check what statuses leads actually have
        print(f"\n8️⃣ Top 10 statuses used by leads:")
        status_usage = await db.execute(
            select(
                ConsultationStatus.id,
                ConsultationStatus.name,
                ConsultationStatus.counts_for_funnel,
                ConsultationStatus.stage_id,
                func.count(Lead.id).label("lead_count")
            )
            .select_from(Lead)
            .outerjoin(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
            .where(Lead.deleted_at.is_(None))
            .group_by(ConsultationStatus.id, ConsultationStatus.name, ConsultationStatus.counts_for_funnel, ConsultationStatus.stage_id)
            .order_by(func.count(Lead.id).desc())
            .limit(10)
        )
        print(f"   {'Status ID':<12} {'Name':<25} {'Funnel':<8} {'Stage':<8} {'Leads':<8}")
        print("   " + "-" * 65)
        for row in status_usage.fetchall():
            sid = row.id or "NULL"
            name = (row.name or "No Status")[:24]
            funnel = str(row.counts_for_funnel) if row.counts_for_funnel is not None else "N/A"
            stage = row.stage_id or "NULL"
            print(f"   {sid:<12} {name:<25} {funnel:<8} {stage:<8} {row.lead_count:<8}")

        # 9. Check if stages match between Lead.pipeline_stage_id and ConsultationStatus.stage_id
        print(f"\n9️⃣ Stage mismatch check (Lead.pipeline_stage_id vs Status.stage_id):")
        mismatch = await db.execute(
            select(func.count(Lead.id))
            .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
            .where(
                Lead.deleted_at.is_(None),
                Lead.pipeline_stage_id != ConsultationStatus.stage_id
            )
        )
        mismatch_count = mismatch.scalar()
        print(f"   Leads with mismatched stages: {mismatch_count}")

        # 10. Sample leads to understand the issue
        print(f"\n🔟 Sample 5 leads (to understand data structure):")
        samples = await db.execute(
            select(Lead)
            .options(
                selectinload(Lead.pipeline_stage),
                selectinload(Lead.consultation_status)
            )
            .where(Lead.deleted_at.is_(None))
            .limit(5)
        )
        for lead in samples.scalars().all():
            stage_id = lead.pipeline_stage_id or "NULL"
            stage_name = lead.pipeline_stage.name if lead.pipeline_stage else "N/A"
            status_id = lead.consultation_status_id or "NULL"
            status_name = lead.consultation_status.name if lead.consultation_status else "N/A"
            funnel_flag = lead.consultation_status.counts_for_funnel if lead.consultation_status else "N/A"
            print(f"   Lead {lead.id}: stage={stage_id} ({stage_name}), status={status_id} ({status_name}), funnel={funnel_flag}")

        print("\n" + "=" * 80)
        print("💡 DIAGNOSIS")
        print("=" * 80)

        if with_status == 0:
            print("❌ ISSUE: No leads have consultation_status_id set!")
            print("   → The INNER JOIN to ConsultationStatus returns 0 rows")
            print("   → FIX: Change JOIN back to OUTERJOIN, or ensure leads have status")
        elif ready == 0:
            print("❌ ISSUE: No leads have counts_for_funnel=True status!")
            print("   → The filter ConsultationStatus.counts_for_funnel=True excludes all leads")
            print("   → FIX: Check if statuses have correct counts_for_funnel flag")
        elif ready < total * 0.5:
            print(f"⚠️ WARNING: Only {ready}/{total} leads ({ready/total*100:.1f}%) are funnel-ready")
            print("   → Many leads are excluded by the counts_for_funnel filter")
        else:
            print(f"✅ Data looks OK: {ready} leads should appear in funnel")
            print("   → Issue might be in the API response or frontend")

        print("\n")


if __name__ == "__main__":
    asyncio.run(main())
