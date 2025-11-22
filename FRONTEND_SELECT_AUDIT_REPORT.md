# QLTS Frontend Select/Combobox Comprehensive Audit Report

## Executive Summary
- **Total Component Files Analyzed:** 117
- **Files Using Select/Combobox:** 23
- **Existing Smart Selectors:** 1 (DocumentTypesSelector)
- **Hardcoded Option Arrays:** 5+
- **Standardization Candidates:** 18+

---

## 1. EXISTING SMART SELECTORS

### DocumentTypesSelector.tsx
- **Location:** `/home/user/QLTS/frontend/src/components/admin/organization/DocumentTypesSelector.tsx`
- **Type:** Smart Multi-Select Component
- **Data Source:** `useDocumentTypes()` hook
- **Current Usage:** 
  - Used in `OfferingAcademicInfoDialog.tsx` for required documents selection
- **Features:**
  - Popover-based combobox
  - Automatic fetching of available document types
  - Display of selected documents with removal capability
  - Loading states handled
  - Summary of selected count
- **Status:** ✅ Already standardized - good candidate for replication pattern

---

## 2. SELECT/COMBOBOX USAGE ACROSS CODEBASE

### Admin Organization Components (10 files)

#### 1. OfferingAcademicInfoDialog.tsx
- **Location:** `components/admin/organization/OfferingAcademicInfoDialog.tsx`
- **Line:** 483-547 (Tuition Discount Policies)
- **Data Type:** Tuition Discount Policies
- **Current Implementation:** 
  - Checkbox-based multi-select for discount policies
  - Fetched via `useTuitionDiscountPolicies()` hook
  - Shows policy code, type, and discount amount
  - Max-height scrollable list
- **Smart Factor:** HIGH - Fully standardized with hook-based data
- **Candidate for Conversion:** YES ⭐ Create `SmartDiscountPoliciesSelector`

#### 2. MajorProgramDialog.tsx
- **Location:** `components/admin/organization/MajorProgramDialog.tsx`
- **Lines:** 250-294 (Degree Level), 334-366 (Unit/Organization)
- **Data Types:** 
  - Degree Levels (2-level structure)
  - Organization Units (hierarchical with indent display)
- **Current Implementation:**
  - Standard Select with API-fetched options
  - Degree levels: `useDegreeLevels()` hook
  - Units: `useOrganizationUnits()` hook with flattening logic
  - Hierarchical display with indentation
- **Smart Factor:** MEDIUM - Hook-based but logic is scattered
- **Candidate for Conversion:** YES ⭐ Create `SmartUnitSelector` and `SmartDegreeLevelSelector`

#### 3. DocumentTypesSelector.tsx
- **Status:** Already analyzed above as existing smart selector

#### 4. UnitDialog.tsx
- **Location:** `components/admin/organization/UnitDialog.tsx`
- **Lines:** 56-127 (Parent Unit Selection)
- **Data Type:** Organization Units (hierarchical)
- **Current Implementation:**
  - Parent unit selection with circular dependency validation
  - Fetched via `useOrganizationUnits()` hook
  - Flattened tree structure for dropdown
  - "none" option for root-level units
  - Duplicate name validation within same parent
- **Smart Factor:** MEDIUM-HIGH - Complex validation logic
- **Candidate for Conversion:** YES ⭐ Create `SmartParentUnitSelector`

#### 5. ProgramOfferingDialog.tsx
- **Location:** `components/admin/organization/ProgramOfferingDialog.tsx`
- **Data Type:** Major Programs
- **Implementation:** Cascading select with major program dependencies
- **Smart Factor:** MEDIUM - Needs cascading logic

#### 6. OfferingAcademicInfoManagement.tsx
- **Type:** Component with complex nested selects
- **Smart Factor:** MEDIUM

#### 7. UnitDetailPanel.tsx
- **Type:** Organization structure management
- **Smart Factor:** LOW-MEDIUM

#### 8. MajorListTab.tsx
- **Location:** `components/admin/organization/MajorListTab.tsx`
- **Data Type:** Major Programs (selection state management)
- **Current Implementation:** Complex state management with multiple selected items
- **Smart Factor:** MEDIUM

