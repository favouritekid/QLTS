#!/usr/bin/env python3
"""
Comprehensive script to diagnose and fix Casbin permission issues.

This script:
1. Checks all Casbin policies (p rules)
2. Checks all grouping policies (g rules)
3. Adds missing policies for admin role
4. Ensures admin user has proper role mapping

Usage:
    python fix_casbin_permissions.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import casbin
from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.config import settings
from app import models


async def main():
    """Main diagnostic and fix function"""

    print("🔧 Connecting to database...")
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )

    print("🔧 Initializing Casbin adapter...")
    adapter = AsyncCasbinAdapter(engine)

    print("🔧 Loading Casbin enforcer...")
    enforcer = casbin.AsyncEnforcer("auth_model.conf", adapter)
    await enforcer.load_policy()

    # ==========================================
    # STEP 1: Check existing policies (p rules)
    # ==========================================
    print("\n" + "="*60)
    print("📊 STEP 1: Checking Permission Policies (p rules)")
    print("="*60)

    policies = enforcer.get_policy()
    print(f"\nTotal permission policies: {len(policies)}")

    if len(policies) == 0:
        print("⚠️  WARNING: No policies found!")
    else:
        print("\nExisting policies:")
        for p in policies[:10]:  # Show first 10
            print(f"  • {p[0]:20} | {p[1]:40} | {p[2]}")
        if len(policies) > 10:
            print(f"  ... and {len(policies) - 10} more")

    # ==========================================
    # STEP 2: Check grouping policies (g rules)
    # ==========================================
    print("\n" + "="*60)
    print("📊 STEP 2: Checking Grouping Policies (g rules)")
    print("="*60)

    grouping = enforcer.get_grouping_policy()
    print(f"\nTotal grouping policies: {len(grouping)}")

    if len(grouping) == 0:
        print("⚠️  WARNING: No grouping policies found!")
    else:
        print("\nExisting grouping policies:")
        for g in grouping[:20]:  # Show first 20
            print(f"  • {g[0]:20} → {g[1]}")
        if len(grouping) > 20:
            print(f"  ... and {len(grouping) - 20} more")

    # ==========================================
    # STEP 3: Check admin user mapping
    # ==========================================
    print("\n" + "="*60)
    print("📊 STEP 3: Checking Admin User (user:1)")
    print("="*60)

    # Get admin user from database
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(models.User).where(models.User.id == 1)
        )
        admin_user = result.scalar_one_or_none()

        if admin_user:
            print(f"\n✅ Found admin user in DB:")
            print(f"   ID: {admin_user.id}")
            print(f"   Username: {admin_user.username}")
            print(f"   DB Role: {admin_user.role}")
        else:
            print("❌ Admin user (ID=1) not found in database!")
            return

    # Check Casbin grouping for admin user
    user_roles = await enforcer.get_roles_for_user("user:1")
    print(f"\n📋 Casbin roles for user:1: {user_roles}")

    if not user_roles:
        print("❌ user:1 has NO grouping policies in Casbin!")
    elif "role:admin" not in user_roles:
        print(f"⚠️  user:1 has roles {user_roles} but NOT role:admin!")

    # ==========================================
    # STEP 4: Add missing policies
    # ==========================================
    print("\n" + "="*60)
    print("🔧 STEP 4: Adding Missing Policies")
    print("="*60)

    changes_made = False

    # Define required permission policies
    required_policies = [
        # Admin wildcard (should match everything)
        ("role:admin", "/*", ".*"),

        # Explicit admin endpoints
        ("role:admin", "/api/admin/*", ".*"),
        ("role:admin", "/api/admin/users", ".*"),
        ("role:admin", "/api/admin/users/*", ".*"),
        ("role:admin", "/api/admin/users/sync-status", "GET"),
        ("role:admin", "/api/admin/users/sync", "POST"),
        ("role:admin", "/api/admin/roles", ".*"),
        ("role:admin", "/api/admin/policies", ".*"),
        ("role:admin", "/api/admin/policies/*", ".*"),
        ("role:admin", "/api/admin/policies/statistics", "GET"),
        ("role:admin", "/api/admin/policies/suggestions", "GET"),
        ("role:admin", "/api/admin/activity-logs", ".*"),
    ]

    print("\n📝 Checking permission policies...")
    for policy in required_policies:
        if not enforcer.has_policy(*policy):
            success = await enforcer.add_policy(*policy)
            if success:
                print(f"  ✅ Added: {policy[0]} | {policy[1]} | {policy[2]}")
                changes_made = True
            else:
                print(f"  ❌ Failed: {policy[0]} | {policy[1]} | {policy[2]}")
        else:
            print(f"  ✓ Exists: {policy[0]} | {policy[1]} | {policy[2]}")

    # ==========================================
    # STEP 5: Fix admin user grouping
    # ==========================================
    print("\n📝 Checking grouping policies...")

    # Ensure user:1 → role:admin exists
    if not await enforcer.has_grouping_policy("user:1", "role:admin"):
        success = await enforcer.add_grouping_policy("user:1", "role:admin")
        if success:
            print("  ✅ Added: user:1 → role:admin")
            changes_made = True
        else:
            print("  ❌ Failed to add: user:1 → role:admin")
    else:
        print("  ✓ Exists: user:1 → role:admin")

    # ==========================================
    # STEP 6: Save changes
    # ==========================================
    if changes_made:
        print("\n💾 Saving policies to database...")
        await enforcer.save_policy()
        print("✅ Policies saved successfully!")
    else:
        print("\n✨ No changes needed - all policies exist!")

    # ==========================================
    # STEP 7: Verify permissions
    # ==========================================
    print("\n" + "="*60)
    print("🧪 STEP 7: Testing Permissions")
    print("="*60)

    test_cases = [
        ("user:1", "/api/admin/roles", "GET"),
        ("user:1", "/api/admin/policies", "GET"),
        ("user:1", "/api/admin/policies/statistics", "GET"),
        ("user:1", "/api/admin/users/sync-status", "GET"),
        ("user:1", "/api/admin/users/sync", "POST"),
        ("user:1", "/api/admin/activity-logs", "GET"),
    ]

    print("\nTesting admin permissions:")
    all_passed = True
    for subject, object_path, action in test_cases:
        result = enforcer.enforce(subject, object_path, action)
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {subject} → {action} {object_path}")
        if not result:
            all_passed = False

    # ==========================================
    # Summary
    # ==========================================
    print("\n" + "="*60)
    print("📊 SUMMARY")
    print("="*60)

    final_policies = enforcer.get_policy()
    final_grouping = enforcer.get_grouping_policy()

    print(f"\nTotal permission policies: {len(final_policies)}")
    print(f"Total grouping policies: {len(final_grouping)}")
    print(f"Changes made: {'Yes' if changes_made else 'No'}")
    print(f"All tests passed: {'Yes ✅' if all_passed else 'No ❌'}")

    if all_passed:
        print("\n🎉 SUCCESS! All permissions are working correctly!")
        print("\n📝 Next steps:")
        print("   1. Restart your backend server (or it will auto-reload)")
        print("   2. Refresh your browser at http://localhost:3000/admin/policies")
        print("   3. The 403 errors should be gone!")
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        print("\n📝 Troubleshooting:")
        print("   1. Check auth_model.conf matcher configuration")
        print("   2. Restart backend server")
        print("   3. Check backend logs for Casbin errors")

    # Cleanup
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
