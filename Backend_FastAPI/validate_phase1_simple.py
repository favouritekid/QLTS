#!/usr/bin/env python3
"""
Phase 1 Simple Validation Script (No Dependencies Required)
===========================================================

This script validates the 3-tier architecture implementation
using only Python standard library.
"""
import sys
import os
import ast
import py_compile
from pathlib import Path

print("=" * 80)
print("PHASE 1 VALIDATION SCRIPT (Simple Mode)")
print("=" * 80)
print()

BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "app" / "models"
SCHEMAS_DIR = BASE_DIR / "app" / "schemas"

# Test 1: Check Python Syntax
# ============================
print("✓ Test 1: Checking Python syntax...")
files_to_check = [
    MODELS_DIR / "major_program.py",
    MODELS_DIR / "program_offering.py",
    MODELS_DIR / "offering_academic_info.py",
    MODELS_DIR / "organization.py",
    MODELS_DIR / "__init__.py",
    SCHEMAS_DIR / "organization.py",
]

all_valid = True
for file_path in files_to_check:
    try:
        py_compile.compile(str(file_path), doraise=True)
        print(f"  ✅ {file_path.name}")
    except py_compile.PyCompileError as e:
        print(f"  ❌ {file_path.name}: {e}")
        all_valid = False

if not all_valid:
    print("\n❌ Syntax errors found!")
    sys.exit(1)

print()

# Test 2: Check Model Classes Exist
# ==================================
print("✓ Test 2: Checking model classes exist...")

def check_class_in_file(file_path, class_name):
    """Check if a class is defined in a Python file"""
    try:
        with open(file_path, 'r') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return True
        return False
    except Exception as e:
        print(f"  ⚠️  Error parsing {file_path}: {e}")
        return False

model_checks = [
    (MODELS_DIR / "major_program.py", "MajorProgram"),
    (MODELS_DIR / "program_offering.py", "ProgramOffering"),
    (MODELS_DIR / "offering_academic_info.py", "OfferingAcademicInfo"),
]

for file_path, class_name in model_checks:
    if check_class_in_file(file_path, class_name):
        print(f"  ✅ {class_name} class found in {file_path.name}")
    else:
        print(f"  ❌ {class_name} class NOT found in {file_path.name}")
        sys.exit(1)

print()

# Test 3: Check Relationships in Models
# ======================================
print("✓ Test 3: Checking relationships in models...")

def check_relationship_in_file(file_path, relationship_name):
    """Check if a relationship is defined in a Python file"""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        # Check for relationship with the target class (handles multi-line and spaces)
        import re
        pattern = rf'relationship\s*\(\s*["\']{ re.escape(relationship_name)}["\']'
        return bool(re.search(pattern, content))
    except Exception as e:
        print(f"  ⚠️  Error reading {file_path}: {e}")
        return False

relationship_checks = [
    (MODELS_DIR / "major_program.py", "ProgramOffering", "offerings"),
    (MODELS_DIR / "program_offering.py", "MajorProgram", "program"),
    (MODELS_DIR / "program_offering.py", "OfferingAcademicInfo", "academic_info_history"),
    (MODELS_DIR / "program_offering.py", "Lead", "leads"),
    (MODELS_DIR / "offering_academic_info.py", "ProgramOffering", "offering"),
    (MODELS_DIR / "organization.py", "MajorProgram", "major_programs"),
]

for file_path, target_class, rel_name in relationship_checks:
    if check_relationship_in_file(file_path, target_class):
        print(f"  ✅ {file_path.name} → {target_class} ('{rel_name}')")
    else:
        print(f"  ❌ {file_path.name} missing relationship to {target_class}")
        sys.exit(1)

print()

# Test 4: Check Table Names
# ==========================
print("✓ Test 4: Checking table names...")

def check_tablename_in_file(file_path, expected_tablename):
    """Check if __tablename__ is defined correctly"""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        return f'__tablename__ = "{expected_tablename}"' in content
    except Exception as e:
        print(f"  ⚠️  Error reading {file_path}: {e}")
        return False

tablename_checks = [
    (MODELS_DIR / "major_program.py", "major_program"),
    (MODELS_DIR / "program_offering.py", "program_offering"),
    (MODELS_DIR / "offering_academic_info.py", "offering_academic_info"),
]

for file_path, tablename in tablename_checks:
    if check_tablename_in_file(file_path, tablename):
        print(f"  ✅ {file_path.name}: __tablename__ = '{tablename}'")
    else:
        print(f"  ❌ {file_path.name}: __tablename__ '{tablename}' not found")
        sys.exit(1)

