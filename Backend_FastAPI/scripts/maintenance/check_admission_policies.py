#!/usr/bin/env python3
"""Check all Casbin admission policies in database."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import casbin
from casbin_async_sqlalchemy_adapter import Adapter
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings

async def check_policies():
    engine = create_async_engine(settings.DATABASE_URL)
    adapter = Adapter(engine)
    enforcer = casbin.AsyncEnforcer("auth_model.conf", adapter)
    await enforcer.load_policy()
    
    policies = enforcer.get_policy()
    
    print("=== ALL ADMISSION POLICIES (p) ===")
    for p in policies:
        if "admission" in p[1].lower():
            print(f"  {p[0]} | {p[1]} | {p[2]}")
    
    print(f"\nTotal admission policies: {len([p for p in policies if 'admission' in p[1].lower()])}")
    print(f"Total policies: {len(policies)}")
    
    # Check grouping policies (g)
    g_policies = enforcer.get_grouping_policy()
    print(f"\n=== GROUPING POLICIES (g) - User to Role mappings ===")
    print(f"Total g policies: {len(g_policies)}")
    for g in g_policies[:20]:  # Show first 20
        print(f"  {g[0]} -> {g[1]}")
    
    # Check if user:8 has role:officer
    print("\n=== USER ROLES ===")
    roles_for_user_8 = enforcer.get_roles_for_user("user:8")
    print(f"  Roles for user:8: {roles_for_user_8}")
    
    # Manual permission test (sync version since enforce is not async in pycasbin)
    print("\n=== MANUAL PERMISSION TESTS ===")
    test_cases = [
        ("user:8", "/api/admissions", "GET"),
        ("user:8", "/api/admissions/1", "GET"),
        ("role:officer", "/api/admissions", "GET"),
        ("role:officer", "/api/admissions/1", "GET"),
    ]
    
    for sub, obj, act in test_cases:
        allowed = enforcer.enforce(sub, obj, act)
        status = "✅" if allowed else "❌"
        print(f"  {status} {sub} | {obj} | {act}")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_policies())
