#!/usr/bin/env python3
"""Add GET /api/admissions policy for officer and manager."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import casbin
from casbin_async_sqlalchemy_adapter import Adapter
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings

async def add_list_policy():
    engine = create_async_engine(settings.DATABASE_URL)
    adapter = Adapter(engine)
    enforcer = casbin.AsyncEnforcer("auth_model.conf", adapter)
    await enforcer.load_policy()
    
    policies = [
        ("role:officer", "/api/admissions", "GET"),
        ("role:manager", "/api/admissions", "GET"),
    ]
    
    for p in policies:
        if not enforcer.has_policy(*p):
            await enforcer.add_policy(*p)
            print(f"Added: {p}")
        else:
            print(f"Exists: {p}")
    
    await enforcer.save_policy()
    await engine.dispose()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(add_list_policy())
