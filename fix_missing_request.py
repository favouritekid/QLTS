#!/usr/bin/env python3
"""
Script to automatically add Request parameter to all rate-limited functions
"""
import re
from pathlib import Path

def fix_file(file_path):
    """Add Request parameter to functions missing it"""
    with open(file_path, 'r') as f:
        lines = f.readlines()

    modified = False
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this line has @limiter.limit
        if '@limiter.limit' in line:
            # Look ahead for the function definition
            j = i + 1
            while j < len(lines) and j < i + 10:
                if lines[j].strip().startswith('async def ') or lines[j].strip().startswith('def '):
                    # Found function definition
                    func_line = lines[j]

                    # Check if opening paren is on same line
                    if '(' in func_line:
                        # Get full parameter list (may span multiple lines)
                        param_start = j
                        param_end = j
                        paren_count = 0
                        started = False

                        for k in range(j, min(len(lines), j + 20)):
                            for char in lines[k]:
                                if char == '(':
                                    paren_count += 1
                                    started = True
                                elif char == ')':
                                    paren_count -= 1

                            if started and paren_count == 0:
                                param_end = k
                                break

                        # Reconstruct parameter lines to check
                        params_str = ''.join(lines[param_start:param_end+1])

                        # Check if request: Request is already there
                        has_request = (
                            'request: Request' in params_str or
                            'http_request: Request' in params_str
                        )

                        if not has_request:
                            # Need to add request: Request as first parameter
                            # Find the opening paren
                            if '(\n' in func_line or func_line.strip().endswith('('):
                                # Parameters on next line - add with proper indentation
                                # Check next line for indentation
                                next_line = lines[j + 1] if j + 1 < len(lines) else ''
                                indent = len(next_line) - len(next_line.lstrip())

                                # Check if function has no parameters (just closing paren)
                                if next_line.strip() == '):' or next_line.strip().startswith('):'):
                                    # No parameters, just add request before closing
                                    lines[j + 1] = ' ' * indent + 'request: Request,\n' + next_line
                                else:
                                    # Has parameters, add request as first
                                    lines.insert(j + 1, ' ' * indent + 'request: Request,\n')

                                modified = True
                            else:
                                # Parameters on same line
                                # Find position after opening paren
                                paren_pos = func_line.index('(')
                                before = func_line[:paren_pos + 1]
                                after = func_line[paren_pos + 1:]

                                # Check if there are already parameters
                                if after.strip().startswith(')'):
                                    # No parameters
                                    lines[j] = before + 'request: Request' + after
                                else:
                                    # Has parameters
                                    lines[j] = before + 'request: Request, ' + after

                                modified = True
                    break
                j += 1
        i += 1

    if modified:
        with open(file_path, 'w') as f:
            f.writelines(lines)
        return True
    return False

def main():
    backend_dir = Path('/home/user/QLTS/Backend_FastAPI/app/routers')

    files_modified = []

    # Fix all Python files
    for py_file in backend_dir.rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue

        if fix_file(py_file):
            files_modified.append(str(py_file))

    # Print results
    if files_modified:
        print(f"✅ Modified {len(files_modified)} files:")
        for file_path in sorted(files_modified):
            rel_path = file_path.replace('/home/user/QLTS/Backend_FastAPI/app/routers/', '')
            print(f"  - {rel_path}")
    else:
        print("✅ All files already have Request parameter!")

if __name__ == '__main__':
    main()
