#!/usr/bin/env python3
import sys
import requests

if len(sys.argv) < 2:
    print("Usage: python debug_profile.py <profile_id>")
    sys.exit(1)

profile_id = sys.argv[1]

# Call debug endpoint (assume backend is running)
try:
    # Try without auth first (modify endpoint to allow it temporarily)
    resp = requests.get(f"http://localhost:8000/api/admissions/{profile_id}/debug/validation")
    if resp.status_code == 401:
        print("Endpoint requires auth. Modify endpoint or provide token.")
        sys.exit(1)
    resp.raise_for_status()
    data = resp.json()
except Exception as e:
    print(f"Error: {e}")
    print("\nMake sure backend is running: uvicorn app.main:app --reload")
    sys.exit(1)

# Print results
print("\n=== VALIDATION ERRORS ===")
for err in data["validation_summary"]["validation_errors"]:
    print(f"  - {err}")

print("\n=== PERSONAL FIELDS ===")
for name, field in data["personal_fields"].items():
    empty = "EMPTY" if field["is_empty"] else "OK"
    print(f"  {empty:5s} {name:20s} = {repr(field['value'])}")

print("\n=== DOCUMENTS ===")
docs = data["documents"]["by_status"]
print(f"  Total: {data['documents']['total_count']}")
for status, count in docs.items():
    print(f"  {status}: {count}")

print("\n=== SCORES ===")
s = data["scores"]
print(f"  Total: {s.get('total_score')}, Min: {s.get('min_score')}")

print(f"\n=== STATUS: {data['eligibility_status'].upper()} ===\n")
