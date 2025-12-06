#!/usr/bin/env python3
"""
Debug Casbin policies for a user.
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
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)

    print("🔧 Loading Casbin enforcer...")
    adapter = AsyncCasbinAdapter(engine)
    enforcer = casbin.AsyncEnforcer("auth_model.conf", adapter)
    await enforcer.load_policy()

    # Check all policies for role:officer
    print("\n📋 All policies for role:officer:")
    all_policies = enforcer.get_policy()
    officer_policies = [p for p in all_policies if p[0] == "role:officer"]
    for p in officer_policies:
        print(f"  {p[0]} | {p[1]} | {p[2]}")
    
    print(f"\n📊 Total officer policies: {len(officer_policies)}")

    # Check user:8 grouping
    print("\n👤 Checking grouping for user:8:")
    roles = enforcer.get_roles_for_user("user:8")
    print(f"  Roles: {roles}")

    # Test specific permission
    print("\n🧪 Testing enforce (sync):")
    test_cases = [
        ("user:8", "/api/leads/97/consultations/123", "PUT"),
        ("user:8", "/api/leads/{lead_id}/consultations/{consultation_id}", "PUT"),
        ("role:officer", "/api/leads/{lead_id}/consultations/{consultation_id}", "PUT"),
    ]
    for sub, obj, act in test_cases:
        # Use sync enforce (not async)
        result = enforcer.enforce(sub, obj, act)
        print(f"  {sub} → {act} {obj}: {'✅ PASS' if result else '❌ FAIL'}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
