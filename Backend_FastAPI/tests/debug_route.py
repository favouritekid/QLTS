
# tests/debug_route.py
import pytest
from app.main import fastapi_app

def test_print_routes():
    print("\n=== REGISTERED ROUTES ===")
    found = False
    for route in fastapi_app.routes:
        if hasattr(route, "path") and "offering-types" in route.path:
            print(f"FOUND: {route.path} [{route.methods}]")
            found = True
    
    if not found:
        print("❌ Route /api/admin/offering-types NOT FOUND in fastapi_app.routes")
    else:
        print("✅ Route found!")
