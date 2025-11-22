# Detailed File References - Select/Combobox Audit

## Component Files Using Select/Combobox (23 files)

### Admin Organization Components (10 files)

#### 1. OfferingAcademicInfoDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/OfferingAcademicInfoDialog.tsx`
- **Select Usage:** Lines 483-547 (Tuition Discount Policies)
- **Implementation:** Checkbox-based multi-select with hook
- **Hook:** `useTuitionDiscountPolicies()`
- **Candidates:** SmartDiscountPoliciesMultiSelector
- **Status:** Good pattern, can be extracted

#### 2. MajorProgramDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/MajorProgramDialog.tsx`
- **Select Usage:** 
  - Lines 250-294: Degree Level selection
  - Lines 334-366: Unit/Organization selection
- **Implementation:** Standard Select with hierarchical data
- **Hooks:** `useDegreeLevels()`, `useOrganizationUnits()`
- **Candidates:** SmartDegreeLevelSelector, SmartUnitSelector
- **Complexity:** Medium - has hierarchy flattening logic
- **Code to Extract:** Flattening and display logic (lines 182-204)

#### 3. DocumentTypesSelector.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/DocumentTypesSelector.tsx`
- **Type:** Already a Smart Component (REFERENCE IMPLEMENTATION)
- **Hook:** `useDocumentTypes()`
- **Features:** Complete popover-based multi-select, loading states
- **Status:** Excellent pattern to replicate for other selectors
- **Use as Template:** YES

#### 4. UnitDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/UnitDialog.tsx`
- **Select Usage:** Parent Unit selection (hierarchical)
- **Implementation:** Complex with validation
- **Hooks:** `useOrganizationUnits()`, custom validation hooks
- **Validation Logic:** Circular dependency checking (lines 135-142)
- **Candidates:** SmartUnitSelector with validation options
- **Complexity:** Medium-High
- **Code to Extract:** Flattening logic (lines 182-202)

#### 5. ProgramOfferingDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/ProgramOfferingDialog.tsx`
- **Type:** Cascading selects (Major Program dependencies)
- **Candidates:** Part of SmartCascadingOfferingSelector
- **Complexity:** Medium

#### 6. OfferingAcademicInfoManagement.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/OfferingAcademicInfoManagement.tsx`
- **Type:** Complex nested structure management
- **Complexity:** Medium

#### 7. UnitDetailPanel.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/UnitDetailPanel.tsx`
- **Type:** Organization detail view
- **Complexity:** Low-Medium

#### 8. MajorListTab.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/MajorListTab.tsx`
- **Type:** List with selection state
- **Complexity:** Medium

#### 9. OrganizationClientPage.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/OrganizationClientPage.tsx`
- **Type:** Component orchestration
- **Complexity:** Low

#### 10. UnitList.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/organization/UnitList.tsx`
- **Type:** List rendering
- **Complexity:** Low

---

### Admin Policy Components (7 files)

#### 1. ConsultationStatusDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/ConsultationStatusDialog.tsx`
- **Hardcoded Arrays:**
  - Lines 53-61: VALID_LEGACY_STATUSES (7 options) ⚠️
  - Lines 103-112: PRESET_COLORS (8 colors) ⚠️
- **Select Usage:**
  - Lines 276-309: Pipeline Stage selection
  - Lines 365-399: Outcome Type selection (hardcoded buttons)
  - Lines 422-456: Legacy Status selection
- **Implementation:** Mix of hardcoded and API-driven
- **Candidates:** SmartPipelineStageSelector, SmartOutcomeTypeSelector, SmartColorPicker
- **Complexity:** Medium (multiple concerns mixed)

#### 2. FeaturePolicyTab.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/policies/FeaturePolicyTab.tsx`
- **Hardcoded Array:**
  - Lines 44-49: AVAILABLE_ROLES (4 roles) ⚠️
- **Issue:** Should use dynamic roles from API
- **Candidates:** SmartRoleSelector (replace hardcoded array with useRoles())
- **Quick Fix:** Available in ManageRolesDialog.tsx as reference

#### 3. PermissionSimulatorTab.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/policies/PermissionSimulatorTab.tsx`
- **Implementation:** Uses Combobox with hook-based suggestions
- **Hook:** `usePolicySuggestions()`
- **Status:** GOOD PATTERN - No changes needed
- **Reference:** How to implement autocomplete suggestions

#### 4. PermissionLookupTab.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/policies/PermissionLookupTab.tsx`
- **Type:** Policy lookup functionality
- **Complexity:** Medium

