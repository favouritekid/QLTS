#!/usr/bin/env python3
"""
Restore Casbin Rules from Policy Templates.

This script recreates ALL casbin rules for system roles from policy_templates.py
after the casbin_rule table was accidentally dropped.

Usage:
    cd Backend_FastAPI
    python scripts/maintenance/restore_casbin_rules.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import casbin
from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.casbin_config.policy_templates import (
    apply_template,
    POLICY_TEMPLATES,
)


# Roles to restore with their templates
ROLE_TEMPLATE_MAPPING = {
    "role:officer": "officer",
    "role:manager": "manager",
    "role:admin": "admin",
}


async def restore_casbin_rules():
    """Restore all casbin rules from templates."""
    
    print("=" * 60)
    print("🔄 RESTORING CASBIN RULES FROM TEMPLATES")
    print("=" * 60)
    
    print("\n🔧 Connecting to database...")
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
    current_policies = enforcer.get_policy()
    print(f"\n📊 Current policies count: {len(current_policies)}")

    total_added = 0
    total_skipped = 0

    # Apply templates for each role
    for role, template_id in ROLE_TEMPLATE_MAPPING.items():
        print(f"\n{'='*50}")
        print(f"📋 Applying template '{template_id}' to role '{role}'")
        print(f"{'='*50}")
        
        try:
            policies = apply_template(template_id, role)
            print(f"   Template contains {len(policies)} policies")
            
            added = 0
            skipped = 0
            
            for policy in policies:
                rule = (policy["subject"], policy["object"], policy["action"])
                
                if enforcer.has_policy(*rule):
                    skipped += 1
                else:
                    success = await enforcer.add_policy(*rule)
                    if success:
                        print(f"   ✅ Added: {rule[0]} | {rule[1]} | {rule[2]}")
                        added += 1
                    else:
                        print(f"   ❌ Failed: {rule[0]} | {rule[1]} | {rule[2]}")
            
            print(f"\n   📈 Added: {added}, Skipped: {skipped}")
            total_added += added
            total_skipped += skipped
            
        except KeyError:
            print(f"   ⚠️ Template '{template_id}' not found!")

    # Save all policies
    if total_added > 0:
        print(f"\n💾 Saving {total_added} new policies to database...")
        await enforcer.save_policy()
        print("✅ Policies saved successfully!")
    else:
        print("\n✨ No new policies to add!")

    # Show final count
    final_policies = enforcer.get_policy()
    print(f"\n{'='*60}")
    print(f"📊 SUMMARY")
    print(f"{'='*60}")
    print(f"   Before: {len(current_policies)}")
    print(f"   Added: {total_added}")
    print(f"   Skipped: {total_skipped}")
    print(f"   After: {len(final_policies)}")
    
    # List all roles with policy counts
    print(f"\n📋 Policies per role:")
    for role in ROLE_TEMPLATE_MAPPING.keys():
        role_policies = [p for p in final_policies if p[0] == role]
        print(f"   {role}: {len(role_policies)} policies")

    # Cleanup
    await engine.dispose()
    print(f"\n{'='*60}")
    print("✅ CASBIN RULES RESTORED SUCCESSFULLY!")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(restore_casbin_rules())
