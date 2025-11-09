#!/usr/bin/env python3
"""
Quick script to add missing Casbin policies for sync endpoints.

This adds policies for:
- GET /api/admin/users/sync-status (admin only)
- POST /api/admin/users/sync (admin only)

Usage:
    python add_sync_policies.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent))

import casbin
from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


async def add_sync_policies():
    """Add missing policies for sync endpoints"""

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

    # Get current policy count
    policies = enforcer.get_policy()
    print(f"\n📊 Current policies count: {len(policies)}")

    # Define new policies to add
    new_policies = [
        # Admin sync endpoints
        ("role:admin", "/api/admin/users/sync-status", "GET"),
        ("role:admin", "/api/admin/users/sync", "POST"),
    ]

    print("\n📝 Adding new policies...")
    added_count = 0

    for policy in new_policies:
        role, path, method = policy

        # Check if policy already exists
        if enforcer.has_policy(*policy):
            print(f"  ⏭  Already exists: {role} | {path} | {method}")
        else:
            # Add new policy
            success = await enforcer.add_policy(*policy)
            if success:
                print(f"  ✅ Added: {role} | {path} | {method}")
                added_count += 1
            else:
                print(f"  ❌ Failed to add: {role} | {path} | {method}")

    # Save policies to database
    if added_count > 0:
        print(f"\n💾 Saving {added_count} new policies to database...")
        await enforcer.save_policy()
        print("✅ Policies saved successfully!")
    else:
        print("\n✨ No new policies to add - all policies already exist!")

    # Show final count
    final_policies = enforcer.get_policy()
    print(f"\n📊 Final policies count: {len(final_policies)}")
    print(f"📈 Total added: {added_count}")

    # Cleanup
    await engine.dispose()
    print("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(add_sync_policies())
