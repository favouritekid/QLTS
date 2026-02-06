# UX Patterns Audit Report

> **Date:** 2026-01-28
> **Scope:** Frontend UX consistency audit
> **Status:** Completed

---

## Executive Summary

### Current State
The codebase has **good foundation** for UX patterns but needs **standardization** in several areas:

| Area | Status | Consistency |
|------|--------|-------------|
| Loading States | Partial | 70% |
| Empty States | Partial | 50% |
| Error Handling | Good | 80% |
| Toast Notifications | Good | 85% |
| Confirmation Dialogs | Duplicate | 60% |
| Form Validation | Good | 85% |

### Key Issues Found
1. **Two ConfirmDialog components** exist (duplication)
2. **Empty states** are inconsistent - some pages missing them
3. **Loading spinners** use different patterns
4. **No generic EmptyState** component - only `EmptyLeadsState`

---

## 1. Loading States Inventory

### 1.1 Skeleton Components

| Component | Location | Usage |
|-----------|----------|-------|
| `Skeleton` | `ui/skeleton.tsx` | Base primitive |
| `DashboardSkeleton` | `ui/skeletons.tsx` | Dashboard cards |
| `TableSkeleton` | `ui/skeletons.tsx` | Table rows |
| `FormSkeleton` | `ui/skeletons.tsx` | Form fields |
| `LeadCardSkeleton` | `ui/skeletons.tsx` | Lead cards |
| `CardListSkeleton` | `ui/skeletons.tsx` | Card grids |

### 1.2 Loading.tsx Files (Next.js App Router)

| Route | Has loading.tsx | Skeleton Type |
|-------|-----------------|---------------|
| `/dashboard` | Yes | Custom |
| `/leads` | Yes | TableSkeleton |
| `/leads/[id]` | No | - |
| `/admissions` | Yes | Custom |
| `/admissions/[id]` | Yes | Custom |
| `/admin/*` | Yes | Custom |

### 1.3 Spinner Usage Pattern

**Standard Pattern (Loader2):**
```tsx
// 53 files use this pattern
<Loader2 className="mr-2 h-4 w-4 animate-spin" />
```

**Files using spinner in buttons:** 53 files

### 1.4 Inconsistencies

| Issue | Current | Recommended |
|-------|---------|-------------|
| Spinner icon | `Loader2` only | Keep `Loader2` |
| Spinner size | `h-4 w-4` (mostly) | Standardize `h-4 w-4` |
| Animation class | `animate-spin` | Keep |
| Spinner position | `mr-2` in buttons | Standardize |

---

## 2. Empty States Inventory

### 2.1 Existing Components

| Component | Location | Context-aware? |
|-----------|----------|----------------|
| `EmptyLeadsState` | `leads/command-center/` | Yes (filters, search) |

### 2.2 Page Empty State Coverage

| Page | Has Empty State? | Style Consistent? |
|------|------------------|-------------------|
| Lead List | Yes | Yes (dedicated component) |
| Dashboard | Partial | Yes |
| Notifications | Yes | Inline |
| Admin Users | Yes | Inline |
| KPI Config | Yes | Inline |
| Admissions List | Yes | Inline |
| Login History | Yes | Inline |
| Audit Logs | Yes | Inline |

### 2.3 Empty State Patterns Found

**Pattern A - Dedicated Component (Best):**
```tsx
<EmptyLeadsState
  hasFilters={hasFilters}
  searchQuery={searchQuery}
  onResetFilters={handleReset}
  onCreateLead={handleCreate}
/>
```

**Pattern B - Inline in Table (Common):**
```tsx
{data.length === 0 && (
  <TableRow>
    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
      Chưa có dữ liệu
    </TableCell>
  </TableRow>
)}
```

**Pattern C - Card with Icon (Good):**
```tsx
<Card>
  <CardContent className="py-12">
    <div className="text-center text-muted-foreground">
      <Icon className="h-16 w-16 mx-auto mb-4 opacity-20" />
      <p>Chưa có dữ liệu</p>
      <p className="text-sm mt-2">Mô tả thêm...</p>
    </div>
  </CardContent>
</Card>
```

### 2.4 Inconsistencies

| Issue | Frequency | Impact |
|-------|-----------|--------|
| No icon in empty state | 40% of cases | Low |
| No action button | 60% of cases | Medium |
| Inconsistent text | 30% of cases | Low |
| No context (filters vs empty) | 70% of cases | Medium |

---

## 3. Error Handling Inventory

### 3.1 Error Boundary Files

| Route | error.tsx | Pattern |
|-------|-----------|---------|
| `/` (root) | Yes | Card + retry |
| `/(dashboard)` | Yes | Card + retry |
| `/leads` | Yes | Same pattern |
| `/admissions` | Yes | Same pattern |
| `/admissions/[id]` | Yes | Same pattern |
| `/notifications` | Yes | Same pattern |
| `/profile` | Yes | Same pattern |
| `/settings` | Yes | Same pattern |
| `/admin` | Yes | Same pattern |

**Consistency:** 100% - All use same pattern

### 3.2 API Error Handling

**Pattern - Toast for API errors:**
```tsx
// 65+ files handle API errors
toast.error("Có lỗi xảy ra")
toast.error(error.message)
```

**Pattern - Inline Alert (less common):**
```tsx
<Alert variant="destructive">
  <AlertDescription>{error.message}</AlertDescription>
</Alert>
```

### 3.3 Query Error States

