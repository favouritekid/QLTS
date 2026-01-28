# UX Standards Documentation

> **Version:** 1.1
> **Last Updated:** 2026-01-28
> **Scope:** Frontend UX patterns and guidelines
> **Compliance:** WCAG 2.1 Level AA

---

## MANDATORY COMPLIANCE

> **CRITICAL:** All UX patterns in this document are **MANDATORY** for all frontend development.
> Code that does not follow these standards will be rejected during code review.

### Required Reading
- This document (UX Standards)
- `DESIGN_SYSTEM.md` (Design tokens & accessibility)
- `docs/accessibility-audit-report.md` (Full accessibility audit)

---

## Table of Contents

1. [**Accessibility Standards (MANDATORY)**](#1-accessibility-standards-mandatory)
2. [Loading States](#2-loading-states)
3. [Empty States](#3-empty-states)
4. [Error Handling](#4-error-handling)
5. [Toast Notifications](#5-toast-notifications)
6. [Confirmation Dialogs](#6-confirmation-dialogs)
7. [Form Patterns](#7-form-patterns)
8. [Decision Trees](#8-decision-trees)

---

## 1. Accessibility Standards (MANDATORY)

> Every component and page MUST comply with WCAG 2.1 Level AA.

### 1.1 Checklist for Every Feature

Before submitting any PR, verify:

- [ ] All interactive elements keyboard accessible (Tab, Enter, Space, Escape)
- [ ] All icon buttons have `aria-label`
- [ ] Color contrast >= 4.5:1 for text
- [ ] Focus states visible on all interactive elements
- [ ] Form inputs have labels and error handling
- [ ] Images have alt text

### 1.2 Icon Button Rule

**MANDATORY:** Every icon-only button MUST have `aria-label`.

```tsx
// ❌ REJECTED - No accessible name
<Button size="icon">
  <Trash2 className="h-4 w-4" />
</Button>

// ❌ REJECTED - Tooltip is NOT an accessible name
<Tooltip>
  <TooltipTrigger asChild>
    <Button size="icon">
      <Edit className="h-4 w-4" />
    </Button>
  </TooltipTrigger>
  <TooltipContent>Edit</TooltipContent>
</Tooltip>

// ✅ APPROVED
<Button size="icon" aria-label="Xóa">
  <Trash2 className="h-4 w-4" />
</Button>

// ✅ APPROVED - aria-label WITH tooltip
<Tooltip>
  <TooltipTrigger asChild>
    <Button size="icon" aria-label="Chỉnh sửa">
      <Edit className="h-4 w-4" />
    </Button>
  </TooltipTrigger>
  <TooltipContent>Chỉnh sửa</TooltipContent>
</Tooltip>
```

### 1.3 Focus State Rule

**NEVER** remove focus outline without providing an alternative:

```tsx
// ❌ REJECTED - Removes focus indicator
className="outline-none"

// ✅ APPROVED - Replaces with ring
className="outline-none focus-visible:ring-2 focus-visible:ring-ring"

// ✅ APPROVED - Our components have this built-in
<Button /> // Already has focus-visible styles
<Input />  // Already has focus-visible styles
```

### 1.4 Color Contrast Rule

**NEVER** use colors that fail contrast requirements:

```tsx
// ❌ REJECTED - gray-500 is below 4.5:1 on white
className="text-gray-500"

// ✅ APPROVED - Use semantic tokens
className="text-muted-foreground" // Uses gray-600, 5.9:1 contrast
```

### 1.5 Expandable/Collapsible Elements

Add `aria-expanded` for toggle buttons:

```tsx
<Button
  aria-label={isExpanded ? "Thu gọn" : "Mở rộng"}
  aria-expanded={isExpanded}
>
  {isExpanded ? <ChevronDown /> : <ChevronRight />}
</Button>
```

### 1.6 Form Accessibility

All form inputs MUST have:
1. Associated label (`htmlFor`/`id`)
2. Error indication (`aria-invalid`)
3. Error description (`aria-describedby`)

```tsx
// Use FormInput which handles all of this:
<FormInput
  label="Email"
  error={errors.email?.message}
  {...register("email")}
/>
```

---

---

## 2. Loading States

### 2.1 When to Use What

| Scenario | Component | Example |
|----------|-----------|---------|
| Initial page load | `loading.tsx` + Skeleton | Route segments |
| Table data loading | `TableSkeleton` | Lead list |
| Card content loading | `CardSkeleton` | Dashboard |
| Button action | `Loader2` spinner | Form submit |
| Inline content | `Skeleton` primitive | Text/images |

### 2.2 Skeleton Loading (Content Areas)

Use skeletons when you know the structure of the content.

```tsx
import { Skeleton } from "@/components/ui/skeleton";
import { TableSkeleton, CardListSkeleton } from "@/components/ui/skeletons";

// Text skeleton
<Skeleton className="h-4 w-[200px]" />

// Card skeleton
<Skeleton className="h-10 w-full" />

// Table loading
<TableSkeleton rows={5} />

// Card grid loading
<CardListSkeleton count={3} />
```

### 2.3 Spinner Loading (Actions)

Use spinners for buttons and small actions.

```tsx
import { Loader2 } from "lucide-react";

// Standard button loading
<Button disabled={isLoading}>
  {isLoading ? (
    <>
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      Đang xử lý...
    </>
  ) : (
    "Lưu"
  )}
</Button>

// Icon-only button
<Button size="icon" disabled={isLoading}>
  {isLoading ? (
    <Loader2 className="h-4 w-4 animate-spin" />
  ) : (
    <Save className="h-4 w-4" />
  )}
</Button>
```

### 2.4 Loading Text Standards

| Action | Loading Text | Success Text |
|--------|--------------|--------------|
| Save | "Đang lưu..." | "Đã lưu" |
| Create | "Đang tạo..." | "Đã tạo" |
| Delete | "Đang xóa..." | "Đã xóa" |
| Submit | "Đang gửi..." | "Đã gửi" |
| Export | "Đang xuất..." | "Xuất thành công" |
| Generic | "Đang xử lý..." | "Hoàn tất" |

### 2.5 Route-level Loading (loading.tsx)

Every route segment should have a `loading.tsx`:

```tsx
// app/(dashboard)/leads/loading.tsx
import { TableSkeleton } from "@/components/ui/skeletons";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function LeadsLoading() {
  return (
    <div className="container mx-auto p-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-10 w-28" />
          </div>
        </CardHeader>
        <CardContent>
          <TableSkeleton rows={10} />
        </CardContent>
      </Card>
    </div>
  );
}
```

---

## 3. Empty States

### 3.1 Component Structure

```tsx
import { EmptyState } from "@/components/common/EmptyState";

<EmptyState
  icon={<FileX className="h-12 w-12" />}
  title="Chưa có dữ liệu"
  description="Mô tả ngắn về tại sao trống và làm gì tiếp theo"
  action={<Button>Tạo mới</Button>}
/>
```

### 3.2 Context-Aware Empty States

**When filters are active:**
```tsx
<EmptyState
  icon={<SearchX className="h-12 w-12" />}
  title="Không tìm thấy kết quả"
  description="Không có dữ liệu khớp với bộ lọc hiện tại"
  action={
    <Button variant="outline" onClick={onResetFilters}>
      <Filter className="mr-2 h-4 w-4" />
      Xóa bộ lọc
    </Button>
  }
/>
```

**When truly empty (no data exists):**
```tsx
<EmptyState
  icon={<Users className="h-12 w-12" />}
  title="Chưa có lead nào"
  description="Bắt đầu bằng cách tạo lead đầu tiên"
  action={
    <Button onClick={onCreate}>
      <Plus className="mr-2 h-4 w-4" />
      Tạo lead mới
    </Button>
  }
/>
```

### 3.3 Empty State Text Standards

| Context | Title | Description |
|---------|-------|-------------|
| No data | "Chưa có [item]" | "Bắt đầu bằng cách tạo [item] đầu tiên" |
| No search results | "Không tìm thấy [item]" | "Thử tìm kiếm với từ khóa khác" |
| No filter results | "Không có kết quả" | "Không có [item] khớp với bộ lọc" |
| Error state | "Có lỗi xảy ra" | "Vui lòng thử lại sau" |

### 3.4 Table Empty State

```tsx
<TableBody>
  {data.length === 0 ? (
    <TableRow>
      <TableCell colSpan={columns.length} className="h-32">
        <EmptyState
          icon={<Inbox className="h-10 w-10" />}
          title="Chưa có dữ liệu"
          description="Dữ liệu sẽ hiển thị ở đây"
          className="py-8"
        />
      </TableCell>
    </TableRow>
  ) : (
    // ... render rows
  )}
</TableBody>
```

---

## 4. Error Handling

### 4.1 Error Handling Strategy

| Error Type | Handler | UI |
|------------|---------|-----|
| Route-level crash | `error.tsx` | Error card + retry |
| API error (transient) | `toast.error()` | Toast notification |
| API error (blocking) | Inline `Alert` | Alert component |
| Form validation | `FormMessage` | Below input |
| 404 Not Found | `not-found.tsx` | Custom page |

### 4.2 Route Error Boundary (error.tsx)

```tsx
"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertTriangle } from "lucide-react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Error:", error);
  }, [error]);

  return (
    <div className="container mx-auto p-6">
      <Card className="max-w-2xl mx-auto">
        <CardHeader>
          <div className="flex items-center gap-4">
            <AlertTriangle className="h-10 w-10 text-destructive" />
            <CardTitle>Có lỗi xảy ra</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground">
            Đã xảy ra lỗi. Vui lòng thử lại.
          </p>

          {process.env.NODE_ENV === "development" && (
            <div className="bg-muted p-3 rounded-md">
              <code className="text-sm">{error.message}</code>
            </div>
          )}

          <div className="flex gap-3">
            <Button onClick={() => reset()}>Thử lại</Button>
            <Button variant="outline" onClick={() => window.location.reload()}>
              Tải lại trang
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

### 4.3 API Error Toast

```tsx
// In mutation onError
onError: (error) => {
  toast.error(error.message || "Có lỗi xảy ra. Vui lòng thử lại.");
}

// Or with try-catch
try {
  await api.post("/endpoint", data);
  toast.success("Thành công!");
} catch (error) {
  toast.error(error.message || "Có lỗi xảy ra");
}
```

### 4.4 Inline Error Alert

```tsx
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";

{isError && (
  <Alert variant="destructive">
    <AlertCircle className="h-4 w-4" />
    <AlertTitle>Lỗi</AlertTitle>
    <AlertDescription>
      {error.message || "Không thể tải dữ liệu"}
    </AlertDescription>
  </Alert>
)}
```

---

## 5. Toast Notifications

### 5.1 Toast Types

```tsx
import { toast } from "sonner";

// Success - Green
toast.success("Đã lưu thành công!");

// Error - Red
toast.error("Có lỗi xảy ra. Vui lòng thử lại.");

// Warning - Yellow
toast.warning("Cảnh báo: Hành động này không thể hoàn tác");

// Info - Blue
toast.info("Thông tin: Đang xử lý yêu cầu...");
```

### 5.2 Toast Message Templates

| Action | Success | Error |
|--------|---------|-------|
| Create | "Đã tạo [item] thành công" | "Không thể tạo [item]" |
| Update | "Đã cập nhật thành công" | "Không thể cập nhật" |
| Delete | "Đã xóa thành công" | "Không thể xóa" |
| Save | "Đã lưu thành công" | "Không thể lưu" |
| Export | "Xuất dữ liệu thành công" | "Xuất dữ liệu thất bại" |

### 5.3 Toast with Actions

```tsx
toast.info("Đang tải xuống...", {
  action: {
    label: "Hủy",
    onClick: () => cancelDownload(),
  },
});
```

### 5.4 Toast Duration

| Type | Duration | Use Case |
|------|----------|----------|
| Success | 3s (default) | Quick confirmation |
| Error | 5s | User needs to read |
| Warning | 4s | Medium attention |
| Info | 3s | Informational |

---

## 6. Confirmation Dialogs

### 6.1 Standard Component

```tsx
import { ConfirmDialog } from "@/components/common/modals/ConfirmDialog";

<ConfirmDialog
  open={isOpen}
  onOpenChange={setIsOpen}
  title="Xóa người dùng?"
  description="Hành động này không thể hoàn tác. Dữ liệu sẽ bị xóa vĩnh viễn."
  confirmText="Xóa"
  cancelText="Hủy"
  onConfirm={handleDelete}
  variant="destructive"
  isLoading={isDeleting}
/>
```

### 6.2 When to Use

| Action | Requires Confirm? | Variant |
|--------|-------------------|---------|
| Delete | Always | `destructive` |
| Bulk delete | Always | `destructive` |
| Cancel unsaved | Yes | `default` |
| Status change | Sometimes | `default` |
| Submit final | Sometimes | `default` |

### 6.3 Confirmation Text Standards

**Destructive Actions:**
```
Title: "Xóa [item]?"
Description: "Hành động này không thể hoàn tác. [Consequences]"
Confirm: "Xóa"
Cancel: "Hủy"
```

**Non-destructive Confirmations:**
```
Title: "Xác nhận [action]?"
Description: "[What will happen]"
Confirm: "Xác nhận"
Cancel: "Hủy"
```

---

## 7. Form Patterns

### 7.1 Form Structure

```tsx
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";

const form = useForm<FormValues>({
  resolver: zodResolver(formSchema),
  defaultValues: { ... },
});

<Form {...form}>
  <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
    <FormField
      control={form.control}
      name="fieldName"
      render={({ field }) => (
        <FormItem>
          <FormLabel>Label</FormLabel>
          <FormControl>
            <Input {...field} />
          </FormControl>
          <FormMessage /> {/* Auto shows validation errors */}
        </FormItem>
      )}
    />

    <Button type="submit" disabled={form.formState.isSubmitting}>
      {form.formState.isSubmitting ? (
        <>
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Đang lưu...
        </>
      ) : (
        "Lưu"
      )}
    </Button>
  </form>
</Form>
```

### 7.2 Validation Error Display

Errors are automatically shown via `FormMessage`:

```tsx
<FormField
  control={form.control}
  name="email"
  render={({ field }) => (
    <FormItem>
      <FormLabel>Email</FormLabel>
      <FormControl>
        <Input type="email" {...field} />
      </FormControl>
      <FormMessage /> {/* Shows "Email không hợp lệ" etc. */}
    </FormItem>
  )}
/>
```

### 7.3 Form Submit Flow

```
1. User clicks Submit
2. Button shows loading spinner
3. Validation runs (Zod)
   - If invalid: Show FormMessage errors
   - If valid: Continue
4. API call made
   - If success: toast.success() + redirect/close
   - If error: toast.error() + keep form open
5. Button returns to normal state
```

---

## 8. Decision Trees

### 8.1 Loading State Decision

```
Is it initial page load?
├── Yes → Use loading.tsx with Skeleton
└── No → Is it a content area?
    ├── Yes → Use Skeleton components
    └── No → Is it a button/action?
        ├── Yes → Use Loader2 spinner
        └── No → Use inline Skeleton
```

### 8.2 Empty State Decision

```
Is data array empty?
├── No → Render data normally
└── Yes → Are filters/search active?
    ├── Yes → Show "No results" + Reset filters
    └── No → Is this a new user/area?
        ├── Yes → Show "Get started" + Create action
        └── No → Show generic empty state
```

### 8.3 Error Handling Decision

```
Is it a route-level error?
├── Yes → Let error.tsx handle it
└── No → Is it blocking the UI?
    ├── Yes → Show inline Alert
    └── No → Is it actionable?
        ├── Yes → toast.error() with action
        └── No → toast.error() simple
```

---

## Quick Reference

### Import Paths

```tsx
// Loading
import { Skeleton } from "@/components/ui/skeleton";
import { TableSkeleton, CardListSkeleton } from "@/components/ui/skeletons";
import { Loader2 } from "lucide-react";

// Empty State
import { EmptyState } from "@/components/common/EmptyState";

// Error
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

// Toast
import { toast } from "sonner";

// Confirmation
import { ConfirmDialog } from "@/components/common/modals/ConfirmDialog";

// Form
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";
```

### Common Patterns Checklist

- [ ] Loading state for async operations
- [ ] Empty state for lists/tables
- [ ] Error handling for API calls
- [ ] Toast feedback for user actions
- [ ] Confirmation for destructive actions
- [ ] Form validation with clear messages
