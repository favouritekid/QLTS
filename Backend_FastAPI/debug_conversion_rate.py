"""Debug script to check conversion rate transitions for an officer."""
import asyncio
import sys
import os

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models import LeadStatusHistory, PipelineStage


async def check_transitions(officer_id: int = 8):
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    async with async_session() as db:
        # Get all pipeline stages for reference
        stages_result = await db.execute(
            select(PipelineStage).order_by(PipelineStage.order)
        )
        stages = {s.id: (s.name, s.order) for s in stages_result.scalars().all()}
        
        print(f"\n=== Pipeline Stages ===")
        for stage_id, (name, order) in sorted(stages.items(), key=lambda x: x[1][1]):
            print(f"  {stage_id}: {name} (order={order})")
        
        # Query transitions
        query = (
            select(
                LeadStatusHistory.old_pipeline_stage_id,
                LeadStatusHistory.new_pipeline_stage_id,
                func.count().label('count')
            )
            .where(
                LeadStatusHistory.changed_by_user_id == officer_id,
                LeadStatusHistory.changed_at >= thirty_days_ago,
                LeadStatusHistory.old_pipeline_stage_id.isnot(None),
                LeadStatusHistory.new_pipeline_stage_id.isnot(None),
                LeadStatusHistory.old_pipeline_stage_id != LeadStatusHistory.new_pipeline_stage_id
            )
            .group_by(
                LeadStatusHistory.old_pipeline_stage_id,
                LeadStatusHistory.new_pipeline_stage_id
            )
        )
        result = await db.execute(query)
        transitions = result.fetchall()
        
        print(f"\n=== Transitions for Officer {officer_id} (last 30 days from {thirty_days_ago.date()}) ===")
        
        if not transitions:
            print("  No transitions found!")
            return
        
        # Build transition map
        transition_map = {}
        for old_stage, new_stage, count in transitions:
            if old_stage not in transition_map:
                transition_map[old_stage] = {}
            transition_map[old_stage][new_stage] = count
            
            old_name = stages.get(old_stage, ("?", 0))[0]
            new_name = stages.get(new_stage, ("?", 0))[0]
            print(f"  {old_stage} ({old_name}) -> {new_stage} ({new_name}): {count} times")
        
        # Calculate conversion rates
        print(f"\n=== Conversion Rates ===")
        for stage_id in sorted(transition_map.keys(), key=lambda x: stages.get(x, ("", 99))[1]):
            transitions_from = transition_map[stage_id]
            total_out = sum(transitions_from.values())
            stage_order = stages.get(stage_id, ("", 99))[1]
            
            # Count progressive transitions (to higher stage)
            progressive = 0
            regressive = 0
            for to_stage_id, count in transitions_from.items():
                to_order = stages.get(to_stage_id, ("", 0))[1]
                if to_order > stage_order:
                    progressive += count
                else:
                    regressive += count
            
            conversion = (progressive / total_out * 100) if total_out > 0 else 0
            stage_name = stages.get(stage_id, ("?", 0))[0]
            print(f"  {stage_name}: {progressive}/{total_out} = {conversion:.1f}% (regressive/lost: {regressive})")
    
    await engine.dispose()


if __name__ == "__main__":
    import sys
    officer_id = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    asyncio.run(check_transitions(officer_id))
