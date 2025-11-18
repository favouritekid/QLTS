#!/usr/bin/env python3
"""
Extract all API routes from FastAPI backend.
"""
import re
import os
from pathlib import Path
from typing import List, Tuple, Dict

def extract_routes_from_file(file_path: str) -> List[Dict]:
    """Extract route definitions from a Python router file."""
    routes = []

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')

    # Find router prefix
    router_prefix = ""
    prefix_match = re.search(r'APIRouter\(prefix=["\']([^"\']+)["\']', content)
    if prefix_match:
        router_prefix = prefix_match.group(1)

    # Find all route decorators
    for i, line in enumerate(lines):
        # Match @router.get, @router.post, etc.
        route_match = re.match(r'@router\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']\)', line)
        if route_match:
            method = route_match.group(1).upper()
            path = route_match.group(2)

            # Get function name (next non-empty, non-decorator line)
            func_name = ""
            for j in range(i + 1, min(i + 5, len(lines))):
                func_match = re.match(r'(?:async\s+)?def\s+(\w+)', lines[j])
                if func_match:
                    func_name = func_match.group(1)
                    break

            # Get docstring if available
            doc = ""
            for j in range(i + 1, min(i + 10, len(lines))):
                if '"""' in lines[j]:
                    doc_start = j
                    for k in range(j, min(j + 5, len(lines))):
                        if lines[k].count('"""') == 2 or (k > j and '"""' in lines[k]):
                            doc = ' '.join(lines[doc_start:k+1])
                            doc = re.sub(r'"""', '', doc).strip()
                            doc = re.sub(r'\s+', ' ', doc)[:100]
                            break
                    break

            routes.append({
                'method': method,
                'path': path,
                'prefix': router_prefix,
                'full_path': router_prefix + path if not path.startswith('/') else path,
                'function': func_name,
                'file': file_path,
                'doc': doc
            })

    return routes

def main():
    backend_path = Path('/home/user/QLTS/Backend_FastAPI/app')

    # Find all router files
    router_files = []
    for root, dirs, files in os.walk(backend_path / 'routers'):
        for file in files:
            if file.endswith('.py') and not file.startswith('__'):
                router_files.append(os.path.join(root, file))

    # Also check main.py for direct routes
    if (backend_path / 'main.py').exists():
        router_files.append(str(backend_path / 'main.py'))

    all_routes = []
    for router_file in sorted(router_files):
        routes = extract_routes_from_file(router_file)
        all_routes.extend(routes)

    # Group by category
    print("=" * 80)
    print("BACKEND API ROUTES INVENTORY")
    print("=" * 80)
    print(f"\nTotal routes found: {len(all_routes)}")
    print()

    # Group by prefix
    by_prefix = {}
    for route in all_routes:
        prefix = route['prefix'] or '/'
        if prefix not in by_prefix:
            by_prefix[prefix] = []
        by_prefix[prefix].append(route)

    for prefix in sorted(by_prefix.keys()):
        routes = by_prefix[prefix]
        print(f"\n{'=' * 80}")
        print(f"PREFIX: {prefix}")
        print(f"Routes: {len(routes)}")
        print('=' * 80)

        # Group by method
        by_method = {}
        for route in routes:
            method = route['method']
            if method not in by_method:
                by_method[method] = []
            by_method[method].append(route)

        for method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']:
            if method not in by_method:
                continue

            print(f"\n  {method}:")
            for route in sorted(by_method[method], key=lambda x: x['path']):
                full_path = route['full_path']
                # Handle main router inclusion
                if '/admin' in route['file'] and not full_path.startswith('/api'):
                    full_path = '/api' + full_path
                print(f"    {full_path:60} -> {route['function']}")
                if route['doc']:
                    print(f"        {route['doc'][:70]}...")

    # Write to file for comparison
    with open('/home/user/QLTS/backend_routes.txt', 'w') as f:
        for route in sorted(all_routes, key=lambda x: (x['prefix'], x['method'], x['path'])):
            full_path = route['full_path']
            if '/admin' in route['file'] and not full_path.startswith('/api'):
                full_path = '/api' + full_path
            f.write(f"{route['method']:7} {full_path}\n")

    print("\n" + "=" * 80)
    print(f"Routes saved to: /home/user/QLTS/backend_routes.txt")
    print("=" * 80)

if __name__ == '__main__':
    main()
