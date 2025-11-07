#!/usr/bin/env python3
"""
🔍 Debug script - Kiểm tra settings được load từ file nào
"""

import os
import sys
from pathlib import Path

print("=" * 80)
print("🔍 DEBUG ENV LOADING")
print("=" * 80)

# Giả lập conftest.py
print("\n--- STEP 1: Before setting APP_ENV ---")
print(f"os.environ.get('APP_ENV') = {os.environ.get('APP_ENV')}")
print(f"os.environ.get('DATABASE_URL') = {os.environ.get('DATABASE_URL')}")

print("\n--- STEP 2: Set APP_ENV=test (like conftest.py) ---")
os.environ["APP_ENV"] = "test"
print(f"os.environ['APP_ENV'] = {os.environ['APP_ENV']}")
print(f"os.environ.get('DATABASE_URL') = {os.environ.get('DATABASE_URL')}")

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("\n--- STEP 3: Import config.py (will print debug messages) ---")
from app.config import settings

print("\n--- STEP 4: Check loaded settings ---")
print(f"settings.APP_ENV = {settings.APP_ENV}")
print(f"settings.DATABASE_URL = {settings.DATABASE_URL}")

print("\n--- STEP 5: Check which env file should be used ---")
from app.config import APP_ENV_FOR_CONFIG, _env_file, _env_file_path, _env_file_exists

print(f"APP_ENV_FOR_CONFIG = {APP_ENV_FOR_CONFIG}")
print(f"_env_file = {_env_file}")
print(f"_env_file_path = {_env_file_path}")
print(f"_env_file_exists = {_env_file_exists}")

print("\n--- STEP 6: Verify .env.test content ---")
env_test_path = project_root / ".env.test"
if env_test_path.exists():
    print(f"\n.env.test exists at: {env_test_path}")
    with open(env_test_path) as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#"):
                if "DATABASE_URL" in line:
                    print(f"  {line.strip()}")
else:
    print(f"\n❌ .env.test NOT FOUND at: {env_test_path}")

print("\n--- STEP 7: Verify .env content ---")
env_path = project_root / ".env"
if env_path.exists():
    print(f"\n.env exists at: {env_path}")
    with open(env_path) as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#"):
                if "DATABASE_URL" in line:
                    print(f"  {line.strip()}")
else:
    print(f"\n❌ .env NOT FOUND at: {env_path}")

print("\n" + "=" * 80)
print("🔍 ANALYSIS")
print("=" * 80)

db_url_lower = settings.DATABASE_URL.lower()
has_test = "test" in db_url_lower
has_qlts_dev = "/qlts_dev" in db_url_lower

print(f"\n✓ DATABASE_URL contains 'test': {has_test}")
print(f"✓ DATABASE_URL contains '/qlts_dev': {has_qlts_dev}")

if has_qlts_dev:
    print("\n❌ PROBLEM DETECTED!")
    print("   Settings loaded /qlts_dev database (from .env)")
    print("   NOT from .env.test as expected!")
    print("\n   Possible reasons:")
    print("   1. .env.test file doesn't exist or has wrong path")
    print("   2. config.py loaded before APP_ENV was set")
    print("   3. Pydantic-settings priority issue")
elif has_test:
    print("\n✅ CORRECT!")
    print("   Settings loaded test database from .env.test")
else:
    print("\n⚠️  UNEXPECTED!")
    print("   Database URL doesn't contain 'test' or '/qlts_dev'")

print("=" * 80)
