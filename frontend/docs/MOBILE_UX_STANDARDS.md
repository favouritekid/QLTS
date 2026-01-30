# Mobile UX Standards - QLTS

## Tổng quan

Tài liệu này định nghĩa quy chuẩn mobile UX cho dự án QLTS, dựa trên:
- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)
- [Material Design 3](https://m3.material.io/)
- [shadcn/ui patterns](https://ui.shadcn.com/)
- Nghiên cứu về mobile-first design 2025

**Nguyên tắc cốt lõi:** *"Mobile-first, Touch-friendly, Native-feel"*

---

## 1. Nguyên tắc Thiết kế

### 1.1 Mobile-First Philosophy

```
Mobile → Tablet → Desktop
(Base)   (Enhance) (Extend)
```

- **Bắt đầu từ mobile**: Design cho màn hình nhỏ nhất trước
- **Progressive Enhancement**: Thêm features cho màn hình lớn
- **Content Priority**: Nội dung quan trọng nhất hiển thị đầu tiên

### 1.2 Thumb Zone Optimization

```
┌─────────────────────┐
│   ❌ Hard to reach  │  ← Avoid placing primary actions
├─────────────────────┤
│   ⚠️ Moderate       │  ← Secondary actions OK
├─────────────────────┤
│   ✅ Easy reach     │  ← Primary actions, navigation
└─────────────────────┘
      (Thumb zone)
```

**75% người dùng thao tác bằng một ngón tay cái** (Steven Hoober Research)

### 1.3 Core Principles

| Principle | Description | Example |
|-----------|-------------|---------|
| **Clarity** | UI rõ ràng, không rối | Tối đa 4-5 actions per screen |
| **Consistency** | Pattern giống nhau across app | MobileActionSheet cho tất cả card actions |
| **Efficiency** | Tối thiểu taps để hoàn thành | Max 2 taps từ home đến main features |
| **Feedback** | Phản hồi ngay lập tức | Loading states, haptic, transitions |

---

## 2. Touch Targets & Gestures

### 2.1 Minimum Touch Target

| Platform | Minimum Size | Recommended |
|----------|--------------|-------------|
| iOS (Apple HIG) | 44×44 pt | 48×48 pt |
| Android (MD3) | 48×48 dp | 56×56 dp |
| **QLTS Standard** | **44×44 px** | **48×48 px** |

```tsx
// ✅ CHUẨN
<Button className="min-h-[44px] min-w-[44px]">Action</Button>

// ✅ Icon button
<Button variant="ghost" size="icon" className="h-10 w-10">
  <Icon className="h-5 w-5" />
</Button>

// ❌ SAI - quá nhỏ
<button className="h-6 w-6">...</button>
```

### 2.2 Spacing Between Targets

```
[Button A]  ← 8px gap minimum →  [Button B]
```

- **Minimum gap**: `gap-2` (8px)
- **Recommended gap**: `gap-3` (12px)
- **Prevents**: "Fat finger" errors

### 2.3 Supported Gestures

| Gesture | Use Case | Component |
|---------|----------|-----------|
| **Tap** | Primary action | Buttons, Links, Cards |
| **Swipe down** | Dismiss sheet | MobileActionSheet, Drawer |
| **Swipe left/right** | Navigation | Tabs (future) |
| **Long press** | Secondary actions | Context menu (future) |
| **Pull to refresh** | Refresh data | List pages (future) |

### 2.4 Gesture Discoverability

```tsx
// ✅ Visual affordance for draggable
<div className="w-10 h-1 rounded-full bg-muted-foreground/30" />
// (Drag handle in MobileActionSheet)

// ✅ Scroll indicator
<div className="overflow-auto scrollbar-thin">
```

---

## 3. Responsive Breakpoints

### 3.1 Breakpoint System (Tailwind)

| Breakpoint | Width | Device Type | Layout |
|------------|-------|-------------|--------|
| Default | < 640px | Mobile portrait | Cards, Bottom nav |
| `sm` | ≥ 640px | Mobile landscape | Cards, Bottom nav |
| `md` | ≥ 768px | Tablet | Tables, Side nav |
| `lg` | ≥ 1024px | Desktop | Tables, Side nav |
| `xl` | ≥ 1280px | Large desktop | Full layout |

### 3.2 Layout Patterns

```tsx
// ✅ CHUẨN - Responsive switching
{/* Mobile: Cards */}
<div className="md:hidden">
  {items.map(item => <MobileCard key={item.id} />)}
</div>

{/* Desktop: Table */}
<div className="hidden md:block">
  <DataTable columns={columns} data={items} />
</div>
```

### 3.3 Navigation Pattern

| Viewport | Navigation |
|----------|------------|
| < 1024px (mobile/tablet) | Bottom Tab Bar |
| ≥ 1024px (desktop) | Side Sidebar |

---

## 4. Component Patterns

### 4.1 Action Menu Pattern

**Rule**: Trên mobile, LUÔN dùng `MobileActionSheet` thay vì `DropdownMenu`

```tsx
// ✅ Mobile: Bottom Sheet
<MobileActionSheet open={open} onOpenChange={setOpen}>
  <MobileActionSheet.Item icon={Edit} onClick={handleEdit}>
    Chỉnh sửa
  </MobileActionSheet.Item>
  <MobileActionSheet.Item icon={Trash2} variant="destructive">
    Xóa
  </MobileActionSheet.Item>
</MobileActionSheet>

// ✅ Desktop: Dropdown
<DropdownMenu>
  <DropdownMenuTrigger>
    <MoreVertical className="h-4 w-4" />
  </DropdownMenuTrigger>
  <DropdownMenuContent>
    <DropdownMenuItem>Chỉnh sửa</DropdownMenuItem>
    <DropdownMenuItem>Xóa</DropdownMenuItem>
  </DropdownMenuContent>
</DropdownMenu>
```

### 4.2 Dialog Pattern

**Rule**: Responsive Dialog - Drawer on mobile, Dialog on desktop

```tsx
// Pattern: Dialog + Drawer responsive
import { useMediaQuery } from "@/hooks/useMediaQuery";

function ResponsiveDialog({ open, onOpenChange, children }) {
  const isDesktop = useMediaQuery("(min-width: 768px)");

  if (isDesktop) {
    return <Dialog open={open} onOpenChange={onOpenChange}>{children}</Dialog>;
  }

  return <Drawer open={open} onOpenChange={onOpenChange}>{children}</Drawer>;
}
```

### 4.3 Card Pattern (BaseCard System)

Xem chi tiết: [BASECARD_STANDARDS.md](./BASECARD_STANDARDS.md)

```tsx
<BaseCard selected={isSelected} onSelect={handleSelect} showCheckbox>
  <CardHeader title="Name" badge={<Badge>Status</Badge>} />
  <CardBody>
    <CardField label="Email" value={email} />
  </CardBody>
  <CardMeta>
    <CardTime date={createdAt} format="relative" />
  </CardMeta>
  <CardActions>
    <MobileActionSheetTrigger />
  </CardActions>
</BaseCard>
```

### 4.4 Form Pattern

```tsx
// ✅ Mobile-optimized form
<form className="space-y-4">
  {/* Full width inputs on mobile */}
  <div className="space-y-2">
    <Label htmlFor="name">Họ tên</Label>
    <Input
      id="name"
      className="h-12" // Larger touch target
      autoComplete="name"
    />
  </div>

  {/* Stack buttons on mobile, inline on desktop */}
  <div className="flex flex-col sm:flex-row gap-2">
    <Button type="submit" className="w-full sm:w-auto">
      Lưu
    </Button>
    <Button type="button" variant="outline" className="w-full sm:w-auto">
      Hủy
    </Button>
  </div>
</form>
```

### 4.5 Filter Pattern

```tsx
// Mobile: Collapsible filters hoặc Bottom sheet
<div className="md:hidden">
  <Button onClick={() => setFiltersOpen(true)}>
    <Filter className="h-4 w-4 mr-2" />
    Bộ lọc
  </Button>
  <MobileActionSheet open={filtersOpen} onOpenChange={setFiltersOpen}>
    {/* Filter options */}
  </MobileActionSheet>
</div>

// Desktop: Inline filters
<div className="hidden md:flex gap-4">
  <Select>...</Select>
  <Input placeholder="Search..." />
</div>
```

---

## 5. Navigation

### 5.1 Bottom Navigation Bar

```
┌─────────────────────────────────────────┐
│  🏠      👥      🎓      🔔      👤    │
│ Home   Leads  Tuyển sinh  TB    Hồ sơ  │
└─────────────────────────────────────────┘
```

**Rules:**
- Max 5 items
- Icons + Labels
- Active state: color + background
- Badge for notifications
- Safe area bottom padding

### 5.2 Page Header Pattern

```tsx
// Mobile: Compact header
<div className="flex items-center justify-between p-4">
  <div>
    <h1 className="text-lg font-semibold">{title}</h1>
    <p className="text-sm text-muted-foreground hidden sm:block">{description}</p>
  </div>
  <Button size="sm">
    <Plus className="h-4 w-4 mr-1" />
    <span className="hidden sm:inline">Thêm mới</span>
  </Button>
</div>
```

### 5.3 Back Navigation

```tsx
// ✅ Always provide clear back navigation
<Button variant="ghost" onClick={() => router.back()}>
  <ChevronLeft className="h-4 w-4 mr-1" />
  Quay lại
</Button>
```

---

## 6. Typography & Spacing

### 6.1 Mobile Typography Scale

| Element | Class | Size | Use |
|---------|-------|------|-----|
| Page title | `text-lg font-semibold` | 18px | Page headers |
| Card title | `text-sm font-medium` | 14px | Card headers |
| Body text | `text-sm` | 14px | Primary content |
| Secondary | `text-xs text-muted-foreground` | 12px | Labels, timestamps |
| Caption | `text-[10px]` | 10px | Badges (sparingly) |

### 6.2 Spacing Scale

| Token | Value | Use |
|-------|-------|-----|
| `space-y-1` | 4px | Tight (within card sections) |
| `space-y-2` | 8px | Standard (between elements) |
| `space-y-4` | 16px | Loose (between cards) |
| `p-4` | 16px | Card padding |
| `px-4` | 16px | Page horizontal padding |
| `py-4` | 16px | Section vertical padding |

### 6.3 Content Width

```tsx
// ✅ Readable line length
<p className="max-w-prose">Long text content...</p>

// ✅ Full width on mobile, constrained on desktop
<div className="w-full max-w-md mx-auto">
```

---

## 7. Loading & Empty States

### 7.1 Skeleton Loading

```tsx
// ✅ Mobile card skeleton
function CardSkeleton() {
  return (
    <div className="p-4 border rounded-lg space-y-3">
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 w-10 rounded-full" />
        <div className="space-y-2 flex-1">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );
}
```

### 7.2 Empty State

```tsx
<div className="flex flex-col items-center justify-center py-12 px-4 text-center">
  <Icon className="h-12 w-12 text-muted-foreground/50 mb-4" />
  <h3 className="text-lg font-medium">No items found</h3>
  <p className="text-sm text-muted-foreground mt-1 max-w-xs">
    Description text here
  </p>
  <Button className="mt-4">
    <Plus className="h-4 w-4 mr-2" />
    Add item
  </Button>
</div>
```

### 7.3 Pull to Refresh (Future)

```tsx
// Pattern for future implementation
<PullToRefresh onRefresh={handleRefresh}>
  <List items={items} />
</PullToRefresh>
```

---

## 8. Performance

### 8.1 Image Optimization

```tsx
// ✅ Responsive images
<Image
  src={src}
  alt={alt}
  sizes="(max-width: 768px) 100vw, 50vw"
  loading="lazy"
  placeholder="blur"
/>
```

### 8.2 List Virtualization

```tsx
// For long lists (>50 items), consider virtualization
import { useVirtualizer } from "@tanstack/react-virtual";
```

### 8.3 Reduce Motion

```tsx
// Respect user preferences
<div className="transition-all motion-reduce:transition-none">
```

---

## 9. Accessibility

### 9.1 Touch Target Requirements

- Minimum 44×44px for all interactive elements
- 8px minimum gap between targets
- Focus visible styles for keyboard navigation

### 9.2 Screen Reader Support

```tsx
// ✅ Proper labeling
<Button aria-label="Mở menu hành động">
  <MoreVertical className="h-4 w-4" />
</Button>

// ✅ Live regions for updates
<div aria-live="polite" className="sr-only">
  {statusMessage}
</div>
```

### 9.3 Color Contrast

- Text on background: minimum 4.5:1 ratio
- Large text (18px+): minimum 3:1 ratio
- Use semantic colors from design system

---

## 10. Component Checklist

### New Mobile Component Checklist

- [ ] Touch targets ≥ 44×44px
- [ ] Uses `MobileActionSheet` for action menus
- [ ] Follows `BaseCard` structure for data cards
- [ ] Responsive typography scale
- [ ] Loading skeleton provided
- [ ] Empty state provided
- [ ] Safe area padding for notched devices
- [ ] Proper ARIA labels
- [ ] Works with bottom nav (no overlap)
- [ ] Tested on real mobile device

### Page Responsive Checklist

- [ ] `md:hidden` for mobile-only components
- [ ] `hidden md:block` for desktop-only components
- [ ] Bottom navigation visible on mobile
- [ ] No horizontal scroll
- [ ] Touch-friendly filter UI
- [ ] Card layout on mobile, table on desktop

---

## 11. Implementation Status

### Components Using MobileActionSheet ✅

| Component | File |
|-----------|------|
| MobileLeadCard | `components/leads/command-center/` |
| AdmissionCard | `admissions/_components/` |
| MobileUserCard | `admin/users/_components/` |
| MobileConfigCard | `admin/config/_components/` |
| MobilePolicyCard | `admin/tuition-discount/_components/` |
| MobileRuleCard | `admin/distribution/_components/` |
| MobileNotificationCard | `notifications/_components/` |
| MobileCategoryCard | `admin/config/_components/` |

### Pages with Responsive Layout ✅

| Page | Mobile View | Desktop View |
|------|-------------|--------------|
| /leads | Card list | DataTable |
| /admissions | Card list | DataTable |
| /admin/users | Card list | DataTable |
| /admin/config | Card list | Tables |
| /notifications | Card list | Table |
| /admin/distribution | Card list | DataTable |

### Future Improvements 🔮

- [ ] Pull-to-refresh for list pages
- [ ] Swipe gestures for card actions
- [ ] Bottom sheet for filters
- [ ] Haptic feedback on actions
- [ ] Offline support with service worker
- [ ] App-like transitions between pages

---

## Sources

- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)
- [Material Design 3 - Bottom Sheets](https://m3.material.io/components/bottom-sheets/guidelines)
- [shadcn/ui Drawer](https://ui.shadcn.com/docs/components/drawer)
- [Vaul - React Drawer](https://github.com/emilkowalski/vaul)
- [Mobile-First Design Guide 2025](https://www.mediamato.com/mobile-first-design-guide-2025-tips/)
- [Mobile App UI Best Practices 2025](https://nextnative.dev/blog/mobile-app-ui-design-best-practices)
