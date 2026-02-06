#!/usr/bin/env python3
"""
MIGRATION SCRIPT: Sync Casbin Templates to DB Policies
======================================================

This script refreshes role policies from their templates.
Use this when you modify `policy_templates.py` and need to apply 
changes to the live database.

Usage:
    cd Backend_FastAPI
    python scripts/sync_casbin_templates.py
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

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import casbin
import casbin_async_sqlalchemy_adapter

from app.services.casbin_service import CasbinPolicyService

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sync_templates")

async def sync_templates():
    print("="*70)
    print("STARTING SYNC: Casbin Templates -> DB Policies")
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
        service = CasbinPolicyService(session, enforcer)
        
        # 2. Sync Officer Role
        print("Syncing 'officer' role...")
        result = await service.refresh_role_from_template(
            role="role:officer",
            template_id="officer", 
            force=True, # Required to overwrite existing policies
            applied_by=1 # System/Admin ID
        )
        
        if result.get("success") is False:
             print(f"❌ Failed to sync officer: {result.get('error')}")
        else:
             print(f"✅ Officer role synced: {result.get('added')} added, {result.get('removed')} removed.")

        # You can add other roles here if needed
        # await service.refresh_role_from_template("role:manager", "manager", force=True)

    print("-" * 70)
    print(f"SYNC COMPLETE.")
    print("="*70)
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(sync_templates())