#### 9. OrganizationClientPage.tsx
- **Type:** Component orchestration
- **Smart Factor:** LOW

#### 10. UnitList.tsx
- **Type:** List rendering
- **Smart Factor:** LOW

### Admin Policy Components (7 files)

#### 1. ConsultationStatusDialog.tsx
- **Location:** `components/admin/ConsultationStatusDialog.tsx`
- **Lines:** 103-112 (Hardcoded PRESET_COLORS), 276-309 (Stage Selection), 365-399 (Outcome Type)
- **Data Types:**
  - Pipeline Stages (via `usePipelineStages()`)
  - Outcome Types (hardcoded enum: positive, neutral, negative)
  - Legacy Statuses (hardcoded array: VALID_LEGACY_STATUSES with 7 options)
- **Current Implementation:**
  - Standard Select for stages
  - Hardcoded buttons for outcome types
  - Preset color picker (8 colors)
  - Enum-based legacy status mapping
- **Hardcoded Arrays:**
  ```typescript
  VALID_LEGACY_STATUSES = [
    { value: "new", label: "New" },
    { value: "assigned", label: "Assigned" },
    { value: "contacted", label: "Contacted" },
    { value: "qualified", label: "Qualified" },
    { value: "unqualified", label: "Unqualified" },
    { value: "converted", label: "Converted" },
    { value: "rejected", label: "Rejected" },
  ];
  
  PRESET_COLORS = [
    { name: "Blue", value: "#3B82F6" },
    { name: "Green", value: "#10B981" },
    { name: "Yellow", value: "#F59E0B" },
    { name: "Red", value: "#EF4444" },
    { name: "Purple", value: "#8B5CF6" },
    { name: "Pink", value: "#EC4899" },
    { name: "Indigo", value: "#6366F1" },
    { name: "Gray", value: "#6B7280" },
  ];
  ```
- **Smart Factor:** MEDIUM - Partially hardcoded, partially hook-based
- **Candidate for Conversion:** YES ⭐ Create `SmartPipelineStageSelector` and `SmartOutcomeTypeSelector`

#### 2. FeaturePolicyTab.tsx
- **Location:** `components/admin/policies/FeaturePolicyTab.tsx`
- **Lines:** 44-49 (AVAILABLE_ROLES)
- **Data Type:** Casbin Roles
- **Hardcoded Array:**
  ```typescript
  AVAILABLE_ROLES = [
    { value: "role:admin", label: "Administrator" },
    { value: "role:manager", label: "Manager" },
    { value: "role:officer", label: "Officer" },
    { value: "role:user", label: "User" },
  ];
  ```
- **Current Implementation:** 
  - Standard Select with hardcoded role options
  - Could be fetched from API instead
  - Role features fetched via API
- **Smart Factor:** LOW - Static hardcoded options
- **Candidate for Conversion:** YES ⭐ Replace hardcoded array with `useRoles()` hook

#### 3. PermissionSimulatorTab.tsx
- **Location:** `components/admin/policies/PermissionSimulatorTab.tsx`
- **Line:** 24 (Import Combobox)
- **Data Type:** Policy Suggestions (Subject, Object, Action)
- **Current Implementation:**
  - Custom Combobox for autocomplete
  - Uses `usePolicySuggestions()` hook
  - Allows custom free-form text entry
- **Smart Factor:** HIGH - Already uses hook-based suggestions
- **Candidate for Conversion:** Already good pattern to replicate

#### 4. PermissionLookupTab.tsx
- **Type:** Policy lookup functionality
- **Smart Factor:** MEDIUM

#### 5. PoliciesTab.tsx
- **Type:** Policy management
- **Smart Factor:** MEDIUM

#### 6. RolesTab.tsx
- **Type:** Role display and management
- **Smart Factor:** LOW-MEDIUM

#### 7. RoleDetailView.tsx
- **Type:** Role detail view
- **Smart Factor:** LOW

### Admin Distribution & Other (2 files)

#### 1. DistributionRuleDialog.tsx
- **Location:** `components/admin/distribution/DistributionRuleDialog.tsx`
- **Lines:** 249-297 (Offering Select), 299-337 (Unit Select)
- **Data Types:**
  - Program Offerings (hierarchical by degree level)
  - Organization Units (hierarchical)
