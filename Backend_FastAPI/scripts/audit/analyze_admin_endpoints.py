#!/usr/bin/env python3
"""Analyze admin.py endpoints and categorize them."""

import re
from collections import defaultdict

# Read admin.py
with open('app/routers/admin.py', 'r') as f:
    content = f.read()

# Extract all function names (excluding helper functions)
functions = re.findall(r'^async def (\w+)\(', content, re.MULTILINE)

# Categorize by keywords
categories = defaultdict(list)

for func in functions:
    func_lower = func.lower()

    # Skip helper functions
    if func == 'log_admin_activity':
        continue

    # Categorize
    if any(kw in func_lower for kw in ['policy', 'policies', 'role', 'grouping', 'permission', 'simulate']):
        categories['Policy/Role Management'].append(func)
    elif any(kw in func_lower for kw in ['user', 'sync_users']):
        categories['User Management'].append(func)
    elif any(kw in func_lower for kw in ['organization', 'program', 'offering']) and 'academic' not in func_lower and 'type' not in func_lower:
        categories['Organization Management'].append(func)
    elif any(kw in func_lower for kw in ['pipeline', 'consultation', 'transition', 'revert']):
        categories['Pipeline/Workflow Management'].append(func)
    elif any(kw in func_lower for kw in ['assignment', 'skill', 'distribution']):
        categories['Assignment/Distribution Config'].append(func)
    elif any(kw in func_lower for kw in ['degree', 'offering_type', 'academic']):
        categories['Academic Configuration'].append(func)
    elif any(kw in func_lower for kw in ['lead', 'bulk_assign']):
        categories['Lead Management'].append(func)
    elif any(kw in func_lower for kw in ['activity', 'statistic', 'who_can']):
        categories['Monitoring/Analytics'].append(func)
    else:
        categories['Other'].append(func)

# Print results
total = 0
print("=" * 80)
print("ADMIN.PY ENDPOINT CATEGORIZATION")
print("=" * 80)
print()

for category in sorted(categories.keys()):
    funcs = categories[category]
    print(f"\n{category} ({len(funcs)} endpoints):")
    print("-" * 80)
    for i, func in enumerate(funcs, 1):
        print(f"  {i:2d}. {func}")
    total += len(funcs)

print()
print("=" * 80)
print(f"TOTAL ENDPOINTS: {total}")
print("=" * 80)
print()

# Print proposed split structure
print("\n" + "=" * 80)
print("PROPOSED ROUTER SPLIT STRUCTURE")
print("=" * 80)
print()

proposed_split = {
    "users.py": ["User Management", "Monitoring/Analytics (user stats only)"],
    "roles.py": ["Policy/Role Management"],
    "organization.py": ["Organization Management"],
    "config.py": ["Assignment/Distribution Config", "Academic Configuration"],
    "pipeline.py": ["Pipeline/Workflow Management"],
    "leads.py": ["Lead Management (if needed)"]
}

for router_file, included_categories in proposed_split.items():
    endpoint_count = sum(len(categories.get(cat, [])) for cat in included_categories)
    print(f"\napp/routers/admin/{router_file} (~{endpoint_count} endpoints)")
    for cat in included_categories:
        if cat in categories:
            print(f"  - {cat}: {len(categories[cat])} endpoints")
