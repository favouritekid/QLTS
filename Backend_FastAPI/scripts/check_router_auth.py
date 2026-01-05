#!/usr/bin/env python3
"""
CI Script: Check all router endpoints have authorization.

This script scans all router files and verifies that each endpoint has
proper authorization via dependency injection.

Rules:
- Each async def endpoint in router MUST have one of:
  - CasbinAuth
  - require_admin
  - require_admin_or_manager
  - require_any_staff
  - require_roles
  - get_current_active_user (for special cases)
  - A get_*_for_user dependency (includes auth)

Exceptions:
- Files in WHITELIST_FILES (auth.py, monitoring.py)
- Functions in WHITELIST_FUNCTIONS (login, register, health, etc.)

Usage:
    python scripts/check_router_auth.py

Exit codes:
    0 - All checks passed
    1 - Authorization issues found

Reference: AUTHORIZATION_GUIDELINES.md v1.0
"""

import re
import sys
from pathlib import Path
from typing import List, Set, Tuple

# ============================================================
# CONFIGURATION
# ============================================================

# Files that don't require authorization (public endpoints)
WHITELIST_FILES: Set[str] = {
    "auth.py",           # Login, register, refresh - public
    "monitoring.py",     # Health checks - public
    "__init__.py",       # Package init files

    # TODO: Review these - currently read-only config endpoints
    # Decision needed: Should these require authentication?
    # See: AUTHORIZATION_DECISIONS.md for decision tracking
    "admission_config.py",  # Read-only admission config data
}

# Functions that don't require authorization
WHITELIST_FUNCTIONS: Set[str] = {
    # Auth flows (must be public)
    "login",
    "register",
    "refresh_token",
    "forgot_password",
    "reset_password",
    "verify_email",
    "resend_verification",

    # Health checks (must be public)
    "health",
    "health_check",
    "health_detailed",
    "readiness",
    "liveness",

    # Metrics (usually public or protected at infra level)
    "metrics",
    "prometheus_metrics",

    # WebSocket handlers (auth handled differently)
    "websocket_endpoint",
    "socket_handler",
}

# Patterns that indicate authorization is present
AUTH_PATTERNS: List[str] = [
    # Casbin-based (dynamic)
    r"CasbinAuth",
    r"check_permission",

    # Role-based (static)
    r"require_admin",
    r"require_admin_or_manager",
    r"require_any_staff",
    r"require_roles",

    # Alias dependencies (commonly used in project)
    r"AdminDep",
    r"AdminOrManagerDep",
    r"StaffDep",

    # User-based (authentication)
    r"get_current_active_user",
    r"get_current_user",

    # IDOR dependencies (include auth)
    r"get_lead_for_user",
    r"get_application_for_user",
    r"get_notification_for_user",
    r"get_consultation_for_user",
    r"get_document_for_user",
    r"get_kpi_target_for_user",
    r"get_kpi_target_for_admin",
    r"get_notification_template_for_admin",
    r"get_notification_rule_for_admin",
    r"get_officer_dashboard_scope",
    r"get_distribution_rule_for_user",
    r"get_organizational_unit_for_user",
    r"verify_user_management_permission",
    r"LeadAccessDep",

    # Generic pattern for future IDOR deps
    r"get_\w+_for_user",
    r"get_\w+_for_admin",
]

# Router decorator patterns
ROUTER_DECORATOR_PATTERN = re.compile(
    r'@(?:router|app)\.(get|post|put|patch|delete|options|head)\s*\('
)

# Function definition pattern
FUNC_DEF_PATTERN = re.compile(
    r'async\s+def\s+(\w+)\s*\('
)


# ============================================================
# ANALYSIS FUNCTIONS
# ============================================================

def find_endpoints(content: str) -> List[Tuple[str, int, int]]:
    """
    Find all endpoint functions in a router file.

    Returns list of (function_name, decorator_start, func_start)
    """
    endpoints = []
    lines = content.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this line has a router decorator
        if ROUTER_DECORATOR_PATTERN.search(line):
            decorator_line = i

            # Find the function definition (may be on next lines)
            j = i + 1
            while j < len(lines) and j < i + 10:  # Look up to 10 lines ahead
                func_match = FUNC_DEF_PATTERN.search(lines[j])
                if func_match:
                    func_name = func_match.group(1)
                    endpoints.append((func_name, decorator_line, j))
                    i = j  # Skip to function line
                    break
                j += 1

        i += 1

    return endpoints


