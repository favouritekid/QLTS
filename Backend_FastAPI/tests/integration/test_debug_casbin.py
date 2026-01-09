
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.main import fastapi_app as app
from casbin_async_sqlalchemy_adapter.adapter import CasbinRule

@pytest.mark.asyncio
async def test_debug_casbin_policies(
    client: AsyncClient,
    manager_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    """
    Debug test to inspect Casbin policies and role assignments.
    """
    print("\n--- DEBUG: STARTING CASBIN INSPECTION ---")
    
    # 1. Inspect Database Content (casbin_rule table)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(CasbinRule))
        rules = result.scalars().all()
        print(f"\n--- DATABASE RULES ({len(rules)} total) ---")
        for rule in rules:
            print(f"Row: ptype={rule.ptype}, v0={rule.v0}, v1={rule.v1}, v2={rule.v2}, v3={rule.v3}")

    # 2. Inspect In-Memory Enforcer State
    if hasattr(app.state, "enforcer"):
        enforcer = app.state.enforcer
        print("\n--- ENFORCER POLICIES (p-rules) ---")
        policies = enforcer.get_policy()
        for p in policies:
            print(f"P-Rule: {p}")
            
        print("\n--- ENFORCER GROUPING POLICIES (g-rules) ---")
        grouping_policies = enforcer.get_grouping_policy()
        for g in grouping_policies:
            print(f"G-Rule: {g}")
            
        # 3. Test Permission Check Explicitly
        user_id = manager_user_in_db["id"]
        role = "role:manager"
        subject = f"user:{user_id}"
        # We use wildcard path as per latest update
        object_path_wildcard = "/api/admissions/123/reject" 
        action = "POST"
        
        print(f"\n--- PERMISSION CHECK: {subject} -> {object_path_wildcard} [{action}] ---")
        allowed = enforcer.enforce(subject, object_path_wildcard, action)
        print(f"Result: {'✅ ALLOWED' if allowed else '❌ DENIED'}")
        
        # Check roles for user
        roles = enforcer.get_roles_for_user(subject)
        print(f"Roles for {subject}: {roles}")
        
    else:
        print("\n❌ Enforcer not found in app.state!")

    print("\n--- DEBUG: END CASBIN INSPECTION ---")
