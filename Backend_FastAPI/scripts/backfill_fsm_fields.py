"""
Backfill FSM fields for existing transitions and statuses.

This script:
1. Backfills trigger_type and required_phase in allowed_transitions
2. Backfills display_order in consultation_status
3. Validates data consistency

Run after migration:
    python scripts/backfill_fsm_fields.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import async_session_maker
from app import models
from app.models.pipeline import TriggerTypeEnum
import structlog

log = structlog.get_logger(__name__)


async def backfill_allowed_transitions(db: AsyncSession) -> int:
    """
    Backfill trigger_type and required_phase for existing transitions.

    Logic:
    - Infer trigger_type from to_status.selectable_mode:
      - selectable_mode = 'system' → trigger_type = 'system'
      - selectable_mode = 'role' → trigger_type = 'role'
      - else → trigger_type = 'user'
    - Set required_phase = to_status.phase (if different from from_status.phase)
    - Set is_active = True for all existing transitions
    """
    # Get all transitions with status relationships
    result = await db.execute(
        select(models.AllowedTransition)
        .join(
            models.ConsultationStatus,
            models.AllowedTransition.to_status_id == models.ConsultationStatus.id
        )
    )
    transitions = result.scalars().all()

    updated_count = 0

    for trans in transitions:
        # Load from_status and to_status
        from_status = await db.get(models.ConsultationStatus, trans.from_status_id)
        to_status = await db.get(models.ConsultationStatus, trans.to_status_id)

        if not from_status or not to_status:
            log.warning(
                "Transition has missing status",
                transition_id=trans.id,
                from_status_id=trans.from_status_id,
                to_status_id=trans.to_status_id
            )
            continue

        # Infer trigger_type from to_status.selectable_mode
        trigger_type = TriggerTypeEnum.user  # Default

        if to_status.selectable_mode == 'system':
            trigger_type = TriggerTypeEnum.system
        elif to_status.selectable_mode == 'role-based' or to_status.selectable_mode == 'role':
            trigger_type = TriggerTypeEnum.role
        # else: keep user

        # Infer required_phase (only if cross-phase)
        required_phase = None
        if from_status.phase != to_status.phase:
            required_phase = to_status.phase

        # Update transition
        await db.execute(
            update(models.AllowedTransition)
            .where(models.AllowedTransition.id == trans.id)
            .values(
                trigger_type=trigger_type,
                required_phase=required_phase,
                is_active=True  # All existing transitions are active
            )
        )

        updated_count += 1

        log.info(
            "Backfilled transition",
            transition_id=trans.id,
            from_status=trans.from_status_id,
            to_status=trans.to_status_id,
            trigger_type=trigger_type.value,
            required_phase=required_phase
        )

    return updated_count


async def backfill_consultation_status_display_order(db: AsyncSession) -> int:
    """
    Backfill display_order for existing consultation statuses.

    Logic:
    - Base order on phase:
      - consultation: 100-299
      - admission: 300-499
      - fee: 400-499
      - enrolled: 500-599
      - universal: 900+
    - Within phase, order by stage.order then status name
    """
    # Get all statuses with stage relationship
    result = await db.execute(
        select(models.ConsultationStatus)
    )
    statuses = result.scalars().all()

    # Phase base offsets
    phase_offsets = {
        "consultation": 100,
        "admission": 300,
        "fee": 400,
        "enrolled": 500,
        "universal": 900
    }

    updated_count = 0

    for status in statuses:
        # Get base offset from phase
        base_offset = phase_offsets.get(status.phase, 0)

        # Get stage order (if exists)
        stage_order = 0
        if status.stage:
            stage = await db.get(models.PipelineStage, status.stage_id)
            if stage:
                stage_order = stage.order * 10  # Multiply by 10 to leave gaps

        # Calculate display_order
        display_order = base_offset + stage_order

        # Update status
        await db.execute(
            update(models.ConsultationStatus)
            .where(models.ConsultationStatus.id == status.id)
            .values(display_order=display_order)
        )

        updated_count += 1

        log.info(
            "Backfilled status display_order",
            status_id=status.id,
            status_name=status.name,
            phase=status.phase,
            display_order=display_order
        )

    return updated_count


async def validate_data_consistency(db: AsyncSession) -> bool:
    """
    Validate FSM data consistency after backfill.

    Checks:
    1. All transitions have trigger_type set
    2. Cross-phase transitions have required_phase set
    3. required_phase matches to_status.phase
    4. All statuses have display_order >= 0
    """
    errors = []

    # Check 1: All transitions have trigger_type
    result = await db.execute(
        select(models.AllowedTransition)
        .where(models.AllowedTransition.trigger_type == None)
    )
    null_trigger_type = result.scalars().all()
    if null_trigger_type:
        errors.append(f"Found {len(null_trigger_type)} transitions with NULL trigger_type")

    # Check 2 & 3: Cross-phase transitions validation
    result = await db.execute(
        select(models.AllowedTransition)
    )
    transitions = result.scalars().all()

    for trans in transitions:
        from_status = await db.get(models.ConsultationStatus, trans.from_status_id)
        to_status = await db.get(models.ConsultationStatus, trans.to_status_id)

        if from_status and to_status:
            # Check if cross-phase
            if from_status.phase != to_status.phase:
                if not trans.required_phase:
                    errors.append(
                        f"Transition {trans.id} is cross-phase but missing required_phase"
                    )
                elif trans.required_phase != to_status.phase:
                    errors.append(
                        f"Transition {trans.id} required_phase mismatch: "
                        f"{trans.required_phase} != {to_status.phase}"
                    )

    # Check 4: All statuses have display_order
    result = await db.execute(
        select(models.ConsultationStatus)
        .where(models.ConsultationStatus.display_order == None)
    )
    null_display_order = result.scalars().all()
    if null_display_order:
        errors.append(f"Found {len(null_display_order)} statuses with NULL display_order")

    # Print results
    if errors:
        log.error("Data validation failed", errors=errors)
        for error in errors:
            print(f"❌ {error}")
        return False
    else:
        log.info("Data validation passed - all checks OK")
        print("✅ All validation checks passed")
        return True


async def main():
    """Run backfill script."""
    print("=" * 80)
    print("FSM FIELDS BACKFILL SCRIPT")
    print("=" * 80)

    async with async_session_maker() as db:
        try:
            # Step 1: Backfill allowed_transitions
            print("\n[1/3] Backfilling allowed_transitions...")
            transitions_count = await backfill_allowed_transitions(db)
            print(f"✅ Updated {transitions_count} transitions")

            # Step 2: Backfill consultation_status
            print("\n[2/3] Backfilling consultation_status display_order...")
            statuses_count = await backfill_consultation_status_display_order(db)
            print(f"✅ Updated {statuses_count} statuses")

            # Commit changes
            await db.commit()
            print("\n✅ All changes committed to database")

            # Step 3: Validate data
            print("\n[3/3] Validating data consistency...")
            is_valid = await validate_data_consistency(db)

            if is_valid:
                print("\n" + "=" * 80)
                print("✅ BACKFILL COMPLETED SUCCESSFULLY")
                print("=" * 80)
                print(f"   - Transitions updated: {transitions_count}")
                print(f"   - Statuses updated: {statuses_count}")
                print(f"   - Data validation: PASSED")
                return 0
            else:
                print("\n" + "=" * 80)
                print("⚠️  BACKFILL COMPLETED WITH WARNINGS")
                print("=" * 80)
                print("   Please review validation errors above")
                return 1

        except Exception as e:
            await db.rollback()
            log.error("Backfill failed", error=str(e), exc_info=True)
            print(f"\n❌ Backfill failed: {e}")
            return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
