"""
Phase 1 Verification Script
Test imports and router registration for Admission Configuration Console
"""
import sys
sys.path.insert(0, '.')

print("=" * 60)
print("PHASE 1 VERIFICATION")
print("=" * 60)

# 1. Test Repository import
print("\n📋 1. REPOSITORY")
try:
    from app.repositories.admission_path_repository import AdmissionPathRepository
    print("  ✅ AdmissionPathRepository imported")
except Exception as e:
    print(f"  ❌ Error: {e}")

# 2. Test Schemas import
print("\n📋 2. SCHEMAS")
try:
    from app.schemas.admission_path import (
        AdmissionPathResponse,
        AdmissionPathCreate,
        AdmissionPathUpdate,
        ResolvedDocumentResponse,
        AcademicYearListResponse,
    )
    print("  ✅ All schemas imported:")
    print("    - AdmissionPathResponse")
    print("    - AdmissionPathCreate")
    print("    - AdmissionPathUpdate")
    print("    - ResolvedDocumentResponse")
    print("    - AcademicYearListResponse")
except Exception as e:
    print(f"  ❌ Error: {e}")

# 3. Test Service import
print("\n📋 3. SERVICE")
try:
    from app.services.admission_path_service import AdmissionPathService
    print("  ✅ AdmissionPathService imported")
except Exception as e:
    print(f"  ❌ Error: {e}")

# 4. Test Router import
print("\n📋 4. ROUTER")
try:
    from app.routers.admission_paths import router
    print("  ✅ Router imported")
    print()
    print("  Router endpoints:")
    for route in router.routes:
        methods = list(route.methods) if hasattr(route, 'methods') else ['?']
        print(f"    {methods[0]:6} {route.path}")
except Exception as e:
    print(f"  ❌ Error: {e}")

# 5. Test main.py integration
print("\n📋 5. MAIN.PY INTEGRATION")
try:
    # This will fail if there are import errors
    from app.main import fastapi_app
    
    # Find our router
    our_routes = [r for r in fastapi_app.routes if hasattr(r, 'path') and 'admission-config' in r.path]
    print(f"  ✅ FastAPI app loaded successfully")
    print(f"  ✅ Found {len(our_routes)} admission-config routes")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print("VERIFICATION COMPLETE")
print("=" * 60)