- **Current Implementation:**
  - SelectGroup with grouped offerings by degree level
  - Offerings extracted from major_programs (via useMemo)
  - Flattened units with hierarchy display
  - Disabled field editing (showing selection only)
- **Complex Logic:**
  - useMemo for program extraction from unit tree
  - useMemo for grouping offerings by degree level
  - Custom displayName formatting
  - Sorting logic (degree level > major name > offering type)
- **Smart Factor:** MEDIUM-HIGH - Complex hierarchical logic
- **Candidate for Conversion:** YES ⭐ Create `SmartOfferingSelector` and reuse `SmartUnitSelector`

#### 2. ManageRolesDialog.tsx
- **Location:** `components/admin/ManageRolesDialog.tsx`
- **Lines:** 53-59 (AVAILABLE_ROLES computed from API)
- **Data Type:** Casbin Roles
- **Current Implementation:**
  - Dynamic role list fetched from API via `useRoles()`
  - Roles mapped to options with display names
  - Complex filtering logic for assignable roles
  - Shows assigned vs assignable separation
- **Smart Factor:** HIGH - Hook-based dynamic data
- **Candidate for Conversion:** YES ⭐ Current implementation is already a good pattern

### Leads Components (7 files)

#### 1. LeadApplicationForm.tsx
- **Location:** `components/leads/LeadApplicationForm.tsx`
- **Lines:** 21-26 (Import Select)
- **Data Types:**
  - Major Programs (cascading)
  - Program Offerings (cascading based on major program)
  - Admission Criteria (cascading based on offering)
- **Current Implementation:**
  - Cascading selects with watch/dependency logic
  - Multiple hooks: useMajorPrograms, useOfferingAcademicInfoList
  - Form-field style rendering
- **Smart Factor:** MEDIUM - Has cascading dependency logic
- **Candidate for Conversion:** YES ⭐ Create `SmartCascadingOfferingSelector`

#### 2. AssignLeadDialog.tsx
- **Location:** `components/leads/AssignLeadDialog.tsx`
- **Lines:** 162-190 (Officer Selection)
- **Data Type:** Users (Officers/Admins)
- **Current Implementation:**
  - Standard Select with user list
  - Fetched via `useAdminUsersList()` hook
  - Filtered to officers and admins only
  - Shows full_name and email in display
- **Smart Factor:** MEDIUM - Hook-based but filtering is local
- **Candidate for Conversion:** YES ⭐ Create `SmartOfficerSelector`

#### 3. ConsultationDialog.tsx
- **Location:** `components/leads/ConsultationDialog.tsx`
- **Lines:** 29-35 (Import Select)
- **Data Type:** Consultation Statuses
- **Current Implementation:**
  - Standard Select with status list
  - Fetched via `useConsultationStatuses()` hook
  - Datetime field for scheduling
  - Notes textarea
- **Smart Factor:** MEDIUM - Hook-based
- **Candidate for Conversion:** YES ⭐ Create `SmartConsultationStatusSelector`

#### 4. EditConsultationDialog.tsx
- **Location:** `components/leads/EditConsultationDialog.tsx`
- **Lines:** 29-35 (Import Select)
- **Data Type:** Consultation Statuses (state-aware)
- **Current Implementation:**
  - Uses `useAllowedNextStatuses()` hook for state machine
  - Shows only valid next statuses
  - Method dropdown with hardcoded enum
- **Hardcoded Enum:**
  ```typescript
  method: z.enum(["phone", "email", "in_person", "online", "video_call"])
  ```
- **Smart Factor:** MEDIUM - State-machine aware selector
- **Candidate for Conversion:** YES ⭐ Create `SmartNextStatusSelector`

