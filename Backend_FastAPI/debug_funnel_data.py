"""
Debug Script: Verify Funnel Data for Officer Dashboard

This script queries the database to verify the funnel calculation logic.
Run this script with the officer's user ID as argument.

Usage:
    python debug_funnel_data.py <officer_id>
"""
import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path

# Load .env file manually
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from sqlalchemy import select, func, Column, String, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env")
    sys.exit(1)

print(f"Using DATABASE_URL: {DATABASE_URL[:50]}...")

# Define minimal models needed for the query (matching actual DB table names)
Base = declarative_base()

class PipelineStage(Base):
    __tablename__ = "pipeline_stage"  # Fixed: singular
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    order = Column(Integer, nullable=False)
    is_final_stage = Column(Boolean, default=False)

class Lead(Base):
    __tablename__ = "lead"  # Fixed: singular
    id = Column(Integer, primary_key=True)
    full_name = Column(String)
    assigned_officer_id = Column(Integer)
    pipeline_stage_id = Column(String, ForeignKey("pipeline_stage.id"))
    consultation_status_id = Column(String)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete field

class ConsultationStatus(Base):
    __tablename__ = "consultation_status"  # Fixed: singular
    id = Column(String, primary_key=True)
    name = Column(String)
    is_final_status = Column(Boolean)
    outcome_type = Column(String)

class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"))
    old_pipeline_stage_id = Column(String)
    new_pipeline_stage_id = Column(String)
    changed_at = Column(DateTime(timezone=True))


