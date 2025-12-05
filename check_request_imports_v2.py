#!/usr/bin/env python3
"""Check all router files have Request imported - handles multi-line imports"""
from pathlib import Path
import re

def check_file(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    # Check if file uses request: Request parameter
    has_request_param = 'request: Request' in content or 'http_request: Request' in content

    if not has_request_param:
        return None

    # Check if Request is imported from fastapi (handle both single-line and multi-line)
    # Pattern 1: Single line import
    if re.search(r'from fastapi import[^\n]*\bRequest\b', content):
        return None

    # Pattern 2: Multi-line import
    fastapi_import_match = re.search(
        r'from fastapi import\s*\(([^)]+)\)',
        content,
        re.DOTALL
    )

    if fastapi_import_match:
        import_list = fastapi_import_match.group(1)
        if re.search(r'\bRequest\b', import_list):
            return None

    # If we get here, Request is missing
    return file_path

def main():
    backend_dir = Path('/home/user/QLTS/Backend_FastAPI/app/routers')

    missing_imports = []

    for py_file in backend_dir.rglob('*.py'):
        if '__pycache__' in str(py_file) or '__init__' in str(py_file):
            continue

        result = check_file(py_file)
        if result:
            missing_imports.append(str(result))

    if missing_imports:
        print(f"❌ Found {len(missing_imports)} files missing Request import:\n")
        for file in sorted(missing_imports):
            rel_path = file.replace('/home/user/QLTS/Backend_FastAPI/app/routers/', '')
            print(f"  - {rel_path}")
    else:
        print("✅ All files with request: Request parameter have proper imports!")

if __name__ == '__main__':
    main()
