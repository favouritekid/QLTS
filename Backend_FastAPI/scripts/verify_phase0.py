"""
Phase 0 Verification Script
Test the AdmissionPath and DocumentGroup schema changes
"""
import sys
sys.path.insert(0, '.')

from app.models.admission_config import AdmissionPath, DocumentGroup, AdmissionMethod
from app.models.offering_academic_info import OfferingAcademicInfo

print("=" * 60)
print("PHASE 0 VERIFICATION")
print("=" * 60)

# 1. Test imports
print("\n✅ 1. IMPORTS")
print(f"  AdmissionPath: {AdmissionPath}")
print(f"  DocumentGroup: {DocumentGroup}")
print(f"  AdmissionMethod: {AdmissionMethod}")

# 2. Check AdmissionPath columns
print("\n📋 2. AdmissionPath COLUMNS")
expected_columns = [
    'id', 'academic_info_id', 'admission_method_id', 'status',
    'display_name', 'display_order', 'visibility',
    'activated_at', 'activated_by', 'created_at', 'updated_at'
]
actual_columns = [col.name for col in AdmissionPath.__table__.columns]
for col in expected_columns:
    status = "✅" if col in actual_columns else "❌"
    print(f"  {status} {col}")

# 3. Check AdmissionPath relationships
print("\n🔗 3. AdmissionPath RELATIONSHIPS")
for rel in AdmissionPath.__mapper__.relationships:
    print(f"  → {rel.key} -> {rel.mapper.class_.__name__}")

# 4. Check unique constraint
print("\n🔒 4. AdmissionPath CONSTRAINTS")
for constraint in AdmissionPath.__table__.constraints:
    print(f"  • {constraint.name}: {type(constraint).__name__}")

# 5. Check DocumentGroup.admission_method_id
print("\n📋 5. DocumentGroup.admission_method_id")
dg_columns = [col.name for col in DocumentGroup.__table__.columns]
has_method_id = 'admission_method_id' in dg_columns
print(f"  {'✅' if has_method_id else '❌'} admission_method_id column exists: {has_method_id}")

# 6. Check DocumentGroup relationships
print("\n🔗 6. DocumentGroup RELATIONSHIPS")
for rel in DocumentGroup.__mapper__.relationships:
    print(f"  → {rel.key} -> {rel.mapper.class_.__name__}")

# 7. Check AdmissionMethod.document_groups relationship
print("\n🔗 7. AdmissionMethod RELATIONSHIPS")
for rel in AdmissionMethod.__mapper__.relationships:
    print(f"  → {rel.key} -> {rel.mapper.class_.__name__}")

# 8. Check OfferingAcademicInfo.admission_paths relationship
print("\n🔗 8. OfferingAcademicInfo RELATIONSHIPS")
for rel in OfferingAcademicInfo.__mapper__.relationships:
    print(f"  → {rel.key} -> {rel.mapper.class_.__name__}")

print("\n" + "=" * 60)
print("VERIFICATION COMPLETE")
print("=" * 60)
