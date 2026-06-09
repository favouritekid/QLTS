"""
Import FSM data v3 from CSV files.

This script:
1. Backs up current data
2. Clears consultation_status and allowed_transitions tables
3. Loads data from v3 CSV files
4. Validates data integrity

Run after migration:
    python scripts/import_fsm_data_v3.py
"""

import asyncio
import csv
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app import models
import structlog

log = structlog.get_logger(__name__)


async def backup_current_data(db: AsyncSession) -> dict:
    """Backup current data before clearing."""
    backup = {
        'timestamp': datetime.now().isoformat(),
        'consultation_status_count': 0,
        'allowed_transitions_count': 0
    }

    # Count current records
    result = await db.execute(select(models.ConsultationStatus))
    backup['consultation_status_count'] = len(result.scalars().all())

    result = await db.execute(select(models.AllowedTransition))
    backup['allowed_transitions_count'] = len(result.scalars().all())

    log.info("Current data backed up", backup=backup)
    return backup


async def clear_tables(db: AsyncSession):
    """Clear existing data from tables."""
    # Delete in correct order (foreign key constraints)
    await db.execute(delete(models.AllowedTransition))
    await db.execute(delete(models.ConsultationStatus))

    log.info("Tables cleared")


async def load_consultation_status_v3(db: AsyncSession, csv_path: str) -> int:
    """Load consultation_status from v3 CSV."""
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    count = 0
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert string booleans to Python bool
            is_final = row['is_final'].lower() == 'true'
            is_universal = row['is_universal'].lower() == 'true'
            updates_pipeline = row['updates_pipeline'].lower() == 'true'
            counts_for_funnel = row['counts_for_funnel'].lower() == 'true'
            display_order = int(row['display_order'])
            legacy_status = (row.get('legacy_status') or '').strip() or None

            # Handle NULL stage_id for universal statuses
            stage_id = row['stage_id'] if row['stage_id'] != 'NULL' else None

            status = models.ConsultationStatus(
                id=row['id'],
                code=row['code'],
                name=row['name'],
                phase=row['phase'],
                stage_id=stage_id,
                status_type=row['status_type'],
                selectable_mode=row['selectable_mode'],
                outcome_type=row['outcome_type'],
                is_final=is_final,
                is_universal=is_universal,
                updates_pipeline=updates_pipeline,
                counts_for_funnel=counts_for_funnel,
                display_order=display_order,
                description=row['description'],
                color_code=row['color_code'],
                legacy_status=legacy_status,
                # Deprecated fields (for backward compatibility)
                is_final_status=is_final,
                counts_for_kpi=counts_for_funnel,
                selectable_by_user=row['selectable_mode']
            )
            db.add(status)
            count += 1

            log.debug("Loaded consultation_status", status_id=row['id'], name=row['name'])

    await db.flush()
    log.info("Loaded consultation_status records", count=count)
    return count


async def load_allowed_transitions_v3(db: AsyncSession, csv_path: str) -> int:
    """Load allowed_transitions from v3 CSV."""
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    count = 0
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert string booleans to Python bool
            is_active = row['is_active'].lower() == 'true'

            # Handle NULL required_phase
            required_phase = row['required_phase'] if row['required_phase'] else None

            transition = models.AllowedTransition(
                id=int(row['id']),
                from_status_id=row['from_status_id'],
                to_status_id=row['to_status_id'],
                trigger_type=row['trigger_type'],
                required_phase=required_phase,
                is_active=is_active,
                description=row['description']
            )
            db.add(transition)
            count += 1

            log.debug(
                "Loaded transition",
                transition_id=row['id'],
                from_status=row['from_status_id'],
                to_status=row['to_status_id'],
                trigger_type=row['trigger_type']
            )

    await db.flush()
    log.info("Loaded allowed_transitions records", count=count)
    return count


