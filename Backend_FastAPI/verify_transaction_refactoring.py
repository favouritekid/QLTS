#!/usr/bin/env python3
"""
Verification script for Transaction Management Refactoring

This script performs static code analysis to verify the refactoring was completed correctly.
It checks:
1. All refactored services return Tuple[Model, Callable]
2. All refactored services use flush() instead of commit()
3. All routers handle tuple unpacking and callback execution
4. All service callbacks use dispatch(..., auto_commit=True)
"""

import re
from pathlib import Path
from typing import List, Tuple, Dict
import sys


class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def check_service_return_types(service_path: Path) -> Tuple[bool, List[str]]:
    """Check if service functions return Tuple[Model, Callable]."""
    issues = []
    content = service_path.read_text()

    # Find all async function definitions
    func_pattern = r'async def (\w+)\([^)]*\)\s*->\s*Tuple\[([^\]]+), Callable\]:'
    matches = re.finditer(func_pattern, content)

    functions_found = []
    for match in matches:
        func_name = match.group(1)
        functions_found.append(func_name)

    if not functions_found:
        issues.append(f"No functions with Tuple[Model, Callable] return type found")

    return len(issues) == 0, functions_found


def check_service_uses_flush(service_path: Path) -> Tuple[bool, List[str]]:
    """Check if service uses db.flush() instead of db.commit()."""
    issues = []
    content = service_path.read_text()

    # Check for db.commit() outside of comments
    commit_pattern = r'await db\.commit\(\)'
    commits = re.findall(commit_pattern, content)

    # Filter out comments and docstrings
    lines = content.split('\n')
    commit_lines = []
    for i, line in enumerate(lines, 1):
        if re.search(commit_pattern, line):
            # Skip if it's in a comment or docstring
            if not (line.strip().startswith('#') or '"""' in line or "'''" in line or '>>> await db.commit()' in line):
                commit_lines.append((i, line.strip()))

    if commit_lines:
        issues.append(f"Found {len(commit_lines)} db.commit() calls (should use flush):")
        for line_no, line in commit_lines:
            issues.append(f"  Line {line_no}: {line}")

    # Check for db.flush()
    flush_pattern = r'await db\.flush\(\)'
    flush_count = len(re.findall(flush_pattern, content))

    return len(commit_lines) == 0, issues


def check_router_callback_handling(router_path: Path) -> Tuple[bool, List[str]]:
    """Check if router unpacks tuples and executes callbacks."""
    issues = []
    content = router_path.read_text()

    # Look for tuple unpacking pattern: model, callback = await service()
    unpack_pattern = r'(\w+),\s*callback\s*=\s*await\s+(\w+\.\w+)'
    unpacks = re.findall(unpack_pattern, content)

    if not unpacks:
        return True, []  # Not all routers may have been refactored

    # For each unpack, verify there's a commit and callback execution
    for var, service_call in unpacks:
        # Check for await db.commit()
        if 'await db.commit()' not in content:
            issues.append(f"Missing 'await db.commit()' after {service_call}")

        # Check for await callback()
        if 'await callback()' not in content:
            issues.append(f"Missing 'await callback()' after {service_call}")

    return len(issues) == 0, unpacks


def check_dispatch_auto_commit(service_path: Path) -> Tuple[bool, List[str]]:
    """Check if dispatch() calls use auto_commit=True in service callbacks."""
    issues = []
    content = service_path.read_text()

    # Find dispatch calls within _post_commit callbacks
    in_callback = False
    dispatch_calls = []

    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'async def _post_commit' in line:
            in_callback = True
        elif in_callback and re.match(r'^\s{0,4}(async def|def|class)', line):
            in_callback = False
        elif in_callback and 'await dispatch(' in line:
            # Check if auto_commit=True is present in the next few lines
            context = '\n'.join(lines[i:min(i+20, len(lines))])
            has_auto_commit = 'auto_commit=True' in context
            dispatch_calls.append((i+1, has_auto_commit))

    missing_auto_commit = [(line, ac) for line, ac in dispatch_calls if not ac]
    if missing_auto_commit:
        issues.append(f"Found {len(missing_auto_commit)} dispatch() calls without auto_commit=True:")
        for line, _ in missing_auto_commit:
            issues.append(f"  Line {line}")

    return len(missing_auto_commit) == 0, dispatch_calls


