
import os
import re
from collections import defaultdict

def find_tests(root_dir):
    test_map = defaultdict(list)
    file_map = defaultdict(set)
    
    for root, dirs, files in os.walk(root_dir):
        if "venv" in root or "__pycache__" in root:
            continue
            
        for file in files:
            if file.startswith("test_") and file.endswith(".py"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        matches = re.findall(r"def (test_\w+)\(", content)
                        for test_name in matches:
                            test_map[test_name].append(file_path)
                            file_map[file_path].add(test_name)
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    
    return test_map, file_map

def generate_report(test_map, file_map):
    print("# Duplicate Test Analysis")
    print("\n## 1. Direct duplicates (Same test name in multiple files)")
    print("| Test Name | Occurrences | Files |")
    print("| :--- | :--- | :--- |")
    
    duplicate_count = 0
    for test_name, files in test_map.items():
        if len(files) > 1:
            # Sort files to ensure deterministic output
            files = sorted(list(set(files))) # dedupe files in case regex matched twice in same file
            if len(files) > 1:
                duplicate_count += 1
                # Format file paths to be relative to root for brevity
                rel_files = [os.path.relpath(f, os.getcwd()) for f in files]
                print(f"| `{test_name}` | {len(files)} | {', '.join([f'`{f}`' for f in rel_files])} |")
                
    if duplicate_count == 0:
        print("\n**No direct duplicates found!**")
        
    print("\n## 2. file Overlap Analysis (Files sharing duplicates)")
    # Analyze which files pair up most often
    file_pairs = defaultdict(int)
    for test_name, files in test_map.items():
        if len(files) > 1:
            files = sorted(list(set(files)))
            for i in range(len(files)):
                for j in range(i+1, len(files)):
                    pair = (files[i], files[j])
                    file_pairs[pair] += 1
                    
    print("| File A | File B | Shared Tests | Status |")
    print("| :--- | :--- | :--- | :--- |")
    
    for (file_a, file_b), count in sorted(file_pairs.items(), key=lambda x: x[1], reverse=True):
        rel_a = os.path.relpath(file_a, os.getcwd())
        rel_b = os.path.relpath(file_b, os.getcwd())
        
        # Determine status
        total_a = len(file_map[file_a])
        total_b = len(file_map[file_b])
        status = "Partial Overlap"
        if count == total_a and count == total_b:
            status = "**EXACT DUPLICATE FILES**"
        elif count == total_a:
            status = f"**File A is subset of File B**"
        elif count == total_b:
            status = f"**File B is subset of File A**"
            
        print(f"| `{rel_a}` | `{rel_b}` | {count} | {status} |")

if __name__ == "__main__":
    test_map, file_map = find_tests("tests")
    generate_report(test_map, file_map)