#### 5. LeadFilters.tsx
- **Location:** `components/leads/command-center/LeadFilters.tsx`
- **Lines:** 42-61 (Hardcoded OPTIONS)
- **Data Types:** Lead Status (enum), Lead Source (enum)
- **Hardcoded Arrays:**
  ```typescript
  STATUS_OPTIONS = [
    { value: "new", label: "New", color: "bg-blue-500" },
    { value: "assigned", label: "Assigned", color: "bg-purple-500" },
    { value: "contacted", label: "Contacted", color: "bg-cyan-500" },
    { value: "qualified", label: "Qualified", color: "bg-emerald-500" },
    { value: "unqualified", label: "Unqualified", color: "bg-gray-500" },
    { value: "converted", label: "Converted", color: "bg-green-500" },
    { value: "rejected", label: "Rejected", color: "bg-red-500" },
  ];
  
  SOURCE_OPTIONS = [
    { value: "website", label: "Website" },
    { value: "referral", label: "Referral" },
    { value: "social_media", label: "Social Media" },
    { value: "walk_in", label: "Walk-in" },
    { value: "email", label: "Email" },
    { value: "phone", label: "Phone" },
    { value: "event", label: "Event" },
    { value: "other", label: "Other" },
  ];
  ```
- **Current Implementation:**
  - Checkbox-based multi-select (not Select component)
  - Hardcoded mappings
  - Uses Checkbox UI component instead of Select
  - Accordion-based filter groups
- **Smart Factor:** LOW - Hardcoded enum values
- **Candidate for Conversion:** YES ⭐ Create constants/hook for lead status and source enums

#### 6. QuickDisposition.tsx
- **Location:** `components/leads/QuickDisposition.tsx`
- **Lines:** 31-39 (Hardcoded STATUS_IDS)
- **Data Types:** Consultation Statuses (grouped by outcome_type)
- **Hardcoded Arrays:**
  ```typescript
  COMPLEX_STATUS_IDS = [
    "hen_goi_lai",
    "tiem_nang",
    "dong_y_tu_van",
    "quan_tam",
  ];
  
  SCHEDULABLE_STATUS_IDS = ["hen_goi_lai", "tiem_nang"];
  ```
- **Current Implementation:**
  - Fetches statuses via `useAllowedNextStatuses()` hook
  - Groups them by outcome_type (neutral, positive, negative)
  - Uses hardcoded IDs for determining behavior
  - Button-based interface instead of Select
  - Shows color from status.color_code
- **Smart Factor:** MEDIUM - Hook-based but uses hardcoded ID arrays
- **Candidate for Conversion:** YES ⭐ Move hardcoded IDs to configuration

#### 7. LeadCard.tsx, LeadDialog.tsx, LeadTimelineTab.tsx, DocumentChecklist.tsx
- **Type:** Various display and utility components
- **Smart Factor:** LOW

### Forms Components (6 files)

- **Status:** No Select/Combobox usage identified
- **Components:** RegisterForm, LoginForm, EditProfileForm, etc.

---

## 3. PATTERNS IDENTIFIED

### Pattern 1: Hardcoded Option Arrays (HIGH PRIORITY)
**Examples:**
- `VALID_LEGACY_STATUSES` (ConsultationStatusDialog.tsx:53-61) - 7 options
- `PRESET_COLORS` (ConsultationStatusDialog.tsx:103-112) - 8 colors
- `AVAILABLE_ROLES` (FeaturePolicyTab.tsx:44-49) - 4 roles
- `STATUS_OPTIONS` (LeadFilters.tsx:42-50) - 7 lead statuses
- `SOURCE_OPTIONS` (LeadFilters.tsx:52-61) - 8 lead sources
- `COMPLEX_STATUS_IDS` (QuickDisposition.tsx:31-36) - 4 status IDs
- `SCHEDULABLE_STATUS_IDS` (QuickDisposition.tsx:38-39) - 2 status IDs

**Impact:** Scattered, hard to maintain, prone to inconsistency
**Action Required:** Create centralized enum definitions and hook-based selectors

### Pattern 2: Manual Fetch + Map to Options (MEDIUM PRIORITY)
**Examples:**
- `useMajorPrograms()` → mapped to SelectItems (LeadApplicationForm.tsx)
- `useOrganizationUnits()` → flattened with custom logic (MajorProgramDialog.tsx, DistributionRuleDialog.tsx, UnitDialog.tsx)
- `useDegreeLevels()` → mapped to SelectItems (MajorProgramDialog.tsx)
- `useAdminUsersList()` → filtered and mapped (AssignLeadDialog.tsx)
- `useTuitionDiscountPolicies()` → mapped to Checkboxes (OfferingAcademicInfoDialog.tsx)
- `useConsultationStatuses()` → mapped to SelectItems (ConsultationDialog.tsx)
- `usePipelineStages()` → mapped to SelectItems (ConsultationStatusDialog.tsx)
- `useAllowedNextStatuses()` → mapped with filtering (EditConsultationDialog.tsx)

