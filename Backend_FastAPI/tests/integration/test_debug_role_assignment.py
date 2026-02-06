# tests/integration/test_debug_role_assignment.py
"""
Debug test to check how user role is mapped to Casbin subject.

This test verifies:
1. User's role from database (users table)
2. Corresponding g-rule in casbin_rule table (user -> role mapping)
3. Whether the user can access /api/admissions based on their role
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from app.database import AsyncSessionLocal
from app.main import fastapi_app as app
from app import models
from casbin_async_sqlalchemy_adapter.adapter import CasbinRule


@pytest.mark.asyncio
async def test_debug_user_role_and_casbin_mapping(
    client: AsyncClient,
):
    """
    Debug test to inspect user role and Casbin mapping.
    """
    print("\n" + "="*60)
    print("DEBUG: USER ROLE AND CASBIN MAPPING")
    print("="*60)
    
    async with AsyncSessionLocal() as session:
        # 1. Get all users and their roles
        result = await session.execute(
            select(models.User.id, models.User.username, models.User.role)
        )
        users = result.all()
        
        print("\n--- USERS TABLE (role column) ---")
        for user_id, username, role in users:
            print(f"  User ID={user_id}, username={username}, role={role}")
        
        # 2. Get all g-rules (user -> role mapping)
        result = await session.execute(
            select(CasbinRule).where(CasbinRule.ptype == "g")
        )
        g_rules = result.scalars().all()
        
        print("\n--- CASBIN G-RULES (user -> role mapping) ---")
        if not g_rules:
            print("  ⚠️  NO G-RULES FOUND! Users are not mapped to roles in Casbin!")
        else:
            for rule in g_rules:
                print(f"  g: {rule.v0} → {rule.v1}")
        
        # 3. Get p-rules for admission access
        result = await session.execute(
            select(CasbinRule).where(
                CasbinRule.ptype == "p",
                CasbinRule.v1.like("%admission%")
            )
        )
        p_rules = result.scalars().all()
        
        print("\n--- ADMISSION P-RULES ---")
        for rule in p_rules:
            print(f"  p: {rule.v0}, {rule.v1}, {rule.v2}")
    
    # 4. Check enforcer state
    if hasattr(app.state, "enforcer"):
        enforcer = app.state.enforcer
        
        print("\n--- ENFORCER G-RULES (in memory) ---")
        g_policies = enforcer.get_grouping_policy()
        if not g_policies:
            print("  ⚠️  NO G-RULES IN ENFORCER!")
        else:
            for g in g_policies:
                print(f"  g: {g}")
        
        # 5. Test permission for specific user
        # Find vothuhien user
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.User).where(models.User.username == "vothuhien")
            )
            user = result.scalar_one_or_none()
            
            if user:
                subject = f"user:{user.id}"
                role_subject = f"role:{user.role}"
                
                print(f"\n--- PERMISSION CHECK FOR vothuhien ---")
                print(f"  User ID: {user.id}")
                print(f"  Username: {user.username}")
                print(f"  Role (from DB): {user.role}")
                print(f"  Casbin subject: {subject}")
                print(f"  Casbin role subject: {role_subject}")
                
                # Check if user has any roles in enforcer
                roles = await enforcer.get_roles_for_user(subject)
                print(f"  Roles for {subject} (from enforcer): {roles}")
                
                # Test direct permission check
                allowed = await enforcer.enforce(subject, "/api/admissions", "GET")
                print(f"  ✅ Direct check: {subject} -> /api/admissions GET = {allowed}")
                
                # Test role-based permission check
                allowed_role = await enforcer.enforce(role_subject, "/api/admissions", "GET")
                print(f"  🔹 Role check: {role_subject} -> /api/admissions GET = {allowed_role}")
                
                # Check which roles have this permission
                print("\n--- ROLES WITH /api/admissions GET PERMISSION ---")
                all_policies = enforcer.get_policy()
                for p in all_policies:
                    if "/api/admissions" in p[1] and "GET" in p[2]:
                        print(f"  ✓ {p[0]} has permission")

    print("\n" + "="*60)
    print("DEBUG: END")
    print("="*60 + "\n")