#### 5. PoliciesTab.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/policies/PoliciesTab.tsx`
- **Type:** Policy management
- **Complexity:** Medium

#### 6. RolesTab.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/policies/RolesTab.tsx`
- **Type:** Role display and management
- **Complexity:** Low-Medium

#### 7. RoleDetailView.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/policies/RoleDetailView.tsx`
- **Type:** Role detail view
- **Complexity:** Low

---

### Admin Distribution & Other (2 files)

#### 1. DistributionRuleDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/distribution/DistributionRuleDialog.tsx`
- **Complex Selects:**
  - Lines 249-297: Offering selection with degree level grouping
  - Lines 299-337: Unit selection with hierarchy
- **Implementation:** Advanced useMemo logic for grouping
  - Lines 130-158: Offering options building
  - Lines 161-172: Grouping by degree level
- **Candidates:** SmartOfferingSelector, SmartUnitSelector
- **Complexity:** Medium-High (most complex logic)
- **Extract:** Entire offering/grouping logic for reuse

#### 2. ManageRolesDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/admin/ManageRolesDialog.tsx`
- **Implementation:** GOOD PATTERN for dynamic role selection
- **Hook:** `useRoles()`
- **Lines 53-59:** AVAILABLE_ROLES computed dynamically (NOT hardcoded!)
- **Status:** Good reference - shows how roles should be handled
- **Reference:** Use this pattern for FeaturePolicyTab

---

### Leads Components (7 files)

#### 1. LeadApplicationForm.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/leads/LeadApplicationForm.tsx`
- **Cascading Selects:**
  - Major Program selection
  - Program Offering selection (depends on major program)
  - Admission Criteria selection (depends on offering)
- **Implementation:** watch/dependency pattern
- **Hooks:** `useMajorPrograms()`, `useOfferingAcademicInfoList()`
- **Candidates:** SmartCascadingOfferingSelector
- **Complexity:** Medium (cascading logic)

#### 2. AssignLeadDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/leads/AssignLeadDialog.tsx`
- **Select Usage:** Lines 162-190 (Officer selection)
- **Implementation:** User list with role filtering
- **Hook:** `useAdminUsersList()`
- **Candidates:** SmartOfficerSelector
- **Complexity:** Low-Medium
- **Features:** Shows name and email in dropdown

#### 3. ConsultationDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/leads/ConsultationDialog.tsx`
- **Select Usage:** Status selection
- **Hook:** `useConsultationStatuses()`
- **Candidates:** SmartConsultationStatusSelector
- **Complexity:** Low
- **Additional Fields:** Datetime and notes

#### 4. EditConsultationDialog.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/leads/EditConsultationDialog.tsx`
- **Select Usage:** Status selection (state-aware)
- **Hardcoded Enum:** Lines 50 - method enum
- **Hook:** `useAllowedNextStatuses()` (intelligent!)
- **Candidates:** SmartConsultationStatusSelector (with state-awareness)
- **Complexity:** Medium
- **Feature:** Only shows valid next statuses

#### 5. LeadFilters.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/leads/command-center/LeadFilters.tsx`
- **Hardcoded Arrays:**
  - Lines 42-50: STATUS_OPTIONS (7 with colors) ⚠️
  - Lines 52-61: SOURCE_OPTIONS (8 sources) ⚠️
- **Implementation:** Checkbox-based filter (NOT Select component)
- **Candidates:** Move to constants, create enum hook
- **Issue:** Colors hardcoded with Tailwind classes
- **Type:** Multi-select filter checkboxes

#### 6. QuickDisposition.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/leads/QuickDisposition.tsx`
- **Hardcoded Arrays:**
  - Lines 31-36: COMPLEX_STATUS_IDS (4 ids) ⚠️
  - Lines 38-39: SCHEDULABLE_STATUS_IDS (2 ids) ⚠️
- **Status:** Uses these IDs to determine component behavior
- **Issue:** Hardcoded IDs should be configuration-driven
- **Implementation:** Button-based UI, not Select
- **Hook:** `useAllowedNextStatuses()`
- **Feature:** Groups statuses by outcome_type with visual indicators

#### 7. LeadCard.tsx, LeadDialog.tsx, LeadTimelineTab.tsx, DocumentChecklist.tsx
- **Type:** Display/utility components with minimal select logic
- **Complexity:** Low

---

### Forms Components (6 files)

#### 1. ResetPasswordForm.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/forms/ResetPasswordForm.tsx`
- **Select Usage:** None

