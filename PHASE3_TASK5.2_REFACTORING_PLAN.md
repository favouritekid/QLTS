# TASK 5.2: OfferingAcademicInfoDialog Split Plan

## Current State

**File:** `frontend/src/components/admin/organization/OfferingAcademicInfoDialog.tsx`
- **Size:** 664 lines
- **Complexity:** High (form management, validation, API conversion)

## Analysis

### Components Identified:

```
Current Structure (664 lines):
├── Form Types & Schemas (lines 43-115)
│   ├── AdmissionCriterionFormData interface
│   ├── admissionCriterionSchema (Zod)
│   └── academicInfoFormSchema (Zod with superRefine)
├── Props Interface (lines 121-128)
│   └── OfferingAcademicInfoDialogProps
├── Helper Functions (lines 134-170)
│   ├── convertApiToFormData() - API → Form
│   └── convertFormToApiData() - Form → API
└── Main Component (lines 174-664)
    ├── Form state management (react-hook-form)
    ├── Field arrays (admission criteria)
    ├── Submit logic
    └── UI rendering
```

## Proposed Refactoring

### New Structure:

```
frontend/src/components/admin/organization/OfferingAcademicInfo/
├── types.ts                          (30 lines)
│   ├── AdmissionCriterionFormData
│   ├── AcademicInfoFormValues
│   └── OfferingAcademicInfoDialogProps
│
├── schema.ts                         (80 lines)
│   ├── admissionCriterionSchema
│   └── academicInfoFormSchema (with validation)
│
├── helpers.ts                        (50 lines)
│   ├── convertApiToFormData()
│   └── convertFormToApiData()
│
├── AdmissionCriteriaList.tsx         (150 lines)
│   ├── Field array rendering
│   ├── Add/remove criterion logic
│   └── Individual criterion form fields
│
├── useOfferingAcademicInfoForm.ts    (200 lines)
│   ├── Form initialization
│   ├── Submit handler
│   ├── Field array management
│   └── API mutation hooks
│
├── OfferingAcademicInfoDialog.tsx    (180 lines)
│   └── Container component using hook + child components
│
└── index.ts                          (Barrel exports)
```

## Estimated Effort

- **Time Required:** 5 hours
- **Files Created:** 7 files
- **Lines Reduction:** 664 → ~180 (main file) = 73% reduction
- **Complexity Reduction:** High → Medium

## Benefits

1. ✅ **Separation of Concerns**
   - Schema/validation logic separated from UI
   - Helper functions in dedicated module
   - Form logic in custom hook

2. ✅ **Reusability**
   - Schema can be reused in other contexts
   - Helpers can be used for other academic info dialogs
   - AdmissionCriteriaList can be used standalone

3. ✅ **Testability**
   - Each module can be tested independently
   - Schema validation tests
   - Helper function tests
   - Component unit tests

4. ✅ **Maintainability**
   - Smaller, focused files
   - Clear module boundaries
   - Easier to understand and modify

## Implementation Steps

### Step 1: Create types.ts (0.5h)
```typescript
// types.ts
export interface AdmissionCriterionFormData {
  id: string;
  method_name: string;
  program_type?: string;
  subject_groups?: string;
  min_score?: number | null;
}

export interface OfferingAcademicInfoDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  offeringId: number;
  existingInfo?: OfferingAcademicInfo;
}
```

### Step 2: Extract schema.ts (1h)
```typescript
// schema.ts
import * as z from "zod";

export const admissionCriterionSchema = z.object({
  id: z.string().min(1, "Mã phương thức là bắt buộc"),
  method_name: z.string().min(1, "Tên phương thức là bắt buộc"),
  // ... rest of schema
});

export const academicInfoFormSchema = z.object({
  academic_year: z.number().int().min(2000).max(2100),
  // ... with superRefine for duplicate validation
});
```

