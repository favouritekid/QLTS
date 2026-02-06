# Responsive Data Display Standards

## Overview

Quy chuẩn hiển thị dữ liệu dạng table/list trên các kích thước màn hình khác nhau.

---

## Classification

### Group A: Small Lists (≤50 items/page)

**Approach:** CSS-based dual render (`hidden md:block` / `md:hidden`)

**Screens:**
- Admin Users (10/page) ✅ **Updated**
- Notifications (20/page) ✅
- Login History (all items) ✅
- Sessions (all items) ✅
- Admin Config CRUDTable (5-20 items)

**Pattern:**
```tsx
{/* Desktop: Table */}
<div className="hidden md:block">
  <Table>...</Table>
</div>

{/* Mobile: Cards */}
<div className="md:hidden space-y-2">
  {items.map(item => <Card key={item.id} ... />)}
</div>
```

**Why CSS dual render:**
- Small datasets (≤50 items)
- SSR-safe, no JS detection needed
- Extra DOM nodes acceptable (~100 nodes max)
- No flash on hydration

---

### Group B: Medium Lists (~50-100 items/page)

**Approach:** Single render with `useMediaQuery`

**Screens:**
- Leads (50/page) ✅ **Already implemented**
- Admissions (20/page) ⚠️ CSS dual render OK for now

**Pattern:**
```tsx
const isMobile = useIsMobile();

// Loading skeleton matches final layout
if (isLoading) {
  return <Skeleton className={isMobile ? "h-20" : "h-12"} />
}

// Single render based on viewport
if (isMobile) {
  return <CardList items={items} />
}

return <Table items={items} />
```

**Why single render:**
- Larger datasets (50-100+ items)
- Prevents duplicate DOM nodes (100-200 nodes saved)
- Shared selection state naturally
- Better performance on low-end devices

**Trade-off:**
- Potential brief flash on hydration (SSR returns mobile-first)
- Mitigated by skeleton loading state

---

### Group C: Large Lists (>200 items)

**Approach:** Server-side pagination + consider virtualization

**Screens:**
- Audit Logs
- Deleted Items
- Pipeline (Kanban - special case)

**Pattern:**
- Keep server-side pagination
- Consider `@tanstack/react-virtual` for virtualization
- Implement when performance issues arise

---

## Implementation Checklist

### For Every Data Display Screen:

- [ ] **Mobile:** Card-based layout, no table
- [ ] **Desktop:** Table with all features (sort, select, actions)
- [ ] **Selection:** Shared `rowSelection` state for both views
- [ ] **Actions:** Same action menu component (dropdown on desktop, action sheet on mobile)
- [ ] **Loading:** Skeleton matches final layout for each viewport
- [ ] **Empty:** Empty state works for both views
- [ ] **Pagination:** Shared pagination state

### Code Quality:

- [ ] No nested scroll containers
- [ ] No horizontal scroll tables on mobile
- [ ] Use `getRowId` for TanStack Table with string IDs
- [ ] Type `rowSelection` as `RowSelectionState`

### Hydration Safety:

- [ ] `formatDistanceToNow` in client components only (after data fetch)
- [ ] Use `suppressHydrationWarning` only when needed
- [ ] Mobile-first SSR (useMediaQuery returns false initially)

---

## Changes Made

### AdminUsersClient.tsx

**Before:**
- Desktop-only table with horizontal scroll
- No mobile card view

**After:**
- Desktop: TanStack Table (unchanged)
- Mobile: UserCard components with same selection state
- CSS dual render pattern (Group A - 10 items/page)
- Shared `RowSelectionState` typed properly
- `getRowId` added for consistent selection

---

## Reference Implementation

### Best: LeadsTable.tsx (Group B Pattern)

```tsx
// Single render with useMediaQuery
const isMobile = useIsMobile();

if (isLoading) {
  return <Skeleton className={isMobile ? "h-20" : "h-12"} />
}

if (isMobile) {
  return (
    <div className="flex h-full flex-col">
      <MobileHeader />
      <MobileLeadList ... />
      <MobilePagination />
      <BulkActionsBar />
    </div>
  );
}

return (
  <div className="flex h-full flex-col">
    <TableToolbar />
    <Table ... />
    <Footer />
    <BulkActionsBar />
  </div>
);
```

### Good: AdmissionsClient.tsx (Group A Pattern)

```tsx
// CSS dual render
{/* Desktop */}
<div className="hidden md:block">
  <Table>...</Table>
</div>

{/* Mobile */}
<div className="md:hidden">
  {profiles.map(p => <AdmissionCard ... />)}
</div>
```

---

## When to Refactor

### From CSS dual render → single render:

1. Page size increases to 100+ items
2. Performance issues on mobile devices
3. Complex shared state between views

### From single render → virtualization:

1. 500+ items rendered at once
2. Scroll lag on mid-tier devices
3. Memory usage concerns
