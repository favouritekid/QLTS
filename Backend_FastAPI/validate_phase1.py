#!/usr/bin/env python3
"""
Phase 1 Validation Script
=========================

This script validates the 3-tier architecture implementation:
1. Models can be imported without circular dependencies
2. Schemas validation works correctly
3. Relationships are properly configured
4. Backward compatibility aliases work
"""
import sys
from decimal import Decimal
from pydantic import ValidationError

print("=" * 80)
print("PHASE 1 VALIDATION SCRIPT")
print("=" * 80)
print()

# Test 1: Import Models
# =====================
print("✓ Test 1: Importing models...")
try:
    from app.models import (
        Base,
        MajorProgram,
        ProgramOffering,
        OfferingAcademicInfo,
        OrganizationUnit,
        Lead,
        # Legacy
        Major,
        MajorAcademicInfo,
    )
    print("  ✅ All models imported successfully")
    print(f"     - MajorProgram: {MajorProgram}")
    print(f"     - ProgramOffering: {ProgramOffering}")
    print(f"     - OfferingAcademicInfo: {OfferingAcademicInfo}")
except ImportError as e:
    print(f"  ❌ FAILED: {e}")
    sys.exit(1)
except Exception as e:
    print(f"  ❌ FAILED with unexpected error: {e}")
    sys.exit(1)

print()

# Test 2: Check Model Relationships
# ==================================
print("✓ Test 2: Checking model relationships...")
try:
    # Check MajorProgram has offerings relationship
    assert hasattr(MajorProgram, 'offerings'), "MajorProgram missing 'offerings' relationship"
    assert hasattr(MajorProgram, 'unit'), "MajorProgram missing 'unit' relationship"

    # Check ProgramOffering relationships
    assert hasattr(ProgramOffering, 'program'), "ProgramOffering missing 'program' relationship"
    assert hasattr(ProgramOffering, 'academic_info_history'), "ProgramOffering missing 'academic_info_history' relationship"
    assert hasattr(ProgramOffering, 'leads'), "ProgramOffering missing 'leads' relationship"

    # Check OfferingAcademicInfo relationships
    assert hasattr(OfferingAcademicInfo, 'offering'), "OfferingAcademicInfo missing 'offering' relationship"
    assert hasattr(OfferingAcademicInfo, 'created_by'), "OfferingAcademicInfo missing 'created_by' relationship"

    # Check OrganizationUnit has major_programs
    assert hasattr(OrganizationUnit, 'major_programs'), "OrganizationUnit missing 'major_programs' relationship"

    print("  ✅ All relationships configured correctly")
    print("     - MajorProgram → ProgramOffering ✓")
    print("     - ProgramOffering → OfferingAcademicInfo ✓")
    print("     - ProgramOffering → Lead ✓")
    print("     - OrganizationUnit → MajorProgram ✓")
except AssertionError as e:
    print(f"  ❌ FAILED: {e}")
    sys.exit(1)
except Exception as e:
    print(f"  ❌ FAILED with unexpected error: {e}")
    sys.exit(1)

print()

# Test 3: Import Schemas
# =======================
print("✓ Test 3: Importing schemas...")
try:
    from app.schemas.organization import (
        # Level 3
        AdmissionCriterion,
        OfferingAcademicInfo as OfferingAcademicInfoSchema,
        OfferingAcademicInfoCreate,
        OfferingAcademicInfoUpdate,
        # Level 2
        ProgramOffering as ProgramOfferingSchema,
        ProgramOfferingCreate,
        ProgramOfferingUpdate,
        # Level 1
        MajorProgram as MajorProgramSchema,
        MajorProgramCreate,
        MajorProgramUpdate,
        # Organization
        OrganizationUnit as OrganizationUnitSchema,
        # Backward compatibility
        Major as MajorSchemaAlias,
        MajorAcademicInfo as MajorAcademicInfoAlias,
    )
    print("  ✅ All schemas imported successfully")
except ImportError as e:
    print(f"  ❌ FAILED: {e}")
    sys.exit(1)

print()

# Test 4: Schema Validation - AdmissionCriterion
# ===============================================
print("✓ Test 4: Testing AdmissionCriterion JSON validation...")
try:
    # Valid admission criterion
    valid_criterion = AdmissionCriterion(
        id="hocba_2025",
        method_name="Xét tuyển học bạ",
        program_type="Chính quy",
        subject_groups=["A00", "A01", "D07"],
        min_score=22.5,
        conditions="Tốt nghiệp THPT",
        profile_requirements="Bằng TN + Học bạ"
    )
    print("  ✅ Valid AdmissionCriterion created successfully")
    print(f"     - ID: {valid_criterion.id}")
    print(f"     - Subject groups: {valid_criterion.subject_groups}")

    # Test invalid subject group format
    try:
        invalid_criterion = AdmissionCriterion(
            id="invalid_test",
            method_name="Test",
            program_type="Test",
            subject_groups=["INVALID"],  # Should fail
        )
        print("  ❌ FAILED: Invalid subject group should have raised ValidationError")
        sys.exit(1)
    except ValidationError:
        print("  ✅ Invalid subject group correctly rejected")

except Exception as e:
    print(f"  ❌ FAILED: {e}")
    sys.exit(1)

print()

