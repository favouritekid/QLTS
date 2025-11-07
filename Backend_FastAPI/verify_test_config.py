#!/usr/bin/env python3
"""
🔍 Script kiểm tra cấu hình test
Chạy script này TRƯỚC KHI chạy pytest để đảm bảo cấu hình đúng
"""

import os
import sys
from pathlib import Path

# Set APP_ENV to test (giống như conftest.py)
os.environ["APP_ENV"] = "test"

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import settings
from app.config import settings

print("=" * 60)
print("🔍 KIỂM TRA CẤU HÌNH TEST")
print("=" * 60)

# Check 1: APP_ENV
print(f"\n✓ APP_ENV: {settings.APP_ENV}")
if settings.APP_ENV != "test":
    print(f"  ❌ CẢNH BÁO: APP_ENV phải là 'test', hiện tại là '{settings.APP_ENV}'")
    sys.exit(1)
else:
    print("  ✅ OK: APP_ENV = 'test'")

# Check 2: DATABASE_URL
print(f"\n✓ DATABASE_URL: {settings.DATABASE_URL}")

db_url_lower = settings.DATABASE_URL.lower()
is_memory = ":memory:" in db_url_lower
has_test = "test" in db_url_lower

dangerous_patterns = ["/qlts_dev", "/qlts_prod", "/qlts_production"]
is_dangerous = any(pattern in db_url_lower for pattern in dangerous_patterns)

if is_dangerous:
    print(f"  ❌ NGUY HIỂM: Database URL chứa pattern nguy hiểm!")
    print(f"     Patterns phát hiện: {[p for p in dangerous_patterns if p in db_url_lower]}")
    sys.exit(1)

if not (is_memory or has_test):
    print(f"  ❌ CẢNH BÁO: Database URL KHÔNG chứa ':memory:' hoặc 'test'")
    print(f"     Tests sẽ bị chặn bởi safety check!")
    sys.exit(1)

if is_memory:
    print("  ✅ OK: Sử dụng in-memory database (an toàn)")
elif has_test:
    print("  ✅ OK: Database name chứa 'test' (an toàn)")

# Check 3: Redis
print(f"\n✓ REDIS_URL: {settings.REDIS_URL}")
if "6379/11" in settings.REDIS_URL or "6379/12" in settings.REDIS_URL or "6379/13" in settings.REDIS_URL:
    print("  ✅ OK: Sử dụng Redis DB numbers riêng cho test")
else:
    print("  ⚠️  CẢNH BÁO: Redis DB number không phải 11-13, có thể conflict với dev")

# Check 4: Secret keys
print(f"\n✓ SECRET_KEY: {settings.SECRET_KEY[:20]}...")
if "test" in settings.SECRET_KEY.lower():
    print("  ✅ OK: Sử dụng test secret key")
else:
    print("  ⚠️  CẢNH BÁO: Secret key không chứa 'test', có thể là production key")

# Check 5: Mail server
print(f"\n✓ MAIL_SERVER: {settings.MAIL_SERVER}")
if settings.MAIL_SERVER == "localhost" or "mailtrap" in settings.MAIL_SERVER:
    print("  ✅ OK: Sử dụng test mail server")
else:
    print("  ⚠️  CẢNH BÁO: Mail server có thể là production server")

print("\n" + "=" * 60)
print("✅ TẤT CẢ KIỂM TRA THÀNH CÔNG")
print("=" * 60)
print("\n🚀 Bạn có thể chạy tests an toàn:")
print("   cd Backend_FastAPI")
print("   pytest tests/ -v")
print("\n📝 Lưu ý:")
print("   - Tests sẽ XÓA TẤT CẢ TABLES trong database test")
print("   - Database production của bạn sẽ KHÔNG bị ảnh hưởng")
print("   - Mỗi test function sẽ có database sạch (fresh)")
print("=" * 60)
