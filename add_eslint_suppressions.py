#!/usr/bin/env python3
"""
Add ESLint suppressions for Promise<any> return types in server.ts
"""
import re

def add_suppressions(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()

    modified_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this line has Promise<any>
        if 'Promise<any>' in line:
            # Check if previous line already has eslint-disable comment
            prev_line = lines[i-1] if i > 0 else ''

            if 'eslint-disable' not in prev_line:
                # Get indentation from current line
                indent = len(line) - len(line.lstrip())

                # Check if this is a function declaration or serverFetch call
                if 'async' in line or 'serverFetch<any>' in line:
                    # Add comment before this line
                    comment = ' ' * indent + '// eslint-disable-next-line @typescript-eslint/no-explicit-any\n'
                    modified_lines.append(comment)

        modified_lines.append(line)
        i += 1

    with open(file_path, 'w') as f:
        f.writelines(modified_lines)

    print(f"✅ Added ESLint suppressions to {file_path}")

if __name__ == '__main__':
    add_suppressions('/home/user/QLTS/frontend/src/lib/api/server.ts')
