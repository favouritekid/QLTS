#!/usr/bin/env python3
"""
Add missing PUT permission for officer role to edit consultations.

Usage:
    python fix_officer_consultation_permission.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import casbin
from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


async def main():
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

    # Define the missing policy
    policy = ("role:officer", "/api/leads/{lead_id}/consultations/{consultation_id}", "PUT")
    
    print(f"\n📝 Checking policy: {policy}")
    
    if not enforcer.has_policy(*policy):
        success = await enforcer.add_policy(*policy)
        if success:
            print(f"  ✅ Added: {policy[0]} | {policy[1]} | {policy[2]}")
            await enforcer.save_policy()
            print("💾 Policy saved to database!")
        else:
            print(f"  ❌ Failed to add policy")
    else:
        print(f"  ✓ Policy already exists")

    # Verify
    print("\n🧪 Testing permission:")
    # Test with a sample user that has officer role (user:8 from your log)
    result = await enforcer.enforce("user:8", "/api/leads/97/consultations/123", "PUT")
    print(f"  user:8 → PUT /api/leads/97/consultations/123: {'✅ PASS' if result else '❌ FAIL'}")

    await engine.dispose()
    
    print("\n📝 Next steps:")
    print("   1. Restart your backend server")
    print("   2. Try editing the consultation again")


if __name__ == "__main__":
    asyncio.run(main())
