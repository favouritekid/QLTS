#!/usr/bin/env python3
"""Automatically add Request to fastapi imports in router files"""
from pathlib import Path
import re

def fix_file(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    # Check if file uses request: Request parameter
    has_request_param = 'request: Request' in content or 'http_request: Request' in content

    if not has_request_param:
        return False

    # Check if Request is already imported
    if re.search(r'from fastapi import.*\bRequest\b', content):
        return False

    # Find the fastapi import line and add Request
    def add_request_to_import(match):
        import_line = match.group(0)

        # Check if it's a multi-line import
        if '(' in import_line:
            # Multi-line import: add Request before closing paren
            return import_line.replace(')', ', Request)')
        else:
            # Single-line import: add Request to the list
            # Find position before 'status' or at the end
            if ', status' in import_line:
                return import_line.replace(', status', ', Request, status')
            elif ' status' in import_line:
                return import_line.replace(' status', ' Request, status')
            else:
                # Add at the end before the newline
                return import_line.rstrip() + ', Request'

    # Pattern to match: from fastapi import ... (single or multi-line)
    pattern = r'from fastapi import[^;]*?(?=\n(?![ \t])|\nfrom|\nimport)'

    new_content = re.sub(pattern, add_request_to_import, content, count=1)

    if new_content != content:
        with open(file_path, 'w') as f:
            f.write(new_content)
        return True

    return False

def main():
    backend_dir = Path('/home/user/QLTS/Backend_FastAPI/app/routers')

    fixed_files = []

    for py_file in backend_dir.rglob('*.py'):
        if '__pycache__' in str(py_file) or '__init__' in str(py_file):
            continue

        if fix_file(py_file):
            fixed_files.append(str(py_file))

    if fixed_files:
        print(f"✅ Fixed {len(fixed_files)} files:")
        for file in sorted(fixed_files):
            rel_path = file.replace('/home/user/QLTS/Backend_FastAPI/app/routers/', '')
            print(f"  - {rel_path}")
    else:
        print("✅ No files needed fixing!")

if __name__ == '__main__':
    main()