# Test 5: Schema Validation - Create Schemas
# ===========================================
print("✓ Test 5: Testing create schemas...")
try:
    # Test MajorProgramCreate
    major_create = MajorProgramCreate(
        name="Cao đẳng Công nghệ thông tin",
        degree_level="Cao đẳng",
        code="6480201",
        unit_id=1,
        is_active=True
    )
    print("  ✅ MajorProgramCreate validation passed")

    # Test ProgramOfferingCreate
    offering_create = ProgramOfferingCreate(
        offering_type="Chính quy",
        duration_semesters=6,
        total_credits=90,
        program_id=1,
        is_active=True
    )
    print("  ✅ ProgramOfferingCreate validation passed")

    # Test OfferingAcademicInfoCreate
    academic_info_create = OfferingAcademicInfoCreate(
        offering_id=1,
        academic_year=2025,
        tuition_fee_per_year=Decimal("15000000.00"),
        annual_admission_quota=100,
        is_published=True,
        admission_criteria=[valid_criterion],
        target_audience="Học sinh tốt nghiệp THPT"
    )
    print("  ✅ OfferingAcademicInfoCreate validation passed")
    print(f"     - Year: {academic_info_create.academic_year}")
    print(f"     - Tuition: {academic_info_create.tuition_fee_per_year}")
    print(f"     - Quota: {academic_info_create.annual_admission_quota}")

except ValidationError as e:
    print(f"  ❌ FAILED: Validation error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"  ❌ FAILED: {e}")
    sys.exit(1)

print()

# Test 6: Schema Validation - Nested Structure
# =============================================
print("✓ Test 6: Testing nested schema structure...")
try:
    # Simulate a full nested structure
    program_schema = MajorProgramSchema(
        id=1,
        name="Cao đẳng Công nghệ thông tin",
        degree_level="Cao đẳng",
        code="6480201",
        unit_id=1,
        is_active=True,
        offerings=[
            ProgramOfferingSchema(
                id=1,
                program_id=1,
                offering_type="Chính quy",
                duration_semesters=6,
                total_credits=90,
                is_active=True,
                academic_info_history=[
                    OfferingAcademicInfoSchema(
                        id=1,
                        offering_id=1,
                        academic_year=2025,
                        tuition_fee_per_year=Decimal("15000000.00"),
                        annual_admission_quota=100,
                        is_published=True,
                        admission_criteria=[valid_criterion]
                    )
                ]
            )
        ]
    )
    print("  ✅ Nested schema structure validated successfully")
    print(f"     - Program: {program_schema.name}")
    print(f"     - Offerings: {len(program_schema.offerings)}")
    print(f"     - Academic Info: {len(program_schema.offerings[0].academic_info_history)}")

except Exception as e:
    print(f"  ❌ FAILED: {e}")
    sys.exit(1)

print()

# Test 7: Backward Compatibility Aliases
# =======================================
print("✓ Test 7: Testing backward compatibility aliases...")
try:
    # Check that aliases point to correct classes
    assert MajorSchemaAlias == MajorProgramSchema, "Major alias incorrect"
    assert MajorAcademicInfoAlias == OfferingAcademicInfoSchema, "MajorAcademicInfo alias incorrect"

    print("  ✅ Backward compatibility aliases working")
    print("     - Major → MajorProgram ✓")
    print("     - MajorAcademicInfo → OfferingAcademicInfo ✓")

except AssertionError as e:
    print(f"  ❌ FAILED: {e}")
    sys.exit(1)

print()

# Test 8: Model Table Names
# ==========================
print("✓ Test 8: Checking model table names...")
try:
    assert MajorProgram.__tablename__ == "major_program"
    assert ProgramOffering.__tablename__ == "program_offering"
    assert OfferingAcademicInfo.__tablename__ == "offering_academic_info"

    print("  ✅ All table names correct")
    print("     - major_program ✓")
    print("     - program_offering ✓")
    print("     - offering_academic_info ✓")

except AssertionError as e:
    print(f"  ❌ FAILED: Table name mismatch")
    sys.exit(1)

print()

# Test 9: Check Constraints
# ==========================
print("✓ Test 9: Checking model constraints...")
try:
    # Check MajorProgram code is unique
    code_col = MajorProgram.__table__.c.code
    assert code_col.unique, "MajorProgram.code should be unique"

    # Check ProgramOffering unique constraint
    offering_constraints = [c.name for c in ProgramOffering.__table__.constraints]
    assert 'uq_program_offering_type' in offering_constraints, "Missing unique constraint on ProgramOffering"

    # Check OfferingAcademicInfo unique constraint
    academic_constraints = [c.name for c in OfferingAcademicInfo.__table__.constraints]
    assert 'uq_offering_academic_year' in academic_constraints, "Missing unique constraint on OfferingAcademicInfo"

    print("  ✅ All constraints configured correctly")
    print("     - MajorProgram.code UNIQUE ✓")
    print("     - (program_id, offering_type) UNIQUE ✓")
    print("     - (offering_id, academic_year) UNIQUE ✓")

except AssertionError as e:
    print(f"  ❌ FAILED: {e}")
    sys.exit(1)

print()

# Summary
# =======
print("=" * 80)
print("✅ ALL VALIDATION TESTS PASSED!")
print("=" * 80)
print()
print("Summary:")
print("  ✅ Models import without circular dependencies")
print("  ✅ All relationships properly configured")
print("  ✅ Schemas validation working correctly")
print("  ✅ AdmissionCriterion JSON validation works")
print("  ✅ Nested schema structure validated")
print("  ✅ Backward compatibility aliases working")
print("  ✅ Table names correct")
print("  ✅ Database constraints configured")
print()
print("🚀 Ready to proceed with Phase 2 (Migration)!")
print()
