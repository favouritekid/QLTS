# tests/integration/test_debug_full_casbin_flow.py
"""
Comprehensive debug test to check the FULL Casbin enforcement flow.

This test simulates what happens when vothuhien tries to access /api/admissions
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.main import fastapi_app as app
from app import models
from casbin_async_sqlalchemy_adapter.adapter import CasbinRule


@pytest.mark.asyncio
async def test_debug_full_casbin_flow_for_vothuhien(client: AsyncClient):
    """
    Full debug flow for vothuhien accessing /api/admissions
    """
    print("\n" + "="*70)
    print("DEBUG: FULL CASBIN ENFORCEMENT FLOW FOR vothuhien")
    print("="*70)
    
    async with AsyncSessionLocal() as session:
        # 1. Find vothuhien in database
        result = await session.execute(
            select(models.User).where(models.User.username == "vothuhien")
        )
        user = result.scalar_one_or_none()
        
        if not user:
            print("\n❌ vothuhien NOT FOUND in database!")
            return
            
        print(f"\n--- USER INFO FROM DATABASE ---")
        print(f"  ID: {user.id}")
        print(f"  Username: {user.username}")
        print(f"  Role: {user.role}")
        print(f"  Status: {user.status}")
        print(f"  Unit ID: {user.unit_id}")
        
        # 2. Check g-rules in database for this user
        result = await session.execute(
            select(CasbinRule).where(
                CasbinRule.ptype == "g",
                CasbinRule.v0 == f"user:{user.id}"
            )
        )
        user_g_rules = result.scalars().all()
        
        print(f"\n--- G-RULES FOR user:{user.id} (in database) ---")
        if not user_g_rules:
            print(f"  ⚠️ NO g-rules for user:{user.id}!")
            print(f"  This user relies on role:{user.role} policies directly")
        else:
            for rule in user_g_rules:
                print(f"  g: {rule.v0} → {rule.v1}")
        
        # 3. Check all g-rules (role inheritance)
        result = await session.execute(
            select(CasbinRule).where(CasbinRule.ptype == "g")
        )
        all_g_rules = result.scalars().all()
        
        print(f"\n--- ALL G-RULES (role inheritance) ---")
        for rule in all_g_rules:
            print(f"  g: {rule.v0} → {rule.v1}")
    
    # 4. Check enforcer
    if not hasattr(app.state, "enforcer"):
        print("\n❌ ENFORCER NOT FOUND IN app.state!")
        return
        
    enforcer = app.state.enforcer
    
    # 5. Get roles for user from enforcer
    subject = f"user:{user.id}"
    roles = await enforcer.get_roles_for_user(subject)
    print(f"\n--- ROLES FOR {subject} (from enforcer) ---")
    print(f"  Roles: {roles}")
    
    # 6. Check role inheritance for role:officer
    role_subject = f"role:{user.role}"
    role_roles = await enforcer.get_roles_for_user(role_subject)
    print(f"\n--- ROLE INHERITANCE FOR {role_subject} ---")
    print(f"  Inherits from: {role_roles}")
    
    # 7. Test enforcement with different subject formats
    test_path = "/api/admissions"
    test_action = "GET"
    
    print(f"\n--- ENFORCEMENT TESTS for {test_path} {test_action} ---")
    
    # Test 1: user:X format
    allowed_user = await enforcer.enforce(subject, test_path, test_action)
    print(f"  1. enforce('{subject}', '{test_path}', '{test_action}') = {allowed_user}")
    
    # Test 2: role:officer format
    allowed_role = await enforcer.enforce(role_subject, test_path, test_action)
    print(f"  2. enforce('{role_subject}', '{test_path}', '{test_action}') = {allowed_role}")
    
    # Test 3: just the role string
    allowed_role_raw = await enforcer.enforce(user.role, test_path, test_action)
    print(f"  3. enforce('{user.role}', '{test_path}', '{test_action}') = {allowed_role_raw}")
    
    # 8. Check p-rules for role:officer
    print(f"\n--- P-RULES FOR role:officer WITH /api/admissions ---")
    all_policies = enforcer.get_policy()
    officer_admission_policies = [p for p in all_policies if p[0] == "role:officer" and "admission" in p[1]]
    for p in officer_admission_policies:
        print(f"  p: {p}")
    
    # 9. Check if there's a model.conf issue
    print(f"\n--- CASBIN MODEL ---")
    model = enforcer.get_model()
    print(f"  Model sections: {model.model.keys()}")
    
    # Check what matchers are defined
    if 'm' in model.model:
        for key, val in model.model['m'].items():
            print(f"  Matcher [{key}]: {val.value}")
    
    # 10. Debug: Check what subject format the middleware uses
    print(f"\n--- EXPECTED SUBJECT FORMAT IN MIDDLEWARE ---")
    print(f"  Based on code: should be 'user:{{user.id}}' = '{subject}'")
    print(f"  Or maybe: 'role:{{user.role}}' = '{role_subject}'")
    
    print("\n" + "="*70)
    print("DEBUG: END")
    print("="*70 + "\n")


@pytest.mark.asyncio  
async def test_list_all_users_and_roles(client: AsyncClient):
    """List all users with their roles"""
    print("\n" + "="*70)
    print("ALL USERS IN DATABASE")
    print("="*70)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.User).order_by(models.User.id)
        )
        users = result.scalars().all()
        
        print(f"\n{'ID':<5} {'Username':<20} {'Role':<12} {'Status':<10} {'Unit':<6}")
        print("-" * 60)
        for user in users:
            print(f"{user.id:<5} {user.username:<20} {user.role:<12} {user.status:<10} {user.unit_id or 'N/A':<6}")
    
    print("\n" + "="*70 + "\n")
