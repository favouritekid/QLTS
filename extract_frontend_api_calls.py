#!/usr/bin/env python3
"""
Extract all API calls from frontend (axios, fetch, etc.)
"""
import re
import os
from pathlib import Path
from typing import List, Dict

def extract_api_calls_from_file(file_path: str) -> List[Dict]:
    """Extract API calls from a TypeScript/JavaScript file."""
    api_calls = []

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')

    relative_path = file_path.replace('/home/user/QLTS/frontend/', '')

    # Pattern 1: axios calls - axios.get("/api/...", ...)
    axios_patterns = [
        r'axios\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]',
        r'axios\s*\(\s*\{[^}]*method:\s*[\'"`](get|post|put|delete|patch)[\'"`][^}]*url:\s*[\'"`]([^\'"` ]+)[\'"`]',
        r'axios\s*\(\s*\{[^}]*url:\s*[\'"`]([^\'"` ]+)[\'"`][^}]*method:\s*[\'"`](get|post|put|delete|patch)[\'"`]',
    ]

    for i, line in enumerate(lines):
        # Pattern 1: axios.METHOD
        match = re.search(r'axios\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]', line)
        if match:
            method = match.group(1).upper()
            url = match.group(2)
            api_calls.append({
                'method': method,
                'url': url,
                'file': relative_path,
                'line': i + 1,
                'type': 'axios'
            })
            continue

        # Pattern 2: fetch calls
        match = re.search(r'fetch\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]', line)
        if match:
            url = match.group(1)
            # Try to find method in next few lines
            method = 'GET'
            for j in range(i, min(i + 5, len(lines))):
                method_match = re.search(r'method:\s*[\'"`](get|post|put|delete|patch)[\'"`]', lines[j], re.IGNORECASE)
                if method_match:
                    method = method_match.group(1).upper()
                    break
            api_calls.append({
                'method': method,
                'url': url,
                'file': relative_path,
                'line': i + 1,
                'type': 'fetch'
            })
            continue

        # Pattern 3: axios config object
        match = re.search(r'axios\s*\(\s*\{', line)
        if match:
            # Extract from object config in next few lines
            config_lines = []
            brace_count = 1
            for j in range(i + 1, min(i + 20, len(lines))):
                config_lines.append(lines[j])
                brace_count += lines[j].count('{') - lines[j].count('}')
                if brace_count <= 0:
                    break

            config_text = ' '.join(config_lines)
            url_match = re.search(r'url:\s*[\'"`]([^\'"` ]+)[\'"`]', config_text)
            method_match = re.search(r'method:\s*[\'"`](get|post|put|delete|patch)[\'"`]', config_text, re.IGNORECASE)

            if url_match:
                url = url_match.group(1)
                method = method_match.group(1).upper() if method_match else 'GET'
                api_calls.append({
                    'method': method,
                    'url': url,
                    'file': relative_path,
                    'line': i + 1,
                    'type': 'axios-config'
                })

        # Pattern 4: Template literals with variables
        match = re.search(r'[\'"`]/api/[^\'"` ]*[\'"`]', line)
        if match and ('axios' in line or 'fetch' in line):
            # Already caught by other patterns, skip
            pass

    return api_calls

def normalize_url(url: str) -> str:
    """Normalize URL by replacing dynamic segments."""
    # Replace ${...} with {param}
    url = re.sub(r'\$\{[^}]+\}', '{param}', url)
    # Replace template literal variables
    url = re.sub(r'\{[^}]+\}', '{id}', url)
    return url

def main():
    frontend_path = Path('/home/user/QLTS/frontend/src')

    # Find all TS/TSX/JS files
    files_to_scan = []
    for ext in ['*.ts', '*.tsx', '*.js', '*.jsx']:
        files_to_scan.extend(frontend_path.rglob(ext))

    all_api_calls = []
    for file in files_to_scan:
        try:
            calls = extract_api_calls_from_file(str(file))
            all_api_calls.extend(calls)
        except Exception as e:
            print(f"Error processing {file}: {e}")

    print("=" * 80)
    print("FRONTEND API CALLS INVENTORY")
    print("=" * 80)
    print(f"\nTotal API calls found: {len(all_api_calls)}")
    print()

    # Filter only /api calls
    api_calls = [call for call in all_api_calls if call['url'].startswith('/api') or call['url'].startswith('${') or call['url'].startswith('`')]

    print(f"API calls to backend (/api/*): {len(api_calls)}")
    print()

    # Group by endpoint pattern
    by_pattern = {}
    for call in api_calls:
        url = normalize_url(call['url'])
        key = f"{call['method']} {url}"
        if key not in by_pattern:
            by_pattern[key] = []
        by_pattern[key].append(call)

    print("\nAPI Endpoints Called (grouped):")
    print("=" * 80)
    for pattern in sorted(by_pattern.keys()):
        calls = by_pattern[pattern]
        print(f"\n{pattern}")
        print(f"  Called from {len(calls)} location(s):")
        for call in calls[:5]:  # Show first 5 locations
            print(f"    - {call['file']}:{call['line']}")
        if len(calls) > 5:
            print(f"    ... and {len(calls) - 5} more")

    # Write to file
    with open('/home/user/QLTS/frontend_api_calls.txt', 'w') as f:
        for call in sorted(api_calls, key=lambda x: (x['method'], normalize_url(x['url']))):
            f.write(f"{call['method']:7} {normalize_url(call['url']):50} <- {call['file']}:{call['line']}\n")

    print("\n" + "=" * 80)
    print(f"API calls saved to: /home/user/QLTS/frontend_api_calls.txt")
    print("=" * 80)

if __name__ == '__main__':
    main()