| Pattern | Usage | Files |
|---------|-------|-------|
| `isError` check | React Query | 65 files |
| `catch` blocks | Manual fetch | 20+ files |
| Error boundaries | Route level | 9 files |

---

## 4. Toast/Notification Inventory

### 4.1 Toast Library

**Library:** `sonner` (via `toast` import)

### 4.2 Toast Usage by Type

| Type | Count | Example |
|------|-------|---------|
| `toast.success()` | 30+ | "Đã lưu thành công" |
| `toast.error()` | 25+ | "Có lỗi xảy ra" |
| `toast.info()` | 15+ | "Tính năng đang phát triển" |
| `toast.warning()` | 5+ | "Cảnh báo: ..." |

### 4.3 Toast Message Patterns

**Success Messages:**
- "Đã lưu thành công"
- "Đã tạo thành công"
- "Đã xóa thành công"
- "Xuất CSV thành công"

**Error Messages:**
- "Có lỗi xảy ra. Vui lòng thử lại."
- "Thiếu thông tin..."
- Error message from API

**Info Messages:**
- "Tính năng đang phát triển"
- "Đang xử lý..."

### 4.4 Consistency

| Aspect | Status |
|--------|--------|
| Language | 95% Vietnamese |
| Tone | Consistent |
| Success pattern | Consistent |
| Error pattern | 80% consistent |

---

## 5. Confirmation Dialogs Inventory

### 5.1 Components Found (DUPLICATION ISSUE)

| Component | Location | Features |
|-----------|----------|----------|
| `ConfirmDialog` | `common/modals/ConfirmDialog.tsx` | Full-featured, icons, variants |
| `ConfirmDialog` | `ui/confirm-dialog.tsx` | Simpler version |
| Direct `AlertDialog` | Various files | Inline usage |

### 5.2 Feature Comparison

| Feature | `common/modals/` | `ui/` |
|---------|------------------|-------|
| Loading state | Yes | Yes |
| Variant (destructive) | Yes | Yes |
| Custom icon | Yes | No |
| Show icon option | Yes | No |
| Async onConfirm | Yes (with try-catch) | Yes |
| Auto-close on success | Yes | No |

### 5.3 Usage Statistics

| Pattern | Files |
|---------|-------|
| `common/modals/ConfirmDialog` | 3 files |
| `ui/confirm-dialog` | 1 file |
| Direct `AlertDialog` | 20+ files |

### 5.4 Recommendation

**Keep:** `common/modals/ConfirmDialog.tsx` (more complete)
**Deprecate:** `ui/confirm-dialog.tsx`
**Migrate:** Direct AlertDialog usages where appropriate

---

## 6. Form Patterns Inventory

### 6.1 Form Libraries

| Library | Usage |
|---------|-------|
| `react-hook-form` | 35 files |
| `@hookform/resolvers` | 35 files |
| `zod` | Validation schemas |

### 6.2 Form Components

| Component | Location |
|-----------|----------|
| `Form` | `ui/form.tsx` |
| `FormField` | `ui/form.tsx` |
| `FormLabel` | `ui/form.tsx` |
| `FormControl` | `ui/form.tsx` |
| `FormMessage` | `ui/form.tsx` |
| `FormDescription` | `ui/form.tsx` |

### 6.3 Submit Button Patterns

**Standard Pattern:**
```tsx
<Button type="submit" disabled={isSubmitting}>
  {isSubmitting ? (
    <>
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      Đang lưu...
    </>
  ) : (
    "Lưu"
  )}
</Button>
```

**Consistency:** 90% follow this pattern

---

## 7. Navigation Patterns

### 7.1 Breadcrumbs

| Component | Location | Auto-generated? |
|-----------|----------|-----------------|
| `Breadcrumbs` | `common/Breadcrumbs.tsx` | Yes (from URL) |

**Usage:** Rendered in `Main.tsx` for all dashboard pages

### 7.2 Back Buttons

| Pattern | Usage |
|---------|-------|
| `router.back()` | Common |
| `PageHeader backButton` | Recommended |
| Custom back links | Some pages |

---

## 8. Inconsistencies Summary

### High Priority (Fix Now)

| Issue | Impact | Files Affected |
|-------|--------|----------------|
| Duplicate ConfirmDialog | Confusion | 24 files |
| No generic EmptyState | DRY violation | 20+ pages |

### Medium Priority (Standardize)

| Issue | Impact | Files Affected |
|-------|--------|----------------|
| Empty states missing context | UX | 15+ pages |
| Inline empty states vs component | Consistency | 20+ pages |
| Loading skeleton coverage | UX | 5+ routes |

### Low Priority (Nice to Have)

| Issue | Impact | Files Affected |
|-------|--------|----------------|
| Toast message consistency | Polish | 10+ files |
| Error message format | Polish | 5+ files |

---

## 9. Recommendations

### 9.1 Components to Create/Update

1. **EmptyState** - Generic reusable component
2. **PageLoading** - Full page spinner for non-skeleton cases
3. **ErrorCard** - Inline error display

### 9.2 Components to Consolidate

1. **ConfirmDialog** - Keep `common/modals/`, deprecate `ui/`

### 9.3 Patterns to Document

1. Loading state decision tree (skeleton vs spinner)
2. Empty state content guidelines
3. Toast message templates
4. Error handling flowchart

---

## 10. Next Steps

1. [ ] Create generic `EmptyState` component
2. [ ] Consolidate ConfirmDialog components
3. [ ] Add loading.tsx to missing routes
4. [ ] Create UX Standards documentation
5. [ ] Migrate pages to use standardized components