**Impact:** Repetitive mapping code scattered across components
**Action Required:** Create reusable Smart Selector components wrapping hooks

### Pattern 3: Enum/Status Mappings to UI (MEDIUM PRIORITY)
**Examples:**
- `outcome_type` enum: "positive" | "neutral" | "negative" (ConsultationStatusDialog.tsx)
- `consultation method` enum: "phone" | "email" | "in_person" | "online" | "video_call" (EditConsultationDialog.tsx)
- `application status` enum: "pending" | "missing_documents" | "completed" | "passed" | "failed" (LeadApplicationForm.tsx)
- `document submission type` enum: "N/A" | "photocopy" | "notarized" | "original" | "incomplete" (LeadApplicationForm.tsx)
- Lead statuses: "new" | "assigned" | "contacted" | "qualified" | "unqualified" | "converted" | "rejected"
- Lead sources: "website" | "referral" | "social_media" | "walk_in" | "email" | "phone" | "event" | "other"

**Impact:** Scattered enum definitions, inconsistent display names
**Action Required:** Centralize enum definitions in types, create display-name mappers

### Pattern 4: Hierarchical/Tree-Based Selectors (MEDIUM-HIGH PRIORITY)
**Examples:**
- Organization Units with parent-child relationships (UnitDialog.tsx, MajorProgramDialog.tsx, DistributionRuleDialog.tsx)
- Program Offering grouped by Degree Level (DistributionRuleDialog.tsx)
- Major Programs with Unit hierarchy

**Impact:** Complex flattening and display logic duplicated across components
**Action Required:** Create reusable hierarchical selector utilities and Smart Components

### Pattern 5: Cascading/Dependent Selects (MEDIUM PRIORITY)
**Examples:**
- Major Program → Program Offering → Admission Criteria (LeadApplicationForm.tsx)
- Unit → Major Programs → Offerings (DistributionRuleDialog.tsx)

**Impact:** Complex form logic with watch/dependency patterns
**Action Required:** Create CascadingSelect abstraction

### Pattern 6: Already Well-Implemented Patterns (BEST PRACTICES)
**Examples:**
- DocumentTypesSelector.tsx - Complete Smart Component with hook, loading states, error handling
- PermissionSimulatorTab.tsx - Good use of Combobox with suggestions from hook
- ManageRolesDialog.tsx - Good dynamic data fetching and filtering

**Status:** These are good reference implementations for standardization

---

## 4. STANDARDIZATION CANDIDATES (Ranked by Priority)

### HIGH PRIORITY - Core Business Data

1. **SmartPipelineStageSelector** (NEW)
   - Replaces: Stage selection in ConsultationStatusDialog
   - Hook: `usePipelineStages()`
   - Features: Simple select with data fetching

2. **SmartConsultationStatusSelector** (NEW)
   - Replaces: Status selection in ConsultationDialog, EditConsultationDialog
   - Hook: `useConsultationStatuses()` or `useAllowedNextStatuses()`
   - Features: State-aware status filtering, outcome type grouping

3. **SmartUnitSelector** (NEW)
   - Replaces: Unit/organization selection in UnitDialog, MajorProgramDialog, DistributionRuleDialog
   - Hook: `useOrganizationUnits()` with `flattenOrganizationTree()`
   - Features: Hierarchical display, circular dependency validation, duplicate checking

4. **SmartOfficerSelector** (NEW)
   - Replaces: Officer selection in AssignLeadDialog
   - Hook: `useAdminUsersList()` with role filtering
   - Features: Shows user info (name + email), filters for officers/admins

### MEDIUM PRIORITY - Supporting Data

5. **SmartDegreeLevelSelector** (NEW)
   - Replaces: Degree level selection in MajorProgramDialog
   - Hook: `useDegreeLevels()`
   - Features: Simple select with active-only filtering

