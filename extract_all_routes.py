#!/usr/bin/env python3
"""
Extract all API routes from FastAPI backend including main.py router inclusions.
"""
import re
from pathlib import Path
from typing import List, Dict, Set

def extract_routes_from_router_file(file_path: str, router_name: str = "router") -> tuple:
    """
    Extract routes and router prefix from a Python router file.
    Returns: (prefix, routes_list)
    """
    routes = []

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')

    # Find router prefix
    router_prefix = ""
    # Pattern: router = APIRouter(prefix="/something"
    prefix_patterns = [
        rf'{router_name}\s*=\s*APIRouter\s*\(\s*prefix\s*=\s*["\']([^"\']+)["\']',
        rf'APIRouter\s*\(\s*prefix\s*=\s*["\']([^"\']+)["\']',
    ]

    for pattern in prefix_patterns:
        prefix_match = re.search(pattern, content)
        if prefix_match:
            router_prefix = prefix_match.group(1)
            break

    # Find all route decorators
    for i, line in enumerate(lines):
        # Match @router.get, @router.post, etc.
        # Handle both: @router.get("/path") and @router.get("")
        route_match = re.match(rf'@{router_name}\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']*)["\']', line)
        if route_match:
            method = route_match.group(1).upper()
            path = route_match.group(2)  # Can be empty string ""

            # Get function name
            func_name = ""
            for j in range(i + 1, min(i + 5, len(lines))):
                func_match = re.match(r'(?:async\s+)?def\s+(\w+)', lines[j])
                if func_match:
                    func_name = func_match.group(1)
                    break

            routes.append({
                'method': method,
                'path': path,
                'prefix': router_prefix,
                'function': func_name,
                'file': file_path,
            })

    return router_prefix, routes

def extract_router_inclusions_from_main() -> Dict[str, str]:
    """
    Extract router inclusions from main.py.
    Returns: dict mapping router_name -> api_prefix
    """
    main_file = '/home/user/QLTS/Backend_FastAPI/app/main.py'
    inclusions = {}

    with open(main_file, 'r') as f:
        content = f.read()

    # Pattern: app.include_router(some_router, prefix="/api/something")
    # or: app.include_router(some_router.router, prefix="/api")
    pattern = r'app\.include_router\s*\(\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*,\s*prefix\s*=\s*["\']([^"\']+)["\']'

    for match in re.finditer(pattern, content):
        router_ref = match.group(1)
        api_prefix = match.group(2)

        # Extract router name (e.g., "leads" from "leads.router" or "admin_router" from "admin_router")
        if '.' in router_ref:
            router_name = router_ref.split('.')[0]
        else:
            router_name = router_ref.replace('_router', '')

        inclusions[router_name] = api_prefix

    return inclusions

def main():
    backend_path = Path('/home/user/QLTS/Backend_FastAPI/app')

    # Get all router files (auto-discover)
    router_files = {}

    # Top-level routers
    for file in (backend_path / 'routers').glob('*.py'):
        if file.name != '__init__.py':
            name = file.stem
            router_files[name] = file

    # Admin sub-routers
    admin_path = backend_path / 'routers' / 'admin'
    if admin_path.exists():
        router_files['admin'] = admin_path / '__init__.py'
        for file in admin_path.glob('*.py'):
            if file.name != '__init__.py':
                name = f"admin_{file.stem}"
                router_files[name] = file

    # Get router inclusions from main.py
    main_inclusions = extract_router_inclusions_from_main()
    print("Router inclusions from main.py:")
    for router, prefix in sorted(main_inclusions.items()):
        print(f"  {router:30} -> {prefix}")
    print()

    # Extract all routes
    all_endpoints = set()

    for name, filepath in router_files.items():
        if not filepath.exists():
            continue

        router_prefix, routes = extract_routes_from_router_file(str(filepath))

        # Determine main.py prefix
        main_prefix = main_inclusions.get(name, '')

        # Special handling for admin routers
        if 'admin' in str(filepath) and name != 'admin':
            # Sub-routers under admin are included by admin/__init__.py
            # which is then included at /api
            main_prefix = '/api'

        for route in routes:
            # Build full path: main_prefix + router_prefix + route_path
            full_path = ""

            if main_prefix:
                full_path = main_prefix

            if router_prefix and router_prefix != main_prefix:
                full_path += router_prefix

            if route['path']:
                if not route['path'].startswith('/'):
                    full_path += '/'
                full_path += route['path']

            endpoint = f"{route['method']:7} {full_path}"
            all_endpoints.add(endpoint)

    # Print all endpoints
    print("=" * 80)
    print("ALL BACKEND API ENDPOINTS")
    print("=" * 80)
    print(f"\nTotal: {len(all_endpoints)} endpoints")
    print()

    for endpoint in sorted(all_endpoints):
        print(endpoint)

    # Save to file
    with open('/home/user/QLTS/backend_routes_complete.txt', 'w') as f:
        for endpoint in sorted(all_endpoints):
            f.write(endpoint + '\n')

    print()
    print("=" * 80)
    print(f"Saved to: /home/user/QLTS/backend_routes_complete.txt")
    print("=" * 80)

if __name__ == '__main__':
    main()
