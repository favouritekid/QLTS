#!/usr/bin/env python3
"""
Quick script to add Casbin policies for admissions endpoints.

Usage:
    python add_admission_policies.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import casbin
from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


async def add_admission_policies():
    """Add policies for admission endpoints"""

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

    # Define new policies to add for admissions
    new_policies = [
        # Officer role - admissions access
        ("role:officer", "/api/admissions", "POST"),
        ("role:officer", "/api/admissions/{profile_id}", "GET"),
        ("role:officer", "/api/admissions/{profile_id}", "PUT"),
        ("role:officer", "/api/admissions/{profile_id}/submit", "POST"),
        ("role:officer", "/api/admissions/{profile_id}/enroll", "POST"),
        
        # Manager role - same permissions (inherits from officer)
        ("role:manager", "/api/admissions", "POST"),
        ("role:manager", "/api/admissions/{profile_id}", "GET"),
        ("role:manager", "/api/admissions/{profile_id}", "PUT"),
        ("role:manager", "/api/admissions/{profile_id}/submit", "POST"),
        ("role:manager", "/api/admissions/{profile_id}/enroll", "POST"),
    ]

    print("\n📝 Adding admission policies...")
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
    print("\n✅ Done! Please restart the server for changes to take effect.")


if __name__ == "__main__":
    asyncio.run(add_admission_policies())
