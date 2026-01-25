#!/usr/bin/env python3
"""Test script for workflow-context API endpoint"""
import sys
sys.path.insert(0, '/mnt/d/QLTS/Backend_FastAPI')

import asyncio
from app.routers.leads import router

# Check if the endpoint is registered
print("=" * 60)
print("WORKFLOW CONTEXT API ENDPOINT CHECK")
print("=" * 60)

print("\n1. Checking registered routes in leads router:")
found_workflow = False
for route in router.routes:
    if hasattr(route, 'path'):
        if 'workflow-context' in route.path:
            found_workflow = True
            print(f"   ✅ FOUND: {route.methods} {route.path}")
            print(f"      Response model: {getattr(route, 'response_model', 'N/A')}")
            print(f"      Name: {route.name}")

if not found_workflow:
    print("   ❌ NOT FOUND: workflow-context endpoint")
    print("\n   All registered paths:")
    for route in router.routes:
        if hasattr(route, 'path'):
            print(f"      {route.path}")

print("\n2. Checking schema imports:")
try:
    from app.schemas.lead import WorkflowContext, WorkflowAllowedStatus
    print("   ✅ WorkflowContext schema imported successfully")
    print("   ✅ WorkflowAllowedStatus schema imported successfully")
    
    # Show schema fields
    print("\n   WorkflowContext fields:")
    for name, field in WorkflowContext.model_fields.items():
        print(f"      - {name}: {field.annotation}")
except Exception as e:
    print(f"   ❌ Import error: {e}")

print("\n" + "=" * 60)
print("API ENDPOINT CHECK COMPLETE")
print("=" * 60)
