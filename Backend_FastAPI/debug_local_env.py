#!/usr/bin/env python3
"""
🔍 DEBUG SCRIPT - Chạy trên máy LOCAL của bạn
Sao chép output và gửi cho tôi để debug
"""

import os
import sys
from pathlib import Path

print("=" * 80)
print("🔍 DEBUG LOCAL ENV LOADING")
print("=" * 80)

# Add project root
project_root = Path(__file__).parent
print(f"\n📁 Project root: {project_root}")

# Check files
print("\n--- FILES CHECK ---")
env_path = project_root / ".env"
env_test_path = project_root / ".env.test"

print(f"✓ .env exists: {env_path.exists()}")
print(f"✓ .env.test exists: {env_test_path.exists()}")

# Read .env
if env_path.exists():
    print(f"\n📄 Content of .env:")
    with open(env_path) as f:
        for i, line in enumerate(f, 1):
            if "DATABASE_URL" in line and not line.strip().startswith("#"):
                print(f"  Line {i}: {line.rstrip()}")
else:
    print("\n⚠️  .env NOT FOUND!")

# Read .env.test
if env_test_path.exists():
    print(f"\n📄 Content of .env.test:")
    with open(env_test_path) as f:
        for i, line in enumerate(f, 1):
            if "DATABASE_URL" in line and not line.strip().startswith("#"):
                print(f"  Line {i}: {line.rstrip()}")
else:
    print("\n⚠️  .env.test NOT FOUND!")

# Simulate conftest.py
print("\n--- SIMULATE conftest.py ---")
print("Setting os.environ['APP_ENV'] = 'test'")
os.environ["APP_ENV"] = "test"

# Import config
sys.path.insert(0, str(project_root))
print("Importing app.config...")

from app.config import settings, APP_ENV_FOR_CONFIG, _env_file, _env_file_path

print(f"\n✓ APP_ENV_FOR_CONFIG = {APP_ENV_FOR_CONFIG}")
print(f"✓ _env_file = {_env_file}")
print(f"✓ _env_file_path = {_env_file_path}")

# Check settings
print("\n--- LOADED SETTINGS ---")
print(f"✓ settings.APP_ENV = {settings.APP_ENV}")
print(f"✓ settings.DATABASE_URL = {settings.DATABASE_URL}")

# Analysis
print("\n--- ANALYSIS ---")
db_url_lower = settings.DATABASE_URL.lower()

print(f"\n📊 Checks:")
print(f"  • Contains 'test': {'test' in db_url_lower}")
print(f"  • Contains '/qlts_dev': {'/qlts_dev' in db_url_lower}")
print(f"  • Contains '/qlts_prod': {'/qlts_prod' in db_url_lower}")
print(f"  • Contains ':memory:': {':memory:' in db_url_lower}")

# Safety check simulation
dangerous_patterns = ["/qlts_dev", "/qlts_prod", "/qlts_production", "/qlts/", "/qlts ", "/production", "/prod/", "/main/"]
detected = [p for p in dangerous_patterns if p in db_url_lower]

if detected:
    print(f"\n❌ DANGEROUS PATTERNS DETECTED: {detected}")
else:
    print(f"\n✅ NO DANGEROUS PATTERNS")

# Final verdict
has_test = "test" in db_url_lower
is_dangerous = len(detected) > 0

print("\n--- VERDICT ---")
if is_dangerous and not has_test:
    print("❌ SAFETY CHECK WOULD FAIL!")
    print(f"   Reason: Dangerous pattern found AND no 'test' in URL")
elif not has_test and not ":memory:" in db_url_lower:
    print("❌ SAFETY CHECK WOULD FAIL!")
    print(f"   Reason: No 'test' in URL and not in-memory")
else:
    print("✅ SAFETY CHECK WOULD PASS!")

print("\n" + "=" * 80)
print("📋 Gửi toàn bộ output này cho tôi để debug!")
print("=" * 80)
