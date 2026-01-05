#!/usr/bin/env python3
"""Quick import check for auth.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.routers.auth import router
    print("✅ auth.py imports OK")
except Exception as e:
    print(f"❌ auth.py import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
