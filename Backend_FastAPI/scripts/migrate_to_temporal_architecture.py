#!/usr/bin/env python3
"""
Data Migration Script: Migrate to Temporal Architecture

This script populates the new temporal tables (user_unit_assignment, major_academic_info)
with data from existing tables (user, major).

PREREQUISITES:
1. Alembic migration j5k6l7m8n9o0 must be applied successfully
2. Database backup must be created
3. Application must be stopped (to prevent concurrent writes)

USAGE:
    python scripts/migrate_to_temporal_architecture.py

STEPS:
1. Create UserUnitAssignment records from existing user.role/unit_id
2. Update user.current_assignment_id to point to those records
3. Add FK constraint user.current_assignment_id -> user_unit_assignment.id
4. (Optional) Create MajorAcademicInfo for current year

EXIT CODES:
    0 = Success
    1 = Database connection error
    2 = Migration already run (detect duplicate data)
    3 = Validation error (data integrity issue)
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, engine
from app.models import User, UserUnitAssignment, Major, MajorAcademicInfo

log = structlog.get_logger(__name__)


async def check_migration_status(db: AsyncSession) -> bool:
    """
    Check if data migration has already been run.

    Returns:
        True if migration already completed, False otherwise
    """
    # Check if user_unit_assignment has any records
    result = await db.execute(select(func.count()).select_from(UserUnitAssignment))
    count = result.scalar()

    if count > 0:
        log.warning(
            "Data migration appears to have already run",
            user_unit_assignment_count=count
        )
        return True

    return False


async def migrate_user_assignments(db: AsyncSession) -> dict:
    """
    Create initial UserUnitAssignment records from existing user data.

    For each user with a role/unit_id, creates an active assignment record
    with start_date = current time.

    Returns:
        Dictionary with migration statistics
    """
    log.info("Starting user assignment migration...")

    # Get all users
    result = await db.execute(select(User))
    users = result.scalars().all()

    stats = {
        "total_users": len(users),
        "assignments_created": 0,
        "users_without_assignment": 0,
        "errors": []
    }

    for user in users:
        try:
            # Skip users without unit (regular users might not be assigned)
            if user.unit_id is None:
                log.debug(
                    "User has no unit assignment, skipping",
                    user_id=user.id,
                    username=user.username,
                    role=user.role
                )
                stats["users_without_assignment"] += 1
                continue

            # Create initial assignment record
            assignment = UserUnitAssignment(
                user_id=user.id,
                unit_id=user.unit_id,
                role=user.role,
                assigned_by_user_id=None,  # NULL = initial/migration assignment
                start_date=datetime.utcnow(),
                end_date=None,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )

            db.add(assignment)
            await db.flush()  # Get assignment.id

            # Update user.current_assignment_id (cache sync)
            user.current_assignment_id = assignment.id

            stats["assignments_created"] += 1

            log.debug(
                "Created assignment for user",
                user_id=user.id,
                username=user.username,
                assignment_id=assignment.id,
                unit_id=assignment.unit_id,
                role=assignment.role
            )

        except Exception as e:
            log.error(
                "Failed to create assignment for user",
                user_id=user.id,
                username=getattr(user, 'username', 'unknown'),
                error=str(e),
                exc_info=True
            )
            stats["errors"].append({
                "user_id": user.id,
                "error": str(e)
            })

    await db.commit()

    log.info(
        "User assignment migration completed",
        **{k: v for k, v in stats.items() if k != "errors"},
        error_count=len(stats["errors"])
    )

    return stats


async def add_foreign_key_constraint(db: AsyncSession) -> None:
    """
    Add FK constraint: user.current_assignment_id -> user_unit_assignment.id

    This must be done AFTER populating user_unit_assignment table.
    """
    log.info("Adding foreign key constraint...")

    try:
        await db.execute(text("""
            ALTER TABLE "user"
            ADD CONSTRAINT fk_user_current_assignment
            FOREIGN KEY (current_assignment_id)
            REFERENCES user_unit_assignment(id)
            ON DELETE SET NULL
        """))
        await db.commit()

        log.info("Foreign key constraint added successfully")

    except Exception as e:
        log.error(
            "Failed to add foreign key constraint",
            error=str(e),
            exc_info=True
        )
        raise


async def create_current_year_academic_info(db: AsyncSession, year: int | None = None) -> dict:
    """
    (Optional) Create MajorAcademicInfo records for current year.

    This is optional because academic info is managed separately.
    Just creates placeholder records for all active majors.

    Args:
        db: Database session
        year: Academic year (default: current year)

    Returns:
        Dictionary with migration statistics
    """
    if year is None:
        year = datetime.utcnow().year

    log.info("Creating current year academic info placeholders...", year=year)

    # Get all active majors
    result = await db.execute(
        select(Major).where(Major.is_active == True)
    )
    majors = result.scalars().all()

    stats = {
        "total_majors": len(majors),
        "academic_info_created": 0,
        "errors": []
    }

    for major in majors:
        try:
            # Check if academic info already exists for this year
            existing = await db.execute(
                select(MajorAcademicInfo).where(
                    MajorAcademicInfo.major_id == major.id,
                    MajorAcademicInfo.academic_year == year
                )
            )
            if existing.scalar_one_or_none():
                log.debug(
                    "Academic info already exists for major/year",
                    major_id=major.id,
                    year=year
                )
                continue

            # Create placeholder
            academic_info = MajorAcademicInfo(
                major_id=major.id,
                academic_year=year,
                target_audience=None,  # To be filled by admin
                detailed_info=None,
                current_year_benefits=None,
                tuition_fee_per_year=None,
                annual_admission_quota=None,
                is_published=False,  # Draft status
                created_by_user_id=None
            )

            db.add(academic_info)
            stats["academic_info_created"] += 1

            log.debug(
                "Created academic info placeholder",
                major_id=major.id,
                major_code=major.code,
                year=year
            )

        except Exception as e:
            log.error(
                "Failed to create academic info for major",
                major_id=major.id,
                major_code=getattr(major, 'code', 'unknown'),
                error=str(e),
                exc_info=True
            )
            stats["errors"].append({
                "major_id": major.id,
                "error": str(e)
            })

    await db.commit()

    log.info(
        "Academic info migration completed",
        **{k: v for k, v in stats.items() if k != "errors"},
        error_count=len(stats["errors"])
    )

    return stats


async def validate_migration(db: AsyncSession) -> bool:
    """
    Validate that migration completed successfully.

    Checks:
    1. All users with unit_id have a current_assignment_id
    2. All current_assignment_id values are valid (point to active assignments)
    3. No orphaned assignments

    Returns:
        True if validation passed, False otherwise
    """
    log.info("Validating migration...")

    issues = []

    # Check 1: Users with unit but no current_assignment_id
    result = await db.execute(
        select(User).where(
            User.unit_id.isnot(None),
            User.current_assignment_id.is_(None)
        )
    )
    users_missing_assignment = result.scalars().all()

    if users_missing_assignment:
        issues.append(
            f"Found {len(users_missing_assignment)} users with unit_id but no current_assignment_id"
        )
        for user in users_missing_assignment[:5]:  # Log first 5
            log.warning(
                "User missing current_assignment_id",
                user_id=user.id,
                username=user.username,
                unit_id=user.unit_id
            )

    # Check 2: Users with current_assignment_id pointing to inactive assignment
    result = await db.execute(
        select(User)
        .join(UserUnitAssignment, User.current_assignment_id == UserUnitAssignment.id)
        .where(UserUnitAssignment.is_active == False)
    )
    users_with_inactive_assignment = result.scalars().all()

    if users_with_inactive_assignment:
        issues.append(
            f"Found {len(users_with_inactive_assignment)} users with inactive current_assignment"
        )

    # Check 3: Orphaned active assignments (is_active=true but user.current_assignment_id doesn't point to it)
    # This is OK - just log it
    result = await db.execute(
        select(func.count()).select_from(UserUnitAssignment).where(
            UserUnitAssignment.is_active == True
        )
    )
    total_active_assignments = result.scalar()

    result = await db.execute(
        select(func.count(func.distinct(User.current_assignment_id)))
        .where(User.current_assignment_id.isnot(None))
    )
    users_with_assignment = result.scalar()

    log.info(
        "Assignment counts",
        total_active_assignments=total_active_assignments,
        users_with_current_assignment=users_with_assignment
    )

    # Report results
    if issues:
        log.error("Validation FAILED", issues=issues)
        for issue in issues:
            print(f"❌ {issue}")
        return False
    else:
        log.info("✅ Validation PASSED - migration successful!")
        return True


async def main():
    """Main migration workflow."""
    print("=" * 70)
    print("Data Migration: Temporal Architecture")
    print("=" * 70)
    print()

    try:
        # Create database session
        async with AsyncSessionLocal() as db:
            # Step 1: Check if already run
            already_run = await check_migration_status(db)
            if already_run:
                print("⚠️  Migration appears to have already run.")
                response = input("Continue anyway? (yes/no): ")
                if response.lower() != 'yes':
                    print("Aborted.")
                    return 2

            # Step 2: Migrate user assignments
            print("\n📋 Step 1: Migrating user assignments...")
            user_stats = await migrate_user_assignments(db)
            print(f"✅ Created {user_stats['assignments_created']} assignments")
            print(f"ℹ️  {user_stats['users_without_assignment']} users without unit")
            if user_stats['errors']:
                print(f"⚠️  {len(user_stats['errors'])} errors occurred")

            # Step 3: Add FK constraint
            print("\n🔗 Step 2: Adding foreign key constraint...")
            await add_foreign_key_constraint(db)
            print("✅ Foreign key constraint added")

            # Step 4: (Optional) Create academic info
            print("\n📚 Step 3: Creating academic info placeholders (optional)...")
            response = input("Create academic info for current year? (yes/no): ")
            if response.lower() == 'yes':
                year = datetime.utcnow().year
                academic_stats = await create_current_year_academic_info(db, year)
                print(f"✅ Created {academic_stats['academic_info_created']} academic info records")
            else:
                print("⏭️  Skipped academic info creation")

            # Step 5: Validate
            print("\n✅ Step 4: Validating migration...")
            validation_passed = await validate_migration(db)

            if validation_passed:
                print("\n" + "=" * 70)
                print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
                print("=" * 70)
                print("\nNext steps:")
                print("1. Restart your application")
                print("2. Test user assignment functionality")
                print("3. Verify Casbin authorization still works")
                print("4. Monitor logs for any issues")
                return 0
            else:
                print("\n" + "=" * 70)
                print("❌ MIGRATION COMPLETED WITH VALIDATION ERRORS")
                print("=" * 70)
                print("\nPlease review the errors above and fix manually.")
                return 3

    except Exception as e:
        log.error("Migration failed", error=str(e), exc_info=True)
        print(f"\n❌ ERROR: {e}")
        print("\nMigration failed. Please check logs and database state.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
