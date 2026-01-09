#!/usr/bin/env python3
"""
MIGRATION SCRIPT: Sync DB Roles to Casbin G-Rules
=================================================

This script iterates through all users in the database and ensures 
that a corresponding g-rule exists in Casbin.

Why is this needed?
-------------------
Previously, the system relied solely on DB roles. We introduced logic to 
sync DB roles to Casbin g-rules (user:ID -> role:NAME) in `user_service.py`.
However, existing users created before this change do not have these g-rules.

This script "backfills" those missing rules to ensure 100% consistency.

Usage:
    cd Backend_FastAPI
    python scripts/sync_db_roles_to_casbin.py
"""
import asyncio
import os
import sys
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env file
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import casbin
import casbin_async_sqlalchemy_adapter

from app import models
# from app.core import config  <-- Removed to fix ImportError

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sync_roles")

async def sync_roles():
    print("="*70)
    print("STARTING SYNC: DB Roles -> Casbin G-Rules")
    print("="*70)

    # 1. Setup Database & Enforcer
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("❌ Error: DATABASE_URL not set in environment")
        return

    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # Initialize Casbin Adapter
    adapter = casbin_async_sqlalchemy_adapter.Adapter(DATABASE_URL)
    enforcer = casbin.AsyncEnforcer(
        "auth_model.conf", 
        adapter
    )
    await enforcer.load_policy()
    
    async with async_session() as session:
        # 2. Get all users
        result = await session.execute(select(models.User))
        users = result.scalars().all()
        
        print(f"Found {len(users)} users in database.")
        
        synced_count = 0
        skipped_count = 0
        
        for user in users:
            # We want to sync ALL roles (admin, manager, officer, user)
            # strictly speaking 'user' role is default so g-rule might be optional,
            # but for consistency let's explicit sync everything if it's not 'user' 
            # OR we can sync everything. Let's sync everything except maybe 'user' 
            # if we want to keep table small, but let's be explicit for now.
            
            # Actually, let's sync non-default roles (admin, manager, officer).
            # 'user' is the fallback in our logic usually, but having the g-rule doesn't hurt.
            
            if user.role == "user":
                # Optional: Skip 'user' role to keep Casbin table smaller 
                # strictly speaking user:X inherits nothing special unless we define it.
                # But let's sync ALL to be 100% safe.
                pass 

            user_subject = f"user:{user.id}"
            role_subject = f"role:{user.role}"
            
            # Check if exists
            has_policy = enforcer.has_grouping_policy(user_subject, role_subject)
            
            if not has_policy:
                # Remove any OLD g-rules for this user first (cleanup)
                # e.g. if they had role:user but now role:officer
                # Get all roles for user
                current_casbin_roles = await enforcer.get_roles_for_user(user_subject)
                for old_role in current_casbin_roles:
                    await enforcer.remove_grouping_policy(user_subject, old_role)
                    print(f"  - Removed old g-rule: {user_subject} -> {old_role}")

                # Add new policy
                await enforcer.add_grouping_policy(user_subject, role_subject)
                print(f"  ✅ Synced: {user.username:<20} ({user_subject}) -> {role_subject}")
                synced_count += 1
            else:
                # print(f"  . Skipped: {user.username:<20} (Already consistent)")
                skipped_count += 1
                
    print("-" * 70)
    print(f"SYNC COMPLETE.")
    print(f"  Allowed (Already consistent): {skipped_count}")
    print(f"  Synced (New/Updated):       {synced_count}")
    print("="*70)
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(sync_roles())