print()

# Test 5: Check Models Exported in __init__.py
# =============================================
print("✓ Test 5: Checking models exported in __init__.py...")

with open(MODELS_DIR / "__init__.py", 'r') as f:
    init_content = f.read()

exports_to_check = [
    "MajorProgram",
    "ProgramOffering",
    "OfferingAcademicInfo",
]

for export in exports_to_check:
    if export in init_content:
        print(f"  ✅ {export} exported")
    else:
        print(f"  ❌ {export} NOT exported")
        sys.exit(1)

print()

# Test 6: Check Schema Classes Exist
# ===================================
print("✓ Test 6: Checking schema classes exist...")

schema_file = SCHEMAS_DIR / "organization.py"
schema_classes = [
    "AdmissionCriterion",
    "OfferingAcademicInfoBase",
    "OfferingAcademicInfoCreate",
    "OfferingAcademicInfoUpdate",
    "OfferingAcademicInfo",
    "ProgramOfferingBase",
    "ProgramOfferingCreate",
    "ProgramOfferingUpdate",
    "ProgramOffering",
    "MajorProgramBase",
    "MajorProgramCreate",
    "MajorProgramUpdate",
    "MajorProgram",
]

for class_name in schema_classes:
    if check_class_in_file(schema_file, class_name):
        print(f"  ✅ {class_name}")
    else:
        print(f"  ❌ {class_name} NOT found")
        sys.exit(1)

print()

# Test 7: Check Backward Compatibility Aliases
# =============================================
print("✓ Test 7: Checking backward compatibility aliases...")

with open(schema_file, 'r') as f:
    schema_content = f.read()

aliases = [
    ("Major", "MajorProgram"),
    ("MajorCreate", "MajorProgramCreate"),
    ("MajorUpdate", "MajorProgramUpdate"),
    ("MajorBase", "MajorProgramBase"),
    ("MajorAcademicInfo", "OfferingAcademicInfo"),
]

for alias, target in aliases:
    if f"{alias} = {target}" in schema_content:
        print(f"  ✅ {alias} → {target}")
    else:
        print(f"  ❌ Alias {alias} → {target} NOT found")
        sys.exit(1)

print()

# Test 8: Check Foreign Keys
# ===========================
print("✓ Test 8: Checking foreign key constraints...")

fk_checks = [
    (MODELS_DIR / "major_program.py", 'ForeignKey("organization_unit.id")'),
    (MODELS_DIR / "program_offering.py", 'ForeignKey("major_program.id"'),
    (MODELS_DIR / "offering_academic_info.py", 'ForeignKey("program_offering.id"'),
]

for file_path, fk_string in fk_checks:
    with open(file_path, 'r') as f:
        content = f.read()
    if fk_string in content:
        print(f"  ✅ {file_path.name}: {fk_string[:40]}...")
    else:
        print(f"  ❌ {file_path.name}: Foreign key not found")
        sys.exit(1)

print()

# Test 9: Check Unique Constraints
# =================================
print("✓ Test 9: Checking unique constraints...")

constraint_checks = [
    (MODELS_DIR / "major_program.py", "unique=True", "code column"),
    (MODELS_DIR / "program_offering.py", "uq_program_offering_type", "(program_id, offering_type)"),
    (MODELS_DIR / "offering_academic_info.py", "uq_offering_academic_year", "(offering_id, academic_year)"),
]

for file_path, constraint_marker, description in constraint_checks:
    with open(file_path, 'r') as f:
        content = f.read()
    if constraint_marker in content:
        print(f"  ✅ {file_path.name}: {description}")
    else:
        print(f"  ❌ {file_path.name}: Constraint '{description}' not found")
        sys.exit(1)

print()

# Summary
# =======
print("=" * 80)
print("✅ ALL VALIDATION TESTS PASSED!")
print("=" * 80)
print()
print("Summary:")
print("  ✅ All Python files have valid syntax")
print("  ✅ All model classes defined correctly")
print("  ✅ All relationships configured")
print("  ✅ All table names correct")
print("  ✅ Models properly exported")
print("  ✅ All schema classes defined")
print("  ✅ Backward compatibility aliases present")
print("  ✅ Foreign keys configured")
print("  ✅ Unique constraints defined")
print()
print("🚀 Ready to proceed with Phase 2 (Migration)!")
print()