def has_authorization(content: str, func_start: int, func_end: int) -> bool:
    """
    Check if a function has authorization dependency.

    Looks at the function signature and body for auth patterns.
    """
    lines = content.split('\n')

    # Get function signature and first part of body
    # Typically auth deps are in the signature
    search_start = max(0, func_start - 5)  # Include decorators
    search_end = min(len(lines), func_end + 30)  # Include some body

    context = '\n'.join(lines[search_start:search_end])

    # Check for any auth pattern
    for pattern in AUTH_PATTERNS:
        if re.search(pattern, context):
            return True

    return False


def find_function_end(content: str, func_start: int) -> int:
    """
    Find the end line of a function (approximate).

    Uses indentation to detect function boundary.
    """
    lines = content.split('\n')

    if func_start >= len(lines):
        return func_start

    # Get base indentation of function def
    func_line = lines[func_start]
    base_indent = len(func_line) - len(func_line.lstrip())

    # Find where indentation returns to base or less
    for i in range(func_start + 1, len(lines)):
        line = lines[i]

        # Skip empty lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        current_indent = len(line) - len(line.lstrip())

        # If we're back at base indent or less, function ended
        if current_indent <= base_indent and stripped:
            return i - 1

    return len(lines) - 1


def check_file(filepath: Path) -> List[str]:
    """
    Check a single router file for authorization issues.

    Returns list of error messages.
    """
    errors = []

    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        return [f"{filepath}: Could not read file: {e}"]

    # Find all endpoints
    endpoints = find_endpoints(content)

    for func_name, decorator_line, func_start in endpoints:
        # Skip whitelisted functions
        if func_name in WHITELIST_FUNCTIONS:
            continue

        # Find function end
        func_end = find_function_end(content, func_start)

        # Check for authorization
        if not has_authorization(content, func_start, func_end):
            line_num = func_start + 1  # 1-indexed for display
            errors.append(
                f"{filepath}:{line_num} - {func_name}() missing authorization dependency"
            )

    return errors


def check_all_routers(router_dir: Path) -> Tuple[List[str], int, int]:
    """
    Check all router files in directory.

    Returns (errors, files_checked, endpoints_checked)
    """
    errors = []
    files_checked = 0
    endpoints_checked = 0

    if not router_dir.exists():
        return [f"Router directory not found: {router_dir}"], 0, 0

    for filepath in router_dir.rglob("*.py"):
        # Skip whitelisted files
        if filepath.name in WHITELIST_FILES:
            continue

        # Skip test files
        if 'test' in filepath.name.lower():
            continue

        files_checked += 1

        # Count endpoints
        try:
            content = filepath.read_text(encoding='utf-8')
            endpoints = find_endpoints(content)
            endpoints_checked += len(endpoints)
        except:
            pass

        # Check file
        file_errors = check_file(filepath)
        errors.extend(file_errors)

    return errors, files_checked, endpoints_checked


# ============================================================
# MAIN
# ============================================================

def main():
    """Main entry point."""
    print("=" * 60)
    print("AUTHORIZATION COVERAGE CHECK")
    print("=" * 60)
    print()

    # Find router directory
    # Try multiple possible locations
    possible_paths = [
        Path("app/routers"),
        Path("Backend_FastAPI/app/routers"),
        Path("../app/routers"),
    ]

    router_dir = None
    for path in possible_paths:
        if path.exists():
            router_dir = path
            break

    if router_dir is None:
        print("ERROR: Could not find app/routers directory")
        print("Searched paths:", [str(p) for p in possible_paths])
        sys.exit(1)

    print(f"Scanning: {router_dir.absolute()}")
    print()

    # Run checks
    errors, files_checked, endpoints_checked = check_all_routers(router_dir)

    # Report results
    print(f"Files checked: {files_checked}")
    print(f"Endpoints found: {endpoints_checked}")
    print()

    if errors:
        print("=" * 60)
        print(f"FAILED: {len(errors)} authorization issue(s) found")
        print("=" * 60)
        print()

        for error in errors:
            print(f"  {error}")

        print()
        print("FIX: Add authorization dependency to each endpoint:")
        print("  - CasbinAuth (for dynamic RBAC)")
        print("  - require_admin (for admin-only static check)")
        print("  - require_admin_or_manager (for admin/manager)")
        print("  - get_{resource}_for_user (for IDOR protection)")
        print()
        print("Reference: AUTHORIZATION_GUIDELINES.md")
        print()

        sys.exit(1)
    else:
        print("=" * 60)
        print("PASSED: All endpoints have authorization")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()
