#!/usr/bin/env python3
"""
Phase 1 Verification Script
Checks that dual detection merge is working correctly.
"""
import sys
import os

# Fix PYTHONPATH - add project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

def main():
    errors = []
    
    # Test 1: Auth router imports correctly (no AnomalyDetector dependency)
    print("Test 1: Checking auth.py imports...")
    try:
        from app.routers.auth import router
        print("  ✅ auth.py imports OK")
    except ImportError as e:
        errors.append(f"auth.py import failed: {e}")
        print(f"  ❌ auth.py import failed: {e}")
    
    # Test 2: login_history_service has email params
    print("\nTest 2: Checking record_login signature...")
    try:
        from app.services import login_history_service
        import inspect
        sig = inspect.signature(login_history_service.record_login)
        params = list(sig.parameters.keys())
        
        if "email_to" in params and "username" in params:
            print("  ✅ record_login has email_to and username params")
        else:
            errors.append(f"record_login missing params. Has: {params}")
            print(f"  ❌ record_login missing email_to/username. Has: {params}")
    except Exception as e:
        errors.append(f"record_login check failed: {e}")
        print(f"  ❌ record_login check failed: {e}")
    
    # Test 3: AnomalyDetector is NOT used in auth.py
    print("\nTest 3: Checking AnomalyDetector is not used in auth.py...")
    try:
        import ast
        with open("app/routers/auth.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        if "AnomalyDetector(db)" in content:
            errors.append("AnomalyDetector(db) still found in auth.py")
            print("  ❌ AnomalyDetector(db) still instantiated in auth.py")
        else:
            print("  ✅ AnomalyDetector not instantiated in auth.py")
            
        # Check import is commented out
        if "from ..services.anomaly_detection import AnomalyDetector" in content:
            errors.append("AnomalyDetector import still active in auth.py")
            print("  ❌ AnomalyDetector import still active")
        else:
            print("  ✅ AnomalyDetector import removed/commented")
    except Exception as e:
        errors.append(f"AnomalyDetector check failed: {e}")
        print(f"  ❌ AnomalyDetector check failed: {e}")
    
    # Test 4: Email task import in login_history_service
    print("\nTest 4: Checking email task integration...")
    try:
        with open("app/services/login_history_service.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        if "send_login_alert_email_task" in content:
            print("  ✅ send_login_alert_email_task found in login_history_service")
        else:
            errors.append("send_login_alert_email_task not found in login_history_service")
            print("  ❌ send_login_alert_email_task not found in login_history_service")
    except Exception as e:
        errors.append(f"Email task check failed: {e}")
        print(f"  ❌ Email task check failed: {e}")
    
    # Summary
    print("\n" + "="*50)
    if errors:
        print(f"❌ VERIFICATION FAILED - {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1
    else:
        print("✅ PHASE 1 VERIFICATION PASSED")
        return 0

if __name__ == "__main__":
    sys.exit(main())