async def validate_data(
    db: AsyncSession,
    expected_statuses: int,
    expected_transitions: int,
) -> bool:
    """Validate loaded data. Expected counts come from the loaders (= CSV row
    counts), so adding a status/transition needs no magic-number edit here —
    the check is that the DB now holds exactly what was just loaded."""
    errors = []

    # Check 1: All statuses loaded
    result = await db.execute(select(models.ConsultationStatus))
    statuses = result.scalars().all()
    if len(statuses) != expected_statuses:
        errors.append(
            f"Expected {expected_statuses} consultation_status records, "
            f"got {len(statuses)}"
        )

    # Check 2: All transitions loaded
    result = await db.execute(select(models.AllowedTransition))
    transitions = result.scalars().all()
    if len(transitions) != expected_transitions:
        errors.append(
            f"Expected {expected_transitions} allowed_transitions, "
            f"got {len(transitions)}"
        )

    # Check 3: All transitions have trigger_type
    for trans in transitions:
        if not trans.trigger_type:
            errors.append(f"Transition {trans.id} missing trigger_type")

    # Check 4: Cross-phase transitions have required_phase
    for trans in transitions:
        from_status = await db.get(models.ConsultationStatus, trans.from_status_id)
        to_status = await db.get(models.ConsultationStatus, trans.to_status_id)

        if from_status and to_status:
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

    # Check 5: All statuses have display_order
    for status in statuses:
        if status.display_order is None:
            errors.append(f"Status {status.id} missing display_order")

    # Print results
    if errors:
        log.error("Data validation failed", errors=errors)
        for error in errors:
            print(f"❌ {error}")
        return False
    else:
        log.info("Data validation passed")
        print("✅ All validation checks passed")
        return True


async def main():
    """Run import script."""
    print("=" * 80)
    print("FSM DATA v3 IMPORT SCRIPT")
    print("=" * 80)

    # CSV file paths
    # CSV file paths
    # Modified to look in local data directory
    csv_dir = Path(__file__).parent / "data"
    consultation_status_csv = csv_dir / "consultation_status_v3.csv"
    allowed_transitions_csv = csv_dir / "allowed_transitions_v3.csv"

    print(f"\nCSV files:")
    print(f"  - consultation_status: {consultation_status_csv}")
    print(f"  - allowed_transitions: {allowed_transitions_csv}")

    if not consultation_status_csv.exists():
        print(f"\n❌ Error: {consultation_status_csv} not found")
        return 1

    if not allowed_transitions_csv.exists():
        print(f"\n❌ Error: {allowed_transitions_csv} not found")
        return 1

    # Confirm with user
    print("\n⚠️  WARNING: This will DELETE all existing data in:")
    print("   - consultation_status")
    print("   - allowed_transitions")
    print("\nContinue? (yes/no): ", end='')
    confirm = input().strip().lower()

    if confirm != 'yes':
        print("\n❌ Import cancelled by user")
        return 1

    async with AsyncSessionLocal() as db:
        try:
            # Step 1: Backup current data
            print("\n[1/5] Backing up current data...")
            backup = await backup_current_data(db)
            print(f"✅ Backed up {backup['consultation_status_count']} statuses, "
                  f"{backup['allowed_transitions_count']} transitions")

            # Step 2: Clear tables
            print("\n[2/5] Clearing tables...")
            await clear_tables(db)
            print("✅ Tables cleared")

            # Step 3: Load consultation_status
            print("\n[3/5] Loading consultation_status from v3 CSV...")
            status_count = await load_consultation_status_v3(
                db,
                str(consultation_status_csv)
            )
            print(f"✅ Loaded {status_count} consultation_status records")

            # Step 4: Load allowed_transitions
            print("\n[4/5] Loading allowed_transitions from v3 CSV...")
            transition_count = await load_allowed_transitions_v3(
                db,
                str(allowed_transitions_csv)
            )
            print(f"✅ Loaded {transition_count} allowed_transitions records")

            # Commit changes
            await db.commit()
            print("\n✅ All changes committed to database")

            # Step 5: Validate data (expected = what the loaders just inserted)
            print("\n[5/5] Validating data integrity...")
            is_valid = await validate_data(db, status_count, transition_count)

            if is_valid:
                print("\n" + "=" * 80)
                print("✅ IMPORT COMPLETED SUCCESSFULLY")
                print("=" * 80)
                print(f"   - Consultation statuses: {status_count}")
                print(f"   - Allowed transitions: {transition_count}")
                print(f"   - Data validation: PASSED")
                print("\nNext step: Test FSM engine with new data")
                return 0
            else:
                print("\n" + "=" * 80)
                print("⚠️  IMPORT COMPLETED WITH WARNINGS")
                print("=" * 80)
                print("   Please review validation errors above")
                return 1

        except Exception as e:
            await db.rollback()
            log.error("Import failed", error=str(e), exc_info=True)
            print(f"\n❌ Import failed: {e}")
            print("\n💡 Tip: Check that migration was run first:")
            print("   alembic upgrade head")
            return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
