#!/usr/bin/env python3
"""
Compare frontend API calls with backend routes to find mismatches.
"""
import re
from pathlib import Path
from typing import Set, Dict, List, Tuple

def normalize_path(path: str) -> str:
    """Normalize path by replacing dynamic segments with a common placeholder."""
    # Replace {anything} with {id}
    normalized = re.sub(r'\{[^}]+\}', '{id}', path)
    # Replace numeric IDs with {id}
    normalized = re.sub(r'/\d+/', '/{id}/', normalized)
    # Replace ${ template literals with {id}
    normalized = re.sub(r'\$\{[^}]+\}', '{id}', normalized)
    return normalized

def load_backend_routes() -> Dict[str, Set[str]]:
    """Load backend routes from the extraction."""
    routes_by_method = {}

    # Read from backend extraction
    with open('/home/user/QLTS/backend_routes.txt', 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue

            method, path = parts
            path_norm = normalize_path(path)

            if method not in routes_by_method:
                routes_by_method[method] = set()
            routes_by_method[method].add(path_norm)

    return routes_by_method

def load_frontend_calls() -> Dict[str, List[Tuple[str, List[str]]]]:
    """Load frontend API calls with their source locations."""
    calls_by_method = {}

    with open('/home/user/QLTS/frontend_api_calls_clean.txt', 'r') as f:
        current_endpoint = None
        current_locations = []

        for line in f:
            line = line.rstrip()

            # Check if this is an endpoint line (METHOD  /api/...)
            if line and not line.startswith(' '):
                # Save previous endpoint
                if current_endpoint:
                    method, path = current_endpoint.split(maxsplit=1)
                    if method not in calls_by_method:
                        calls_by_method[method] = []
                    calls_by_method[method].append((path, current_locations))

                # Start new endpoint
                current_endpoint = line
                current_locations = []

            # Check if this is a location line
            elif line.strip().startswith('•'):
                location = line.strip().lstrip('• ')
                current_locations.append(location)

        # Don't forget the last endpoint
        if current_endpoint:
            method, path = current_endpoint.split(maxsplit=1)
            if method not in calls_by_method:
                calls_by_method[method] = []
            calls_by_method[method].append((path, current_locations))

    return calls_by_method

def find_mismatches():
    """Find mismatches between frontend calls and backend routes."""
    backend = load_backend_routes()
    frontend = load_frontend_calls()

    print("=" * 80)
    print("ROUTE MISMATCH ANALYSIS REPORT")
    print("=" * 80)
    print()

    # Summary
    backend_total = sum(len(routes) for routes in backend.values())
    frontend_total = sum(len(calls) for calls in frontend.values())

    print(f"Backend routes:  {backend_total}")
    print(f"Frontend calls:  {frontend_total}")
    print()

    # Find mismatches
    mismatches = []
    matched = []
    backend_only = []

    # Check each frontend call against backend
    for method in sorted(frontend.keys()):
        for path, locations in frontend[method]:
            path_norm = normalize_path(path)
            backend_routes = backend.get(method, set())

            if path_norm not in backend_routes:
                mismatches.append({
                    'method': method,
                    'path': path,
                    'path_norm': path_norm,
                    'locations': locations,
                    'type': 'FRONTEND_ONLY'
                })
            else:
                matched.append({
                    'method': method,
                    'path': path,
                })

    # Find backend routes not called by frontend
    for method in sorted(backend.keys()):
        for route in backend[method]:
            # Check if any frontend call matches this
            found = False
            if method in frontend:
                for path, _ in frontend[method]:
                    if normalize_path(path) == route:
                        found = True
                        break

            if not found:
                backend_only.append({
                    'method': method,
                    'path': route,
                })

    # Print results
    print("=" * 80)
    print("CRITICAL ISSUES: Frontend calls non-existent backend routes")
    print("=" * 80)
    print()

    if mismatches:
        print(f"Found {len(mismatches)} CRITICAL mismatch(es):")
        print()
        for mismatch in sorted(mismatches, key=lambda x: (x['method'], x['path'])):
            print(f"❌ {mismatch['method']:7} {mismatch['path']}")
            print(f"   Frontend expects this endpoint but backend doesn't provide it!")
            print(f"   Called from:")
            for loc in mismatch['locations']:
                print(f"     • {loc}")
            print()
    else:
        print("✅ No critical mismatches! All frontend calls have matching backend routes.")
        print()

    print("=" * 80)
    print("WARNINGS: Backend routes not used by frontend")
    print("=" * 80)
    print()

    if backend_only:
        print(f"Found {len(backend_only)} unused backend route(s):")
        print("(These may be OK if used by mobile app, API clients, or planned features)")
        print()
        for route in sorted(backend_only, key=lambda x: (x['method'], x['path']))[:20]:
            print(f"⚠️  {route['method']:7} {route['path']}")
        if len(backend_only) > 20:
            print(f"   ... and {len(backend_only) - 20} more")
        print()
    else:
        print("✅ All backend routes are used by frontend.")
        print()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print(f"✅ Matched routes:        {len(matched)}")
    print(f"❌ Frontend-only calls:   {len(mismatches)} (CRITICAL)")
    print(f"⚠️  Backend-only routes:  {len(backend_only)} (Warning)")
    print()

    if mismatches:
        print("🔧 ACTION REQUIRED:")
        print("   Fix frontend calls to match backend endpoints or add missing backend routes.")
        print()

    # Save detailed report
    with open('/home/user/QLTS/route_mismatch_report.txt', 'w') as f:
        f.write("ROUTE MISMATCH REPORT\n")
        f.write("=" * 80 + "\n\n")

        f.write("CRITICAL: Frontend calls non-existent routes\n")
        f.write("-" * 80 + "\n")
        for mismatch in sorted(mismatches, key=lambda x: (x['method'], x['path'])):
            f.write(f"\n{mismatch['method']} {mismatch['path']}\n")
            f.write(f"  Normalized: {mismatch['path_norm']}\n")
            for loc in mismatch['locations']:
                f.write(f"  • {loc}\n")

        f.write("\n\nWARNING: Backend routes not called by frontend\n")
        f.write("-" * 80 + "\n")
        for route in sorted(backend_only, key=lambda x: (x['method'], x['path'])):
            f.write(f"{route['method']} {route['path']}\n")

    print(f"📄 Detailed report saved to: /home/user/QLTS/route_mismatch_report.txt")
    print()

if __name__ == '__main__':
    find_mismatches()
