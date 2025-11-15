#!/usr/bin/env python3
"""
CRITICAL FIX: Auto-patch outcome_type enum conversion
Run this script to automatically fix the enum conversion bug.

Usage:
    python fix_enum_conversion.py /path/to/Backend_FastAPI

Example:
    python fix_enum_conversion.py /mnt/d/QLTS/Backend_FastAPI
    python fix_enum_conversion.py ./Backend_FastAPI
"""

import sys
import os
import re
from pathlib import Path

# The fix code to inject
FIX_CODE = '''        # ✅ CRITICAL FIX: Convert enum to lowercase
        create_data = status_in.model_dump(mode='python')

        # Force outcome_type to lowercase
        if "outcome_type" in create_data:
            val = create_data["outcome_type"]
            log.debug(
                "Converting outcome_type",
                original_value=val,
                original_type=type(val).__name__
            )

            if isinstance(val, models.OutcomeTypeEnum):
                create_data["outcome_type"] = val.value.lower()
            elif isinstance(val, str):
                create_data["outcome_type"] = val.lower()
            elif hasattr(val, 'value'):
                create_data["outcome_type"] = str(val.value).lower()
            else:
                create_data["outcome_type"] = str(val).lower()

            log.debug(
                "Converted outcome_type",
                converted_value=create_data["outcome_type"]
            )
'''

def find_backend_directory():
    """Try to find Backend_FastAPI directory."""
    possible_paths = [
        Path.cwd() / "Backend_FastAPI",
        Path.home() / "QLTS" / "Backend_FastAPI",
        Path("/mnt/d/QLTS/Backend_FastAPI"),
        Path("/mnt/c/QLTS/Backend_FastAPI"),
    ]

    for path in possible_paths:
        if path.exists() and (path / "app" / "services" / "pipeline_service.py").exists():
            return path

    return None

def apply_fix(backend_path):
    """Apply the enum conversion fix to pipeline_service.py"""

    service_file = backend_path / "app" / "services" / "pipeline_service.py"

    if not service_file.exists():
        print(f"❌ ERROR: File not found: {service_file}")
        return False

    print(f"📁 Found: {service_file}")

    # Read current content
    with open(service_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Backup original file
    backup_file = service_file.with_suffix('.py.backup')
    with open(backup_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"💾 Backup created: {backup_file}")

    # Check if already fixed
    if "CRITICAL FIX: Convert enum to lowercase" in content:
        print("✅ File already contains the fix!")
        print("   If still getting errors, restart backend server.")
        return True

    # Pattern to find the section to replace
    # Look for: create_data = status_in.model_dump()
    pattern = r'(\s+)# 3\. Kiểm tra Stage cha\s+await _get_stage_by_id\(\s+db, status_in\.stage_id\s+\).*?\n\s+# 4\. Tạo.*?\n\s+create_data = status_in\.model_dump\(\)'

    if not re.search(pattern, content, re.DOTALL):
        print("❌ ERROR: Could not find the code pattern to replace.")
        print("   Your file structure might be different.")
        print("   Please apply fix manually using CRITICAL_FIX_outcome_type.patch")
        return False

    # Replace with fix
    replacement = r'\1# 3. Kiểm tra Stage cha\n\1await _get_stage_by_id(\n\1    db, status_in.stage_id\n\1)\n\n' + FIX_CODE.replace('\n', '\n' + r'\1')

    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    if new_content == content:
        print("⚠️  WARNING: Content unchanged after replacement.")
        print("   Trying alternative pattern...")

        # Alternative: Just find model_dump() and replace
        alt_pattern = r'(\s+)create_data = status_in\.model_dump\(\)'
        if re.search(alt_pattern, content):
            new_content = re.sub(
                alt_pattern,
                FIX_CODE.rstrip(),
                content,
                count=1
            )
        else:
            print("❌ ERROR: Alternative pattern also failed.")
            return False

    # Write fixed content
    with open(service_file, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print("✅ Fix applied successfully!")
    print("\n📋 Next steps:")
    print("   1. Restart backend server")
    print("   2. Test creating consultation status")
    print("   3. Check logs for: [debug] Converting outcome_type")
    print("\n💡 If errors persist:")
    print("   - Make sure you restarted the RIGHT backend process")
    print("   - Check backend is running from this directory")
    print(f"   - Verify: ps aux | grep uvicorn")

    return True

def main():
    print("🔧 CRITICAL FIX: outcome_type Enum Conversion")
    print("=" * 60)

    # Get backend path from argument or auto-detect
    if len(sys.argv) > 1:
        backend_path = Path(sys.argv[1])
    else:
        print("🔍 Auto-detecting backend directory...")
        backend_path = find_backend_directory()

    if not backend_path:
        print("❌ ERROR: Could not find Backend_FastAPI directory!")
        print("\nUsage:")
        print("   python fix_enum_conversion.py /path/to/Backend_FastAPI")
        print("\nExample:")
        print("   python fix_enum_conversion.py /mnt/d/QLTS/Backend_FastAPI")
        sys.exit(1)

    print(f"📂 Backend directory: {backend_path}")

    if not backend_path.exists():
        print(f"❌ ERROR: Directory does not exist: {backend_path}")
        sys.exit(1)

    # Apply the fix
    success = apply_fix(backend_path)

    if success:
        print("\n✅ SUCCESS! Fix applied.")
        sys.exit(0)
    else:
        print("\n❌ FAILED to apply fix automatically.")
        print("   Please apply manually using CRITICAL_FIX_outcome_type.patch")
        sys.exit(1)

if __name__ == "__main__":
    main()
