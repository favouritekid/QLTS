#!/usr/bin/env python3
"""
Script to find all rate-limited functions missing Request parameter
"""
import re
import os
from pathlib import Path

def check_file(file_path):
    """Check a Python file for rate limiter issues"""
    with open(file_path, 'r') as f:
        content = f.read()

    issues = []
    lines = content.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this line has @limiter.limit
        if '@limiter.limit' in line:
            # Look ahead for the function definition
            j = i + 1
            while j < len(lines) and j < i + 10:  # Look ahead max 10 lines
                if lines[j].strip().startswith('async def ') or lines[j].strip().startswith('def '):
                    # Found function definition
                    func_name_match = re.search(r'(async )?def (\w+)\(', lines[j])
                    if func_name_match:
                        func_name = func_name_match.group(2)

                        # Get function parameters (could span multiple lines)
                        param_lines = []
                        k = j
                        paren_count = 0
                        started = False
                        while k < len(lines) and k < j + 20:
                            param_line = lines[k]
                            for char in param_line:
                                if char == '(':
                                    paren_count += 1
                                    started = True
                                elif char == ')':
                                    paren_count -= 1

                            param_lines.append(param_line)

                            if started and paren_count == 0:
                                break
                            k += 1

                        params_str = '\n'.join(param_lines)

                        # Check if request: Request is in parameters
                        has_request = (
                            'request: Request' in params_str or
                            'http_request: Request' in params_str
                        )

                        if not has_request:
                            issues.append({
                                'file': str(file_path),
                                'line': j + 1,
                                'function': func_name,
                                'limiter_line': i + 1
                            })
                    break
                j += 1
        i += 1

    return issues

def main():
    backend_dir = Path('/home/user/QLTS/Backend_FastAPI/app/routers')

    all_issues = []

    # Check all Python files
    for py_file in backend_dir.rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue

        issues = check_file(py_file)
        all_issues.extend(issues)

    # Print results
    if all_issues:
        print(f"Found {len(all_issues)} functions with @limiter.limit missing Request parameter:\n")
        for issue in all_issues:
            rel_path = issue['file'].replace('/home/user/QLTS/Backend_FastAPI/app/routers/', '')
            print(f"{rel_path}:{issue['line']}")
            print(f"  Function: {issue['function']}")
            print(f"  Rate limiter on line: {issue['limiter_line']}")
            print()
    else:
        print("✅ All rate-limited functions have Request parameter!")

if __name__ == '__main__':
    main()