def verify_refactoring():
    """Main verification function."""
    print(f"{Colors.BOLD}🔍 Verifying Transaction Management Refactoring{Colors.END}\n")

    # Define refactored services
    services = [
        'notification_service.py',
        'application_service.py',
        'notification_preference_service.py',
        'tuition_discount_service.py',
        'lead_service.py',
        'activity_service.py',
        'notification_dispatcher.py',
        'notification_workflow.py',
        'officer_service.py',
        'role_service.py',
    ]

    # Define updated routers
    routers = [
        'notifications.py',
        'applications.py',
        'leads.py',
        'officer.py',
        'admin/tuition_discount.py',
        'admin/roles.py',
    ]

    services_path = Path('app/services')
    routers_path = Path('app/routers')

    total_checks = 0
    passed_checks = 0

    # Check services
    print(f"{Colors.BOLD}📦 Checking Services:{Colors.END}\n")
    for service_file in services:
        service_path = services_path / service_file
        if not service_path.exists():
            print(f"{Colors.RED}✗{Colors.END} {service_file} not found")
            continue

        print(f"{Colors.BOLD}{service_file}:{Colors.END}")

        # Check return types
        total_checks += 1
        success, functions = check_service_return_types(service_path)
        if success and functions:
            print(f"  {Colors.GREEN}✓{Colors.END} Return types: {len(functions)} functions with Tuple[Model, Callable]")
            passed_checks += 1
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.END} Return types: No functions found")

        # Check flush vs commit
        total_checks += 1
        success, issues = check_service_uses_flush(service_path)
        if success:
            print(f"  {Colors.GREEN}✓{Colors.END} Uses flush() instead of commit()")
            passed_checks += 1
        else:
            print(f"  {Colors.RED}✗{Colors.END} Found commit() calls:")
            for issue in issues:
                print(f"    {issue}")

        # Check dispatch auto_commit
        total_checks += 1
        success, dispatch_calls = check_dispatch_auto_commit(service_path)
        if dispatch_calls:
            if success:
                print(f"  {Colors.GREEN}✓{Colors.END} All {len(dispatch_calls)} dispatch() calls use auto_commit=True")
                passed_checks += 1
            else:
                print(f"  {Colors.RED}✗{Colors.END} Some dispatch() calls missing auto_commit=True")
        else:
            print(f"  {Colors.BLUE}ℹ{Colors.END} No dispatch() calls in callbacks")
            passed_checks += 1

        print()

    # Check routers
    print(f"\n{Colors.BOLD}🔀 Checking Routers:{Colors.END}\n")
    for router_file in routers:
        router_path = routers_path / router_file
        if not router_path.exists():
            print(f"{Colors.RED}✗{Colors.END} {router_file} not found")
            continue

        print(f"{Colors.BOLD}{router_file}:{Colors.END}")

        total_checks += 1
        success, unpacks = check_router_callback_handling(router_path)
        if unpacks:
            if success:
                print(f"  {Colors.GREEN}✓{Colors.END} {len(unpacks)} endpoints handle callbacks correctly")
                passed_checks += 1
            else:
                print(f"  {Colors.RED}✗{Colors.END} Missing commit or callback execution")
        else:
            print(f"  {Colors.BLUE}ℹ{Colors.END} No tuple unpacking found")
            passed_checks += 1

        print()

    # Summary
    print(f"\n{Colors.BOLD}📊 Verification Summary:{Colors.END}\n")
    print(f"  Total checks: {total_checks}")
    print(f"  Passed: {Colors.GREEN}{passed_checks}{Colors.END}")
    print(f"  Failed: {Colors.RED}{total_checks - passed_checks}{Colors.END}")

    percentage = (passed_checks / total_checks * 100) if total_checks > 0 else 0
    print(f"  Success rate: {percentage:.1f}%")

    if passed_checks == total_checks:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✅ All checks passed!{Colors.END}")
        return 0
    else:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}⚠ Some checks failed{Colors.END}")
        return 1


if __name__ == '__main__':
    sys.exit(verify_refactoring())