### Step 3: Extract helpers.ts (0.5h)
```typescript
// helpers.ts
export function convertApiToFormData(
  apiCriteria: AdmissionCriterion[]
): AdmissionCriterionFormData[] {
  return apiCriteria.map((c) => ({
    id: c.id,
    method_name: c.method_name,
    subject_groups: c.subject_groups?.join(", ") || "",
    // ... rest of conversion
  }));
}

export function convertFormToApiData(
  formCriteria: AdmissionCriterionFormData[]
): AdmissionCriterion[] {
  return formCriteria.map((c) => ({
    id: c.id,
    method_name: c.method_name,
    subject_groups: c.subject_groups?.split(",").map(s => s.trim()).filter(Boolean),
    // ... rest of conversion
  }));
}
```

### Step 4: Extract AdmissionCriteriaList.tsx (1.5h)
```typescript
// AdmissionCriteriaList.tsx
interface AdmissionCriteriaListProps {
  fields: any[];
  control: Control;
  onAdd: () => void;
  onRemove: (index: number) => void;
}

export function AdmissionCriteriaList({
  fields,
  control,
  onAdd,
  onRemove
}: AdmissionCriteriaListProps) {
  return (
    <div className="space-y-4">
      {fields.map((field, index) => (
        <Card key={field.id}>
          {/* Render form fields for each criterion */}
        </Card>
      ))}
      <Button onClick={onAdd}>Add Criterion</Button>
    </div>
  );
}
```

### Step 5: Extract useOfferingAcademicInfoForm.ts (1.5h)
```typescript
// useOfferingAcademicInfoForm.ts
export function useOfferingAcademicInfoForm(
  existingInfo?: OfferingAcademicInfo
) {
  const form = useForm({
    resolver: zodResolver(academicInfoFormSchema),
    defaultValues: { /* ... */ },
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "admission_criteria",
  });

  const createMutation = useCreateOfferingAcademicInfo();
  const updateMutation = useUpdateOfferingAcademicInfo();

  const handleSubmit = async (values: AcademicInfoFormValues) => {
    // Submit logic
  };

  return {
    form,
    fields,
    append,
    remove,
    handleSubmit,
    isSubmitting: createMutation.isPending || updateMutation.isPending,
  };
}
```

### Step 6: Refactor main dialog (1h)
```typescript
// OfferingAcademicInfoDialog.tsx (NEW - 180 lines)
export function OfferingAcademicInfoDialog({
  open,
  onOpenChange,
  offeringId,
  existingInfo,
}: OfferingAcademicInfoDialogProps) {
  const {
    form,
    fields,
    append,
    remove,
    handleSubmit,
    isSubmitting,
  } = useOfferingAcademicInfoForm(existingInfo);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <Form {...form}>
          {/* Basic fields */}

          <AdmissionCriteriaList
            fields={fields}
            control={form.control}
            onAdd={() => append(defaultCriterion)}
            onRemove={remove}
          />

          <DialogFooter>
            <Button onClick={form.handleSubmit(handleSubmit)}>
              Save
            </Button>
          </DialogFooter>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
```

## Status

**Current Status:** PLANNED (not implemented)

**Reason for Deferral:**
- TASK 5.1 (RoleManagementWorkflowTab) successfully completed and demonstrates the refactoring pattern
- Backend tasks (5.3, 5.4, 5.5) are higher priority for system architecture
- This split follows the exact same pattern as TASK 5.1, so can be executed easily when needed

**When to Implement:**
- After PHASE 3 backend tasks are complete
- Or when OfferingAcademicInfoDialog needs significant modifications
- Or as part of PHASE 4 polish work

## Recommendation

✅ **Defer TASK 5.2 to focus on backend optimization (TASK 5.3-5.5)**

The pattern has been proven successful with TASK 5.1 (RoleManagementWorkflowTab), and this document provides a clear blueprint for implementation when needed.

Priority should be given to:
1. TASK 5.3: Move Model business logic to services
2. TASK 5.4: Replace asyncio.Lock with Redis locks
3. TASK 5.5: Add ESLint rules

These backend tasks have more immediate impact on system architecture and performance.