async def debug_funnel_data(officer_id: int):
    """Debug funnel data for a specific officer."""
    
    # Create async engine
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        print(f"\n{'='*60}")
        print(f"FUNNEL DATA DEBUG FOR OFFICER ID: {officer_id}")
        print(f"{'='*60}")
        
        # 1. Get all leads assigned to this officer (INCLUDING deleted)
        total_all_query = (
            select(func.count(Lead.id))
            .where(Lead.assigned_officer_id == officer_id)
        )
        total_all = (await db.execute(total_all_query)).scalar() or 0
        
        # 2. Get active leads (EXCLUDING deleted)
        total_active_query = (
            select(func.count(Lead.id))
            .where(
                Lead.assigned_officer_id == officer_id,
                Lead.deleted_at.is_(None)  # Exclude soft-deleted
            )
        )
        total_active = (await db.execute(total_active_query)).scalar() or 0
        
        # 3. Count deleted leads
        deleted_count = total_all - total_active
        
        print(f"\n✅ TỔNG SỐ LEADS ASSIGNED CHO OFFICER: {total_all}")
        print(f"   - Active (chưa xóa): {total_active}")
        print(f"   - Deleted (đã xóa): {deleted_count}")
        
        # Use total_active for funnel calculations
        total_leads = total_active
        
        # 4. Get leads grouped by pipeline_stage (excluding deleted)
        leads_by_stage_query = (
            select(
                PipelineStage.id,
                PipelineStage.name,
                PipelineStage.order,
                PipelineStage.is_final_stage,
                func.count(Lead.id).label("lead_count")
            )
            .join(Lead, Lead.pipeline_stage_id == PipelineStage.id, isouter=True)
            .where(
                Lead.assigned_officer_id == officer_id,
                Lead.deleted_at.is_(None)  # Exclude soft-deleted
            )
            .group_by(
                PipelineStage.id,
                PipelineStage.name,
                PipelineStage.order,
                PipelineStage.is_final_stage
            )
            .order_by(PipelineStage.order)
        )
        result = await db.execute(leads_by_stage_query)
        leads_by_stage = result.fetchall()
        
        print(f"\n📊 PHÂN BỐ LEADS THEO STAGE (ACTIVE ONLY - ĐÃ LOẠI TRỪ DELETED):")
        print("-" * 60)
        for row in leads_by_stage:
            stage_id, stage_name, order, is_final, count = row
            final_marker = " [FINAL]" if is_final else ""
            percent = (count / total_leads * 100) if total_leads > 0 else 0
            print(f"  {order}. {stage_name} ({stage_id}): {count} leads ({percent:.1f}%){final_marker}")
        
        # 5. Get ALL pipeline stages (including empty ones)
        all_stages_query = (
            select(PipelineStage)
            .order_by(PipelineStage.order.asc())
        )
        all_stages = (await db.execute(all_stages_query)).scalars().all()
        
        print(f"\n📊 TẤT CẢ PIPELINE STAGES:")
        print("-" * 60)
        for stage in all_stages:
            print(f"  {stage.order}. [{stage.id}] {stage.name} (is_final={stage.is_final_stage})")
        
        # 6. Count per stage (excluding deleted)
        print(f"\n📊 FUNNEL - SỐ LEADS ACTIVE TẠI MỖI STAGE:")
        print("-" * 60)
        
        stage_counts = []
        for stage in all_stages:
            stage_count_query = (
                select(func.count(Lead.id))
                .where(
                    Lead.assigned_officer_id == officer_id,
                    Lead.pipeline_stage_id == stage.id,
                    Lead.deleted_at.is_(None)  # Exclude soft-deleted
                )
            )
            count = (await db.execute(stage_count_query)).scalar() or 0
            stage_counts.append(count)
            percent = (count / total_leads * 100) if total_leads > 0 else 0
            final_marker = " [FINAL]" if stage.is_final_stage else ""
            print(f"  {stage.name}: {count} ({percent:.1f}%){final_marker}")
        
        # 7. Check for leads without pipeline_stage (excluding deleted)
        leads_no_stage_query = (
            select(func.count(Lead.id))
            .where(
                Lead.assigned_officer_id == officer_id,
                Lead.pipeline_stage_id.is_(None),
                Lead.deleted_at.is_(None)  # Exclude soft-deleted
            )
        )
        leads_no_stage = (await db.execute(leads_no_stage_query)).scalar() or 0
        print(f"\n⚠️  LEADS ACTIVE KHÔNG CÓ PIPELINE STAGE: {leads_no_stage}")
        
        # 8. Sum check
        sum_leads = sum(stage_counts)
        print(f"\n📊 KIỂM TRA TỔNG (ACTIVE LEADS ONLY):")
        print(f"  Tổng leads active: {total_leads}")
        print(f"  Tổng leads trong các stages: {sum_leads}")
        print(f"  + Leads không có stage: {leads_no_stage}")
        print(f"  = Tổng: {sum_leads + leads_no_stage}")
        if sum_leads + leads_no_stage != total_leads:
            print(f"  ⚠️ KHÔNG KHỚP! Chênh lệch: {total_leads - sum_leads - leads_no_stage}")
        else:
            print(f"  ✅ KHỚP!")
        
        # 9. Historical Conversion Rates (from lead_status_history)
        from datetime import timedelta, timezone as tz
        thirty_days_ago = datetime.now(tz.utc) - timedelta(days=30)
        
        print(f"\n📊 HISTORICAL CONVERSION (30 ngày qua):")
        print("-" * 60)
        
        transition_query = (
            select(
                LeadStatusHistory.old_pipeline_stage_id,
                LeadStatusHistory.new_pipeline_stage_id,
                func.count().label("count")
            )
            .join(Lead, LeadStatusHistory.lead_id == Lead.id)
            .where(
                Lead.assigned_officer_id == officer_id,
                LeadStatusHistory.changed_at >= thirty_days_ago,
                LeadStatusHistory.old_pipeline_stage_id.isnot(None),
                LeadStatusHistory.new_pipeline_stage_id.isnot(None),
                LeadStatusHistory.old_pipeline_stage_id != LeadStatusHistory.new_pipeline_stage_id
            )
            .group_by(
                LeadStatusHistory.old_pipeline_stage_id,
                LeadStatusHistory.new_pipeline_stage_id
            )
            .order_by(LeadStatusHistory.old_pipeline_stage_id)
        )
        transitions = (await db.execute(transition_query)).fetchall()
        
        if transitions:
            # Build stage order map
            stage_order = {s.id: s.order for s in all_stages}
            
            # Group by from_stage
            from_stage_data = {}
            for old_stage, new_stage, count in transitions:
                if old_stage not in from_stage_data:
                    from_stage_data[old_stage] = {"total": 0, "progressive": 0}
                from_stage_data[old_stage]["total"] += count
                if stage_order.get(new_stage, 0) > stage_order.get(old_stage, 0):
                    from_stage_data[old_stage]["progressive"] += count
            
            for stage in all_stages:
                if stage.id in from_stage_data:
                    data = from_stage_data[stage.id]
                    conv_rate = (data["progressive"] / data["total"] * 100) if data["total"] > 0 else 0
                    print(f"  {stage.name}: {data['progressive']}/{data['total']} tiến lên stage cao hơn = {conv_rate:.1f}%")
        else:
            print("  (Chưa có dữ liệu chuyển đổi trong 30 ngày qua)")
        
        # 10. Summary
        print(f"\n{'='*60}")
        print("📋 TÓM TẮT:")
        print("-" * 60)
        print(f"  Total leads (bao gồm deleted): {total_all}")
        print(f"  Active leads (hiển thị trên funnel): {total_leads}")
        print(f"  Deleted leads (đã loại trừ): {deleted_count}")
        print(f"{'='*60}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_funnel_data.py <officer_id>")
        print("Example: python debug_funnel_data.py 5")
        sys.exit(1)
    
    officer_id = int(sys.argv[1])
    asyncio.run(debug_funnel_data(officer_id))
