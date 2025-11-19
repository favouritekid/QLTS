#!/bin/bash

cd /home/user/QLTS/frontend/src

echo "Scanning frontend API calls..."
echo ""

# Extract all api.METHOD calls
grep -rn "api\.\(get\|post\|put\|delete\|patch\)" \
  --include="*.ts" --include="*.tsx" \
  . > /tmp/api_calls.txt

echo "Total lines with API calls: $(wc -l < /tmp/api_calls.txt)"
echo ""
echo "Extracting unique endpoints..."
echo ""

# Parse and extract endpoints
python3 << 'PYEOF'
import re
from collections import defaultdict

calls_by_endpoint = defaultdict(list)

with open('/tmp/api_calls.txt', 'r') as f:
    for line in f:
        # Extract file:line
        match = re.match(r'([^:]+):(\d+):', line)
        if not match:
            continue

        file_path = match.group(1)
        line_num = match.group(2)

        # Extract method and URL
        # Patterns: api.get('/api/...') or api.get(`/api/...`)
        patterns = [
            r"api\.(get|post|put|patch|delete)\s*\(\s*['\"`]([^'\"` ]+)",
            r"api\.(get|post|put|patch|delete)<[^>]+>\s*\(\s*['\"`]([^'\"` ]+)",
        ]

        for pattern in patterns:
            api_match = re.search(pattern, line, re.IGNORECASE)
            if api_match:
                method = api_match.group(1).upper()
                url = api_match.group(2)

                # Normalize URLs with variables
                url_norm = re.sub(r'\$\{[^}]+\}', '{id}', url)
                url_norm = re.sub(r'/\d+/', '/{id}/', url_norm)

                endpoint = f"{method:7} {url_norm}"
                calls_by_endpoint[endpoint].append(f"{file_path}:{line_num}")
                break

# Sort and display
print("=" * 80)
print("FRONTEND API ENDPOINTS")
print("=" * 80)
print()

for endpoint in sorted(calls_by_endpoint.keys()):
    locations = calls_by_endpoint[endpoint]
    print(f"{endpoint}")
    print(f"  Called from {len(locations)} location(s):")
    for loc in locations[:3]:
        print(f"    • {loc}")
    if len(locations) > 3:
        print(f"    ... and {len(locations) - 3} more")
    print()

# Save to file
with open('/home/user/QLTS/frontend_api_calls_clean.txt', 'w') as f:
    for endpoint in sorted(calls_by_endpoint.keys()):
        f.write(f"{endpoint}\n")
        for loc in calls_by_endpoint[endpoint]:
            f.write(f"  {loc}\n")

print("=" * 80)
print(f"Total unique endpoints: {len(calls_by_endpoint)}")
print(f"Saved to: /home/user/QLTS/frontend_api_calls_clean.txt")
print("=" * 80)
PYEOF
