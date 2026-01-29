# Mobile Standardization Guide

> Chuẩn hóa thiết kế và phát triển cho thiết bị di động trong QLTS Frontend

**Ngày tạo**: 2025-01-28
**Trạng thái**: Draft
**Phiên bản**: 1.0

---

## Mục lục

1. [Tổng quan hiện trạng](#1-tổng-quan-hiện-trạng)
2. [Breakpoint System](#2-breakpoint-system)
3. [Touch Target Guidelines](#3-touch-target-guidelines)
4. [Component Patterns](#4-component-patterns)
5. [Layout Patterns](#5-layout-patterns)
6. [Navigation Patterns](#6-navigation-patterns)
7. [Form Patterns](#7-form-patterns)
8. [Data Display Patterns](#8-data-display-patterns)
9. [Performance Guidelines](#9-performance-guidelines)
10. [Implementation Checklist](#10-implementation-checklist)

---

## 1. Tổng quan hiện trạng

### 1.1 Đánh giá hiện tại

| Khía cạnh | Trạng thái | Độ phủ | Ghi chú |
|-----------|------------|--------|---------|
| Breakpoints | ✅ Đã cấu hình | 100% | Tailwind mặc định, tập trung lg |
| Responsive Classes | ✅ Sử dụng | ~80% | 80+ components, nhưng không nhất quán |
| Touch Interactions | ⚠️ Một phần | 40% | Bottom nav tốt, Kanban thiếu touch |
| Mobile Components | ✅ Có | 85% | Bottom nav, overlay, sidebar collapse |
| Viewport Meta | ✅ Đầy đủ | 100% | PWA + notch support |
| Mobile-First Design | ⚠️ Một phần | 50% | Chưa thực sự mobile-first |

### 1.2 Các vấn đề cần giải quyết

#### Nghiêm trọng (Critical)
1. **Kanban Board** (`PipelineColumn.tsx`): `w-80` cố định 320px, không hiển thị được trên mobile
2. **Dialog Modal** (`dialog.tsx`): `max-w-lg` cố định, không responsive
3. **Admin Tables**: Không có mobile card view

#### Cao (High)
4. **Sheet Drawer**: `w-3/4` quá hẹp trên điện thoại nhỏ (< 480px)
5. **Drag-and-Drop**: Sensor chưa tối ưu cho touch
6. **Form Inputs**: Một số form có input quá nhỏ trên mobile

#### Trung bình (Medium)
7. `maximumScale: 1` ngăn user zoom (vấn đề accessibility)
8. Không có swipe gestures cho navigation
9. Tables thiếu scroll indicators

---

## 2. Breakpoint System

### 2.1 Breakpoints chuẩn

```typescript
// tailwind.config.ts - Breakpoints hiện tại
screens: {
  'sm': '640px',   // Điện thoại ngang, tablet nhỏ
  'md': '768px',   // Tablet dọc
  'lg': '1024px',  // Tablet ngang, laptop nhỏ (CHÍNH)
  'xl': '1280px',  // Desktop
  '2xl': '1400px', // Desktop lớn
}
```

### 2.2 Breakpoint Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                         BREAKPOINT MAP                          │
├─────────┬───────────────┬───────────────────────────────────────┤
│ 0-639px │ Mobile        │ Single column, bottom nav, full-width │
│         │ (base)        │ dialogs, stacked forms                │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 640-767 │ Mobile Large  │ 2-column grids where appropriate,     │
│ (sm:)   │               │ slightly larger touch targets         │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 768-1023│ Tablet        │ Side-by-side layouts, larger dialogs, │
│ (md:)   │               │ show more table columns               │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 1024+   │ Desktop       │ Full sidebar, all features visible,   │
│ (lg:)   │               │ multi-column layouts                  │
└─────────┴───────────────┴───────────────────────────────────────┘
```

### 2.3 Quy tắc sử dụng (Mobile-First)

```tsx
// ✅ ĐÚNG: Mobile-first (base → larger screens)
<div className="p-4 md:p-6 lg:p-8">
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
<div className="flex flex-col md:flex-row">

// ❌ SAI: Desktop-first (phải override cho mobile)
<div className="p-8 sm:p-4"> // Confusing!
<div className="hidden sm:block"> // Prefer: "block sm:hidden" for mobile-only
```

---

## 3. Touch Target Guidelines

### 3.1 Kích thước tối thiểu

```
┌────────────────────────────────────────────────────────┐
│              TOUCH TARGET STANDARDS                     │
├─────────────────────┬──────────────────────────────────┤
│ Minimum Size        │ 44 x 44 px (iOS Human Interface) │
│ Recommended Size    │ 48 x 48 px (Material Design)     │
│ Spacing Between     │ 8px minimum                      │
│ Icon Button         │ min-h-[44px] min-w-[44px]        │
│ Text Button         │ min-h-[44px] px-4                │
└─────────────────────┴──────────────────────────────────┘
```

### 3.2 CSS Classes chuẩn

```tsx
// Touch target utility classes (thêm vào globals.css)
.touch-target {
  @apply min-h-[44px] min-w-[44px];
}

.touch-target-lg {
  @apply min-h-[48px] min-w-[48px];
}

// Sử dụng
<Button className="touch-target">Click me</Button>
<button className="touch-target-lg p-2">
  <Icon className="h-6 w-6" />
</button>
```

### 3.3 Ví dụ tốt từ codebase

```tsx
// MobileBottomNav.tsx - Touch target đúng chuẩn
<Link
  className={cn(
    "flex flex-col items-center justify-center",
    "min-w-[56px] min-h-[44px] px-2 py-1", // ✅ 44px height
    "rounded-lg transition-colors"
  )}
>
```

---

## 4. Component Patterns

### 4.1 Dialog/Modal

#### Vấn đề hiện tại
```tsx
// dialog.tsx - Không responsive
className="w-full max-w-lg" // 512px cố định
```

#### Đề xuất chuẩn hóa

```tsx
// Responsive Dialog Content
const DialogContent = React.forwardRef<...>(({ className, size = "default", ...props }) => {
  const sizeClasses = {
    sm: "max-w-sm",           // 384px
    default: "max-w-lg",      // 512px
    lg: "max-w-2xl",          // 672px
    xl: "max-w-4xl",          // 896px
    full: "max-w-[95vw] h-[90vh]", // Near full-screen
  };

  return (
    <DialogPrimitive.Content
      className={cn(
        "fixed left-[50%] top-[50%] z-50 w-full",
        "translate-x-[-50%] translate-y-[-50%]",
        // Mobile: full width with margin
        "mx-4 max-h-[85vh] overflow-y-auto",
        // Tablet+: centered with max-width
        "sm:mx-0",
        sizeClasses[size],
        // Rounded corners only on larger screens
        "rounded-lg sm:rounded-xl",
        className
      )}
      {...props}
    />
  );
});
```

### 4.2 Sheet/Drawer

#### Đề xuất cho mobile bottom sheet

```tsx
// Mobile-optimized Sheet
const sheetVariants = cva("", {
  variants: {
    side: {
      // Existing sides...
      bottom: cn(
        "inset-x-0 bottom-0",
        "h-auto max-h-[85vh]",
        "rounded-t-2xl",
        "data-[state=open]:slide-in-from-bottom",
        "safe-area-pb" // iPhone safe area
      ),
    },
  },
});

// Usage for mobile actions
<Sheet>
  <SheetTrigger asChild>
    <Button className="lg:hidden">Actions</Button>
  </SheetTrigger>
  <SheetContent side="bottom" className="lg:hidden">
    {/* Mobile action menu */}
  </SheetContent>
</Sheet>
```

### 4.3 Button Variants cho Mobile

```tsx
// Thêm mobile-specific variants
const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md font-medium transition-colors",
  {
    variants: {
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-10 px-6",
        icon: "h-9 w-9",
        // Mobile-optimized sizes
        "mobile-default": "h-11 px-4 py-2 min-h-[44px]",
        "mobile-lg": "h-12 px-6 min-h-[48px]",
        "mobile-icon": "h-11 w-11 min-h-[44px] min-w-[44px]",
      },
    },
  }
);
```

---

## 5. Layout Patterns

### 5.1 Main Content Area

```tsx
// DashboardLayout pattern
<main className={cn(
  // Base (mobile)
  "flex-1 overflow-y-auto",
  "p-3",                    // Compact padding on mobile
  "pb-20",                  // Space for bottom nav (64px + 16px)
  // Tablet
  "md:p-4",
  // Desktop
  "lg:p-6 lg:pb-6",         // No bottom nav padding needed
)}>
  {children}
</main>
```

### 5.2 Grid Layouts

```tsx
// Responsive grid patterns
const gridPatterns = {
  // Stats/KPI cards
  stats: "grid gap-3 grid-cols-2 lg:grid-cols-4",

  // Dashboard sections
  sections: "grid gap-4 md:grid-cols-2 lg:grid-cols-3",

  // Form fields
  formFields: "grid gap-4 sm:grid-cols-2",

  // Card list
  cardList: "grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
};

// Usage
<div className={gridPatterns.stats}>
  <StatCard />
  <StatCard />
  <StatCard />
  <StatCard />
</div>
```

### 5.3 Sidebar Behavior

```
┌─────────────────────────────────────────────────────────┐
│                 SIDEBAR STATES BY SCREEN                │
├─────────────┬───────────────────────────────────────────┤
│ < 1024px    │ Hidden by default, slide-in overlay       │
│ (Mobile)    │ Toggle via hamburger menu                 │
│             │ Full-height, 75% width max                │
├─────────────┼───────────────────────────────────────────┤
│ >= 1024px   │ Always visible                            │
│ (Desktop)   │ Collapsible to icon-only (72px)          │
│             │ Expanded width: 256px                     │
└─────────────┴───────────────────────────────────────────┘
```

---

## 6. Navigation Patterns

### 6.1 Mobile Bottom Navigation

```tsx
// Cấu trúc chuẩn - đã implement tốt
<nav className={cn(
  "fixed bottom-0 left-0 right-0 z-50",
  "bg-background border-t",
  "safe-area-pb",          // iPhone notch
  "lg:hidden"              // Hide on desktop
)}>
  <div className="flex items-center justify-around h-16 px-2">
    {/* Max 5 items */}
    {navItems.map(item => (
      <NavItem
        key={item.href}
        className="min-w-[56px] min-h-[44px]" // Touch target
      />
    ))}
  </div>
</nav>
```

### 6.2 Mobile Header Actions

```tsx
// Pattern cho header actions trên mobile
<header className="flex items-center justify-between px-4 h-14">
  {/* Left: Menu toggle (mobile) or Logo (desktop) */}
  <div className="flex items-center gap-2">
    <Button
      variant="ghost"
      size="icon"
      className="lg:hidden touch-target"
      onClick={toggleSidebar}
    >
      <Menu className="h-5 w-5" />
    </Button>
    <Logo className="hidden lg:block" />
  </div>

  {/* Right: Essential actions only on mobile */}
  <div className="flex items-center gap-1">
    {/* Notifications - always visible */}
    <NotificationButton className="touch-target" />

    {/* Search - icon on mobile, full on desktop */}
    <Button className="touch-target lg:hidden">
      <Search className="h-5 w-5" />
    </Button>
    <SearchInput className="hidden lg:flex w-64" />
  </div>
</header>
```

### 6.3 Swipe Gestures (Đề xuất)

```tsx
// Hook cho swipe navigation
import { useSwipeable } from 'react-swipeable';

function SwipeableContainer({ children, onSwipeLeft, onSwipeRight }) {
  const handlers = useSwipeable({
    onSwipedLeft: onSwipeLeft,
    onSwipedRight: onSwipeRight,
    trackMouse: false,
    trackTouch: true,
    delta: 50,              // Minimum swipe distance
    swipeDuration: 500,     // Max swipe time
    preventScrollOnSwipe: true,
  });

  return <div {...handlers}>{children}</div>;
}

// Usage in tabs/panels
<SwipeableContainer
  onSwipeLeft={() => setActiveTab(prev => Math.min(prev + 1, tabs.length - 1))}
  onSwipeRight={() => setActiveTab(prev => Math.max(prev - 1, 0))}
>
  <TabContent tab={activeTab} />
</SwipeableContainer>
```

---

## 7. Form Patterns

### 7.1 Input Sizing

```tsx
// Mobile-optimized input
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        "flex w-full rounded-md border bg-transparent",
        // Mobile: larger touch target
        "h-11 px-3 py-2 text-base",
        // Desktop: can be slightly smaller
        "md:h-10 md:text-sm",
        // Prevent zoom on iOS when focused
        "text-[16px] md:text-sm",
        className
      )}
      ref={ref}
      {...props}
    />
  )
);
```

### 7.2 Form Layout

```tsx
// Responsive form layout
<form className="space-y-4">
  {/* Single column on mobile, 2 columns on tablet+ */}
  <div className="grid gap-4 sm:grid-cols-2">
    <FormField name="firstName" />
    <FormField name="lastName" />
  </div>

  {/* Full width fields */}
  <FormField name="email" />

  {/* Actions: stacked on mobile, inline on desktop */}
  <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
    <Button variant="outline" className="w-full sm:w-auto">
      Cancel
    </Button>
    <Button className="w-full sm:w-auto">
      Submit
    </Button>
  </div>
</form>
```

### 7.3 Date/Time Pickers

```tsx
// Mobile-friendly date picker
<Popover>
  <PopoverTrigger asChild>
    <Button
      variant="outline"
      className={cn(
        "w-full justify-start text-left",
        "h-11 md:h-10",  // Taller on mobile
        "text-base md:text-sm"
      )}
    >
      <CalendarIcon className="mr-2 h-4 w-4" />
      {date ? format(date, "PPP") : "Pick a date"}
    </Button>
  </PopoverTrigger>
  <PopoverContent
    className="w-auto p-0"
    align="start"
    // Full width on mobile
    sideOffset={4}
  >
    <Calendar
      mode="single"
      selected={date}
      onSelect={setDate}
      className="rounded-md border"
    />
  </PopoverContent>
</Popover>
```

---

## 8. Data Display Patterns

### 8.1 Table → Card View Transformation

```tsx
// Responsive data table with card view
interface DataDisplayProps<T> {
  data: T[];
  columns: ColumnDef<T>[];
  mobileCardRender: (item: T) => React.ReactNode;
}

function ResponsiveDataDisplay<T>({ data, columns, mobileCardRender }: DataDisplayProps<T>) {
  return (
    <>
      {/* Mobile: Card view */}
      <div className="space-y-3 md:hidden">
        {data.map((item, i) => (
          <Card key={i} className="p-4">
            {mobileCardRender(item)}
          </Card>
        ))}
      </div>

      {/* Desktop: Table view */}
      <div className="hidden md:block">
        <DataTable columns={columns} data={data} />
      </div>
    </>
  );
}

// Usage
<ResponsiveDataDisplay
  data={leads}
  columns={leadColumns}
  mobileCardRender={(lead) => (
    <div className="space-y-2">
      <div className="flex justify-between">
        <span className="font-medium">{lead.name}</span>
        <Badge>{lead.status}</Badge>
      </div>
      <div className="text-sm text-muted-foreground">{lead.email}</div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline">Edit</Button>
        <Button size="sm">View</Button>
      </div>
    </div>
  )}
/>
```

### 8.2 Horizontal Scrollable Tables

```tsx
// Table with scroll indicators
<div className="relative">
  {/* Scroll shadow indicators */}
  <div className="pointer-events-none absolute inset-y-0 left-0 w-4 bg-gradient-to-r from-background to-transparent md:hidden" />
  <div className="pointer-events-none absolute inset-y-0 right-0 w-4 bg-gradient-to-l from-background to-transparent md:hidden" />

  {/* Scrollable container */}
  <div className="overflow-x-auto -mx-4 px-4 md:mx-0 md:px-0">
    <Table className="min-w-[600px]">
      {/* Table content */}
    </Table>
  </div>
</div>
```

### 8.3 Kanban Board Mobile

```tsx
// Mobile-friendly Kanban
function KanbanBoard({ columns }) {
  return (
    <div className={cn(
      // Mobile: horizontal scroll
      "flex gap-4 overflow-x-auto pb-4",
      "snap-x snap-mandatory",
      "-mx-4 px-4",
      // Desktop: no snap, normal scroll
      "lg:mx-0 lg:px-0 lg:snap-none"
    )}>
      {columns.map(column => (
        <div
          key={column.id}
          className={cn(
            // Mobile: full width, snap to column
            "flex-shrink-0 w-[85vw] snap-center",
            // Desktop: fixed width
            "lg:w-80 lg:snap-align-none"
          )}
        >
          <PipelineColumn column={column} />
        </div>
      ))}
    </div>
  );
}
```

---

## 9. Performance Guidelines

### 9.1 Image Optimization

```tsx
// Responsive images
import Image from 'next/image';

<Image
  src={src}
  alt={alt}
  // Responsive sizes
  sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
  // Priority for above-fold images
  priority={isAboveFold}
  // Lazy load for below-fold
  loading={isAboveFold ? "eager" : "lazy"}
  // Placeholder
  placeholder="blur"
  blurDataURL={blurDataUrl}
/>
```

### 9.2 Lazy Loading Components

```tsx
// Lazy load heavy components
import dynamic from 'next/dynamic';

// Chart components - heavy, lazy load
const Chart = dynamic(() => import('@/components/Chart'), {
  loading: () => <Skeleton className="h-[300px]" />,
  ssr: false, // Disable SSR for client-only components
});

// Modal content - load when needed
const HeavyModalContent = dynamic(
  () => import('./HeavyModalContent'),
  { loading: () => <Spinner /> }
);
```

### 9.3 Reduce Motion

```tsx
// Respect user's motion preferences
const prefersReducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// In Tailwind
<div className={cn(
  "transition-transform",
  "motion-reduce:transition-none"
)}>
```

---

## 10. Implementation Checklist

### 10.1 Quick Wins (< 2 giờ mỗi item)

- [ ] **Fix Dialog responsive**: Thêm `mx-4 max-h-[85vh]` cho mobile
- [ ] **Fix Sheet drawer width**: Thêm breakpoint `w-[85vw] sm:w-3/4`
- [ ] **Add scroll indicators**: Shadow gradients cho tables
- [ ] **Increase input height**: `h-11` trên mobile
- [ ] **Add touch-target class**: Utility class trong globals.css

### 10.2 Medium Effort (2-4 giờ mỗi item)

- [x] **Mobile card view**: Tạo ResponsiveDataDisplay component ✅
- [x] **Kanban horizontal scroll**: Thêm snap scrolling ✅ (đã có sẵn)
- [x] **Form responsive layout**: Tạo ResponsiveFormLayout components ✅
- [x] **Bottom sheet pattern**: Tạo MobileActionSheet component ✅

### 10.3 Strategic (1-2 ngày)

- [x] **Swipe gestures**: Implement react-swipeable cho navigation ✅
  - Created `useSwipeNavigation` hook
  - Created `SwipeableContainer`, `SwipeableTabs`, `DismissibleContainer` components
  - Applied to `LeadInfoTabs` for tab swiping on mobile
- [x] **Touch-optimized drag-drop**: Tune dnd-kit sensors ✅
  - Added `TouchSensor` with 250ms delay to prevent accidental drags
  - Added `KeyboardSensor` for accessibility
  - Configured activation constraints for touch vs pointer
- [x] **Mobile testing framework**: Setup Playwright mobile viewports ✅
  - Added comprehensive tests in `mobile-responsive.spec.ts`
  - Added desktop tests in `desktop-responsive.spec.ts`
  - 131 tests passing across Mobile_Chrome, Mobile_Safari, chromium, firefox, webkit
- [x] **Design tokens mobile**: Tạo CSS variables cho mobile-specific values ✅
  - Added touch target tokens (`--touch-target-min`, `--touch-target-recommended`)
  - Added safe area tokens (`--safe-area-*`)
  - Added mobile spacing, input, dialog tokens in `foundation.css`

---

## CSS Variables cho Mobile (Đề xuất thêm)

```css
/* globals.css */
:root {
  /* Touch targets */
  --touch-target-min: 44px;
  --touch-target-recommended: 48px;

  /* Mobile spacing */
  --spacing-mobile-page: 1rem;    /* 16px */
  --spacing-mobile-card: 0.75rem; /* 12px */

  /* Safe areas */
  --safe-area-top: env(safe-area-inset-top);
  --safe-area-bottom: env(safe-area-inset-bottom);
  --safe-area-left: env(safe-area-inset-left);
  --safe-area-right: env(safe-area-inset-right);

  /* Bottom nav height */
  --bottom-nav-height: 64px;
  --bottom-nav-height-safe: calc(64px + var(--safe-area-bottom));
}

/* Utility classes */
.safe-area-pt { padding-top: var(--safe-area-top); }
.safe-area-pb { padding-bottom: var(--safe-area-bottom); }
.safe-area-pl { padding-left: var(--safe-area-left); }
.safe-area-pr { padding-right: var(--safe-area-right); }

.touch-target {
  min-height: var(--touch-target-min);
  min-width: var(--touch-target-min);
}
```

---

## Tài liệu tham khảo

- [Apple Human Interface Guidelines - Touch Targets](https://developer.apple.com/design/human-interface-guidelines/inputs)
- [Material Design - Touch Targets](https://m3.material.io/foundations/interaction/states/overview)
- [WCAG 2.1 - Target Size](https://www.w3.org/WAI/WCAG21/Understanding/target-size.html)
- [Tailwind CSS Responsive Design](https://tailwindcss.com/docs/responsive-design)

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-01-28 | Initial draft based on codebase analysis |