#### 2. RegisterForm.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/forms/RegisterForm.tsx`
- **Select Usage:** None

#### 3. LoginForm.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/forms/LoginForm.tsx`
- **Select Usage:** None

#### 4. ForgotPasswordForm.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/forms/ForgotPasswordForm.tsx`
- **Select Usage:** None

#### 5. EditProfileForm.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/forms/EditProfileForm.tsx`
- **Select Usage:** None

#### 6. ChangePasswordForm.tsx
- **Path:** `/home/user/QLTS/frontend/src/components/forms/ChangePasswordForm.tsx`
- **Select Usage:** None

---

## UI Components (Reference)

### Select Component
- **Path:** `/home/user/QLTS/frontend/src/components/ui/select.tsx`
- **Type:** Radix UI Select wrapper
- **Usage:** Base component for all Select implementations

### Combobox Component
- **Path:** `/home/user/QLTS/frontend/src/components/ui/combobox.tsx`
- **Type:** Basic autocomplete combobox
- **Features:** String value suggestions, free-form entry allowed
- **Props:** value, onChange, suggestions, placeholder, etc.

---

## Code Duplication Hotspots

### 1. Organization Unit Flattening (3 locations)
**Problem:** Same flattening logic repeated

1. UnitDialog.tsx (lines 182-202)
2. MajorProgramDialog.tsx (lines 182-202)
3. DistributionRuleDialog.tsx (lines 96-98, using flattenOrganizationTree hook)

**Solution:** Create SmartUnitSelector with reusable flattening

### 2. Offering Grouping by Degree Level (1+ locations)
**Problem:** Complex grouping logic in DistributionRuleDialog

1. DistributionRuleDialog.tsx (lines 130-172)

**Solution:** Create SmartOfferingSelector

### 3. Hardcoded Status Arrays (4 locations)
**Problem:** Same status enums/colors repeated

1. ConsultationStatusDialog.tsx (VALID_LEGACY_STATUSES)
2. LeadFilters.tsx (STATUS_OPTIONS)
3. QuickDisposition.tsx (COMPLEX_STATUS_IDS)
4. Various status type definitions in types files

**Solution:** Centralize in constants file

---

## Migration Path

### Step 1: Extract SmartUnitSelector
**Files to Read First:**
1. DocumentTypesSelector.tsx (reference implementation)
2. UnitDialog.tsx (line 182-202)
3. MajorProgramDialog.tsx (line 182-204)
4. DistributionRuleDialog.tsx (line 96-98)

**Files to Update:**
1. UnitDialog.tsx
2. MajorProgramDialog.tsx
3. DistributionRuleDialog.tsx

### Step 2: Create Enum Constants
**Files to Consolidate:**
1. LeadFilters.tsx (STATUS_OPTIONS, SOURCE_OPTIONS)
2. ConsultationStatusDialog.tsx (VALID_LEGACY_STATUSES, PRESET_COLORS)
3. QuickDisposition.tsx (COMPLEX_STATUS_IDS, SCHEDULABLE_STATUS_IDS)
4. Type definitions scattered in types files

### Step 3: Extract SmartConsultationStatusSelector
**Files to Read First:**
1. DocumentTypesSelector.tsx (reference)
2. ConsultationDialog.tsx
3. EditConsultationDialog.tsx

**Files to Update:**
1. ConsultationDialog.tsx
2. EditConsultationDialog.tsx

---

## Quick Navigation

### Files Requiring Immediate Attention (High Priority)
- `/frontend/src/components/admin/organization/UnitDialog.tsx`
- `/frontend/src/components/admin/organization/MajorProgramDialog.tsx`
- `/frontend/src/components/admin/organization/DistributionRuleDialog.tsx`
- `/frontend/src/components/admin/ConsultationStatusDialog.tsx`
- `/frontend/src/components/leads/LeadFilters.tsx`
- `/frontend/src/components/leads/QuickDisposition.tsx`
- `/frontend/src/components/admin/policies/FeaturePolicyTab.tsx`

### Reference Implementations (Good Patterns)
- `/frontend/src/components/admin/organization/DocumentTypesSelector.tsx` ⭐
- `/frontend/src/components/admin/policies/PermissionSimulatorTab.tsx` ⭐
- `/frontend/src/components/admin/ManageRolesDialog.tsx` ⭐

### UI Base Components
- `/frontend/src/components/ui/select.tsx`
- `/frontend/src/components/ui/combobox.tsx`

---

Generated: 2025-11-22