6. **SmartMajorProgramSelector** (NEW)
   - Replaces: Major program selection in LeadApplicationForm
   - Hook: `useMajorPrograms()`
   - Features: Unit-specific filtering, cascading dependency ready

7. **SmartOfferingSelector** (NEW)
   - Replaces: Offering selection in DistributionRuleDialog
   - Hook: Custom extraction from units + grouping by degree level
   - Features: Grouped display, hierarchical presentation

8. **SmartDiscountPoliciesMultiSelector** (NEW)
   - Replaces: Discount policy selection in OfferingAcademicInfoDialog
   - Hook: `useTuitionDiscountPolicies()`
   - Features: Multi-select with checkbox, shows policy details (code, type, discount amount)

9. **SmartOutcomeTypeSelector** (REFACTOR)
   - Replaces: Hardcoded outcome_type selection in ConsultationStatusDialog
   - Features: Enum-based, with visual indicators (color dots)

10. **SmartColorPicker** (NEW)
    - Replaces: PRESET_COLORS in ConsultationStatusDialog
    - Features: Grid of preset colors, hex input validation

### LOW PRIORITY - Secondary Data

11. **SmartRoleSelector** (NEW)
    - Replaces: Hardcoded AVAILABLE_ROLES in FeaturePolicyTab
    - Hook: `useRoles()` (already dynamic in ManageRolesDialog)
    - Features: Dynamic role list fetching, role display formatting

12. **SmartLeadStatusSelector** (NEW)
    - Replaces: Hardcoded STATUS_OPTIONS in LeadFilters
    - Hook: Could be centralized enum or hook
    - Features: Color-coded display, multi-select capability

13. **SmartLeadSourceSelector** (NEW)
    - Replaces: Hardcoded SOURCE_OPTIONS in LeadFilters
    - Hook: Could be centralized enum or hook
    - Features: Multi-select with all source types

14. **SmartParentUnitSelector** (REFACTOR)
    - Special case of SmartUnitSelector for self-reference validation
    - Includes: Circular dependency detection, duplicate name validation

---

## 5. SUMMARY TABLE

| File | Lines | Type | Selector Count | Candidates | Smart Factor |
|------|-------|------|----------------|------------|--------------|
| OfferingAcademicInfoDialog.tsx | 483-547 | Discount Policies | 1 | YES | HIGH |
| MajorProgramDialog.tsx | 250-366 | Degree Level, Unit | 2 | YES (2) | MEDIUM |
| UnitDialog.tsx | 56-127 | Parent Unit | 1 | YES | MEDIUM-HIGH |
| ConsultationStatusDialog.tsx | Various | Stage, Outcome, Legacy | 3 | YES (3) | MEDIUM |
| FeaturePolicyTab.tsx | 44-49 | Role | 1 | YES | LOW |
| PermissionSimulatorTab.tsx | 24 | Policy Suggestion | 1 | NO (good pattern) | HIGH |
| DistributionRuleDialog.tsx | 249-337 | Offering, Unit | 2 | YES (2) | MEDIUM-HIGH |
| ManageRolesDialog.tsx | 53-59 | Role | 1 | NO (good pattern) | HIGH |
| LeadApplicationForm.tsx | Various | Major Program, Offering, Criteria | 3 | YES (3) | MEDIUM |
| AssignLeadDialog.tsx | 162-190 | Officer | 1 | YES | MEDIUM |
| ConsultationDialog.tsx | Various | Status | 1 | YES | MEDIUM |
| EditConsultationDialog.tsx | Various | Status | 1 | YES | MEDIUM |
| LeadFilters.tsx | 42-61 | Lead Status, Source | 0 | YES (enum) | LOW |
| QuickDisposition.tsx | 31-39 | Consultation Status | 0 | YES (config) | MEDIUM |
| DocumentTypesSelector.tsx | - | Document Type | - | NO (existing) | EXCELLENT |

---

## 6. RECOMMENDATIONS

### Immediate Actions (Week 1)

1. ✅ Create `/components/common/selectors/` directory structure
2. ✅ Create `SmartUnitSelector.tsx` - Most reused pattern
3. ✅ Create `SmartConsultationStatusSelector.tsx` - Core business logic
4. ✅ Create `SmartOfferingSelector.tsx` - Complex hierarchical logic
5. ✅ Create centralized enum constants file for Lead/Consultation enums

