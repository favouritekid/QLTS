#!/usr/bin/env python3
"""
Pre-deploy check: Ensure critical Casbin policies exist before deployment.

This script MUST be run before every deployment to prevent admin lockout.

Critical policies are essential for system operation:
- Admin wildcard policy: Without this, no admin can access anything
- Other critical policies defined in CRITICAL_POLICIES

Usage:
    # With environment variable
    DATABASE_URL=postgresql://... python scripts/pre_deploy_check.py

    # Or in CI/CD
    - name: Pre-deploy policy check
      run: python scripts/pre_deploy_check.py
      env:
        DATABASE_URL: ${{ secrets.DATABASE_URL }}

Exit codes:
    0 - All critical policies present
    1 - Missing critical policies (DEPLOY BLOCKED)

Reference: AUTHORIZATION_DECISIONS.md Decision 1
"""

import asyncio
import os
import sys
from typing import List, Tuple

# ============================================================
# CRITICAL POLICIES
# ============================================================

# These policies MUST exist for system to function
# Format: (v0, v1, v2) matching casbin_rule table
CRITICAL_POLICIES: List[Tuple[str, str, str]] = [
    # Admin wildcard - MOST CRITICAL
    # Without this, admin cannot access ANY endpoint
    ("role:admin", "/*", ".*"),
]

# Warning policies - should exist but not blocking
WARNING_POLICIES: List[Tuple[str, str, str]] = [
    # Manager should have user management access
    ("role:manager", "/api/admin/users", ".*"),

    # Profile access for all roles
    ("role:user", "/api/profile", "GET"),
    ("role:user", "/api/profile", "PUT"),
]

# Role inheritance (g policies) - Phase 3.3
# Format: (child_role, parent_role)
ROLE_INHERITANCE: List[Tuple[str, str]] = [
    ("role:officer", "role:user"),    # Officer inherits from User
    ("role:manager", "role:officer"), # Manager inherits from Officer
    ("role:admin", "role:manager"),   # Admin inherits from Manager
]


# ============================================================
# DATABASE CONNECTION
# ============================================================

async def get_db_connection():
    """Get async database connection."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        database_url = os.environ.get("DATABASE_URL")

        if not database_url:
            # Try to load from .env or config
            try:
                from app.core.config import settings
                database_url = settings.DATABASE_URL
            except ImportError:
                pass

        if not database_url:
            print("ERROR: DATABASE_URL not set")
            print("Set environment variable or ensure app.core.config is available")
            return None, None

        # Convert postgres:// to postgresql+asyncpg://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        engine = create_async_engine(database_url)
        return engine, text

    except ImportError as e:
        print(f"ERROR: Missing dependency: {e}")
        print("Install with: pip install sqlalchemy asyncpg")
        return None, None


# ============================================================
# POLICY CHECKS
# ============================================================

async def check_policy_exists(conn, text_func, v0: str, v1: str, v2: str) -> bool:
    """Check if a specific policy exists."""
    result = await conn.execute(text_func("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
    """), {"v0": v0, "v1": v1, "v2": v2})

    count = result.scalar()
    return count > 0


async def check_grouping_exists(conn, text_func, child: str, parent: str) -> bool:
    """Check if a role inheritance (grouping policy) exists."""
    result = await conn.execute(text_func("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'g' AND v0 = :child AND v1 = :parent
    """), {"child": child, "parent": parent})

    count = result.scalar()
    return count > 0


async def check_critical_policies() -> Tuple[bool, List[str], List[str], List[str]]:
    """
    Check all critical policies exist.

    Returns:
        (success, missing_critical, missing_warnings, missing_inheritance)
    """
    engine, text_func = await get_db_connection()

    if engine is None:
        return False, ["Could not connect to database"], [], []

    missing_critical = []
    missing_warnings = []
    missing_inheritance = []

    try:
        async with engine.connect() as conn:
            # Check critical policies
            for v0, v1, v2 in CRITICAL_POLICIES:
                exists = await check_policy_exists(conn, text_func, v0, v1, v2)
                if not exists:
                    missing_critical.append(f"({v0}, {v1}, {v2})")

            # Check warning policies
            for v0, v1, v2 in WARNING_POLICIES:
                exists = await check_policy_exists(conn, text_func, v0, v1, v2)
                if not exists:
                    missing_warnings.append(f"({v0}, {v1}, {v2})")

            # Check role inheritance (Phase 3.3)
            for child, parent in ROLE_INHERITANCE:
                exists = await check_grouping_exists(conn, text_func, child, parent)
                if not exists:
                    missing_inheritance.append(f"({child} -> {parent})")

    except Exception as e:
        return False, [f"Database error: {e}"], [], []

    finally:
        await engine.dispose()

    success = len(missing_critical) == 0
    return success, missing_critical, missing_warnings, missing_inheritance


async def get_policy_counts() -> dict:
    """Get count of policies per role for reporting."""
    engine, text_func = await get_db_connection()

    if engine is None:
        return {}

    counts = {}

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text_func("""
                SELECT v0, COUNT(*) as cnt
                FROM casbin_rule
                WHERE ptype = 'p'
                GROUP BY v0
                ORDER BY cnt DESC
            """))

            for row in result:
                counts[row[0]] = row[1]

    except Exception as e:
        print(f"Warning: Could not get policy counts: {e}")

    finally:
        await engine.dispose()

    return counts


# ============================================================
# MAIN
# ============================================================

async def main():
    """Main entry point."""
    print("=" * 60)
    print("PRE-DEPLOY POLICY CHECK")
    print("=" * 60)
    print()

    # Run checks
    success, missing_critical, missing_warnings, missing_inheritance = await check_critical_policies()

    # Get policy counts for reporting
    counts = await get_policy_counts()

    # Report policy counts
    if counts:
        print("Current policy counts by role:")
        for role, count in counts.items():
            print(f"  {role}: {count} policies")
        print()

    # Report warnings (non-blocking)
    if missing_warnings:
        print("WARNINGS (non-blocking):")
        for policy in missing_warnings:
            print(f"  - Missing policy: {policy}")
        print()

    # Report missing inheritance (non-blocking but important)
    if missing_inheritance:
        print("ROLE INHERITANCE WARNINGS:")
        print("  Role inheritance reduces policy duplication (Phase 3.3)")
        for inheritance in missing_inheritance:
            print(f"  - Missing: {inheritance}")
        print()
        print("  FIX: Run migration p3a1b2c3d4e5")
        print()

    # Report critical issues
    if missing_critical:
        print("=" * 60)
        print("CRITICAL: DEPLOY BLOCKED")
        print("=" * 60)
        print()
        print("Missing critical policies:")
        for policy in missing_critical:
            print(f"  - {policy}")
        print()
        print("Without these policies, system will be UNUSABLE!")
        print()
        print("FIX OPTIONS:")
        print("  1. Run Alembic migrations to restore default policies:")
        print("     alembic upgrade head")
        print()
        print("  2. Manually insert missing policies:")
        for policy in missing_critical:
            v0, v1, v2 = policy.strip("()").split(", ")
            print(f"     INSERT INTO casbin_rule (ptype, v0, v1, v2)")
            print(f"     VALUES ('p', {v0}, {v1}, {v2});")
        print()
        print("Reference: AUTHORIZATION_DECISIONS.md Decision 1")
        print()
        return False

    print("=" * 60)
    print("PASSED: All critical policies present")
    print("=" * 60)
    print()
    print("Safe to deploy.")
    return True


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
