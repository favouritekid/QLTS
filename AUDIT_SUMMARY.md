# QLTS Frontend Select/Combobox Audit - Quick Summary

## Key Findings

### 1. EXISTING SMART SELECTORS (1)
- **DocumentTypesSelector.tsx** - Excellent implementation pattern for multi-select with hook integration

### 2. SELECT/COMBOBOX USAGE
- **23 files** use Select or Combobox components
- **117 total** component files analyzed
- **High concentration** in Admin Organization (10), Leads (7), and Admin Policies (7)

### 3. CRITICAL ISSUES FOUND

#### High Priority - Hardcoded Arrays
Located in component files with no centralized configuration:
1. **ConsultationStatusDialog.tsx**
   - VALID_LEGACY_STATUSES (7 options)
   - PRESET_COLORS (8 colors)

2. **FeaturePolicyTab.tsx**
   - AVAILABLE_ROLES (4 hardcoded roles)

3. **LeadFilters.tsx**
   - STATUS_OPTIONS (7 lead statuses with colors)
   - SOURCE_OPTIONS (8 lead sources)

4. **QuickDisposition.tsx**
   - COMPLEX_STATUS_IDS (4 hardcoded status IDs)
   - SCHEDULABLE_STATUS_IDS (2 hardcoded status IDs)

#### Medium Priority - Scattered Implementation Logic
- **Organization Units** flattening/hierarchy logic repeated in 3 places:
  - UnitDialog.tsx
  - MajorProgramDialog.tsx
  - DistributionRuleDialog.tsx

- **Cascading Selects** patterns scattered without abstraction:
  - LeadApplicationForm.tsx (Major Program → Offering → Criteria)
  - DistributionRuleDialog.tsx (Complex grouping logic)

### 4. STANDARDIZATION OPPORTUNITIES

**High Impact (Used in 3+ places):**
1. SmartUnitSelector (replaces logic in 3 files)
2. SmartConsultationStatusSelector (replaces logic in 2+ files)
3. SmartOfferingSelector (replaces complex grouping in 1+ files)

**Medium Impact (Used in 1-2 places):**
4. SmartDegreeLevelSelector
5. SmartMajorProgramSelector
6. SmartDiscountPoliciesMultiSelector
7. SmartOfficerSelector
8. SmartColorPicker
9. SmartOutcomeTypeSelector

**Low Impact (Enum cleanup):**
10. SmartLeadStatusSelector (move hardcoded enum)
11. SmartLeadSourceSelector (move hardcoded enum)
12. SmartRoleSelector (replace hardcoded AVAILABLE_ROLES)

---

## By the Numbers

| Metric | Count |
|--------|-------|
| Total Components Analyzed | 117 |
| Files with Select/Combobox | 23 |
| Existing Smart Selectors | 1 ✅ |
| Hardcoded Option Arrays | 7 |
| High Priority Candidates | 4 |
| Medium Priority Candidates | 5 |
| Low Priority Candidates | 3 |
| **Total Standardization Candidates** | **12** |
| Estimated Code Reduction | 40-50% |

---

## Most Impactful Changes

### 1. Create SmartUnitSelector
**Impact:** Eliminates duplicate flattening/hierarchy logic from 3 files
- Files affected: UnitDialog.tsx, MajorProgramDialog.tsx, DistributionRuleDialog.tsx
- Lines saved: ~150 lines of duplicated logic
- Complexity reduced: Circular dependency validation centralized
- Reusability: Can be used in future components

### 2. Centralize Enum Constants
**Impact:** Creates single source of truth for lead statuses, sources, colors
- Creates: `/constants/lead-constants.ts` or similar
- Files affected: LeadFilters.tsx, QuickDisposition.tsx, ConsultationStatusDialog.tsx
- Maintainability: Changes needed in 1 place instead of 3
- Consistency: Ensures uniform display across UI

### 3. Create SmartConsultationStatusSelector
**Impact:** Consolidates status selection logic with state-machine awareness
- Files affected: ConsultationDialog.tsx, EditConsultationDialog.tsx
- Features: Automatic next-status filtering, outcome type grouping, color display
- Reduces: Form-specific selection logic

---

## Implementation Priority

### Phase 1: Foundation (Week 1)
1. Create `/components/common/selectors/` directory
2. Create SmartUnitSelector (most reused)
3. Centralize enum constants
4. Create SmartConsultationStatusSelector

### Phase 2: Core Refactoring (Week 2)
1. Migrate UnitDialog, MajorProgramDialog to SmartUnitSelector
2. Migrate ConsultationDialog, EditConsultationDialog to SmartConsultationStatusSelector
3. Update ConsultationStatusDialog hardcoded arrays

### Phase 3: Secondary Components (Week 3)
1. Create and integrate remaining high-priority selectors
2. Refactor hardcoded arrays to use constants
3. Create documentation and examples

---

## File Locations for Reference

### Most Complex Components (Worth Studying)
1. `/home/user/QLTS/frontend/src/components/admin/organization/DistributionRuleDialog.tsx` - Complex hierarchical logic (lines 249-337)
2. `/home/user/QLTS/frontend/src/components/admin/organization/UnitDialog.tsx` - Validation logic (lines 56-127)
3. `/home/user/QLTS/frontend/src/components/leads/LeadApplicationForm.tsx` - Cascading selects (full component)

### Best Practice Examples
1. `/home/user/QLTS/frontend/src/components/admin/organization/DocumentTypesSelector.tsx` - Already standardized
2. `/home/user/QLTS/frontend/src/components/admin/policies/PermissionSimulatorTab.tsx` - Good hook usage
3. `/home/user/QLTS/frontend/src/components/admin/ManageRolesDialog.tsx` - Good data fetching pattern

---

## Expected Benefits

- **40-50% code reduction** in select-related components
- **Single source of truth** for all enums and options
- **Improved maintainability** through centralized components
- **Better consistency** across UI
- **Reduced bugs** from duplicated logic
- **Easier testing** with reusable components
- **Faster development** for future select needs

---

## Next Steps

1. Review full report at: `/home/user/QLTS/FRONTEND_SELECT_AUDIT_REPORT.md`
2. Begin with Phase 1 implementation
3. Create branch: `feature/standardize-selectors`
4. Build SmartUnitSelector as proof of concept
5. Measure code reduction and developer experience improvements

---

Generated: 2025-11-22
