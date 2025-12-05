#!/usr/bin/env python3
"""Check all router files have Request imported if they use request: Request parameter"""
from pathlib import Path
import re

def check_file(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    # Check if file uses request: Request parameter
    has_request_param = 'request: Request' in content or 'http_request: Request' in content

    if not has_request_param:
        return None

    # Check if Request is imported from fastapi
    has_import = re.search(r'from fastapi import.*\bRequest\b', content)

    if not has_import:
        return file_path

    return None

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