### Short-term (Week 2-3)

1. Create remaining high-priority smart selectors (5 components)
2. Create selector configuration/constants file
3. Refactor existing hardcoded arrays to use constants
4. Update ConsultationStatusDialog to use new selectors
5. Update DistributionRuleDialog to use new selectors

### Medium-term (Week 3-4)

1. Migrate remaining medium-priority selectors
2. Create documentation and examples
3. Create composition patterns for cascading selectors
4. Test edge cases (loading, error, disabled states)

### Long-term (Ongoing)

1. Monitor for new select usage patterns
2. Maintain consistency across codebase
3. Consider building selection state management utility
4. Track reuse metrics to validate standardization benefits

---

## 7. DETAILED COMPONENT RECOMMENDATIONS

### 1. SmartUnitSelector (HIGHEST PRIORITY)

**Used by:** UnitDialog, MajorProgramDialog, DistributionRuleDialog (3 places)

**Implementation:**
```typescript
interface SmartUnitSelectorProps {
  value: string | number | null;
  onChange: (unitId: string | number | null) => void;
  disabled?: boolean;
  excludeUnitIds?: number[]; // For parent selection
  validateCircularDependency?: boolean;
  showParentIndicator?: boolean;
}

- Fetches units via useOrganizationUnits()
- Flattens hierarchy with visual indentation
- Optional circular dependency validation
- Handles null for root selection
```

### 2. SmartConsultationStatusSelector (HIGH PRIORITY)

**Used by:** ConsultationDialog, EditConsultationDialog, and potentially other consultation flows

**Implementation:**
```typescript
interface SmartConsultationStatusSelectorProps {
  value: string;
  onChange: (statusId: string) => void;
  currentStatusId?: string; // For getting allowed next statuses
  disabled?: boolean;
  groupByOutcomeType?: boolean;
}

- Fetches via useConsultationStatuses() or useAllowedNextStatuses()
- Optional state-aware filtering (next statuses only)
- Optional visual grouping by outcome_type
- Shows color indicators from status.color_code
```

### 3. SmartDiscountPoliciesMultiSelector (HIGH PRIORITY)

**Used by:** OfferingAcademicInfoDialog (currently custom)

**Implementation:**
```typescript
interface SmartDiscountPoliciesMultiSelectorProps {
  value: number[];
  onChange: (policyIds: number[]) => void;
  disabled?: boolean;
}

- Already good implementation exists in DocumentTypesSelector pattern
- Reuse popover + checkbox pattern
- Show policy details (code, discount_type, discount_value)
```

### 4. SmartOfferingSelector (HIGH PRIORITY)

**Used by:** DistributionRuleDialog (complex grouping logic)

**Implementation:**
```typescript
interface SmartOfferingOptionProps {
  id: number;
  displayName: string;
  degreeLevel: string;
  majorName: string;
  offeringType: string;
}

interface SmartOfferingSelectorProps {
  value: string;
  onChange: (offeringId: string) => void;
  groupByDegreeLevel?: boolean;
  disabled?: boolean;
}

- Extracts offerings from organization tree
- Groups by degree level in SelectGroup
- Shows full path: "Degree > Major > Type"
```

### 5. SmartOfficerSelector (MEDIUM PRIORITY)

**Used by:** AssignLeadDialog (already good but can be extracted)

**Implementation:**
```typescript
interface SmartOfficerSelectorProps {
  value: string;
  onChange: (officerId: string) => void;
  disabled?: boolean;
  includeAdmins?: boolean;
  showContactInfo?: boolean;
}

- Filters users to officers/admins
- Shows full_name and email
- Uses useAdminUsersList()
```

---

## 8. EXISTING UI COMPONENTS

### Available Components:
- `/components/ui/select.tsx` - Standard Radix Select wrapper
- `/components/ui/combobox.tsx` - Basic combobox with suggestions

### Suggestion:
Consider creating intermediate "Smart" wrapper layer:
- `/components/common/smart-inputs/` - Higher-level abstractions
- These wrap both UI components + hooks + business logic
- Separate from `/components/ui/` which contains primitive components
